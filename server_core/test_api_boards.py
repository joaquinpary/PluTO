"""The board endpoints of the front end: detail and limits, live state and the pass in course."""
import json
from datetime import datetime, timedelta, timezone

from django.test import Client, SimpleTestCase

from .models import DispatchOrder, PluginData, PluginInstance, Rotor, RotorState
from .plugin_handlers.tinygs import satellite_from_tracking
from .test_api import DEVICE_ID, OTHER_DEVICE_ID, FrontTestCase, running_plugin

BOARD_KEYS = {
    'device_id', 'name', 'online', 'status_changed_at', 'last_state_at',
    'latitude_deg', 'longitude_deg', 'altitude_m',
    'min_elevation_deg', 'min_azimuth_deg', 'max_azimuth_deg', 'plugins',
}
LIVE_STATE_KEYS = {
    'received_at', 'mode', 'az_cdeg', 'el_cdeg', 'pan_mode', 'batch_accepted', 'batch_error',
    'clock_synced', 'rejected_total', 'meas', 'err_cdeg',
}
T0 = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)


def at(seconds):
    # Explicit times: received_at and created_at default to the database's
    # now(), which PostgreSQL keeps fixed for the whole test transaction.
    return T0 + timedelta(seconds=seconds)


def state(rotor, seconds, **fields):
    return RotorState.objects.create(rotor=rotor, received_at=at(seconds), **fields)


def order(rotor, plugin, seconds, kind=DispatchOrder.Kind.BATCH, t0_ms=0, points=(), reason=''):
    points = [list(point) for point in points]
    return DispatchOrder.objects.create(
        rotor=rotor, plugin=plugin, kind=kind, t0_ms=t0_ms, t_sent_ms=t0_ms,
        t_end_ms=t0_ms + (points[-1][0] if points else 0), points=points, reason=reason,
        created_at=at(seconds),
    )


class BoardDetailTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID, name='Terraza')
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs', rotor=self.rotor)
        self.url = f'/api/boards/{DEVICE_ID}'

    def patch(self, body):
        return self.client.patch(self.url, data=json.dumps(body), content_type='application/json')

    def test_shows_the_board_with_its_settings_and_instances(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        board = response.json()
        self.assertEqual(set(board), BOARD_KEYS)
        self.assertEqual((board['name'], board['min_elevation_deg'], board['latitude_deg']), ('Terraza', 10, None))
        self.assertEqual(board['plugins'], [
            {'plugin_uuid': str(self.plugin.plugin_uuid), 'name': 'tinygs-1', 'status': 'STOPPED'},
        ])

    def test_an_unknown_board_is_not_found(self):
        url = f'/api/boards/{OTHER_DEVICE_ID}'

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, data='{}', content_type='application/json').status_code, 404)

    def test_edits_the_name_the_location_and_the_elevation(self):
        response = self.patch({'name': 'Patio', 'latitude_deg': -31.4, 'longitude_deg': -64.2, 'altitude_m': 400,
                               'min_elevation_deg': 15})

        self.assertEqual(response.status_code, 200)
        self.rotor.refresh_from_db()
        self.assertEqual(
            (self.rotor.name, self.rotor.latitude_deg, self.rotor.longitude_deg, self.rotor.altitude_m,
             self.rotor.min_elevation_deg),
            ('Patio', -31.4, -64.2, 400, 15),
        )

    def test_out_of_range_values_are_rejected_by_field(self):
        response = self.patch({'latitude_deg': 91, 'longitude_deg': -181, 'min_elevation_deg': 95,
                               'min_azimuth_deg': 361, 'max_azimuth_deg': 10})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {'latitude_deg', 'longitude_deg', 'min_elevation_deg', 'min_azimuth_deg'})

    def test_what_the_board_reports_is_read_only(self):
        response = self.patch({'device_id': OTHER_DEVICE_ID, 'online': True})

        self.assertEqual(response.status_code, 200)
        self.rotor.refresh_from_db()
        self.assertEqual((self.rotor.device_id, self.rotor.online), (DEVICE_ID, False))

    def test_needs_a_login(self):
        self.assertEqual(Client().get(self.url).status_code, 401)


