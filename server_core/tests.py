from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.db import IntegrityError, OperationalError
from django.db.models import ProtectedError
from django.test import RequestFactory, SimpleTestCase, TestCase

from .admin import PluginInstanceAdmin
from .models import PluginData, PluginInstance
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

	def test_pass_settings_are_optional(self):
		self.assertIsNone(self.handler.validate({'tinygs_device': 'My_TinyGS'}))

	def test_valid_pass_settings_are_accepted(self):
		config = {
			'tinygs_device': 'My_TinyGS',
			'tinygs_topic_prefix': 'pluto',
			'min_elevation_deg': 15,
			'lookahead_minutes': 20,
			'sample_seconds': 1,
			'tle_ttl_hours': 12.5,
		}

		self.assertIsNone(self.handler.validate(config))

	def test_impossible_pass_settings_are_rejected(self):
		for key, value in (
			('min_elevation_deg', 91),
			('min_elevation_deg', -91),
			('lookahead_minutes', 0),
			('sample_seconds', -1),
			('tle_ttl_hours', 0),
			('sample_seconds', '1'),
			('lookahead_minutes', True),
		):
			with self.subTest(key=key, value=value):
				self.assertIsNotNone(self.handler.validate({'tinygs_device': 'My_TinyGS', key: value}))

	def test_topic_prefix_must_be_a_single_segment(self):
		for prefix in ('', 'pluto/extra', '+', '#'):
			with self.subTest(prefix=prefix):
				self.assertIsNotNone(self.handler.validate({'tinygs_device': 'My_TinyGS', 'tinygs_topic_prefix': prefix}))

	def test_pass_settings_reach_the_container_upper_cased(self):
		environment = self.handler.get_environment({
			'tinygs_device': 'My_TinyGS', 'min_elevation_deg': 15, 'lookahead_minutes': 20,
		})

		self.assertEqual(environment['MIN_ELEVATION_DEG'], '15')
		self.assertEqual(environment['LOOKAHEAD_MINUTES'], '20')


class PluginDataTests(TestCase):
	def setUp(self):
		self.plugin = PluginInstance.objects.create(name='tinygs-0', plugin_type='tinygs')

	def test_created_at_is_set_by_the_database(self):
		row = PluginData.objects.create(plugin=self.plugin, message_type='rx', payload={'rssi': -97})

		row.refresh_from_db()

		self.assertIsNotNone(row.created_at)

	def test_message_id_is_unique(self):
		PluginData.objects.create(plugin=self.plugin, message_type='rx', message_id='msg-1')

		with self.assertRaises(IntegrityError):
			PluginData.objects.create(plugin=self.plugin, message_type='rx', message_id='msg-1')

	def test_rows_without_message_id_do_not_collide(self):
		PluginData.objects.create(plugin=self.plugin, message_type='rx')
		PluginData.objects.create(plugin=self.plugin, message_type='rx')

		self.assertEqual(self.plugin.data.count(), 2)

	def test_plugin_with_data_cannot_be_deleted(self):
		PluginData.objects.create(plugin=self.plugin, message_type='rx')

		with self.assertRaises(ProtectedError):
			self.plugin.delete()


class HealthcheckTests(SimpleTestCase):
	def test_returns_503_when_database_is_unreachable(self):
		with patch('pluto.urls.connection') as connection:
			connection.cursor.side_effect = OperationalError('password authentication failed')

			response = self.client.get('/')

		self.assertEqual(response.status_code, 503)
		self.assertEqual(response.json()['database'], 'unreachable')

	def test_returns_200_when_database_answers(self):
		with patch('pluto.urls.connection'):
			response = self.client.get('/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['database'], 'ok')
