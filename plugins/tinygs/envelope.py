"""Builds the envelope this plugin republishes for the central ingester.

Pure stdlib and no I/O on purpose: this is the logic that is easiest to get
wrong and cheapest to test, the same split file_tracker/parser.py and
coord_transform/transformer.py already use.
"""
import base64
import json
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# base64 inflates by 33% and Mongo documents cap at 16 MB, so a board with
# broken firmware must not be able to fill the collection.
MAX_PAYLOAD_BYTES = 64 * 1024
PREVIEW_BYTES = 1024


def normalize_payload(raw):
    """Turn the board's raw bytes into (dict, payload_format).

    The result is always a dict: PluginData.payload is a DictField, so a bare
    list or scalar would be rejected on save. Note that json.loads(b"42")
    returns 42 and json.loads(b"null") returns None -- both are valid JSON and
    neither is a dict.
    """
    size = len(raw)

    if size > MAX_PAYLOAD_BYTES:
        return {
            'truncated': True,
            'size': size,
            'preview_base64': base64.b64encode(raw[:PREVIEW_BYTES]).decode('ascii'),
        }, 'truncated'

    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return {'raw_base64': base64.b64encode(raw).decode('ascii'), 'size': size}, 'binary'

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {'text': text}, 'text'

    if isinstance(parsed, dict):
        return parsed, 'json'
    if isinstance(parsed, list):
        return {'items': parsed}, 'json_array'
    return {'value': parsed}, 'json_scalar'


def build_envelope(plugin_id, plugin_type, device, message_type, source_topic, raw, now=None):
    """Wrap one board message with everything the ingester needs to store it."""
    payload, payload_format = normalize_payload(raw)
    timestamp = now or datetime.now(timezone.utc)

    return {
        'schema_version': SCHEMA_VERSION,
        'message_id': str(uuid.uuid4()),
        'plugin_id': plugin_id,
        'plugin_type': plugin_type,
        'device': device,
        'message_type': message_type,
        'source_topic': source_topic,
        'received_at': timestamp.isoformat(),
        'payload_format': payload_format,
        'payload': payload,
    }
