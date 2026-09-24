import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
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

    # The rotor this instance drives while it runs. Empty is normal: a plugin can
    # be configured before any board has registered, and one that only produces
    # data never drives anything. SET_NULL because unassigning a rotor is routine
    # and no reason to lose the plugin's own configuration.
    rotor = models.ForeignKey(
        'Rotor',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='plugin_instances',
        help_text='The rotor this instance drives while RUNNING. Only one running instance per rotor (RF-31.1).',
    )

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

    def clean(self):
        super().clean()
        if self.rotor_id and self.status == self.Status.RUNNING:
            # RF-31.1: one plugin has exclusive control of the motors, and
            # assigning the rotor is how the user picks it. Excluding self.pk is
            # a no-op while the instance is unsaved (pk is None and no stored row
            # has a null pk), so the same check covers the add form too.
            already_driven = PluginInstance.objects.filter(
                rotor_id=self.rotor_id, status=self.Status.RUNNING,
            ).exclude(pk=self.pk).exists()
            if already_driven:
                raise ValidationError({
                    'rotor': f'{self.rotor} is already driven by another running plugin instance.',
                })

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

    # Operational pointing limits (RF-30.1). The board keeps its own servo limits
    # as the last line of defence (RF-07.2); these say where the antenna is
    # allowed to look — an obstruction, or a horizon below which tracking is
    # pointless — and the dispatcher cuts a trajectory that leaves them.
    min_elevation_deg = models.FloatField(
        default=10.0,
        validators=[MinValueValidator(-90.0), MaxValueValidator(90.0)],
        help_text='Below this elevation the dispatcher cuts the trajectory and sends HOLD (RF-30.2).',
    )
    min_azimuth_deg = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(360.0)],
        help_text='Start of the allowed azimuth window. Leave both azimuth fields empty for no restriction.',
    )
    max_azimuth_deg = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(360.0)],
        help_text='End of the allowed azimuth window. A value below the start wraps through north, e.g. 300 to 60.',
    )

    class Meta:
        ordering = ['device_id']

    def clean(self):
        super().clean()
        # Half a window says nothing: is 200 a floor or a ceiling?
        if (self.min_azimuth_deg is None) != (self.max_azimuth_deg is None):
            raise ValidationError('Set both azimuth limits, or leave both empty for no azimuth restriction.')

    def __str__(self):
        return self.name or self.device_id

    def azimuth_in_window(self, az_deg):
        """Whether az_deg falls inside the configured azimuth window."""
        if self.min_azimuth_deg is None or self.max_azimuth_deg is None:
            return True
        if self.min_azimuth_deg <= self.max_azimuth_deg:
            return self.min_azimuth_deg <= az_deg <= self.max_azimuth_deg
        # The window wraps through north: 300..60 means 300..360 plus 0..60.
        return az_deg >= self.min_azimuth_deg or az_deg <= self.max_azimuth_deg

    def point_in_bounds(self, az_deg, el_deg):
        """Whether the dispatcher may forward this point to the board (RF-30.2)."""
        return el_deg >= self.min_elevation_deg and self.azimuth_in_window(az_deg)

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

class DispatchOrder(models.Model):
    """One row per message mqtt_dispatch published on device/<device_id>/coordinates/polar.

    Consecutive batches overlap on purpose (coordinates-dto.md §10), so a given
    setpoint shows up in up to three rows. That duplication is the point: this is
    the log of what went on the wire, and the board answers per message —
    RotorState.batch_accepted, batch_error and latency_ms are keyed by t_sent_ms,
    which only a per-message row can be joined against.
    """
    class Kind(models.TextChoices):
        BATCH = 'BATCH', 'Batch'
        HOLD  = 'HOLD',  'Hold'

    class Reason(models.TextChoices):
        END     = 'end',     'Trajectory ended'
        LIMITS  = 'limits',  'Left the rotor limits'
        EXPIRED = 'expired', 'Every point had already expired'

    # PROTECT on both: a plugin or a rotor with history is stopped, not deleted,
    # so the pointing record keeps pointing at rows that exist.
    rotor = models.ForeignKey(Rotor, on_delete=models.PROTECT, related_name='orders')
    plugin = models.ForeignKey(PluginInstance, on_delete=models.PROTECT, related_name='orders')
    kind = models.CharField(max_length=8, choices=Kind.choices)

    # The header of the binary DTO as published (coordinates-dto.md §3.1).
    t0_ms = models.BigIntegerField()
    t_sent_ms = models.BigIntegerField()

    # t0_ms plus the last dt_ms: the instant this message covers. Materialized so
    # that "which order was in effect at T" is a range query rather than a walk
    # through the JSON.
    t_end_ms = models.BigIntegerField()

    # [[dt_ms, az_cdeg, el_cdeg], ...] exactly as encoded, empty for a HOLD. The
    # absolute instant of a setpoint is t0_ms + dt_ms.
    points = models.JSONField(default=list)

    # Why the antenna was told to stop. Empty on a BATCH.
    reason = models.CharField(max_length=16, choices=Reason.choices, blank=True)

    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['rotor', '-created_at']),
        ]

    def __str__(self):
        return f'{self.rotor_id} {self.kind}#{self.pk}'
