from .base import BasePluginHandler
from .fields import config_field


class TinyGSHandler(BasePluginHandler):
    label = "TinyGS"
    # One per topic the plugin relays from the board (plugins/tinygs/mqtt_handler.py).
    allowed_message_types = ("tracking", "rx")

    # Every rule is about a single setting, so validate() has nothing to add.
    # The pass settings reach the container on their own, as upper-cased
    # environment variables.
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


# What the station reports before the TinyGS server assigns it a satellite
# (plugins/tinygs/tracker.py): a placeholder, not something it follows.
_UNASSIGNED_SATELLITE = "Waiting"


def satellite_from_tracking(payload):
    """The satellite a tracking payload names, as {"name", "norad"}, or None.

    The payload is whatever the station sent, so a missing or odd field just
    leaves that part empty instead of failing the caller.
    """
    if not isinstance(payload, dict) or payload.get("satellite") == _UNASSIGNED_SATELLITE:
        return None

    name = payload.get("satellite")
    norad = payload.get("NORAD")
    name = name if isinstance(name, str) and name else None
    # bool is an int in Python, and True is not a catalog number.
    norad = norad if isinstance(norad, int) and not isinstance(norad, bool) and norad > 0 else None

    if name is None and norad is None:
        return None
    return {"name": name, "norad": norad}
