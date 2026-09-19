"""Subscribes to the plugin data topics and persists every message into PostgreSQL.

Runs as its own container from the server image (see the `mqtt_ingest` service
in docker-compose.yml) rather than inside the Django server: `loop_forever()`
under `runserver` would be duplicated by the autoreloader and write everything
twice. It writes through the same models as the rest of server_core, so the
schema lives in one place.
"""
import json
import logging
import os
import re
import signal
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from server_core.models import PluginData, PluginInstance

logger = logging.getLogger(__name__)

INGEST_TOPIC = 'plugin/+/data/+'
MESSAGE_TYPE_RE = re.compile(r'^[a-z0-9_-]{1,32}$')

INGESTED = 'ingested'
DUPLICATE = 'duplicate'
UNKNOWN_PLUGIN = 'unknown_plugin'

# Only these envelope keys ever reach a column. Everything else in the envelope
# is dropped, so a publisher can't set created_at or the plugin it belongs to.
# plugin_type isn't copied either: the row's plugin foreign key already says it.
_ENVELOPE_FIELDS = ('device', 'payload_format', 'message_id', 'source_topic')


def parse_ingest_topic(topic):
    """'plugin/<plugin_id>/data/<message_type>' -> (plugin_id, message_type), or None."""
    parts = topic.split('/')
    if len(parts) != 4:
        return None

    namespace, plugin_id, section, message_type = parts
    if namespace != 'plugin' or section != 'data':
        return None
    if not plugin_id or not MESSAGE_TYPE_RE.match(message_type):
        return None

    return plugin_id, message_type


def normalize_datetime(value):
    """Parse an ISO-8601 string into an aware UTC datetime.

    received_at is a timestamptz column. A naive value would be read in the
    session's time zone, and one without an offset is assumed to be UTC.
    """
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        logger.warning('Could not parse received_at value %r', value)
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def build_document_fields(topic, payload):
    """Turn a raw MQTT message into the fields of one PluginData row, or None if unusable."""
    parsed_topic = parse_ingest_topic(topic)
    if parsed_topic is None:
        logger.warning('Ignoring message on unexpected topic %s', topic)
        return None

    plugin_id, message_type = parsed_topic

    try:
        envelope = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning('Ignoring undecodable envelope on %s: %s', topic, exc)
        return None

    if not isinstance(envelope, dict):
        logger.warning('Ignoring non-object envelope on %s', topic)
        return None

    declared_plugin_id = envelope.get('plugin_id')
    if declared_plugin_id and declared_plugin_id != plugin_id:
        # The topic wins: a plugin cannot claim another instance's data without
        # publishing on that instance's topic.
        logger.warning(
            'Envelope on %s declares plugin_id %s, using the one from the topic instead',
            topic, declared_plugin_id,
        )

    fields = {
        'plugin_id': plugin_id,
        'message_type': message_type,
        'ingest_topic': topic,
        'received_at': normalize_datetime(envelope.get('received_at')),
    }

    for key in _ENVELOPE_FIELDS:
        value = envelope.get(key)
        if value is not None:
            fields[key] = str(value)

    schema_version = envelope.get('schema_version')
    if isinstance(schema_version, int):
        fields['schema_version'] = schema_version

    body = envelope.get('payload')
    if isinstance(body, dict):
        fields['payload'] = body
    else:
        # The payload column always holds a JSON object, so anything else is wrapped.
        fields['payload'] = {'value': body}
        fields['payload_format'] = 'coerced'

    return fields


def store_message(fields):
    """Persist one message. Returns INGESTED, DUPLICATE or UNKNOWN_PLUGIN.

    The plugin_id in the topic must be the uuid of an existing PluginInstance,
    so no row can point at a plugin that does not exist.
    """
    fields = dict(fields)
    try:
        plugin_uuid = uuid.UUID(fields.pop('plugin_id'))
    except ValueError:
        return UNKNOWN_PLUGIN

    plugin = PluginInstance.objects.filter(plugin_uuid=plugin_uuid).first()
    if plugin is None:
        return UNKNOWN_PLUGIN

    try:
        # The savepoint keeps a rejected INSERT from breaking an outer transaction.
        with transaction.atomic():
            PluginData.objects.create(plugin=plugin, **fields)
    except IntegrityError:
        # message_id is unique: a QoS 1 redelivery carries the same one.
        message_id = fields.get('message_id')
        if message_id and PluginData.objects.filter(message_id=message_id).exists():
            return DUPLICATE
        raise

    return INGESTED


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


