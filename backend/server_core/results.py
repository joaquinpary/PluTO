"""Thesis results; pass error is the board's err_cdeg, else position vs. order by t_sent_ms (KAN-67)."""
import math
from datetime import datetime, timedelta, timezone

from .device_state import measured_position, tracking_error
from .models import DispatchOrder, PluginData, RotorState
from .payloads import payload_value

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _from_epoch_ms(ms):
    return _EPOCH + timedelta(milliseconds=ms)


def to_epoch_ms(moment):
    # Copy of pluto_sdk.dto.to_epoch_ms; server_core doesn't import the SDK.
    return (moment - _EPOCH) // timedelta(milliseconds=1)


def sky_distance_cdeg(az1, el1, az2, el2):
    """Great-circle distance in centidegrees, same formula as the board's err_cdeg."""
    az1, el1, az2, el2 = (math.radians(value / 100) for value in (az1, el1, az2, el2))
    h = math.sin((el2 - el1) / 2) ** 2 + math.cos(el1) * math.cos(el2) * math.sin((az2 - az1) / 2) ** 2
    return round(math.degrees(2 * math.asin(math.sqrt(min(h, 1.0)))) * 100)


def target_at(order, t_ms):
    """(az_cdeg, el_cdeg) a BATCH commands at t_ms, interpolated like the board does."""
    points = [(order.t0_ms + dt_ms, az, el) for dt_ms, az, el in order.points]
    if t_ms <= points[0][0]:
        return points[0][1], points[0][2]

    for (t1, az1, el1), (t2, az2, el2) in zip(points, points[1:]):
        if t_ms <= t2:
            fraction = (t_ms - t1) / (t2 - t1)
            # Short way round: 35950 to 50 is +100, not -35900.
            d_az = (az2 - az1 + 18000) % 36000 - 18000
            return (az1 + fraction * d_az) % 36000, el1 + fraction * (el2 - el1)

    return points[-1][1], points[-1][2]


def split_passes(orders):
    """[(batches, hold)] for closed passes; open batches and lone HOLDs are skipped."""
    passes, batches = [], []
    for order in orders:
        if order.kind == DispatchOrder.Kind.BATCH:
            batches.append(order)
        elif batches:
            passes.append((batches, order))
            batches = []
    return passes


def _measured_errors(states):
    errors = []
    for state in states:
        error = tracking_error(state.payload)
        if measured_position(state.payload) is not None and error is not None:
            errors.append(error)
    return errors


def _commanded_errors(states, batches):
    by_sent = {order.t_sent_ms: order for order in batches}
    errors = []
    for state in states:
        batch = payload_value(state.payload, 'batch', dict) or {}
        order = by_sent.get(batch.get('t_sent_ms'))
        # A rejected batch isn't being executed.
        if order is None or state.batch_accepted is not True or state.az_cdeg is None or state.el_cdeg is None:
            continue
        # Board clock if synced; an unsynced board can't track anyway.
        az, el = target_at(order, to_epoch_ms(state.board_time or state.received_at))
        errors.append(sky_distance_cdeg(state.az_cdeg, state.el_cdeg, az, el))
    return errors


def pointing_error(rotor, start, end):
    """Pointing error per pass of `rotor` closed within [start, end)."""
    orders = (DispatchOrder.objects
              .filter(rotor=rotor, created_at__gte=start, created_at__lt=end)
              .order_by('t_sent_ms', 'pk'))

    result = []
    for batches, hold in split_passes(orders):
        pass_start = _from_epoch_ms(batches[0].t0_ms)
        pass_end = _from_epoch_ms(hold.t_sent_ms)
        states = list(RotorState.objects.filter(
            rotor=rotor, received_at__gte=pass_start, received_at__lte=pass_end,
        ).order_by('received_at', 'pk'))

        errors = _measured_errors(states)
        source = 'meas'
        if not errors:
            errors = _commanded_errors(states, batches)
            source = 'commanded'

        result.append({
            'start': pass_start,
            'end': pass_end,
            'source': source,
            'samples': len(errors),
            'mean_err_cdeg': round(sum(errors) / len(errors), 1) if errors else None,
            'max_err_cdeg': max(errors, default=None),
        })
    return result


def _mean(values):
    return round(sum(values) / len(values), 1) if values else None


def reception_by_day(plugin, start, end):
    """Rx packets, CRC errors and mean RSSI/SNR per UTC day, empty days included."""
    days = {}
    day = start.astimezone(timezone.utc).date()
    last = (end - timedelta(microseconds=1)).astimezone(timezone.utc).date()
    while day <= last:
        days[day] = {'packets': 0, 'crc_errors': 0, 'rssi': [], 'snr': []}
        day += timedelta(days=1)

    rows = (PluginData.objects
            .filter(plugin=plugin, message_type='rx', created_at__gte=start, created_at__lt=end)
            .values_list('created_at', 'payload'))
    for created_at, payload in rows:
        stats = days[created_at.astimezone(timezone.utc).date()]
        stats['packets'] += 1
        if payload_value(payload, 'crc_error', bool):
            stats['crc_errors'] += 1
        for key in ('rssi', 'snr'):
            value = payload_value(payload, key, (int, float))
            if value is not None:
                stats[key].append(value)

    return [
        {
            'date': day,
            'packets': stats['packets'],
            'crc_errors': stats['crc_errors'],
            'rssi_mean': _mean(stats['rssi']),
            'snr_mean': _mean(stats['snr']),
        }
        for day, stats in days.items()
    ]
