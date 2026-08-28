from django.urls import path

from apps.master import views, views_saas, views_totem

app_name = "master"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # -- Clientes ----------------------------------------------
    path("clientes/", views.ClienteListView.as_view(), name="cliente_lista"),
    path("clientes/novo/", views.ClienteCreateView.as_view(), name="cliente_criar"),
    path("clientes/<int:pk>/", views.ClienteDetailView.as_view(), name="cliente_detalhe"),
    path(
        "clientes/<int:pk>/editar/",
        views.ClienteUpdateView.as_view(),
        name="cliente_editar",
    ),
    path("clientes/<int:pk>/suspender/", views.cliente_suspender, name="cliente_suspender"),
    path("clientes/<int:pk>/api-key/", views.cliente_api_key, name="cliente_api_key"),
    # -- Empresas ----------------------------------------------
    path("empresas/", views.EmpresaListView.as_view(), name="empresa_lista"),
    path("empresas/vincular/", views.EmpresaCreateView.as_view(), name="empresa_vincular"),
    path(
        "empresas/<int:pk>/editar/",
        views.EmpresaUpdateView.as_view(),
        name="empresa_editar",
    ),
    # -- Planos ------------------------------------------------
    path("planos/", views.PlanoListView.as_view(), name="plano_lista"),
    path("planos/novo/", views.PlanoCreateView.as_view(), name="plano_criar"),
    path("planos/<int:pk>/editar/", views.PlanoUpdateView.as_view(), name="plano_editar"),
    path(
        "planos/<int:pk>/excluir/", views.PlanoDeleteView.as_view(), name="plano_excluir"
    ),
    # -- Totens e comodato (Fase 5) ----------------------------
    path("totens/", views_totem.TotemListView.as_view(), name="totem_lista"),
    path("totens/novo/", views_totem.TotemCreateView.as_view(), name="totem_criar"),
    path("totens/<int:pk>/", views_totem.totem_detalhe, name="totem_detalhe"),
    path(
        "totens/<int:pk>/editar/",
        views_totem.TotemUpdateView.as_view(),
        name="totem_editar",
    ),
    path("totens/<int:pk>/comodato/", views_totem.totem_comodato, name="totem_comodato"),
    path(
        "totens/<int:pk>/token/",
        views_totem.totem_regenerar_token,
        name="totem_regenerar_token",
    ),
    path("totens/<int:pk>/devolver/", views_totem.totem_devolver, name="totem_devolver"),
    path(
        "grupos-totem/",
        views_totem.GrupoTotemListView.as_view(),
        name="grupo_totem_lista",
    ),
    path(
        "grupos-totem/novo/",
        views_totem.GrupoTotemCreateView.as_view(),
        name="grupo_totem_criar",
    ),
    path(
        "grupos-totem/<int:pk>/editar/",
        views_totem.GrupoTotemUpdateView.as_view(),
        name="grupo_totem_editar",
    ),
    # -- SaaS: gateway, assinaturas, usuarios, auditoria --------
    path("gateway/", views_saas.gateway, name="gateway"),
    path("assinaturas/", views_saas.assinaturas, name="assinaturas"),
    path(
        "assinaturas/<int:pk>/",
        views_saas.assinatura_detalhe,
        name="assinatura_detalhe",
    ),
    path("usuarios/", views_saas.usuarios, name="usuarios"),
    path("usuarios/novo/", views_saas.usuario_criar, name="usuario_criar"),
    path("usuarios/<int:pk>/editar/", views_saas.usuario_editar, name="usuario_editar"),
    path(
        "usuarios/<int:pk>/senha/",
        views_saas.usuario_resetar_senha,
        name="usuario_resetar_senha",
    ),
    path(
        "usuarios/<int:pk>/ativar/",
        views_saas.usuario_alternar_ativo,
        name="usuario_alternar_ativo",
    ),
    path("auditoria/", views_saas.auditoria, name="auditoria"),
    # -- Logs --------------------------------------------------
    path("logs/", views.LogAcessoListView.as_view(), name="log_lista"),
]
