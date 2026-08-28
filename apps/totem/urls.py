from django.urls import path

from apps.totem import views

app_name = "totem"

urlpatterns = [
    path("<str:token>/manifest.json", views.manifesto, name="manifesto"),
    path("offline/", views.offline, name="offline"),
    path("sw.js", views.service_worker, name="service_worker"),
    # Antes da rota por token: "autenticidade" nao pode ser lido
    # como o token de um totem.
    path("autenticidade/<str:codigo>/", views.autenticidade,
         name="autenticidade"),
    path("etiqueta/<int:pk>.png", views.etiqueta_png, name="etiqueta"),
    path("<str:token>/diagnostico/", views.diagnostico, name="diagnostico"),
    path("<str:token>/", views.kiosk, name="kiosk"),
]
