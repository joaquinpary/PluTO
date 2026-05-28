from .file_tracker import FileTrackerHandler
from .tinygs import TinyGSHandler


PLUGIN_HANDLERS = {
    "file_tracker": FileTrackerHandler(),
    "tinygs": TinyGSHandler(),
}