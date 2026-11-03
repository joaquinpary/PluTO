"""The plugin endpoints of the front end: types, create, edit and delete, actions and logs."""
import json
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
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


class PluginActionTests(PluginApiTestCase):
    def setUp(self):
        super().setUp()
        self.plugin = self.tinygs()

    def post(self, action):
        return self.client.post(f'/api/plugins/{self.plugin.plugin_uuid}/{action}')

    def test_each_action_goes_through_the_lifecycle_and_answers_the_instance(self):
        for action, status in [('launch', 'RUNNING'), ('stop', 'STOPPED'), ('sync', 'ERROR')]:
            def apply(plugin, status=status):
                plugin.status = status
                plugin.save()
                return plugin

            with self.subTest(action=action), patch(f'server_core.lifecycle.{action}', side_effect=apply) as call:
                response = self.post(action)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.json()), PLUGIN_KEYS)
                self.assertEqual(response.json()['status'], status)
                self.assertEqual(call.call_args.args[0].pk, self.plugin.pk)

    def test_lifecycle_errors_become_http_codes(self):
        cases = [
            ('launch', 'invalid_config', 400),
            ('launch', 'board_busy', 409),
            ('launch', 'already_running', 409),
            ('launch', 'docker', 502),
            ('stop', 'docker', 502),
            ('sync', 'docker', 502),
        ]
        for action, code, http_status in cases:
            error = LifecycleError(code, f'{code} happened')
            with self.subTest(action=action, code=code), patch(f'server_core.lifecycle.{action}', side_effect=error):
                response = self.post(action)

                self.assertEqual(response.status_code, http_status)
                self.assertEqual(response.json(), {'detail': f'{code} happened'})

    def test_an_invalid_config_on_launch_comes_by_field(self):
        error = LifecycleError('invalid_config', 'Fix the configuration first.',
                               fields={'tinygs_device': ['This field is required.']})
        with patch('server_core.lifecycle.launch', side_effect=error):
            response = self.post('launch')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {
            'detail': 'Fix the configuration first.',
            'config': {'tinygs_device': ['This field is required.']},
        })

    def test_actions_are_post_only_and_need_a_known_instance(self):
        self.assertEqual(self.client.get(f'/api/plugins/{self.plugin.plugin_uuid}/launch').status_code, 405)
        self.assertEqual(self.client.post(f'/api/plugins/{UNKNOWN_UUID}/launch').status_code, 404)


class CoordinatesFileTests(PluginApiTestCase):
    def setUp(self):
        super().setUp()
        self.plugin = PluginInstance.objects.create(
            name='tracker', plugin_type='file_tracker', config={'coord_type': 'ENU', 'coord_format': 'POLAR'},
        )
        self.url = f'/api/plugins/{self.plugin.plugin_uuid}/coordinates-file'

    def upload(self, content=b'0 45 10\n'):
        return self.client.post(self.url, {'file': SimpleUploadedFile('pass.txt', content)})

    def test_hands_the_upload_to_the_lifecycle(self):
        received = {}

        def send(plugin, upload):
            # Read here: the upload is closed once the response is out.
            received.update(plugin=plugin.pk, name=upload.name, content=upload.read())

        with patch('server_core.lifecycle.send_coordinates_file', side_effect=send):
            response = self.upload()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'tracker')
        self.assertEqual(received, {'plugin': self.plugin.pk, 'name': 'pass.txt', 'content': b'0 45 10\n'})

    def test_what_the_lifecycle_rejects_is_a_bad_request(self):
        for code in ('not_file_tracker', 'bad_file'):
            error = LifecycleError(code, f'{code} happened')
            with self.subTest(code=code), patch('server_core.lifecycle.send_coordinates_file', side_effect=error):
                response = self.upload()

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {'detail': f'{code} happened'})

    def test_an_unreachable_broker_is_service_unavailable(self):
        error = LifecycleError('broker', 'Could not reach the broker: refused')
        with patch('server_core.lifecycle.send_coordinates_file', side_effect=error):
            response = self.upload()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Could not reach the broker: refused'})

    @patch('server_core.lifecycle.send_coordinates_file')
    def test_without_a_file_nothing_is_sent(self, send):
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 400)
        self.assertIn('file', response.json())
        send.assert_not_called()


class PluginLogsTests(PluginApiTestCase):
    def setUp(self):
        super().setUp()
        self.plugin = self.tinygs()
        self.url = f'/api/plugins/{self.plugin.plugin_uuid}/logs'

    def test_the_last_100_lines_by_default(self):
        self.orchestrator.container_logs.return_value = ['connected', 'subscribed']

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'source': 'tinygs-1', 'lines': ['connected', 'subscribed']})
        self.orchestrator.container_logs.assert_called_once_with('tinygs', self.plugin.plugin_uuid, 100)

    def test_tail_goes_from_1_to_1000(self):
        self.assertEqual(self.client.get(f'{self.url}?tail=1000').status_code, 200)
        self.orchestrator.container_logs.assert_called_once_with('tinygs', self.plugin.plugin_uuid, 1000)

        for tail in ('0', '1001', 'many'):
            with self.subTest(tail=tail):
                response = self.client.get(f'{self.url}?tail={tail}')

                self.assertEqual(response.status_code, 400)
                self.assertIn('tail', response.json())

    def test_an_instance_without_a_container_is_not_found(self):
        # container_logs() answers None without a container (Task 2).
        self.orchestrator.container_logs.return_value = None

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'detail': 'tinygs-1 has no container. Launch it first.'})

    def test_without_docker_it_is_a_bad_gateway(self):
        self.orchestrator.client = None

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {'detail': 'Could not reach Docker.'})
        self.orchestrator.container_logs.assert_not_called()
