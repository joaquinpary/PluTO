from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.test import RequestFactory, TestCase

from .admin import PluginInstanceAdmin
from .models import PluginInstance


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
