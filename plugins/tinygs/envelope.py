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

# base64 inflates by 33% and every message becomes a PostgreSQL row, so a
# board with broken firmware must not be able to fill the table.
MAX_PAYLOAD_BYTES = 64 * 1024
PREVIEW_BYTES = 1024


def normalize_payload(raw):
    """Turn the board's raw bytes into (dict, payload_format).

    The result is always a dict: the ingester stores it in a column that holds
    a JSON object, so a bare list or scalar is wrapped. Note that
    json.loads(b"42") returns 42 and json.loads(b"null") returns None -- both
    are valid JSON and neither is a dict.

    Text carrying U+0000 goes as binary too: PostgreSQL's jsonb rejects that
    character, and base64 keeps the bytes intact.
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
        return _binary(raw)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        payload, payload_format = {'text': text}, 'text'
    else:
        if isinstance(parsed, dict):
            payload, payload_format = parsed, 'json'
        elif isinstance(parsed, list):
            payload, payload_format = {'items': parsed}, 'json_array'
        else:
            payload, payload_format = {'value': parsed}, 'json_scalar'

    if _has_nul(payload):
        return _binary(raw)
    return payload, payload_format


def _binary(raw):
    return {'raw_base64': base64.b64encode(raw).decode('ascii'), 'size': len(raw)}, 'binary'


def _has_nul(payload):
    # json.dumps writes U+0000 as the escape \u0000. An escaped backslash
    # followed by "u0000" matches too; that only sends the text as binary,
    # which loses nothing.
    return '\\u0000' in json.dumps(payload)


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
