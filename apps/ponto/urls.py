from django.urls import path

from apps.ponto import views, views_espelho

app_name = "ponto"

urlpatterns = [
    path("registrar/", views.registrar, name="registrar"),
    path("registrar/batida/", views.registrar_batida, name="registrar_batida"),
    path("meus-pontos/", views.meus_pontos, name="meus_pontos"),
    path("comprovante/<uuid:uuid>/", views.comprovante, name="comprovante"),
    path("espelho/<int:ano>/<int:mes>/", views.espelho, name="espelho"),
    path(
        "espelho/<int:ano>/<int:mes>/<int:colaborador_id>/",
        views.espelho,
        name="espelho_colaborador",
    ),

    # -- Espelhos e assinatura eletrônica (Fase 4) -------------
    path("espelhos/", views_espelho.meus_espelhos, name="meus_espelhos"),
    path("espelhos/<int:pk>/", views_espelho.conferir_espelho, name="conferir_espelho"),
    path("espelhos/<int:pk>/assinar/", views_espelho.assinar_espelho, name="assinar_espelho"),
    path(
        "justificativa/",
        views_espelho.solicitar_justificativa,
        name="solicitar_justificativa",
    ),
]
