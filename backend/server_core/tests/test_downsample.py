from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from ..downsample import downsample


def rows(*times):
    return [{'t': t, 'value': index} for index, t in enumerate(times)]


class DownsampleTests(SimpleTestCase):
    def test_few_rows_come_back_untouched(self):
        data = rows(0, 1, 2)

        self.assertEqual(downsample(data, 't', 5), data)

    def test_keeps_the_last_row_of_each_interval(self):
        # 0..9 in 5 intervals of 1.8: [0, 1.8) holds 0 and 1, [1.8, 3.6) holds 2 and 3...
        result = downsample(rows(*range(10)), 't', 5)

        self.assertEqual([row['t'] for row in result], [1, 3, 5, 7, 9])

    def test_never_returns_more_than_max_points_and_ends_on_the_last_row(self):
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        data = rows(*(start + timedelta(seconds=second) for second in range(86400)))

        result = downsample(data, 't', 2000)

        self.assertEqual(len(result), 2000)
        self.assertEqual(result[-1], data[-1])
        self.assertEqual(result, sorted(result, key=lambda row: row['t']))

    def test_a_gap_stays_a_gap(self):
        result = downsample(rows(0, 1, 2, 3, 4, 100, 101, 102, 103, 104), 't', 5)

        self.assertEqual([row['t'] for row in result], [4, 104])

    def test_rows_all_in_the_same_instant_collapse_into_the_last(self):
        data = rows(7, 7, 7)

        self.assertEqual(downsample(data, 't', 2), [data[-1]])

    def test_an_iterator_with_its_bounds_is_thinned_the_same_way(self):
        # What the series view passes: a queryset iterator, plus the first
        # instant, the last one and the count, which it asks the database for.
        data = rows(*range(10))

        result = downsample(iter(data), 't', 5, start=0, end=9, count=10)

        self.assertEqual([row['t'] for row in result], [1, 3, 5, 7, 9])
