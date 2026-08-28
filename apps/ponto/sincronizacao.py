"""
Kronus — recepcao das marcacoes que o totem registrou sem conexao.

Anexo IX, requisitos 4 e 5: a marcacao deve vir de coletor on-line,
podendo **excepcionalmente** estar off-line — e, nesse caso, ser enviada
assim que a conexao voltar.

Tres decisoes que valem explicacao:

**Idempotencia pelo banco, nao pelo codigo.** Cada marcacao carrega um
identificador gerado pelo coletor, com restricao de unicidade na tabela.
Se a resposta se perder na volta, o totem reenvia — e o banco recusa a
duplicata, em vez de o servico "verificar antes de inserir", que perde a
corrida quando dois envios chegam juntos.

**O horario e o do coletor; o da gravacao e o nosso.** O AFD tem os dois
campos separados justamente porque eles diferem quando ha fila. Usar a
hora da chegada como hora da marcacao seria registrar que a pessoa bateu
o ponto no momento em que a internet voltou.

**Relogio do coletor nao merece fe cega.** Um tablet com a data errada
mandaria batidas em 2019. A janela aceita e generosa — a fila pode ficar
dias parada — mas finita, e o que cai fora e recusado com motivo, nao
silenciosamente descartado.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger("kronus.ponto")

#: Quanto para tras a fila pode estar. Uma semana cobre feriado
#: prolongado com o link caido; alem disso, e mais provavel ser relogio
#: errado do que fila legitima.
JANELA_PASSADO = timedelta(days=7)

#: Tolerancia para a frente, so para folga de relogio. Marcacao no futuro
#: nao existe.
JANELA_FUTURO = timedelta(minutes=10)


class ResultadoSincronizacao:
    """O que aconteceu com cada item enviado."""

    ACEITA = "aceita"
    DUPLICADA = "duplicada"
    RECUSADA = "recusada"


def sincronizar(totem, itens: list[dict]) -> dict:
    """
    Grava as marcacoes da fila do totem.

    Devolve o destino de **cada** item, pelo identificador que o coletor
    enviou. O totem so apaga da fila o que voltar como `aceita` ou
    `duplicada`; o que for `recusada` fica para o operador ver, porque
    apagar em silencio uma batida recusada perde o registro de trabalho
    de alguem.
    """
    from apps.core.constants import MetodoRegistro, TipoRegistro
    from apps.ponto.models import RegistroPonto
    from apps.ponto.services import RegistroPontoService
    from apps.rh.models import Colaborador

    agora = timezone.now()
    empresas = set(totem.empresas_atendidas().values_list("pk", flat=True))
    resultados = {}

    for item in itens:
        identificador = (item.get("uuid") or "").strip()[:36]
        if not identificador:
            continue

        # Ja gravada num envio anterior cuja resposta se perdeu.
        if RegistroPonto.objects.filter(uuid_offline=identificador).exists():
            resultados[identificador] = {
                "situacao": ResultadoSincronizacao.DUPLICADA,
                "motivo": "Já registrada.",
            }
            continue

        momento = _ler_momento(item.get("momento"))
        if momento is None:
            resultados[identificador] = _recusa("Data e hora ilegíveis.")
            continue
        if momento > agora + JANELA_FUTURO:
            resultados[identificador] = _recusa(
                "Marcação no futuro — verifique o relógio do equipamento."
            )
            continue
        if momento < agora - JANELA_PASSADO:
            resultados[identificador] = _recusa(
                "Marcação antiga demais para envio automático."
            )
            continue

        colaborador = Colaborador.objects.filter(
            pk=item.get("colaborador_id"),
            empresa_id__in=empresas,
            ativo=True,
            deleted_at__isnull=True,
        ).select_related("empresa", "escala").first()
        if colaborador is None:
            resultados[identificador] = _recusa(
                "Colaborador não encontrado ou não autorizado neste equipamento."
            )
            continue

        tipo = item.get("tipo")
        if tipo not in dict(TipoRegistro.choices):
            tipo = None  # o servico decide qual e a proxima batida

        try:
            with transaction.atomic():
                registro = RegistroPontoService.registrar(
                    colaborador=colaborador,
                    metodo=MetodoRegistro.CPF,
                    tipo=tipo,
                    momento=momento,
                    totem=totem,
                    observacao="Registrada sem conexão",
                    # A fila e enviada em bloco quando a conexao volta; o
                    # intervalo minimo existe para conter duplo toque de
                    # gente, e recusaria batidas legitimas aqui.
                    validar_intervalo=False,
                )
                RegistroPonto.objects.filter(pk=registro.pk).update(
                    registrado_offline=True, uuid_offline=identificador
                )
        except IntegrityError:
            # Outro envio simultaneo ganhou a corrida — o que confirma
            # que a batida esta gravada.
            resultados[identificador] = {
                "situacao": ResultadoSincronizacao.DUPLICADA,
                "motivo": "Já registrada.",
            }
            continue
        except Exception as erro:
            logger.warning(
                "Marcacao offline recusada (totem %s): %s", totem.pk, erro
            )
            resultados[identificador] = _recusa(str(erro))
            continue

        resultados[identificador] = {
            "situacao": ResultadoSincronizacao.ACEITA,
            "nsr": registro.nsr,
            "momento": momento.isoformat(),
        }

    aceitas = sum(
        1 for r in resultados.values()
        if r["situacao"] == ResultadoSincronizacao.ACEITA
    )
    if aceitas:
        logger.info(
            "Totem %s sincronizou %s marcacao(oes) offline.", totem.pk, aceitas
        )
    return resultados


def _recusa(motivo: str) -> dict:
    return {"situacao": ResultadoSincronizacao.RECUSADA, "motivo": motivo}


def _ler_momento(valor):
    """
    Converte o carimbo enviado pelo coletor.

    Aceita ISO 8601 com ou sem fuso. Sem fuso, assume o do servidor — o
    coletor e um tablet parado dentro da empresa, no mesmo fuso dela.
    """
    from django.utils.dateparse import parse_datetime

    if not valor:
        return None
    momento = parse_datetime(str(valor))
    if momento is None:
        return None
    if timezone.is_naive(momento):
        momento = timezone.make_aware(momento)
    return momento
