import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from .device_state import parse_device_topic, store_state, store_status
from .management.commands.mqtt_ingest import Command
from .models import Rotor, RotorState

DEVICE_ID = 'a1b2c3d4e5f6'

# What the firmware publishes right after accepting a batch (device-state.md §3).
STATE = {
    'v': 1,
    'ts_ms': 1789763398140,
    'clock_synced': True,
    'mode': 'tracking',
    'az_cdeg': 27000,
    'el_cdeg': 3000,
    'pan_mode': 'flipped',
    'batch': {
        't_sent_ms': 1789763398000,
        'received_ms': 1789763398140,
        'latency_ms': 140,
        'accepted': True,
        'error': None,
    },
    'rejected_total': 2,
}


def state(**overrides):
    document = dict(STATE, **overrides)
    return json.dumps(document).encode()


class ParseDeviceTopicTests(SimpleTestCase):
    def test_parses_status_and_state(self):
        self.assertEqual(parse_device_topic(f'device/{DEVICE_ID}/status'), (DEVICE_ID, 'status'))
        self.assertEqual(parse_device_topic(f'device/{DEVICE_ID}/state'), (DEVICE_ID, 'state'))

    def test_rejects_anything_else(self):
        for topic in (
            'device/subscription',
            f'device/{DEVICE_ID}/coordinates/polar',
            f'device/{DEVICE_ID.upper()}/state',
            f'device/{DEVICE_ID[:-1]}/state',
            f'device/{DEVICE_ID}/health',
            f'plugin/{DEVICE_ID}/state',
        ):
            with self.subTest(topic=topic):
                self.assertIsNone(parse_device_topic(topic))


class StoreStatusTests(TestCase):
    def test_online_registers_the_board(self):
        self.assertTrue(store_status(DEVICE_ID, b'online'))

        rotor = Rotor.objects.get(device_id=DEVICE_ID)
        self.assertTrue(rotor.online)
        self.assertIsNotNone(rotor.status_changed_at)

    def test_a_repeated_retained_status_does_not_move_the_timestamp(self):
        store_status(DEVICE_ID, b'online')
        first = Rotor.objects.get().status_changed_at

        store_status(DEVICE_ID, b'online')

        self.assertEqual(Rotor.objects.get().status_changed_at, first)

    def test_offline_from_the_last_will(self):
        store_status(DEVICE_ID, b'online')

        self.assertTrue(store_status(DEVICE_ID, b'offline'))

        self.assertFalse(Rotor.objects.get().online)

    def test_anything_else_is_rejected_without_registering(self):
        with self.assertLogs('server_core.device_state', level='WARNING'):
            self.assertFalse(store_status(DEVICE_ID, b'maybe'))
        self.assertFalse(Rotor.objects.exists())


class StoreStateTests(TestCase):
    def test_stores_the_fields_and_the_whole_document(self):
        self.assertTrue(store_state(DEVICE_ID, state()))

        row = RotorState.objects.get()
        self.assertEqual(row.rotor.device_id, DEVICE_ID)
        self.assertEqual((row.mode, row.az_cdeg, row.el_cdeg, row.pan_mode), ('tracking', 27000, 3000, 'flipped'))
        self.assertEqual((row.batch_accepted, row.batch_error, row.latency_ms), (True, '', 140))
        self.assertEqual(row.rejected_total, 2)
        self.assertEqual(row.board_time, datetime(2026, 9, 18, 20, 29, 58, 140000, tzinfo=timezone.utc))
        self.assertEqual(row.payload, STATE)
        self.assertIsNotNone(Rotor.objects.get().last_state_at)

    def test_a_rejected_batch(self):
        store_state(DEVICE_ID, state(batch={'t_sent_ms': None, 'received_ms': 1, 'latency_ms': None,
                                            'accepted': False, 'error': 'bad_magic'}))

        row = RotorState.objects.get()
        self.assertEqual((row.batch_accepted, row.batch_error, row.latency_ms), (False, 'bad_magic', None))

    def test_board_time_is_dropped_without_a_synced_clock(self):
        store_state(DEVICE_ID, state(clock_synced=False, ts_ms=12345))

        self.assertIsNone(RotorState.objects.get().board_time)

    def test_an_idle_board_without_position_or_batch(self):
        store_state(DEVICE_ID, state(mode='idle', az_cdeg=None, el_cdeg=None, pan_mode=None, batch=None))

        row = RotorState.objects.get()
        self.assertEqual((row.az_cdeg, row.el_cdeg, row.pan_mode, row.batch_accepted), (None, None, '', None))

    def test_unexpected_types_are_stored_empty(self):
        store_state(DEVICE_ID, state(az_cdeg='27000', clock_synced='yes', rejected_total=True, mode=7))

        row = RotorState.objects.get()
        self.assertEqual((row.az_cdeg, row.clock_synced, row.rejected_total, row.mode), (None, False, 0, ''))

    def test_non_objects_are_rejected(self):
        for payload in (b'{"v": 1', b'[1, 2]', b'\xff'):
            with self.subTest(payload=payload), self.assertLogs('server_core.device_state', level='WARNING'):
                self.assertFalse(store_state(DEVICE_ID, payload))
        self.assertFalse(Rotor.objects.exists())


@patch('server_core.management.commands.mqtt_ingest.close_old_connections')
class DeviceMessageRoutingTests(TestCase):
    def setUp(self):
        self.command = Command()
        self.command.stats = {'ingested': 0, 'duplicate': 0, 'device_updates': 0, 'rejected': 0, 'failed': 0}

    def deliver(self, topic, payload):
        self.command.on_message(None, None, SimpleNamespace(topic=topic, payload=payload))

    def test_status_and_state_reach_the_database(self, _close):
        self.deliver(f'device/{DEVICE_ID}/status', b'online')
        self.deliver(f'device/{DEVICE_ID}/state', state())

        self.assertTrue(Rotor.objects.get().online)
        self.assertEqual(RotorState.objects.count(), 1)
        self.assertEqual(self.command.stats['device_updates'], 2)

    def test_unexpected_device_topics_are_rejected(self, _close):
        with self.assertLogs('server_core.management.commands.mqtt_ingest', level='WARNING'):
            self.deliver('device/subscription', DEVICE_ID.encode())

        self.assertEqual(self.command.stats['rejected'], 1)
        self.assertFalse(Rotor.objects.exists())

    def test_an_invalid_state_counts_as_rejected(self, _close):
        with self.assertLogs('server_core.device_state', level='WARNING'):
            self.deliver(f'device/{DEVICE_ID}/state', b'not json')

        self.assertEqual(self.command.stats['rejected'], 1)
