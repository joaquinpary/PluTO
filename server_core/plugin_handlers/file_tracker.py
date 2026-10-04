import json
import uuid

from .base import BasePluginHandler


_VALID_COORD_COMBINATIONS = {
    ("ECEF", "CARTESIAN"), ("ECEF", "GEO"),
    ("ECI", "CARTESIAN"),
    ("ENU", "POLAR"), ("ENU", "CARTESIAN"),
}

# A coordinates file is a few thousand lines of text at most. The cap keeps a
# wrong upload (a video, a dump) from becoming a retained message the broker
# hands to the plugin on every subscription.
MAX_FILE_BYTES = 1024 * 1024


def input_topic(plugin_uuid):
    return f"plugin/{plugin_uuid}/input/file"


def build_file_message(config, filename, content):
    """The retained message that hands a coordinates file to the plugin.

    It carries coord_type and coord_format so the plugin does not depend on
    the environment it was launched with: changing them in the admin applies
    to the next upload without restarting the container. upload_id lets the
    plugin tell a new file from the broker re-delivering the retained one
    after a reconnection.
    """
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"The file is larger than {MAX_FILE_BYTES // 1024} KB.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("The file is not UTF-8 text.") from None

    return json.dumps({
        "upload_id": str(uuid.uuid4()),
        "filename": filename,
        "coord_type": str(config["coord_type"]).upper(),
        "coord_format": str(config["coord_format"]).upper(),
        "content": text,
    })


class FileTrackerHandler(BasePluginHandler):
    def validate(self, config):
        coord_type = config.get("coord_type")
        coord_format = config.get("coord_format")

        if not coord_type:
            return "Error: coord_type is required for file_tracker."
        if not coord_format:
            return "Error: coord_format is required for file_tracker."

        combo = (str(coord_type).upper(), str(coord_format).upper())
        if combo not in _VALID_COORD_COMBINATIONS:
            valid = ", ".join(f"{coord_type}+{coord_format}" for coord_type, coord_format in sorted(_VALID_COORD_COMBINATIONS))
            return f"Error: Invalid combination {coord_type}+{coord_format}. Valid: {valid}"

        return None

    def get_environment(self, config):
        environment = super().get_environment(config)
        plugin_id = config.get("plugin_id")
        if plugin_id is not None:
            environment["MQTT_PUBLISH_TOPIC"] = f"plugin/{plugin_id}/coordinates/raw"
            environment["MQTT_INPUT_TOPIC"] = input_topic(plugin_id)
        return environment
