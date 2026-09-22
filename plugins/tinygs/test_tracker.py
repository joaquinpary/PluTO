import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from tle import Tle
from tracker import Tracker, assigned_norad

NOW = datetime(2026, 9, 22, 15, 0, 0, tzinfo=timezone.utc)
STATION = {'lat': -31.4201, 'lon': -64.1888, 'alt': 470.0}
TOPIC = 'plugin/3f2a-uuid/coordinates/raw'

NOAA_19 = 33591
ISS = 25544


def tracking(norad=NOAA_19, satellite='NOAA 19', **extra):
    """What the station publishes on pluto/<device>/tracking (MQTT_Pluto.cpp)."""
    return dict({'station': 'My TinyGS', 'satellite': satellite, 'NORAD': norad, 'mode': 'LoRa'}, **extra)


def a_pass(start=NOW + timedelta(minutes=10), seconds=3):
    return [(start + timedelta(seconds=index), 120.0 + index, 20.0 + index, 1500.0) for index in range(seconds)]


class AssignedNoradTests(unittest.TestCase):
    def test_reads_the_catalog_number(self):
        self.assertEqual(assigned_norad(tracking()), NOAA_19)

    def test_the_boot_placeholder_is_not_a_satellite(self):
        # Before the TinyGS server assigns anything, the retained message says
        # "Waiting" with the compiled-in default NORAD, FossaSat-3.
        self.assertIsNone(assigned_norad(tracking(norad=46494, satellite='Waiting')))

    def test_anything_that_is_not_a_catalog_number_is_ignored(self):
        for document in (
            {'satellite': 'NOAA 19'},
            tracking(norad='33591'),
            tracking(norad=True),
            tracking(norad=0),
            tracking(norad=-5),
            'not a document',
            None,
        ):
            with self.subTest(document=document):
                self.assertIsNone(assigned_norad(document))


class FakeClock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.cache = MagicMock()
        self.cache.get.side_effect = lambda norad: Tle(f'SAT {norad}', '1 x', '2 x')
        self.compute = MagicMock(return_value=a_pass())
        self.publish = MagicMock()
        self.tracker = Tracker(
            station=STATION, cache=self.cache, publish=self.publish, topic=TOPIC,
            min_elevation_deg=15.0, lookahead_minutes=25, sample_seconds=2,
            clock=self.clock, compute=self.compute,
        )

    def deliver(self, document):
        """What the worker thread does, run inline: queue and then process."""
        self.tracker.on_tracking(document)
        norad = self.tracker.take_pending()
        return norad is not None and self.tracker.process(norad)

    def test_a_new_satellite_publishes_its_pass(self):
        self.assertTrue(self.deliver(tracking()))

        self.publish.assert_called_once()
        topic, payload = self.publish.call_args.args
        self.assertEqual(topic, TOPIC)
        document = json.loads(payload)
        self.assertEqual((document['type'], document['coord_format']), ('ENU', 'POLAR'))
        self.assertEqual(len(document['coordinates']), 3)

    def test_the_settings_reach_the_propagator(self):
        self.deliver(tracking())

        self.assertEqual(self.compute.call_args.args, (self.cache.get(NOAA_19), STATION, NOW))
        self.assertEqual(self.compute.call_args.kwargs, {
            'min_elevation_deg': 15.0, 'lookahead_minutes': 25, 'sample_seconds': 2,
        })

    def test_the_heartbeat_does_not_republish_a_pass_that_is_still_ahead(self):
        self.deliver(tracking())
        self.clock.now = NOW + timedelta(minutes=5)

        self.assertFalse(self.deliver(tracking()))
        self.publish.assert_called_once()

    def test_a_different_satellite_publishes_again(self):
        self.deliver(tracking())

        self.assertTrue(self.deliver(tracking(norad=ISS, satellite='ISS')))
        self.assertEqual(self.publish.call_count, 2)

    def test_the_same_satellite_publishes_again_once_its_pass_is_over(self):
        self.deliver(tracking())
        # The 15 minute heartbeat after the pass ended is what catches the next.
        self.clock.now = a_pass()[-1][0] + timedelta(minutes=15)

        self.assertTrue(self.deliver(tracking()))
        self.assertEqual(self.publish.call_count, 2)

    def test_the_boot_placeholder_publishes_nothing(self):
        with self.assertLogs('tracker', level='INFO'):
            self.assertFalse(self.deliver(tracking(norad=46494, satellite='Waiting')))

        self.cache.get.assert_not_called()
        self.publish.assert_not_called()

    def test_no_pass_in_the_window_is_retried_on_the_next_message(self):
        self.compute.return_value = None

        with self.assertLogs('tracker', level='INFO'):
            self.assertFalse(self.deliver(tracking()))
        self.publish.assert_not_called()

        # Nothing was recorded, so the heartbeat tries again rather than being
        # taken for "already published".
        self.compute.return_value = a_pass()
        self.assertTrue(self.deliver(tracking()))

    def test_only_the_latest_satellite_waits_in_the_mailbox(self):
        self.tracker.on_tracking(tracking())
        self.tracker.on_tracking(tracking(norad=ISS, satellite='ISS'))

        self.assertEqual(self.tracker.take_pending(), ISS)
        self.assertIsNone(self.tracker.take_pending())

    def test_a_duplicate_queued_before_the_first_pass_was_recorded_is_dropped(self):
        # The retained message and the one sent on reconnect can both be queued
        # before the worker gets to the first; the second must not republish.
        self.assertTrue(self.tracker.process(NOAA_19))

        self.assertFalse(self.tracker.process(NOAA_19))
        self.publish.assert_called_once()


class WorkerThreadTests(unittest.TestCase):
    def test_a_failure_does_not_stop_the_worker(self):
        published = threading.Event()
        cache = MagicMock()
        cache.get.side_effect = [OSError('celestrak unreachable'), Tle('ISS', '1 x', '2 x')]
        tracker = Tracker(
            station=STATION, cache=cache, publish=lambda topic, payload: published.set(), topic=TOPIC,
            clock=FakeClock(), compute=MagicMock(return_value=a_pass()),
        )
        tracker.start()

        with self.assertLogs('tracker', level='ERROR'):
            tracker.on_tracking(tracking())
            # Give the first, failing round time to run before the next message.
            for _ in range(100):
                if cache.get.call_count:
                    break
                threading.Event().wait(0.01)

        tracker.on_tracking(tracking(norad=ISS, satellite='ISS'))

        self.assertTrue(published.wait(timeout=5), 'the worker died after the first failure')


if __name__ == '__main__':
    unittest.main()
