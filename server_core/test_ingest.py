import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from .management.commands.mqtt_ingest import (
    DUPLICATE,
    INGEST_TOPIC,
    INGESTED,
    UNKNOWN_PLUGIN,
    Command,
    build_document_fields,
    parse_ingest_topic,
    store_message,
    wait_for_migrations,
)
from .models import PluginData, PluginInstance

LOGGER = 'server_core.management.commands.mqtt_ingest'
MODULE = 'server_core.management.commands.mqtt_ingest'


class ParseIngestTopicTests(SimpleTestCase):
    def test_parses_valid_ingest_topic(self):
        self.assertEqual(
            parse_ingest_topic('plugin/3f2a-uuid/data/tracking'),
            ('3f2a-uuid', 'tracking'),
        )

    def test_rejects_topic_with_wrong_depth(self):
        self.assertIsNone(parse_ingest_topic('plugin/3f2a-uuid/data'))
        self.assertIsNone(parse_ingest_topic('plugin/3f2a-uuid/data/tracking/extra'))

    def test_rejects_other_namespaces(self):
        self.assertIsNone(parse_ingest_topic('plugin/3f2a-uuid/coordinates/raw'))
        self.assertIsNone(parse_ingest_topic('pluto/heltec-lp-01/tracking'))

    def test_rejects_invalid_message_type(self):
        self.assertIsNone(parse_ingest_topic('plugin/3f2a-uuid/data/..'))
        self.assertIsNone(parse_ingest_topic('plugin/3f2a-uuid/data/TRACKING'))
        self.assertIsNone(parse_ingest_topic('plugin/3f2a-uuid/data/'))


def envelope(**overrides):
    payload = {
        'schema_version': 1,
        'message_id': 'msg-1',
        'plugin_id': '3f2a-uuid',
        'plugin_type': 'tinygs',
        'device': 'heltec-lp-01',
        'message_type': 'tracking',
        'source_topic': 'pluto/heltec-lp-01/tracking',
        'received_at': '2026-09-12T18:03:11+00:00',
        'payload_format': 'json',
        'payload': {'az': 1.0},
    }
    payload.update(overrides)
    return json.dumps(payload).encode('utf-8')