class Command(BaseCommand):
    help = 'Subscribes to plugin data topics and persists the messages into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--topic', default=INGEST_TOPIC, help='Topic filter to subscribe to.')
        parser.add_argument('--qos', type=int, default=1, help='Subscription QoS.')
        parser.add_argument('--host', default=None, help='Overrides MQTT_HOST.')
        parser.add_argument('--port', type=int, default=None, help='Overrides MQTT_PORT.')
        parser.add_argument('--client-id', default='pluto-mqtt-ingest')
        parser.add_argument('--log-level', default=os.environ.get('LOG_LEVEL', 'INFO').upper())

    def handle(self, *args, **options):
        # Django configures handlers for its own loggers only, so without this
        # every INFO line from this command would be silently dropped.
        logging.basicConfig(
            level=options['log_level'],
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        )

        self.topic = options['topic']
        self.qos = options['qos']
        self.stats = {'ingested': 0, 'duplicate': 0, 'rejected': 0, 'failed': 0}

        wait_for_migrations()

        host = options['host'] or settings.MQTT_CONFIG['HOST']
        port = options['port'] or settings.MQTT_CONFIG['PORT']
        username = settings.MQTT_CONFIG['USERNAME']
        password = settings.MQTT_CONFIG['PASSWORD']

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=options['client_id'])
        if username and password:
            client.username_pw_set(username, password)

        # A single bad message must never take the ingester down.
        client.suppress_exceptions = True
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        self._install_signal_handlers(client)

        logger.info('Connecting to MQTT broker at %s:%s', host, port)
        client.connect(host, port, 60)
        try:
            # depends_on does not wait for the broker to be ready.
            client.loop_forever(retry_first_connection=True)
        except KeyboardInterrupt:
            logger.info('Shutting down MQTT ingester...')
            client.disconnect()

        logger.info('Final stats: %s', self.stats)

    def _install_signal_handlers(self, client):
        def shutdown(_signum, _frame):
            logger.info('Signal received, disconnecting from the broker...')
            client.disconnect()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.error('Failed to connect to MQTT broker with reason code %s', reason_code)
            return

        logger.info('Connected to MQTT broker successfully.')
        # Subscribing here means the subscription comes back on its own after a
        # broker restart.
        client.subscribe(self.topic, qos=self.qos)
        logger.info('Subscribed to %s with qos=%s', self.topic, self.qos)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.warning('Disconnected from MQTT broker (reason code %s), reconnecting...', reason_code)

    def on_message(self, client, userdata, msg):
        try:
            fields = build_document_fields(msg.topic, msg.payload)
            if fields is None:
                self.stats['rejected'] += 1
                return

            # What Django does before every request: drop a connection that is
            # stale or died (PostgreSQL restarted), so the query opens a fresh one.
            close_old_connections()

            outcome = store_message(fields)
            if outcome == UNKNOWN_PLUGIN:
                self.stats['rejected'] += 1
                logger.warning('Ignoring message on %s: no plugin instance with that uuid', msg.topic)
            elif outcome == DUPLICATE:
                self.stats['duplicate'] += 1
                logger.info('Skipping redelivered message %s on %s', fields.get('message_id'), msg.topic)
            else:
                self.stats['ingested'] += 1
                logger.info(
                    '[%s] plugin=%s device=%s format=%s id=%s',
                    fields['message_type'], fields['plugin_id'],
                    fields.get('device'), fields.get('payload_format'), fields.get('message_id'),
                )
        except DatabaseError as exc:
            self.stats['failed'] += 1
            logger.error('Could not persist message from %s: %s', msg.topic, exc)
        except Exception:
            self.stats['failed'] += 1
            logger.exception('Unexpected error handling message from %s', msg.topic)

        total = sum(self.stats.values())
        if total and total % 100 == 0:
            logger.info('Stats: %s', self.stats)
