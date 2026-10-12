from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from . import api

urlpatterns = [
    # Plugin containers, with Plugin <token>.
    path('plugin-data/<str:message_type>', api.PluginDataView.as_view(), name='api-plugin-data'),
    path('device/status', api.DeviceStatusView.as_view(), name='api-device-status'),
    path('device/state', api.DeviceStateView.as_view(), name='api-device-state'),
    # The user's session: log in, refresh, log out (blacklists the refresh token).
    path('auth/token', TokenObtainPairView.as_view(), name='api-token'),
    path('auth/token/refresh', TokenRefreshView.as_view(), name='api-token-refresh'),
    path('auth/token/blacklist', TokenBlacklistView.as_view(), name='api-token-blacklist'),
    # The front end, with Bearer <jwt>.
    path('boards', api.BoardsView.as_view(), name='api-boards'),
    path('boards/scan', api.BoardScanView.as_view(), name='api-boards-scan'),
    path('plugins/<uuid:plugin_uuid>/board', api.PluginBoardView.as_view(), name='api-plugin-board'),
    # The OpenAPI schema and its Swagger UI.
    path('schema', SpectacularAPIView.as_view(), name='api-schema'),
    path('docs', SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-docs'),
]
