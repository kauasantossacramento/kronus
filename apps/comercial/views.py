"""
Kronus — solicitacao publica de demonstracao.

Endpoint publico que cria ambiente e usuario. Trata-se de escrita no
banco disparada por anonimo, entao os limites nao sao detalhe: sem eles,
um laco simples cria mil clientes e enche o disco da VPS.
"""
import logging

from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.comercial.forms import FormularioDemonstracao
from apps.comercial.models import ConfiguracaoComercial, SolicitacaoDemonstracao
from apps.comercial.services import criar_demonstracao

logger = logging.getLogger("kronus.comercial")

LIMITE_POR_IP = 3
JANELA_SEGUNDOS = 60 * 60 * 6


def _ip(request) -> str:
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _excedeu_limite_do_ip(request) -> bool:
    chave = f"demo:ip:{_ip(request)}"
    tentativas = cache.get(chave, 0) + 1
    cache.set(chave, tentativas, JANELA_SEGUNDOS)
    return tentativas > LIMITE_POR_IP


def _excedeu_limite_do_dia(config) -> bool:
    hoje = timezone.localdate()
    return SolicitacaoDemonstracao.objects.filter(
        created_at__date=hoje
    ).count() >= config.demo_limite_diario


@require_http_methods(["POST"])
def solicitar(request):
    """Recebe o formulario da capa e devolve o ambiente pronto."""
    config = ConfiguracaoComercial.carregar()

    if not config.demo_ativa:
        return _falha(request, config,
                      "A demonstração automática está temporariamente "
                      "indisponível. Fale com a gente pelo WhatsApp.")

    formulario = FormularioDemonstracao(request.POST, request.FILES)
    if not formulario.is_valid():
        return _falha(request, config, formulario=formulario)

    if _excedeu_limite_do_ip(request):
        logger.warning("Limite de demonstracoes por IP atingido: %s", _ip(request))
        return _falha(request, config,
                      "Já criamos demonstrações demais a partir daqui. "
                      "Fale com a gente pelo WhatsApp.")

    if _excedeu_limite_do_dia(config):
        return _falha(request, config,
                      "O limite de demonstrações de hoje foi atingido. "
                      "Fale com a gente pelo WhatsApp.")

    solicitacao = formulario.save(commit=False)
    solicitacao.token = SolicitacaoDemonstracao.novo_token()
    solicitacao.expira_em = timezone.now()  # ajustado em criar_demonstracao
    solicitacao.ip = _ip(request) or None
    solicitacao.user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]
    solicitacao.save()

    try:
        solicitacao, senha = criar_demonstracao(
            solicitacao, config, logo=formulario.cleaned_data.get("logo")
        )
    except Exception:
        logger.exception("Falha ao criar ambiente de demonstracao")
        solicitacao.status = SolicitacaoDemonstracao.Status.CANCELADA
        solicitacao.save(update_fields=["status", "updated_at"])
        return _falha(request, config,
                      "Não conseguimos preparar o ambiente agora. "
                      "Fale com a gente pelo WhatsApp que resolvemos na hora.")

    _enviar_email(request, solicitacao, senha)

    return render(request, "comercial/pronta.html", {
        "solicitacao": solicitacao,
        "senha": senha,
        "config": config,
        "url_acesso": request.build_absolute_uri(
            f"/{solicitacao.cliente.empresas.first().slug}/"
        ),
    })


def _falha(request, config, mensagem="", formulario=None):
    """Devolve a capa com o formulario preenchido e o erro visivel."""
    from apps.landing.views import contexto_da_capa

    contexto = contexto_da_capa()
    contexto["formulario_demo"] = formulario or FormularioDemonstracao(
        request.POST, request.FILES
    )
    contexto["erro_demo"] = mensagem
    contexto["config_comercial"] = config
    resposta = render(request, "landing/index.html", contexto)
    resposta.status_code = 400 if formulario else 429
    return resposta


def _enviar_email(request, solicitacao, senha) -> None:
    """
    Manda as credenciais. Falha aqui nao derruba a criacao: a tela ja
    mostra o acesso, e perder o ambiente por causa de um SMTP fora do ar
    seria trocar um problema pequeno por um grande.
    """
    from django.conf import settings
    from django.core.mail import send_mail
    from django.template.loader import render_to_string

    empresa = solicitacao.cliente.empresas.first()
    contexto = {
        "solicitacao": solicitacao,
        "senha": senha,
        "url_acesso": request.build_absolute_uri(f"/{empresa.slug}/"),
        "expira_em": solicitacao.expira_em,
    }
    try:
        send_mail(
            subject="Sua demonstração do Kronus está pronta",
            message=render_to_string("comercial/email_demo.txt", contexto),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[solicitacao.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Falha ao enviar e-mail da demonstracao %s", solicitacao.pk)


def expirada(request):
    """Pagina mostrada quando a demonstracao acabou."""
    return render(request, "comercial/expirada.html", {
        "config": ConfiguracaoComercial.carregar(),
    })
