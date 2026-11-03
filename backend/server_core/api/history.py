"""The history the front end browses and exports: what the boards
reported, what the plugins sent them and produced, and the results
computed from them."""
from datetime import timedelta

from django.db.models import Count, F, Max, Min
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from ..downsample import downsample
from ..models import DispatchOrder, PluginData, PluginInstance, Rotor, RotorState
from ..pagination import TimeCursorPagination
from ..renderers import CSVRenderer
from ..results import pointing_error, reception_by_day
from ..serializers import (
    OrderRowSerializer,
    OrdersQuerySerializer,
    PluginDataQuerySerializer,
    PluginDataRowSerializer,
    PointingErrorQuerySerializer,
    PointingErrorSerializer,
    RangeQuerySerializer,
    ReceptionQuerySerializer,
    ReceptionSerializer,
    SeriesQuerySerializer,
    SeriesSerializer,
    StateRowSerializer,
)


def _rotor(device_id):
    rotor = Rotor.objects.filter(device_id=device_id).first()
    if rotor is None:
        raise NotFound('No board with that device_id.')
    return rotor


def _query(serializer_class, request):
    query = serializer_class(data=request.query_params)
    query.is_valid(raise_exception=True)
    return query.validated_data


# CSVRenderer builds the whole file before sending it (about 3 600 rows/s):
# a week of states at one per second takes a few minutes, well inside nginx's 600 s.
# A cap instead of streaming: values() and a StreamingHttpResponse if longer exports are ever needed.
CSV_MAX_RANGE = timedelta(days=7)


class HistoryListView(ListAPIView):
    """A history table: newest first with a cursor per page or, with
    ?format=csv, every row of the range, oldest first."""
    pagination_class = TimeCursorPagination
    renderer_classes = [JSONRenderer, CSVRenderer]
    query_serializer = RangeQuerySerializer
    lookups = {}               # query parameter -> ORM lookup
    time_field = 'created_at'  # what from, to and the cursor go by
    csv_name = 'rows'

    def base_queryset(self):
        return self.serializer_class.Meta.model.objects.all()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            # drf-spectacular builds the schema without a request to filter by.
            return self.serializer_class.Meta.model.objects.none()

        params = _query(self.query_serializer, self.request)
        filters = {lookup: params[name] for name, lookup in self.lookups.items() if name in params}
        if 'from' in params:
            filters[f'{self.time_field}__gte'] = params['from']
        if 'to' in params:
            filters[f'{self.time_field}__lt'] = params['to']
        return self.base_queryset().filter(**filters)

    def list(self, request, *args, **kwargs):
        if request.accepted_renderer.format != 'csv':
            return super().list(request, *args, **kwargs)

        params = _query(self.query_serializer, request)
        if 'from' not in params or 'to' not in params or params['to'] - params['from'] > CSV_MAX_RANGE:
            # As JSON, not CSV, so the front shows the detail.
            request.accepted_renderer, request.accepted_media_type = JSONRenderer(), 'application/json'
            return Response({'detail': 'Exporting needs from and to, at most 7 days apart.'}, status=400)

        rows = self.get_queryset().order_by(self.time_field, 'pk').iterator(chunk_size=2000)
        # A generator over .iterator(): the rows of a long range are never all
        # instances at once. CSVRenderer still builds the whole text in memory.
        response = Response({'results': (self.get_serializer(row).data for row in rows)})
        response['Content-Disposition'] = f'attachment; filename="{self.csv_name}.csv"'
        return response


@extend_schema_view(get=extend_schema(
    summary='States a board reported',
    description='Paginated by a cursor, newest first. `?format=csv` returns every row of the range, oldest first.',
    parameters=[RangeQuerySerializer],
))
class BoardStatesView(HistoryListView):
    serializer_class = StateRowSerializer
    time_field = 'received_at'
    csv_name = 'states'

    def base_queryset(self):
        return RotorState.objects.filter(rotor=_rotor(self.kwargs['device_id']))


