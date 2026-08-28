"""
Kronus — serviços de registro de ponto e consolidação de jornada.

`RegistroPontoService` é o **único** caminho para criar uma batida.
Ele concentra as garantias da Portaria 671/2021:

    * NSR sequencial por empresa, sem lacunas nem repetições (regra 2)
    * hash SHA-256 encadeado ao registro anterior (regra 3)
    * imutabilidade — correções passam por `AjustePontoService` (regra 1)

`ConsolidacaoService` recalcula o banco de horas a partir das marcações.
"""
import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.constants import MetodoRegistro, StatusDia
from apps.core.utils import gerar_hash_registro, obter_ip, obter_user_agent
from apps.ponto import validators
from apps.ponto.calculators import (
    CalculadoraBancoHoras,
    CalculadoraJornada,
    proximo_tipo_esperado,
)
from apps.ponto.models import AjustePonto, BancoHoras, RegistroPonto

logger = logging.getLogger("kronus.ponto")

# ══════════════════════════════════════════════════════════════
# Hora Legal Brasileira
# ══════════════════════════════════════════════════════════════
# O Anexo IX da Portaria 671/2021, requisito 2, exige que o REP-P
# "possua ou acesse relogio que mantenha sincronismo com a Hora Legal
# Brasileira (HLB) disseminada pelo Observatorio Nacional (ON), com uma
# variacao de no maximo 30 segundos".
#
# Quem carimba a marcacao e o relogio do **servidor**, nunca o do
# tablet: o horario do aparelho e adulteravel e nao tem procedencia.
# O servidor sincroniza via systemd-timesyncd com os servidores
# estrato 1 do NTP.br (a.st1.ntp.br e seguintes), que sao ligados
# diretamente aos relogios atomicos do ON.
#
# A configuracao vive em /etc/systemd/timesyncd.conf.d/hlb.conf no
# servidor. Trocar a fonte para um NTP generico ainda daria precisao,
# mas responder "sincronizado com a Ubuntu" a uma fiscalizacao e pior
# do que responder "sincronizado com o Observatorio Nacional".


