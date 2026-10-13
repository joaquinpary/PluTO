import os
from unittest.mock import patch

import docker
from django.conf import settings

from django.test import SimpleTestCase, override_settings

from .orchestrator import PluginOrchestrator


class PluginOrchestratorTests(SimpleTestCase):
    @override_settings(MQTT_CONFIG={'HOST': 'broker', 'PORT': 1884, 'USERNAME': 'user', 'PASSWORD': 'secret'})
    def test_plugins_get_the_server_broker_settings(self):
        with patch('server_core.orchestrator.docker.DockerClient') as client_cls:
            client = client_cls.return_value
            client.containers.run.return_value.id = 'container-123'
            orchestrator = PluginOrchestrator()

            success, _ = orchestrator.spawn_plugin(
                plugin_type='tinygs',
                instance_id='uuid-1',
                station_coordinates={'lat': 0, 'lon': 0, 'alt': 0},
                tinygs_device='My_TinyGS',
            )

        self.assertTrue(success)
        environment = client.containers.run.call_args.kwargs['environment']
        self.assertEqual(environment['MQTT_BROKER_URL'], 'broker')
        self.assertEqual(environment['MQTT_BROKER_PORT'], '1884')
        self.assertEqual(environment['MQTT_USERNAME'], 'user')
        self.assertEqual(environment['MQTT_PASSWORD'], 'secret')

    @override_settings(PLUTO_API_URL='http://server:8000/api/', PLUTO_TRANSFORM_URL='http://coord_transform:8000/')
    def test_plugins_get_the_api_url_their_token_and_their_board(self):
        with patch('server_core.orchestrator.docker.DockerClient') as client_cls:
            client = client_cls.return_value
            client.containers.run.return_value.id = 'container-123'

            PluginOrchestrator().spawn_plugin(
                plugin_type='tinygs',
                instance_id='uuid-1',
                station_coordinates={'lat': 0, 'lon': 0, 'alt': 0},
                api_token='secret-token',
                rotor_device_id='a1b2c3d4e5f6',
                tinygs_device='My_TinyGS',
            )

        environment = client.containers.run.call_args.kwargs['environment']
        self.assertEqual(environment['PLUTO_API_URL'], 'http://server:8000/api/')
        self.assertEqual(environment['PLUTO_TRANSFORM_URL'], 'http://coord_transform:8000/')
        self.assertEqual(environment['PLUTO_API_TOKEN'], 'secret-token')
        self.assertEqual(environment['ROTOR_DEVICE_ID'], 'a1b2c3d4e5f6')
        # Neither is plugin configuration, so neither goes through the handler.
        self.assertNotIn('API_TOKEN', environment)

    def test_a_plugin_without_a_board_gets_no_device_id(self):
        with patch('server_core.orchestrator.docker.DockerClient') as client_cls:
            client = client_cls.return_value
            client.containers.run.return_value.id = 'container-123'

            PluginOrchestrator().spawn_plugin(
                plugin_type='tinygs',
                instance_id='uuid-1',
                station_coordinates={'lat': 0, 'lon': 0, 'alt': 0},
                tinygs_device='My_TinyGS',
            )

        environment = client.containers.run.call_args.kwargs['environment']
        self.assertNotIn('ROTOR_DEVICE_ID', environment)
        self.assertNotIn('PLUTO_API_TOKEN', environment)

    def test_plugin_images_are_built_from_plugins_so_they_get_the_sdk(self):
        with patch('server_core.orchestrator.docker.DockerClient') as client_cls:
            client = client_cls.return_value
            client.images.get.side_effect = docker.errors.ImageNotFound('missing')

            ok, image = PluginOrchestrator()._build_image_if_needed('file_tracker')

        self.assertTrue(ok)
        self.assertEqual(image, 'pluto/plugin-file-tracker:latest')
        kwargs = client.images.build.call_args.kwargs
        self.assertEqual(kwargs['path'], os.path.join(settings.BASE_DIR, 'plugins'))
        self.assertEqual(kwargs['dockerfile'], os.path.join('file_tracker', 'Dockerfile'))
