"""
Kronus — interface de quiosque do totem.

    /totem/<token>/     página única do equipamento (Seção 6.5)
    /totem/offline/     página servida pelo Service Worker sem rede
    /totem/sw.js        Service Worker (precisa de escopo em /totem/)

A autenticação é o token opaco na URL. Não há sessão nem cookie: o totem
é um dispositivo, não um usuário — quem se identifica é o colaborador,
pelo rosto ou pelo CPF, a cada batida.
"""
import logging

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt

from apps.totem.models import EventoTotem, Totem

logger = logging.getLogger("kronus.totem")

#: Versão do app do totem, enviada no heartbeat e usada para diagnóstico.
VERSAO_APP = "1.0.0"


@never_cache
@xframe_options_exempt
def kiosk(request, token):
    """
    Serve a página do totem.

    `never_cache` é deliberado: o token e a configuração da empresa não
    podem ficar em cache de proxy corporativo. O cache dos *assets* fica
    a cargo do Service Worker, que sabe o que pode e o que não pode
    guardar.
    """
    totem = get_object_or_404(
        Totem.objects.select_related("empresa", "empresa__cliente", "empresa__config"),
        token_acesso=token,
        ativo=True,
        deleted_at__isnull=True,
    )

    if totem.empresa.cliente.suspenso:
        return render(
            request,
            "totem/suspenso.html",
            {"empresa": totem.empresa},
            status=403,
        )

    return render(
        request,
        "totem/index.html",
        {
            "totem": totem,
            "empresa": totem.empresa,
            "versao_app": VERSAO_APP,
        },
    )


@never_cache
def offline(request):
    """
    Página de indisponibilidade.

    Fica no cache do Service Worker e é servida quando a navegação
    falha. Não depende de nenhum dado do servidor — por isso não recebe
    o token.
    """
    return render(request, "totem/offline.html")


@never_cache
def service_worker(request):
    """
    Serve o Service Worker a partir de `/totem/sw.js`.

    Um Service Worker só controla URLs abaixo do próprio caminho. Servido
    de `/static/`, ele não poderia interceptar `/totem/<token>/` — daí
    esta view, que o entrega no escopo certo.
    """
    corpo = render_to_string("totem/sw.js", request=request)
    resposta = HttpResponse(corpo, content_type="application/javascript")
    resposta["Service-Worker-Allowed"] = "/totem/"
    resposta["Cache-Control"] = "no-cache"
    return resposta


@never_cache
def diagnostico(request, token):
    """
    Página técnica do equipamento, para o suporte da KS TEC.

    Mostra heartbeat, últimos eventos e taxa de reconhecimento — o que
    normalmente se pediria por telefone ao usuário do totem.
    """
    totem = get_object_or_404(
        Totem.objects.select_related("empresa"), token_acesso=token
    )

    from django.db.models import Count

    from apps.facial.models import TentativaReconhecimento

    tentativas = TentativaReconhecimento.objects.filter(totem=totem)
    resumo = list(
        tentativas.values("resultado").annotate(total=Count("pk")).order_by("-total")
    )
    total = sum(item["total"] for item in resumo) or 1
    for item in resumo:
        item["percentual"] = round(item["total"] * 100 / total, 1)

    return render(
        request,
        "totem/diagnostico.html",
        {
            "totem": totem,
            "empresa": totem.empresa,
            "versao_app": VERSAO_APP,
            "eventos": totem.eventos.all()[:30],
            "resumo_reconhecimento": resumo,
            "total_tentativas": tentativas.count(),
            "tipos_evento": dict(EventoTotem.Tipo.choices),
        },
    )
