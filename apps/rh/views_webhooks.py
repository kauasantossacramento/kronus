"""
Kronus — gestão de webhooks pelo Admin RH (Seção 8.8).

    /rh/configuracoes/webhooks/                lista, cadastro
    /rh/configuracoes/webhooks/<pk>/           entregas recentes
    /rh/configuracoes/webhooks/<pk>/testar/    entrega de teste
    /rh/configuracoes/webhooks/<pk>/reativar/  volta a ativar após falhas

**Por que o histórico de entregas é a tela principal do detalhe.** Quando
uma integração "não recebeu o evento", a pergunta é sempre a mesma: o
Kronus tentou? quando? o que o outro lado respondeu? Sem essa tela, a
resposta viraria um chamado de suporte e uma consulta ao banco. Com ela,
o próprio cliente vê o `500` que o servidor dele devolveu.
"""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.core.utils import gerar_token
from apps.notificacoes.models import EntregaWebhook, Webhook

logger = logging.getLogger("kronus.webhooks")


@rh_required
@empresa_ativa_required
def webhooks(request):
    """Lista e cadastro. O segredo é gerado aqui, nunca digitado."""
    empresa = request.empresa_ativa

    if not empresa.cliente.pode_integrar:
        messages.error(
            request,
            "Os webhooks não estão habilitados para esta conta. Fale com a KS TEC.",
        )
        return redirect("rh:configuracoes")

    plano = empresa.cliente.plano
    lista = Webhook.objects.filter(empresa=empresa).order_by("nome")

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "criar":
            if not plano.tem_webhook:
                messages.error(
                    request,
                    f"O plano {plano} não inclui webhooks. Fale com a KS TEC.",
                )
                return redirect("rh:webhooks")

            nome = (request.POST.get("nome") or "").strip()
            url = (request.POST.get("url") or "").strip()
            eventos = request.POST.getlist("eventos")

            if not nome or not url:
                messages.error(request, "Informe nome e URL de destino.")
                return redirect("rh:webhooks")

            if not url.startswith("https://"):
                # HTTP simples exporia CPF e marcações em trânsito. O
                # payload carrega dado pessoal — não há caso de uso que
                # justifique entregá-lo em claro.
                messages.error(
                    request,
                    "A URL precisa ser HTTPS: o payload carrega dados pessoais.",
                )
                return redirect("rh:webhooks")

            if not eventos:
                messages.error(request, "Selecione ao menos um evento.")
                return redirect("rh:webhooks")

            webhook = Webhook.objects.create(
                empresa=empresa,
                nome=nome,
                url=url,
                eventos=eventos,
                segredo=gerar_token(24),
            )
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.CRIACAO,
                descricao=f"Webhook criado: {nome} → {url}",
                objeto=webhook,
                empresa=empresa,
            )
            messages.success(
                request,
                "Webhook criado. Guarde o segredo — é ele que valida a assinatura.",
            )
            return redirect("rh:webhook_detalhe", pk=webhook.pk)

        if acao == "excluir":
            webhook = get_object_or_404(
                Webhook, pk=request.POST.get("webhook"), empresa=empresa
            )
            nome = webhook.nome
            webhook.delete()
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.EXCLUSAO,
                descricao=f"Webhook excluído: {nome}",
                empresa=empresa,
            )
            messages.warning(request, f"Webhook '{nome}' removido.")
            return redirect("rh:webhooks")

    return render(
        request,
        "rh/configuracoes/webhooks.html",
        {
            "titulo": "Webhooks",
            "menu_ativo": "configuracoes",
            "empresa": empresa,
            "webhooks": lista,
            "eventos_disponiveis": Webhook.Evento.choices,
            "plano_tem_webhook": plano.tem_webhook,
        },
    )


