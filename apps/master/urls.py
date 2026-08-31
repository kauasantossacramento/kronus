from django.urls import path

from apps.master import views, views_comercial, views_saas, views_totem

app_name = "master"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # -- Clientes ----------------------------------------------
    # Auditoria do reconhecimento: a foto, a decisao e o numero que
    # decidiu. Sem isso, "foi a pessoa certa?" so tinha resposta de
    # conversa — e conversa e onde duvida sobre ponto vira litigio.
    path("reconhecimentos/", views.reconhecimentos, name="reconhecimentos"),
    path("clientes/", views.ClienteListView.as_view(), name="cliente_lista"),
    path("clientes/novo/", views.ClienteCreateView.as_view(), name="cliente_criar"),
    path("clientes/<int:pk>/", views.ClienteDetailView.as_view(), name="cliente_detalhe"),
    # Suporte: ver o ambiente com os olhos do cliente. Ver views.entrar_como.
    path("empresas/<int:pk>/entrar/", views.entrar_como, name="entrar_como"),
    path("sair-do-ambiente/", views.sair_do_ambiente, name="sair_do_ambiente"),
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
    path(
        "empresas/<int:pk>/personalizacao/",
        views.empresa_personalizacao,
        name="empresa_personalizacao",
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
    # Recarga de verdade — distinta da atualizacao ao vivo, que ja
    # acontece ao salvar a personalizacao. Ver views_totem.
    path("totens/recarregar/", views_totem.totens_recarregar_todos,
         name="totens_recarregar"),
    path("totens/<int:pk>/recarregar/", views_totem.totem_recarregar,
         name="totem_recarregar"),
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
    path("comercial/", views_comercial.configuracao, name="comercial_config"),
    path("comercial/demos/", views_comercial.demonstracoes, name="comercial_demos"),
    path("comercial/demos/nova/", views_comercial.demonstracao_criar,
         name="demo_criar"),
    path(
        "comercial/demos/<int:pk>/prorrogar/",
        views_comercial.demonstracao_prorrogar,
        name="demo_prorrogar",
    ),
    path(
        "comercial/demos/<int:pk>/converter/",
        views_comercial.demonstracao_converter,
        name="demo_converter",
    ),
    path(
        "comercial/demos/<int:pk>/encerrar/",
        views_comercial.demonstracao_encerrar,
        name="demo_encerrar",
    ),
    path("gateway/", views_saas.gateway, name="gateway"),
    path("assinaturas/", views_saas.assinaturas, name="assinaturas"),
    path("assinaturas/custos/", views_saas.custos, name="custos"),
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
