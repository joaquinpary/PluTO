import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .api import MAX_BATCH, MAX_ENVELOPE_BYTES
from .api_tokens import TOKEN_PREFIX, hash_token, issue_token
from .board_scan import BrokerUnavailable, record_status, scan_boards
from .models import DispatchOrder, PluginData, PluginInstance, Rotor, RotorState
from .plugin_handlers import PLUGIN_HANDLERS

DEVICE_ID = 'a1b2c3d4e5f6'
OTHER_DEVICE_ID = '0a0b0c0d0e0f'


def envelope(**overrides):
    document = {
        'schema_version': 1,
        'message_id': 'msg-1',
        'plugin_type': 'tinygs',
        'device': 'heltec-lp-01',
        'message_type': 'rx',
        'source_topic': 'pluto/heltec-lp-01/rx',
        'received_at': '2026-09-12T18:03:11+00:00',
        'payload_format': 'json',
        'payload': {'rssi': -97},
    }
    document.update(overrides)
    return document


def running_plugin(name='tinygs-1', plugin_type='tinygs', rotor=None):
    token, token_hash = issue_token()
    plugin = PluginInstance.objects.create(
        name=name,
        plugin_type=plugin_type,
        status=PluginInstance.Status.RUNNING,
        api_token_hash=token_hash,
        rotor=rotor,
    )
    return plugin, token


class ApiTokenTests(SimpleTestCase):
    def test_issued_tokens_are_unique_and_stored_hashed(self):
        token, token_hash = issue_token()
        other, _ = issue_token()

        self.assertNotEqual(token, other)
        self.assertEqual(token_hash, hash_token(token))
        self.assertNotIn(token, token_hash)
        self.assertTrue(token.startswith(TOKEN_PREFIX))

    def test_the_api_host_is_always_allowed(self):
        # Plugins call http://server:8000/api/, whatever DJANGO_ALLOWED_HOSTS says.
        self.assertIn('server', settings.ALLOWED_HOSTS)


class PluginAuthTests(TestCase):
    def post(self, token=None, body=None):
        headers = {'HTTP_AUTHORIZATION': f'Plugin {token}'} if token else {}
        return self.client.post(
            '/api/plugin-data/rx',
            data=json.dumps(body if body is not None else envelope()),
            content_type='application/json',
            **headers,
        )

    def test_missing_token_is_unauthorized(self):
        self.assertEqual(self.post().status_code, 401)

    def test_unknown_token_is_unauthorized(self):
        running_plugin()
        self.assertEqual(self.post(token='not-a-token').status_code, 401)

    def test_token_of_a_stopped_instance_is_unauthorized(self):
        plugin, token = running_plugin()
        plugin.status = PluginInstance.Status.STOPPED
        plugin.save()

        self.assertEqual(self.post(token=token).status_code, 401)
        self.assertFalse(PluginData.objects.exists())

    def test_a_cleared_hash_never_matches(self):
        PluginInstance.objects.create(name='no-token', plugin_type='tinygs', status=PluginInstance.Status.RUNNING)

        response = self.client.post('/api/plugin-data/rx', data='{}', content_type='application/json',
                                    HTTP_AUTHORIZATION='Plugin ')
        self.assertEqual(response.status_code, 401)

    def test_the_user_jwt_is_not_a_plugin_token(self):
        user = get_user_model().objects.create_user('operator', password='x')
        access = RefreshToken.for_user(user).access_token

        response = self.post_with_header(f'Bearer {access}')

        self.assertEqual(response.status_code, 401)
        self.assertFalse(PluginData.objects.exists())

    def post_with_header(self, header):
        return self.client.post('/api/plugin-data/rx', data=json.dumps(envelope()),
                                content_type='application/json', HTTP_AUTHORIZATION=header)

    def test_only_post_is_allowed(self):
        _, token = running_plugin()
        response = self.client.get('/api/plugin-data/rx', HTTP_AUTHORIZATION=f'Plugin {token}')
        self.assertEqual(response.status_code, 405)