class RegistroPontoService:
    """Criação de batidas de ponto."""

    # ══════════════════════════════════════════════════════════
    # Consultas de apoio
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def registros_do_dia(colaborador, dia: date = None):
        """Marcações válidas do colaborador no dia, em ordem cronológica."""
        dia = dia or timezone.localdate()
        return list(
            RegistroPonto.objects.filter(
                colaborador=colaborador, cancelado=False, deleted_at__isnull=True
            )
            .filter(data_hora__date=dia)
            .order_by("data_hora", "nsr")
        )

    @classmethod
    def proximo_tipo(cls, colaborador, dia: date = None) -> str:
        """Qual batida o colaborador deve registrar agora (Seção 6.3)."""
        escala = colaborador.escala
        exige_intervalo = escala.exige_intervalo if escala else True
        return proximo_tipo_esperado(
            cls.registros_do_dia(colaborador, dia), exige_intervalo=exige_intervalo
        )

    # ══════════════════════════════════════════════════════════
    # Registro
    # ══════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def registrar(
        cls,
        *,
        colaborador,
        metodo: str = MetodoRegistro.WEB,
        tipo: str = None,
        momento=None,
        latitude=None,
        longitude=None,
        precisao_gps=None,
        request=None,
        totem=None,
        foto_momento=None,
        confianca_face=None,
        registrado_por=None,
        observacao: str = "",
        validar_intervalo: bool = True,
    ) -> RegistroPonto:
        """
        Cria uma batida de ponto.

        Levanta `validators.RegistroInvalido` quando alguma regra de
        negócio impede o registro. Toda a operação roda em uma
        transação: ou o NSR é consumido e o registro nasce, ou nada
        acontece — o que preserva a sequência exigida pela Portaria 671.
        """
        from apps.clientes.models import Empresa

        momento = momento or timezone.now()
        empresa_id = colaborador.empresa_id

        # -- validações prévias --------------------------------
        validators.validar_data_hora(momento)
        validators.validar_colaborador_apto(colaborador)
        validators.validar_empresa_operacional(colaborador.empresa)
        validators.validar_totem_autorizado(totem, colaborador)
        if validar_intervalo:
            validators.validar_intervalo_minimo(colaborador, momento)

        fora_area, _distancia = validators.validar_geofencing(
            colaborador.empresa, latitude, longitude
        )
        suspeita = False
        config = colaborador.empresa.configuracao
        if config.anti_fake_gps:
            suspeita = validators.detectar_gps_suspeito(
                colaborador, latitude, longitude, precisao_gps, momento
            )

        if tipo is None:
            tipo = cls.proximo_tipo(colaborador, timezone.localtime(momento).date())

        # -- trava a empresa para reservar o NSR ---------------
        # `select_for_update` serializa as batidas concorrentes da mesma
        # empresa; sem isso, dois registros simultâneos poderiam receber
        # o mesmo NSR e quebrar o AFD.
        empresa = Empresa.objects.select_for_update().get(pk=empresa_id)
        empresa.nsr_atual += 1
        nsr = empresa.nsr_atual
        empresa.save(update_fields=["nsr_atual"])

        anterior = (
            RegistroPonto.objects.filter(empresa_id=empresa_id)
            .order_by("-nsr")
            .values_list("hash_registro", flat=True)
            .first()
        )

        hash_registro = gerar_hash_registro(
            colaborador_id=colaborador.pk,
            data_hora=momento,
            nsr=nsr,
            salt_empresa=empresa.salt_registro,
            hash_anterior=anterior or "",
        )

        registro = RegistroPonto(
            empresa_id=empresa_id,
            colaborador=colaborador,
            data_hora=momento,
            tipo=tipo,
            metodo=metodo,
            latitude=latitude,
            longitude=longitude,
            precisao_gps=precisao_gps,
            fora_area=fora_area,
            suspeita_fraude=suspeita,
            ip_address=obter_ip(request) if request else None,
            user_agent=obter_user_agent(request) if request else "",
            totem=totem,
            confianca_face=confianca_face,
            nsr=nsr,
            hash_registro=hash_registro,
            hash_anterior=anterior or "",
            registrado_por=registrado_por,
            observacao=observacao[:255],
        )
        if foto_momento is not None:
            registro.foto_momento = foto_momento
        registro.save()

        logger.info(
            "Ponto registrado: colaborador=%s nsr=%s tipo=%s metodo=%s",
            colaborador.pk,
            nsr,
            tipo,
            metodo,
        )

        # A consolidação roda após o commit para não segurar a trava da
        # empresa durante o cálculo do dia.
        dia = timezone.localtime(momento).date()
        transaction.on_commit(
            lambda: ConsolidacaoService.consolidar_dia(colaborador, dia)
        )
        transaction.on_commit(lambda: _publicar_no_painel(registro))
        # Webhook `ponto.registrado` (Secao 8.8). `disparar` ja usa
        # on_commit internamente para o envio; o que roda aqui e so a
        # gravacao da entrega pendente.
        _notificar_integracoes("ponto.registrado", colaborador.empresa, registro)
        return registro

    # ══════════════════════════════════════════════════════════
    # Verificação de integridade
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def verificar_cadeia(empresa, ate_nsr: int = None) -> dict:
        """
        Recalcula a cadeia de hashes da empresa e aponta o primeiro
        registro divergente — a prova de integridade da Portaria 671.
        """
        registros = RegistroPonto.objects.filter(empresa=empresa).order_by("nsr")
        if ate_nsr:
            registros = registros.filter(nsr__lte=ate_nsr)

        anterior = ""
        esperado_nsr = 0
        for registro in registros.iterator():
            esperado_nsr += 1
            if registro.nsr != esperado_nsr:
                return {
                    "integra": False,
                    "motivo": "lacuna_ou_repeticao_de_nsr",
                    "nsr": registro.nsr,
                    "nsr_esperado": esperado_nsr,
                }
            recalculado = gerar_hash_registro(
                colaborador_id=registro.colaborador_id,
                data_hora=registro.data_hora,
                nsr=registro.nsr,
                salt_empresa=empresa.salt_registro,
                hash_anterior=anterior,
            )
            if recalculado != registro.hash_registro:
                return {
                    "integra": False,
                    "motivo": "hash_divergente",
                    "nsr": registro.nsr,
                }
            anterior = registro.hash_registro

        return {"integra": True, "registros_verificados": esperado_nsr}