class AzimuthWindowTests(FrontTestCase):
    """REVIEW FOCUS 3: a window through north is saved; half a window is not."""

    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)

    def patch(self, body):
        return self.client.patch(f'/api/boards/{DEVICE_ID}', data=json.dumps(body), content_type='application/json')

    def test_a_window_through_north_is_saved(self):
        response = self.patch({'min_azimuth_deg': 300, 'max_azimuth_deg': 60})

        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()['min_azimuth_deg'], response.json()['max_azimuth_deg']), (300, 60))
        self.rotor.refresh_from_db()
        # Stored as given: the plugin reads it through pluto_sdk.pointing.RotorLimits,
        # whose own tests cover the wrap through north.
        self.assertEqual((self.rotor.min_azimuth_deg, self.rotor.max_azimuth_deg), (300, 60))

    def test_half_a_window_is_rejected(self):
        response = self.patch({'min_azimuth_deg': 300})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(response.json()), ['non_field_errors'])
        self.rotor.refresh_from_db()
        self.assertIsNone(self.rotor.min_azimuth_deg)

    def test_clearing_one_end_of_a_saved_window_is_rejected(self):
        Rotor.objects.filter(pk=self.rotor.pk).update(min_azimuth_deg=300, max_azimuth_deg=60)

        response = self.patch({'max_azimuth_deg': None})

        self.assertEqual(response.status_code, 400)
        self.rotor.refresh_from_db()
        self.assertEqual(self.rotor.max_azimuth_deg, 60)

    def test_clearing_both_ends_removes_the_window(self):
        Rotor.objects.filter(pk=self.rotor.pk).update(min_azimuth_deg=300, max_azimuth_deg=60)

        response = self.patch({'min_azimuth_deg': None, 'max_azimuth_deg': None})

        self.assertEqual(response.status_code, 200)
        self.rotor.refresh_from_db()
        self.assertEqual((self.rotor.min_azimuth_deg, self.rotor.max_azimuth_deg), (None, None))


class BoardWithoutDataTests(FrontTestCase):
    """REVIEW FOCUS 2: a board that registered but never sent a state."""

    def setUp(self):
        super().setUp()
        Rotor.objects.create(device_id=DEVICE_ID)

    def test_live_answers_without_a_state(self):
        response = self.client.get('/api/boards/live')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{
            'device_id': DEVICE_ID, 'name': '', 'online': False, 'status_changed_at': None, 'last_state_at': None,
            'state': None, 'running_plugin': None, 'satellite': None, 'last_hold_reason': None,
        }])

    def test_its_detail_answers_too(self):
        response = self.client.get(f'/api/boards/{DEVICE_ID}')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['last_state_at'])


class BoardsLiveTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID, name='Terraza', online=True)
        self.other = Rotor.objects.create(device_id=OTHER_DEVICE_ID)

    def live(self, device_id=DEVICE_ID):
        response = self.client.get('/api/boards/live')
        self.assertEqual(response.status_code, 200)
        return {board['device_id']: board for board in response.json()}[device_id]

    def test_each_board_shows_its_latest_state(self):
        state(self.rotor, 0, mode='holding', az_cdeg=100, el_cdeg=200)
        state(self.rotor, 10, mode='tracking', az_cdeg=27000, el_cdeg=3000, pan_mode='normal',
              batch_accepted=False, batch_error='all_expired', clock_synced=True, rejected_total=2)
        state(self.other, 20, mode='idle')

        live_state = self.live()['state']

        self.assertEqual(set(live_state), LIVE_STATE_KEYS)
        self.assertEqual(
            (live_state['mode'], live_state['az_cdeg'], live_state['el_cdeg'], live_state['batch_accepted'],
             live_state['batch_error'], live_state['rejected_total']),
            ('tracking', 27000, 3000, False, 'all_expired', 2),
        )
        self.assertEqual((live_state['meas'], live_state['err_cdeg']), (None, None))
        self.assertEqual(self.live(OTHER_DEVICE_ID)['state']['mode'], 'idle')

    def test_meas_and_err_come_from_the_document_of_a_board_with_encoders(self):
        state(self.rotor, 0, mode='tracking', payload={'meas': {'az_cdeg': 12310, 'el_cdeg': 4472}, 'err_cdeg': 37})

        live_state = self.live()['state']

        self.assertEqual(live_state['meas'], {'az_cdeg': 12310, 'el_cdeg': 4472})
        self.assertEqual(live_state['err_cdeg'], 37)

    def test_a_malformed_meas_is_left_out(self):
        state(self.rotor, 0, payload={'meas': {'az_cdeg': 'north'}, 'err_cdeg': True})

        live_state = self.live()['state']

        self.assertEqual((live_state['meas'], live_state['err_cdeg']), (None, None))

    def test_the_running_instance_and_the_satellite_it_follows(self):
        stopped = PluginInstance.objects.create(name='old', plugin_type='tinygs', rotor=self.rotor)
        PluginData.objects.create(plugin=stopped, message_type='tracking',
                                  payload={'satellite': 'ISS', 'NORAD': 25544}, created_at=at(30))
        plugin, _ = running_plugin(rotor=self.rotor)
        PluginData.objects.create(plugin=plugin, message_type='tracking',
                                  payload={'satellite': 'ISS', 'NORAD': 25544}, created_at=at(0))
        PluginData.objects.create(plugin=plugin, message_type='tracking',
                                  payload={'satellite': 'NOAA 19', 'NORAD': 33591}, created_at=at(10))
        PluginData.objects.create(plugin=plugin, message_type='rx', payload={'rssi': -97}, created_at=at(20))

        board = self.live()

        self.assertEqual(board['running_plugin'],
                         {'plugin_uuid': str(plugin.plugin_uuid), 'name': 'tinygs-1', 'plugin_type': 'tinygs'})
        self.assertEqual(board['satellite'], {'name': 'NOAA 19', 'norad': 33591})
        self.assertIsNone(self.live(OTHER_DEVICE_ID)['running_plugin'])

    def test_without_a_running_instance_there_is_no_satellite(self):
        stopped = PluginInstance.objects.create(name='old', plugin_type='tinygs', rotor=self.rotor)
        PluginData.objects.create(plugin=stopped, message_type='tracking', payload={'satellite': 'ISS', 'NORAD': 25544})

        board = self.live()

        self.assertEqual((board['running_plugin'], board['satellite']), (None, None))

    def test_a_tracking_message_without_a_satellite_gives_none(self):
        plugin, _ = running_plugin(rotor=self.rotor)
        PluginData.objects.create(plugin=plugin, message_type='tracking', payload={'station': 'My TinyGS'})

        self.assertIsNone(self.live()['satellite'])

    def test_the_reason_of_the_latest_hold(self):
        plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')
        order(self.rotor, plugin, 0, kind=DispatchOrder.Kind.HOLD, reason='end')
        order(self.rotor, plugin, 10, kind=DispatchOrder.Kind.HOLD, reason='limits')
        order(self.rotor, plugin, 20, t0_ms=1_000, points=[(0, 100, 200)])
        order(self.other, plugin, 30, kind=DispatchOrder.Kind.HOLD, reason='expired')

        self.assertEqual(self.live()['last_hold_reason'], 'limits')
        self.assertEqual(self.live(OTHER_DEVICE_ID)['last_hold_reason'], 'expired')

    def test_needs_a_login(self):
        self.assertEqual(Client().get('/api/boards/live').status_code, 401)


