from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    """Tiny liveness probe, also handy as the 'it works' page."""
    return JsonResponse(
        {
            "service": "CodeNova GST fraud-ring detection API",
            "status": "ok",
            "api_root": "/api/",
        }
    )


urlpatterns = [
    path("", health),
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    path("api/", include("fraud_engine.urls")),
]
