from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from .api import account, boards, history, ingest, logs, plugins

urlpatterns = [
    # Plugin containers, with Plugin <token>.
    path('plugin-data/<str:message_type>', ingest.PluginDataView.as_view(), name='api-plugin-data'),
    path('device/status', ingest.DeviceStatusView.as_view(), name='api-device-status'),
    path('device/state', ingest.DeviceStateView.as_view(), name='api-device-state'),
    path('plugin/rotor', ingest.PluginRotorView.as_view(), name='api-plugin-rotor'),
    path('dispatch-orders', ingest.DispatchOrdersView.as_view(), name='api-dispatch-orders'),
    # Open to anyone: the healthcheck, and creating the first user.
    path('health', account.HealthView.as_view(), name='api-health'),
    path('setup', account.SetupView.as_view(), name='api-setup'),
    # The user's session: log in, refresh, log out (blacklists the refresh token).
    path('auth/token', TokenObtainPairView.as_view(), name='api-token'),
    path('auth/token/refresh', TokenRefreshView.as_view(), name='api-token-refresh'),
    path('auth/token/blacklist', TokenBlacklistView.as_view(), name='api-token-blacklist'),
    path('auth/password', account.PasswordView.as_view(), name='api-password'),
    # The front end, with Bearer <jwt>.
    path('boards', boards.BoardsView.as_view(), name='api-boards'),
    path('boards/scan', boards.BoardScanView.as_view(), name='api-boards-scan'),
    # Before <device_id>, which would take "live" for a board.
    path('boards/live', boards.BoardsLiveView.as_view(), name='api-boards-live'),
    path('boards/<str:device_id>', boards.BoardDetailView.as_view(), name='api-board'),
    path('boards/<str:device_id>/track', boards.BoardTrackView.as_view(), name='api-board-track'),
    path('plugin-types', plugins.PluginTypesView.as_view(), name='api-plugin-types'),
    path('plugins', plugins.PluginsView.as_view(), name='api-plugins'),
    path('plugins/<uuid:plugin_uuid>', plugins.PluginDetailView.as_view(), name='api-plugin'),
    path('plugins/<uuid:plugin_uuid>/board', plugins.PluginBoardView.as_view(), name='api-plugin-board'),
    path('plugins/<uuid:plugin_uuid>/launch', plugins.PluginLaunchView.as_view(), name='api-plugin-launch'),
    path('plugins/<uuid:plugin_uuid>/stop', plugins.PluginStopView.as_view(), name='api-plugin-stop'),
    path('plugins/<uuid:plugin_uuid>/sync', plugins.PluginSyncView.as_view(), name='api-plugin-sync'),
    path('plugins/<uuid:plugin_uuid>/coordinates-file', plugins.PluginCoordinatesFileView.as_view(),
         name='api-plugin-coordinates-file'),
    path('plugins/<uuid:plugin_uuid>/logs', plugins.PluginLogsView.as_view(), name='api-plugin-logs'),
    path('boards/<str:device_id>/states', history.BoardStatesView.as_view(), name='api-board-states'),
    path('boards/<str:device_id>/states/series', history.BoardStatesSeriesView.as_view(),
         name='api-board-states-series'),
    path('orders', history.OrdersView.as_view(), name='api-orders'),
    path('plugin-data', history.PluginDataHistoryView.as_view(), name='api-plugin-data-history'),
    path('results/pointing-error', history.PointingErrorView.as_view(), name='api-results-pointing-error'),
    path('results/reception', history.ReceptionView.as_view(), name='api-results-reception'),
    path('logs/<str:service>', logs.ServiceLogsView.as_view(), name='api-service-logs'),
    # The OpenAPI schema and its Swagger UI.
    path('schema', SpectacularAPIView.as_view(), name='api-schema'),
    path('docs', SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-docs'),
]
