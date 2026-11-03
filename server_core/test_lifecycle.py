from unittest.mock import patch

from django.test import TestCase

from .api_tokens import hash_token
from .lifecycle import LifecycleError, launch
from .models import PluginInstance, Rotor

DEVICE_ID = 'a1b2c3d4e5f6'
RUNNING = PluginInstance.Status.RUNNING
STOPPED = PluginInstance.Status.STOPPED
ERROR = PluginInstance.Status.ERROR


@patch('server_core.lifecycle.PluginOrchestrator')
class LaunchTests(TestCase):
    def setUp(self):
        self.rotor = Rotor.objects.create(device_id=DEVICE_ID)
        self.plugin = PluginInstance.objects.create(
            name='tinygs-1', plugin_type='tinygs', rotor=self.rotor, config={'tinygs_device': 'My_TinyGS'},
        )

    def spawned(self, orchestrator_cls):
        """The keyword arguments spawn_plugin got."""
        return orchestrator_cls.return_value.spawn_plugin.call_args.kwargs

    def test_hands_the_container_a_token_its_board_and_its_config(self, orchestrator_cls):
        orchestrator_cls.return_value.spawn_plugin.return_value = (True, 'container-123')

        launch(self.plugin)

        kwargs = self.spawned(orchestrator_cls)
        self.assertEqual(kwargs['plugin_type'], 'tinygs')
        self.assertEqual(kwargs['instance_id'], self.plugin.plugin_uuid)
        self.assertEqual(kwargs['rotor_device_id'], DEVICE_ID)
        self.assertEqual(kwargs['tinygs_device'], 'My_TinyGS')
        self.plugin.refresh_from_db()
        self.assertEqual((self.plugin.status, self.plugin.container_id), (RUNNING, 'container-123'))
        # Only the hash is kept, and it is the hash of what the container got.
        self.assertEqual(self.plugin.api_token_hash, hash_token(kwargs['api_token']))

    def test_a_failed_launch_is_an_error_and_leaves_no_token(self, orchestrator_cls):
        orchestrator_cls.return_value.spawn_plugin.return_value = (False, 'boom')
        self.plugin.api_token_hash = 'stale'
        self.plugin.save()

        with self.assertRaises(LifecycleError) as raised:
            launch(self.plugin)

        self.assertEqual((raised.exception.code, raised.exception.detail), ('docker', 'boom'))
        self.plugin.refresh_from_db()
        self.assertEqual((self.plugin.status, self.plugin.container_id, self.plugin.api_token_hash), (ERROR, '', ''))

    def test_an_unexpected_docker_failure_is_an_error_too(self, orchestrator_cls):
        # docker-py also raises requests' own errors, e.g. a read timeout while building.
        orchestrator_cls.return_value.spawn_plugin.side_effect = TimeoutError('read timed out')

        with self.assertRaises(LifecycleError) as raised:
            launch(self.plugin)

        self.assertEqual(raised.exception.code, 'docker')
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.status, ERROR)

    def test_an_invalid_config_never_reaches_docker(self, orchestrator_cls):
        self.plugin.config = {}
        self.plugin.save()

        with self.assertRaises(LifecycleError) as raised:
            launch(self.plugin)

        self.assertEqual(raised.exception.code, 'invalid_config')
        orchestrator_cls.return_value.spawn_plugin.assert_not_called()
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.status, STOPPED)

    def test_a_running_instance_is_not_launched_again(self, orchestrator_cls):
        self.plugin.status = RUNNING
        self.plugin.save()

        with self.assertRaises(LifecycleError) as raised:
            launch(self.plugin)

        self.assertEqual(raised.exception.code, 'already_running')
        orchestrator_cls.return_value.spawn_plugin.assert_not_called()

    def test_a_board_driven_by_another_running_instance_is_busy(self, orchestrator_cls):
        # RF-31.1. The admin never checked it when launching.
        PluginInstance.objects.create(name='tinygs-2', plugin_type='tinygs', rotor=self.rotor, status=RUNNING)

        with self.assertRaises(LifecycleError) as raised:
            launch(self.plugin)

        self.assertEqual(raised.exception.code, 'board_busy')
        self.assertIn('tinygs-2', raised.exception.detail)
        orchestrator_cls.return_value.spawn_plugin.assert_not_called()
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.status, STOPPED)

    def test_stopped_instances_of_the_same_board_do_not_block_it(self, orchestrator_cls):
        orchestrator_cls.return_value.spawn_plugin.return_value = (True, 'container-123')
        PluginInstance.objects.create(name='tinygs-2', plugin_type='tinygs', rotor=self.rotor)

        launch(self.plugin)

        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.status, RUNNING)

    def test_an_instance_in_error_can_be_launched_again(self, orchestrator_cls):
        orchestrator_cls.return_value.spawn_plugin.return_value = (True, 'container-123')
        self.plugin.status = ERROR
        self.plugin.save()

        launch(self.plugin)

        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.status, RUNNING)

    def test_launches_the_stored_type(self, orchestrator_cls):
        orchestrator_cls.return_value.spawn_plugin.return_value = (True, 'container-123')
        self.plugin.plugin_type = 'file_tracker'  # edited, never saved

        launch(self.plugin)

        self.assertEqual(self.spawned(orchestrator_cls)['plugin_type'], 'tinygs')
