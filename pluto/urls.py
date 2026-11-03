"""URL configuration for pluto.

Everything is under /api/ (server_core/urls.py, docs/contracts/ingest-api.md):
the front end is served by the web container, the healthcheck is
GET /api/health, and there is no Django admin. `manage.py createsuperuser`
still works from a console, as the way back in.
"""
from django.urls import include, path

urlpatterns = [
    path('api/', include('server_core.urls')),
]
