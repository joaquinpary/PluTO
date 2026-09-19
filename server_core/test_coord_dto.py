from datetime import datetime, timezone

from django.test import SimpleTestCase

from .coord_dto import (
    FLAG_HOLD,
    MAX_POINTS,
    az_to_cdeg,
    el_to_cdeg,
    encode,
    encode_hold,
    plan_batches,
    to_epoch_ms,
)

# The worked example of docs/contracts/coordinates-dto.md §7.
EXAMPLE_T0_MS = 1789763400000
EXAMPLE_T_SENT_MS = 1789763398000
EXAMPLE_POINTS = [(0, 12345, 4500), (1000, 12400, 4530), (2000, 12455, 4560)]
EXAMPLE_HEX = (
    '500003403136b6a0010000702936b6a0010000'
    '0000000039309411'
    'e80300007030b211'
    'd0070000a730d011'
)


class EncodeTests(SimpleTestCase):
    def test_matches_the_worked_example_of_the_contract(self):
        payload = encode(EXAMPLE_T0_MS, EXAMPLE_T_SENT_MS, EXAMPLE_POINTS)

        self.assertEqual(payload.hex(), EXAMPLE_HEX)
        self.assertEqual(len(payload), 43)

    def test_hold_is_the_bare_header_with_the_flag_set(self):
        payload = encode_hold(EXAMPLE_T_SENT_MS)

        self.assertEqual(len(payload), 19)
        self.assertEqual(payload[1], FLAG_HOLD)
        self.assertEqual(payload[2], 0)

    def test_five_points_fit_under_64_bytes(self):
        payload = encode(0, 0, [(i * 1000, 0, 0) for i in range(5)])

        self.assertEqual(len(payload), 59)

    def test_rejects_what_the_decoder_would_reject(self):
        cases = {
            'no points without HOLD': ([], 0),
            'too many points': ([(i, 0, 0) for i in range(MAX_POINTS + 1)], 0),
            'HOLD with points': ([(0, 0, 0)], FLAG_HOLD),
            'reserved flag': ([(0, 0, 0)], 0x02),
            'dt not increasing': ([(1000, 0, 0), (1000, 0, 0)], 0),
            'azimuth 36000': ([(0, 36000, 0)], 0),
            'elevation above 90': ([(0, 0, 9001)], 0),
            'elevation below -90': ([(0, 0, -9001)], 0),
            'dt beyond uint32': ([(2 ** 32, 0, 0)], 0),
        }
        for name, (points, flags) in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                encode(0, 0, points, flags=flags)


class ConversionTests(SimpleTestCase):
    def test_azimuth_rounds_before_wrapping(self):
        for az_deg, expected in ((359.994, 35999), (359.995, 0), (359.999, 0), (-0.001, 0),
                                 (360.0, 0), (123.45, 12345), (-90.0, 27000)):
            with self.subTest(az_deg=az_deg):
                self.assertEqual(az_to_cdeg(az_deg), expected)

    def test_elevation_is_rounded_and_bounded(self):
        self.assertEqual(el_to_cdeg(45.3), 4530)
        self.assertEqual(el_to_cdeg(-90.0), -9000)
        with self.assertRaises(ValueError):
            el_to_cdeg(90.01)

    def test_epoch_ms_is_exact_and_requires_a_timezone(self):
        moment = datetime(2026, 9, 18, 20, 30, 0, 999000, tzinfo=timezone.utc)

        self.assertEqual(to_epoch_ms(moment), EXAMPLE_T0_MS + 999)
        with self.assertRaises(ValueError):
            to_epoch_ms(moment.replace(tzinfo=None))


def trajectory(count, start_ms=EXAMPLE_T0_MS, step_ms=1000):
    return [(start_ms + i * step_ms, 100.0 + i, 20.0 + i) for i in range(count)]


class PlanBatchesTests(SimpleTestCase):
    def test_batches_overlap_and_the_last_one_reaches_the_end(self):
        batches = plan_batches(trajectory(9))

        # 5-point windows every 2 points: 0-4, 2-6, 4-8
        self.assertEqual([b.t0_ms - EXAMPLE_T0_MS for b in batches], [0, 2000, 4000])
        self.assertEqual(batches[-1].t0_ms + batches[-1].points[-1][0], EXAMPLE_T0_MS + 8000)
        self.assertTrue(all(len(b.points) == 5 for b in batches))

    def test_points_are_relative_to_the_batch_and_already_converted(self):
        first = plan_batches(trajectory(5))[0]

        self.assertEqual(first.points[0], (0, 10000, 2000))
        self.assertEqual(first.points[1], (1000, 10100, 2100))

    def test_each_batch_is_due_lead_ms_before_its_first_point(self):
        batches = plan_batches(trajectory(7), lead_ms=2500)

        self.assertTrue(all(b.send_at_ms == b.t0_ms - 2500 for b in batches))

    def test_a_short_trajectory_is_a_single_batch(self):
        batches = plan_batches(trajectory(1))

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].points, ((0, 10000, 2000),))

    def test_planned_batches_encode(self):
        for batch in plan_batches(trajectory(12)):
            self.assertLessEqual(len(batch.encode(batch.send_at_ms)), 64)

    def test_invalid_plans_are_rejected(self):
        with self.assertRaises(ValueError):
            plan_batches([])
        with self.assertRaises(ValueError):
            plan_batches(trajectory(5), stride=3)  # more than half a batch
        with self.assertRaises(ValueError):
            plan_batches([(0, 0.0, 0.0), (0, 1.0, 1.0)])  # timestamps not increasing
