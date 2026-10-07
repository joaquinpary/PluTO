import unittest
from datetime import datetime, timedelta, timezone

from models import Station
from parser import build_payload_from_text, split_timestamp

STATION = Station(lat=-31.4, lon=-64.2, alt=400.0)
NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def build(text, coord_type='ECEF', coord_format='GEO'):
    return build_payload_from_text(text, coord_type, coord_format, STATION, NOW)


class ParserTests(unittest.TestCase):
    def test_points_without_timestamps_go_one_second_apart_from_now(self):
        payload = build('[40.4, -3.7, 667.0]\n[41.3, 2.1, 12.0]\n')

        self.assertEqual([point.timestamp for point in payload.coordinates], [NOW, NOW + timedelta(seconds=1)])
        self.assertEqual(payload.coordinates[1].lon, 2.1)

    def test_comma_is_accepted_as_decimal_separator(self):
        payload = build('40,5 -3,25 667')

        self.assertEqual((payload.coordinates[0].lat, payload.coordinates[0].lon), (40.5, -3.25))

    def test_lines_without_three_numbers_are_skipped(self):
        payload = build('lat lon alt\n40 -3 667\n\nend')

        self.assertEqual(len(payload.coordinates), 1)

    def test_timestamps_keep_their_spacing_but_start_now(self):
        payload = build(
            '2025-01-01T08:00:00Z 120 10 500\n'
            '2025-01-01T08:00:02.5Z 121 11 501\n'
            '2025-01-01 08:00:10 122 12 502\n',
            coord_type='ENU', coord_format='POLAR',
        )

        self.assertEqual(
            [point.timestamp for point in payload.coordinates],
            [NOW, NOW + timedelta(seconds=2.5), NOW + timedelta(seconds=10)],
        )
        self.assertEqual((payload.coordinates[0].az, payload.coordinates[0].el, payload.coordinates[0].range), (120, 10, 500))

    def test_timestamp_digits_are_not_read_as_coordinates(self):
        timestamp, rest = split_timestamp('["2025-01-01T08:00:00+03:00", 1, 2, 3]')

        self.assertEqual(timestamp, datetime(2025, 1, 1, 5, 0, 0, tzinfo=timezone.utc))
        self.assertNotIn('2025', rest)

    def test_mixing_lines_with_and_without_timestamps_is_rejected(self):
        with self.assertRaises(ValueError):
            build('2025-01-01T08:00:00Z 1 2 3\n4 5 6\n')

    def test_timestamps_that_do_not_increase_are_rejected(self):
        with self.assertRaises(ValueError):
            build('2025-01-01T08:00:05Z 1 2 3\n2025-01-01T08:00:01Z 4 5 6\n')

    def test_a_file_without_coordinates_is_rejected(self):
        with self.assertRaises(ValueError):
            build('nothing here\n')


if __name__ == '__main__':
    unittest.main()
