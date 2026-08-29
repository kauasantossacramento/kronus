"""
Kronus — URLconf da API REST (v1).

    /api/v1/conta/          identifica a credencial e a cota
    /api/v1/colaboradores/  cadastro
    /api/v1/departamentos/  estrutura
    /api/v1/cargos/
    /api/v1/escalas/
    /api/v1/pontos/         marcações (+ registrar/, {uuid}/verificar/)
    /api/v1/banco-horas/    apuração (+ resumo/)
    /api/v1/atestados/
    /api/v1/relatorios/afd/       arquivo fiscal
    /api/v1/relatorios/aej/
    /api/v1/relatorios/espelho/
    /api/v1/totem/...       endpoints do equipamento de quiosque
    /api/v1/schema/         OpenAPI 3 gerado pelo drf-spectacular
    /api/v1/docs/           Swagger UI
    /api/v1/redoc/          ReDoc

Os recursos usam `uuid` como lookup, nunca o id sequencial: expor ids
incrementais numa API pública permite estimar o tamanho da base e
enumerar registros vizinhos.
"""
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from apps.api import views_manutencao, views_publicos, views_totem

app_name = "api"

totem_patterns = [
    path("recognize/", views_totem.recognize, name="totem_recognize"),
    path("punch-cpf/", views_totem.punch_cpf, name="totem_punch_cpf"),
    path("heartbeat/", views_totem.heartbeat, name="totem_heartbeat"),
    path("config/", views_totem.config, name="totem_config"),
    path("colaboradores-offline/", views_totem.colaboradores_offline,
         name="totem_colaboradores_offline"),
    path("sincronizar/", views_totem.sincronizar_offline,
         name="totem_sincronizar"),

    # Cadastro facial feito no proprio equipamento — ver
    # apps/api/views_manutencao.py.
    path("manutencao/entrar/", views_manutencao.entrar,
         name="totem_manutencao_entrar"),
    path("manutencao/sair/", views_manutencao.sair,
         name="totem_manutencao_sair"),
    path("manutencao/colaboradores/", views_manutencao.colaboradores,
         name="totem_manutencao_colaboradores"),
    path("manutencao/consentimento/", views_manutencao.consentimento,
         name="totem_manutencao_consentimento"),
    path("manutencao/amostra/", views_manutencao.amostra,
         name="totem_manutencao_amostra"),
]

relatorio_patterns = [
    path("afd/", views_publicos.AFDAPIView.as_view(), name="afd"),
    path("aej/", views_publicos.AEJAPIView.as_view(), name="aej"),
    path("espelho/", views_publicos.EspelhoAPIView.as_view(), name="espelho"),
]

router = DefaultRouter()
router.register("colaboradores", views_publicos.ColaboradorViewSet, basename="colaborador")
router.register("departamentos", views_publicos.DepartamentoViewSet, basename="departamento")
router.register("cargos", views_publicos.CargoViewSet, basename="cargo")
router.register("escalas", views_publicos.EscalaViewSet, basename="escala")
router.register("pontos", views_publicos.RegistroPontoViewSet, basename="ponto")
router.register("banco-horas", views_publicos.BancoHorasViewSet, basename="bancohoras")
router.register("atestados", views_publicos.AtestadoViewSet, basename="atestado")

urlpatterns = [
    path("conta/", views_publicos.ContaAPIView.as_view(), name="conta"),
    path("relatorios/", include((relatorio_patterns, "relatorios"))),
    path("totem/", include((totem_patterns, "totem"))),
    # Guia de integracao. O Swagger lista endpoints; este guia explica
    # como pensar a integracao — sincronizar por NSR, validar a
    # assinatura do webhook, converter horas para a folha.
    path(
        "guia/",
        TemplateView.as_view(template_name="api/guia.html"),
        name="guia",
    ),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"), name="swagger"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api:schema"), name="redoc"),
    path("", include(router.urls)),
]
