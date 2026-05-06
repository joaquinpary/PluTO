import mongoengine
from datetime import datetime

class GenericJSONDocument(mongoengine.DynamicDocument):
    """
    A generic dynamic document designed to store arbitrary JSON data.
    Because data is formatted as JSONs, DynamicDocument allows you to attach
    any fields dynamically, or you can use the 'payload' DictField to store the entire JSON.
    """
    meta = {'abstract': True}
    
    # Optional metadata that might be useful for all JSONs
    created_at = mongoengine.DateTimeField(default=datetime.utcnow)
    
    # Store the complete raw JSON data here, or attach attributes dynamically to the document
    payload = mongoengine.DictField()

class SystemSettings(GenericJSONDocument):
    """Collection for system settings data"""
    # contains the system configuration data for the whole system
    # shall include the active plugins, base system settings (e.g. timezone),
    # registered esp32's, etc
    pass

class Devices(GenericJSONDocument):
    """Collection for devices data"""
    # contains the geographical data corresponding to each esp32
    # shall state the locations (lat, lon)
    # shall state the name of the device
    # shall state the id of the device
    # shall contain the mqtt topics for each device
    pass

class CoordinatesSent(GenericJSONDocument):
    """Collection for telemetry data"""
    # contains a history of coordinates sent to each esp32
    # each element should have az and el values
    pass

class PluginData(GenericJSONDocument):
    """Collection for plugin data"""
    # contains data from all plugins organized through a plugin_id field
    # could also use a "collection" field for each plugin
    pass
