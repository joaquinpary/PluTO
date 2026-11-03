"""The plugin instances for the front end: types, create, edit and delete, actions and logs.

What it takes to launch, stop or delete an instance lives in lifecycle.py;
these views only translate it to HTTP.
"""
import logging

import docker
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import lifecycle
from .lifecycle import LifecycleError
from .models import PluginInstance
from .orchestrator import PluginOrchestrator
from .plugin_handlers import PLUGIN_HANDLERS
from .serializers import (
    CoordinatesFileSerializer,
    LogsQuerySerializer,
    LogsSerializer,
    PluginSerializer,
    PluginTypeSerializer,
)

logger = logging.getLogger(__name__)

# The HTTP status each LifecycleError.code becomes.
LIFECYCLE_HTTP_STATUS = {
    'invalid_config': 400,
    'not_file_tracker': 400,
    'bad_file': 400,
    'board_busy': 409,
    'already_running': 409,
    'protected': 409,
    'docker': 502,
    # Mosquitto did not take the coordinates file (send_coordinates_file).
    'broker': 503,
}

UNKNOWN_PLUGIN = OpenApiResponse(description='No plugin instance with that uuid.')


def lifecycle_error_response(exc):
    body = {'detail': exc.detail}
    if exc.fields:
        # The same shape as a rejected save, so the form shows them by field.
        body['config'] = exc.fields
    return Response(body, status=LIFECYCLE_HTTP_STATUS[exc.code])


def get_plugin(plugin_uuid):
    plugin = PluginInstance.objects.select_related('rotor').filter(plugin_uuid=plugin_uuid).first()
    if plugin is None:
        raise NotFound('No plugin instance with that uuid.')
    return plugin


def docker_statuses(plugins):
    """Docker's state of each plugin's container, by plugin_uuid, from a single listing (KAN-50).

    Empty when Docker cannot be reached or the listing fails: the serializer
    then says 'unknown'.
    """
    if not plugins:
        return {}
    orchestrator = PluginOrchestrator()
    if orchestrator.client is None:
        return {}
    try:
        by_name = orchestrator.container_statuses()
    except docker.errors.DockerException as exc:
        # container_statuses() already turns an APIError into None; this is
        # only a safety net for anything else docker-py raises.
        logger.warning('Could not list the plugin containers: %s', exc)
        return {}
    if by_name is None:
        return {}
    return {
        plugin.plugin_uuid: by_name.get(orchestrator.container_name(plugin.plugin_type, plugin.plugin_uuid), 'not_found')
        for plugin in plugins
    }


def plugin_response(plugin, status=200):
    context = {'docker_statuses': docker_statuses([plugin])}
    return Response(PluginSerializer(plugin, context=context).data, status=status)


class PluginTypesView(APIView):
    @extend_schema(summary='List the plugin types and the configuration each one takes',
                   responses=PluginTypeSerializer(many=True))
    def get(self, request):
        types = [
            {
                'type': plugin_type,
                'label': handler.label,
                'message_types': list(handler.allowed_message_types or ()),
                'config_fields': handler.config_fields,
            }
            for plugin_type, handler in sorted(PLUGIN_HANDLERS.items())
        ]
        return Response(PluginTypeSerializer(types, many=True).data)


class PluginsView(APIView):
    @extend_schema(
        summary='List the plugin instances',
        parameters=[
            OpenApiParameter('type', str, description='Only this plugin type.'),
            OpenApiParameter('status', str, enum=PluginInstance.Status.values, description='Only this status.'),
            OpenApiParameter('search', str, description='Part of the name, ignoring case.'),
        ],
        responses=PluginSerializer(many=True),
    )
    def get(self, request):
        plugins = PluginInstance.objects.select_related('rotor')
        if request.query_params.get('type'):
            plugins = plugins.filter(plugin_type=request.query_params['type'])
        if request.query_params.get('status'):
            plugins = plugins.filter(status=request.query_params['status'])
        if request.query_params.get('search'):
            plugins = plugins.filter(name__icontains=request.query_params['search'])

        plugins = list(plugins)
        context = {'docker_statuses': docker_statuses(plugins)}
        return Response(PluginSerializer(plugins, many=True, context=context).data)

    @extend_schema(
        summary='Create a plugin instance',
        description='Created stopped. The config is checked against the fields its type declares.',
        request=PluginSerializer,
        responses={
            201: PluginSerializer,
            400: OpenApiResponse(description='Invalid name, type or config; config errors come by field under "config".'),
        },
    )
    def post(self, request):
        serializer = PluginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return plugin_response(serializer.save(), status=201)


