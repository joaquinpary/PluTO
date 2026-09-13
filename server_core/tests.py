import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.admin import AdminSite
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from pymongo.errors import PyMongoError

from .admin import PluginInstanceAdmin
from .models import PluginInstance
from .management.commands.mqtt_ingest import (
	INGEST_TOPIC,
	build_document_fields,
	parse_ingest_topic,
)
from .management.commands.mqtt_ingest import Command as MqttIngestCommand
from .plugin_handlers import PLUGIN_HANDLERS


class PluginInstanceAdminTests(TestCase):
	def setUp(self):
		self.factory = RequestFactory()
		self.admin_site = AdminSite()
		self.model_admin = PluginInstanceAdmin(PluginInstance, self.admin_site)
		self.request = self.factory.get('/admin/server_core/plugininstance/')

	def test_add_form_hides_runtime_fields(self):
		fieldsets = self.model_admin.get_fieldsets(self.request)
		first_fields = fieldsets[0][1]['fields']

		self.assertEqual(first_fields, ('name', 'plugin_type'))
		self.assertNotIn('status', first_fields)

	def test_change_form_marks_status_as_readonly(self):
		plugin = PluginInstance.objects.create(name='tracker-0', plugin_type='file_tracker')

		readonly_fields = self.model_admin.get_readonly_fields(self.request, plugin)

		self.assertIn('status', readonly_fields)

	def test_save_model_starts_new_running_plugin(self):
		plugin = PluginInstance(
			name='tracker-1',
			plugin_type='file_tracker',
			status=PluginInstance.Status.RUNNING,
			config={
				'file_path': '/tmp/coords.txt',
				'coord_type': 'ECEF',
				'coord_format': 'GEO',
			},
		)
		request = self.factory.post('/admin/server_core/plugininstance/add/')

		with patch('server_core.admin.PluginOrchestrator') as orchestrator_cls:
			orchestrator_cls.return_value.spawn_plugin.return_value = (True, 'container-123')

			self.model_admin.save_model(request, plugin, form=None, change=False)

		plugin.refresh_from_db()
		self.assertEqual(plugin.status, PluginInstance.Status.RUNNING)
		self.assertEqual(plugin.container_id, 'container-123')

	def test_delete_model_cancels_deletion_when_stop_fails(self):
		plugin = PluginInstance.objects.create(
			name='tracker-2',
			plugin_type='file_tracker',
			status=PluginInstance.Status.RUNNING,
		)
		request = self.factory.post(f'/admin/server_core/plugininstance/{plugin.pk}/delete/')

		with patch.object(self.model_admin, '_stop_plugin', return_value=(False, 'boom')) as stop_plugin:
			with patch.object(self.model_admin, 'message_user') as message_user:
				self.model_admin.delete_model(request, plugin)

		self.assertTrue(PluginInstance.objects.filter(pk=plugin.pk).exists())
		stop_plugin.assert_called_once()
		message_user.assert_called_once()

	def test_delete_model_stops_running_plugin_before_deleting(self):
		plugin = PluginInstance.objects.create(
			name='tracker-3',
			plugin_type='file_tracker',
			status=PluginInstance.Status.RUNNING,
		)
		request = self.factory.post(f'/admin/server_core/plugininstance/{plugin.pk}/delete/')

		with patch.object(self.model_admin, '_stop_plugin', return_value=(True, 'stopped')) as stop_plugin:
			self.model_admin.delete_model(request, plugin)

		self.assertFalse(PluginInstance.objects.filter(pk=plugin.pk).exists())
		stop_plugin.assert_called_once()


class TinyGSHandlerTests(SimpleTestCase):
	def setUp(self):
		self.handler = PLUGIN_HANDLERS['tinygs']

	def test_validate_requires_device(self):
		self.assertIsNotNone(self.handler.validate({}))
		self.assertIsNotNone(self.handler.validate({'tinygs_device': '   '}))

	def test_validate_rejects_mqtt_wildcards(self):
		for device in ('+', '#', 'heltec/lp-01'):
			self.assertIsNotNone(self.handler.validate({'tinygs_device': device}))

	def test_validate_accepts_plain_device_id(self):
		self.assertIsNone(self.handler.validate({'tinygs_device': 'heltec-lp-01'}))

	def test_get_environment_exposes_device_id(self):
		environment = self.handler.get_environment({'tinygs_device': 'heltec-lp-01'})

		self.assertEqual(environment['TINYGS_DEVICE'], 'heltec-lp-01')


class MqttIngestTopicTests(SimpleTestCase):
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


