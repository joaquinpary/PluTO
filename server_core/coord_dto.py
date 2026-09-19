"""Encoder for the binary pointing payload sent to the ESP32.

The format is defined in docs/contracts/coordinates-dto.md; section numbers
below refer to that document. Everything here is pure: no MQTT and no database,
so the dispatcher that publishes on device/<device_id>/coordinates/polar only
has to call it.
"""
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MAGIC = 0x50
FLAG_HOLD = 0x01
MAX_POINTS = 16

# RNF-19.1 keeps a control payload under 64 bytes, which caps a batch at 5 points (§8).
BATCH_POINTS = 5

HEADER = struct.Struct('<BBBqq')
POINT = struct.Struct('<IHh')

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MAX_DT_MS = 0xFFFFFFFF


def to_epoch_ms(moment):
    """Epoch milliseconds of an aware datetime, computed without going through float."""
    if moment.tzinfo is None:
        raise ValueError('timestamps must be timezone-aware')
    return (moment - _EPOCH) // timedelta(milliseconds=1)


def az_to_cdeg(az_deg):
    """Azimuth in degrees to centidegrees in 0..35999.

    Rounding first and wrapping after matters: wrapping first turns any azimuth
    in [359.995, 360) into 36000, which is out of range (§7.1).
    """
    return round(az_deg * 100) % 36000


def el_to_cdeg(el_deg):
    """Elevation in degrees to centidegrees in -9000..9000."""
    value = round(el_deg * 100)
    if not -9000 <= value <= 9000:
        raise ValueError(f'elevation {el_deg} is outside -90..90 degrees')
    return value


def encode(t0_ms, t_sent_ms, points, flags=0):
    """Pack one message. points are (dt_ms, az_cdeg, el_cdeg) tuples.

    Raises ValueError for anything the board's decoder would reject (§6.1, §6.5),
    so a bad batch fails here instead of being published and silently dropped.
    """
    points = list(points)

    if flags & ~FLAG_HOLD:
        raise ValueError('reserved flag bits must be 0')
    if flags & FLAG_HOLD:
        if points:
            raise ValueError('a HOLD carries no points')
    elif not 1 <= len(points) <= MAX_POINTS:
        raise ValueError(f'a batch carries 1 to {MAX_POINTS} points, got {len(points)}')

    previous_dt = -1
    for dt_ms, az_cdeg, el_cdeg in points:
        if dt_ms <= previous_dt:
            raise ValueError('dt_ms must be strictly increasing')
        if dt_ms > _MAX_DT_MS:
            raise ValueError(f'dt_ms {dt_ms} does not fit in uint32')
        if not 0 <= az_cdeg <= 35999:
            raise ValueError(f'az_cdeg {az_cdeg} is outside 0..35999')
        if not -9000 <= el_cdeg <= 9000:
            raise ValueError(f'el_cdeg {el_cdeg} is outside -9000..9000')
        previous_dt = dt_ms

    header = HEADER.pack(MAGIC, flags, len(points), t0_ms, t_sent_ms)
    return header + b''.join(POINT.pack(*point) for point in points)


def encode_hold(t_sent_ms):
    """A HOLD: stop and drop whatever is pending (§6.6). t0_ms is ignored by the board."""
    return encode(t_sent_ms, t_sent_ms, [], flags=FLAG_HOLD)


@dataclass(frozen=True)
class Batch:
    """One planned message: when to publish it and what it carries."""
    send_at_ms: int
    t0_ms: int
    points: tuple  # (dt_ms, az_cdeg, el_cdeg)

    def encode(self, t_sent_ms):
        # t_sent_ms is taken at publish time, not planned: it is what measures latency.
        return encode(self.t0_ms, t_sent_ms, self.points)


def plan_batches(trajectory, batch_points=BATCH_POINTS, stride=2, lead_ms=2000):
    """Split a trajectory into overlapping batches, each due lead_ms before its first point (§10).

    trajectory is (t_ms, az_deg, el_deg) in time order, as coord_transform
    produces it. Each batch starts `stride` points after the previous one, at
    most halfway through it: since a new batch replaces what the board has
    pending (§6.7), the overlap duplicates nothing and only keeps the board
    supplied if one message is lost.
    """
    if not 1 <= batch_points <= MAX_POINTS:
        raise ValueError(f'batch_points must be 1..{MAX_POINTS}')
    if not 1 <= stride <= max(1, batch_points // 2):
        raise ValueError('stride must be at least 1 and at most half a batch')

    points = [(t_ms, az_to_cdeg(az_deg), el_to_cdeg(el_deg)) for t_ms, az_deg, el_deg in trajectory]
    if not points:
        raise ValueError('the trajectory has no points')
    if any(later[0] <= earlier[0] for earlier, later in zip(points, points[1:])):
        raise ValueError('trajectory timestamps must be strictly increasing')

    batches = []
    start = 0
    while True:
        window = points[start:start + batch_points]
        t0_ms = window[0][0]
        batches.append(Batch(
            send_at_ms=t0_ms - lead_ms,
            t0_ms=t0_ms,
            points=tuple((t_ms - t0_ms, az, el) for t_ms, az, el in window),
        ))
        if start + batch_points >= len(points):
            return batches
        start += stride
