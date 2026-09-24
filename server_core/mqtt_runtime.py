"""What every MQTT command in server_core needs before it can consume anything.

Both mqtt_ingest and mqtt_dispatch run as their own container from the server
image, and both have to wait for the same thing before touching the database.
"""
import logging
import time

from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor

logger = logging.getLogger(__name__)


def wait_for_migrations(delay=2.0, sleep=time.sleep):
    """Block until PostgreSQL answers and every migration is applied.

    The server container runs `migrate` on start; consuming MQTT before that
    would only turn every message into a failure.
    """
    while True:
        try:
            executor = MigrationExecutor(connection)
            if not executor.migration_plan(executor.loader.graph.leaf_nodes()):
                logger.info('PostgreSQL ready and migrations applied')
                return
            logger.info('Waiting for the server to apply the migrations...')
        except DatabaseError as exc:
            logger.info('Waiting for PostgreSQL: %s', exc)
            connection.close()
        sleep(delay)
