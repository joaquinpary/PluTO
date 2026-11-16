"""Shapes of /api/; envelope serializers only feed the schema, ingest.envelope_fields decides storage."""
import copy

from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.settings import api_settings

from .device_state import DEVICE_ID_RE, measured_position, tracking_error
from .models import DispatchOrder, PluginData, PluginInstance, Rotor, RotorState
from .payloads import payload_value
from .plugin_handlers import PLUGIN_HANDLERS, get_handler
from .plugin_handlers.fields import apply_defaults, config_errors
from .plugin_handlers.tinygs import satellite_from_tracking


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
    # Several instances per board, only one running (RF-31.1).
    plugins = BoardPluginSerializer(source='plugin_instances', many=True, read_only=True)

    class Meta:
        model = Rotor
        fields = [
            'device_id', 'name', 'online', 'status_changed_at', 'last_state_at',
            'latitude_deg', 'longitude_deg', 'altitude_m',
            'min_elevation_deg', 'min_azimuth_deg', 'max_azimuth_deg', 'plugins',
        ]
        # Reported by the board.
        read_only_fields = ['device_id', 'online', 'status_changed_at', 'last_state_at']

    def validate(self, attrs):
        # Clean the merged rotor so a PATCH of one azimuth end is checked against the stored one.
        rotor = copy.copy(self.instance)
        for name, value in attrs.items():
            setattr(rotor, name, value)
        try:
            rotor.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY if field == NON_FIELD_ERRORS else field: messages
                for field, messages in exc.message_dict.items()
            })
        return attrs


class BindBoardSerializer(serializers.Serializer):
    device_id = serializers.RegexField(
        DEVICE_ID_RE,
        help_text='The MAC of the board: twelve lowercase hex digits.',
        error_messages={'invalid': 'device_id must be twelve lowercase hex digits.'},
    )


class PluginBoardSerializer(serializers.ModelSerializer):
    # allow_null is for the schema: unbound instances answer null.
    board = serializers.SlugRelatedField(source='rotor', slug_field='device_id', read_only=True, allow_null=True)

    class Meta:
        model = PluginInstance
        fields = ['plugin_uuid', 'name', 'status', 'board']


class RotorLimitsSerializer(serializers.ModelSerializer):
    """The board a plugin points and its limits."""

    class Meta:
        model = Rotor
        fields = ['device_id', 'min_elevation_deg', 'min_azimuth_deg', 'max_azimuth_deg']


# Max points per message (coordinates-dto.md §3.1).
MAX_DISPATCH_POINTS = 16


class DispatchPointField(serializers.ListField):
    """[dt_ms, az_cdeg, el_cdeg] within the ranges the board accepts."""

    def __init__(self, **kwargs):
        super().__init__(child=serializers.IntegerField(), min_length=3, max_length=3, **kwargs)

    def to_internal_value(self, data):
        point = super().to_internal_value(data)
        # DRF checks the length after this, too late to unpack.
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
    """A message a plugin published on device/<device_id>/coordinates/polar."""
    kind = serializers.ChoiceField(choices=DispatchOrder.Kind.choices)
    t0_ms = serializers.IntegerField()
    t_sent_ms = serializers.IntegerField(help_text='Taken by the plugin when it published, not when it reports.')
    points = serializers.ListField(child=DispatchPointField(), max_length=MAX_DISPATCH_POINTS, required=False, default=list)
    reason = serializers.ChoiceField(choices=DispatchOrder.Reason.choices, required=False, allow_blank=True, default='')

    def validate(self, attrs):
        # Same rule as the board: HOLD has a reason and no points, BATCH has points.
        if attrs['kind'] == DispatchOrder.Kind.HOLD:
            if attrs['points']:
                raise serializers.ValidationError('A HOLD carries no points.')
            if not attrs['reason']:
                raise serializers.ValidationError('A HOLD needs a reason.')
        elif not attrs['points']:
            raise serializers.ValidationError('A BATCH needs at least one point.')
        return attrs


# --- Account -----------------------------------------------------------------

class HealthSerializer(serializers.Serializer):
    status = serializers.CharField(help_text='ok, or degraded when the database does not answer.')
    service = serializers.CharField()
    database = serializers.CharField(help_text='ok or unreachable.')


class SetupStatusSerializer(serializers.Serializer):
    needs_setup = serializers.BooleanField(help_text='True until the first user is created.')


