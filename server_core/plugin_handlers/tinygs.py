import re
import unicodedata

from .base import BasePluginHandler


_MQTT_RESERVED_CHARS = ("/", "+", "#")

# The device name becomes a segment of the topics the plugin subscribes to, and
# it only hears anything if that segment matches the one the board publishes
# on. A space or an accent is legal in a topic, so a name carrying one is
# accepted by the broker and the plugin listens, silently, to nothing.
_DEVICE_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
_NOT_SLUG = re.compile(r"[^A-Za-z0-9_-]+")


def _suggest_slug(value):
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return _NOT_SLUG.sub("_", ascii_value).strip("_")

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

        if not _DEVICE_PATTERN.fullmatch(str(device)):
            error = "Error: tinygs_device may only contain letters, digits, _ and -."
            suggestion = _suggest_slug(str(device))
            return f'{error} Did you mean "{suggestion}"?' if suggestion else error

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
