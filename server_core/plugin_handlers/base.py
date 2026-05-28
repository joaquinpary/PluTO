import json
from abc import ABC


class BasePluginHandler(ABC):
    def validate(self, config):
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