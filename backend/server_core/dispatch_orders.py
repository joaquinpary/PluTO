"""The record of what each plugin sent to its board (DispatchOrder).

Plugins dispatch on their own now (plugins/_sdk/pluto_sdk/dispatcher.py) and
report every message through POST /api/dispatch-orders; this is where those
reports become rows the pointing error is measured against.
"""
from .models import DispatchOrder


def record_order(rotor, plugin, kind, t0_ms, t_sent_ms, points, reason=''):
    """Store one published message."""
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
