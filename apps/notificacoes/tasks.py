"""
Kronus — jobs assíncronos de notificação e webhook.

Três tarefas, todas referenciadas no `beat_schedule` de `config/celery.py`
ou disparadas por `webhooks.disparar()`:

    entregar_webhook              uma entrega (chamada pelo on_commit)
    reprocessar_entregas_pendentes  varredura de retentativas vencidas
    notificar_esquecimento_ponto    Seção 8.7 — jornada aberta ao fim do dia

`reprocessar_entregas_pendentes` é a rede de segurança do sistema de
webhooks: se o broker estava fora do ar no `on_commit`, ou se o worker
morreu no meio de uma entrega, a entrega continua no banco marcada como
pendente e esta varredura a recupera. Sem ela, um Redis reiniciado
perderia eventos silenciosamente.
"""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("kronus.webhooks")


@shared_task(name="apps.notificacoes.tasks.entregar_webhook", ignore_result=True)
def entregar_webhook(entrega_pk):
    """Executa uma entrega. O agendamento da retentativa fica em `webhooks.executar`."""
    from apps.notificacoes.models import EntregaWebhook
    from apps.notificacoes.webhooks import executar

    entrega = (
        EntregaWebhook.objects.select_related("webhook", "empresa")
        .filter(pk=entrega_pk)
        .first()
    )
    if entrega is None:
        logger.warning("Entrega %s não encontrada.", entrega_pk)
        return None

    if entrega.status == EntregaWebhook.Status.ENTREGUE:
        # Reentrância: a mesma entrega pode ser enfileirada duas vezes
        # (on_commit + varredura). Entregar de novo duplicaria o evento
        # no cliente.
        return True

    return executar(entrega)


@shared_task(
    name="apps.notificacoes.tasks.reprocessar_entregas_pendentes", ignore_result=True
)
def reprocessar_entregas_pendentes(limite=200):
    """Reenfileira entregas cuja retentativa já venceu."""
    from apps.notificacoes.models import EntregaWebhook

    vencidas = EntregaWebhook.objects.filter(
        status=EntregaWebhook.Status.PENDENTE,
        proxima_tentativa__lte=timezone.now(),
    ).order_by("proxima_tentativa")[:limite]

    total = 0
    for entrega in vencidas:
        entregar_webhook.delay(entrega.pk)
        total += 1

    # Entregas que nunca foram agendadas (broker fora do ar no commit):
    # `proxima_tentativa` nula e zero tentativas.
    orfas = EntregaWebhook.objects.filter(
        status=EntregaWebhook.Status.PENDENTE,
        proxima_tentativa__isnull=True,
        tentativas=0,
        created_at__lte=timezone.now() - timezone.timedelta(minutes=5),
    ).order_by("created_at")[:limite]

    for entrega in orfas:
        entregar_webhook.delay(entrega.pk)
        total += 1

    if total:
        logger.info("Reprocessadas %s entregas de webhook.", total)
    return total


@shared_task(
    name="apps.notificacoes.tasks.notificar_esquecimento_ponto", ignore_result=True
)
def notificar_esquecimento_ponto():
    """
    Seção 8.7 — avisa quem tem jornada aberta no fim do dia.

    Roda às 20h. Notifica o colaborador que bateu entrada e não bateu
    saída: o esquecimento corrigido no mesmo dia evita um ajuste
    manual depois, que é mais caro para o RH e mais frágil na auditoria.
    """
    from apps.notificacoes.models import Notificacao
    from apps.notificacoes.services import criar
    from apps.ponto.models import RegistroPonto
    from apps.rh.models import Colaborador

    hoje = timezone.localdate()
    inicio = timezone.make_aware(
        timezone.datetime.combine(hoje, timezone.datetime.min.time())
    )
    fim = inicio + timezone.timedelta(days=1)

    marcacoes = (
        RegistroPonto.objects.filter(
            data_hora__gte=inicio, data_hora__lt=fim, cancelado=False
        )
        .values_list("colaborador_id", flat=True)
    )

    contagem = {}
    for colaborador_id in marcacoes:
        contagem[colaborador_id] = contagem.get(colaborador_id, 0) + 1

    # Número ímpar de marcações = jornada aberta. O pareamento é
    # posicional (ver ponto/calculators.py), então a paridade é o
    # critério certo, não o `tipo` declarado.
    abertos = [pk for pk, total in contagem.items() if total % 2 == 1]
    if not abertos:
        return 0

    criadas = 0
    for colaborador in Colaborador.objects.filter(pk__in=abertos, ativo=True).select_related(
        "empresa", "empresa__config", "user"
    ):
        if colaborador.user_id is None:
            continue

        # A empresa decide se este aviso sai — e por qual canal. Ignorar
        # a configuracao faria o Kronus mandar e-mail que o cliente
        # desligou de proposito.
        config = getattr(colaborador.empresa, "config", None)
        if config is not None and not config.notif_esq_ponto:
            continue

        criar(
            destinatario=colaborador.user,
            empresa=colaborador.empresa,
            evento=Notificacao.Evento.ESQUECIMENTO_PONTO,
            nivel=Notificacao.Nivel.ALERTA,
            canal=Notificacao.Canal.AMBOS,
            titulo="Jornada em aberto hoje",
            mensagem=(
                "Consta uma entrada sem a saída correspondente em "
                f"{hoje:%d/%m/%Y}. Registre a saída ou solicite ajuste ao RH."
            ),
            url_acao=f"/ponto/meus-pontos/?data={hoje:%Y-%m-%d}",
        )
        criadas += 1

    logger.info("Esquecimento de ponto: %s notificações criadas.", criadas)
    return criadas


@shared_task(name="apps.notificacoes.tasks.testar_webhook", ignore_result=False)
def testar_webhook(webhook_pk):
    """
    Entrega de teste disparada pelo botão "Testar" da tela de webhooks.

    Usa o mesmo caminho da entrega real — inclusive assinatura — porque
    um teste que não exercita a assinatura não prova que a integração
    funciona.
    """
    from apps.notificacoes.models import EntregaWebhook, Webhook
    from apps.notificacoes.webhooks import executar, montar_payload
    import uuid as _uuid

    webhook = Webhook.objects.select_related("empresa").filter(pk=webhook_pk).first()
    if webhook is None:
        return False

    payload = montar_payload(
        "webhook.teste",
        webhook.empresa,
        {"mensagem": "Entrega de teste emitida pelo painel do Kronus."},
    )
    entrega = EntregaWebhook.objects.create(
        webhook=webhook,
        empresa=webhook.empresa,
        evento="webhook.teste",
        identificador=_uuid.uuid4(),
        payload=payload,
    )
    return executar(entrega)


def disparar_apos_commit(evento, empresa, objeto):
    """
    Atalho seguro para uso nos services de domínio.

    Envolve `webhooks.disparar` num guard: um erro ao montar o payload
    de um webhook **nunca** pode derrubar o registro de ponto que o
    originou. O ponto é a obrigação legal; o webhook é conveniência.
    """
    from apps.notificacoes.webhooks import disparar

    try:
        with transaction.atomic():
            return disparar(evento, empresa, objeto)
    except Exception:
        logger.exception("Falha ao preparar webhooks do evento %s.", evento)
        return []