class BoardStatesSeriesView(APIView):
    @extend_schema(
        summary="A board's position over time, for a chart",
        description=(
            'The span from the first state of the range to the last is cut into `max_points` intervals '
            'and the last state of each one is kept.'
        ),
        parameters=[SeriesQuerySerializer],
        responses={200: SeriesSerializer, 400: OpenApiResponse(description='Missing or invalid range.'),
                   404: OpenApiResponse(description='Unknown board.')},
    )
    def get(self, request, device_id):
        rotor = _rotor(device_id)
        params = _query(SeriesQuerySerializer, request)
        states = RotorState.objects.filter(rotor=rotor, received_at__gte=params['from'], received_at__lt=params['to'])
        # The bounds first, in one aggregate query, so the rows can then be
        # walked once without holding them.
        bounds = states.aggregate(start=Min('received_at'), end=Max('received_at'), count=Count('pk'))
        if not bounds['count']:
            return Response(SeriesSerializer({'points': []}).data)
        # values(): a small dict per row is much cheaper than a model instance.
        rows = (
            states.order_by('received_at', 'pk')
            .values('az_cdeg', 'el_cdeg', t=F('received_at'))
            .iterator(chunk_size=2000)
        )
        points = downsample(rows, 't', params['max_points'],
                            start=bounds['start'], end=bounds['end'], count=bounds['count'])
        return Response(SeriesSerializer({'points': points}).data)


@extend_schema_view(get=extend_schema(
    summary='Orders the plugins sent to their boards',
    description='Paginated by a cursor, newest first. `?format=csv` returns every row of the range, oldest first.',
    parameters=[OrdersQuerySerializer],
))
class OrdersView(HistoryListView):
    serializer_class = OrderRowSerializer
    query_serializer = OrdersQuerySerializer
    lookups = {'board': 'rotor__device_id', 'kind': 'kind', 'reason': 'reason'}
    csv_name = 'dispatch-orders'

    def base_queryset(self):
        return DispatchOrder.objects.select_related('rotor', 'plugin')


@extend_schema_view(get=extend_schema(
    summary='Data the plugins sent',
    description=(
        'rssi, snr, crc_error and satellite come out of the payload when it has them, '
        'and are null otherwise. Paginated by a cursor, newest first. `?format=csv` returns '
        'every row of the range, oldest first.'
    ),
    parameters=[PluginDataQuerySerializer],
))
class PluginDataHistoryView(HistoryListView):
    serializer_class = PluginDataRowSerializer
    query_serializer = PluginDataQuerySerializer
    lookups = {'plugin': 'plugin__plugin_uuid', 'type': 'message_type'}
    csv_name = 'plugin-data'

    def base_queryset(self):
        return PluginData.objects.select_related('plugin')


def _results_response(request, key, rows, serializer_class, csv_name):
    """{key: rows} as JSON or, with ?format=csv, one CSV line per row as a download."""
    data = serializer_class({key: rows}).data
    if request.accepted_renderer.format != 'csv':
        return Response(data)
    # CSVRenderer writes a line per element of "results".
    response = Response({'results': data[key]})
    response['Content-Disposition'] = f'attachment; filename="{csv_name}.csv"'
    return response


class PointingErrorView(APIView):
    renderer_classes = [JSONRenderer, CSVRenderer]

    @extend_schema(
        summary='Pointing error per pass of a board',
        description=(
            'A pass is the BATCH orders up to the HOLD that ended them; passes still in progress are left out. '
            'source is `meas` when the board reported err_cdeg (encoders), and `commanded` when the error is '
            'what the board reported against the order it was executing, matched by t_sent_ms. '
            '`?format=csv` returns one line per pass.'
        ),
        parameters=[PointingErrorQuerySerializer],
        responses={200: PointingErrorSerializer, 400: OpenApiResponse(description='Missing board or range.'),
                   404: OpenApiResponse(description='Unknown board.')},
    )
    def get(self, request):
        params = _query(PointingErrorQuerySerializer, request)
        rotor = _rotor(params['board'])
        passes = pointing_error(rotor, params['from'], params['to'])
        return _results_response(request, 'passes', passes, PointingErrorSerializer, 'pointing-error')


class ReceptionView(APIView):
    renderer_classes = [JSONRenderer, CSVRenderer]

    @extend_schema(
        summary='Reception per day of a plugin instance',
        description=(
            'Packets, CRC errors and mean RSSI and SNR of its rx data, one entry per UTC day of the range. '
            '`?format=csv` returns one line per day.'
        ),
        parameters=[ReceptionQuerySerializer],
        responses={200: ReceptionSerializer, 400: OpenApiResponse(description='Missing plugin or range.'),
                   404: OpenApiResponse(description='Unknown plugin instance.')},
    )
    def get(self, request):
        params = _query(ReceptionQuerySerializer, request)
        plugin = PluginInstance.objects.filter(plugin_uuid=params['plugin']).first()
        if plugin is None:
            raise NotFound('No plugin instance with that uuid.')
        days = reception_by_day(plugin, params['from'], params['to'])
        return _results_response(request, 'days', days, ReceptionSerializer, 'reception')
