"""GET /api/logs/<service>: the last lines of PluTO's own containers."""
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .orchestrator import LOG_SERVICES, PluginOrchestrator
from .serializers import LogsQuerySerializer, LogsSerializer


class ServiceLogsView(APIView):
    @extend_schema(
        summary='The last lines of a PluTO service',
        description=(
            f'service is one of: {", ".join(LOG_SERVICES)}. Each plugin instance has its own '
            'under /api/plugins/<plugin_uuid>/logs.'
        ),
        parameters=[LogsQuerySerializer],
        responses={
            200: LogsSerializer,
            400: OpenApiResponse(description='tail out of range.'),
            404: OpenApiResponse(description='Unknown service, or it has no container.'),
            502: OpenApiResponse(description='Could not reach Docker.'),
        },
    )
    def get(self, request, service):
        if service not in LOG_SERVICES:
            raise NotFound(f'Unknown service. One of: {", ".join(LOG_SERVICES)}.')
        query = LogsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        orchestrator = PluginOrchestrator()
        if orchestrator.client is None:
            return Response({'detail': 'Could not reach Docker.'}, status=502)
        lines = orchestrator.service_logs(service, query.validated_data['tail'])
        if lines is None:
            raise NotFound(f'No container for the {service} service.')
        return Response(LogsSerializer({'source': service, 'lines': lines}).data)
