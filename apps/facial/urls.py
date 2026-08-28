from django.urls import path

from apps.facial import views

app_name = "facial"

urlpatterns = [
    path("cadastro/<int:colaborador_id>/", views.cadastro, name="cadastro"),
    path(
        "cadastro/<int:colaborador_id>/amostra/",
        views.receber_amostra,
        name="receber_amostra",
    ),
    path(
        "cadastro/<int:colaborador_id>/consentir/",
        views.registrar_consentimento,
        name="consentimento",
    ),
    path(
        "cadastro/<int:colaborador_id>/amostra/<int:amostra_id>/excluir/",
        views.excluir_amostra,
        name="excluir_amostra",
    ),
    path(
        "cadastro/<int:colaborador_id>/refazer/",
        views.refazer_cadastro,
        name="refazer_cadastro",
    ),
    path(
        "cadastro/<int:colaborador_id>/excluir/",
        views.excluir_biometria,
        name="excluir_biometria",
    ),
]
