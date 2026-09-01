"""
Kronus — context processors.

`marca`  disponibiliza a identidade Kronus/KS TEC em todos os templates
`tenant` disponibiliza cliente, empresa ativa e tema white-label
"""
from django.conf import settings

from apps.core.constants import TipoUsuario


def marca(request):
    """Identidade visual e dados institucionais (Secoes 1 e 3 do plano)."""
    dados = dict(settings.KRONUS)
    dados["DEBUG"] = settings.DEBUG
    return {
        "KRONUS": dados,
        "APP_NAME": settings.KRONUS["APP_NAME"],
        "TAGLINE": settings.KRONUS["TAGLINE"],
        "KSTEC_LOGO": settings.KRONUS["DESENVOLVEDORA_LOGO"],
        "KSTEC_SITE": settings.KRONUS["DESENVOLVEDORA_SITE"],
        "KSTEC_NOME": settings.KRONUS["DESENVOLVEDORA"],
    }


def tenant(request):
    """
    Contexto multi-tenant + tema white-label parcial (Secao 3.6).

    `tema` traz as cores efetivas da empresa ativa; os templates as
    injetam como CSS custom properties, sobrescrevendo o design system.
    """
    empresa = getattr(request, "empresa_ativa", None)
    user = getattr(request, "user", None)

    tema = {
        "cor_primaria": getattr(empresa, "cor_primaria", "") or "#1E3A5F",
        "cor_secundaria": getattr(empresa, "cor_secundaria", "") or "#D4A017",
        "logo": empresa.logo.url if empresa and empresa.logo else "",
    }

    from apps.core.mixins import escopo_empresas

    nao_lidas = 0
    pendencias = {}
    if user is not None and user.is_authenticated:
        nao_lidas = user.notificacoes.filter(lida=False).count()
        pendencias = _pendencias(user, empresa)

    return {
        "notificacoes_nao_lidas": nao_lidas,
        **pendencias,
        # A regra CSS da logo no menu, ja resolvida.
        #
        # O template nao decide: ele recebe pronto. A alternativa era
        # chamar `css_da_logo("menu")` no proprio HTML, e metodo com
        # argumento nao se chama de dentro de template Django.
        "css_logo_menu": (
            empresa.css_da_logo("menu") if empresa is not None else ""
        ),
        "cliente_atual": getattr(request, "cliente", None),
        "empresa_atual": empresa,
        "empresas_disponiveis": escopo_empresas(user),
        "colaborador_atual": getattr(request, "colaborador", None),
        "tema": tema,
        "eh_master": bool(user and user.is_authenticated and user.tipo == TipoUsuario.MASTER),
        # O master dentro do ambiente de um cliente enxerga o menu do
        # cliente.
        #
        # Sem isto, "entrar no ambiente" entregava metade do que promete:
        # a empresa ativa mudava, mas a barra lateral continuava a do
        # Master — e dar suporte sem conseguir abrir as telas que a
        # pessoa esta descrevendo e o mesmo que nao ter entrado.
        #
        # Nao amplia permissao nenhuma: o master ja alcanca todas as
        # empresas. O que muda e o caminho ate elas.
        "eh_rh": bool(
            user
            and user.is_authenticated
            and (
                user.tipo in (TipoUsuario.RH, TipoUsuario.CLIENTE)
                or (user.tipo == TipoUsuario.MASTER and empresa is not None)
            )
        ),
        "eh_colaborador": bool(
            user and user.is_authenticated and user.tipo == TipoUsuario.COLABORADOR
        ),
    }


def _pendencias(user, empresa) -> dict:
    """
    Contadores exibidos como badge na barra lateral.

    Sao consultas baratas (COUNT com indice) e so rodam para quem tem o
    menu correspondente — o colaborador nao paga pela contagem do RH.
    """
    from apps.core.constants import StatusAprovacao

    dados = {}

    if user.tipo in (TipoUsuario.RH, TipoUsuario.CLIENTE) and empresa is not None:
        from apps.rh.models import Atestado, Justificativa

        dados["atestados_pendentes"] = Atestado.objects.filter(
            empresa=empresa, status=StatusAprovacao.PENDENTE
        ).count()
        dados["justificativas_pendentes"] = Justificativa.objects.filter(
            empresa=empresa, status=StatusAprovacao.PENDENTE
        ).count()

    elif user.tipo == TipoUsuario.COLABORADOR:
        from apps.ponto.models import FechamentoMensal

        colaborador = getattr(user, "colaborador", None)
        if colaborador is not None:
            dados["espelhos_pendentes"] = FechamentoMensal.objects.filter(
                colaborador=colaborador, fechado=True, assinado=False
            ).count()

    return dados


def aparencia(request):
    """
    Tamanho das marcas no painel administrativo.

    Vem da configuracao, e nao do CSS: e ajuste de gosto e de monitor, e
    exigir deploy para mudar a altura de uma logo e desproporcional.
    """
    from apps.comercial.models import ConfiguracaoComercial

    try:
        config = ConfiguracaoComercial.carregar()
    except Exception:
        # Antes da primeira migracao a tabela pode nao existir; o painel
        # nao pode deixar de abrir por causa do tamanho de uma logo.
        return {"LOGO_KRONUS_PX": 32, "LOGO_KSTEC_PX": 16}

    return {
        "LOGO_KRONUS_PX": config.logo_kronus_altura_px,
        "LOGO_KSTEC_PX": config.logo_kstec_altura_px,
    }


def ajuda_da_tela(request):
    """
    Conteudo de ajuda da tela atual.

    Resolvido por context processor porque a ajuda precisa existir em
    **todas** as telas: exigir que cada view lembre de passa-la garantiria
    que algumas ficassem sem — e um botao de ajuda que some em parte do
    sistema ensina o usuario a nao procurar por ele.
    """
    import json

    from apps.core.ajuda import para_rota

    if not getattr(request, "resolver_match", None):
        return {}
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    conteudo = para_rota(request.resolver_match.view_name)
    return {
        "ajuda": conteudo,
        "ajuda_passos_json": json.dumps(conteudo["passos"], ensure_ascii=False),
    }
