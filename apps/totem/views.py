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

from django.conf import settings

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt

from apps.core.versao import versao_dos_estaticos
from apps.totem.models import EventoTotem, Totem

logger = logging.getLogger("kronus.totem")

#: Versão do app do totem, enviada no heartbeat e usada para diagnóstico.
#: Versao do app do totem.
#:
#: Vem de `settings.KRONUS["VERSAO"]`, a mesma que o AEJ declara no
#: registro 08. Duas constantes separadas divergiriam no primeiro
#: lancamento, e o suporte passaria a ver uma versao no relatorio fiscal
#: e outra na tela do equipamento.
VERSAO_APP = settings.KRONUS["VERSAO"]


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
            # So os slides vigentes hoje: um comunicado com prazo sai da
            # rotacao sozinho, sem alguem precisar lembrar de remove-lo.
            "slides": [
                slide
                for slide in totem.empresa.slides.order_by("ordem", "created_at")
                if slide.vigente
            ],
            "versao_app": VERSAO_APP,
            "versao_estaticos": versao_dos_estaticos(),
            # O gesto de manutencao so e ligado quando a porta existe:
            # um caminho que aparece e recusa ensina que ele esta ali.
            "cadastro_no_totem": (
                totem.empresa.cliente.cadastro_no_totem_disponivel
            ),
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
    from apps.core.versao import versao_dos_estaticos
    # A chave do cache precisa mudar a cada deploy: com uma string
    # fixa o `activate` nunca apaga nada e o totem fica com os
    # arquivos do deploy anterior.
    corpo = render_to_string(
        "totem/sw.js",
        {"versao_estaticos": versao_dos_estaticos()},
        request=request,
    )
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


@never_cache
def manifesto(request, token):
    """
    Manifesto PWA do totem.

    **`display: fullscreen`**, ao contrário do app do colaborador. Aqui o
    aparelho é dedicado: fica preso num suporte na portaria, e a barra de
    status só oferece um caminho para alguém sair do quiosque. Esconder é
    o comportamento certo.

    `orientation: portrait` porque o enquadramento do rosto pressupõe
    tablet em pé; girar produziria recorte lateral e embedding ruim.
    """
    from django.http import JsonResponse

    from apps.core.icones_pwa import para_logo

    totem = get_object_or_404(
        Totem.objects.select_related("empresa"), token_acesso=token, ativo=True
    )
    empresa = totem.empresa

    return JsonResponse({
        "name": f"Ponto — {empresa.nome_exibicao}",
        "short_name": "Ponto",
        "description": f"Totem de registro de ponto de {empresa.nome_exibicao}",
        "start_url": totem.url_kiosk,
        "scope": totem.url_kiosk,
        "display": "fullscreen",
        # `display_override` pede o modo de janela mais imersivo que o
        # navegador oferecer, caindo para os seguintes quando não houver.
        "display_override": ["window-controls-overlay", "fullscreen", "standalone"],
        "orientation": "portrait",
        "background_color": empresa.cor_primaria,
        "theme_color": empresa.cor_primaria,
        "lang": "pt-BR",
        "categories": ["business", "productivity"],
        "prefer_related_applications": False,
        "icons": para_logo(empresa.logo.url if empresa.logo else None),
    })


def autenticidade(request, codigo):
    """
    Pagina publica de conferencia do equipamento (`/totem/autenticidade/<codigo>/`).

    Quem aponta a camera para a etiqueta quer saber uma coisa: este
    aparelho e legitimo? A pagina responde isso e **nada mais** — nao
    expoe token, nem colaborador, nem batida. Um QR impresso e visivel
    para qualquer visitante da recepcao.

    Sem login por construcao: exigir conta aqui tornaria a verificacao
    inutil justamente para quem precisa dela — o fiscal, o cliente novo,
    o segurança que encontrou o tablet fora do lugar.
    """
    from django.shortcuts import render

    encontrado = None
    # O codigo e um digest; nao da para consultar por ele no banco sem
    # recalcular. Sao dezenas de totens, entao a varredura e barata — e
    # guardar o digest numa coluna criaria um segundo lugar para
    # dessincronizar quando o token for rotacionado.
    for totem in Totem.objects.select_related("empresa", "empresa__cliente"):
        if totem.codigo_autenticidade == codigo:
            encontrado = totem
            break

    return render(request, "totem/autenticidade.html", {
        "totem": encontrado,
        "codigo": codigo,
    })


@login_required
def etiqueta_png(request, pk):
    """
    Etiqueta de patrimonio em PNG, pronta para imprimir e colar.

    Restrita a quem administra a plataforma: a etiqueta carrega o codigo
    de verificacao, e emiti-la para qualquer um permitiria fabricar
    etiquetas de equipamentos que nao existem.
    """
    from apps.core.constants import TipoUsuario
    from apps.totem.etiqueta import gerar

    if request.user.tipo != TipoUsuario.MASTER:
        raise PermissionDenied("Somente a KS TEC emite etiquetas de patrimônio.")

    totem = get_object_or_404(Totem, pk=pk)
    base = f"{request.scheme}://{request.get_host()}"

    resposta = HttpResponse(gerar(totem, base), content_type="image/png")
    resposta["Content-Disposition"] = (
        f'inline; filename="etiqueta-{totem.identificador}.png"'
    )
    return resposta
