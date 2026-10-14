"""Shapes of the /api/ requests and responses (docs/contracts/ingest-api.md).

The envelope serializers only describe the payload for the OpenAPI schema: the
envelope is deliberately tolerant, and ingest.envelope_fields is what decides
which of its keys reach a row.
"""
from rest_framework import serializers

from .device_state import DEVICE_ID_RE
from .models import DispatchOrder, PluginInstance, Rotor


class EnvelopeSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(required=False)
    message_id = serializers.CharField(required=False, help_text='Unique; a repeated one is a duplicate, so retries are safe.')
    plugin_id = serializers.CharField(required=False, help_text='Ignored: the token decides the instance.')
    device = serializers.CharField(required=False)
    source_topic = serializers.CharField(required=False)
    received_at = serializers.DateTimeField(required=False)
    payload_format = serializers.CharField(required=False)
    payload = serializers.JSONField(required=False, help_text='A JSON object; anything else is stored as {"value": ...}.')


class IngestResultSerializer(serializers.Serializer):
    message_id = serializers.CharField(allow_null=True)
    result = serializers.ChoiceField(choices=['ingested', 'duplicate', 'rejected'])
    error = serializers.CharField(required=False)


class BatchResultSerializer(serializers.Serializer):
    results = IngestResultSerializer(many=True)


class DeviceReportResultSerializer(serializers.Serializer):
    device_id = serializers.CharField()


class BoardPluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = PluginInstance
        fields = ['plugin_uuid', 'name', 'status']


class BoardSerializer(serializers.ModelSerializer):
    # Several instances may be bound to one board; only one runs at a time (RF-31.1).
    plugins = BoardPluginSerializer(source='plugin_instances', many=True, read_only=True)

    class Meta:
        model = Rotor
        fields = ['device_id', 'name', 'online', 'status_changed_at', 'last_state_at', 'plugins']


class BindBoardSerializer(serializers.Serializer):
    device_id = serializers.RegexField(
        DEVICE_ID_RE,
        help_text='The MAC of the board: twelve lowercase hex digits.',
        error_messages={'invalid': 'device_id must be twelve lowercase hex digits.'},
    )


class PluginBoardSerializer(serializers.ModelSerializer):
    board = serializers.SlugRelatedField(source='rotor', slug_field='device_id', read_only=True)

    class Meta:
        model = PluginInstance
        fields = ['plugin_uuid', 'name', 'status', 'board']


class RotorLimitsSerializer(serializers.ModelSerializer):
    """What a plugin needs to point its board: which board, and where it may look."""

    class Meta:
        model = Rotor
        fields = ['device_id', 'min_elevation_deg', 'min_azimuth_deg', 'max_azimuth_deg']


# The most points one message may carry (coordinates-dto.md §3.1, count).
MAX_DISPATCH_POINTS = 16


class DispatchPointField(serializers.ListField):
    """[dt_ms, az_cdeg, el_cdeg], with the ranges the board accepts (coordinates-dto.md §3.2)."""

    def __init__(self, **kwargs):
        super().__init__(child=serializers.IntegerField(), min_length=3, max_length=3, **kwargs)

    def to_internal_value(self, data):
        point = super().to_internal_value(data)
        # DRF checks min/max_length after this method, too late to unpack safely.
        if len(point) != 3:
            raise serializers.ValidationError('A point is [dt_ms, az_cdeg, el_cdeg].')
        dt_ms, az_cdeg, el_cdeg = point
        if not 0 <= dt_ms <= 0xFFFFFFFF:
            raise serializers.ValidationError('dt_ms must fit in 32 unsigned bits.')
        if not 0 <= az_cdeg <= 35999:
            raise serializers.ValidationError('az_cdeg must be between 0 and 35999.')
        if not -9000 <= el_cdeg <= 9000:
            raise serializers.ValidationError('el_cdeg must be between -9000 and 9000.')
        return [dt_ms, az_cdeg, el_cdeg]


class DispatchOrderSerializer(serializers.Serializer):
    """One message a plugin published on device/<device_id>/coordinates/polar."""
    kind = serializers.ChoiceField(choices=DispatchOrder.Kind.choices)
    t0_ms = serializers.IntegerField()
    t_sent_ms = serializers.IntegerField(help_text='Taken by the plugin when it published, not when it reports.')
    points = serializers.ListField(child=DispatchPointField(), max_length=MAX_DISPATCH_POINTS, required=False, default=list)
    reason = serializers.ChoiceField(choices=DispatchOrder.Reason.choices, required=False, allow_blank=True, default='')

    def validate(self, attrs):
        # The same shape the board enforces (§6.6): a HOLD carries no points
        # and says why; a batch carries points.
        if attrs['kind'] == DispatchOrder.Kind.HOLD:
            if attrs['points']:
                raise serializers.ValidationError('A HOLD carries no points.')
            if not attrs['reason']:
                raise serializers.ValidationError('A HOLD needs a reason.')
        elif not attrs['points']:
            raise serializers.ValidationError('A BATCH needs at least one point.')
        return attrs
