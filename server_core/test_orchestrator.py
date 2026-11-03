import os
from unittest.mock import MagicMock, patch

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


def fake_container(name, status='running', logs=b''):
    """A container as containers.list(sparse=True) or containers.get hand it back."""
    container = MagicMock()
    container.attrs = {'Names': [f'/{name}']}
    container.status = status
    container.logs.return_value = logs
    return container


class DockerTestCase(SimpleTestCase):
    """An orchestrator over a fake Docker client, self.client."""

    def setUp(self):
        patcher = patch('server_core.orchestrator.docker.DockerClient')
        self.client = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.orchestrator = PluginOrchestrator()


class ContainerStatusesTests(DockerTestCase):
    def test_container_names_carry_the_type_and_the_instance(self):
        self.assertEqual(self.orchestrator.container_name('file_tracker', 'uuid-1'), 'plugin-file-tracker-uuid-1')

    def test_lists_every_plugin_container_in_a_single_call(self):
        self.client.containers.list.return_value = [
            fake_container('plugin-tinygs-uuid-1', 'running'),
            fake_container('plugin-file-tracker-uuid-2', 'exited'),
            fake_container('pluto-server-1', 'running'),
        ]

        statuses = self.orchestrator.container_statuses()

        self.assertEqual(statuses, {'plugin-tinygs-uuid-1': 'running', 'plugin-file-tracker-uuid-2': 'exited'})
        # sparse: the list already carries names and states, so nothing is inspected one by one.
        self.client.containers.list.assert_called_once_with(all=True, sparse=True)
        self.client.containers.get.assert_not_called()

    def test_no_plugin_containers_is_an_empty_answer(self):
        self.client.containers.list.return_value = []

        self.assertEqual(self.orchestrator.container_statuses(), {})

    def test_a_docker_error_is_unknown_not_empty(self):
        self.client.containers.list.side_effect = docker.errors.APIError('boom')

        with self.assertLogs('server_core.orchestrator', level='ERROR'):
            self.assertIsNone(self.orchestrator.container_statuses())

    def test_without_the_proxy_nothing_is_known(self):
        self.client.ping.side_effect = docker.errors.DockerException('connection refused')

        with self.assertLogs('server_core.orchestrator', level='ERROR'):
            orchestrator = PluginOrchestrator()

        self.assertIsNone(orchestrator.container_statuses())
