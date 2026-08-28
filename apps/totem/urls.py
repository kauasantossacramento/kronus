from django.urls import path

from apps.totem import views

app_name = "totem"

urlpatterns = [
    path("offline/", views.offline, name="offline"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("<str:token>/diagnostico/", views.diagnostico, name="diagnostico"),
    path("<str:token>/", views.kiosk, name="kiosk"),
]
