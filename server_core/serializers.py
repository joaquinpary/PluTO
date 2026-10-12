"""Shapes of the /api/ requests and responses (docs/contracts/ingest-api.md).

The envelope serializers only describe the payload for the OpenAPI schema: the
envelope is deliberately tolerant, and ingest.envelope_fields is what decides
which of its keys reach a row.
"""
from rest_framework import serializers

from .device_state import DEVICE_ID_RE
from .models import PluginInstance, Rotor


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
