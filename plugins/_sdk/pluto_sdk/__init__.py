"""What every PluTO plugin needs to talk to the server, copied into each plugin image.

The orchestrator launches a plugin with PLUTO_API_URL and PLUTO_API_TOKEN, and
with ROTOR_DEVICE_ID when a board is bound to the instance. from_environment()
turns those into a started ApiClient and, if there is a board, its BoardBridge.
"""
import os

from .api_client import ApiClient
from .board_bridge import BoardBridge

__all__ = ['ApiClient', 'BoardBridge', 'ConfigurationError', 'from_environment']


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
