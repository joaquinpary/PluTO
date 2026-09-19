from .base import BasePluginHandler


_MQTT_RESERVED_CHARS = ("/", "+", "#")


class TinyGSHandler(BasePluginHandler):
    def validate(self, config):
        device = config.get("tinygs_device")

        if not device or not str(device).strip():
            return "Error: tinygs_device is required for tinygs."

        if any(char in str(device) for char in _MQTT_RESERVED_CHARS):
            return "Error: tinygs_device cannot contain MQTT wildcard or separator characters (/ + #)."

        return None
