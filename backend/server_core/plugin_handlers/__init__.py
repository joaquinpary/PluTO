from .file_tracker import FileTrackerHandler
from .tinygs import TinyGSHandler


PLUGIN_HANDLERS = {
    "file_tracker": FileTrackerHandler(),
    "tinygs": TinyGSHandler(),
}


def get_handler(plugin_type):
    """Handler for a plugin type, or None."""
    return PLUGIN_HANDLERS.get(plugin_type)
