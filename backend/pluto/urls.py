"""Everything lives under /api/; no Django admin (`createsuperuser` still works)."""
from django.urls import include, path

urlpatterns = [
    path('api/', include('server_core.urls')),
]
