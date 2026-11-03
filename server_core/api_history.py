"""The history the front end browses and exports (spec §4.4): what the boards
reported, what the dispatcher sent and what the plugins produced."""
from django.db.models import Count, F, Max, Min
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .downsample import downsample
from .models import Rotor, RotorState
from .pagination import TimeCursorPagination
from .renderers import CSVRenderer
from .serializers import RangeQuerySerializer, SeriesQuerySerializer, SeriesSerializer, StateRowSerializer


def _rotor(device_id):
    rotor = Rotor.objects.filter(device_id=device_id).first()
    if rotor is None:
        raise NotFound('No board with that device_id.')
    return rotor


def _query(serializer_class, request):
    query = serializer_class(data=request.query_params)
    query.is_valid(raise_exception=True)
    return query.validated_data


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
        # walked once without holding them (Review Focus 4).
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
