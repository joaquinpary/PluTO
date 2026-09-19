import uuid

from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Now

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

class PluginData(models.Model):
    """One row per message a plugin published on plugin/<plugin_uuid>/data/<type>.

    Its only writer is the mqtt_ingest management command, which runs as its
    own container from the server image.
    """
    # PROTECT: a plugin that already produced data is stopped, not deleted,
    # so its history keeps pointing at a real instance.
    plugin = models.ForeignKey(PluginInstance, on_delete=models.PROTECT, related_name='data')
    device = models.TextField(blank=True)
    message_type = models.CharField(max_length=32)

    # How the plugin normalized the payload before publishing it
    payload_format = models.TextField(default='json')
    schema_version = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField(default=dict)

    # Tracing: message_id correlates the plugin log line with this row and lets
    # the ingester drop QoS 1 redeliveries; received_at is when the plugin saw
    # the message and created_at when it was persisted.
    message_id = models.TextField(unique=True, null=True, blank=True)
    source_topic = models.TextField(blank=True)
    ingest_topic = models.TextField(blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['plugin', 'message_type', '-created_at']),
            models.Index(fields=['device', '-created_at']),
        ]

    def __str__(self):
        return f'{self.plugin_id}/{self.message_type}#{self.pk}'

class Rotor(models.Model):
    """An ESP32 driving a pan-tilt, known by the device_id of its MQTT topics.

    mqtt_ingest creates the row the first time a board reports on
    device/<device_id>/status or device/<device_id>/state
    (docs/contracts/device-state.md), so a new board shows up without being
    registered by hand.
    """
    device_id = models.CharField(
        max_length=12,
        unique=True,
        validators=[RegexValidator(r'^[0-9a-f]{12}$', 'Twelve lowercase hex digits: the MAC of the station interface.')],
    )
    name = models.CharField(max_length=100, blank=True)
    online = models.BooleanField(default=False)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    last_state_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['device_id']

    def __str__(self):
        return self.name or self.device_id

class RotorState(models.Model):
    """One state document from device/<device_id>/state (device-state.md §3)."""
    rotor = models.ForeignKey(Rotor, on_delete=models.PROTECT, related_name='states')
    received_at = models.DateTimeField(db_default=Now())

    # The board's own time, kept only when its clock was synced.
    board_time = models.DateTimeField(null=True, blank=True)
    clock_synced = models.BooleanField(default=False)
    mode = models.CharField(max_length=16, blank=True)

    # Commanded position in geographic centidegrees; the servos report nothing back.
    az_cdeg = models.IntegerField(null=True, blank=True)
    el_cdeg = models.IntegerField(null=True, blank=True)
    pan_mode = models.CharField(max_length=16, blank=True)

    # The last batch the board received, as the board reported it.
    batch_accepted = models.BooleanField(null=True, blank=True)
    batch_error = models.CharField(max_length=32, blank=True)
    latency_ms = models.BigIntegerField(null=True, blank=True)
    rejected_total = models.PositiveBigIntegerField(default=0)

    # The whole document, so fields added to the contract later are not lost.
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['rotor', '-received_at']),
        ]

    def __str__(self):
        return f'{self.rotor_id} {self.mode} #{self.pk}'