class SatelliteFromTrackingTests(SimpleTestCase):
    """Whatever the station sent, the live view gets a satellite or None, never an exception."""

    def test_reads_the_name_and_the_norad(self):
        payload = {'station': 'My TinyGS', 'satellite': 'NOAA 19', 'NORAD': 33591, 'mode': 'LoRa'}

        self.assertEqual(satellite_from_tracking(payload), {'name': 'NOAA 19', 'norad': 33591})

    def test_keeps_what_it_can(self):
        self.assertEqual(satellite_from_tracking({'satellite': 'NOAA 19'}), {'name': 'NOAA 19', 'norad': None})
        self.assertEqual(satellite_from_tracking({'NORAD': 33591}), {'name': None, 'norad': 33591})

    def test_nothing_to_follow_is_none(self):
        payloads = [
            None, 'not an object', {}, {'station': 'My TinyGS'}, {'value': 'text'},
            {'satellite': 'Waiting', 'NORAD': 46494}, {'satellite': 7, 'NORAD': True},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(satellite_from_tracking(payload))


class BoardTrackTests(FrontTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.other = Rotor.objects.create(device_id=OTHER_DEVICE_ID)
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')

    def track(self, device_id=DEVICE_ID):
        response = self.client.get(f'/api/boards/{device_id}/track')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_the_setpoints_since_the_last_hold_with_overlaps_resolved(self):
        order(self.rotor, self.plugin, 0, t0_ms=1_000, points=[(0, 100, 200), (1_000, 110, 210)])
        order(self.rotor, self.plugin, 5, kind=DispatchOrder.Kind.HOLD, t0_ms=3_000, reason='end')
        order(self.rotor, self.plugin, 10, t0_ms=50_000,
              points=[(0, 9_000, 1_000), (1_000, 9_100, 1_100), (2_000, 9_200, 1_200)])
        # Overlaps the previous batch at 52 000: the later message is the one in effect.
        order(self.rotor, self.plugin, 11, t0_ms=52_000, points=[(0, 9_250, 1_250), (1_000, 9_300, 1_300)])
        order(self.other, self.plugin, 12, t0_ms=50_000, points=[(0, 1, 1)])

        self.assertEqual(self.track(), {'device_id': DEVICE_ID, 'points': [
            {'t_ms': 50_000, 'az_cdeg': 9_000, 'el_cdeg': 1_000},
            {'t_ms': 51_000, 'az_cdeg': 9_100, 'el_cdeg': 1_100},
            {'t_ms': 52_000, 'az_cdeg': 9_250, 'el_cdeg': 1_250},
            {'t_ms': 53_000, 'az_cdeg': 9_300, 'el_cdeg': 1_300},
        ]})

    def test_a_pass_that_ended_leaves_no_track(self):
        order(self.rotor, self.plugin, 0, t0_ms=1_000, points=[(0, 100, 200)])
        order(self.rotor, self.plugin, 5, kind=DispatchOrder.Kind.HOLD, t0_ms=3_000, reason='end')

        self.assertEqual(self.track()['points'], [])

    def test_before_any_hold_every_batch_counts(self):
        order(self.rotor, self.plugin, 0, t0_ms=1_000, points=[(0, 100, 200)])
        order(self.rotor, self.plugin, 1, t0_ms=2_000, points=[(0, 110, 210)])

        self.assertEqual([point['t_ms'] for point in self.track()['points']], [1_000, 2_000])

    def test_a_board_without_orders_has_an_empty_track(self):
        """REVIEW FOCUS 2: nothing sent yet is an empty track, not an error."""
        self.assertEqual(self.track(OTHER_DEVICE_ID), {'device_id': OTHER_DEVICE_ID, 'points': []})

    def test_an_unknown_board_is_not_found(self):
        self.assertEqual(self.client.get('/api/boards/ffffffffffff/track').status_code, 404)