def _password_errors(password, user):
    """AUTH_PASSWORD_VALIDATORS errors, or []."""
    try:
        password_validation.validate_password(password, user=user)
    except DjangoValidationError as exc:
        return list(exc.messages)
    return []


class SetupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    password = serializers.CharField(write_only=True, trim_whitespace=False, style={'input_type': 'password'})

    def validate(self, attrs):
        # Validate against the new user so a password equal to the username fails.
        errors = _password_errors(attrs['password'], get_user_model()(username=attrs['username']))
        if errors:
            raise serializers.ValidationError({'password': errors})
        return attrs


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False, style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, style={'input_type': 'password'})

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('The current password is not correct.')
        return value

    def validate_new_password(self, value):
        errors = _password_errors(value, self.context['request'].user)
        if errors:
            raise serializers.ValidationError(errors)
        return value


# --- Plugin instances --------------------------------------------------------

class ConfigFieldSerializer(serializers.Serializer):
    """A handler config field, for the front end form."""
    name = serializers.CharField(help_text='The key in config.')
    label = serializers.CharField()
    help = serializers.CharField(default='')
    type = serializers.ChoiceField(choices=['string', 'integer', 'number', 'boolean', 'choice'])
    required = serializers.BooleanField(default=False)
    default = serializers.JSONField(allow_null=True)
    min = serializers.FloatField(allow_null=True, help_text='integer and number only.')
    max = serializers.FloatField(allow_null=True, help_text='integer and number only.')
    choices = serializers.ListField(child=serializers.ListField(), allow_null=True,
                                    help_text='[value, label] pairs; choice only.')
    pattern = serializers.CharField(allow_null=True, help_text='A regular expression the whole value matches; string only.')


class PluginTypeSerializer(serializers.Serializer):
    type = serializers.CharField(help_text='What plugin_type is set to when creating an instance.')
    label = serializers.CharField()
    message_types = serializers.ListField(child=serializers.CharField(),
                                          help_text='What it sends to /api/plugin-data/<type>.')
    config_fields = ConfigFieldSerializer(many=True)


def clean_config(plugin_type, config):
    """Validate config like launch does, then fill in the defaults."""
    handler = get_handler(plugin_type)
    if handler is None:
        raise serializers.ValidationError({'plugin_type': [f'Unknown plugin type {plugin_type!r}.']})
    errors = config_errors(handler, config)
    if errors:
        raise serializers.ValidationError({'config': errors})
    return apply_defaults(handler.config_fields, config)


def config_warnings(plugin):
    """Config that saves but won't do what the user expects."""
    warnings = []
    plugin_min = (plugin.config or {}).get('min_elevation_deg')
    rotor = plugin.rotor
    is_number = isinstance(plugin_min, (int, float)) and not isinstance(plugin_min, bool)
    if rotor is not None and is_number and plugin_min < rotor.min_elevation_deg:
        # The board drops a pass whose first point is below its limit.
        warnings.append(
            f'min_elevation_deg ({plugin_min:g}) is below the minimum of the board ({rotor.min_elevation_deg:g}): '
            'every pass that starts below the board minimum is dropped.'
        )
    if rotor is not None and rotor.location is None:
        warnings.append(
            f'The board {rotor} has no location: tinygs computes no passes, and file_tracker converts '
            'its coordinates from (0, 0, 0). Set it in the board.'
        )
    return warnings


class PluginSerializer(serializers.ModelSerializer):
    plugin_type = serializers.ChoiceField(choices=sorted(PLUGIN_HANDLERS), help_text='Fixed once created: ignored on PATCH.')
    # allow_null is for the schema: unbound instances answer null.
    board = serializers.SlugRelatedField(source='rotor', slug_field='device_id', read_only=True, allow_null=True,
                                         help_text='Set with PUT /api/plugins/<uuid>/board.')
    docker_status = serializers.SerializerMethodField(
        help_text="Docker's state of the container; not_found without one, unknown if Docker did not answer.",
    )
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = PluginInstance
        fields = [
            'plugin_uuid', 'name', 'plugin_type', 'config', 'status', 'docker_status', 'board',
            'created_at', 'updated_at', 'warnings',
        ]
        read_only_fields = ['status']

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            # Changing the type would orphan a running container.
            fields['plugin_type'].read_only = True
        return fields

    def validate(self, attrs):
        if self.instance is None or 'config' in attrs:
            plugin_type = attrs['plugin_type'] if self.instance is None else self.instance.plugin_type
            attrs['config'] = clean_config(plugin_type, attrs.get('config', {}))
        return attrs

    def get_docker_status(self, plugin) -> str:
        return self.context.get('docker_statuses', {}).get(plugin.plugin_uuid, 'unknown')

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_warnings(self, plugin):
        return config_warnings(plugin)


