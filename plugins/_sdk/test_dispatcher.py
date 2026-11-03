import unittest
from unittest.mock import MagicMock

from pluto_sdk.dispatcher import BATCH, HOLD, Dispatcher
from pluto_sdk.pointing import END, LIMITS, STOPPED, RotorLimits
from test_pointing import DEVICE_ID, NOW_MS, at, rising_pass

TOPIC = f'device/{DEVICE_ID}/coordinates/polar'


class FakeTimer:
    """Records what would be armed; the test fires it by hand."""
    armed = []

    def __init__(self, delay, function, args=()):
        self.delay, self.function, self.args = delay, function, args
        self.cancelled = False
        FakeTimer.armed.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args)


class DispatcherTestCase(unittest.TestCase):
    def setUp(self):
        FakeTimer.armed = []
        self.clock = [NOW_MS]
        self.published = []
        self.reported = []
        self.dispatcher = Dispatcher(
            publish=lambda topic, payload: self.published.append((topic, payload)),
            report=self.reported.append,
            clock_ms=lambda: self.clock[0],
            timer_factory=FakeTimer,
        )
        self.limits = RotorLimits(DEVICE_ID, min_elevation_deg=10.0)

    def fire_all(self):
        """Fire whatever is armed, as the clock would, until the schedule is done."""
        while self.dispatcher.schedule is not None:
            FakeTimer.armed[-1].fire()


class InstallTests(DispatcherTestCase):
    def test_a_trajectory_arms_one_timer_for_the_first_batch_lead_time(self):
        self.assertTrue(self.dispatcher.install(self.limits, rising_pass()))

        # First point 3 s out, published 2 s ahead of it.
        self.assertEqual(len(FakeTimer.armed), 1)
        self.assertAlmostEqual(FakeTimer.armed[0].delay, 1.0, places=3)

    def test_an_overdue_batch_goes_out_immediately(self):
        self.dispatcher.install(self.limits, [(at(500), 120.0, 30.0), (at(1500), 121.0, 31.0)])

        self.assertEqual(FakeTimer.armed[0].delay, 0.0)

    def test_one_point_at_a_time_accumulates_instead_of_replacing(self):
        for offset_ms in (3000, 4000, 5000):
            self.dispatcher.install(self.limits, [(at(offset_ms), 120.0, 30.0)])

        # With replace semantics this would be a single point, and the HOLD of
        # each message would fire before the next one arrived.
        self.assertEqual([point[0] for point in self.dispatcher.schedule.trajectory], [at(3000), at(4000), at(5000)])
        self.assertEqual(self.dispatcher.schedule.reason, END)
        self.assertEqual(self.published, [])

    def test_a_new_trajectory_cancels_what_was_armed(self):
        self.dispatcher.install(self.limits, rising_pass())
        first = FakeTimer.armed[0]

        self.dispatcher.install(self.limits, rising_pass())

        self.assertTrue(first.cancelled)

    def test_new_limits_apply_to_what_was_pending(self):
        self.dispatcher.install(self.limits, rising_pass())

        self.dispatcher.install(RotorLimits(DEVICE_ID, 10.0, min_azimuth_deg=0.0, max_azimuth_deg=122.5), [])

        # rising_pass turns one degree a second from 120: the window cuts it at the fourth point.
        self.assertEqual(self.dispatcher.schedule.reason, LIMITS)
        self.assertEqual(self.dispatcher.schedule.hold_at_ms, at(6000))

    def test_an_unusable_trajectory_plans_nothing(self):
        with self.assertLogs('pluto_sdk.pointing', level='WARNING'):
            self.assertFalse(self.dispatcher.install(self.limits, [(at(3000), 120.0, 95.0)]))

        self.assertIsNone(self.dispatcher.schedule)


class PublishingTests(DispatcherTestCase):
    def setUp(self):
        super().setUp()
        self.dispatcher.install(self.limits, rising_pass(count=3))

    def test_a_batch_goes_out_on_the_board_topic(self):
        FakeTimer.armed[-1].fire()

        topic, payload = self.published[0]
        self.assertEqual(topic, TOPIC)
        self.assertEqual(payload[0], 0x50)

    def test_every_message_is_reported_with_what_went_on_the_wire(self):
        FakeTimer.armed[-1].fire()

        order = self.reported[0]
        self.assertEqual((order['kind'], order['t0_ms'], order['t_sent_ms'], order['reason']),
                         (BATCH, at(3000), NOW_MS, ''))
        self.assertEqual(order['points'][0], [0, 12000, 2000])

    def test_the_last_message_of_a_trajectory_is_a_hold(self):
        self.fire_all()

        hold = self.reported[-1]
        self.assertEqual((hold['kind'], hold['points'], hold['reason']), (HOLD, [], END))
        self.assertEqual(hold['t0_ms'], hold['t_sent_ms'])
        self.assertEqual(len(self.published[-1][1]), 19)

    def test_the_schedule_is_dropped_once_the_hold_has_gone_out(self):
        self.fire_all()

        self.assertIsNone(self.dispatcher.schedule)

    def test_a_replaced_schedule_never_publishes(self):
        ghost = FakeTimer.armed[-1]
        self.dispatcher.install(self.limits, rising_pass(count=3, first_offset_ms=60000))

        ghost.fire()

        self.assertEqual(self.published, [])

    def test_a_failing_publish_does_not_escape_the_timer_thread(self):
        self.dispatcher._publish = MagicMock(side_effect=RuntimeError('broker gone'))

        with self.assertLogs('pluto_sdk.dispatcher', level='ERROR'):
            FakeTimer.armed[-1].fire()


class StopTests(DispatcherTestCase):
    def test_stopping_mid_trajectory_holds_the_antenna(self):
        self.dispatcher.install(self.limits, rising_pass())
        armed = FakeTimer.armed[-1]

        self.dispatcher.stop()

        self.assertTrue(armed.cancelled)
        self.assertEqual(self.published[-1][0], TOPIC)
        self.assertEqual((self.reported[-1]['kind'], self.reported[-1]['reason']), (HOLD, STOPPED))
        self.assertIsNone(self.dispatcher.schedule)

    def test_stopping_with_nothing_pending_sends_nothing(self):
        self.dispatcher.stop()

        self.dispatcher.install(self.limits, rising_pass(count=1))
        self.fire_all()
        published = len(self.published)
        self.dispatcher.stop()

        # The trajectory already ended with its own HOLD.
        self.assertEqual(len(self.published), published)


if __name__ == '__main__':
    unittest.main()
