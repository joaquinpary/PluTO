from unittest.mock import patch

from .test_api import FrontTestCase


@patch('server_core.api.logs.PluginOrchestrator')
class ServiceLogsApiTests(FrontTestCase):
    def test_returns_the_last_lines_of_a_service(self, orchestrator_cls):
        orchestrator_cls.return_value.service_logs.return_value = ['Starting gunicorn', 'Booting worker with pid: 8']

        response = self.client.get('/api/logs/server', {'tail': 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'source': 'server', 'lines': ['Starting gunicorn', 'Booting worker with pid: 8']})
        orchestrator_cls.return_value.service_logs.assert_called_once_with('server', 2)

    def test_tail_defaults_to_100_and_stops_at_1000(self, orchestrator_cls):
        orchestrator_cls.return_value.service_logs.return_value = []

        self.client.get('/api/logs/coord_transform')

        orchestrator_cls.return_value.service_logs.assert_called_once_with('coord_transform', 100)
        self.assertEqual(self.client.get('/api/logs/coord_transform', {'tail': 1001}).status_code, 400)
        self.assertEqual(self.client.get('/api/logs/coord_transform', {'tail': 'all'}).status_code, 400)

    def test_an_unknown_service_is_not_found_without_asking_docker(self, orchestrator_cls):
        for service in ('postgres', 'mqtt_dispatch', 'plugin-tinygs-x'):
            with self.subTest(service=service):
                self.assertEqual(self.client.get(f'/api/logs/{service}').status_code, 404)
        orchestrator_cls.assert_not_called()

    def test_a_service_without_a_container_is_not_found(self, orchestrator_cls):
        orchestrator_cls.return_value.service_logs.return_value = None

        response = self.client.get('/api/logs/coord_transform')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'detail': 'No container for the coord_transform service.'})

    def test_without_docker_it_is_a_bad_gateway(self, orchestrator_cls):
        orchestrator_cls.return_value.client = None

        response = self.client.get('/api/logs/server')

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {'detail': 'Could not reach Docker.'})

    def test_needs_a_login(self, orchestrator_cls):
        del self.client.defaults['HTTP_AUTHORIZATION']

        self.assertEqual(self.client.get('/api/logs/server').status_code, 401)
