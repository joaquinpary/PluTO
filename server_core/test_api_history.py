from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from .downsample import downsample
from .models import Rotor, RotorState
from .test_api import DEVICE_ID, OTHER_DEVICE_ID, FrontTestCase

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAY = 86400


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def iso(moment):
    # How DRF writes a UTC datetime.
    return moment.isoformat().replace('+00:00', 'Z')


def one_state_per_second(rotor, seconds):
    RotorState.objects.bulk_create(
        RotorState(rotor=rotor, received_at=at(second), mode='tracking', az_cdeg=second % 36000, el_cdeg=4500)
        for second in range(seconds)
    )


class BoardStatesTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.url = f'/api/boards/{DEVICE_ID}/states'

    def state(self, seconds, **fields):
        return RotorState.objects.create(rotor=self.rotor, received_at=at(seconds), **fields)

    def test_lists_the_states_newest_first(self):
        self.state(0, mode='idle')
        self.state(1, mode='tracking', az_cdeg=27000, el_cdeg=3000,
                   payload={'meas': {'az_cdeg': 26990, 'el_cdeg': 3010}, 'err_cdeg': 14})

        page = self.client.get(self.url).json()

        self.assertEqual(set(page), {'next', 'previous', 'results'})
        self.assertEqual([row['mode'] for row in page['results']], ['tracking', 'idle'])
        self.assertEqual(set(page['results'][0]), {
            'received_at', 'mode', 'az_cdeg', 'el_cdeg', 'pan_mode', 'batch_accepted',
            'batch_error', 'latency_ms', 'clock_synced', 'err_cdeg',
        })
        self.assertEqual(page['results'][0]['err_cdeg'], 14)
        self.assertIsNone(page['results'][1]['err_cdeg'])

    def test_from_is_inclusive_and_to_exclusive(self):
        for second in range(5):
            self.state(second)

        rows = self.client.get(self.url, {'from': iso(at(1)), 'to': iso(at(3))}).json()['results']

        self.assertEqual([row['received_at'] for row in rows], [iso(at(2)), iso(at(1))])

    def test_a_bad_range_is_rejected(self):
        self.assertEqual(self.client.get(self.url, {'from': 'yesterday'}).status_code, 400)
        response = self.client.get(self.url, {'from': iso(at(5)), 'to': iso(at(1))})
        self.assertEqual(response.status_code, 400)
        self.assertIn('to', response.json())

    def test_an_unknown_board_is_not_found(self):
        self.assertEqual(self.client.get(f'/api/boards/{OTHER_DEVICE_ID}/states').status_code, 404)

    def test_the_series_needs_a_range(self):
        response = self.client.get(f'{self.url}/series')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {'from', 'to'})

    def test_csv_has_every_row_of_the_range_oldest_first(self):
        one_state_per_second(self.rotor, 150)

        response = self.client.get(self.url, {'format': 'csv'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="states.csv"')
        lines = response.content.decode().splitlines()
        self.assertEqual(
            lines[0],
            'received_at,mode,az_cdeg,el_cdeg,pan_mode,batch_accepted,batch_error,latency_ms,clock_synced,err_cdeg',
        )
        # Not a page: the header and all 150 rows.
        self.assertEqual(len(lines), 151)
        self.assertTrue(lines[1].startswith(f'{iso(at(0))},tracking,0,4500,'))


class LongRangeTests(FrontTestCase):
    """Review Focus 4: a whole day at one state per second."""

    @classmethod
    def setUpTestData(cls):
        cls.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        one_state_per_second(cls.rotor, DAY)

    def setUp(self):
        super().setUp()
        self.url = f'/api/boards/{DEVICE_ID}/states'

    def test_a_day_at_one_state_per_second_is_paginated_without_loading_it(self):
        with patch.object(RotorState, 'from_db', side_effect=RotorState.from_db) as from_db:
            first = self.client.get(self.url).json()

        self.assertEqual(len(first['results']), 100)
        # The page plus the one row that says there is a next page.
        self.assertLessEqual(from_db.call_count, 101)
        self.assertEqual(first['results'][0]['received_at'], iso(at(DAY - 1)))

        second = self.client.get(first['next']).json()
        self.assertEqual(second['results'][0]['received_at'], iso(at(DAY - 101)))

    def test_the_series_of_a_day_has_at_most_max_points_and_loads_no_model(self):
        with patch.object(RotorState, 'from_db', side_effect=RotorState.from_db) as from_db:
            response = self.client.get(f'{self.url}/series', {'from': iso(at(0)), 'to': iso(at(DAY)), 'max_points': 500})

        points = response.json()['points']
        self.assertEqual(len(points), 500)
        from_db.assert_not_called()
        self.assertEqual(points[0], {'t': iso(at(172)), 'az_cdeg': 172, 'el_cdeg': 4500})
        self.assertEqual(points[-1]['t'], iso(at(DAY - 1)))

    def test_the_series_defaults_to_2000_points(self):
        points = self.client.get(f'{self.url}/series', {'from': iso(at(0)), 'to': iso(at(DAY))}).json()['points']

        self.assertEqual(len(points), 2000)

    def test_the_series_walks_the_rows_instead_of_listing_them(self):
        with patch('server_core.api_history.downsample', wraps=downsample) as thin:
            response = self.client.get(f'{self.url}/series', {'from': iso(at(0)), 'to': iso(at(DAY))})

        self.assertEqual(response.status_code, 200)
        rows = thin.call_args.args[0]
        # A list would hold the 86 400 rows at once; the iterator hands them over one chunk at a time.
        self.assertNotIsInstance(rows, (list, tuple))
        self.assertEqual(thin.call_args.kwargs['count'], DAY)
