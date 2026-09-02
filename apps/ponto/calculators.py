"""
Kronus — cálculo de jornada, horas extras e banco de horas.

Este módulo é **puro**: recebe dados e devolve números, sem tocar no
banco. Isso mantém a regra trabalhista testável isoladamente — o que
importa, porque erro de arredondamento aqui vira passivo jurídico.

Todos os totais são em **minutos inteiros**.

Base legal (Seção 8.4 do plano):
    Art. 58 §1º CLT — tolerância de até 5 min por marcação, 10 min/dia
    Art. 71 CLT     — intervalo intrajornada de 1h para jornadas > 6h
    Art. 73 CLT     — adicional noturno 22h–5h, hora reduzida de 52min30s
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from apps.core.constants import (
    MINUTOS_HORA_NOTURNA,
    StatusDia,
    TipoRegistro,
)

#: Minutos em uma hora relógio — usado na conversão da hora noturna reduzida.
MINUTOS_HORA_RELOGIO = 60


# ══════════════════════════════════════════════════════════════
# Estruturas de resultado
# ══════════════════════════════════════════════════════════════
@dataclass
class ParDeMarcacoes:
    """Um par entrada→saída efetivamente trabalhado."""

    inicio: datetime
    fim: datetime

    @property
    def minutos(self) -> int:
        return int((self.fim - self.inicio).total_seconds() // 60)


@dataclass
class ResultadoDia:
    """Consolidação de um dia de trabalho."""

    data: date
    minutos_trabalhados: int = 0
    minutos_esperados: int = 0
    minutos_intervalo: int = 0
    minutos_noturnos: int = 0
    minutos_extras: int = 0
    minutos_atraso: int = 0
    minutos_saida_antecipada: int = 0
    saldo_dia: int = 0
    status: str = StatusDia.INCOMPLETO
    marcacoes_impares: bool = False
    intervalo_irregular: bool = False
    observacao: str = ""
    pares: list[ParDeMarcacoes] = field(default_factory=list)

    @property
    def completo(self) -> bool:
        return self.status == StatusDia.COMPLETO


# ══════════════════════════════════════════════════════════════
# Calculadora de jornada
# ══════════════════════════════════════════════════════════════
class CalculadoraJornada:
    """
    Consolida as marcações de **um** colaborador em **um** dia.

    Uso:
        calc = CalculadoraJornada(escala=escala, config=empresa.config)
        resultado = calc.calcular(dia, registros, contexto=ContextoDia(...))
    """

    def __init__(self, *, escala=None, config=None):
        self.escala = escala
        self.config = config

    # -- parâmetros efetivos -----------------------------------
    @property
    def tolerancia_min(self) -> int:
        if self.escala is not None and self.escala.tolerancia_min is not None:
            return self.escala.tolerancia_min
        if self.config is not None:
            return self.config.tolerancia_atraso_min
        return 5

    @property
    def intervalo_minimo_min(self) -> int:
        return self.config.intervalo_minimo_min if self.config else 60

    @property
    def jornada_padrao_min(self) -> int:
        if self.escala is not None:
            return self.escala.carga_diaria_min
        return self.config.jornada_diaria_padrao_min if self.config else 480

    @property
    def limite_extra_diaria_min(self) -> int:
        return self.config.limite_hora_extra_diaria_min if self.config else 120

    # -- API principal -----------------------------------------
    def calcular(
        self,
        dia: date,
        registros: list,
        *,
        eh_feriado: bool = False,
        coberto_por_atestado: bool = False,
        coberto_por_afastamento: bool = False,
        justificado: bool = False,
        compensado: bool = False,
    ) -> ResultadoDia:
        """
        `registros` deve vir ordenado por `data_hora`, já em horário local,
        e sem registros cancelados.
        """
        resultado = ResultadoDia(data=dia)
        resultado.minutos_esperados = self._minutos_esperados(dia, eh_feriado)

        pares, impares = self._parear(registros)
        resultado.pares = pares
        resultado.marcacoes_impares = impares

        resultado.minutos_trabalhados = sum(par.minutos for par in pares)
        resultado.minutos_intervalo = self._minutos_intervalo(pares)
        resultado.minutos_noturnos = self._minutos_noturnos(pares)

        self._avaliar_atraso_e_saida(resultado, dia, registros)
        self._avaliar_extras(resultado)

        resultado.saldo_dia = resultado.minutos_trabalhados - resultado.minutos_esperados
        resultado.status = self._status(
            resultado,
            registros,
            eh_feriado=eh_feriado,
            coberto_por_atestado=coberto_por_atestado,
            coberto_por_afastamento=coberto_por_afastamento,
            justificado=justificado,
            compensado=compensado,
        )

        # Dias abonados não geram débito: o saldo é zerado.
        if resultado.status in (
            StatusDia.ATESTADO,
            StatusDia.JUSTIFICADO,
            StatusDia.FERIAS,
            StatusDia.AFASTAMENTO,
        ):
            resultado.saldo_dia = max(resultado.saldo_dia, 0)
            resultado.minutos_atraso = 0
            resultado.minutos_saida_antecipada = 0

        # A folga compensada faz o contrário do abono: **debita**.
        #
        # O saldo do dia já é `trabalhado - esperado`, ou seja, menos a
        # jornada inteira quando ninguém bateu ponto. É exatamente o que
        # sai do banco, e por isso não há conta nova aqui — o que muda é
        # o nome do dia e o fato de o débito não ser perdoado.
        #
        # Atraso e saída antecipada saem: não houve jornada a cumprir, e
        # deixá-los marcaria de irregular um dia acordado.
        if resultado.status == StatusDia.COMPENSADO:
            resultado.minutos_atraso = 0
            resultado.minutos_saida_antecipada = 0

        self._descrever_irregularidades(resultado)
        return resultado

    # -- etapas ------------------------------------------------
    def _minutos_esperados(self, dia: date, eh_feriado: bool) -> int:
        if eh_feriado:
            return 0
        if self.escala is None:
            # Sem escala cadastrada, o padrao da CLT: segunda a sexta.
            #
            # Antes daqui a jornada era cobrada nos sete dias, e o
            # resultado apareceu em producao — nove pessoas sem escala
            # levaram falta em sabado e domingo. Cobrar jornada de um
            # domingo que ninguem combinou nao e rigor, e erro.
            if dia.weekday() >= 5:
                return 0
            return self.jornada_padrao_min
        return self.escala.minutos_esperados(dia)

    @staticmethod
    def _parear(registros) -> tuple[list[ParDeMarcacoes], bool]:
        """
        Agrupa as marcações em pares entrada→saída.

        O pareamento é **posicional**, não por tipo declarado: uma batida
        esquecida no meio do dia não deve corromper o cálculo das demais.
        Um número ímpar de marcações sinaliza jornada em aberto.
        """
        momentos = [r.data_hora for r in registros]
        pares = []
        for indice in range(0, len(momentos) - 1, 2):
            inicio, fim = momentos[indice], momentos[indice + 1]
            if fim > inicio:
                pares.append(ParDeMarcacoes(inicio=inicio, fim=fim))
        return pares, len(momentos) % 2 == 1

    @staticmethod
    def _minutos_intervalo(pares: list[ParDeMarcacoes]) -> int:
        """Soma das lacunas entre um par e o seguinte."""
        total = 0
        for anterior, seguinte in zip(pares, pares[1:]):
            total += int((seguinte.inicio - anterior.fim).total_seconds() // 60)
        return total

    def _minutos_noturnos(self, pares: list[ParDeMarcacoes]) -> int:
        """
        Minutos trabalhados dentro do período noturno.

        Com `hora_noturna_reduzida`, cada 52min30s reais equivalem a
        uma hora noturna — o total é convertido para minutos-relógio
        equivalentes (Art. 73 §1º da CLT).
        """
        if self.config is not None and not self.config.adicional_noturno:
            return 0

        inicio_noturno = (
            self.config.hora_ini_noturno if self.config else time(22, 0)
        )
        fim_noturno = self.config.hora_fim_noturno if self.config else time(5, 0)

        reais = 0
        for par in pares:
            reais += self._minutos_no_periodo_noturno(
                par.inicio, par.fim, inicio_noturno, fim_noturno
            )

        if self.config is not None and self.config.hora_noturna_reduzida and reais:
            return int(round(reais * MINUTOS_HORA_RELOGIO / MINUTOS_HORA_NOTURNA))
        return reais

    @staticmethod
    def _minutos_no_periodo_noturno(
        inicio: datetime, fim: datetime, hora_ini: time, hora_fim: time
    ) -> int:
        """
        Interseção do intervalo trabalhado com a faixa noturna.

        A faixa cruza a meia-noite (22h→5h), então avaliamos a janela de
        cada dia coberto pelo intervalo, mais o dia anterior ao início.
        """
        total = 0
        dia = (inicio - timedelta(days=1)).date()
        ultimo = fim.date()
        while dia <= ultimo:
            janela_ini = datetime.combine(dia, hora_ini, tzinfo=inicio.tzinfo)
            janela_fim = datetime.combine(dia, hora_fim, tzinfo=inicio.tzinfo)
            if janela_fim <= janela_ini:  # cruza a meia-noite
                janela_fim += timedelta(days=1)
            sobreposicao = min(fim, janela_fim) - max(inicio, janela_ini)
            if sobreposicao > timedelta(0):
                total += int(sobreposicao.total_seconds() // 60)
            dia += timedelta(days=1)
        return total

    def _avaliar_atraso_e_saida(self, resultado: ResultadoDia, dia: date, registros):
        """
        Atraso e saída antecipada só existem quando a escala fixa
        horários. Em escala flexível, o que vale é a carga total.
        """
        if self.escala is None or not registros:
            return
        config_dia = self.escala.config_do_dia(dia)
        if not config_dia or config_dia.get("flexivel"):
            return

        tolerancia = self.tolerancia_min
        primeira = registros[0].data_hora
        ultima = registros[-1].data_hora

        entrada_prevista = self._datetime_previsto(dia, config_dia.get("entrada"), primeira)
        if entrada_prevista is not None:
            atraso = int((primeira - entrada_prevista).total_seconds() // 60)
            if atraso > tolerancia:
                resultado.minutos_atraso = atraso

        saida_prevista = self._datetime_previsto(dia, config_dia.get("saida"), ultima)
        if saida_prevista is not None and len(registros) % 2 == 0:
            if saida_prevista > ultima:
                antecipacao = int((saida_prevista - ultima).total_seconds() // 60)
                if antecipacao > tolerancia:
                    resultado.minutos_saida_antecipada = antecipacao

    @staticmethod
    def _datetime_previsto(dia: date, texto_hora, referencia: datetime):
        if not texto_hora:
            return None
        horas, minutos = str(texto_hora).split(":")[:2]
        return datetime.combine(
            dia, time(int(horas), int(minutos)), tzinfo=referencia.tzinfo
        )

    def _avaliar_extras(self, resultado: ResultadoDia):
        excedente = resultado.minutos_trabalhados - resultado.minutos_esperados
        if excedente <= 0:
            resultado.minutos_extras = 0
            return
        # A tolerância também protege o empregador: minutos residuais
        # dentro dela não viram hora extra (Art. 58 §1º).
        if excedente <= self.tolerancia_min:
            resultado.minutos_extras = 0
            return
        resultado.minutos_extras = min(excedente, self.limite_extra_diaria_min)

    def _status(
        self,
        resultado: ResultadoDia,
        registros,
        *,
        eh_feriado,
        coberto_por_atestado,
        coberto_por_afastamento,
        justificado,
        compensado=False,
    ) -> str:
        if coberto_por_atestado:
            return StatusDia.ATESTADO
        if coberto_por_afastamento:
            return StatusDia.AFASTAMENTO
        # Antes do abono: os dois chegam como justificativa aprovada, e o
        # que os separa e o efeito no saldo. Se a compensacao caisse em
        # JUSTIFICADO, o bloco de abono zeraria o debito logo abaixo.
        if compensado and not registros:
            return StatusDia.COMPENSADO
        if justificado:
            return StatusDia.JUSTIFICADO
        if eh_feriado:
            return StatusDia.FERIADO
        if resultado.minutos_esperados == 0:
            return StatusDia.FOLGA if not registros else StatusDia.COMPLETO
        if not registros:
            return StatusDia.FALTA
        if resultado.marcacoes_impares:
            return StatusDia.INCOMPLETO
        if len(registros) < 2:
            return StatusDia.INCOMPLETO
        return StatusDia.COMPLETO

    def _descrever_irregularidades(self, resultado: ResultadoDia):
        avisos = []
        if resultado.marcacoes_impares:
            avisos.append("Número ímpar de marcações — jornada em aberto.")
        if (
            resultado.minutos_esperados > 360
            and resultado.pares
            and len(resultado.pares) > 1
            and resultado.minutos_intervalo < self.intervalo_minimo_min
        ):
            resultado.intervalo_irregular = True
            avisos.append(
                f"Intervalo de {resultado.minutos_intervalo} min abaixo do mínimo "
                f"de {self.intervalo_minimo_min} min (Art. 71 CLT)."
            )
        elif (
            resultado.minutos_esperados > 360
            and len(resultado.pares) == 1
            and resultado.minutos_trabalhados > 360
        ):
            resultado.intervalo_irregular = True
            avisos.append("Jornada acima de 6h sem intervalo registrado (Art. 71 CLT).")
        resultado.observacao = " ".join(avisos)[:255]


# ══════════════════════════════════════════════════════════════
# Horas extras por faixa de percentual
# ══════════════════════════════════════════════════════════════
@dataclass
class FaixaHoraExtra:
    percentual: int
    minutos: int

    @property
    def minutos_remunerados(self) -> float:
        """Minutos já acrescidos do percentual — base para a folha."""
        return self.minutos * (1 + self.percentual / 100)


class CalculadoraHorasExtras:
    """
    Distribui os minutos extras de um dia entre as faixas de percentual
    configuradas na empresa (Seção 8.4).

        até 2h/dia .................. hora_extra_percentual (padrão 50%)
        a partir da 3ª hora ......... hora_extra_percentual_2 (padrão 70%)
        domingos e feriados ......... hora_extra_percentual_dsr (padrão 100%)
    """

    LIMITE_PRIMEIRA_FAIXA_MIN = 120

    def __init__(self, config=None):
        self.config = config

    @property
    def percentual_1(self) -> int:
        return self.config.hora_extra_percentual if self.config else 50

    @property
    def percentual_2(self) -> int:
        return self.config.hora_extra_percentual_2 if self.config else 70

    @property
    def percentual_dsr(self) -> int:
        return self.config.hora_extra_percentual_dsr if self.config else 100

    def distribuir(
        self, minutos_extras: int, *, dia: date = None, eh_feriado: bool = False
    ) -> list[FaixaHoraExtra]:
        if minutos_extras <= 0:
            return []

        eh_domingo = dia is not None and dia.weekday() == 6
        if eh_feriado or eh_domingo:
            return [FaixaHoraExtra(self.percentual_dsr, minutos_extras)]

        primeira = min(minutos_extras, self.LIMITE_PRIMEIRA_FAIXA_MIN)
        faixas = [FaixaHoraExtra(self.percentual_1, primeira)]
        restante = minutos_extras - primeira
        if restante > 0:
            faixas.append(FaixaHoraExtra(self.percentual_2, restante))
        return faixas


# ══════════════════════════════════════════════════════════════
# Banco de horas
# ══════════════════════════════════════════════════════════════
class CalculadoraBancoHoras:
    """
    Acumula o saldo do banco de horas (Seção 8.4).

    Com `modo_compensacao` ativo, créditos e débitos se compensam num
    saldo corrente único. Sem ele, extras e débitos são acompanhados
    separadamente — mesmo saldo, apuração distinta na folha.
    """

    def __init__(self, config=None):
        self.config = config

    @property
    def compensacao_ativa(self) -> bool:
        return self.config.modo_compensacao if self.config else True

    @staticmethod
    def acumular(saldo_anterior: int, saldo_dia: int) -> int:
        return saldo_anterior + saldo_dia

    @staticmethod
    def classificar(saldo_acumulado: int) -> str:
        """Faixas de cor do painel: verde / amarelo / vermelho."""
        if saldo_acumulado > 0:
            return "positivo"
        if saldo_acumulado >= -120:
            return "atencao"
        return "negativo"

    def separar_credito_debito(self, saldos_diarios: list[int]) -> tuple[int, int]:
        """Devolve `(total_credito, total_debito)` em minutos."""
        credito = sum(s for s in saldos_diarios if s > 0)
        debito = sum(-s for s in saldos_diarios if s < 0)
        return credito, debito

    def saldo_final(self, saldos_diarios: list[int], saldo_anterior: int = 0) -> int:
        credito, debito = self.separar_credito_debito(saldos_diarios)
        if self.compensacao_ativa:
            return saldo_anterior + credito - debito
        return saldo_anterior + credito - debito

    def prazo_expirado(self, data_credito: date, hoje: date = None) -> bool:
        """
        Créditos não compensados dentro do prazo acordado devem ser
        pagos como hora extra (Art. 59 §2º da CLT).
        """
        meses = self.config.prazo_compensacao_meses if self.config else 6
        hoje = hoje or date.today()
        limite_ano = data_credito.year + (data_credito.month - 1 + meses) // 12
        limite_mes = (data_credito.month - 1 + meses) % 12 + 1
        dia = min(data_credito.day, 28)
        return hoje > date(limite_ano, limite_mes, dia)


# ══════════════════════════════════════════════════════════════
# Utilitário de sequência
# ══════════════════════════════════════════════════════════════
def proximo_tipo_esperado(registros_do_dia, exige_intervalo: bool = True) -> str:
    """
    Determina qual batida o colaborador deve registrar agora.

    Alimenta a cor e o rótulo do botão em `/ponto/registrar/`
    (Seção 6.3 do plano).
    """
    quantidade = len(registros_do_dia)
    if not exige_intervalo:
        return TipoRegistro.ENTRADA if quantidade % 2 == 0 else TipoRegistro.SAIDA

    sequencia = [
        TipoRegistro.ENTRADA,
        TipoRegistro.INTERVALO_INICIO,
        TipoRegistro.INTERVALO_FIM,
        TipoRegistro.SAIDA,
    ]
    if quantidade < len(sequencia):
        return sequencia[quantidade]
    # Jornadas com mais de quatro marcações alternam entrada e saída.
    return TipoRegistro.ENTRADA if quantidade % 2 == 0 else TipoRegistro.SAIDA
