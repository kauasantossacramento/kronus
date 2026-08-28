"""
Kronus — URLconf raiz.

Mapa de rotas (Secao 6 do plano):
    /                    Landing page publica
    /accounts/           Autenticacao (login por CPF ou e-mail)
    /ponto/              Interface do colaborador (bater ponto, meus pontos)
    /rh/                 Painel do Admin RH
    /master/             Painel Master (KS TEC)
    /totem/<token>/      Interface do totem (kiosk)
    /api/v1/             API REST publica
    /django-admin/       Admin do Django (uso interno)
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.views.generic import RedirectView
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path(
        "faturamento/",
        include("apps.faturamento.urls", namespace="faturamento"),
    ),
    path("", include("apps.landing.urls", namespace="landing")),
    path("comercial/", include("apps.comercial.urls", namespace="comercial")),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("app/", include("apps.core.urls", namespace="core")),
    path("ponto/", include("apps.ponto.urls", namespace="ponto")),
    path("rh/", include("apps.rh.urls", namespace="rh")),
    path("master/", include("apps.master.urls", namespace="master")),
    path("totem/", include("apps.totem.urls", namespace="totem")),
    path("facial/", include("apps.facial.urls", namespace="facial")),
    path("relatorios/", include("apps.relatorios.urls", namespace="relatorios")),
    # Atalho publico da verificacao: o codigo vai impresso em documento,
    # e "kronus.online/verificar" cabe melhor num rodape do que
    # "kronus.online/relatorios/verificar".
    path(
        "verificar/",
        RedirectView.as_view(pattern_name="relatorios:verificar", permanent=False),
        name="verificar_atalho",
    ),
    path("notificacoes/", include("apps.notificacoes.urls", namespace="notificacoes")),
    path("api/v1/", include("apps.api.urls", namespace="api")),
    # POR ULTIMO: o `<slug>` captura qualquer caminho de um segmento, e
    # antes das demais rotas uma empresa chamada "relatorios" sequestraria
    # /relatorios/.
    path("", include("apps.clientes.urls", namespace="clientes")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.erro_403"
handler404 = "apps.core.views.erro_404"
handler500 = "apps.core.views.erro_500"
