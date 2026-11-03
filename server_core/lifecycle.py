"""What happens to a plugin instance: launch, stop, sync, delete, and the
coordinates file of a file_tracker.

The API calls these, and so does the admin until it goes away; nothing here
knows about HTTP. A failure is a LifecycleError whose code the caller turns
into a response.
"""
import logging

from .api_tokens import issue_token
from .models import PluginInstance
from .orchestrator import PluginOrchestrator
from .plugin_handlers import PLUGIN_HANDLERS

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

    handler = PLUGIN_HANDLERS.get(instance.plugin_type)
    if handler is None:
        raise LifecycleError('invalid_config', f'Unknown plugin type {instance.plugin_type!r}.')
    error = handler.validate(instance.config or {})
    if error:
        raise LifecycleError('invalid_config', error)

    if instance.rotor_id:
        # RF-31.1: one running instance drives a board at a time.
        driver = (
            PluginInstance.objects.filter(rotor_id=instance.rotor_id, status=RUNNING)
            .exclude(pk=instance.pk)
            .first()
        )
        if driver is not None:
            raise LifecycleError('board_busy', f'{driver.name} already drives {instance.rotor} (RF-31.1).')

    # A new token on every launch, so one leaked from an earlier container
    # stops working as soon as that container is replaced.
    api_token, api_token_hash = issue_token()
    try:
        success, result = PluginOrchestrator().spawn_plugin(
            plugin_type=instance.plugin_type,
            instance_id=instance.plugin_uuid,
            station_coordinates=instance.station_coordinates,
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
