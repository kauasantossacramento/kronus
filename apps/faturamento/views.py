"""
Kronus — webhook do gateway e área de assinatura do cliente.

    POST /faturamento/webhook/asaas/   notificações do gateway (público)
    /faturamento/minha-assinatura/     plano atual, faturas, upgrade
    /faturamento/planos/               contratação e troca de plano
    /faturamento/checkout/<slug>/      confirma a contratação

**O webhook é a única rota pública que muda dinheiro.** Ele é protegido
por token no header, não por sessão — e recusa qualquer requisição sem
o token correto antes de olhar o corpo.
"""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.faturamento.models import Assinatura, Cobranca, ConfiguracaoGateway
from apps.faturamento.services import AssinaturaService, WebhookService
from apps.master.models import Plano

logger = logging.getLogger("kronus.faturamento")


# ══════════════════════════════════════════════════════════════
# Webhook
# ══════════════════════════════════════════════════════════════
@csrf_exempt
@require_POST
def webhook_asaas(request):
    """
    Recebe as notificações do ASAAS.

    **Responde 200 depressa e sempre que possível.** O ASAAS reenvia
    enquanto não receber 200, e uma fila de reentregas represa todos os
    eventos seguintes daquela conta. Erro de processamento vira 500 só
    quando reprocessar de fato ajuda; evento desconhecido é aceito e
    arquivado.
    """
    token = request.headers.get("asaas-access-token", "")
    if not WebhookService.token_confere(token):
        # Não dizemos se o token está errado ou se falta configuração:
        # ambos são 401 para quem tenta adivinhar.
        logger.warning(
            "Webhook do ASAAS recusado: token invalido (origem %s).",
            request.META.get("REMOTE_ADDR"),
        )
        return JsonResponse({"erro": "nao autorizado"}, status=401)

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"erro": "payload invalido"}, status=400)

    try:
        registro = WebhookService.registrar(payload)
    except ValueError as erro:
        # Evento que não casa com nenhuma assinatura nossa: aceitar e
        # arquivar. Devolver erro faria o ASAAS reenviar para sempre um
        # evento que nunca vamos conseguir processar.
        logger.warning("Webhook do ASAAS ignorado: %s", erro)
        return JsonResponse({"status": "ignorado", "motivo": str(erro)}, status=200)
    except Exception:
        logger.exception("Falha ao processar webhook do ASAAS.")
        return JsonResponse({"erro": "falha interna"}, status=500)

    return JsonResponse({"status": "ok", "evento": registro.evento})


# ══════════════════════════════════════════════════════════════
# Área do cliente
# ══════════════════════════════════════════════════════════════
def _cliente_do_usuario(request):
    """
    O cliente que o usuário administra.

    Só quem é dono da conta mexe em assinatura: um Admin RH opera o
    ponto, mas contratar plano e trocar de faixa é decisão de quem paga.
    """
    usuario = request.user
    if usuario.tipo == "master":
        return None
    return getattr(usuario, "cliente", None)


@login_required
def minha_assinatura(request):
    """Plano atual, faturas e situação da conta."""
    cliente = _cliente_do_usuario(request)
    if cliente is None:
        messages.error(request, "Seu usuário não administra uma conta de cliente.")
        return redirect("core:home")

    assinatura = getattr(cliente, "assinatura", None)
    cobrancas = (
        Cobranca.objects.filter(assinatura=assinatura).order_by("-vencimento")[:24]
        if assinatura
        else []
    )

    from apps.rh.models import Colaborador

    return render(
        request,
        "faturamento/minha_assinatura.html",
        {
            "titulo": "Minha assinatura",
            "menu_ativo": "assinatura",
            "cliente": cliente,
            "assinatura": assinatura,
            "cobrancas": cobrancas,
            "em_aberto": [c for c in cobrancas if not c.paga and c.status != "cancelada"],
            "colaboradores_ativos": Colaborador.objects.filter(
                empresa__cliente=cliente, ativo=True
            ).count(),
            "empresas_ativas": cliente.empresas.filter(ativo=True).count(),
            "totens_ativos": cliente.total_totens,
        },
    )