@rh_required
@empresa_ativa_required
def webhook_detalhe(request, pk):
    """Configuração, segredo e as últimas 50 entregas."""
    empresa = request.empresa_ativa
    webhook = get_object_or_404(
        Webhook.objects.select_related("empresa"), pk=pk, empresa=empresa
    )

    if request.method == "POST" and request.POST.get("acao") == "salvar":
        url = (request.POST.get("url") or "").strip()
        eventos = request.POST.getlist("eventos")

        if url and not url.startswith("https://"):
            messages.error(request, "A URL precisa ser HTTPS.")
            return redirect("rh:webhook_detalhe", pk=pk)

        webhook.nome = (request.POST.get("nome") or webhook.nome).strip()
        webhook.url = url or webhook.url
        webhook.eventos = eventos
        webhook.ativo = request.POST.get("ativo") == "on"
        if webhook.ativo:
            # Reativar zera o contador: senão a próxima falha isolada
            # desativaria o webhook de novo imediatamente.
            webhook.falhas_consecutivas = 0
        webhook.save()

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.ALTERACAO,
            descricao=f"Webhook atualizado: {webhook.nome}",
            objeto=webhook,
            empresa=empresa,
        )
        messages.success(request, "Webhook atualizado.")
        return redirect("rh:webhook_detalhe", pk=pk)

    entregas = (
        EntregaWebhook.objects.filter(webhook=webhook)
        .order_by("-created_at")[:50]
    )

    return render(
        request,
        "rh/configuracoes/webhook_detalhe.html",
        {
            "titulo": webhook.nome,
            "menu_ativo": "configuracoes",
            "empresa": empresa,
            "webhook": webhook,
            "entregas": entregas,
            "eventos_disponiveis": Webhook.Evento.choices,
            "eventos_assinados": webhook.eventos or [],
        },
    )


@rh_required
@empresa_ativa_required
@require_POST
def webhook_testar(request, pk):
    """
    Envia uma entrega de teste pelo caminho real, com assinatura.

    Roda **de forma síncrona**: o operador clicou e está olhando para a
    tela esperando a resposta. Mandar para a fila e dizer "enviado"
    esconderia justamente o erro que ele veio investigar.
    """
    empresa = request.empresa_ativa
    webhook = get_object_or_404(Webhook, pk=pk, empresa=empresa)

    from apps.notificacoes.tasks import testar_webhook

    sucesso = testar_webhook(webhook.pk)
    webhook.refresh_from_db()

    if sucesso:
        messages.success(
            request,
            f"Entrega de teste aceita pelo destino (HTTP {webhook.ultimo_status}).",
        )
    else:
        ultima = (
            EntregaWebhook.objects.filter(webhook=webhook, evento="webhook.teste")
            .order_by("-created_at")
            .first()
        )
        detalhe = (ultima.resposta if ultima else "") or "sem resposta"
        messages.error(
            request,
            f"O destino recusou a entrega de teste: {detalhe[:200]}",
        )

    return redirect("rh:webhook_detalhe", pk=pk)


@rh_required
@empresa_ativa_required
@require_POST
def webhook_reenviar(request, pk, entrega_pk):
    """Reenvia uma entrega específica que falhou."""
    empresa = request.empresa_ativa
    webhook = get_object_or_404(Webhook, pk=pk, empresa=empresa)
    entrega = get_object_or_404(EntregaWebhook, pk=entrega_pk, webhook=webhook)

    from apps.notificacoes.webhooks import executar

    # O reenvio zera o contador de tentativas para que o backoff volte
    # ao início: se o cliente acabou de corrigir o endpoint, não faz
    # sentido a próxima retentativa automática esperar dez horas.
    entrega.tentativas = 0
    entrega.status = EntregaWebhook.Status.PENDENTE
    entrega.save(update_fields=["tentativas", "status", "updated_at"])

    sucesso = executar(entrega)
    if sucesso:
        messages.success(request, "Entrega reenviada e aceita pelo destino.")
    else:
        messages.error(
            request, f"O reenvio falhou: {entrega.resposta[:200] or 'sem resposta'}"
        )
    return redirect("rh:webhook_detalhe", pk=pk)