def _notificar_integracoes(evento, empresa, objeto):
    """
    Enfileira os webhooks do evento sem poder derrubar o registro.

    Um ERP mal configurado do cliente nao pode impedir uma batida de
    ponto: a batida e a obrigacao legal, o webhook e conveniencia. Por
    isso a chamada e envolvida em try/except e nunca propaga.
    """
    try:
        from apps.notificacoes.webhooks import disparar

        disparar(evento, empresa, objeto)
    except Exception:
        logger.exception("Falha ao enfileirar webhooks do evento %s.", evento)


def _publicar_no_painel(registro):
    """
    Espelha a batida no dashboard do RH (Seção 6.6 — tempo real).

    Efeito colateral opcional: se o Channels/Redis estiver fora, o
    registro já está gravado e nada se perde — só o painel deixa de
    atualizar sozinho.
    """
    from apps.totem.consumers import notificar_painel

    momento = timezone.localtime(registro.data_hora)
    notificar_painel(
        registro.empresa,
        {
            "colaborador": registro.colaborador.nome_exibicao,
            "colaborador_id": registro.colaborador_id,
            "tipo": registro.get_tipo_display(),
            "metodo": registro.get_metodo_display(),
            "hora": momento.strftime("%H:%M:%S"),
            "nsr": registro.nsr,
            "fora_area": registro.fora_area,
        },
    )


class AjustePontoService:
    """
    Correções feitas pelo RH.

    Um registro nunca é editado (regra 1 da Seção 14): inclui-se uma
    nova marcação, cancela-se a antiga, ou faz-se as duas coisas. Todos
    os registros permanecem no AFD, com trilha de auditoria.
    """

    @staticmethod
    @transaction.atomic
    def incluir(*, colaborador, data_hora, tipo, justificativa, executado_por, request=None):
        ajuste = AjustePonto.objects.create(
            empresa=colaborador.empresa,
            colaborador=colaborador,
            tipo_ajuste=AjustePonto.TipoAjuste.INCLUSAO,
            data_hora_nova=data_hora,
            tipo_novo=tipo,
            justificativa=justificativa,
            executado_por=executado_por,
            ip=obter_ip(request) if request else None,
        )
        registro = RegistroPontoService.registrar(
            colaborador=colaborador,
            metodo=MetodoRegistro.MANUAL,
            tipo=tipo,
            momento=data_hora,
            request=request,
            registrado_por=executado_por,
            observacao=f"Inclusão manual: {justificativa}",
            validar_intervalo=False,
        )
        registro.origem_ajuste = ajuste
        registro.save(update_fields=["origem_ajuste", "updated_at"])
        return ajuste, registro

    @staticmethod
    @transaction.atomic
    def cancelar(*, registro, justificativa, executado_por, request=None):
        ajuste = AjustePonto.objects.create(
            empresa=registro.empresa,
            colaborador=registro.colaborador,
            tipo_ajuste=AjustePonto.TipoAjuste.CANCELAMENTO,
            registro_original=registro,
            justificativa=justificativa,
            executado_por=executado_por,
            ip=obter_ip(request) if request else None,
        )
        registro.cancelado = True
        registro.observacao = f"Cancelado: {justificativa}"[:255]
        registro.save(update_fields=["cancelado", "observacao", "updated_at"])

        dia = timezone.localtime(registro.data_hora).date()
        transaction.on_commit(
            lambda: ConsolidacaoService.consolidar_dia(registro.colaborador, dia)
        )
        _notificar_integracoes("ponto.ajustado", registro.empresa, registro)
        return ajuste

    @classmethod
    @transaction.atomic
    def substituir(
        cls, *, registro, data_hora, tipo, justificativa, executado_por, request=None
    ):
        """Cancela a marcação original e cria a corrigida."""
        colaborador = registro.colaborador
        ajuste = AjustePonto.objects.create(
            empresa=registro.empresa,
            colaborador=colaborador,
            tipo_ajuste=AjustePonto.TipoAjuste.SUBSTITUICAO,
            registro_original=registro,
            data_hora_nova=data_hora,
            tipo_novo=tipo,
            justificativa=justificativa,
            executado_por=executado_por,
            ip=obter_ip(request) if request else None,
        )
        registro.cancelado = True
        registro.observacao = f"Substituído: {justificativa}"[:255]
        registro.save(update_fields=["cancelado", "observacao", "updated_at"])

        novo = RegistroPontoService.registrar(
            colaborador=colaborador,
            metodo=MetodoRegistro.MANUAL,
            tipo=tipo,
            momento=data_hora,
            request=request,
            registrado_por=executado_por,
            observacao=f"Substitui NSR {registro.nsr}: {justificativa}",
            validar_intervalo=False,
        )
        novo.origem_ajuste = ajuste
        novo.save(update_fields=["origem_ajuste", "updated_at"])
        return ajuste, novo