@login_required
def planos_disponiveis(request):
    """Vitrine de planos, marcando o atual e o que cada troca implica."""
    cliente = _cliente_do_usuario(request)
    if cliente is None:
        messages.error(request, "Seu usuário não administra uma conta de cliente.")
        return redirect("core:home")

    from apps.rh.models import Colaborador

    em_uso = Colaborador.objects.filter(
        empresa__cliente=cliente, ativo=True
    ).count()
    empresas = cliente.empresas.filter(ativo=True).count()
    assinatura = getattr(cliente, "assinatura", None)

    planos = []
    for plano in Plano.objects.filter(ativo=True).order_by("ordem", "preco_mensal"):
        # O cliente precisa ver *antes* de clicar por que um plano não
        # serve. Descobrir no erro do checkout é a pior hora.
        impedimentos = []
        if plano.max_colaboradores and em_uso > plano.max_colaboradores:
            impedimentos.append(
                f"você tem {em_uso} colaboradores ativos e este plano permite "
                f"{plano.max_colaboradores}"
            )
        if plano.max_empresas and empresas > plano.max_empresas:
            impedimentos.append(
                f"você tem {empresas} empresa(s) e este plano permite "
                f"{plano.max_empresas}"
            )
        planos.append({
            "plano": plano,
            "atual": assinatura is not None and assinatura.plano_id == plano.pk,
            "impedimentos": impedimentos,
            "disponivel": not impedimentos,
        })

    return render(
        request,
        "faturamento/planos.html",
        {
            "titulo": "Planos",
            "menu_ativo": "assinatura",
            "cliente": cliente,
            "assinatura": assinatura,
            "planos": planos,
            "colaboradores_ativos": em_uso,
            "ciclos": Assinatura.Ciclo.choices,
        },
    )


@login_required
def checkout(request, slug):
    """
    Confirmação da contratação.

    Uma tela só, com o valor final e o que muda — e um POST para
    efetivar. Sem carrinho e sem etapas: o cliente já escolheu o plano
    na tela anterior.
    """
    cliente = _cliente_do_usuario(request)
    if cliente is None:
        messages.error(request, "Seu usuário não administra uma conta de cliente.")
        return redirect("core:home")

    plano = get_object_or_404(Plano, slug=slug, ativo=True)
    assinatura = getattr(cliente, "assinatura", None)
    ciclo = request.POST.get("ciclo") or request.GET.get("ciclo") or Assinatura.Ciclo.MENSAL
    if ciclo not in dict(Assinatura.Ciclo.choices):
        ciclo = Assinatura.Ciclo.MENSAL

    valor = AssinaturaService._valor_do_ciclo(plano, ciclo)

    if request.method == "POST" and request.POST.get("acao") == "confirmar":
        forma = request.POST.get("forma_pagamento") or Assinatura.FormaPagamento.INDEFINIDO
        try:
            if assinatura and assinatura.status != Assinatura.Status.CANCELADA:
                AssinaturaService.trocar_plano(
                    assinatura=assinatura, plano=plano, ciclo=ciclo
                )
                acao = "Plano alterado"
            else:
                AssinaturaService.contratar(
                    cliente=cliente, plano=plano, ciclo=ciclo, forma_pagamento=forma
                )
                acao = "Plano contratado"
        except ValueError as erro:
            messages.error(request, str(erro))
            return redirect("faturamento:planos")
        except Exception:
            logger.exception("Falha na contratação do plano %s.", plano.slug)
            messages.error(
                request,
                "Não foi possível concluir a contratação. Tente novamente ou "
                "fale com o suporte.",
            )
            return redirect("faturamento:planos")

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.CONFIG,
            descricao=f"{acao}: {plano.nome} ({ciclo})",
            cliente=cliente,
        )
        messages.success(
            request,
            f"{acao} para {plano.nome}. Acompanhe as faturas em Minha assinatura.",
        )
        return redirect("faturamento:minha_assinatura")

    return render(
        request,
        "faturamento/checkout.html",
        {
            "titulo": f"Contratar {plano.nome}",
            "menu_ativo": "assinatura",
            "cliente": cliente,
            "plano": plano,
            "assinatura": assinatura,
            "ciclo": ciclo,
            "valor": valor,
            "ciclos": Assinatura.Ciclo.choices,
            "formas": Assinatura.FormaPagamento.choices,
            "gateway_ativo": ConfiguracaoGateway.carregar().ativo,
            "dias_de_teste": AssinaturaService.DIAS_DE_TESTE,
        },
    )


