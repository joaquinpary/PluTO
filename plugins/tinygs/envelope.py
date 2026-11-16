"""Builds the envelope this plugin sends to the server's /api/plugin-data/<type>.

Pure stdlib and no I/O on purpose: this is the logic that is easiest to get
wrong and cheapest to test, the same split file_tracker/parser.py and
coord_transform/transformer.py already use.
"""
import base64
import json
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# base64 adds 33% and every message is a row: broken firmware must not fill the table.
MAX_PAYLOAD_BYTES = 64 * 1024
PREVIEW_BYTES = 1024


def normalize_payload(raw):
    """Turn the board's raw bytes into (dict, payload_format).

    The result is always a dict: the server stores it in a column that holds
    a JSON object, so a bare list or scalar is wrapped. Text with U+0000 goes
    as binary: jsonb rejects it.
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
    # json.dumps escapes U+0000 as \u0000. An escaped backslash before "u0000"
    # also matches, which only sends the text as binary.
    return '\\u0000' in json.dumps(payload)


def build_envelope(plugin_id, plugin_type, device, message_type, source_topic, raw, now=None):
    """Wrap one board message with everything the server needs to store it."""
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
