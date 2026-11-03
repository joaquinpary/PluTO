"""The plugin endpoints of the front end: types, create, edit and delete, actions and logs."""
import json
from unittest.mock import MagicMock, patch

from django.test import Client

from .lifecycle import LifecycleError
from .models import PluginInstance, Rotor
from .orchestrator import PluginOrchestrator
from .test_api import DEVICE_ID, FrontTestCase

PLUGIN_KEYS = {
    'plugin_uuid', 'name', 'plugin_type', 'config', 'status', 'docker_status', 'board',
    'created_at', 'updated_at', 'warnings',
}
CONFIG_FIELD_KEYS = {'name', 'label', 'help', 'type', 'required', 'default', 'min', 'max', 'choices', 'pattern'}
UNKNOWN_UUID = '00000000-0000-4000-8000-000000000000'


def fake_orchestrator():
    """A PluginOrchestrator that never talks to Docker: real container names, canned answers."""
    orchestrator = PluginOrchestrator.__new__(PluginOrchestrator)
    orchestrator.client = MagicMock()
    orchestrator.container_statuses = MagicMock(return_value={})
    orchestrator.container_logs = MagicMock(return_value=[])
    return orchestrator


class PluginApiTestCase(FrontTestCase):
    """Logged in, with fake_orchestrator() in place of Docker for api_plugins."""

    def setUp(self):
        super().setUp()
        self.orchestrator = fake_orchestrator()
        patcher = patch('server_core.api_plugins.PluginOrchestrator', return_value=self.orchestrator)
        self.orchestrator_cls = patcher.start()
        self.addCleanup(patcher.stop)

    def tinygs(self, name='tinygs-1', **fields):
        fields.setdefault('config', {'tinygs_device': 'My_TinyGS'})
        return PluginInstance.objects.create(name=name, plugin_type='tinygs', **fields)

    def send(self, method, url, body):
        return getattr(self.client, method)(url, data=json.dumps(body), content_type='application/json')


class PluginTypesTests(PluginApiTestCase):
    def test_lists_every_type_with_the_fields_of_its_form(self):
        response = self.client.get('/api/plugin-types')

        self.assertEqual(response.status_code, 200)
        types = {plugin_type['type']: plugin_type for plugin_type in response.json()}
        self.assertEqual(set(types), {'file_tracker', 'tinygs'})
        self.assertEqual(types['tinygs']['message_types'], ['tracking', 'rx'])
        self.assertEqual(types['file_tracker']['message_types'], [])
        self.assertTrue(types['tinygs']['label'])
        self.assertIn('tinygs_device', [field['name'] for field in types['tinygs']['config_fields']])
        for plugin_type in types.values():
            for field in plugin_type['config_fields']:
                self.assertEqual(set(field), CONFIG_FIELD_KEYS)