class MqttIngestDocumentTests(SimpleTestCase):
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
		self.assertIsNone(build_document_fields('plugin/3f2a-uuid/data/rx', b'{"roto'))

	def test_returns_none_for_undecodable_bytes(self):
		self.assertIsNone(build_document_fields('plugin/3f2a-uuid/data/rx', b'\xff\xfe'))

	def test_returns_none_for_non_object_envelope(self):
		self.assertIsNone(build_document_fields('plugin/3f2a-uuid/data/rx', b'[1, 2]'))

	def test_returns_none_for_unexpected_topic(self):
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


class MqttIngestMessageHandlingTests(SimpleTestCase):
	def setUp(self):
		self.command = MqttIngestCommand()
		self.command.stats = {'ingested': 0, 'rejected': 0, 'failed': 0}

	def message(self, topic='plugin/3f2a-uuid/data/tracking', payload=b'{"payload": {"az": 1}}'):
		return SimpleNamespace(topic=topic, payload=payload)

	def test_saves_document_for_valid_message(self):
		with patch('server_core.management.commands.mqtt_ingest.PluginData') as plugin_data:
			self.command.on_message(None, None, self.message())

		plugin_data.assert_called_once()
		plugin_data.return_value.save.assert_called_once()
		self.assertEqual(self.command.stats['ingested'], 1)

	def test_malformed_message_does_not_raise_and_does_not_save(self):
		with patch('server_core.management.commands.mqtt_ingest.PluginData') as plugin_data:
			self.command.on_message(None, None, self.message(payload=b'{"roto'))

		plugin_data.assert_not_called()
		self.assertEqual(self.command.stats['rejected'], 1)

	def test_unexpected_topic_is_rejected(self):
		with patch('server_core.management.commands.mqtt_ingest.PluginData') as plugin_data:
			self.command.on_message(None, None, self.message(topic='plugin/x/coordinates/raw'))

		plugin_data.assert_not_called()
		self.assertEqual(self.command.stats['rejected'], 1)

	def test_mongo_failure_is_logged_and_swallowed(self):
		with patch('server_core.management.commands.mqtt_ingest.PluginData') as plugin_data:
			plugin_data.return_value.save.side_effect = PyMongoError('mongo caido')

			with self.assertLogs('server_core.management.commands.mqtt_ingest', level='ERROR'):
				self.command.on_message(None, None, self.message())

		self.assertEqual(self.command.stats['failed'], 1)

	def test_unexpected_error_is_swallowed(self):
		with patch('server_core.management.commands.mqtt_ingest.PluginData') as plugin_data:
			plugin_data.side_effect = RuntimeError('boom')

			with self.assertLogs('server_core.management.commands.mqtt_ingest', level='ERROR'):
				self.command.on_message(None, None, self.message())

		self.assertEqual(self.command.stats['failed'], 1)


class MqttIngestClientTests(SimpleTestCase):
	def setUp(self):
		self.command = MqttIngestCommand()
		self.command.topic = INGEST_TOPIC
		self.command.qos = 1

	def test_subscribes_to_wildcard_topic_on_connect(self):
		client = MagicMock()

		self.command.on_connect(client, None, None, 0)

		client.subscribe.assert_called_once_with('plugin/+/data/+', qos=1)

	def test_does_not_subscribe_when_connection_fails(self):
		client = MagicMock()

		with self.assertLogs('server_core.management.commands.mqtt_ingest', level='ERROR'):
			self.command.on_connect(client, None, None, 5)

		client.subscribe.assert_not_called()

	@override_settings(MQTT_CONFIG={'HOST': 'broker', 'PORT': 1884, 'USERNAME': 'u', 'PASSWORD': 'p'})
	def test_uses_settings_for_broker_and_credentials(self):
		with patch('server_core.management.commands.mqtt_ingest.mqtt.Client') as client_cls:
			client = client_cls.return_value
			client.loop_forever.side_effect = KeyboardInterrupt

			call_command('mqtt_ingest')

		client.username_pw_set.assert_called_once_with('u', 'p')
		client.connect.assert_called_once_with('broker', 1884, 60)


class HealthcheckTests(SimpleTestCase):
	def test_returns_503_when_mongo_command_fails(self):
		with patch('pluto.urls.mongo_client') as mongo_client:
			mongo_client.__getitem__.return_value.command.side_effect = PyMongoError('sin auth')

			response = self.client.get('/')

		self.assertEqual(response.status_code, 503)
		self.assertEqual(response.json()['mongodb'], 'unreachable')

	def test_returns_200_when_mongo_command_succeeds(self):
		with patch('pluto.urls.mongo_client') as mongo_client:
			mongo_client.__getitem__.return_value.command.return_value = {'ok': 1.0}

			response = self.client.get('/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['mongodb'], 'ok')
