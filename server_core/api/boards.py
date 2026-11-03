"""The boards for the front end: the list and the scan, their settings, what they are doing now and the pass in course."""
import logging

from django.db.models import OuterRef, Prefetch, Subquery
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from ..board_scan import BrokerUnavailable, scan_boards
from ..device_state import store_status
from ..models import DispatchOrder, PluginData, PluginInstance, Rotor, RotorState
from ..plugin_handlers.tinygs import satellite_from_tracking
from ..serializers import BoardLiveSerializer, BoardSerializer, TrackSerializer
from .exceptions import ServiceUnavailable

logger = logging.getLogger(__name__)

UNKNOWN_BOARD = OpenApiResponse(description='No board with that device_id.')


def get_board(device_id):
    rotor = Rotor.objects.prefetch_related('plugin_instances').filter(device_id=device_id).first()
    if rotor is None:
        raise NotFound('No board with that device_id.')
    return rotor


class BoardDetailView(APIView):
    @extend_schema(summary='Show a board', responses={200: BoardSerializer, 404: UNKNOWN_BOARD})
    def get(self, request, device_id):
        return Response(BoardSerializer(get_board(device_id)).data)

    @extend_schema(
        summary='Edit the name, the location and the pointing limits of a board',
        description='Both azimuth limits or neither; a start above the end wraps through north, e.g. 300 to 60.',
        request=BoardSerializer,
        responses={
            200: BoardSerializer,
            400: OpenApiResponse(description='Out of range, or half an azimuth window (under non_field_errors).'),
            404: UNKNOWN_BOARD,
        },
    )
    def patch(self, request, device_id):
        serializer = BoardSerializer(get_board(device_id), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


def _satellite(plugin):
    """What a running instance follows, from its latest tracking message (only tinygs sends them)."""
    if plugin is None:
        return None
    payload = (
        PluginData.objects.filter(plugin=plugin, message_type='tracking')
        .order_by('-created_at').values_list('payload', flat=True).first()
    )
    return satellite_from_tracking(payload)


class BoardsLiveView(APIView):
    @extend_schema(
        summary='What every board is doing now',
        description=(
            'The latest state of each board, the instance running on it, the satellite that instance '
            'follows and why the antenna last stopped. The home page polls it every second.'
        ),
        responses=BoardLiveSerializer(many=True),
    )
    def get(self, request):
        # Each LIMIT 1 subquery walks its board's index from the newest row, so
        # the cost does not grow with the history.
        last_state = RotorState.objects.filter(rotor=OuterRef('pk')).order_by('-received_at').values('pk')[:1]
        last_hold = (
            DispatchOrder.objects.filter(rotor=OuterRef('pk'), kind=DispatchOrder.Kind.HOLD)
            .order_by('-created_at').values('reason')[:1]
        )
        running = PluginInstance.objects.filter(status=PluginInstance.Status.RUNNING)
        rotors = list(
            Rotor.objects.annotate(last_state_id=Subquery(last_state), last_hold_reason=Subquery(last_hold))
            .prefetch_related(Prefetch('plugin_instances', queryset=running, to_attr='running_plugins'))
        )
        states = RotorState.objects.in_bulk([rotor.last_state_id for rotor in rotors if rotor.last_state_id])

        for rotor in rotors:
            rotor.live_state = states.get(rotor.last_state_id)
            # RF-31.1: at most one running instance drives a board.
            rotor.running_plugin = rotor.running_plugins[0] if rotor.running_plugins else None
            rotor.satellite = _satellite(rotor.running_plugin)
            rotor.last_hold_reason = rotor.last_hold_reason or None
        return Response(BoardLiveSerializer(rotors, many=True).data)


class BoardTrackView(APIView):
    @extend_schema(
        summary='The setpoints of the pass the board is following',
        description=(
            'Every point the dispatcher sent the board since its last HOLD, one per instant. '
            'Empty when the last order was a HOLD: no pass in course.'
        ),
        responses={200: TrackSerializer, 404: UNKNOWN_BOARD},
    )
    def get(self, request, device_id):
        rotor = get_board(device_id)
        batches = rotor.orders.filter(kind=DispatchOrder.Kind.BATCH)
        last_hold = (
            rotor.orders.filter(kind=DispatchOrder.Kind.HOLD)
            .order_by('-created_at').values_list('created_at', flat=True).first()
        )
        if last_hold is not None:
            batches = batches.filter(created_at__gt=last_hold)

        # Consecutive batches overlap on purpose (coordinates-dto.md §10), so an
        # instant shows up in up to three rows: the latest one sent is in effect.
        setpoints = {}
        for t0_ms, points in batches.order_by('created_at').values_list('t0_ms', 'points'):
            for dt_ms, az_cdeg, el_cdeg in points:
                setpoints[t0_ms + dt_ms] = (az_cdeg, el_cdeg)

        track = {
            'device_id': rotor.device_id,
            'points': [
                {'t_ms': t_ms, 'az_cdeg': az_cdeg, 'el_cdeg': el_cdeg}
                for t_ms, (az_cdeg, el_cdeg) in sorted(setpoints.items())
            ],
        }
        return Response(TrackSerializer(track).data)


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
