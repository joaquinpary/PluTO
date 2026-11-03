"""The account endpoints of the front end: healthcheck, first-run setup and password change.

health and setup are open, and do not even read the Authorization header: a
stale token left in the browser must not turn them into a 401.
"""
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .api import Conflict
from .serializers import HealthSerializer, PasswordChangeSerializer, SetupSerializer, SetupStatusSerializer


class OpenView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class HealthView(OpenView):
    @extend_schema(
        summary='Healthcheck',
        description='Opens a database connection, so wrong credentials show up here as a 503.',
        responses={200: HealthSerializer, 503: HealthSerializer},
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except DatabaseError:
            return Response({'status': 'degraded', 'service': 'pluto-backend', 'database': 'unreachable'}, status=503)
        return Response({'status': 'ok', 'service': 'pluto-backend', 'database': 'ok'})


class SetupView(OpenView):
    @extend_schema(summary='Whether the first user still has to be created', responses=SetupStatusSerializer)
    def get(self, request):
        return Response({'needs_setup': not get_user_model().objects.exists()})

    @extend_schema(
        summary='Create the only user',
        description='Only while there is no user at all. After that, `createsuperuser` is the way to add one.',
        request=SetupSerializer,
        responses={
            201: SetupSerializer,
            400: OpenApiResponse(description='Invalid username, or a password the validators reject.'),
            409: OpenApiResponse(description='The user already exists.'),
        },
    )
    def post(self, request):
        User = get_user_model()
        if User.objects.exists():
            raise Conflict('The user already exists. Log in instead.')

        serializer = SetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.create_superuser(
            serializer.validated_data['username'], password=serializer.validated_data['password'],
        )
        return Response({'username': user.username}, status=201)


class PasswordView(APIView):
    @extend_schema(
        summary="Change the user's password",
        request=PasswordChangeSerializer,
        responses={
            204: None,
            400: OpenApiResponse(description='Wrong current password, or a new one the validators reject.'),
        },
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        return Response(status=204)
