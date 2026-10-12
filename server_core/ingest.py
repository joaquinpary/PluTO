"""Turns a plugin's envelope into a PluginData row.

Shared by the two ways data comes in: the REST endpoint (server_core/api.py)
and, until the plugins move to it, the mqtt_ingest command. Both know which
instance the envelope belongs to before calling in here, from the token or from
the topic, and that is the only plugin_id that counts.
"""
import logging
import re
from datetime import datetime, timezone

from django.db import IntegrityError, transaction

from .models import PluginData

logger = logging.getLogger(__name__)

MESSAGE_TYPE_RE = re.compile(r'^[a-z0-9_-]{1,32}$')

INGESTED = 'ingested'
DUPLICATE = 'duplicate'

# Only these envelope keys ever reach a column. Everything else in the envelope
# is dropped, so a publisher can't set created_at or the plugin it belongs to.
# plugin_type isn't copied either: the row's plugin foreign key already says it.
_ENVELOPE_FIELDS = ('device', 'payload_format', 'message_id', 'source_topic')


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


def envelope_fields(plugin_id, message_type, envelope, ingest_topic=''):
    """The PluginData fields for one decoded envelope, without the plugin itself.

    plugin_id and message_type come from the caller, never from the envelope;
    ingest_topic records where the message came in (an MQTT topic or an API path).
    """
    declared_plugin_id = envelope.get('plugin_id')
    if declared_plugin_id and str(declared_plugin_id) != str(plugin_id):
        # A plugin cannot claim another instance's data by writing its id here.
        logger.warning(
            'Envelope for %s declares plugin_id %s, using %s instead',
            ingest_topic or message_type, declared_plugin_id, plugin_id,
        )

    fields = {
        'message_type': message_type,
        'ingest_topic': ingest_topic,
        'received_at': normalize_datetime(envelope.get('received_at')),
    }

    for key in _ENVELOPE_FIELDS:
        value = envelope.get(key)
        if value is not None:
            fields[key] = str(value)

    schema_version = envelope.get('schema_version')
    if isinstance(schema_version, int) and not isinstance(schema_version, bool):
        fields['schema_version'] = schema_version

    body = envelope.get('payload')
    if isinstance(body, dict):
        fields['payload'] = body
    else:
        # The payload column always holds a JSON object, so anything else is wrapped.
        fields['payload'] = {'value': body}
        fields['payload_format'] = 'coerced'

    return fields


def store_document(plugin, fields):
    """Persist one envelope for a known plugin. Returns INGESTED or DUPLICATE."""
    try:
        # The savepoint keeps a rejected INSERT from breaking an outer transaction.
        with transaction.atomic():
            PluginData.objects.create(plugin=plugin, **fields)
    except IntegrityError:
        # message_id is unique: a retried request or a QoS 1 redelivery carries the same one.
        message_id = fields.get('message_id')
        if message_id and PluginData.objects.filter(message_id=message_id).exists():
            return DUPLICATE
        raise

    return INGESTED
