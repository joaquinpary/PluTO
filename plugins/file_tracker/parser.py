import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

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


def build_payload_from_file(file_path: str, coord_type: str, coord_format: str, station: Station) -> RawCoordinatesPayload:
    if not file_path:
        raise ValueError("No FILE_PATH provided")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Input file not found: {file_path}")

    normalized_format = CoordinateFormat(coord_format)

    with open(file_path, "r", encoding="utf-8") as handle:
        raw_text = handle.read()

    lines = raw_text.strip().splitlines()
    logger.info("Read %s lines of raw data from %s.", len(lines), file_path)

    coordinates = []
    base_time = datetime.now(timezone.utc)

    for index, line in enumerate(lines):
        parsed = parse_messy_line(line)
        if not parsed:
            continue

        point_time = base_time + timedelta(seconds=index)
        if normalized_format == CoordinateFormat.GEO:
            coordinates.append(GeoCoordinatePoint(timestamp=point_time, lat=parsed[0], lon=parsed[1], alt=parsed[2]))
        elif normalized_format == CoordinateFormat.CARTESIAN:
            coordinates.append(CartesianCoordinatePoint(timestamp=point_time, x=parsed[0], y=parsed[1], z=parsed[2]))
        elif normalized_format == CoordinateFormat.POLAR:
            coordinates.append(PolarCoordinatePoint(timestamp=point_time, az=parsed[0], el=parsed[1], range=parsed[2]))

    if not coordinates:
        raise ValueError("No valid coordinates could be parsed from the provided data")

    logger.info("Successfully parsed %s coordinate points.", len(coordinates))

    return RawCoordinatesPayload(
        type=CoordinateType(coord_type),
        coord_format=normalized_format,
        station=station,
        coordinates=coordinates,
    )