from .base import BasePluginHandler
from .fields import config_field


class TinyGSHandler(BasePluginHandler):
    label = "TinyGS"
    # One per topic the plugin relays.
    allowed_message_types = ("tracking", "rx")

    # Pass settings reach the container as upper-cased env vars.
    config_fields = (
        # Part of the subscribed topics; a space or accent is legal there but never matches the board.
        config_field(
            "tinygs_device", "Dispositivo TinyGS", "string", required=True, pattern=r"[A-Za-z0-9_-]+",
            help="El nombre de la estación en sus tópicos MQTT: letras, dígitos, _ y -.",
        ),
        config_field(
            "tinygs_topic_prefix", "Prefijo de los tópicos", "string", pattern=r"[^/+#\s]+",
            help='El prefijo MQTT configurado en la estación, sin / + # ni espacios. Vacío usa "pluto".',
        ),
        # Below the board's min the board drops the whole pass.
        config_field(
            "min_elevation_deg", "Elevación mínima (°)", "number", min=-90, max=90, default=10,
            help="Solo se publica el tramo de la pasada por encima de esta elevación. No la pongas por debajo de la de la placa.",
        ),
        # Mins below stand in for "greater than 0" in the form.
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


# Placeholder the station sends before TinyGS assigns a satellite.
_UNASSIGNED_SATELLITE = "Waiting"


def satellite_from_tracking(payload):
    """{"name", "norad"} from a tracking payload, or None; odd fields are left empty."""
    if not isinstance(payload, dict) or payload.get("satellite") == _UNASSIGNED_SATELLITE:
        return None

    name = payload.get("satellite")
    norad = payload.get("NORAD")
    name = name if isinstance(name, str) and name else None
    # bool is an int in Python.
    norad = norad if isinstance(norad, int) and not isinstance(norad, bool) and norad > 0 else None

    if name is None and norad is None:
        return None
    return {"name": name, "norad": norad}