class PluginListTests(PluginApiTestCase):
    def setUp(self):
        super().setUp()
        self.first = self.tinygs(status=PluginInstance.Status.RUNNING)
        self.tracker = PluginInstance.objects.create(
            name='tracker', plugin_type='file_tracker', config={'coord_type': 'ENU', 'coord_format': 'POLAR'},
        )
        self.second = self.tinygs(name='tinygs-2', status=PluginInstance.Status.ERROR)

    def names(self, query=''):
        response = self.client.get(f'/api/plugins{query}')
        self.assertEqual(response.status_code, 200)
        return [plugin['name'] for plugin in response.json()]

    def test_lists_every_instance_by_name(self):
        self.assertEqual(set(self.client.get('/api/plugins').json()[0]), PLUGIN_KEYS)
        self.assertEqual(self.names(), ['tinygs-1', 'tinygs-2', 'tracker'])

    def test_filters_by_type_status_and_name(self):
        self.assertEqual(self.names('?type=tinygs'), ['tinygs-1', 'tinygs-2'])
        self.assertEqual(self.names('?status=RUNNING'), ['tinygs-1'])
        self.assertEqual(self.names('?search=TRACK'), ['tracker'])
        self.assertEqual(self.names('?type=tinygs&status=ERROR'), ['tinygs-2'])

    def test_docker_status_comes_from_a_single_listing(self):
        self.orchestrator.container_statuses.return_value = {
            self.orchestrator.container_name('tinygs', self.first.plugin_uuid): 'running',
        }

        plugins = {plugin['name']: plugin for plugin in self.client.get('/api/plugins').json()}

        self.assertEqual(plugins['tinygs-1']['docker_status'], 'running')
        self.assertEqual(plugins['tinygs-2']['docker_status'], 'not_found')
        # KAN-50: one listing for the whole table, not one Docker call per row.
        self.orchestrator_cls.assert_called_once_with()
        self.orchestrator.container_statuses.assert_called_once_with()

    def test_docker_status_is_unknown_when_docker_does_not_answer(self):
        self.orchestrator.client = None

        plugins = self.client.get('/api/plugins').json()

        self.assertEqual({plugin['docker_status'] for plugin in plugins}, {'unknown'})

    def test_docker_status_is_unknown_when_the_listing_fails(self):
        # What container_statuses() answers when Docker errs (Task 2): it logs
        # the APIError itself and never raises it.
        self.orchestrator.container_statuses.return_value = None

        response = self.client.get('/api/plugins')

        self.assertEqual(response.status_code, 200)
        self.assertEqual({plugin['docker_status'] for plugin in response.json()}, {'unknown'})

    def test_needs_a_login(self):
        self.assertEqual(Client().get('/api/plugins').status_code, 401)


class PluginSchemaTests(PluginApiTestCase):
    def test_an_unbound_instance_is_null_in_the_schema(self):
        # frontend/src/api/schema.d.ts is generated from this schema: without
        # nullable, a Plugin's board would be typed as a string that never is null.
        schema = self.client.get('/api/schema', {'format': 'json'}).json()
        board = schema['components']['schemas']['Plugin']['properties']['board']

        self.assertIs(board['nullable'], True)


