import json
import unittest
from datetime import datetime, timedelta, timezone

from tle import Tle
from trajectory import build_raw_payload, next_pass

# A real NOAA 19 element set, fetched from CelesTrak on 2026-09-22, and a fixed
# station and instant: with skyfield pinned, every run propagates the same pass.
NOAA_19 = Tle(
    'NOAA 19',
    '1 33591U 09005A   26265.59422357 -.00000002  00000+0  22595-4 0  9992',
    '2 33591  98.9435 336.4970 0014750 113.5139 246.7585 14.13486520908247',
)
CORDOBA = {'lat': -31.4201, 'lon': -64.1888, 'alt': 470.0}

# That pass over Córdoba rises through 10 degrees at 15:10:34 UTC, culminates
# at 23.18 degrees at 15:14:51 and sets at 15:19:11.
BEFORE_THE_PASS = datetime(2026, 9, 22, 15, 0, 0, tzinfo=timezone.utc)
DURING_THE_PASS = datetime(2026, 9, 22, 15, 14, 0, tzinfo=timezone.utc)
AFTER_THE_PASS = datetime(2026, 9, 22, 15, 30, 0, tzinfo=timezone.utc)


class NextPassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.points = next_pass(NOAA_19, CORDOBA, BEFORE_THE_PASS, min_elevation_deg=10.0, lookahead_minutes=20)

    def test_finds_the_pass_that_starts_within_the_lookahead(self):
        self.assertIsNotNone(self.points)
        self.assertEqual(self.points[0][0].replace(microsecond=0), datetime(2026, 9, 22, 15, 10, 34, tzinfo=timezone.utc))
        self.assertEqual(self.points[-1][0].replace(microsecond=0), datetime(2026, 9, 22, 15, 19, 11, tzinfo=timezone.utc))

    def test_every_point_is_at_or_above_the_threshold(self):
        # The rise and set are threshold crossings, where a sample can come out
        # a hair below. The dispatcher drops a trajectory whose first point is
        # out of bounds, so not one may slip through.
        self.assertGreaterEqual(min(point[2] for point in self.points), 10.0)

    def test_the_culmination_is_in_the_middle_of_the_pass(self):
        peak = max(self.points, key=lambda point: point[2])

        self.assertAlmostEqual(peak[2], 23.177, places=2)
        self.assertEqual(peak[0].replace(microsecond=0), datetime(2026, 9, 22, 15, 14, 51, tzinfo=timezone.utc))
        self.assertLess(self.points[0][2], peak[2])
        self.assertLess(self.points[-1][2], peak[2])

    def test_points_are_one_second_apart(self):
        steps = {later[0] - earlier[0] for earlier, later in zip(self.points, self.points[1:])}

        self.assertEqual(steps, {timedelta(seconds=1)})

    def test_azimuth_stays_in_range_and_timestamps_are_aware(self):
        for moment, az_deg, _, range_km in self.points:
            self.assertIsNotNone(moment.tzinfo)
            self.assertTrue(0.0 <= az_deg < 360.0)
            self.assertGreater(range_km, 0.0)

    def test_nothing_when_the_next_pass_starts_after_the_lookahead(self):
        self.assertIsNone(next_pass(NOAA_19, CORDOBA, BEFORE_THE_PASS - timedelta(hours=1), lookahead_minutes=20))

    def test_nothing_right_after_a_pass(self):
        self.assertIsNone(next_pass(NOAA_19, CORDOBA, AFTER_THE_PASS, lookahead_minutes=20))

    def test_a_pass_in_progress_is_taken_from_now(self):
        # find_events has no rise to report for a pass that already started.
        points = next_pass(NOAA_19, CORDOBA, DURING_THE_PASS, lookahead_minutes=20)

        self.assertEqual(points[0][0], DURING_THE_PASS)
        self.assertEqual(points[-1][0].replace(microsecond=0), datetime(2026, 9, 22, 15, 19, 11, tzinfo=timezone.utc))

    def test_sampling_follows_sample_seconds(self):
        points = next_pass(NOAA_19, CORDOBA, BEFORE_THE_PASS, lookahead_minutes=20, sample_seconds=5)

        self.assertEqual(points[1][0] - points[0][0], timedelta(seconds=5))
        self.assertAlmostEqual(len(points), len(self.points) / 5, delta=2)

    def test_a_higher_threshold_gives_a_shorter_pass(self):
        points = next_pass(NOAA_19, CORDOBA, BEFORE_THE_PASS, min_elevation_deg=20.0, lookahead_minutes=20)

        self.assertLess(len(points), len(self.points))
        self.assertGreaterEqual(min(point[2] for point in points), 20.0)


class BuildRawPayloadTests(unittest.TestCase):
    def setUp(self):
        self.points = [
            (datetime(2026, 9, 22, 15, 10, 34, tzinfo=timezone.utc), 327.643, 10.0, 2821.4),
            (datetime(2026, 9, 22, 15, 10, 35, tzinfo=timezone.utc), 327.5, 10.1, 2810.2),
        ]

    def test_is_enu_polar_so_the_engine_forwards_it_as_is(self):
        payload = build_raw_payload(CORDOBA, self.points)

        self.assertEqual(payload['type'], 'ENU')
        self.assertEqual(payload['coord_format'], 'POLAR')
        self.assertEqual(payload['station'], CORDOBA)

    def test_each_point_carries_exactly_what_coord_transform_expects(self):
        payload = build_raw_payload(CORDOBA, self.points)

        self.assertEqual(payload['coordinates'][0], {
            'timestamp': '2026-09-22T15:10:34+00:00',
            'az': 327.643,
            'el': 10.0,
            'range': 2821.4,
        })

    def test_timestamps_keep_their_offset(self):
        payload = build_raw_payload(CORDOBA, self.points)

        for point in payload['coordinates']:
            self.assertIsNotNone(datetime.fromisoformat(point['timestamp']).tzinfo)

    def test_a_real_pass_serializes_to_json(self):
        points = next_pass(NOAA_19, CORDOBA, BEFORE_THE_PASS, lookahead_minutes=20)

        document = json.loads(json.dumps(build_raw_payload(CORDOBA, points)))

        self.assertEqual(len(document['coordinates']), len(points))


if __name__ == '__main__':
    unittest.main()
