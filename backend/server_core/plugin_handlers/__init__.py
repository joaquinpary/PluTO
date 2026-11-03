from .file_tracker import FileTrackerHandler
from .tinygs import TinyGSHandler


PLUGIN_HANDLERS = {
    "file_tracker": FileTrackerHandler(),
    "tinygs": TinyGSHandler(),
}


def get_handler(plugin_type):
    """The handler of a plugin type, or None if PluTO does not know the type."""
    return PLUGIN_HANDLERS.get(plugin_type)
