import json
import logging
import re
import signal
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from mongoengine.errors import ValidationError
from pymongo.errors import PyMongoError

from models import PluginData

logger = logging.getLogger(__name__)

INGEST_TOPIC = 'plugin/+/data/+'
MESSAGE_TYPE_RE = re.compile(r'^[a-z0-9_-]{1,32}$')

# Only these envelope keys ever reach the document. PluginData is a
# DynamicDocument, so passing the envelope straight through would let any
# publisher create arbitrary top-level fields, including overwriting created_at.
_ENVELOPE_FIELDS = ('plugin_type', 'device', 'payload_format', 'message_id', 'source_topic')


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
    """Parse an ISO-8601 string into naive UTC.

    GenericJSONDocument.created_at is naive UTC, and mixing naive and aware
    datetimes in one collection breaks ordering and comparisons in subtle ways.
    """
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        logger.warning('Could not parse received_at value %r', value)
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def build_document_fields(topic, payload):
    """Turn a raw MQTT message into kwargs for PluginData, or None if unusable."""
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
        # payload is a DictField: anything else would raise ValidationError.
        fields['payload'] = {'value': body}
        fields['payload_format'] = 'coerced'

    return fields


class IngestMQTTClient:
    """
    Subscribes to every plugin's data topic and persists what arrives into
    MongoDB. One writer for all plugins, so the schema lives in a single place.
    """

    def __init__(self, broker_url, broker_port, username=None, password=None,
                 topic=INGEST_TOPIC, qos=1, client_id='pluto-mqtt-ingest'):
        self.broker_url = broker_url
        self.broker_port = broker_port
        self.topic = topic
        self.qos = qos
        self.stats = {'ingested': 0, 'rejected': 0, 'failed': 0}

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username and password:
            self.client.username_pw_set(username, password)

        # A single bad message must never take the ingester down.
        self.client.suppress_exceptions = True
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        self._install_signal_handlers()

    def start(self):
        logger.info('Connecting to MQTT broker at %s:%s', self.broker_url, self.broker_port)
        self.client.connect(self.broker_url, self.broker_port, 60)
        try:
            # depends_on does not wait for the broker to be ready.
            self.client.loop_forever(retry_first_connection=True)
        except KeyboardInterrupt:
            logger.info('Shutting down MQTT ingester...')
            self.client.disconnect()

        logger.info('Final stats: %s', self.stats)

    def _install_signal_handlers(self):
        def shutdown(_signum, _frame):
            logger.info('Signal received, disconnecting from the broker...')
            self.client.disconnect()

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

            document = PluginData(**fields)
            document.save()
            self.stats['ingested'] += 1
            logger.info(
                '[%s] plugin=%s device=%s format=%s -> %s',
                fields['message_type'], fields['plugin_id'],
                fields.get('device'), fields.get('payload_format'), document.id,
            )
        except (ValidationError, PyMongoError) as exc:
            self.stats['failed'] += 1
            logger.error('Could not persist message from %s: %s', msg.topic, exc)
        except Exception:
            self.stats['failed'] += 1
            logger.exception('Unexpected error handling message from %s', msg.topic)

        total = sum(self.stats.values())
        if total and total % 100 == 0:
            logger.info('Stats: %s', self.stats)
