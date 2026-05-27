import os

from .base import BasePluginHandler


_VALID_COORD_COMBINATIONS = {
    ("ECEF", "CARTESIAN"), ("ECEF", "GEO"),
    ("ECI", "CARTESIAN"),
    ("ENU", "POLAR"), ("ENU", "CARTESIAN"),
}


class FileTrackerHandler(BasePluginHandler):
    def validate(self, config):
        file_path = config.get("file_path")
        coord_type = config.get("coord_type")
        coord_format = config.get("coord_format")

        if not file_path:
            return "Error: file_path is required for file_tracker."
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
        file_name = os.path.basename(os.path.abspath(config["file_path"]))
        environment["FILE_PATH"] = f"/data/{file_name}"
        environment["COORD_TYPE"] = str(config["coord_type"]).upper()
        environment["COORD_FORMAT"] = str(config["coord_format"]).upper()
        return environment

    def get_volumes(self, config):
        host_dir = os.path.dirname(os.path.abspath(config["file_path"]))
        return {host_dir: {"bind": "/data", "mode": "ro"}}