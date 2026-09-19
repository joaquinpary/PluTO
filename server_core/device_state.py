"""What the boards report about themselves (docs/contracts/device-state.md).

Pure parsing plus the ORM writes, called by the mqtt_ingest command for the
device/<device_id>/status and device/<device_id>/state topics.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from django.db.models.functions import Now
from django.utils import timezone as django_timezone

from .models import Rotor, RotorState

logger = logging.getLogger(__name__)

DEVICE_STATUS_TOPIC = 'device/+/status'
DEVICE_STATE_TOPIC = 'device/+/state'

DEVICE_ID_RE = re.compile(r'^[0-9a-f]{12}$')
STATUSES = {'online': True, 'offline': False}

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_device_topic(topic):
    """'device/<device_id>/<status|state>' -> (device_id, leaf), or None."""
    parts = topic.split('/')
    if len(parts) != 3:
        return None

    namespace, device_id, leaf = parts
    if namespace != 'device' or not DEVICE_ID_RE.match(device_id) or leaf not in ('status', 'state'):
        return None

    return device_id, leaf


def store_status(device_id, payload):
    """Apply an online/offline message. Returns False if the payload is not one."""
    online = STATUSES.get(payload.decode('utf-8', errors='replace').strip())
    if online is None:
        logger.warning('Ignoring unknown status %r from %s', payload[:32], device_id)
        return False

    rotor, _ = Rotor.objects.get_or_create(device_id=device_id)
    # The status is retained, so it comes again on every reconnect of the
    # ingester: only a real change moves status_changed_at.
    if rotor.online != online or rotor.status_changed_at is None:
        rotor.online = online
        rotor.status_changed_at = django_timezone.now()
        rotor.save(update_fields=['online', 'status_changed_at'])
    return True


def _int(value):
    # bool is an int in Python, and true is not a number of milliseconds.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool(value):
    return value if isinstance(value, bool) else None


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else ''


def _board_time(ts_ms):
    if ts_ms is None:
        return None
    try:
        return _EPOCH + timedelta(milliseconds=ts_ms)
    except OverflowError:
        return None


def store_state(device_id, payload):
    """Store one state document. Returns False if it is not a JSON object.

    Fields with an unexpected type are stored as empty rather than rejecting
    the whole document: the raw document is kept in `payload` either way.
    """
    try:
        document = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning('Ignoring undecodable state from %s: %s', device_id, exc)
        return False

    if not isinstance(document, dict):
        logger.warning('Ignoring non-object state from %s', device_id)
        return False

    batch = document.get('batch') if isinstance(document.get('batch'), dict) else {}
    clock_synced = document.get('clock_synced') is True
    rejected_total = _int(document.get('rejected_total'))

    rotor, _ = Rotor.objects.get_or_create(device_id=device_id)
    RotorState.objects.create(
        rotor=rotor,
        board_time=_board_time(_int(document.get('ts_ms'))) if clock_synced else None,
        clock_synced=clock_synced,
        mode=_text(document.get('mode'), 16),
        az_cdeg=_int(document.get('az_cdeg')),
        el_cdeg=_int(document.get('el_cdeg')),
        pan_mode=_text(document.get('pan_mode'), 16),
        batch_accepted=_bool(batch.get('accepted')),
        batch_error=_text(batch.get('error'), 32),
        latency_ms=_int(batch.get('latency_ms')),
        rejected_total=rejected_total if rejected_total and rejected_total > 0 else 0,
        payload=document,
    )
    Rotor.objects.filter(pk=rotor.pk).update(last_state_at=Now())
    return True
