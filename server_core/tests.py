import json
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError
from django.db.models import ProtectedError
from django.test import RequestFactory, SimpleTestCase, TestCase

from .admin import PluginInstanceAdmin, PluginInstanceForm
from .models import PluginData, PluginInstance
from .plugin_handlers import PLUGIN_HANDLERS
from .plugin_handlers.file_tracker import MAX_FILE_BYTES, build_file_message


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

		with patch.object(self.model_admin, '_stop_plugin', return_value=(True, 'stopped')) as stop_plugin, \
				patch('server_core.admin.publish_retained'):
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

	def test_validate_rejects_names_that_are_not_slugs(self):
		for device in ('Estacion Cordoba', 'estación', 'a.b', 'a b'):
			with self.subTest(device=device):
				self.assertIsNotNone(self.handler.validate({'tinygs_device': device}))

	def test_rejection_suggests_a_slug(self):
		error = self.handler.validate({'tinygs_device': 'Estación Córdoba'})

		self.assertIn('"Estacion_Cordoba"', error)

	def test_rejection_without_a_usable_slug_suggests_nothing(self):
		error = self.handler.validate({'tinygs_device': '###'})

		self.assertNotIn('Did you mean', error)

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


class FileTrackerHandlerTests(SimpleTestCase):
	def setUp(self):
		self.handler = PLUGIN_HANDLERS['file_tracker']

	def test_validate_needs_no_file_path(self):
		self.assertIsNone(self.handler.validate({'coord_type': 'ecef', 'coord_format': 'geo'}))

	def test_validate_rejects_an_invalid_combination(self):
		self.assertIsNotNone(self.handler.validate({'coord_type': 'ENU', 'coord_format': 'GEO'}))

	def test_the_plugin_is_told_where_files_arrive(self):
		environment = self.handler.get_environment({'coord_type': 'ECEF', 'coord_format': 'GEO', 'plugin_id': 'abc'})

		self.assertEqual(environment['MQTT_INPUT_TOPIC'], 'plugin/abc/input/file')
		self.assertIsNone(self.handler.get_volumes({}))

	def test_file_message_carries_the_content_and_the_formats(self):
		message = json.loads(build_file_message({'coord_type': 'ecef', 'coord_format': 'geo'}, 'c.txt', '40 -3 6'.encode()))

		self.assertEqual((message['coord_type'], message['coord_format']), ('ECEF', 'GEO'))
		self.assertEqual(message['content'], '40 -3 6')
		self.assertTrue(message['upload_id'])

	def test_every_upload_gets_its_own_id(self):
		config = {'coord_type': 'ECEF', 'coord_format': 'GEO'}

		first = json.loads(build_file_message(config, 'c.txt', b'1 2 3'))
		second = json.loads(build_file_message(config, 'c.txt', b'1 2 3'))

		self.assertNotEqual(first['upload_id'], second['upload_id'])

	def test_file_message_rejects_binary_and_oversized_files(self):
		config = {'coord_type': 'ECEF', 'coord_format': 'GEO'}

		with self.assertRaises(ValueError):
			build_file_message(config, 'c.bin', b'\xff\xfe\x00')
		with self.assertRaises(ValueError):
			build_file_message(config, 'c.txt', b'1' * (MAX_FILE_BYTES + 1))


class CoordinatesUploadTests(TestCase):
	def setUp(self):
		self.factory = RequestFactory()
		self.model_admin = PluginInstanceAdmin(PluginInstance, AdminSite())
		self.plugin = PluginInstance.objects.create(
			name='tracker', plugin_type='file_tracker',
			config={'coord_type': 'ECEF', 'coord_format': 'GEO'},
		)

	def form(self, plugin, content=b'40 -3 667\n'):
		data = {
			'name': plugin.name, 'plugin_type': plugin.plugin_type, 'status': plugin.status,
			'station_lat': plugin.station_lat, 'station_lon': plugin.station_lon, 'station_alt': plugin.station_alt,
			'config': json.dumps(plugin.config),
		}
		files = {'coordinates_file': SimpleUploadedFile('coords.txt', content)}
		return PluginInstanceForm(data=data, files=files, instance=plugin)

	def request(self):
		request = self.factory.post('/admin/server_core/plugininstance/')
		request._messages = MessageCollector()
		return request

	def test_saving_with_a_file_publishes_it_retained_on_the_input_topic(self):
		form = self.form(self.plugin)
		self.assertTrue(form.is_valid(), form.errors)

		with patch('server_core.admin.publish_retained') as publish, patch('server_core.admin.PluginOrchestrator'):
			self.model_admin.save_model(self.request(), form.save(commit=False), form, change=True)

		topic, payload = publish.call_args.args
		self.assertEqual(topic, f'plugin/{self.plugin.plugin_uuid}/input/file')
		self.assertEqual(json.loads(payload)['content'], '40 -3 667\n')

	def test_a_file_for_another_plugin_type_is_a_form_error(self):
		plugin = PluginInstance.objects.create(name='gs', plugin_type='tinygs', config={'tinygs_device': 'My_TinyGS'})

		form = self.form(plugin)

		self.assertFalse(form.is_valid())
		self.assertIn('coordinates_file', form.errors)

	def test_a_binary_file_is_a_form_error(self):
		form = self.form(self.plugin, content=b'\xff\xfe\x00')

		self.assertFalse(form.is_valid())
		self.assertIn('coordinates_file', form.errors)

	def test_deleting_the_instance_clears_the_retained_file(self):
		with patch('server_core.admin.publish_retained') as publish:
			self.model_admin.delete_model(self.request(), self.plugin)

		publish.assert_called_once_with(f'plugin/{self.plugin.plugin_uuid}/input/file', b'')


class MessageCollector(list):
	def add(self, level, message, extra_tags=''):
		self.append(message)


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
