"""The REST API under /api/ (docs/contracts/ingest-api.md).

Two kinds of caller, and every view accepts exactly one of them:

- Plugin containers send their data and their board's reports with
  `Authorization: Plugin <token>` (authentication.py). The token decides the
  instance, and the instance decides the board, so no URL carries a plugin or
  device id a plugin could use to speak for someone else.
- The person using PluTO, through the front end, with `Authorization: Bearer
  <jwt>` from /api/auth/token. That is the project-wide default (settings.py),
  so the front-end views declare nothing.
"""
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import IsPluginInstance, PluginTokenAuthentication
from .board_scan import BrokerUnavailable, scan_boards
from .device_state import store_state, store_status
from .dispatch import record_order
from .ingest import DUPLICATE, MESSAGE_TYPE_RE, envelope_fields, store_document
from .models import PluginInstance, Rotor
from .plugin_handlers import PLUGIN_HANDLERS
from .serializers import (
    BatchResultSerializer,
    DispatchOrderSerializer,
    RotorLimitsSerializer,
    BindBoardSerializer,
    BoardSerializer,
    DeviceReportResultSerializer,
    EnvelopeSerializer,
    IngestResultSerializer,
    PluginBoardSerializer,
)

logger = logging.getLogger(__name__)

# The tinygs plugin caps the board's raw payload at 64 KiB, but base64 grows a
# binary one by a third before it is wrapped, so the envelope gets more room.
MAX_ENVELOPE_BYTES = 128 * 1024
MAX_BATCH = 100


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'conflict'


class ServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = 'service_unavailable'


class PayloadTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = 'payload_too_large'
    default_detail = 'Request body too large.'


def _reject_oversized_body(request):
    # Django refuses to read a body above DATA_UPLOAD_MAX_MEMORY_SIZE and calls
    # it a bad request; checking the declared length first makes it a 413.
    try:
        length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        return
    if length > settings.DATA_UPLOAD_MAX_MEMORY_SIZE:
        raise PayloadTooLarge()


class PluginView(APIView):
    """Base for the endpoints a plugin container calls. request.auth is its PluginInstance."""
    authentication_classes = [PluginTokenAuthentication]
    permission_classes = [IsPluginInstance]


# --- Plugins -----------------------------------------------------------------

def _ingest_one(plugin, handler, message_type, envelope, ingest_topic):
    """Store one envelope. Returns (http_status, result) for that envelope alone."""
    message_id = envelope.get('message_id') if isinstance(envelope, dict) else None
    result = {'message_id': message_id}

    if not isinstance(envelope, dict):
        return 400, {**result, 'result': 'rejected', 'error': 'An envelope must be a JSON object.'}
    if len(json.dumps(envelope)) > MAX_ENVELOPE_BYTES:
        return 413, {**result, 'result': 'rejected', 'error': f'Envelopes are limited to {MAX_ENVELOPE_BYTES} bytes.'}

    fields = envelope_fields(plugin.plugin_uuid, message_type, envelope, ingest_topic=ingest_topic)
    error = handler.validate_data(message_type, fields['payload']) if handler else None
    if error:
        return 400, {**result, 'result': 'rejected', 'error': error}

    if store_document(plugin, fields) == DUPLICATE:
        return 200, {**result, 'result': 'duplicate'}
    return 201, {**result, 'result': 'ingested'}


class PluginDataView(PluginView):
    parser_classes = [JSONParser]

    @extend_schema(
        summary='Store data a plugin produced',
        description='One envelope, or a list of 1 to 100. A list is answered per envelope, always with 200.',
        request=EnvelopeSerializer,
        responses={
            201: IngestResultSerializer,
            200: OpenApiResponse(BatchResultSerializer, description='A batch, or a duplicate single envelope.'),
            400: OpenApiResponse(description='Malformed message_type, JSON or envelope, or rejected by the plugin type.'),
            403: OpenApiResponse(description='This plugin type does not send that message_type.'),
            413: OpenApiResponse(description='Envelope above 128 KiB or body above 2.5 MB.'),
        },
    )
    def post(self, request, message_type):
        plugin = request.auth

        if not MESSAGE_TYPE_RE.match(message_type):
            return Response({'detail': 'message_type must match [a-z0-9_-]{1,32}.'}, status=400)

        handler = PLUGIN_HANDLERS.get(plugin.plugin_type)
        allowed = handler.allowed_message_types if handler else None
        if allowed is not None and message_type not in allowed:
            raise PermissionDenied(f'A {plugin.plugin_type} plugin does not send {message_type} data.')

        _reject_oversized_body(request)
        document = request.data

        if isinstance(document, list):
            if not 1 <= len(document) <= MAX_BATCH:
                return Response({'detail': f'A batch carries between 1 and {MAX_BATCH} envelopes.'}, status=400)
            # Answered per envelope, so a client retries only the ones that failed.
            results = [_ingest_one(plugin, handler, message_type, item, request.path)[1] for item in document]
            return Response({'results': results})

        code, result = _ingest_one(plugin, handler, message_type, document, request.path)
        return Response(result, status=code)


class DeviceReportView(PluginView):
    """A report of the board bound to the calling instance, forwarded as the board published it.

    The body is read raw on purpose, not through DRF's parsers: status is the
    plain text the board sends, and both must reach device_state.py untouched.
    """
    leaf = None
    store = None

    def post(self, request):
        rotor = request.auth.rotor
        if rotor is None:
            raise PermissionDenied('This plugin instance has no board bound to it.')

        _reject_oversized_body(request)
        if not self.store(rotor.device_id, request.body):
            return Response({'detail': f'Not a valid {self.leaf} payload (docs/contracts/device-state.md).'}, status=400)
        return Response({'device_id': rotor.device_id}, status=201)


