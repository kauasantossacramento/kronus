"""Kronus — tarefas assíncronas dos equipamentos de totem."""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("kronus.totem")


@shared_task(name="apps.totem.tasks.monitorar_totens_offline")
def monitorar_totens_offline():
    """
    Detecta totens sem heartbeat e notifica RH e Master.

    Seção 8.7 do plano: alerta quando o equipamento passa de 10 minutos
    sem sinal. Roda a cada 5 minutos e só notifica na **transição** para
    offline — repetir o alerta a cada ciclo treinaria o RH a ignorá-lo.
    """
    from apps.notificacoes.services import notificar_totem_offline
    from apps.totem.models import EventoTotem, Totem

    limite = timezone.now() - timezone.timedelta(minutes=Totem.MINUTOS_PARA_OFFLINE)
    novos_offline = []

    for totem in Totem.objects.filter(ativo=True).select_related("empresa"):
        esta_offline = totem.ultimo_heartbeat is None or totem.ultimo_heartbeat < limite

        ultimo_evento = (
            EventoTotem.objects.filter(
                totem=totem,
                tipo__in=[EventoTotem.Tipo.OFFLINE, EventoTotem.Tipo.ONLINE],
            )
            .order_by("-created_at")
            .values_list("tipo", flat=True)
            .first()
        )
        ja_sinalizado = ultimo_evento == EventoTotem.Tipo.OFFLINE

        if esta_offline and not ja_sinalizado:
            EventoTotem.objects.create(
                totem=totem,
                tipo=EventoTotem.Tipo.OFFLINE,
                detalhes=(
                    f"Sem heartbeat desde {totem.ultimo_heartbeat:%d/%m/%Y %H:%M}"
                    if totem.ultimo_heartbeat
                    else "Nunca conectou"
                ),
            )
            novos_offline.append(totem)
            try:
                notificar_totem_offline(totem)
            except Exception:
                logger.exception("Falha ao notificar totem offline %s", totem.pk)

        elif not esta_offline and ja_sinalizado:
            EventoTotem.objects.create(
                totem=totem, tipo=EventoTotem.Tipo.ONLINE, detalhes="Conexão restabelecida"
            )

    if novos_offline:
        logger.warning(
            "Totens que ficaram offline: %s",
            ", ".join(t.identificador for t in novos_offline),
        )
    return {"novos_offline": [t.identificador for t in novos_offline]}


@shared_task(name="apps.totem.tasks.limpar_eventos_antigos")
def limpar_eventos_antigos(dias: int = 90):
    """O diário de bordo do equipamento não precisa de histórico infinito."""
    from apps.totem.models import EventoTotem

    limite = timezone.now() - timezone.timedelta(days=dias)
    removidos, _ = EventoTotem.all_objects.filter(created_at__lt=limite).delete()
    return {"eventos_removidos": removidos}
