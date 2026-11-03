from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from ..downsample import downsample
from ..models import DispatchOrder, PluginData, PluginInstance, Rotor, RotorState
from .test_api import DEVICE_ID, OTHER_DEVICE_ID, FrontTestCase

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAY = 86400


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def iso(moment):
    # How DRF writes a UTC datetime.
    return moment.isoformat().replace('+00:00', 'Z')


# Exporting asks for a range of at most a week (CSV_MAX_RANGE).
CSV_RANGE = {'format': 'csv', 'from': iso(at(0)), 'to': iso(at(DAY))}


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

        response = self.client.get(self.url, CSV_RANGE)

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
    """A whole day at one state per second."""

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
        with patch('server_core.api.history.downsample', wraps=downsample) as thin:
            response = self.client.get(f'{self.url}/series', {'from': iso(at(0)), 'to': iso(at(DAY))})

        self.assertEqual(response.status_code, 200)
        rows = thin.call_args.args[0]
        # A list would hold the 86 400 rows at once; the iterator hands them over one chunk at a time.
        self.assertNotIsInstance(rows, (list, tuple))
        self.assertEqual(thin.call_args.kwargs['count'], DAY)


class DispatchOrdersTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.other = Rotor.objects.create(device_id=OTHER_DEVICE_ID)
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')

    def order(self, rotor, seconds, kind=DispatchOrder.Kind.BATCH, reason='', points=()):
        return DispatchOrder.objects.create(
            rotor=rotor, plugin=self.plugin, kind=kind, reason=reason,
            t0_ms=1000, t_sent_ms=900, t_end_ms=1000, points=list(points), created_at=at(seconds),
        )

    def test_lists_the_orders_of_a_board_newest_first(self):
        batch = self.order(self.rotor, 0, points=[[0, 100, 200], [500, 110, 210], [1000, 120, 220]])
        hold = self.order(self.rotor, 1, kind=DispatchOrder.Kind.HOLD, reason=DispatchOrder.Reason.LIMITS)
        self.order(self.other, 2)

        rows = self.client.get('/api/orders', {'board': DEVICE_ID}).json()['results']

        self.assertEqual([row['id'] for row in rows], [hold.pk, batch.pk])
        self.assertEqual(rows[1], {
            'id': batch.pk, 'board': DEVICE_ID, 'plugin': str(self.plugin.plugin_uuid), 'kind': 'BATCH',
            'reason': '', 't0_ms': 1000, 't_end_ms': 1000, 't_sent_ms': 900, 'point_count': 3,
            'created_at': iso(at(0)),
        })
        self.assertEqual(rows[0]['point_count'], 0)

    def test_filters_by_kind_reason_and_range(self):
        self.order(self.rotor, 0)
        limits = self.order(self.rotor, 1, kind=DispatchOrder.Kind.HOLD, reason=DispatchOrder.Reason.LIMITS)
        self.order(self.rotor, 2, kind=DispatchOrder.Kind.HOLD, reason=DispatchOrder.Reason.END)

        by_reason = self.client.get('/api/orders', {'kind': 'HOLD', 'reason': 'limits'}).json()['results']
        by_range = self.client.get('/api/orders', {'from': iso(at(1)), 'to': iso(at(2))}).json()['results']

        self.assertEqual([row['id'] for row in by_reason], [limits.pk])
        self.assertEqual([row['id'] for row in by_range], [limits.pk])

    def test_bad_filters_are_rejected_by_field(self):
        response = self.client.get('/api/orders', {'kind': 'PAUSE', 'board': 'not-a-mac'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {'kind', 'board'})

    def test_csv(self):
        self.order(self.rotor, 0)

        response = self.client.get('/api/orders', CSV_RANGE)

        lines = response.content.decode().splitlines()
        self.assertEqual(lines[0], 'id,board,plugin,kind,reason,t0_ms,t_end_ms,t_sent_ms,point_count,created_at')
        self.assertEqual(len(lines), 2)


class PluginDataHistoryTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')

    def row(self, payload, message_type='rx', plugin=None, seconds=0):
        return PluginData.objects.create(
            plugin=plugin or self.plugin, message_type=message_type, payload=payload, created_at=at(seconds),
        )

    def test_pulls_rssi_snr_crc_and_satellite_out_of_the_payload(self):
        payload = {'rssi': -112, 'snr': 4.5, 'crc_error': False, 'satellite': 'NOAA 19', 'NORAD': 33591}
        row = self.row(payload)

        result = self.client.get('/api/plugin-data').json()['results'][0]

        self.assertEqual(result, {
            'id': row.pk, 'plugin': str(self.plugin.plugin_uuid), 'message_type': 'rx', 'device': '',
            'received_at': None, 'created_at': iso(at(0)),
            'rssi': -112, 'snr': 4.5, 'crc_error': False, 'satellite': {'name': 'NOAA 19', 'norad': 33591},
            'payload': payload,
        })

    def test_missing_or_odd_fields_are_null_and_the_payload_stays(self):
        # An rx without rssi, a tracking without a satellite, the
        # placeholder a station sends before it gets one, a payload the ingester
        # wrapped, odd types, and a plugin type nobody knows.
        weather = PluginInstance.objects.create(name='weather-1', plugin_type='weather')
        payloads = [
            {},
            {'mode': 'LoRa'},
            {'satellite': 'Waiting', 'NORAD': 46494},
            {'value': 42},
            {'rssi': 'strong', 'snr': True, 'crc_error': 'no', 'satellite': 7, 'NORAD': True},
            {'temperature': 21.5},
        ]
        self.row(payloads[0])
        self.row(payloads[1], message_type='tracking')
        self.row(payloads[2], message_type='tracking')
        self.row(payloads[3])
        self.row(payloads[4])
        self.row(payloads[5], message_type='reading', plugin=weather)

        response = self.client.get('/api/plugin-data')

        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(len(results), 6)
        for result in results:
            with self.subTest(payload=result['payload']):
                self.assertEqual(
                    [result['rssi'], result['snr'], result['crc_error'], result['satellite']],
                    [None, None, None, None],
                )
        self.assertEqual([result['payload'] for result in reversed(results)], payloads)

    def test_filters_by_plugin_type_and_range(self):
        other = PluginInstance.objects.create(name='tinygs-2', plugin_type='tinygs')
        rx = self.row({'rssi': -100}, seconds=1)
        self.row({'satellite': 'ISS'}, message_type='tracking', seconds=1)
        self.row({'rssi': -90}, plugin=other, seconds=1)
        self.row({'rssi': -80}, seconds=5)

        rows = self.client.get('/api/plugin-data', {
            'plugin': str(self.plugin.plugin_uuid), 'type': 'rx', 'from': iso(at(0)), 'to': iso(at(2)),
        }).json()['results']

        self.assertEqual([row['id'] for row in rows], [rx.pk])

    def test_a_malformed_plugin_uuid_is_rejected(self):
        response = self.client.get('/api/plugin-data', {'plugin': 'tinygs-1'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('plugin', response.json())

    def test_csv_writes_nested_values_as_json(self):
        self.row({'rssi': -112, 'satellite': 'NOAA 19'})

        lines = self.client.get('/api/plugin-data', CSV_RANGE).content.decode().splitlines()

        self.assertEqual(
            lines[0],
            'id,plugin,message_type,device,received_at,created_at,rssi,snr,crc_error,satellite,payload',
        )
        self.assertTrue(lines[1].endswith(
            ',-112,,,"{""name"": ""NOAA 19"", ""norad"": null}","{""rssi"": -112, ""satellite"": ""NOAA 19""}"'
        ))


class HistoryAuthTests(FrontTestCase):
    def test_every_history_endpoint_needs_a_login(self):
        Rotor.objects.create(device_id=DEVICE_ID)
        del self.client.defaults['HTTP_AUTHORIZATION']

        for url in (f'/api/boards/{DEVICE_ID}/states', f'/api/boards/{DEVICE_ID}/states/series',
                    '/api/orders', '/api/plugin-data'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)


class CsvRangeTests(FrontTestCase):
    """A CSV is built whole before it is sent: an open or months-long range would
    outlast nginx's 600 s and hold the rows in memory, so exports ask for a week at most."""

    def test_an_export_needs_both_ends_of_the_range(self):
        Rotor.objects.create(device_id=DEVICE_ID)
        for url in (f'/api/boards/{DEVICE_ID}/states', '/api/orders', '/api/plugin-data'):
            for query in ({'format': 'csv'}, {'format': 'csv', 'from': iso(at(0))}):
                with self.subTest(url=url, query=query):
                    response = self.client.get(url, query)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn('detail', response.json())

    def test_an_export_covers_a_week_at_most(self):
        week = {'format': 'csv', 'from': iso(at(0)), 'to': iso(at(7 * DAY))}
        longer = {'format': 'csv', 'from': iso(at(0)), 'to': iso(at(7 * DAY + 1))}

        self.assertEqual(self.client.get('/api/orders', week).status_code, 200)
        response = self.client.get('/api/orders', longer)
        self.assertEqual(response.status_code, 400)
        self.assertIn('7 days', response.json()['detail'])

    def test_the_tables_still_page_without_a_range(self):
        self.assertEqual(self.client.get('/api/orders').status_code, 200)
