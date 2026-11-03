"""Turning an az/el trajectory into the batches a board has to execute.

The pure half of the dispatcher: reading what POST /transform returns, merging
it with whatever is already pending, cutting it where it leaves the rotor's
limits and planning the batches. Everything that can be tested without MQTT,
HTTP or threads lives here, next to dispatcher.py, which calls it.

The wire format it feeds is docs/contracts/coordinates-dto.md; section numbers
below refer to that document.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .dto import plan_batches, to_epoch_ms

logger = logging.getLogger(__name__)

# Why the antenna was told to stop: DispatchOrder.Reason on the server.
END = 'end'
LIMITS = 'limits'
EXPIRED = 'expired'
STOPPED = 'stopped'

# A HOLD acts on arrival (§6.6), so the one that ends a trajectory waits this
# long past the last point: a plugin that publishes one point at a time can run
# slightly late without the antenna stopping in the gap. Physically it changes
# nothing, because the board does not extrapolate and already sits on the last
# point (§6.7). A cut by the rotor limits gets no grace: there it must stop at
# the edge.
HOLD_GRACE_MS = 1500


@dataclass(frozen=True)
class RotorLimits:
    """The board a plugin drives and where it may look, as GET /api/plugin/rotor returns it."""
    device_id: str
    min_elevation_deg: float
    min_azimuth_deg: float = None
    max_azimuth_deg: float = None

    @classmethod
    def from_api(cls, document):
        return cls(
            device_id=document['device_id'],
            min_elevation_deg=float(document['min_elevation_deg']),
            min_azimuth_deg=_optional_float(document.get('min_azimuth_deg')),
            max_azimuth_deg=_optional_float(document.get('max_azimuth_deg')),
        )

    def azimuth_in_window(self, az_deg):
        if self.min_azimuth_deg is None or self.max_azimuth_deg is None:
            return True
        if self.min_azimuth_deg <= self.max_azimuth_deg:
            return self.min_azimuth_deg <= az_deg <= self.max_azimuth_deg
        # The window wraps through north: 300..60 means 300..360 plus 0..60.
        return az_deg >= self.min_azimuth_deg or az_deg <= self.max_azimuth_deg

    def point_in_bounds(self, az_deg, el_deg):
        """Whether a point may be sent to the board (RF-30.2)."""
        return el_deg >= self.min_elevation_deg and self.azimuth_in_window(az_deg)


def _optional_float(value):
    return None if value is None else float(value)


def _number(value):
    # bool is an int in Python, and True is not an angle.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _point_time(value):
    """The instant of one coordinate as epoch milliseconds, or None."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        # A timestamp without an offset is UTC, as everywhere else in PluTO.
        parsed = parsed.replace(tzinfo=timezone.utc)

    return to_epoch_ms(parsed)


def parse_polar(document):
    """What POST /transform returns -> [(t_ms, az_deg, el_deg)], or None.

    Only the three fields the board needs survive: the station is the one the
    plugin was launched with, and range does not travel in the DTO.

    Points that cannot be read are skipped rather than failing the trajectory,
    and two points claiming the same instant collapse into the last one: the
    same last-writer-wins rule merge_trajectory applies, and §6.5 requires the
    timestamps that reach the board to be strictly increasing.
    """
    if not isinstance(document, dict):
        logger.warning('Ignoring a polar trajectory that is not an object')
        return None

    coordinates = document.get('coordinates')
    if not isinstance(coordinates, list):
        logger.warning('Ignoring a polar trajectory without a list of coordinates')
        return None

    by_instant = {}
    for point in coordinates:
        if not isinstance(point, dict):
            continue
        t_ms = _point_time(point.get('timestamp'))
        az_deg = _number(point.get('az'))
        el_deg = _number(point.get('el'))
        if t_ms is None or az_deg is None or el_deg is None:
            continue
        by_instant[t_ms] = (t_ms, az_deg, el_deg)

    if not by_instant:
        logger.warning('Ignoring a polar trajectory without one usable point')
        return None

    return [by_instant[t_ms] for t_ms in sorted(by_instant)]


def merge_trajectory(pending, incoming):
    """The trajectory in effect once `incoming` arrives.

    Each plugin produces at its own granularity: file_tracker sends the whole
    list at once, tinygs a computed pass, and nothing stops a plugin from
    sending one point at a time. Merging by timestamp covers that whole range
    without a per-plugin setting: what arrives wins over the stretch of time it
    covers, and whatever was pending beyond that edge stays.

    Replacing outright instead would break the one-point-at-a-time case: every
    message would schedule its own end-of-trajectory HOLD, which would fire
    before the next point arrived and leave the antenna starting and stopping at
    each step.
    """
    if not incoming:
        return list(pending)

    edge = incoming[0][0]
    return [point for point in pending if point[0] < edge] + list(incoming)


def plan_for_rotor(limits, trajectory, now_ms):
    """Plan what to publish: (batches, hold_at_ms, reason), or None if unusable.

    Points whose instant already passed are dropped: moving to a position
    computed for several seconds ago is worse than not moving (§6.3). What is
    left is walked in order and cut at the first point outside the rotor's
    limits, keeping the prefix: one cut, not a filter per segment, which is what
    §9 describes and what a pass actually does.

    An empty result means there is nothing to track and the antenna should stop
    now. Otherwise the HOLD is scheduled for the cut instant, or for the end of
    the trajectory plus HOLD_GRACE_MS.
    """
    kept = []
    cut_at_ms = None
    for t_ms, az_deg, el_deg in trajectory:
        if t_ms <= now_ms:
            continue
        if not limits.point_in_bounds(az_deg, el_deg):
            cut_at_ms = t_ms
            break
        kept.append((t_ms, az_deg, el_deg))

    if not kept:
        return [], now_ms, (LIMITS if cut_at_ms is not None else EXPIRED)

    try:
        batches = plan_batches(kept)
    except ValueError as exc:
        # A trajectory the encoder refuses is a bug upstream, not a reason to
        # take the plugin down.
        logger.warning('Ignoring unusable trajectory: %s', exc)
        return None

    if cut_at_ms is not None:
        return batches, cut_at_ms, LIMITS

    return batches, kept[-1][0] + HOLD_GRACE_MS, END
