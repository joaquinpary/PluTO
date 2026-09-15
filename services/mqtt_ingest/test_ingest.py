import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pymongo.errors import PyMongoError

from mqtt_handler import (
    INGEST_TOPIC,
    IngestMQTTClient,
    build_document_fields,
    parse_ingest_topic,
)

LOGGER = 'mqtt_handler'


class ParseIngestTopicTests(unittest.TestCase):
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


class BuildDocumentFieldsTests(unittest.TestCase):
    def envelope(self, **overrides):
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

    def test_builds_fields_from_valid_envelope(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/tracking', self.envelope())

        self.assertEqual(fields['plugin_id'], '3f2a-uuid')
        self.assertEqual(fields['message_type'], 'tracking')
        self.assertEqual(fields['device'], 'heltec-lp-01')
        self.assertEqual(fields['payload'], {'az': 1.0})
        self.assertEqual(fields['ingest_topic'], 'plugin/3f2a-uuid/data/tracking')

    def test_plugin_id_from_topic_wins_over_envelope(self):
        with self.assertLogs(LOGGER, level='WARNING'):
            fields = build_document_fields(
                'plugin/real-uuid/data/tracking',
                self.envelope(plugin_id='spoofed-uuid'),
            )

        self.assertEqual(fields['plugin_id'], 'real-uuid')

    def test_message_type_comes_from_topic(self):
        fields = build_document_fields(
            'plugin/3f2a-uuid/data/rx',
            self.envelope(message_type='tracking'),
        )

        self.assertEqual(fields['message_type'], 'rx')

    def test_wraps_non_dict_payload(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/rx', self.envelope(payload=[1, 2]))

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
            self.assertIsNone(build_document_fields('plugin/3f2a-uuid/coordinates/raw', self.envelope()))

    def test_normalizes_aware_datetime_to_naive_utc(self):
        fields = build_document_fields(
            'plugin/3f2a-uuid/data/tracking',
            self.envelope(received_at='2026-09-12T15:03:11-03:00'),
        )

        self.assertIsNone(fields['received_at'].tzinfo)
        self.assertEqual(fields['received_at'], datetime(2026, 9, 12, 18, 3, 11))

    def test_missing_received_at_is_tolerated(self):
        fields = build_document_fields('plugin/3f2a-uuid/data/tracking', self.envelope(received_at=None))

        self.assertIsNone(fields['received_at'])

    def test_unknown_envelope_keys_are_dropped(self):
        fields = build_document_fields(
            'plugin/3f2a-uuid/data/tracking',
            self.envelope(created_at='hacked', evil='x'),
        )

        self.assertNotIn('created_at', fields)
        self.assertNotIn('evil', fields)


class MessageHandlingTests(unittest.TestCase):
    def setUp(self):
        with patch('mqtt_handler.mqtt.Client'), patch('mqtt_handler.signal.signal'):
            self.client = IngestMQTTClient(broker_url='mosquitto', broker_port=1883)

    def message(self, topic='plugin/3f2a-uuid/data/tracking', payload=b'{"payload": {"az": 1}}'):
        return SimpleNamespace(topic=topic, payload=payload)

    def test_saves_document_for_valid_message(self):
        with patch('mqtt_handler.PluginData') as plugin_data:
            self.client.on_message(None, None, self.message())

        plugin_data.assert_called_once()
        plugin_data.return_value.save.assert_called_once()
        self.assertEqual(self.client.stats['ingested'], 1)

    def test_malformed_message_does_not_raise_and_does_not_save(self):
        with patch('mqtt_handler.PluginData') as plugin_data:
            with self.assertLogs(LOGGER, level='WARNING'):
                self.client.on_message(None, None, self.message(payload=b'{"roto'))

        plugin_data.assert_not_called()
        self.assertEqual(self.client.stats['rejected'], 1)

    def test_unexpected_topic_is_rejected(self):
        with patch('mqtt_handler.PluginData') as plugin_data:
            with self.assertLogs(LOGGER, level='WARNING'):
                self.client.on_message(None, None, self.message(topic='plugin/x/coordinates/raw'))

        plugin_data.assert_not_called()
        self.assertEqual(self.client.stats['rejected'], 1)

    def test_mongo_failure_is_logged_and_swallowed(self):
        with patch('mqtt_handler.PluginData') as plugin_data:
            plugin_data.return_value.save.side_effect = PyMongoError('mongo caido')

            with self.assertLogs(LOGGER, level='ERROR'):
                self.client.on_message(None, None, self.message())

        self.assertEqual(self.client.stats['failed'], 1)

    def test_unexpected_error_is_swallowed(self):
        with patch('mqtt_handler.PluginData') as plugin_data:
            plugin_data.side_effect = RuntimeError('boom')

            with self.assertLogs(LOGGER, level='ERROR'):
                self.client.on_message(None, None, self.message())

        self.assertEqual(self.client.stats['failed'], 1)


class ClientTests(unittest.TestCase):
    def build(self, **kwargs):
        with patch('mqtt_handler.mqtt.Client') as client_cls, patch('mqtt_handler.signal.signal'):
            client = IngestMQTTClient(broker_url='broker', broker_port=1884, **kwargs)
        return client, client_cls.return_value

    def test_uses_credentials_when_both_are_given(self):
        client, paho = self.build(username='u', password='p')

        paho.username_pw_set.assert_called_once_with('u', 'p')

    def test_skips_credentials_when_missing(self):
        client, paho = self.build()

        paho.username_pw_set.assert_not_called()

    def test_subscribes_to_wildcard_topic_on_connect(self):
        client, _ = self.build()
        paho = MagicMock()

        client.on_connect(paho, None, None, 0)

        paho.subscribe.assert_called_once_with(INGEST_TOPIC, qos=1)

    def test_does_not_subscribe_when_connection_fails(self):
        client, _ = self.build()
        paho = MagicMock()

        with self.assertLogs(LOGGER, level='ERROR'):
            client.on_connect(paho, None, None, 5)

        paho.subscribe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
