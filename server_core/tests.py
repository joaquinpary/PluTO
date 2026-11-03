import json
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError
from django.db.models import ProtectedError
from django.test import RequestFactory, SimpleTestCase, TestCase

from .admin import PluginInstanceAdmin, PluginInstanceForm
from .lifecycle import LifecycleError
from .models import PluginData, PluginInstance
from .plugin_handlers import PLUGIN_HANDLERS
from .plugin_handlers.file_tracker import MAX_FILE_BYTES, build_file_message


class PluginInstanceAdminTests(TestCase):
	"""The admin only delegates now; test_lifecycle.py covers what it delegates to."""

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

	def test_change_form_marks_status_and_type_as_readonly(self):
		plugin = PluginInstance.objects.create(name='tracker-0', plugin_type='file_tracker')

		readonly_fields = self.model_admin.get_readonly_fields(self.request, plugin)

		self.assertIn('status', readonly_fields)
		# Changing the type of a running instance orphaned its container.
		self.assertIn('plugin_type', readonly_fields)

	def test_the_actions_go_through_the_lifecycle(self):
		plugin = PluginInstance.objects.create(name='tinygs-1', plugin_type='tinygs')
		request = self.factory.post('/admin/server_core/plugininstance/')
		actions = {
			'launch': self.model_admin.launch_selected_plugins,
			'stop': self.model_admin.stop_selected_plugins,
			'sync': self.model_admin.sync_container_statuses,
		}

		for step, action in actions.items():
			with self.subTest(step=step):
				with patch(f'server_core.lifecycle.{step}') as lifecycle_step, patch.object(self.model_admin, 'message_user'):
					action(request, PluginInstance.objects.all())
				lifecycle_step.assert_called_once_with(plugin)

	def test_a_failed_step_is_reported_and_the_rest_go_on(self):
		PluginInstance.objects.create(name='a', plugin_type='tinygs')
		PluginInstance.objects.create(name='b', plugin_type='tinygs')
		request = self.factory.post('/admin/server_core/plugininstance/')

		with patch('server_core.lifecycle.launch', side_effect=[LifecycleError('docker', 'boom'), None]) as launch, \
				patch.object(self.model_admin, 'message_user') as message_user:
			self.model_admin.launch_selected_plugins(request, PluginInstance.objects.all())

		self.assertEqual(launch.call_count, 2)
		self.assertIn('boom', message_user.call_args_list[0].args[1])

	def test_delete_model_cancels_deletion_when_stop_fails(self):
		plugin = PluginInstance.objects.create(
			name='tracker-2',
			plugin_type='file_tracker',
			status=PluginInstance.Status.RUNNING,
		)
		request = self.factory.post(f'/admin/server_core/plugininstance/{plugin.pk}/delete/')

		with patch('server_core.lifecycle.PluginOrchestrator') as orchestrator_cls, \
				patch.object(self.model_admin, 'message_user') as message_user:
			orchestrator_cls.return_value.kill_plugin.return_value = (False, 'boom')
			self.model_admin.delete_model(request, plugin)

		self.assertTrue(PluginInstance.objects.filter(pk=plugin.pk).exists())
		message_user.assert_called_once()

	def test_delete_model_stops_running_plugin_before_deleting(self):
		plugin = PluginInstance.objects.create(
			name='tracker-3',
			plugin_type='file_tracker',
			status=PluginInstance.Status.RUNNING,
		)
		request = self.factory.post(f'/admin/server_core/plugininstance/{plugin.pk}/delete/')

		with patch('server_core.lifecycle.PluginOrchestrator') as orchestrator_cls, \
				patch('server_core.lifecycle.publish_retained'):
			orchestrator_cls.return_value.kill_plugin.return_value = (True, 'stopped')
			self.model_admin.delete_model(request, plugin)

		self.assertFalse(PluginInstance.objects.filter(pk=plugin.pk).exists())
		orchestrator_cls.return_value.kill_plugin.assert_called_once_with('file_tracker', plugin.plugin_uuid)


class TinyGSHandlerTests(SimpleTestCase):
	"""What reaches the container. The validation lives in test_fields.py."""

	def setUp(self):
		self.handler = PLUGIN_HANDLERS['tinygs']

	def test_get_environment_exposes_device_id(self):
		environment = self.handler.get_environment({'tinygs_device': 'heltec-lp-01'})

		self.assertEqual(environment['TINYGS_DEVICE'], 'heltec-lp-01')

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

		with patch('server_core.lifecycle.publish_retained') as publish:
			self.model_admin.save_model(self.request(), form.save(commit=False), form, change=True)

		topic, payload = publish.call_args.args
		self.assertEqual(topic, f'plugin/{self.plugin.plugin_uuid}/input/file')
		self.assertEqual(json.loads(payload)['content'], '40 -3 667\n')

	def test_a_bad_file_is_reported_and_not_sent(self):
		form = self.form(self.plugin, content=b'\xff\xfe\x00')
		self.assertTrue(form.is_valid(), form.errors)
		request = self.request()

		with patch('server_core.lifecycle.publish_retained') as publish:
			self.model_admin.save_model(request, form.save(commit=False), form, change=True)

		publish.assert_not_called()
		self.assertIn('not UTF-8', request._messages[0])

	def test_deleting_the_instance_clears_the_retained_file(self):
		with patch('server_core.lifecycle.publish_retained') as publish:
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