class BuildDocumentFieldsTests(SimpleTestCase):
    def test_builds_fields_from_valid_envelope(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/tracking', envelope())

        self.assertEqual(fields['plugin_id'], '3f2a-uuid')
        self.assertEqual(fields['message_type'], 'tracking')
        self.assertEqual(fields['device'], 'heltec-lp-01')
        self.assertEqual(fields['payload'], {'az': 1.0})
        self.assertEqual(fields['ingest_topic'], 'plugin/3f2a-uuid/data/tracking')

    def test_plugin_id_from_topic_wins_over_envelope(self):
        with self.assertLogs(LOGGER, level='WARNING'):
            fields = build_document_fields(
                'plugin/real-uuid/data/tracking',
                envelope(plugin_id='spoofed-uuid'),
            )

        self.assertEqual(fields['plugin_id'], 'real-uuid')

    def test_message_type_comes_from_topic(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/rx', envelope(message_type='tracking'))

        self.assertEqual(fields['message_type'], 'rx')

    def test_wraps_non_dict_payload(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/rx', envelope(payload=[1, 2]))

        self.assertEqual(fields['payload'], {'value': [1, 2]})
        self.assertEqual(fields['payload_format'], 'coerced')

    def test_returns_none_for_invalid_json(self):
        with self.assertLogs(LOGGER, level='WARNING'):
            self.assertIsNone(build_document_fields('plugin/3f2a-uuid/data/rx', b'{"roto'))

    def test_returns_none_for_undecodable_bytes(self):
        with self.assertLogs(LOGGER, level='WARNING'):
            self.assertIsNone(build_document_fields('plugin/3f2a-uuid/data/rx', b'\xff\xfe'))

    def test_returns_none_for_non_object_envelope(self):
        with self.assertLogs(LOGGER, level='WARNING'):
            self.assertIsNone(build_document_fields('plugin/3f2a-uuid/data/rx', b'[1, 2]'))

    def test_returns_none_for_unexpected_topic(self):
        with self.assertLogs(LOGGER, level='WARNING'):
            self.assertIsNone(build_document_fields('plugin/3f2a-uuid/coordinates/raw', envelope()))

    def test_normalizes_datetime_to_aware_utc(self):
        fields = build_document_fields(
            'plugin/3f2a-uuid/data/tracking',
            envelope(received_at='2026-09-12T15:03:11-03:00'),
        )

        self.assertEqual(fields['received_at'], datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc))

    def test_datetime_without_offset_is_taken_as_utc(self):
        fields = build_document_fields(
            'plugin/3f2a-uuid/data/tracking',
            envelope(received_at='2026-09-12T18:03:11'),
        )

        self.assertEqual(fields['received_at'], datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc))

    def test_missing_received_at_is_tolerated(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/tracking', envelope(received_at=None))

        self.assertIsNone(fields['received_at'])

    def test_unknown_envelope_keys_are_dropped(self):
        fields = build_document_fields(
            'plugin/3f2a-uuid/data/tracking',
            envelope(created_at='hacked', evil='x'),
        )

        self.assertNotIn('created_at', fields)
        self.assertNotIn('evil', fields)

    def test_plugin_type_is_not_copied(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/tracking', envelope())

        self.assertNotIn('plugin_type', fields)


class StoreMessageTests(TestCase):
    def setUp(self):
        self.plugin = PluginInstance.objects.create(name='tinygs-0', plugin_type='tinygs')
        self.topic = f'plugin/{self.plugin.plugin_uuid}/data/rx'

    def fields(self, **overrides):
        return build_document_fields(self.topic, envelope(**overrides))

    def test_stores_the_row_linked_to_its_plugin(self):
        self.assertEqual(store_message(self.fields(payload={'rssi': -97})), INGESTED)

        row = PluginData.objects.get()
        self.assertEqual(row.plugin, self.plugin)
        self.assertEqual(row.message_type, 'rx')
        self.assertEqual(row.payload, {'rssi': -97})
        self.assertEqual(row.received_at, datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc))

    def test_redelivery_is_reported_as_duplicate_and_stored_once(self):
        store_message(self.fields())

        self.assertEqual(store_message(self.fields()), DUPLICATE)
        self.assertEqual(PluginData.objects.count(), 1)

    def test_uuid_without_plugin_instance_is_not_stored(self):
        fields = build_document_fields('plugin/00000000-0000-4000-8000-000000000000/data/rx', envelope())

        self.assertEqual(store_message(fields), UNKNOWN_PLUGIN)
        self.assertFalse(PluginData.objects.exists())

    def test_non_uuid_plugin_id_is_not_stored(self):
        fields = build_document_fields('plugin/no-es-uuid/data/rx', envelope())

        self.assertEqual(store_message(fields), UNKNOWN_PLUGIN)
        self.assertFalse(PluginData.objects.exists())

    def test_minimal_envelope_takes_the_model_defaults(self):
        fields = build_document_fields(self.topic, b'{"payload": {"x": 1}}')

        store_message(fields)

        row = PluginData.objects.get()
        self.assertEqual((row.device, row.payload_format, row.schema_version), ('', 'json', 1))
        self.assertIsNone(row.message_id)


@patch(f'{MODULE}.close_old_connections')
class MessageHandlingTests(TestCase):
    def setUp(self):
        self.plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')
        self.command = Command()
        self.command.stats = {'ingested': 0, 'duplicate': 0, 'rejected': 0, 'failed': 0}

    def message(self, topic=None, payload=None):
        topic = topic or f'plugin/{self.plugin.plugin_uuid}/data/tracking'
        return SimpleNamespace(topic=topic, payload=payload or envelope())

    def test_valid_message_is_stored(self, _close):
        self.command.on_message(None, None, self.message())

        self.assertEqual(self.plugin.data.count(), 1)
        self.assertEqual(self.command.stats['ingested'], 1)

    def test_redelivered_message_counts_as_duplicate(self, _close):
        self.command.on_message(None, None, self.message())
        self.command.on_message(None, None, self.message())

        self.assertEqual(self.plugin.data.count(), 1)
        self.assertEqual(self.command.stats['duplicate'], 1)
        self.assertEqual(self.command.stats['failed'], 0)

    def test_unknown_plugin_is_rejected(self, _close):
        with self.assertLogs(LOGGER, level='WARNING'):
            self.command.on_message(None, None, self.message(topic='plugin/00000000-0000-4000-8000-000000000000/data/rx'))

        self.assertEqual(self.command.stats['rejected'], 1)

    def test_malformed_message_does_not_raise_and_does_not_store(self, _close):
        with self.assertLogs(LOGGER, level='WARNING'):
            self.command.on_message(None, None, self.message(payload=b'{"roto'))

        self.assertFalse(PluginData.objects.exists())
        self.assertEqual(self.command.stats['rejected'], 1)

    def test_database_failure_is_logged_and_swallowed(self, _close):
        with patch(f'{MODULE}.store_message', side_effect=OperationalError('postgres caido')):
            with self.assertLogs(LOGGER, level='ERROR'):
                self.command.on_message(None, None, self.message())

        self.assertEqual(self.command.stats['failed'], 1)

    def test_unexpected_error_is_swallowed(self, _close):
        with patch(f'{MODULE}.store_message', side_effect=RuntimeError('boom')):
            with self.assertLogs(LOGGER, level='ERROR'):
                self.command.on_message(None, None, self.message())

        self.assertEqual(self.command.stats['failed'], 1)

    def test_stale_connections_are_dropped_before_each_message(self, close_old_connections):
        self.command.on_message(None, None, self.message())

        close_old_connections.assert_called_once()


class WaitForMigrationsTests(SimpleTestCase):
    def test_polls_until_nothing_is_left_to_apply(self):
        with patch(f'{MODULE}.MigrationExecutor') as executor_cls:
            executor_cls.return_value.migration_plan.side_effect = [['0002_plugindata'], []]
            sleep = MagicMock()

            with self.assertLogs(LOGGER, level='INFO'):
                wait_for_migrations(sleep=sleep)

        sleep.assert_called_once()

    def test_keeps_waiting_while_postgres_is_down(self):
        with patch(f'{MODULE}.MigrationExecutor') as executor_cls, patch(f'{MODULE}.connection'):
            executor_cls.side_effect = [OperationalError('connection refused'), MagicMock(**{'migration_plan.return_value': []})]
            sleep = MagicMock()

            with self.assertLogs(LOGGER, level='INFO'):
                wait_for_migrations(sleep=sleep)

        sleep.assert_called_once()


@override_settings(MQTT_CONFIG={'HOST': 'broker', 'PORT': 1884, 'USERNAME': 'u', 'PASSWORD': 'p'})
class CommandTests(SimpleTestCase):
    def run_command(self, **options):
        with patch(f'{MODULE}.mqtt.Client') as client_cls, \
                patch(f'{MODULE}.wait_for_migrations') as wait, \
                patch(f'{MODULE}.signal.signal'), \
                patch(f'{MODULE}.logging.basicConfig'):
            call_command('mqtt_ingest', **options)
        return client_cls.return_value, wait

    def test_waits_for_migrations_then_connects_with_credentials(self):
        paho, wait = self.run_command()

        wait.assert_called_once()
        paho.username_pw_set.assert_called_once_with('u', 'p')
        paho.connect.assert_called_once_with('broker', 1884, 60)

    def test_subscribes_to_wildcard_topic_on_connect(self):
        command = Command()
        command.topic, command.qos = INGEST_TOPIC, 1
        paho = MagicMock()

        command.on_connect(paho, None, None, 0)

        paho.subscribe.assert_called_once_with(INGEST_TOPIC, qos=1)

    def test_does_not_subscribe_when_connection_fails(self):
        command = Command()
        command.topic, command.qos = INGEST_TOPIC, 1
        paho = MagicMock()

        with self.assertLogs(LOGGER, level='ERROR'):
            command.on_connect(paho, None, None, 5)

        paho.subscribe.assert_not_called()