# --- Plugin actions and logs ---------------------------------------------------

DEFAULT_LOG_LINES = 100
MAX_LOG_LINES = 1000


class CoordinatesFileSerializer(serializers.Serializer):
    file = serializers.FileField(help_text='The coordinates file: UTF-8 text, up to 1 MiB.')


class LogsQuerySerializer(serializers.Serializer):
    tail = serializers.IntegerField(min_value=1, max_value=MAX_LOG_LINES, default=DEFAULT_LOG_LINES,
                                    help_text=f'How many of the last lines, 1 to {MAX_LOG_LINES}.')


class LogsSerializer(serializers.Serializer):
    source = serializers.CharField(help_text='The plugin instance or the service the lines come from.')
    lines = serializers.ListField(child=serializers.CharField(allow_blank=True))


# --- Boards, live --------------------------------------------------------------

class MeasSerializer(serializers.Serializer):
    az_cdeg = serializers.IntegerField()
    el_cdeg = serializers.IntegerField()


class LiveStateSerializer(serializers.ModelSerializer):
    meas = serializers.SerializerMethodField(help_text='Measured by the encoders; null without them.')
    err_cdeg = serializers.SerializerMethodField(help_text='Tracking error the board measured; null without encoders.')

    class Meta:
        model = RotorState
        fields = [
            'received_at', 'mode', 'az_cdeg', 'el_cdeg', 'pan_mode', 'batch_accepted', 'batch_error',
            'clock_synced', 'rejected_total', 'meas', 'err_cdeg',
        ]
        read_only_fields = fields

    @extend_schema_field(MeasSerializer(allow_null=True))
    def get_meas(self, state):
        return measured_position(state.payload)

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_err_cdeg(self, state):
        return tracking_error(state.payload)


class RunningPluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = PluginInstance
        fields = ['plugin_uuid', 'name', 'plugin_type']
        read_only_fields = fields


class SatelliteSerializer(serializers.Serializer):
    name = serializers.CharField(allow_null=True)
    norad = serializers.IntegerField(allow_null=True)


class BoardLiveSerializer(serializers.ModelSerializer):
    """A board as the home page polls it; BoardsLiveView sets the extra attributes."""
    state = LiveStateSerializer(source='live_state', allow_null=True, read_only=True)
    running_plugin = RunningPluginSerializer(allow_null=True, read_only=True)
    satellite = SatelliteSerializer(allow_null=True, read_only=True)
    last_hold_reason = serializers.ChoiceField(choices=DispatchOrder.Reason.choices, allow_null=True, read_only=True)

    class Meta:
        model = Rotor
        fields = [
            'device_id', 'name', 'online', 'status_changed_at', 'last_state_at',
            'state', 'running_plugin', 'satellite', 'last_hold_reason',
        ]
        read_only_fields = fields


class TrackPointSerializer(serializers.Serializer):
    t_ms = serializers.IntegerField(help_text='When the antenna should be there: epoch milliseconds, UTC.')
    az_cdeg = serializers.IntegerField()
    el_cdeg = serializers.IntegerField()


class TrackSerializer(serializers.Serializer):
    device_id = serializers.CharField()
    points = TrackPointSerializer(many=True)


# --- History (GET /api/boards/<id>/states, /api/orders, /api/plugin-data) ---

class RangeQuerySerializer(serializers.Serializer):
    """`from`/`to` of a history query, ISO 8601; set in get_fields since `from` is a keyword."""
    range_required = False

    def get_fields(self):
        fields = super().get_fields()
        fields['from'] = serializers.DateTimeField(required=self.range_required, help_text='Inclusive, ISO 8601.')
        fields['to'] = serializers.DateTimeField(required=self.range_required, help_text='Exclusive, ISO 8601.')
        return fields

    def validate(self, attrs):
        if 'from' in attrs and 'to' in attrs and attrs['from'] >= attrs['to']:
            raise serializers.ValidationError({'to': 'Must be later than from.'})
        return attrs