@login_required
@require_POST
def cancelar_assinatura(request):
    """Cancelamento pelo próprio cliente."""
    cliente = _cliente_do_usuario(request)
    assinatura = getattr(cliente, "assinatura", None) if cliente else None
    if assinatura is None:
        messages.error(request, "Não há assinatura para cancelar.")
        return redirect("faturamento:minha_assinatura")

    AssinaturaService.cancelar(
        assinatura=assinatura, motivo=request.POST.get("motivo", "")[:255]
    )
    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao="Assinatura cancelada pelo cliente",
        cliente=cliente,
    )
    messages.warning(
        request,
        "Assinatura cancelada. O acesso continua até o fim do período pago, e "
        "seus registros de ponto permanecem disponíveis para download.",
    )
    return redirect("faturamento:minha_assinatura")


@login_required
@require_POST
def contratar_totens(request):
    """
    O cliente contrata ou devolve totens adicionais sozinho.

    Contratar entra em vigor na hora — o totem e liberado imediatamente e
    a diferenca aparece na proxima fatura. Reduzir **nao** desliga totem:
    derrubar o ponto de uma unidade por causa de uma alteracao de plano
    seria pior do que cobrar a maior por um ciclo. A tela avisa e pede que
    o excedente seja desativado antes.
    """
    from apps.faturamento.services import AssinaturaService

    cliente = _cliente_do_usuario(request)
    if cliente is None:
        messages.error(request, "Seu usuário não administra uma conta de cliente.")
        return redirect("core:home")

    assinatura = getattr(cliente, "assinatura", None)
    if assinatura is None or not assinatura.em_dia:
        messages.error(
            request,
            "É preciso ter uma assinatura ativa para contratar adicionais.",
        )
        return redirect("faturamento:minha_assinatura")

    try:
        quantidade = int(request.POST.get("totens_contratados", 0))
    except (TypeError, ValueError):
        quantidade = assinatura.totens_contratados
    quantidade = max(0, min(50, quantidade))

    em_uso = cliente.total_totens
    minimo = max(0, em_uso - (assinatura.plano.max_totems or 0))
    if quantidade < minimo:
        messages.error(
            request,
            f"Você usa {em_uso} totem(ns). Desative os que não for manter "
            f"antes de reduzir para {quantidade}.",
        )
        return redirect("faturamento:minha_assinatura")

    anterior = assinatura.totens_contratados
    assinatura.totens_contratados = quantidade
    assinatura.save(update_fields=["totens_contratados", "updated_at"])

    # Sem isto a proxima fatura sai pelo valor antigo.
    if assinatura.asaas_subscription_id:
        try:
            AssinaturaService.sincronizar_no_gateway(assinatura)
        except Exception:
            logger.exception(
                "Falha ao sincronizar adicionais da assinatura %s", assinatura.pk
            )
            messages.warning(
                request,
                "Os totens foram liberados, mas não conseguimos atualizar a "
                "cobrança agora. Nossa equipe ajusta a próxima fatura.",
            )

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.EDICAO,
        descricao=f"Totens adicionais: {anterior} -> {quantidade}",
        objeto=assinatura,
    )

    if quantidade > anterior:
        messages.success(
            request,
            f"{quantidade - anterior} totem(ns) liberado(s). Você já pode "
            "cadastrá-los; a diferença entra na próxima fatura.",
        )
    elif quantidade < anterior:
        messages.success(
            request,
            f"Adicionais reduzidos para {quantidade}. O novo valor vale a "
            "partir da próxima fatura.",
        )
    else:
        messages.info(request, "Nada mudou.")
    return redirect("faturamento:minha_assinatura")
