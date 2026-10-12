import json
from abc import ABC


class BasePluginHandler(ABC):
    # The message types this plugin may send to /api/plugin-data/<type>. None
    # accepts any type the URL pattern allows; an empty tuple, none at all.
    allowed_message_types = None

    def validate(self, config):
        return None

    def validate_data(self, message_type, payload):
        """Return an error string to reject one envelope's payload, or None."""
        return None

    def get_environment(self, config):
        environment = {}

        for key, value in config.items():
            if value is None:
                continue

            env_key = key.upper()
            if isinstance(value, (dict, list, tuple)):
                environment[env_key] = json.dumps(value)
            else:
                environment[env_key] = str(value)

        return environment

    def get_volumes(self, config):
        return None