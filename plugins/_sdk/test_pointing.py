import unittest
from datetime import datetime, timezone

from pluto_sdk.pointing import (
    END,
    EXPIRED,
    HOLD_GRACE_MS,
    LIMITS,
    RotorLimits,
    merge_trajectory,
    parse_polar,
    plan_for_rotor,
)

DEVICE_ID = 'a1b2c3d4e5f6'

# A round instant to hang the clock on: 2026-09-18T20:30:00Z.
NOW_MS = 1789763400000


def at(offset_ms):
    return NOW_MS + offset_ms


def polar(points):
    """What POST /transform returns: a station plus timestamped az/el points."""
    return {
        'station': {'lat': -31.44, 'lon': -64.19, 'alt': 470.0},
        'coordinates': [
            {
                'timestamp': datetime.fromtimestamp(t_ms / 1000, timezone.utc).isoformat(),
                'az': az_deg,
                'el': el_deg,
                'range': 1187.4,
            }
            for t_ms, az_deg, el_deg in points
        ],
    }


def rising_pass(count=6, first_offset_ms=3000):
    """A trajectory climbing away from the horizon, one point per second."""
    return [
        (at(first_offset_ms + 1000 * index), 120.0 + index, 20.0 + 5 * index)
        for index in range(count)
    ]


def limits(**overrides):
    overrides.setdefault('min_elevation_deg', 10.0)
    return RotorLimits(device_id=DEVICE_ID, **overrides)


class ParsePolarTests(unittest.TestCase):
    def test_reads_what_transform_returns(self):
        trajectory = parse_polar(polar([(at(1000), 123.45, 45.0), (at(2000), 124.0, 45.3)]))

        self.assertEqual(trajectory, [(at(1000), 123.45, 45.0), (at(2000), 124.0, 45.3)])

    def test_points_come_back_in_time_order(self):
        trajectory = parse_polar(polar([(at(2000), 124.0, 45.3), (at(1000), 123.45, 45.0)]))

        self.assertEqual([point[0] for point in trajectory], [at(1000), at(2000)])

    def test_two_points_on_the_same_instant_collapse_into_the_last(self):
        trajectory = parse_polar(polar([(at(1000), 123.45, 45.0), (at(1000), 200.0, 10.0)]))

        self.assertEqual(trajectory, [(at(1000), 200.0, 10.0)])

    def test_timestamp_without_offset_is_taken_as_utc(self):
        trajectory = parse_polar({'coordinates': [{'timestamp': '2026-09-18T20:30:00', 'az': 10.0, 'el': 20.0}]})

        self.assertEqual(trajectory[0][0], NOW_MS)

    def test_unusable_points_are_skipped(self):
        document = {'coordinates': [
            {'timestamp': 'not-a-date', 'az': 10.0, 'el': 20.0},
            {'timestamp': '2026-09-18T20:30:01+00:00', 'az': True, 'el': 20.0},
            {'timestamp': '2026-09-18T20:30:02+00:00', 'az': 10.0, 'el': None},
            {'timestamp': '2026-09-18T20:30:03+00:00', 'az': 10.0, 'el': 20.0},
            'not a point',
        ]}

        self.assertEqual(parse_polar(document), [(at(3000), 10.0, 20.0)])

    def test_returns_none_when_nothing_is_usable(self):
        for document in (
            [1, 2],
            {'station': {}},
            {'station': {}, 'coordinates': []},
            {'coordinates': [{'timestamp': 'x', 'az': 1, 'el': 2}]},
        ):
            with self.subTest(document=document), self.assertLogs('pluto_sdk.pointing', level='WARNING'):
                self.assertIsNone(parse_polar(document))


class RotorLimitsTests(unittest.TestCase):
    def test_reads_what_the_server_returns(self):
        rotor = RotorLimits.from_api({'device_id': DEVICE_ID, 'min_elevation_deg': 12,
                                      'min_azimuth_deg': 300, 'max_azimuth_deg': 60})

        self.assertEqual(rotor, RotorLimits(DEVICE_ID, 12.0, 300.0, 60.0))

    def test_without_a_window_every_azimuth_is_allowed(self):
        rotor = RotorLimits.from_api({'device_id': DEVICE_ID, 'min_elevation_deg': 10,
                                      'min_azimuth_deg': None, 'max_azimuth_deg': None})

        for az_deg in (0.0, 180.0, 359.9):
            self.assertTrue(rotor.azimuth_in_window(az_deg))

    def test_plain_window_is_a_closed_interval(self):
        rotor = limits(min_azimuth_deg=90.0, max_azimuth_deg=180.0)

        self.assertTrue(rotor.azimuth_in_window(90.0))
        self.assertTrue(rotor.azimuth_in_window(180.0))
        self.assertFalse(rotor.azimuth_in_window(89.9))
        self.assertFalse(rotor.azimuth_in_window(180.1))

    def test_window_below_its_start_wraps_through_north(self):
        rotor = limits(min_azimuth_deg=300.0, max_azimuth_deg=60.0)

        for az_deg in (300.0, 350.0, 0.0, 60.0):
            self.assertTrue(rotor.azimuth_in_window(az_deg), az_deg)
        for az_deg in (61.0, 180.0, 299.0):
            self.assertFalse(rotor.azimuth_in_window(az_deg), az_deg)

    def test_point_in_bounds_checks_the_elevation_threshold(self):
        rotor = limits(min_elevation_deg=15.0)

        self.assertTrue(rotor.point_in_bounds(120.0, 15.0))
        self.assertFalse(rotor.point_in_bounds(120.0, 14.9))


