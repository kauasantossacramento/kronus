"""
Kronus — sinais do RH que alimentam webhooks (Seção 8.8).

**Por que sinais aqui e chamadas explícitas no ponto.** No `RegistroPonto`
existe um único caminho de criação (`RegistroPontoService.registrar`), e
chamar o webhook lá deixa o disparo visível ao lado da regra. Já um
`Colaborador` nasce de vários lugares — formulário do RH, importação de
CSV, seed, shell — e nenhum deles é "o" caminho. Amarrar o evento ao
`post_save` garante que nenhum desses caminhos esqueça de avisar o ERP
do cliente que entrou gente nova.

O desligamento é detectado por transição: `ativo` era `True` e passou a
`False`, ou `data_demissao` deixou de ser nula. Comparar com o estado
anterior evita disparar `colaborador.desligado` toda vez que alguém
salva um colaborador que já estava desligado.
"""
import logging

from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

logger = logging.getLogger("kronus.rh")


def _disparar(evento, empresa, objeto):
    """Guard: falha de webhook nunca derruba um cadastro."""
    try:
        from apps.notificacoes.webhooks import disparar

        disparar(evento, empresa, objeto)
    except Exception:
        logger.exception("Falha ao enfileirar webhooks do evento %s.", evento)


@receiver(post_init, sender="rh.Colaborador")
def _guardar_estado_anterior(sender, instance, **kwargs):
    """Memoriza o estado carregado do banco, para detectar a transição."""
    instance._ativo_anterior = instance.ativo
    instance._demissao_anterior = instance.data_demissao


@receiver(post_save, sender="rh.Colaborador")
def colaborador_salvo(sender, instance, created, **kwargs):
    if created:
        _disparar("colaborador.criado", instance.empresa, instance)
        return

    # `post_init` não roda em instâncias construídas na memória sem
    # carga do banco; nesse caso não há transição a detectar.
    ativo_antes = getattr(instance, "_ativo_anterior", instance.ativo)
    demissao_antes = getattr(instance, "_demissao_anterior", instance.data_demissao)

    virou_inativo = ativo_antes and not instance.ativo
    ganhou_demissao = demissao_antes is None and instance.data_demissao is not None

    if virou_inativo or ganhou_demissao:
        _disparar("colaborador.desligado", instance.empresa, instance)

    # Reancora o estado: um segundo save na mesma instância não deve
    # redisparar o evento.
    instance._ativo_anterior = instance.ativo
    instance._demissao_anterior = instance.data_demissao


@receiver(post_save, sender="rh.Atestado")
def atestado_salvo(sender, instance, created, **kwargs):
    """
    Dispara `atestado.aprovado` quando o RH aprova.

    Detectado pelo status atual em vez de por transição: `Atestado.aprovar`
    grava com `update_fields`, e a mesma aprovação não é repetida — quem
    já está aprovado não passa por `aprovar()` de novo.
    """
    from apps.core.constants import StatusAprovacao

    if created or instance.status != StatusAprovacao.APROVADO:
        return

    if getattr(instance, "_atestado_ja_notificado", False):
        return
    instance._atestado_ja_notificado = True

    _disparar("atestado.aprovado", instance.empresa, instance)