class PluginDataTests(TestCase):
    def setUp(self):
        self.plugin, self.token = running_plugin()

    def post(self, body, message_type='rx', raw=False):
        return self.client.post(
            f'/api/plugin-data/{message_type}',
            data=body if raw else json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Plugin {self.token}',
        )

    def test_stores_the_envelope_under_the_token_instance(self):
        response = self.post(envelope())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {'message_id': 'msg-1', 'result': 'ingested'})
        row = PluginData.objects.get()
        self.assertEqual(row.plugin, self.plugin)
        self.assertEqual(row.message_type, 'rx')
        self.assertEqual(row.payload, {'rssi': -97})
        self.assertEqual(row.ingest_topic, '/api/plugin-data/rx')
        self.assertEqual(row.received_at, datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc))

    def test_a_retry_is_a_duplicate_and_stored_once(self):
        self.post(envelope())
        response = self.post(envelope())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result'], 'duplicate')
        self.assertEqual(PluginData.objects.count(), 1)

    def test_the_envelope_cannot_claim_another_instance(self):
        other, _ = running_plugin(name='tinygs-2')

        with self.assertLogs('server_core.ingest', level='WARNING'):
            self.post(envelope(plugin_id=str(other.plugin_uuid)))

        self.assertEqual(PluginData.objects.get().plugin, self.plugin)

    def test_the_url_decides_the_message_type(self):
        self.post(envelope(message_type='tracking'), message_type='rx')
        self.assertEqual(PluginData.objects.get().message_type, 'rx')

    def test_malformed_message_type_is_rejected(self):
        self.assertEqual(self.post(envelope(), message_type='RX').status_code, 400)

    def test_message_type_the_plugin_type_does_not_send_is_forbidden(self):
        response = self.post(envelope(), message_type='telemetry')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(PluginData.objects.exists())

    def test_a_plugin_type_without_data_is_forbidden_any_type(self):
        _, token = running_plugin(name='tracker', plugin_type='file_tracker')
        response = self.client.post('/api/plugin-data/rx', data=json.dumps(envelope()),
                                    content_type='application/json', HTTP_AUTHORIZATION=f'Plugin {token}')
        self.assertEqual(response.status_code, 403)

    def test_invalid_json_is_rejected(self):
        self.assertEqual(self.post('{"roto', raw=True).status_code, 400)

    def test_non_object_envelope_is_rejected(self):
        self.assertEqual(self.post('"just a string"', raw=True).status_code, 400)

    def test_oversized_envelope_is_rejected(self):
        response = self.post(envelope(payload={'blob': 'x' * MAX_ENVELOPE_BYTES}))

        self.assertEqual(response.status_code, 413)
        self.assertFalse(PluginData.objects.exists())

    def test_the_handler_can_reject_a_payload(self):
        handler = PLUGIN_HANDLERS['tinygs']
        with patch.object(handler, 'validate_data', return_value='rssi is required') as validate_data:
            response = self.post(envelope(payload={}))

        validate_data.assert_called_once_with('rx', {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'rssi is required')

    def test_a_batch_is_answered_per_envelope(self):
        self.post(envelope(message_id='seen'))

        response = self.post([envelope(message_id='new'), envelope(message_id='seen'), 'not an object'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [result['result'] for result in response.json()['results']],
            ['ingested', 'duplicate', 'rejected'],
        )
        self.assertEqual(PluginData.objects.count(), 2)

    def test_a_batch_must_not_be_empty_or_too_long(self):
        self.assertEqual(self.post([]).status_code, 400)
        too_many = [envelope(message_id=f'm{index}') for index in range(MAX_BATCH + 1)]
        self.assertEqual(self.post(too_many).status_code, 400)
        self.assertFalse(PluginData.objects.exists())


STATE = {
    'v': 1,
    'ts_ms': 1789763398140,
    'clock_synced': True,
    'mode': 'tracking',
    'az_cdeg': 27000,
    'el_cdeg': 3000,
    'pan_mode': 'normal',
    'batch': {'accepted': True, 'error': None, 'latency_ms': 140},
    'rejected_total': 0,
}


class DeviceReportTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin, self.token = running_plugin(rotor=self.rotor)

    def post(self, leaf, body, token=None):
        return self.client.post(
            f'/api/device/{leaf}',
            data=body,
            content_type='application/json' if leaf == 'state' else 'text/plain',
            HTTP_AUTHORIZATION=f'Plugin {token or self.token}',
        )

    def test_status_updates_the_bound_board(self):
        response = self.post('status', 'online')

        self.assertEqual(response.status_code, 201)
        self.rotor.refresh_from_db()
        self.assertTrue(self.rotor.online)
        self.assertIsNotNone(self.rotor.status_changed_at)

    def test_state_is_stored_for_the_bound_board(self):
        response = self.post('state', json.dumps(STATE))

        self.assertEqual(response.status_code, 201)
        state = RotorState.objects.get()
        self.assertEqual((state.rotor, state.mode, state.az_cdeg), (self.rotor, 'tracking', 27000))

    def test_invalid_reports_are_rejected(self):
        with self.assertLogs('server_core.device_state', level='WARNING'):
            self.assertEqual(self.post('status', 'maybe').status_code, 400)
            self.assertEqual(self.post('state', '[1, 2]').status_code, 400)
        self.assertFalse(RotorState.objects.exists())

    def test_an_instance_without_a_board_is_forbidden(self):
        _, token = running_plugin(name='no-board')

        response = self.post('status', 'online', token=token)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Rotor.objects.count(), 1)


class FrontAuthTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('operator', password='secret')

    def login(self):
        response = self.client.post('/api/auth/token', data={'username': 'operator', 'password': 'secret'},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_anonymous_is_unauthorized(self):
        self.assertEqual(self.client.get('/api/boards').status_code, 401)

    def test_a_plugin_token_is_not_a_login(self):
        _, token = running_plugin()
        response = self.client.get('/api/boards', HTTP_AUTHORIZATION=f'Plugin {token}')
        self.assertEqual(response.status_code, 401)

    def test_logging_in_gives_access_to_the_front_end_endpoints(self):
        tokens = self.login()

        response = self.client.get('/api/boards', HTTP_AUTHORIZATION=f'Bearer {tokens["access"]}')

        self.assertEqual(response.status_code, 200)

    def test_wrong_password_gets_no_token(self):
        response = self.client.post('/api/auth/token', data={'username': 'operator', 'password': 'nope'},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_a_refresh_token_works_once(self):
        refresh = self.login()['refresh']

        first = self.client.post('/api/auth/token/refresh', data={'refresh': refresh}, content_type='application/json')
        second = self.client.post('/api/auth/token/refresh', data={'refresh': refresh}, content_type='application/json')

        self.assertEqual(first.status_code, 200)
        self.assertIn('refresh', first.json())
        self.assertEqual(second.status_code, 401)

    def test_logging_out_revokes_the_refresh_token(self):
        refresh = self.login()['refresh']

        logout = self.client.post('/api/auth/token/blacklist', data={'refresh': refresh}, content_type='application/json')
        after = self.client.post('/api/auth/token/refresh', data={'refresh': refresh}, content_type='application/json')

        self.assertEqual(logout.status_code, 200)
        self.assertEqual(after.status_code, 401)


class FrontTestCase(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user('operator', password='x')
        self.client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {RefreshToken.for_user(user).access_token}'


class BoardsTests(FrontTestCase):
    def test_lists_the_boards_with_their_plugins(self):
        rotor = Rotor.objects.create(device_id=DEVICE_ID, online=True)
        plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs', rotor=rotor)
        Rotor.objects.create(device_id=OTHER_DEVICE_ID)

        boards = self.client.get('/api/boards').json()
        self.assertEqual(set(boards[0]), {'device_id', 'name', 'online', 'status_changed_at', 'last_state_at', 'plugins'})

        self.assertEqual([board['device_id'] for board in boards], [OTHER_DEVICE_ID, DEVICE_ID])
        self.assertEqual(boards[1]['online'], True)
        self.assertEqual(boards[1]['plugins'], [
            {'plugin_uuid': str(plugin.plugin_uuid), 'name': 'tinygs-1', 'status': 'STOPPED'},
        ])
        self.assertEqual(boards[0]['plugins'], [])

    @patch('server_core.api.scan_boards')
    def test_listing_does_not_touch_the_broker(self, scan):
        self.client.get('/api/boards')
        scan.assert_not_called()


@patch('server_core.api.scan_boards')
class ScanTests(FrontTestCase):
    def test_registers_new_boards_and_refreshes_online(self, scan):
        Rotor.objects.create(device_id=OTHER_DEVICE_ID, online=True)
        scan.return_value = {DEVICE_ID: b'online', OTHER_DEVICE_ID: b'offline'}

        response = self.client.post('/api/boards/scan')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {board['device_id']: board['online'] for board in response.json()},
            {DEVICE_ID: True, OTHER_DEVICE_ID: False},
        )
        self.assertTrue(Rotor.objects.get(device_id=DEVICE_ID).online)

    def test_an_unknown_status_does_not_register_the_board(self, scan):
        scan.return_value = {DEVICE_ID: b'garbage'}

        with self.assertLogs('server_core.device_state', level='WARNING'):
            response = self.client.post('/api/boards/scan')

        self.assertEqual(response.json(), [])

    def test_an_unreachable_broker_is_service_unavailable(self, scan):
        scan.side_effect = BrokerUnavailable('connection refused')

        with self.assertLogs('server_core.api', level='WARNING'):
            response = self.client.post('/api/boards/scan')

        self.assertEqual(response.status_code, 503)

    def test_only_post_scans(self, scan):
        self.assertEqual(self.client.get('/api/boards/scan').status_code, 405)
        scan.assert_not_called()


class PluginBoardTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')

    def url(self, plugin=None):
        return f'/api/plugins/{(plugin or self.plugin).plugin_uuid}/board'

    def put(self, body, plugin=None):
        return self.client.put(self.url(plugin), data=json.dumps(body), content_type='application/json')

    def test_binds_a_registered_board(self):
        response = self.put({'device_id': DEVICE_ID})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['board'], DEVICE_ID)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.rotor, self.rotor)

    def test_unbinds(self):
        self.plugin.rotor = self.rotor
        self.plugin.save()

        response = self.client.delete(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['board'])
        self.plugin.refresh_from_db()
        self.assertIsNone(self.plugin.rotor)

    def test_an_unregistered_board_is_not_found(self):
        self.assertEqual(self.put({'device_id': OTHER_DEVICE_ID}).status_code, 404)

    def test_a_malformed_device_id_is_rejected(self):
        response = self.put({'device_id': 'A1:B2:C3:D4:E5:F6'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'device_id': ['device_id must be twelve lowercase hex digits.']})
        self.assertEqual(self.put(['nope']).status_code, 400)

    def test_an_unknown_plugin_is_not_found(self):
        response = self.client.put('/api/plugins/00000000-0000-4000-8000-000000000000/board',
                                   data=json.dumps({'device_id': DEVICE_ID}), content_type='application/json')
        self.assertEqual(response.status_code, 404)

    def test_a_running_plugin_keeps_its_board(self):
        self.plugin.status = PluginInstance.Status.RUNNING
        self.plugin.save()

        self.assertEqual(self.put({'device_id': DEVICE_ID}).status_code, 409)
        self.assertEqual(self.client.delete(self.url()).status_code, 409)

    def test_a_board_driven_by_another_running_plugin_is_taken(self):
        running_plugin(name='tinygs-2', rotor=self.rotor)

        self.assertEqual(self.put({'device_id': DEVICE_ID}).status_code, 409)
        self.plugin.refresh_from_db()
        self.assertIsNone(self.plugin.rotor)


class RecordStatusTests(SimpleTestCase):
    def test_keeps_retained_statuses_by_device(self):
        boards = {}

        self.assertTrue(record_status(boards, f'device/{DEVICE_ID}/status', b'online', retain=True))
        self.assertEqual(boards, {DEVICE_ID: b'online'})

    def test_ignores_live_messages_and_other_topics(self):
        boards = {}

        self.assertFalse(record_status(boards, f'device/{DEVICE_ID}/status', b'online', retain=False))
        self.assertFalse(record_status(boards, f'device/{DEVICE_ID}/state', b'{}', retain=True))
        self.assertFalse(record_status(boards, 'device/not-a-mac/status', b'online', retain=True))
        self.assertEqual(boards, {})


class FakeClient:
    """Plays the broker: acknowledges the connection and the subscription, then
    delivers the retained messages, the way mosquitto does after a SUBACK."""

    def __init__(self, retained=(), connect_error=None, connect_code=0):
        self.retained = retained
        self.connect_error = connect_error
        self.connect_code = connect_code
        self.disconnected = False

    def username_pw_set(self, username, password):
        self.credentials = (username, password)

    def connect(self, host, port, keepalive=60):
        if self.connect_error:
            raise self.connect_error

    def loop_start(self):
        self.on_connect(self, None, None, self.connect_code)

    def subscribe(self, topic, qos=0):
        self.on_subscribe(self, None, 1, [0])
        for topic, payload in self.retained:
            self.on_message(self, None, SimpleNamespace(topic=topic, payload=payload, retain=True))

    def disconnect(self):
        self.disconnected = True

    def loop_stop(self):
        pass


class ScanBoardsTests(SimpleTestCase):
    def scan(self, client):
        with patch('server_core.board_scan.mqtt.Client', return_value=client):
            return scan_boards(timeout=1.0, quiet=0.05)

    def test_returns_every_retained_status(self):
        client = FakeClient(retained=[
            (f'device/{DEVICE_ID}/status', b'online'),
            (f'device/{OTHER_DEVICE_ID}/status', b'offline'),
        ])

        self.assertEqual(self.scan(client), {DEVICE_ID: b'online', OTHER_DEVICE_ID: b'offline'})
        self.assertTrue(client.disconnected)

    def test_no_boards_ends_after_the_quiet_period(self):
        self.assertEqual(self.scan(FakeClient()), {})

    def test_an_unreachable_broker_raises(self):
        with self.assertRaises(BrokerUnavailable):
            self.scan(FakeClient(connect_error=ConnectionRefusedError('refused')))

    def test_a_refused_connection_raises(self):
        with self.assertRaises(BrokerUnavailable):
            self.scan(FakeClient(connect_code=5))


class PluginRotorTests(TestCase):
    def get(self, token):
        return self.client.get('/api/plugin/rotor', HTTP_AUTHORIZATION=f'Plugin {token}')

    def test_returns_the_bound_board_and_its_limits(self):
        rotor = Rotor.objects.create(device_id=DEVICE_ID, min_elevation_deg=12.5,
                                     min_azimuth_deg=300.0, max_azimuth_deg=60.0)
        _, token = running_plugin(rotor=rotor)

        response = self.get(token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'device_id': DEVICE_ID, 'min_elevation_deg': 12.5,
            'min_azimuth_deg': 300.0, 'max_azimuth_deg': 60.0,
        })

    def test_without_a_board_it_is_null(self):
        _, token = running_plugin()

        response = self.get(token)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_needs_a_plugin_token(self):
        self.assertEqual(self.client.get('/api/plugin/rotor').status_code, 401)