class ConsolidacaoService:
    """Recalcula `BancoHoras` a partir das marcações."""

    # ══════════════════════════════════════════════════════════
    # Contexto do dia
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def contexto_do_dia(colaborador, dia: date) -> dict:
        """Descobre feriado, atestado, afastamento e justificativa do dia."""
        from apps.core.models import Feriado
        from apps.core.constants import StatusAprovacao

        eh_feriado = Feriado.objects.filter(data=dia).filter(
            empresa__isnull=True
        ).exists() or Feriado.objects.filter(
            data=dia, empresa=colaborador.empresa
        ).exists()

        coberto_por_atestado = colaborador.atestados.filter(
            status=StatusAprovacao.APROVADO, data_inicio__lte=dia, data_fim__gte=dia
        ).exists()

        coberto_por_afastamento = colaborador.afastamentos.filter(
            data_inicio__lte=dia, data_fim__gte=dia
        ).exists()

        justificado = colaborador.justificativas.filter(
            status=StatusAprovacao.APROVADO, data=dia, abona_dia=True
        ).exists()

        return {
            "eh_feriado": eh_feriado,
            "coberto_por_atestado": coberto_por_atestado,
            "coberto_por_afastamento": coberto_por_afastamento,
            "justificado": justificado,
        }

    # ══════════════════════════════════════════════════════════
    # Consolidação
    # ══════════════════════════════════════════════════════════
    @classmethod
    def consolidar_dia(cls, colaborador, dia: date = None) -> BancoHoras:
        """
        Calcula e persiste o `BancoHoras` do dia.

        Dias já fechados no fechamento mensal não são recalculados.
        """
        dia = dia or timezone.localdate()
        existente = BancoHoras.objects.filter(colaborador=colaborador, data=dia).first()
        if existente is not None and existente.fechado:
            return existente

        registros = RegistroPontoService.registros_do_dia(colaborador, dia)
        config = colaborador.empresa.configuracao
        calculadora = CalculadoraJornada(escala=colaborador.escala, config=config)
        resultado = calculadora.calcular(dia, registros, **cls.contexto_do_dia(colaborador, dia))

        saldo_anterior = cls._saldo_acumulado_ate(colaborador, dia)

        banco, _criado = BancoHoras.objects.update_or_create(
            colaborador=colaborador,
            data=dia,
            defaults={
                "empresa": colaborador.empresa,
                "minutos_trabalhados": resultado.minutos_trabalhados,
                "minutos_esperados": resultado.minutos_esperados,
                "minutos_intervalo": resultado.minutos_intervalo,
                "minutos_noturnos": resultado.minutos_noturnos,
                "minutos_extras": resultado.minutos_extras,
                "minutos_atraso": resultado.minutos_atraso,
                "minutos_saida_antecipada": resultado.minutos_saida_antecipada,
                "saldo_dia": resultado.saldo_dia,
                "saldo_acumulado": saldo_anterior + resultado.saldo_dia,
                "status": resultado.status,
                "observacao": resultado.observacao,
                "calculado_em": timezone.now(),
            },
        )
        cls._propagar_acumulado(colaborador, dia)
        return banco

    @staticmethod
    def _saldo_acumulado_ate(colaborador, dia: date) -> int:
        """Saldo acumulado até o dia anterior."""
        anterior = (
            BancoHoras.objects.filter(colaborador=colaborador, data__lt=dia)
            .order_by("-data")
            .values_list("saldo_acumulado", flat=True)
            .first()
        )
        return anterior or 0

    @staticmethod
    def _propagar_acumulado(colaborador, desde: date):
        """
        Recalcula o acumulado dos dias posteriores.

        Necessário quando um ajuste retroativo altera um dia no meio da
        série — o saldo corrente de todos os dias seguintes muda junto.
        """
        posteriores = BancoHoras.objects.filter(
            colaborador=colaborador, data__gt=desde, fechado=False
        ).order_by("data")
        acumulado = (
            BancoHoras.objects.filter(colaborador=colaborador, data=desde)
            .values_list("saldo_acumulado", flat=True)
            .first()
            or 0
        )
        atualizados = []
        for banco in posteriores:
            acumulado += banco.saldo_dia
            if banco.saldo_acumulado != acumulado:
                banco.saldo_acumulado = acumulado
                atualizados.append(banco)
        if atualizados:
            BancoHoras.objects.bulk_update(atualizados, ["saldo_acumulado"])

    @classmethod
    def consolidar_periodo(cls, colaborador, inicio: date, fim: date) -> list[BancoHoras]:
        """Recalcula um intervalo completo, dia a dia."""
        resultados = []
        dia = inicio
        while dia <= fim:
            resultados.append(cls.consolidar_dia(colaborador, dia))
            dia += timedelta(days=1)
        return resultados

    @classmethod
    def consolidar_empresa_no_dia(cls, empresa, dia: date = None) -> int:
        """Consolida todos os colaboradores ativos de uma empresa."""
        dia = dia or timezone.localdate()
        total = 0
        for colaborador in empresa.colaborador_set.filter(
            ativo=True, deleted_at__isnull=True
        ).select_related("escala", "empresa"):
            cls.consolidar_dia(colaborador, dia)
            total += 1
        return total

    # ══════════════════════════════════════════════════════════
    # Resumo de período
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def resumo_periodo(colaborador, inicio: date, fim: date) -> dict:
        """Totais do período, usados no espelho de ponto e no dashboard."""
        registros = BancoHoras.objects.filter(
            colaborador=colaborador, data__gte=inicio, data__lte=fim
        ).order_by("data")

        saldos = [b.saldo_dia for b in registros]
        calculadora = CalculadoraBancoHoras(colaborador.empresa.configuracao)
        credito, debito = calculadora.separar_credito_debito(saldos)

        saldo_anterior = (
            BancoHoras.objects.filter(colaborador=colaborador, data__lt=inicio)
            .order_by("-data")
            .values_list("saldo_acumulado", flat=True)
            .first()
            or 0
        )

        return {
            "dias": list(registros),
            "minutos_trabalhados": sum(b.minutos_trabalhados for b in registros),
            "minutos_esperados": sum(b.minutos_esperados for b in registros),
            "minutos_extras": sum(b.minutos_extras for b in registros),
            "minutos_noturnos": sum(b.minutos_noturnos for b in registros),
            "minutos_atraso": sum(b.minutos_atraso for b in registros),
            "credito": credito,
            "debito": debito,
            "saldo_periodo": sum(saldos),
            "saldo_anterior": saldo_anterior,
            "saldo_final": saldo_anterior + sum(saldos),
            "dias_falta": sum(1 for b in registros if b.status == StatusDia.FALTA),
            "dias_atestado": sum(1 for b in registros if b.status == StatusDia.ATESTADO),
            "dias_incompletos": sum(
                1 for b in registros if b.status == StatusDia.INCOMPLETO
            ),
        }
