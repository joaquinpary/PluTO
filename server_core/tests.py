import json

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase

from .models import PluginData, PluginInstance
from .plugin_handlers import PLUGIN_HANDLERS
from .plugin_handlers.file_tracker import MAX_FILE_BYTES, build_file_message


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
