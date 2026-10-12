"""How plugin containers authenticate against /api/: `Authorization: Plugin <token>`.

A keyword of its own, rather than Bearer, so a plugin token and the user's JWT
can never be mistaken for one another: each view lists the one it accepts, and
the other is simply not read.
"""
from django.contrib.auth.models import AnonymousUser
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from .api_tokens import hash_token
from .models import PluginInstance


class PluginTokenAuthentication(BaseAuthentication):
    keyword = 'Plugin'

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword.lower().encode():
            return None
        if len(parts) != 2:
            raise AuthenticationFailed(f'Expected "{self.keyword} <token>".')

        try:
            token = parts[1].decode('ascii')
        except UnicodeDecodeError:
            raise AuthenticationFailed('Invalid token.')

        plugin = (
            PluginInstance.objects.select_related('rotor')
            .filter(api_token_hash=hash_token(token), status=PluginInstance.Status.RUNNING)
            .first()
        )
        if plugin is None:
            # Also what a container still running after its instance was stopped gets.
            raise AuthenticationFailed('The token does not belong to a running plugin instance.')

        # A plugin is not a person: request.user stays anonymous, so no
        # endpoint guarded by IsAuthenticated ever lets a plugin in.
        return AnonymousUser(), plugin

    def authenticate_header(self, request):
        # Makes DRF answer 401 rather than 403 when the token is missing.
        return self.keyword


class IsPluginInstance(BasePermission):
    """The request was authenticated by PluginTokenAuthentication."""

    def has_permission(self, request, view):
        return isinstance(request.auth, PluginInstance)


class PluginTokenScheme(OpenApiAuthenticationExtension):
    """Describes the plugin token in the OpenAPI schema; registered by being defined."""
    target_class = PluginTokenAuthentication
    name = 'pluginToken'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'Plugin <token>: the PLUTO_API_TOKEN the container was launched with.',
        }