class SeriesQuerySerializer(RangeQuerySerializer):
    range_required = True
    max_points = serializers.IntegerField(min_value=1, max_value=10000, default=2000)


class StateRowSerializer(serializers.ModelSerializer):
    err_cdeg = serializers.SerializerMethodField()

    class Meta:
        model = RotorState
        fields = ['received_at', 'mode', 'az_cdeg', 'el_cdeg', 'pan_mode', 'batch_accepted',
                  'batch_error', 'latency_ms', 'clock_synced', 'err_cdeg']

    def get_err_cdeg(self, state) -> int | None:
        # Only boards with encoders send it.
        return tracking_error(state.payload)


class SeriesPointSerializer(serializers.Serializer):
    t = serializers.DateTimeField()
    az_cdeg = serializers.IntegerField(allow_null=True)
    el_cdeg = serializers.IntegerField(allow_null=True)


class SeriesSerializer(serializers.Serializer):
    points = SeriesPointSerializer(many=True)


class OrdersQuerySerializer(RangeQuerySerializer):
    board = serializers.RegexField(DEVICE_ID_RE, required=False, help_text='device_id of the board.')
    kind = serializers.ChoiceField(DispatchOrder.Kind.choices, required=False)
    reason = serializers.ChoiceField(DispatchOrder.Reason.choices, required=False)


class PluginDataQuerySerializer(RangeQuerySerializer):
    plugin = serializers.UUIDField(required=False, help_text='plugin_uuid of the instance.')
    type = serializers.CharField(required=False, max_length=32, help_text='message_type, e.g. rx or tracking.')


class OrderRowSerializer(serializers.ModelSerializer):
    board = serializers.SlugRelatedField(source='rotor', slug_field='device_id', read_only=True)
    plugin = serializers.SlugRelatedField(slug_field='plugin_uuid', read_only=True)
    point_count = serializers.SerializerMethodField()

    class Meta:
        model = DispatchOrder
        fields = ['id', 'board', 'plugin', 'kind', 'reason', 't0_ms', 't_end_ms', 't_sent_ms',
                  'point_count', 'created_at']

    def get_point_count(self, order) -> int:
        return len(order.points)


class PluginDataRowSerializer(serializers.ModelSerializer):
    """A stored message, with the tinyGS fork's rx/tracking fields pulled out of the payload."""
    plugin = serializers.SlugRelatedField(slug_field='plugin_uuid', read_only=True)
    rssi = serializers.SerializerMethodField()
    snr = serializers.SerializerMethodField()
    crc_error = serializers.SerializerMethodField()
    satellite = serializers.SerializerMethodField()

    class Meta:
        model = PluginData
        fields = ['id', 'plugin', 'message_type', 'device', 'received_at', 'created_at',
                  'rssi', 'snr', 'crc_error', 'satellite', 'payload']

    def get_rssi(self, row) -> float | None:
        return payload_value(row.payload, 'rssi', (int, float))

    def get_snr(self, row) -> float | None:
        return payload_value(row.payload, 'snr', (int, float))

    def get_crc_error(self, row) -> bool | None:
        return payload_value(row.payload, 'crc_error', bool)

    @extend_schema_field(SatelliteSerializer(allow_null=True))
    def get_satellite(self, row):
        return satellite_from_tracking(row.payload)


# --- Results (GET /api/results/...) ---

class PointingErrorQuerySerializer(RangeQuerySerializer):
    range_required = True
    board = serializers.RegexField(DEVICE_ID_RE, help_text='device_id of the board.')


class ReceptionQuerySerializer(RangeQuerySerializer):
    range_required = True
    plugin = serializers.UUIDField(help_text='plugin_uuid of the instance.')


class PassErrorSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    source = serializers.ChoiceField(['meas', 'commanded'])
    samples = serializers.IntegerField()
    mean_err_cdeg = serializers.FloatField(allow_null=True)
    max_err_cdeg = serializers.IntegerField(allow_null=True)


class PointingErrorSerializer(serializers.Serializer):
    passes = PassErrorSerializer(many=True)


class ReceptionDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    packets = serializers.IntegerField()
    crc_errors = serializers.IntegerField()
    rssi_mean = serializers.FloatField(allow_null=True)
    snr_mean = serializers.FloatField(allow_null=True)


class ReceptionSerializer(serializers.Serializer):
    days = ReceptionDaySerializer(many=True)
