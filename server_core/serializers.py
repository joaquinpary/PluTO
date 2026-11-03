"""Shapes of the /api/ requests and responses (docs/contracts/ingest-api.md).

The envelope serializers only describe the payload for the OpenAPI schema: the
envelope is deliberately tolerant, and ingest.envelope_fields is what decides
which of its keys reach a row.
"""
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .device_state import DEVICE_ID_RE
from .models import DispatchOrder, PluginInstance, Rotor
from .plugin_handlers import PLUGIN_HANDLERS, get_handler
from .plugin_handlers.fields import apply_defaults, config_errors


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


# --- Account -----------------------------------------------------------------

class HealthSerializer(serializers.Serializer):
    status = serializers.CharField(help_text='ok, or degraded when the database does not answer.')
    service = serializers.CharField()
    database = serializers.CharField(help_text='ok or unreachable.')


class SetupStatusSerializer(serializers.Serializer):
    needs_setup = serializers.BooleanField(help_text='True until the first user is created.')


def _password_errors(password, user):
    """What AUTH_PASSWORD_VALIDATORS say about this password, or []."""
    try:
        password_validation.validate_password(password, user=user)
    except DjangoValidationError as exc:
        return list(exc.messages)
    return []


class SetupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    password = serializers.CharField(write_only=True, trim_whitespace=False, style={'input_type': 'password'})

    def validate(self, attrs):
        # Against the user about to exist, so a password that repeats the
        # username is caught too.
        errors = _password_errors(attrs['password'], get_user_model()(username=attrs['username']))
        if errors:
            raise serializers.ValidationError({'password': errors})
        return attrs


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
    """One entry of a handler's config_fields: what the front end builds the form from."""
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
    """config with the defaults of its type filled in, or ValidationError({'config': {field: [...]}}).

    The same check launch makes (fields.config_errors), on the config as it
    came: the rules of each field first, then the handler's validate() for the
    rules that cross fields. The defaults go in only once it passed, so saving
    and launching never disagree about the same config.
    """
    handler = get_handler(plugin_type)
    if handler is None:
        raise serializers.ValidationError({'plugin_type': [f'Unknown plugin type {plugin_type!r}.']})
    errors = config_errors(handler, config)
    if errors:
        raise serializers.ValidationError({'config': errors})
    return apply_defaults(handler.config_fields, config)


def config_warnings(plugin):
    """What saves fine but will not do what the user expects."""
    warnings = []
    plugin_min = (plugin.config or {}).get('min_elevation_deg')
    rotor = plugin.rotor
    is_number = isinstance(plugin_min, (int, float)) and not isinstance(plugin_min, bool)
    if rotor is not None and is_number and plugin_min < rotor.min_elevation_deg:
        # The antenna cuts a trajectory at its first point below the board's
        # limit, so a pass that starts lower is dropped whole.
        warnings.append(
            f'min_elevation_deg ({plugin_min:g}) is below the minimum of the board ({rotor.min_elevation_deg:g}): '
            'every pass that starts below the board minimum is dropped.'
        )
    return warnings


class PluginSerializer(serializers.ModelSerializer):
    plugin_type = serializers.ChoiceField(choices=sorted(PLUGIN_HANDLERS), help_text='Fixed once created: ignored on PATCH.')
    # allow_null only tells the schema the truth: an unbound instance answers null.
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
            # Changing the type of an instance whose container runs would orphan
            # that container, so the type is decided once, at creation.
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
