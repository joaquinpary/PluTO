"""What happens to a plugin instance: launch, stop, sync, delete, and the
coordinates file of a file_tracker.

The API calls these, and so does the admin until it goes away; nothing here
knows about HTTP. A failure is a LifecycleError whose code the caller turns
into a response.
"""
import logging

from django.db import transaction

from .tokens import issue_token
from .models import PluginInstance, Rotor
from .mqtt_publish import publish_retained
from .orchestrator import PluginOrchestrator
from .plugin_handlers import get_handler
from .plugin_handlers.fields import config_errors
from .plugin_handlers.file_tracker import MAX_FILE_BYTES, build_file_message, input_topic

logger = logging.getLogger(__name__)

RUNNING = PluginInstance.Status.RUNNING
STOPPED = PluginInstance.Status.STOPPED
ERROR = PluginInstance.Status.ERROR


class LifecycleError(Exception):
    """code: 'invalid_config' | 'already_running' | 'board_busy' | 'docker' |
    'protected' | 'not_file_tracker' | 'bad_file' | 'broker'."""

    def __init__(self, code, detail, fields=None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.fields = fields


def _save_runtime(instance, status, container_id, api_token_hash):
    instance.status = status
    instance.container_id = container_id
    instance.api_token_hash = api_token_hash
    instance.save(update_fields=['status', 'container_id', 'api_token_hash', 'updated_at'])


def launch(instance):
    """Start the container of an instance that is STOPPED or in ERROR. Returns it RUNNING."""
    # The stored row, not whatever the caller holds: a type edited but never
    # saved must not decide which container gets started.
    instance.refresh_from_db()
    if instance.status == RUNNING:
        raise LifecycleError('already_running', f'{instance.name} is already running.')

    handler = get_handler(instance.plugin_type)
    if handler is None:
        raise LifecycleError('invalid_config', f'Unknown plugin type {instance.plugin_type!r}.')
    # Checked on save too; this catches a configuration stored before that.
    errors = config_errors(handler, instance.config)
    if errors:
        raise LifecycleError('invalid_config', 'The configuration is not valid. Fix it and save it before launching.', fields=errors)

    # A new token on every launch, so one leaked from an earlier container
    # stops working as soon as that container is replaced.
    api_token, api_token_hash = issue_token()

    # Claim the instance (and its board) before building, which can take
    # minutes: a second launch from another tab or the phone must find it
    # RUNNING instead of starting a clashing container and wiping the token.
    with transaction.atomic():
        if instance.rotor_id:
            # Serialises launches on one board, so RF-31.1 holds for two instances too.
            Rotor.objects.select_for_update().filter(pk=instance.rotor_id).first()
            # RF-31.1: one running instance drives a board at a time.
            driver = (
                PluginInstance.objects.filter(rotor_id=instance.rotor_id, status=RUNNING)
                .exclude(pk=instance.pk)
                .first()
            )
            if driver is not None:
                raise LifecycleError('board_busy', f'{driver.name} already drives {instance.rotor} (RF-31.1).')
        claimed = PluginInstance.objects.filter(pk=instance.pk, status__in=[STOPPED, ERROR]).update(
            status=RUNNING, container_id='', api_token_hash=api_token_hash,
        )
        if not claimed:
            raise LifecycleError('already_running', f'{instance.name} is already running.')

    try:
        success, result = PluginOrchestrator().spawn_plugin(
            plugin_type=instance.plugin_type,
            instance_id=instance.plugin_uuid,
            station_coordinates=instance.rotor.location if instance.rotor_id else None,
            api_token=api_token,
            rotor_device_id=instance.rotor.device_id if instance.rotor_id else None,
            **(instance.config or {}),
        )
    except Exception as exc:
        # docker-py also raises requests' own errors, e.g. a read timeout
        # while the first launch builds the image.
        success, result = False, str(exc)

    if not success:
        _save_runtime(instance, ERROR, '', '')
        raise LifecycleError('docker', result)

    _save_runtime(instance, RUNNING, result, api_token_hash)
    return instance


def stop(instance):
    """Remove the container and revoke its token. Works from any status, ERROR included."""
    instance.refresh_from_db()
    success, result = PluginOrchestrator().kill_plugin(instance.plugin_type, instance.plugin_uuid)
    if not success:
        # Nothing changes: the container may still be there, and so is its record.
        raise LifecycleError('docker', result)
    _save_runtime(instance, STOPPED, '', '')
    return instance


def _status_for(runtime_status):
    if runtime_status == 'running':
        return RUNNING
    if runtime_status == 'not_found':
        return STOPPED
    return ERROR


def sync(instance):
    """Make the stored status say what Docker says."""
    instance.refresh_from_db()
    success, runtime_status = PluginOrchestrator().get_container_status(instance.plugin_type, instance.plugin_uuid)
    if not success:
        raise LifecycleError('docker', 'Could not query the container status from Docker.')

    container_id, api_token_hash = instance.container_id, instance.api_token_hash
    if runtime_status == 'not_found':
        # No container left to use the token.
        container_id, api_token_hash = '', ''
    status = _status_for(runtime_status)

    if (instance.status, instance.container_id, instance.api_token_hash) != (status, container_id, api_token_hash):
        _save_runtime(instance, status, container_id, api_token_hash)
    return instance


def delete(instance):
    """Stop the instance unless it is STOPPED, then delete it.

    An instance that produced data or drove a board is kept, as the database
    already demands (PROTECT): its history must keep pointing at it. That is
    checked before stopping, so a refused delete leaves the instance as it was.
    """
    instance.refresh_from_db()
    if instance.data.exists() or instance.orders.exists():
        raise LifecycleError(
            'protected', f'{instance.name} has stored data or dispatch orders. Stop it instead of deleting it.',
        )
    if instance.status != STOPPED:
        stop(instance)

    plugin_type, plugin_uuid = instance.plugin_type, instance.plugin_uuid
    instance.delete()
    if plugin_type == 'file_tracker':
        _clear_coordinates_file(plugin_uuid)


def _clear_coordinates_file(plugin_uuid):
    # Otherwise the file outlives the instance, retained on a topic nobody
    # will ever read again.
    try:
        publish_retained(input_topic(plugin_uuid), b'')
    except Exception as exc:
        logger.warning('Could not clear the coordinates file of %s: %s', plugin_uuid, exc)


def send_coordinates_file(instance, uploaded_file):
    """Hand a coordinates file to a file_tracker, running or not.

    The message is retained: a running plugin gets it right away, a stopped
    one when it is launched. A new file replaces the previous one.
    """
    if instance.plugin_type != 'file_tracker':
        raise LifecycleError('not_file_tracker', 'Only file_tracker instances take a coordinates file.')
    config = instance.config or {}
    missing = [key for key in ('coord_type', 'coord_format') if not config.get(key)]
    if missing:
        raise LifecycleError('invalid_config', f'Set {" and ".join(missing)} in the configuration first.')

    # One byte past the limit is enough to know the file is too big.
    content = uploaded_file.read(MAX_FILE_BYTES + 1)
    try:
        message = build_file_message(config, uploaded_file.name, content)
    except ValueError as exc:
        raise LifecycleError('bad_file', str(exc)) from None

    try:
        publish_retained(input_topic(instance.plugin_uuid), message)
    except Exception as exc:
        logger.warning('Could not send the coordinates file of %s: %s', instance.name, exc)
        raise LifecycleError('broker', f'Could not reach the broker: {exc}') from None
