from datetime import datetime, timezone

from django.test import SimpleTestCase, TestCase

from .ingest import DUPLICATE, INGESTED, envelope_fields, store_document
from .models import PluginData, PluginInstance

PLUGIN_ID = '3f2a-uuid'
INGEST_TOPIC = '/api/plugin-data/tracking'


def envelope(**overrides):
    document = {
        'schema_version': 1,
        'message_id': 'msg-1',
        'plugin_id': PLUGIN_ID,
        'plugin_type': 'tinygs',
        'device': 'heltec-lp-01',
        'message_type': 'tracking',
        'source_topic': 'pluto/heltec-lp-01/tracking',
        'received_at': '2026-09-12T18:03:11+00:00',
        'payload_format': 'json',
        'payload': {'az': 1.0},
    }
    document.update(overrides)
    return document


def fields(url_type='tracking', **overrides):
    """The fields for an envelope sent to /api/plugin-data/<url_type>."""
    return envelope_fields(PLUGIN_ID, url_type, envelope(**overrides), ingest_topic=INGEST_TOPIC)


class EnvelopeFieldsTests(SimpleTestCase):
    def test_builds_the_fields_of_a_valid_envelope(self):
        result = fields()

        self.assertEqual(result['message_type'], 'tracking')
        self.assertEqual(result['device'], 'heltec-lp-01')
        self.assertEqual(result['payload'], {'az': 1.0})
        self.assertEqual(result['ingest_topic'], INGEST_TOPIC)

    def test_the_caller_decides_the_plugin_not_the_envelope(self):
        with self.assertLogs('server_core.ingest', level='WARNING'):
            result = fields(plugin_id='spoofed-uuid')

        self.assertNotIn('plugin_id', result)

    def test_the_caller_decides_the_message_type(self):
        self.assertEqual(fields('rx', message_type='tracking')['message_type'], 'rx')

    def test_wraps_a_payload_that_is_not_an_object(self):
        result = fields(payload=[1, 2])

        self.assertEqual(result['payload'], {'value': [1, 2]})
        self.assertEqual(result['payload_format'], 'coerced')

    def test_normalizes_received_at_to_aware_utc(self):
        result = fields(received_at='2026-09-12T15:03:11-03:00')

        self.assertEqual(result['received_at'], datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc))

    def test_received_at_without_offset_is_taken_as_utc(self):
        result = fields(received_at='2026-09-12T18:03:11')

        self.assertEqual(result['received_at'], datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc))

    def test_missing_or_unreadable_received_at_is_tolerated(self):
        self.assertIsNone(fields(received_at=None)['received_at'])
        with self.assertLogs('server_core.ingest', level='WARNING'):
            self.assertIsNone(fields(received_at='yesterday')['received_at'])

    def test_unknown_keys_and_plugin_type_are_dropped(self):
        result = fields(created_at='hacked', evil='x')

        for key in ('created_at', 'evil', 'plugin_type'):
            self.assertNotIn(key, result)

    def test_a_boolean_is_not_a_schema_version(self):
        self.assertNotIn('schema_version', fields(schema_version=True))


class StoreDocumentTests(TestCase):
    def setUp(self):
        self.plugin = PluginInstance.objects.create(name='tinygs-0', plugin_type='tinygs')

    def test_stores_the_row_linked_to_its_plugin(self):
        self.assertEqual(store_document(self.plugin, fields('rx', payload={'rssi': -97})), INGESTED)

        row = PluginData.objects.get()
        self.assertEqual(row.plugin, self.plugin)
        self.assertEqual(row.message_type, 'rx')
        self.assertEqual(row.payload, {'rssi': -97})
        self.assertEqual(row.received_at, datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc))

    def test_a_repeated_message_id_is_a_duplicate_stored_once(self):
        store_document(self.plugin, fields())

        self.assertEqual(store_document(self.plugin, fields()), DUPLICATE)
        self.assertEqual(PluginData.objects.count(), 1)

    def test_a_minimal_envelope_takes_the_model_defaults(self):
        store_document(self.plugin, envelope_fields(PLUGIN_ID, 'rx', {'payload': {'x': 1}}))

        row = PluginData.objects.get()
        self.assertEqual((row.device, row.payload_format, row.schema_version), ('', 'json', 1))
        self.assertIsNone(row.message_id)
