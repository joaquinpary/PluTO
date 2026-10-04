from unittest.mock import patch

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
