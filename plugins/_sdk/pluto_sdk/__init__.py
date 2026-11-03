"""What every PluTO plugin needs to talk to the server, copied into each plugin image.

The orchestrator launches a plugin with PLUTO_API_URL, PLUTO_API_TOKEN and
PLUTO_TRANSFORM_URL, and with ROTOR_DEVICE_ID when a board is bound to the
instance. from_environment() turns those into a started ApiClient and, if there
is a board, its BoardBridge; antenna_from_environment() builds what points it.
"""
import os

from .antenna import Antenna
from .api_client import ApiClient
from .board_bridge import BoardBridge
from .dispatcher import Dispatcher
from .transform_client import TransformClient

__all__ = [
    'Antenna', 'ApiClient', 'BoardBridge', 'ConfigurationError',
    'antenna_from_environment', 'from_environment',
]


class ConfigurationError(Exception):
    pass


def from_environment(environ=None):
    """(api, bridge) from the variables the orchestrator sets. bridge is None without a board."""
    environ = os.environ if environ is None else environ
    url = environ.get('PLUTO_API_URL', '').strip()
    token = environ.get('PLUTO_API_TOKEN', '').strip()
    if not url or not token:
        # Failing at start rather than producing data nobody will store.
        raise ConfigurationError(
            'PLUTO_API_URL and PLUTO_API_TOKEN are required; the orchestrator sets both '
            'when it launches the plugin.'
        )

    device_id = environ.get('ROTOR_DEVICE_ID', '').strip()
    api = ApiClient(url, token)
    try:
        bridge = BoardBridge(device_id, api) if device_id else None
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from None

    api.start()
    return api, bridge


def antenna_from_environment(api, publish, environ=None):
    """A started Antenna for the bound board, or None when the instance has none.

    publish(topic, payload) is the plugin's own MQTT publish: the batches go to
    the board over the connection the plugin already has.
    """
    environ = os.environ if environ is None else environ
    if not environ.get('ROTOR_DEVICE_ID', '').strip():
        return None

    transform_url = environ.get('PLUTO_TRANSFORM_URL', '').strip()
    if not transform_url:
        raise ConfigurationError(
            'PLUTO_TRANSFORM_URL is required to point a board; the orchestrator sets it '
            'when it launches the plugin.'
        )

    antenna = Antenna(api, TransformClient(transform_url), Dispatcher(publish, api.send_dispatch_order))
    antenna.start()
    return antenna
