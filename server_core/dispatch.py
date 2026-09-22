"""Turning a polar trajectory into the batches the board has to execute.

The pure half of the mqtt_dispatch command: parsing what coord_transform
publishes, merging it with whatever is already pending for a rotor, cutting it
where it leaves the rotor's limits and planning the batches. Everything that can
be tested without MQTT or threads lives here, next to the command that calls it,
the same way device_state.py sits beside mqtt_ingest.

The wire format it feeds is docs/contracts/coordinates-dto.md; section numbers
below refer to that document.
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from .coord_dto import plan_batches, to_epoch_ms
from .models import DispatchOrder, PluginInstance

logger = logging.getLogger(__name__)

POLAR_TOPIC = 'plugin/+/coordinates/polar'

# A HOLD acts on arrival (§6.6), so the one that ends a trajectory waits this
# long past the last point: a plugin that publishes one point at a time can run
# slightly late without the antenna stopping in the gap. Physically it changes
# nothing, because the board does not extrapolate and already sits on the last
# point (§6.7). A cut by the rotor limits gets no grace: there it must stop at
# the edge.
HOLD_GRACE_MS = 1500


def parse_polar_topic(topic):
    """'plugin/<plugin_uuid>/coordinates/polar' -> plugin_uuid, or None."""
    parts = topic.split('/')
    if len(parts) != 4:
        return None

    namespace, plugin_id, section, leaf = parts
    if namespace != 'plugin' or section != 'coordinates' or leaf != 'polar':
        return None

    return plugin_id or None


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
        # Same rule as the ingester: a timestamp without an offset is UTC.
        parsed = parsed.replace(tzinfo=timezone.utc)

    return to_epoch_ms(parsed)


def parse_polar_payload(payload):
    """What coord_transform publishes -> [(t_ms, az_deg, el_deg)], or None.

    The payload is a PolarCoordinatesPayload: a station plus points carrying
    timestamp, az, el and range. Only the three fields the board needs survive —
    the station is the one the plugin was configured with and the dispatcher has
    nothing to add to it, and range does not travel in the DTO.

    Points that cannot be read are skipped rather than failing the message, and
    two points claiming the same instant collapse into the last one: the same
    last-writer-wins rule merge_trajectory applies, and §6.5 requires the
    timestamps that reach the board to be strictly increasing.
    """
    try:
        document = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning('Ignoring undecodable polar payload: %s', exc)
        return None

    if not isinstance(document, dict):
        logger.warning('Ignoring non-object polar payload')
        return None

    coordinates = document.get('coordinates')
    if not isinstance(coordinates, list):
        logger.warning('Ignoring polar payload without a list of coordinates')
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
        logger.warning('Ignoring polar payload: not one usable point in it')
        return None

    return [by_instant[t_ms] for t_ms in sorted(by_instant)]


def resolve_rotor(plugin_uuid):
    """(plugin, rotor) for the uuid in a topic, or None if there is nothing to drive."""
    try:
        parsed = uuid.UUID(plugin_uuid)
    except ValueError:
        logger.warning('Ignoring coordinates for %r: not a uuid', plugin_uuid)
        return None

    plugin = PluginInstance.objects.select_related('rotor').filter(plugin_uuid=parsed).first()
    if plugin is None:
        logger.warning('Ignoring coordinates for %s: no plugin instance with that uuid', plugin_uuid)
        return None

    if plugin.rotor is None:
        # Not an error: a plugin without a rotor assigned drives nothing yet.
        logger.info('Ignoring coordinates from %s: no rotor assigned', plugin.name)
        return None

    return plugin, plugin.rotor


def merge_trajectory(pending, incoming):
    """The trajectory in effect once `incoming` arrives.

    Each plugin publishes at its own granularity: file_tracker sends the whole
    list at once, tinygs will send a computed pass, and nothing stops a plugin
    from publishing one point at a time. Merging by timestamp covers that whole
    range without a per-plugin setting — what arrives wins over the stretch of
    time it covers, and whatever was pending beyond that edge stays.

    Replacing outright instead would break the one-point-at-a-time case: every
    message would schedule its own end-of-trajectory HOLD, which would fire
    before the next point arrived and leave the antenna starting and stopping at
    each step.
    """
    if not incoming:
        return list(pending)

    edge = incoming[0][0]
    return [point for point in pending if point[0] < edge] + list(incoming)


def plan_for_rotor(rotor, trajectory, now_ms):
    """Plan what to publish: (batches, hold_at_ms, reason), or None if unusable.

    Points whose instant already passed are dropped — moving to a position
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
        if not rotor.point_in_bounds(az_deg, el_deg):
            cut_at_ms = t_ms
            break
        kept.append((t_ms, az_deg, el_deg))

    if not kept:
        reason = DispatchOrder.Reason.LIMITS if cut_at_ms is not None else DispatchOrder.Reason.EXPIRED
        return [], now_ms, reason

    try:
        batches = plan_batches(kept)
    except ValueError as exc:
        # A trajectory the encoder refuses is a bug upstream, not a reason to
        # take the dispatcher down.
        logger.warning('Ignoring unusable trajectory: %s', exc)
        return None

    if cut_at_ms is not None:
        return batches, cut_at_ms, DispatchOrder.Reason.LIMITS

    return batches, kept[-1][0] + HOLD_GRACE_MS, DispatchOrder.Reason.END


def record_order(rotor, plugin, kind, t0_ms, t_sent_ms, points, reason=''):
    """Store one published message, so the pointing error can be measured later."""
    points = [list(point) for point in points]
    return DispatchOrder.objects.create(
        rotor=rotor,
        plugin=plugin,
        kind=kind,
        t0_ms=t0_ms,
        t_sent_ms=t_sent_ms,
        # A HOLD covers a single instant, so it ends where it starts.
        t_end_ms=t0_ms + (points[-1][0] if points else 0),
        points=points,
        reason=reason,
    )
