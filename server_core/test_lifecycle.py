from unittest.mock import patch

from django.test import TestCase

from .api_tokens import hash_token
from .lifecycle import LifecycleError, launch, stop, sync
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


@patch('server_core.lifecycle.PluginOrchestrator')
class StopTests(TestCase):
    def setUp(self):
        self.plugin = PluginInstance.objects.create(
            name='tinygs-1', plugin_type='tinygs', status=RUNNING,
            container_id='container-123', api_token_hash='a' * 64,
        )

    def runtime(self):
        self.plugin.refresh_from_db()
        return self.plugin.status, self.plugin.container_id, self.plugin.api_token_hash

    def test_stopping_removes_the_container_and_revokes_the_token(self, orchestrator_cls):
        orchestrator_cls.return_value.kill_plugin.return_value = (True, 'Plugin shut down correctly.')

        stop(self.plugin)

        orchestrator_cls.return_value.kill_plugin.assert_called_once_with('tinygs', self.plugin.plugin_uuid)
        self.assertEqual(self.runtime(), (STOPPED, '', ''))

    def test_stops_from_error(self, orchestrator_cls):
        # The admin only stopped RUNNING instances, so one in ERROR needed a sync first.
        orchestrator_cls.return_value.kill_plugin.return_value = (True, 'Plugin shut down correctly.')
        self.plugin.status = ERROR
        self.plugin.save()

        stop(self.plugin)

        self.assertEqual(self.runtime(), (STOPPED, '', ''))

    def test_stops_the_container_of_the_stored_type(self, orchestrator_cls):
        # Editing the type of a running instance used to orphan its container.
        orchestrator_cls.return_value.kill_plugin.return_value = (True, 'Plugin shut down correctly.')
        self.plugin.plugin_type = 'file_tracker'  # edited, never saved

        stop(self.plugin)

        orchestrator_cls.return_value.kill_plugin.assert_called_once_with('tinygs', self.plugin.plugin_uuid)

    def test_a_failed_stop_changes_nothing(self, orchestrator_cls):
        orchestrator_cls.return_value.kill_plugin.return_value = (False, 'Internal error: boom')

        with self.assertRaises(LifecycleError) as raised:
            stop(self.plugin)

        self.assertEqual(raised.exception.code, 'docker')
        self.assertEqual(self.runtime(), (RUNNING, 'container-123', 'a' * 64))


@patch('server_core.lifecycle.PluginOrchestrator')
class SyncTests(TestCase):
    def setUp(self):
        self.plugin = PluginInstance.objects.create(
            name='tinygs-1', plugin_type='tinygs', status=RUNNING,
            container_id='container-123', api_token_hash='a' * 64,
        )

    def sync_with(self, orchestrator_cls, answer):
        orchestrator_cls.return_value.get_container_status.return_value = answer
        sync(self.plugin)
        self.plugin.refresh_from_db()
        return self.plugin.status, self.plugin.container_id, self.plugin.api_token_hash

    def test_a_vanished_container_stops_the_instance_and_revokes_its_token(self, orchestrator_cls):
        self.assertEqual(self.sync_with(orchestrator_cls, (True, 'not_found')), (STOPPED, '', ''))

    def test_a_container_that_is_not_running_is_an_error(self, orchestrator_cls):
        self.assertEqual(self.sync_with(orchestrator_cls, (True, 'exited')), (ERROR, 'container-123', 'a' * 64))

    def test_a_running_container_is_running(self, orchestrator_cls):
        self.plugin.status = ERROR
        self.plugin.save()

        self.assertEqual(self.sync_with(orchestrator_cls, (True, 'running')), (RUNNING, 'container-123', 'a' * 64))

    def test_without_docker_nothing_changes(self, orchestrator_cls):
        orchestrator_cls.return_value.get_container_status.return_value = (False, 'unknown')

        with self.assertRaises(LifecycleError) as raised:
            sync(self.plugin)

        self.assertEqual(raised.exception.code, 'docker')
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.status, RUNNING)
