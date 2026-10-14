"""Publishing each planned batch to the board at its own instant.

What mqtt_dispatch used to do for every rotor, now done by the plugin for the
one board it drives. pointing.py decides what to send; this module decides
when, and puts it on device/<device_id>/coordinates/polar (coordinates-dto.md).
Every message that goes out is also reported, so the server keeps the record
the pointing error is measured against.
"""
import logging
import threading
import time

from .dto import encode_hold
from .pointing import STOPPED, merge_trajectory, plan_for_rotor

logger = logging.getLogger(__name__)

BATCH = 'BATCH'
HOLD = 'HOLD'


def now_ms():
    """The wall clock in epoch milliseconds, the one both ends share over NTP."""
    return int(time.time() * 1000)


def board_topic(device_id):
    return f'device/{device_id}/coordinates/polar'


class Schedule:
    """What is pending for the board, and the single timer that drives it.

    One timer re-armed after each message instead of one per batch: a ten
    minute pass plans around three hundred batches, and that many live threads
    is a lot to reserve for something idle by definition. The next delay is
    always computed from the absolute clock, so a late wakeup never accumulates.
    """

    def __init__(self, limits, trajectory, batches, hold_at_ms, reason):
        self.limits = limits
        self.trajectory = trajectory
        self.batches = batches
        self.hold_at_ms = hold_at_ms
        self.reason = reason
        # Walks the batches and then stops on the HOLD, one past the last one.
        self.index = 0
        self.timer = None

    def next_due_ms(self):
        """When the next message is due, or None once the HOLD has gone out."""
        if self.index < len(self.batches):
            return self.batches[self.index].send_at_ms
        if self.index == len(self.batches):
            return self.hold_at_ms
        return None

    def cancel(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None


class Dispatcher:
    def __init__(self, publish, report, clock_ms=now_ms, timer_factory=threading.Timer):
        """publish(topic, payload) puts bytes on the broker; report(order) records them on the server."""
        self._publish = publish
        self._report = report
        self._clock_ms = clock_ms
        self._timer_factory = timer_factory
        # Covers the schedule, which the timer thread walks as it fires.
        self._lock = threading.Lock()
        self._schedule = None

    @property
    def schedule(self):
        return self._schedule

    def install(self, limits, incoming):
        """Merge a new trajectory into what is pending and re-arm. Returns whether anything was planned."""
        moment = self._clock_ms()

        with self._lock:
            previous, self._schedule = self._schedule, None
            if previous is not None:
                previous.cancel()

            pending = previous.trajectory if previous is not None else []
            # Points already in the past are dead weight, and dropping them is
            # what keeps the working set bounded when a plugin streams one point
            # at a time forever.
            trajectory = [point for point in merge_trajectory(pending, incoming) if point[0] > moment]

            planned = plan_for_rotor(limits, trajectory, moment)
            if planned is None:
                return False

            batches, hold_at_ms, reason = planned
            schedule = Schedule(limits, trajectory, batches, hold_at_ms, reason)
            self._schedule = schedule
            logger.info(
                'Planned %s batch(es) for %s, holding at %s (%s)',
                len(batches), limits.device_id, hold_at_ms, reason,
            )
            self._arm(schedule)
            return True

    def stop(self):
        """Cancel what is pending and stop the antenna, if it was being driven.

        Called when the plugin shuts down. Without it the board would still run
        out the points it already holds, a few seconds of a pass nobody follows
        any more; a HOLD makes it stop where it is (§6.6).
        """
        with self._lock:
            schedule, self._schedule = self._schedule, None
            if schedule is None:
                return
            schedule.cancel()
            self._send(schedule.limits.device_id, HOLD, reason=STOPPED)

    def _arm(self, schedule):
        """Arm the timer for the next message. Called holding the lock."""
        due_ms = schedule.next_due_ms()
        if due_ms is None:
            self._schedule = None
            return

        # A batch that is already due goes out now: file_tracker stamps its
        # points from now() when it parses the file, so the first ones
        # routinely arrive with no lead time left.
        delay = max(0.0, (due_ms - self._clock_ms()) / 1000)
        schedule.timer = self._timer_factory(delay, self._fire, args=(schedule,))
        schedule.timer.daemon = True
        schedule.timer.start()

    def _fire(self, schedule):
        try:
            with self._lock:
                # A trajectory that arrived while this timer was waiting replaces
                # the whole schedule; this one is then a ghost and must not publish.
                if self._schedule is not schedule:
                    return

                if schedule.index < len(schedule.batches):
                    self._send(schedule.limits.device_id, BATCH, batch=schedule.batches[schedule.index])
                else:
                    self._send(schedule.limits.device_id, HOLD, reason=schedule.reason)
                schedule.index += 1
                self._arm(schedule)
        except Exception:
            logger.exception('Unexpected error publishing for %s', schedule.limits.device_id)

    def _send(self, device_id, kind, batch=None, reason=''):
        # Taken at publish time, not planned: this is what measures the
        # transport latency against the board's clock (§3.3).
        t_sent_ms = self._clock_ms()
        if kind == BATCH:
            payload = batch.encode(t_sent_ms)
            t0_ms, points = batch.t0_ms, [list(point) for point in batch.points]
        else:
            payload = encode_hold(t_sent_ms)
            t0_ms, points = t_sent_ms, []

        # retain=False without exception (§2): a retained setpoint would be
        # handed to the board on every reconnect, aiming it at an instant that
        # has passed. The publish callable owns that and the QoS.
        self._publish(board_topic(device_id), payload)
        self._report({'kind': kind, 't0_ms': t0_ms, 't_sent_ms': t_sent_ms, 'points': points, 'reason': reason})

        if kind == HOLD:
            logger.info('[HOLD] %s reason=%s', device_id, reason)
        else:
            logger.info('[BATCH] %s points=%s t0_ms=%s bytes=%s', device_id, len(points), t0_ms, len(payload))