@extend_schema(
    summary="Forward the bound board's status",
    request={'text/plain': OpenApiTypes.STR},
    responses={201: DeviceReportResultSerializer, 400: None, 403: None},
)
class DeviceStatusView(DeviceReportView):
    leaf = 'status'
    store = staticmethod(store_status)

    # Repeated only so the schema decorator has a method to describe.
    def post(self, request):
        return super().post(request)


@extend_schema(
    summary="Forward the bound board's state document",
    request={'application/json': OpenApiTypes.OBJECT},
    responses={201: DeviceReportResultSerializer, 400: None, 403: None},
)
class DeviceStateView(DeviceReportView):
    leaf = 'state'
    store = staticmethod(store_state)

    def post(self, request):
        return super().post(request)


class PluginRotorView(PluginView):
    @extend_schema(
        summary='The board bound to the calling instance and its pointing limits',
        description=(
            'null when no board is bound. A plugin asks before planning each trajectory, '
            'so a change of limits applies from the next one.'
        ),
        responses={200: RotorLimitsSerializer},
    )
    def get(self, request):
        rotor = request.auth.rotor
        if rotor is None:
            # DRF renders a None body as empty; the contract says a JSON null.
            return JsonResponse(None, safe=False)
        return Response(RotorLimitsSerializer(rotor).data)


class DispatchOrdersView(PluginView):
    parser_classes = [JSONParser]

    @extend_schema(
        summary='Record what the plugin sent to its board',
        description=(
            'One order or a list of up to 100. Each becomes a DispatchOrder of the board '
            'bound to the instance, the record the pointing error is measured against.'
        ),
        request=DispatchOrderSerializer(many=True),
        responses={
            201: OpenApiResponse(description='{"stored": n}'),
            400: OpenApiResponse(description='An order that is not a valid BATCH or HOLD.'),
            403: OpenApiResponse(description='The instance has no board bound to it.'),
        },
    )
    def post(self, request):
        plugin = request.auth
        rotor = plugin.rotor
        if rotor is None:
            raise PermissionDenied('This plugin instance has no board bound to it.')

        _reject_oversized_body(request)
        many = isinstance(request.data, list)
        if many and not 1 <= len(request.data) <= MAX_BATCH:
            return Response({'detail': f'A batch carries between 1 and {MAX_BATCH} orders.'}, status=400)

        # All or nothing: a half-stored list would leave a gap the plugin
        # cannot tell from the response which orders to resend for.
        serializer = DispatchOrderSerializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        orders = serializer.validated_data if many else [serializer.validated_data]

        with transaction.atomic():
            for order in orders:
                record_order(
                    rotor, plugin, order['kind'], order['t0_ms'], order['t_sent_ms'],
                    order['points'], order['reason'],
                )
        return Response({'stored': len(orders)}, status=201)


# --- Front end ---------------------------------------------------------------

def _boards_response():
    return Response(BoardSerializer(Rotor.objects.prefetch_related('plugin_instances'), many=True).data)


class BoardsView(APIView):
    @extend_schema(summary='List the registered boards', description='Does not touch the broker.',
                   responses=BoardSerializer(many=True))
    def get(self, request):
        return _boards_response()


class BoardScanView(APIView):
    @extend_schema(
        summary='Ask the broker which boards exist',
        description='Registers the new ones, refreshes `online` on the known ones, and lists them all.',
        request=None,
        responses={200: BoardSerializer(many=True), 503: OpenApiResponse(description='The broker did not answer.')},
    )
    def post(self, request):
        try:
            found = scan_boards()
        except BrokerUnavailable as exc:
            logger.warning('Board scan failed: %s', exc)
            raise ServiceUnavailable('Could not reach the broker.')

        for device_id, payload in found.items():
            # The same path a live status report takes: registers the board and
            # moves status_changed_at only on a real change.
            store_status(device_id, payload)

        return _boards_response()


class PluginBoardView(APIView):
    def _plugin(self, plugin_uuid):
        plugin = PluginInstance.objects.select_related('rotor').filter(plugin_uuid=plugin_uuid).first()
        if plugin is None:
            raise NotFound('No plugin instance with that uuid.')
        if plugin.status == PluginInstance.Status.RUNNING:
            # The board reaches the container as ROTOR_DEVICE_ID when it is
            # launched, so a change would not take effect until the next launch.
            raise Conflict('Stop the plugin before changing its board.')
        return plugin

    @extend_schema(
        summary='Bind a board to a plugin instance',
        request=BindBoardSerializer,
        responses={
            200: PluginBoardSerializer,
            404: OpenApiResponse(description='Unknown plugin, or a board not registered yet (scan first).'),
            409: OpenApiResponse(description='The plugin is running, or another running instance drives the board.'),
        },
    )
    def put(self, request, plugin_uuid):
        plugin = self._plugin(plugin_uuid)
        serializer = BindBoardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rotor = Rotor.objects.filter(device_id=serializer.validated_data['device_id']).first()
        if rotor is None:
            raise NotFound('Unknown board. Scan for boards first.')

        driven = PluginInstance.objects.filter(rotor=rotor, status=PluginInstance.Status.RUNNING)
        if driven.exclude(pk=plugin.pk).exists():
            raise Conflict('Another running plugin instance already drives that board (RF-31.1).')

        plugin.rotor = rotor
        plugin.save(update_fields=['rotor', 'updated_at'])
        return Response(PluginBoardSerializer(plugin).data)

    @extend_schema(summary='Unbind the board of a plugin instance', request=None,
                   responses={200: PluginBoardSerializer})
    def delete(self, request, plugin_uuid):
        plugin = self._plugin(plugin_uuid)
        plugin.rotor = None
        plugin.save(update_fields=['rotor', 'updated_at'])
        return Response(PluginBoardSerializer(plugin).data)
