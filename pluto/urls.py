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
from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from pymongo import MongoClient
from pymongo.errors import PyMongoError

mongo_client = MongoClient(
    host=settings.MONGO_CONFIG['HOST'],
    port=settings.MONGO_CONFIG['PORT'],
    username=settings.MONGO_CONFIG['USERNAME'] or None,
    password=settings.MONGO_CONFIG['PASSWORD'] or None,
    serverSelectionTimeoutMS=1000,
)


def healthcheck(_request):
    mongo_status = 'unreachable'

    try:
        mongo_client.admin.command('ping')
        mongo_status = 'ok'
    except PyMongoError:
        return JsonResponse(
            {
                'status': 'degraded',
                'service': 'pluto-backend',
                'mongodb': mongo_status,
            },
            status=503,
        )

    return JsonResponse(
        {
            'status': 'ok',
            'service': 'pluto-backend',
            'mongodb': mongo_status,
        }
    )

urlpatterns = [
    path('', healthcheck, name='healthcheck'),
    path('admin/', admin.site.urls),
]