class MergeTrajectoryTests(unittest.TestCase):
    def test_nothing_pending_keeps_what_arrives(self):
        incoming = rising_pass(2)

        self.assertEqual(merge_trajectory([], incoming), incoming)

    def test_an_empty_message_leaves_the_plan_alone(self):
        pending = rising_pass(2)

        self.assertEqual(merge_trajectory(pending, []), pending)

    def test_a_single_point_extends_the_tail(self):
        pending = rising_pass(2)
        incoming = [(at(6000), 140.0, 60.0)]

        self.assertEqual(merge_trajectory(pending, incoming), pending + incoming)

    def test_what_arrives_wins_over_the_stretch_it_covers(self):
        pending = rising_pass(4)
        incoming = [(at(5000), 999.0, 88.0)]

        # The pending points from 5000 on are gone; the earlier ones survive.
        self.assertEqual(merge_trajectory(pending, incoming), pending[:2] + incoming)

    def test_a_message_starting_first_replaces_everything(self):
        pending = rising_pass(4)
        incoming = [(at(1000), 10.0, 10.0), (at(2000), 11.0, 11.0)]

        self.assertEqual(merge_trajectory(pending, incoming), incoming)


class PlanForRotorTests(unittest.TestCase):
    def test_points_that_already_passed_are_dropped(self):
        trajectory = [(at(-5000), 120.0, 30.0)] + rising_pass(3)

        batches, _, _ = plan_for_rotor(limits(), trajectory, NOW_MS)

        self.assertEqual(batches[0].t0_ms, at(3000))

    def test_a_whole_trajectory_holds_after_the_last_point(self):
        trajectory = rising_pass(6)

        batches, hold_at_ms, reason = plan_for_rotor(limits(), trajectory, NOW_MS)

        self.assertTrue(batches)
        self.assertEqual(hold_at_ms, trajectory[-1][0] + HOLD_GRACE_MS)
        self.assertEqual(reason, END)

    def test_elevation_threshold_cuts_the_trajectory_at_the_edge(self):
        # Climbs, then drops back under the threshold on the fourth point.
        trajectory = [
            (at(3000), 120.0, 30.0),
            (at(4000), 121.0, 25.0),
            (at(5000), 122.0, 20.0),
            (at(6000), 123.0, 5.0),
            (at(7000), 124.0, 2.0),
        ]

        batches, hold_at_ms, reason = plan_for_rotor(limits(min_elevation_deg=15.0), trajectory, NOW_MS)

        self.assertEqual(reason, LIMITS)
        # No grace: the antenna stops exactly where the target leaves the window.
        self.assertEqual(hold_at_ms, at(6000))
        self.assertEqual([point[0] for point in batches[0].points], [0, 1000, 2000])

    def test_azimuth_window_cuts_the_trajectory_too(self):
        trajectory = [(at(3000), 350.0, 30.0), (at(4000), 10.0, 30.0), (at(5000), 120.0, 30.0)]

        _, hold_at_ms, reason = plan_for_rotor(
            limits(min_azimuth_deg=300.0, max_azimuth_deg=60.0), trajectory, NOW_MS,
        )

        self.assertEqual(reason, LIMITS)
        self.assertEqual(hold_at_ms, at(5000))

    def test_everything_expired_means_stop_now(self):
        trajectory = [(at(-2000), 120.0, 30.0), (at(-1000), 121.0, 31.0)]

        self.assertEqual(plan_for_rotor(limits(), trajectory, NOW_MS), ([], NOW_MS, EXPIRED))

    def test_a_first_point_out_of_bounds_means_stop_now(self):
        trajectory = [(at(3000), 120.0, 2.0), (at(4000), 121.0, 1.0)]

        self.assertEqual(plan_for_rotor(limits(min_elevation_deg=15.0), trajectory, NOW_MS), ([], NOW_MS, LIMITS))

    def test_a_trajectory_the_encoder_refuses_is_rejected(self):
        with self.assertLogs('pluto_sdk.pointing', level='WARNING'):
            self.assertIsNone(plan_for_rotor(limits(), [(at(3000), 120.0, 95.0)], NOW_MS))


if __name__ == '__main__':
    unittest.main()