class PluginCreateTests(PluginApiTestCase):
    def create(self, **body):
        return self.send('post', '/api/plugins', body)

    def test_creates_a_stopped_instance_with_the_defaults_of_its_type(self):
        response = self.create(name='tinygs-1', plugin_type='tinygs', config={'tinygs_device': 'My_TinyGS'})

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), PLUGIN_KEYS)
        self.assertEqual(
            (body['status'], body['board'], body['warnings'], body['docker_status']),
            ('STOPPED', None, [], 'not_found'),
        )
        self.assertEqual(body['config']['min_elevation_deg'], 10)
        self.assertEqual(PluginInstance.objects.get().config, body['config'])

    def test_config_errors_come_by_field(self):
        cases = [
            ({}, 'tinygs_device'),
            ({'tinygs_device': 'mi estación'}, 'tinygs_device'),
            ({'tinygs_device': 'My_TinyGS', 'lookahead_minutes': 0}, 'lookahead_minutes'),
            ({'tinygs_device': 'My_TinyGS', 'min_elevation_deg': 91}, 'min_elevation_deg'),
        ]
        for config, field in cases:
            with self.subTest(config=config):
                response = self.create(name='tinygs-1', plugin_type='tinygs', config=config)

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['config'])
        self.assertFalse(PluginInstance.objects.exists())

    def test_rules_across_fields_come_as_non_field_errors(self):
        response = self.create(name='tracker', plugin_type='file_tracker',
                               config={'coord_type': 'ECI', 'coord_format': 'POLAR'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(response.json()['config']), ['non_field_errors'])

    def test_unknown_type_non_object_config_and_repeated_name_are_rejected(self):
        self.tinygs()
        cases = [
            ({'name': 'x', 'plugin_type': 'nope', 'config': {}}, 'plugin_type'),
            ({'name': 'x', 'plugin_type': 'tinygs', 'config': [1]}, 'config'),
            ({'name': 'tinygs-1', 'plugin_type': 'tinygs', 'config': {'tinygs_device': 'A'}}, 'name'),
        ]
        for body, field in cases:
            with self.subTest(field=field):
                response = self.create(**body)

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertEqual(PluginInstance.objects.count(), 1)


class PluginEditTests(PluginApiTestCase):
    def setUp(self):
        super().setUp()
        self.plugin = self.tinygs()
        self.url = f'/api/plugins/{self.plugin.plugin_uuid}'

    def test_shows_one_instance(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), PLUGIN_KEYS)
        self.assertEqual(response.json()['name'], 'tinygs-1')

    def test_edits_the_name_and_the_config(self):
        response = self.send('patch', self.url, {'name': 'roof', 'config': {'tinygs_device': 'Other_Station'}})

        self.assertEqual(response.status_code, 200)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.name, 'roof')
        self.assertEqual(self.plugin.config['tinygs_device'], 'Other_Station')
        self.assertEqual(self.plugin.config['min_elevation_deg'], 10)

    def test_the_type_and_the_status_are_read_only(self):
        response = self.send('patch', self.url, {'plugin_type': 'file_tracker', 'status': 'RUNNING'})

        self.assertEqual(response.status_code, 200)
        self.plugin.refresh_from_db()
        self.assertEqual((self.plugin.plugin_type, self.plugin.status), ('tinygs', 'STOPPED'))

    def test_an_invalid_config_changes_nothing(self):
        response = self.send('patch', self.url, {'name': 'roof', 'config': {'tinygs_device': 'bad device'}})

        self.assertEqual(response.status_code, 400)
        self.assertIn('tinygs_device', response.json()['config'])
        self.plugin.refresh_from_db()
        self.assertEqual((self.plugin.name, self.plugin.config), ('tinygs-1', {'tinygs_device': 'My_TinyGS'}))

    def test_renaming_does_not_validate_the_stored_config_again(self):
        PluginInstance.objects.filter(pk=self.plugin.pk).update(config={})

        self.assertEqual(self.send('patch', self.url, {'name': 'roof'}).status_code, 200)

    def test_a_running_instance_can_be_edited(self):
        PluginInstance.objects.filter(pk=self.plugin.pk).update(status=PluginInstance.Status.RUNNING)

        self.assertEqual(self.send('patch', self.url, {'name': 'roof'}).status_code, 200)

    def test_an_unknown_uuid_is_not_found(self):
        url = f'/api/plugins/{UNKNOWN_UUID}'

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.send('patch', url, {'name': 'x'}).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)


class PluginWarningTests(PluginApiTestCase):
    def setUp(self):
        super().setUp()
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID, min_elevation_deg=15)

    def warnings_for(self, name, min_elevation_deg, rotor):
        plugin = self.tinygs(name=name, rotor=rotor,
                             config={'tinygs_device': 'My_TinyGS', 'min_elevation_deg': min_elevation_deg})
        return self.client.get(f'/api/plugins/{plugin.plugin_uuid}').json()['warnings']

    def test_warns_when_the_plugin_threshold_is_below_the_board_one(self):
        warnings = self.warnings_for('low', 10, self.rotor)

        self.assertEqual(len(warnings), 1)
        self.assertIn('min_elevation_deg', warnings[0])

    def test_no_warning_otherwise(self):
        self.assertEqual(self.warnings_for('same', 15, self.rotor), [])
        self.assertEqual(self.warnings_for('high', 20, self.rotor), [])
        self.assertEqual(self.warnings_for('no-board', 0, None), [])


class PluginDeleteTests(PluginApiTestCase):
    def setUp(self):
        super().setUp()
        self.plugin = self.tinygs()
        self.url = f'/api/plugins/{self.plugin.plugin_uuid}'

    @patch('server_core.lifecycle.delete')
    def test_deletes_through_the_lifecycle(self, delete):
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(delete.call_args.args[0].pk, self.plugin.pk)

    @patch('server_core.lifecycle.delete', side_effect=LifecycleError('protected', 'tinygs-1 has data: stop it instead.'))
    def test_an_instance_with_history_is_a_conflict(self, delete):
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {'detail': 'tinygs-1 has data: stop it instead.'})
