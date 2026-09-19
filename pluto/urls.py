"""
URL configuration for pluto project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.urls import path


def healthcheck(_request):
    try:
        # Opening the connection authenticates, so a credentials mismatch
        # shows up here instead of silently reporting a healthy database.
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except DatabaseError:
        return JsonResponse(
            {
                'status': 'degraded',
                'service': 'pluto-backend',
                'database': 'unreachable',
            },
            status=503,
        )

    return JsonResponse(
        {
            'status': 'ok',
            'service': 'pluto-backend',
            'database': 'ok',
        }
    )

urlpatterns = [
    path('', healthcheck, name='healthcheck'),
    path('admin/', admin.site.urls),
]
