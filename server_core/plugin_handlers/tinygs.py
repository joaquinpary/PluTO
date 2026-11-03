import re
import unicodedata

from .base import BasePluginHandler
from .fields import config_field


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
    # One per topic the plugin relays from the board (plugins/tinygs/mqtt_handler.py).
    label = "TinyGS"

    config_fields = (
        # It becomes a segment of the topics the plugin subscribes to, and the
        # plugin only hears anything if it matches the one the board publishes
        # on. A space or an accent is legal in a topic, so a name carrying one
        # is accepted by the broker and the plugin listens, silently, to nothing.
        config_field(
            "tinygs_device", "Dispositivo TinyGS", "string", required=True, pattern=r"[A-Za-z0-9_-]+",
            help="El nombre de la estación en sus tópicos MQTT: letras, dígitos, _ y -.",
        ),
        config_field(
            "tinygs_topic_prefix", "Prefijo de los tópicos", "string", pattern=r"[^/+#\s]+",
            help='El prefijo MQTT configurado en la estación, sin / + # ni espacios. Vacío usa "pluto".',
        ),
        # Not lower than the board's min_elevation_deg: the antenna cuts a
        # trajectory at its first point out of bounds, so a pass that starts
        # below the board's threshold is dropped whole.
        config_field(
            "min_elevation_deg", "Elevación mínima (°)", "number", min=-90, max=90, default=10,
            help="Solo se publica el tramo de la pasada por encima de esta elevación. No la pongas por debajo de la de la placa.",
        ),
        # "Greater than 0" for the three below, as a minimum the form can show.
        config_field(
            "lookahead_minutes", "Anticipación (min)", "number", min=1, default=20,
            help="Solo se publica una pasada que empieza dentro de este plazo.",
        ),
        config_field(
            "sample_seconds", "Paso entre puntos (s)", "number", min=0.1, default=1,
            help="Cada cuánto tiempo se calcula un punto de la pasada.",
        ),
        config_field(
            "tle_ttl_hours", "Vigencia del TLE (h)", "number", min=1, default=12,
            help="Cada cuánto se vuelven a pedir los elementos orbitales a CelesTrak.",
        ),
    )

    allowed_message_types = ("tracking", "rx")

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
