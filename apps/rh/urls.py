from django.urls import path

from apps.rh import (
    views,
    views_config,
    views_dados,
    views_gestao,
    views_ponto,
    views_webhooks,
)

app_name = "rh"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # -- Colaboradores -----------------------------------------
    path("colaboradores/", views.ColaboradorListView.as_view(), name="colaborador_lista"),
    path(
        "colaboradores/novo/",
        views.ColaboradorCreateView.as_view(),
        name="colaborador_criar",
    ),
    path(
        "colaboradores/<int:pk>/",
        views.ColaboradorDetailView.as_view(),
        name="colaborador_detalhe",
    ),
    path(
        "colaboradores/<int:pk>/editar/",
        views.ColaboradorUpdateView.as_view(),
        name="colaborador_editar",
    ),
    path(
        "colaboradores/<int:pk>/desligar/",
        views.colaborador_desligar,
        name="colaborador_desligar",
    ),
    # -- Departamentos -----------------------------------------
    path("departamentos/", views.DepartamentoListView.as_view(), name="departamento_lista"),
    path(
        "departamentos/novo/",
        views.DepartamentoCreateView.as_view(),
        name="departamento_criar",
    ),
    path(
        "departamentos/<int:pk>/editar/",
        views.DepartamentoUpdateView.as_view(),
        name="departamento_editar",
    ),
    # -- Cargos ------------------------------------------------
    path("cargos/", views.CargoListView.as_view(), name="cargo_lista"),
    path("cargos/novo/", views.CargoCreateView.as_view(), name="cargo_criar"),
    path("cargos/<int:pk>/editar/", views.CargoUpdateView.as_view(), name="cargo_editar"),

    # -- Registros de ponto (Fase 2) ---------------------------
    path("registros/", views_ponto.RegistroPontoListView.as_view(), name="registro_lista"),
    path("registros/ajustar/", views_ponto.ajustar_registro, name="ajuste_novo"),
    path("registros/<int:pk>/ajustar/", views_ponto.ajustar_registro, name="ajuste_registro"),

    # -- Banco de horas ----------------------------------------
    path("banco-horas/", views_ponto.banco_horas, name="banco_horas"),
    path(
        "banco-horas/<int:colaborador_id>/recalcular/",
        views_ponto.recalcular_periodo,
        name="banco_horas_recalcular",
    ),

    # -- Espelho de ponto --------------------------------------
    path("espelhos/", views_ponto.espelho_lista, name="espelho_lista"),

    # -- Escalas de trabalho -----------------------------------
    path("escalas/", views_ponto.EscalaListView.as_view(), name="escala_lista"),
    path("escalas/nova/", views_ponto.EscalaCreateView.as_view(), name="escala_criar"),
    path("escalas/<int:pk>/editar/", views_ponto.EscalaUpdateView.as_view(), name="escala_editar"),
    path("escalas/<int:pk>/vincular/", views_ponto.vincular_escala, name="escala_vincular"),

    # -- Atestados (Fase 4) ------------------------------------
    path("atestados/", views_gestao.AtestadoListView.as_view(), name="atestado_lista"),
    path("atestados/novo/", views_gestao.AtestadoCreateView.as_view(), name="atestado_criar"),
    path("atestados/<int:pk>/avaliar/", views_gestao.avaliar_atestado, name="atestado_avaliar"),

    # -- Justificativas ----------------------------------------
    path("justificativas/", views_gestao.JustificativaListView.as_view(), name="justificativa_lista"),
    path("justificativas/nova/", views_gestao.JustificativaCreateView.as_view(), name="justificativa_criar"),
    path("justificativas/<int:pk>/avaliar/", views_gestao.avaliar_justificativa, name="justificativa_avaliar"),

    # -- Afastamentos ------------------------------------------
    path("afastamentos/", views_gestao.AfastamentoListView.as_view(), name="afastamento_lista"),
    path("afastamentos/novo/", views_gestao.AfastamentoCreateView.as_view(), name="afastamento_criar"),
    path("afastamentos/<int:pk>/editar/", views_gestao.AfastamentoUpdateView.as_view(), name="afastamento_editar"),

    # -- Fechamento mensal -------------------------------------
    path("fechamento/", views_gestao.fechamento, name="fechamento"),
    path("fechamento/<int:ano>/<int:mes>/fechar/", views_gestao.fechar_periodo, name="fechar_periodo"),
    path(
        "fechamento/<int:ano>/<int:mes>/<int:colaborador_id>/fechar/",
        views_gestao.fechar_periodo,
        name="fechar_periodo_colaborador",
    ),
    path(
        "fechamento/<int:ano>/<int:mes>/<int:colaborador_id>/reabrir/",
        views_gestao.reabrir_periodo,
        name="reabrir_periodo",
    ),

    # -- Configurações -----------------------------------------
    path("configuracoes/", views_config.configuracoes, name="configuracoes"),
    path("configuracoes/reprocessar/", views_config.reprocessar_mes, name="reprocessar_mes"),
    path("configuracoes/personalizacao/", views_config.personalizacao, name="personalizacao"),
    path("configuracoes/notificacoes/", views_config.notificacoes, name="notificacoes_config"),
    path("configuracoes/integracao/", views_config.integracao, name="integracao"),
    # -- Dados: importacao e folha (Fase 6) ---------------------
    path(
        "dados/importar/",
        views_dados.importar_colaboradores,
        name="importar_colaboradores",
    ),
    path(
        "dados/importar/modelo/",
        views_dados.modelo_importacao,
        name="modelo_importacao",
    ),
    path("dados/folha/", views_dados.exportar_folha, name="exportar_folha"),
    path("dados/folha/baixar/", views_dados.baixar_folha, name="baixar_folha"),
    path("equipamentos/", views_dados.equipamentos, name="equipamentos"),
    path("configuracoes/slides/", views_config.slides_totem, name="slides_totem"),
    path(
        "equipamentos/recarregar/",
        views_config.recarregar_totens,
        name="recarregar_totens",
    ),
    # -- Webhooks (Fase 5) -------------------------------------
    path("configuracoes/webhooks/", views_webhooks.webhooks, name="webhooks"),
    path(
        "configuracoes/webhooks/<int:pk>/",
        views_webhooks.webhook_detalhe,
        name="webhook_detalhe",
    ),
    path(
        "configuracoes/webhooks/<int:pk>/testar/",
        views_webhooks.webhook_testar,
        name="webhook_testar",
    ),
    path(
        "configuracoes/webhooks/<int:pk>/entregas/<int:entrega_pk>/reenviar/",
        views_webhooks.webhook_reenviar,
        name="webhook_reenviar",
    ),
]