class PluginDetailView(APIView):
    @extend_schema(summary='Show a plugin instance', responses={200: PluginSerializer, 404: UNKNOWN_PLUGIN})
    def get(self, request, plugin_uuid):
        return plugin_response(get_plugin(plugin_uuid))

    @extend_schema(
        summary='Edit the name and the config of a plugin instance',
        description='A running instance keeps its old settings until it is launched again.',
        request=PluginSerializer,
        responses={
            200: PluginSerializer,
            400: OpenApiResponse(description='Invalid name or config; config errors come by field under "config".'),
            404: UNKNOWN_PLUGIN,
        },
    )
    def patch(self, request, plugin_uuid):
        serializer = PluginSerializer(get_plugin(plugin_uuid), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return plugin_response(serializer.save())

    @extend_schema(
        summary='Stop and delete a plugin instance',
        responses={
            204: None,
            404: UNKNOWN_PLUGIN,
            409: OpenApiResponse(description='It has data or orders recorded: stop it instead.'),
            502: OpenApiResponse(description='Docker could not stop its container.'),
        },
    )
    def delete(self, request, plugin_uuid):
        plugin = get_plugin(plugin_uuid)
        try:
            lifecycle.delete(plugin)
        except LifecycleError as exc:
            return lifecycle_error_response(exc)
        return Response(status=204)


# --- Actions -------------------------------------------------------------------

DOCKER_FAILED = OpenApiResponse(description='Docker failed; detail says how.')


def run_action(action, plugin_uuid):
    """Apply a lifecycle function and answer with the instance as it ended up."""
    plugin = get_plugin(plugin_uuid)
    try:
        plugin = action(plugin)
    except LifecycleError as exc:
        return lifecycle_error_response(exc)
    return plugin_response(plugin)


class PluginLaunchView(APIView):
    @extend_schema(
        summary='Launch a plugin instance',
        description='The first launch of a type builds its image and can take minutes: it is one long request.',
        request=None,
        responses={
            200: PluginSerializer,
            400: OpenApiResponse(description='The config is invalid; errors by field under "config".'),
            404: UNKNOWN_PLUGIN,
            409: OpenApiResponse(description='Already running, or another running instance drives its board (RF-31.1).'),
            502: DOCKER_FAILED,
        },
    )
    def post(self, request, plugin_uuid):
        return run_action(lifecycle.launch, plugin_uuid)


class PluginStopView(APIView):
    @extend_schema(summary='Stop a plugin instance', description='Also from ERROR.', request=None,
                   responses={200: PluginSerializer, 404: UNKNOWN_PLUGIN, 502: DOCKER_FAILED})
    def post(self, request, plugin_uuid):
        return run_action(lifecycle.stop, plugin_uuid)


class PluginSyncView(APIView):
    @extend_schema(summary='Match the status of a plugin instance with its container', request=None,
                   responses={200: PluginSerializer, 404: UNKNOWN_PLUGIN, 502: DOCKER_FAILED})
    def post(self, request, plugin_uuid):
        return run_action(lifecycle.sync, plugin_uuid)


class PluginCoordinatesFileView(APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(
        summary='Send a coordinates file to a file_tracker instance',
        description='Retained on the broker: a running instance publishes it at once, a stopped one when launched.',
        request={'multipart/form-data': CoordinatesFileSerializer},
        responses={
            200: PluginSerializer,
            400: OpenApiResponse(description='No file, not a file_tracker, not UTF-8 text or above 1 MiB.'),
            404: UNKNOWN_PLUGIN,
            503: OpenApiResponse(description='The broker did not answer; nothing was sent.'),
        },
    )
    def post(self, request, plugin_uuid):
        plugin = get_plugin(plugin_uuid)
        serializer = CoordinatesFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            lifecycle.send_coordinates_file(plugin, serializer.validated_data['file'])
        except LifecycleError as exc:
            return lifecycle_error_response(exc)
        return plugin_response(plugin)


class PluginLogsView(APIView):
    @extend_schema(
        summary='The last lines of the container log of a plugin instance',
        parameters=[LogsQuerySerializer],
        responses={
            200: LogsSerializer,
            400: OpenApiResponse(description='tail out of range.'),
            404: OpenApiResponse(description='Unknown plugin, or it has no container.'),
            502: OpenApiResponse(description='Could not reach Docker.'),
        },
    )
    def get(self, request, plugin_uuid):
        plugin = get_plugin(plugin_uuid)
        query = LogsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        orchestrator = PluginOrchestrator()
        if orchestrator.client is None:
            return Response({'detail': 'Could not reach Docker.'}, status=502)
        lines = orchestrator.container_logs(plugin.plugin_type, plugin.plugin_uuid, query.validated_data['tail'])
        if lines is None:
            # No container, which is what stopping an instance leaves. A Docker
            # error while looking it up is None too; the orchestrator logs it.
            raise NotFound(f'{plugin.name} has no container. Launch it first.')
        return Response(LogsSerializer({'source': plugin.name, 'lines': lines}).data)
