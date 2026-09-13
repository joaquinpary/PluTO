import uuid
import mongoengine
from datetime import datetime

from django.db import models

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
    """Collection for plugin data (one document per ingested MQTT message)"""
    # contains data from all plugins organized through a plugin_id field
    # could also use a "collection" field for each plugin

    # Where the message came from
    plugin_id    = mongoengine.StringField(required=True)
    plugin_type  = mongoengine.StringField()
    device       = mongoengine.StringField()
    message_type = mongoengine.StringField(required=True)

    # How the payload was normalized by the plugin before publishing
    payload_format = mongoengine.StringField(default='json')
    schema_version = mongoengine.IntField(default=1)

    # Tracing: message_id correlates the plugin log line with this document,
    # received_at is when the plugin saw it and created_at when it was persisted
    message_id   = mongoengine.StringField()
    source_topic = mongoengine.StringField()
    ingest_topic = mongoengine.StringField()
    received_at  = mongoengine.DateTimeField()

    meta = {
        'indexes': [
            ('plugin_id', 'message_type', '-created_at'),
            ('device', '-created_at'),
        ],
        'ordering': ['-created_at'],
    }

class PluginInstance(models.Model):
    class Status(models.TextChoices):
        STOPPED = 'STOPPED', 'Stopped'
        RUNNING = 'RUNNING', 'Running'
        ERROR   = 'ERROR',   'Error'

    name        = models.CharField(max_length=100, unique=True)
    plugin_type = models.CharField(max_length=50)
    plugin_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    status      = models.CharField(max_length=20, choices=Status.choices, default=Status.STOPPED)
    container_id = models.CharField(max_length=128, blank=True)

    # Ground station position — common to every plugin
    station_lat = models.FloatField(default=0.0)
    station_lon = models.FloatField(default=0.0)
    station_alt = models.FloatField(default=0.0)

    # Plugin-specific parameters — arbitrary key/value pairs forwarded to the orchestrator
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Plugin-specific parameters as JSON (e.g. {"file_path": "/data/coords.txt", "coord_type": "ECEF", "coord_format": "GEO"}).',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def station_coordinates(self):
        return {
            'lat': self.station_lat,
            'lon': self.station_lon,
            'alt': self.station_alt,
        }
