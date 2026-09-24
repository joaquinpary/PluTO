from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import SimpleTestCase

from .mqtt_runtime import wait_for_migrations

MODULE = 'server_core.mqtt_runtime'


class WaitForMigrationsTests(SimpleTestCase):
    def test_polls_until_nothing_is_left_to_apply(self):
        with patch(f'{MODULE}.MigrationExecutor') as executor_cls:
            executor_cls.return_value.migration_plan.side_effect = [['0002_plugindata'], []]
            sleep = MagicMock()

            with self.assertLogs(MODULE, level='INFO'):
                wait_for_migrations(sleep=sleep)

        sleep.assert_called_once()

    def test_keeps_waiting_while_postgres_is_down(self):
        with patch(f'{MODULE}.MigrationExecutor') as executor_cls, patch(f'{MODULE}.connection'):
            executor_cls.side_effect = [OperationalError('connection refused'), MagicMock(**{'migration_plan.return_value': []})]
            sleep = MagicMock()

            with self.assertLogs(MODULE, level='INFO'):
                wait_for_migrations(sleep=sleep)

        sleep.assert_called_once()
