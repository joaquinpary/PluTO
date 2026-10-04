import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from models import (
    CartesianCoordinatePoint,
    CoordinateFormat,
    CoordinateType,
    GeoCoordinatePoint,
    PolarCoordinatePoint,
    RawCoordinatesPayload,
    Station,
)

logger = logging.getLogger(__name__)

# Only ISO 8601 at the start of a line. Its digits would otherwise be read as
# the first coordinates, and an epoch number cannot be told apart from one.
_TIMESTAMP = re.compile(
    r'^\s*\[?\s*["\']?'
    r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)'
)


def parse_messy_line(line: str) -> Optional[Tuple[float, float, float]]:
    if not line.strip():
        return None

    pattern = r'[-+]?\d*[.,]?\d+'
    matches = re.findall(pattern, line)

    if len(matches) < 3:
        return None

    try:
        return (
            float(matches[0].replace(',', '.')),
            float(matches[1].replace(',', '.')),
            float(matches[2].replace(',', '.')),
        )
    except ValueError:
        return None


def split_timestamp(line: str) -> Tuple[Optional[datetime], str]:
    """Separate a leading ISO 8601 timestamp from the rest of the line."""
    match = _TIMESTAMP.match(line)
    if not match:
        return None, line

    raw = match.group(1).replace('Z', '+00:00')
    timestamp = datetime.fromisoformat(raw)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp, line[match.end():]


def schedule(timestamps: List[Optional[datetime]], now: datetime) -> List[datetime]:
    """When each point must be reached, starting now.

    A file with its own timestamps keeps their spacing but is shifted to start
    now: a recorded trajectory replayed at its original instants would be
    entirely in the past, and the dispatcher drops what is already over.
    Without timestamps the points go one second apart.
    """
    stamped = [timestamp is not None for timestamp in timestamps]
    if not any(stamped):
        return [now + timedelta(seconds=index) for index in range(len(timestamps))]
    if not all(stamped):
        raise ValueError("Either every line carries a timestamp or none does")

    for previous, current in zip(timestamps, timestamps[1:]):
        if current <= previous:
            raise ValueError(f"Timestamps must increase: {current.isoformat()} follows {previous.isoformat()}")

    first = timestamps[0]
    return [now + (timestamp - first) for timestamp in timestamps]


def build_payload_from_text(
    text: str, coord_type: str, coord_format: str, station: Station, now: datetime,
) -> RawCoordinatesPayload:
    normalized_format = CoordinateFormat(coord_format)

    timestamps = []
    values = []
    for line in text.strip().splitlines():
        timestamp, rest = split_timestamp(line)
        parsed = parse_messy_line(rest)
        if not parsed:
            continue
        timestamps.append(timestamp)
        values.append(parsed)

    if not values:
        raise ValueError("No valid coordinates could be parsed from the provided data")

    coordinates = []
    for point_time, parsed in zip(schedule(timestamps, now), values):
        if normalized_format == CoordinateFormat.GEO:
            coordinates.append(GeoCoordinatePoint(timestamp=point_time, lat=parsed[0], lon=parsed[1], alt=parsed[2]))
        elif normalized_format == CoordinateFormat.CARTESIAN:
            coordinates.append(CartesianCoordinatePoint(timestamp=point_time, x=parsed[0], y=parsed[1], z=parsed[2]))
        elif normalized_format == CoordinateFormat.POLAR:
            coordinates.append(PolarCoordinatePoint(timestamp=point_time, az=parsed[0], el=parsed[1], range=parsed[2]))

    logger.info("Parsed %s coordinate points.", len(coordinates))

    return RawCoordinatesPayload(
        type=CoordinateType(coord_type),
        coord_format=normalized_format,
        station=station,
        coordinates=coordinates,
    )
