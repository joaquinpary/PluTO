from .base import BasePluginHandler


_MQTT_RESERVED_CHARS = ("/", "+", "#")

# The optional pass settings, each with the check that makes it sensible. They
# reach the container on their own as upper-cased environment variables.
_NUMERIC_SETTINGS = {
    # The plugin only publishes the stretch of a pass above this. It must not
    # be lower than the assigned rotor's min_elevation_deg: the dispatcher cuts
    # a trajectory at its first point out of bounds, so a pass that starts
    # below the rotor's threshold is dropped whole.
    "min_elevation_deg": (lambda value: -90 <= value <= 90, "between -90 and 90"),
    "lookahead_minutes": (lambda value: value > 0, "greater than 0"),
    "sample_seconds": (lambda value: value > 0, "greater than 0"),
    "tle_ttl_hours": (lambda value: value > 0, "greater than 0"),
}


class TinyGSHandler(BasePluginHandler):
    def validate(self, config):
        device = config.get("tinygs_device")

        if not device or not str(device).strip():
            return "Error: tinygs_device is required for tinygs."

        if any(char in str(device) for char in _MQTT_RESERVED_CHARS):
            return "Error: tinygs_device cannot contain MQTT wildcard or separator characters (/ + #)."

        prefix = config.get("tinygs_topic_prefix")
        if prefix is not None and (not str(prefix).strip() or any(char in str(prefix) for char in _MQTT_RESERVED_CHARS)):
            return "Error: tinygs_topic_prefix must be a single topic segment, without / + or #."

        for key, (is_valid, requirement) in _NUMERIC_SETTINGS.items():
            if key not in config:
                continue
            value = config[key]
            # bool is an int in Python, and true is not a number of minutes.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"Error: {key} must be a number."
            if not is_valid(value):
                return f"Error: {key} must be {requirement}."

        return None