def order(**overrides):
    document = {'kind': 'BATCH', 't0_ms': 1789763400000, 't_sent_ms': 1789763398012,
                'points': [[0, 27000, 3000], [1000, 27050, 3010]], 'reason': ''}
    document.update(overrides)
    return document


HOLD = {'kind': 'HOLD', 't0_ms': 1789763712000, 't_sent_ms': 1789763712000, 'points': [], 'reason': 'limits'}


class DispatchOrdersTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin, self.token = running_plugin(rotor=self.rotor)

    def post(self, body, token=None):
        return self.client.post('/api/dispatch-orders', data=json.dumps(body), content_type='application/json',
                                HTTP_AUTHORIZATION=f'Plugin {token or self.token}')

    def test_stores_a_batch_under_the_bound_board(self):
        response = self.post(order())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {'stored': 1})
        row = DispatchOrder.objects.get()
        self.assertEqual((row.rotor, row.plugin, row.kind), (self.rotor, self.plugin, 'BATCH'))
        self.assertEqual(row.points, [[0, 27000, 3000], [1000, 27050, 3010]])
        # The instant the batch covers up to, as mqtt_dispatch records it.
        self.assertEqual(row.t_end_ms, 1789763401000)

    def test_a_list_is_stored_whole(self):
        response = self.post([order(), HOLD, dict(HOLD, reason='stopped')])

        self.assertEqual(response.json(), {'stored': 3})
        self.assertEqual(list(DispatchOrder.objects.order_by('pk').values_list('kind', 'reason')),
                         [('BATCH', ''), ('HOLD', 'limits'), ('HOLD', 'stopped')])

    def test_one_bad_order_rejects_the_whole_list(self):
        response = self.post([order(), order(points=[])])

        self.assertEqual(response.status_code, 400)
        self.assertFalse(DispatchOrder.objects.exists())

    def test_orders_must_have_the_shape_the_board_accepts(self):
        for bad in (
            order(points=[]),                                  # a batch without points
            dict(HOLD, points=[[0, 0, 0]]),                    # a HOLD with points
            dict(HOLD, reason=''),                             # a HOLD without a reason
            order(points=[[0, 36000, 0]]),                     # azimuth out of range
            order(points=[[0, 0, 9001]]),                      # elevation out of range
            order(points=[[0, 0]]),                            # a point is three numbers
            order(points=[[index * 1000, 0, 0] for index in range(17)]),  # more than 16
            order(kind='MOVE'),
            order(reason='bored'),
        ):
            with self.subTest(order=bad):
                self.assertEqual(self.post(bad).status_code, 400)
        self.assertFalse(DispatchOrder.objects.exists())

    def test_an_instance_without_a_board_is_forbidden(self):
        _, token = running_plugin(name='no-board')

        self.assertEqual(self.post(order(), token=token).status_code, 403)

    def test_a_list_has_a_size_limit(self):
        self.assertEqual(self.post([]).status_code, 400)
        self.assertEqual(self.post([order()] * (MAX_BATCH + 1)).status_code, 400)


class SchemaTests(TestCase):
    def test_the_openapi_schema_and_its_ui_are_served(self):
        self.assertEqual(self.client.get('/api/schema').status_code, 200)
        self.assertEqual(self.client.get('/api/docs').status_code, 200)
