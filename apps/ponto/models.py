"""
Kronus — nucleo do registro de ponto.

Models:
    EscalaTrabalho   jornada contratual (fixa, flexivel, 12x36, ...)
    RegistroPonto    a batida — imutavel, com NSR e hash encadeado
    AjustePonto      trilha de ajustes manuais (regra 1 da Secao 14)
    BancoHoras       consolidacao diaria de saldo
    FechamentoMensal fechamento e assinatura do espelho de ponto

Conformidade: Portaria 671/2021 (Secao 8.1 do plano).
"""
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.constants import (
    MetodoRegistro,
    StatusDia,
    TipoEscala,
    TipoRegistro,
)
from apps.core.models import TenantBaseModel
from apps.core.utils import minutos_para_hhmm


# ==============================================================
# Escala de trabalho
# ==============================================================
class EscalaTrabalho(TenantBaseModel):
    """
    Jornada contratual do colaborador.

    `jornada_config` guarda a definicao em JSON, o que permite escalas
    complexas sem rigidez de schema (Secao 4.2 do plano). Formato:

        {
          "dias": {
            "0": {"entrada": "08:00", "intervalo_inicio": "12:00",
                  "intervalo_fim": "13:00", "saida": "17:00"},
            ...
            "6": null                      # folga
          },
          "carga_semanal_min": 2640,
          "ciclo": {"trabalha": 1, "folga": 1}   # apenas para 12x36
        }
    """

    nome = models.CharField("Nome", max_length=100)
    descricao = models.CharField("Descrição", max_length=255, blank=True)
    tipo = models.CharField(
        "Tipo", max_length=15, choices=TipoEscala.choices, default=TipoEscala.FIXA
    )
    tolerancia_min = models.PositiveSmallIntegerField(
        "Tolerância (min)",
        default=5,
        help_text="Art. 58 §1º da CLT — padrão de 5 minutos por marcação.",
    )
    jornada_config = models.JSONField("Configuração da jornada", default=dict, blank=True)

    carga_diaria_min = models.PositiveSmallIntegerField(
        "Carga diária padrão (min)", default=480
    )
    carga_semanal_min = models.PositiveSmallIntegerField(
        "Carga semanal (min)", default=2640
    )
    exige_intervalo = models.BooleanField("Exige intervalo", default=True)
    intervalo_min = models.PositiveSmallIntegerField(
        "Duração do intervalo (min)", default=60
    )
    data_referencia = models.DateField(
        "Data de referência do ciclo",
        null=True,
        blank=True,
        help_text="Primeiro dia trabalhado do ciclo (usado em 12x36, 6x1 e plantão).",
    )
    ativa = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Escala de trabalho"
        verbose_name_plural = "Escalas de trabalho"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_escala_por_empresa",
            )
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"

    # -- consulta da jornada -----------------------------------
    def config_do_dia(self, dia: date) -> dict | None:
        """
        Devolve a configuracao de horarios para um dia especifico,
        ou None quando o dia e folga.
        """
        if self.tipo == TipoEscala.ESCALA_12X36:
            return self._config_12x36(dia)
        if self.tipo == TipoEscala.FLEXIVEL:
            return {"flexivel": True, "carga_min": self.carga_diaria_min}
        dias = (self.jornada_config or {}).get("dias") or {}
        return dias.get(str(dia.weekday()))

    def _config_12x36(self, dia: date) -> dict | None:
        """12 horas trabalhadas seguidas de 36 de descanso (ciclo de 2 dias)."""
        if not self.data_referencia:
            return None
        delta = (dia - self.data_referencia).days
        if delta < 0 or delta % 2 != 0:
            return None
        padrao = (self.jornada_config or {}).get("padrao_12x36") or {
            "entrada": "07:00",
            "saida": "19:00",
        }
        return padrao

    def minutos_esperados(self, dia: date) -> int:
        """Carga horaria contratual esperada no dia (0 em folgas)."""
        config = self.config_do_dia(dia)
        if not config:
            return 0
        if config.get("flexivel"):
            return int(config.get("carga_min", self.carga_diaria_min))
        entrada = self._hora(config.get("entrada"))
        saida = self._hora(config.get("saida"))
        if entrada is None or saida is None:
            return self.carga_diaria_min
        total = self._delta_minutos(entrada, saida)
        ini_int = self._hora(config.get("intervalo_inicio"))
        fim_int = self._hora(config.get("intervalo_fim"))
        if ini_int and fim_int:
            total -= self._delta_minutos(ini_int, fim_int)
        return max(total, 0)

    def eh_dia_util(self, dia: date) -> bool:
        return self.config_do_dia(dia) is not None

    @staticmethod
    def _hora(texto):
        if not texto:
            return None
        if isinstance(texto, time):
            return texto
        horas, minutos = str(texto).split(":")[:2]
        return time(int(horas), int(minutos))

    @staticmethod
    def _delta_minutos(inicio: time, fim: time) -> int:
        base = date(2000, 1, 1)
        dt_ini = datetime.combine(base, inicio)
        dt_fim = datetime.combine(base, fim)
        if dt_fim <= dt_ini:  # virada de dia (jornada noturna)
            dt_fim += timedelta(days=1)
        return int((dt_fim - dt_ini).total_seconds() // 60)


# ==============================================================
# Registro de ponto
# ==============================================================
class RegistroPontoQuerySet(models.QuerySet):
    def do_dia(self, dia: date):
        return self.filter(data_hora__date=dia)

    def do_colaborador(self, colaborador):
        return self.filter(colaborador=colaborador)

    def validos(self):
        return self.filter(deleted_at__isnull=True, cancelado=False)

    def ordenados(self):
        return self.order_by("data_hora", "nsr")


class RegistroPonto(TenantBaseModel):
    """
    Uma batida de ponto. **Imutavel** por determinacao legal (regra 1 da
    Secao 14): correcoes sao feitas por `AjustePonto`, nunca por UPDATE.

    Cada registro carrega:
        * `nsr`            sequencial por empresa, sem lacunas
        * `hash_registro`  SHA-256 encadeado ao registro anterior
        * evidencias de nao-repudio: foto, geolocalizacao, IP, user agent
    """

    colaborador = models.ForeignKey(
        "rh.Colaborador",
        on_delete=models.PROTECT,
        related_name="registros",
        verbose_name="Colaborador",
    )
    data_hora = models.DateTimeField("Data e hora", db_index=True)
    tipo = models.CharField("Tipo", max_length=20, choices=TipoRegistro.choices)
    metodo = models.CharField(
        "Método", max_length=12, choices=MetodoRegistro.choices, default=MetodoRegistro.WEB
    )

    # -- Evidencias de nao-repudio (Secao 8.1) -----------------
    latitude = models.DecimalField(
        "Latitude", max_digits=10, decimal_places=7, null=True, blank=True
    )
    longitude = models.DecimalField(
        "Longitude", max_digits=10, decimal_places=7, null=True, blank=True
    )
    precisao_gps = models.FloatField("Precisão do GPS (m)", null=True, blank=True)
    fora_area = models.BooleanField("Fora da área autorizada", default=False)
    suspeita_fraude = models.BooleanField("Suspeita de GPS fictício", default=False)

    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.TextField("User agent", blank=True)

    totem = models.ForeignKey(
        "totem.Totem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros",
        verbose_name="Totem",
    )
    foto_momento = models.ImageField(
        "Foto no ato",
        upload_to="comprovantes/fotos/%Y/%m/",
        null=True,
        blank=True,
        help_text="Evidência antifraude capturada no instante da batida.",
    )
    confianca_face = models.FloatField(
        "Confiança do reconhecimento (%)", null=True, blank=True
    )

    # -- Portaria 671 ------------------------------------------
    nsr = models.PositiveBigIntegerField("NSR", db_index=True)
    hash_registro = models.CharField("Hash SHA-256", max_length=64, db_index=True)
    hash_anterior = models.CharField("Hash do registro anterior", max_length=64, blank=True)
    comprovante_pdf = models.FileField(
        "Comprovante (PDF)", upload_to="comprovantes/%Y/%m/", null=True, blank=True
    )

    # -- Ajustes -----------------------------------------------
    origem_ajuste = models.ForeignKey(
        "ponto.AjustePonto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_gerados",
        verbose_name="Ajuste de origem",
    )
    cancelado = models.BooleanField(
        "Cancelado",
        default=False,
        help_text="Registro anulado por ajuste. Permanece no AFD para auditoria.",
    )

    registrado_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pontos_registrados",
        verbose_name="Registrado por",
        help_text="Preenchido em ajustes manuais e registros via API.",
    )
    observacao = models.CharField("Observação", max_length=255, blank=True)

    objects = RegistroPontoQuerySet.as_manager()

    class Meta:
        verbose_name = "Registro de ponto"
        verbose_name_plural = "Registros de ponto"
        ordering = ("-data_hora",)
        constraints = [
            models.UniqueConstraint(fields=["empresa", "nsr"], name="uniq_nsr_por_empresa"),
        ]
        indexes = [
            models.Index(fields=["colaborador", "data_hora"]),
            models.Index(fields=["empresa", "data_hora"]),
            models.Index(fields=["empresa", "nsr"]),
        ]

    def __str__(self):
        return (
            f"{self.colaborador.nome_exibicao} — {self.get_tipo_display()} "
            f"em {timezone.localtime(self.data_hora):%d/%m/%Y %H:%M:%S}"
        )

    # -- imutabilidade (regra 1 da Secao 14) -------------------
    #: Campos que podem ser gravados apos a criacao. Qualquer outro
    #: disparo de UPDATE sobre um registro existente e recusado.
    CAMPOS_MUTAVEIS = {
        "comprovante_pdf",
        "cancelado",
        "origem_ajuste",
        "deleted_at",
        "updated_at",
        "observacao",
    }

    def save(self, *args, **kwargs):
        if not self._state.adding:
            campos = set(kwargs.get("update_fields") or [])
            if not campos or not campos.issubset(self.CAMPOS_MUTAVEIS):
                raise ValidationError(
                    "Registros de ponto são imutáveis (Portaria 671/2021). "
                    "Use um ajuste manual para corrigir a marcação."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Registros de ponto não podem ser excluídos. Utilize o cancelamento por ajuste."
        )

    # -- apresentacao ------------------------------------------
    @property
    def hora_local(self):
        return timezone.localtime(self.data_hora)

    @property
    def data_local(self) -> date:
        return timezone.localtime(self.data_hora).date()

    @property
    def tem_geolocalizacao(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def codigo_verificacao(self) -> str:
        from apps.core.utils import hash_curto

        return hash_curto(self.hash_registro)


# ==============================================================
# Ajuste manual
# ==============================================================
class AjustePonto(TenantBaseModel):
    """
    Ajuste manual feito pelo RH. Nunca altera o registro original:
    cancela o antigo e/ou cria um novo, mantendo ambos no AFD.
    """

    class TipoAjuste(models.TextChoices):
        INCLUSAO = "inclusao", "Inclusão de marcação"
        CANCELAMENTO = "cancelamento", "Cancelamento de marcação"
        SUBSTITUICAO = "substituicao", "Substituição de marcação"

    colaborador = models.ForeignKey(
        "rh.Colaborador",
        on_delete=models.CASCADE,
        related_name="ajustes",
        verbose_name="Colaborador",
    )
    tipo_ajuste = models.CharField("Tipo", max_length=15, choices=TipoAjuste.choices)
    registro_original = models.ForeignKey(
        RegistroPonto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ajustes_aplicados",
        verbose_name="Registro original",
    )
    data_hora_nova = models.DateTimeField("Nova data/hora", null=True, blank=True)
    tipo_novo = models.CharField(
        "Novo tipo", max_length=20, choices=TipoRegistro.choices, blank=True
    )
    justificativa = models.TextField("Justificativa")
    executado_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.PROTECT,
        related_name="ajustes_executados",
        verbose_name="Executado por",
    )
    ip = models.GenericIPAddressField("IP", null=True, blank=True)

    class Meta:
        verbose_name = "Ajuste de ponto"
        verbose_name_plural = "Ajustes de ponto"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["colaborador", "-created_at"])]

    def __str__(self):
        return f"{self.get_tipo_ajuste_display()} — {self.colaborador.nome_exibicao}"


# ==============================================================
# Banco de horas
# ==============================================================
class BancoHoras(TenantBaseModel):
    """
    Consolidacao diaria (Secao 8.4). Uma linha por colaborador por dia,
    gerada pela task Celery das 23:59 e recalculavel sob demanda.

    Todos os totais sao armazenados em **minutos inteiros** para evitar
    erros de arredondamento em ponto flutuante.
    """

    colaborador = models.ForeignKey(
        "rh.Colaborador",
        on_delete=models.CASCADE,
        related_name="banco_horas",
        verbose_name="Colaborador",
    )
    data = models.DateField("Data", db_index=True)

    minutos_trabalhados = models.IntegerField("Minutos trabalhados", default=0)
    minutos_esperados = models.IntegerField("Minutos esperados", default=0)
    minutos_intervalo = models.IntegerField("Minutos de intervalo", default=0)
    minutos_noturnos = models.IntegerField("Minutos noturnos", default=0)
    minutos_extras = models.IntegerField("Minutos extras", default=0)
    minutos_atraso = models.IntegerField("Minutos de atraso", default=0)
    minutos_saida_antecipada = models.IntegerField("Minutos de saída antecipada", default=0)

    saldo_dia = models.IntegerField("Saldo do dia (min)", default=0)
    saldo_acumulado = models.IntegerField("Saldo acumulado (min)", default=0)

    status = models.CharField(
        "Status do dia",
        max_length=15,
        choices=StatusDia.choices,
        default=StatusDia.INCOMPLETO,
        db_index=True,
    )
    compensado = models.BooleanField("Compensado", default=False)
    fechado = models.BooleanField(
        "Fechado", default=False, help_text="Bloqueia recálculo após o fechamento mensal."
    )
    observacao = models.CharField("Observação", max_length=255, blank=True)
    calculado_em = models.DateTimeField("Calculado em", null=True, blank=True)

    class Meta:
        verbose_name = "Banco de horas"
        verbose_name_plural = "Banco de horas"
        ordering = ("-data",)
        constraints = [
            models.UniqueConstraint(
                fields=["colaborador", "data"], name="uniq_banco_horas_dia"
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "data"]),
            models.Index(fields=["colaborador", "-data"]),
        ]

    def __str__(self):
        return f"{self.colaborador.nome_exibicao} — {self.data:%d/%m/%Y} ({self.saldo_formatado})"

    @property
    def saldo_formatado(self) -> str:
        return minutos_para_hhmm(self.saldo_dia)

    @property
    def acumulado_formatado(self) -> str:
        return minutos_para_hhmm(self.saldo_acumulado)

    @property
    def trabalhado_formatado(self) -> str:
        return minutos_para_hhmm(self.minutos_trabalhados, com_sinal=False)

    @property
    def classe_cor(self) -> str:
        """Cores do painel de banco de horas (Secao 8.4)."""
        if self.saldo_acumulado > 0:
            return "positivo"
        if self.saldo_acumulado >= -120:
            return "atencao"
        return "negativo"


# ==============================================================
# Fechamento mensal e espelho de ponto
# ==============================================================
class FechamentoMensal(TenantBaseModel):
    """
    Fechamento do periodo e espelho de ponto do colaborador (Secao 8.5).

    Uma vez assinado pelo colaborador, o espelho torna-se imutavel
    (regra 4 da Secao 14).
    """

    colaborador = models.ForeignKey(
        "rh.Colaborador",
        on_delete=models.CASCADE,
        related_name="fechamentos",
        verbose_name="Colaborador",
    )
    ano = models.PositiveSmallIntegerField("Ano")
    mes = models.PositiveSmallIntegerField("Mês")
    data_inicio = models.DateField("Início do período")
    data_fim = models.DateField("Fim do período")

    minutos_trabalhados = models.IntegerField("Minutos trabalhados", default=0)
    minutos_esperados = models.IntegerField("Minutos esperados", default=0)
    minutos_extras = models.IntegerField("Minutos extras", default=0)
    minutos_noturnos = models.IntegerField("Minutos noturnos", default=0)
    minutos_atraso = models.IntegerField("Minutos de atraso", default=0)
    saldo_periodo = models.IntegerField("Saldo do período (min)", default=0)
    saldo_anterior = models.IntegerField("Saldo anterior (min)", default=0)
    saldo_final = models.IntegerField("Saldo final (min)", default=0)
    dias_falta = models.PositiveSmallIntegerField("Dias de falta", default=0)
    dias_atestado = models.PositiveSmallIntegerField("Dias de atestado", default=0)

    espelho_pdf = models.FileField(
        "Espelho de ponto (PDF)", upload_to="espelhos/%Y/%m/", null=True, blank=True
    )
    hash_documento = models.CharField("Hash do documento", max_length=64, blank=True)

    fechado = models.BooleanField("Fechado", default=False)
    fechado_em = models.DateTimeField("Fechado em", null=True, blank=True)
    fechado_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fechamentos_realizados",
        verbose_name="Fechado por",
    )

    # -- Assinatura eletronica do colaborador (Secao 8.5) ------
    assinado = models.BooleanField("Assinado pelo colaborador", default=False)
    assinado_em = models.DateTimeField("Assinado em", null=True, blank=True)
    assinatura_ip = models.GenericIPAddressField("IP da assinatura", null=True, blank=True)
    assinatura_hash = models.CharField("Hash da assinatura", max_length=64, blank=True)
    assinatura_selfie = models.ImageField(
        "Selfie da assinatura", upload_to="assinaturas/%Y/%m/", null=True, blank=True
    )

    class Meta:
        verbose_name = "Fechamento mensal"
        verbose_name_plural = "Fechamentos mensais"
        ordering = ("-ano", "-mes")
        constraints = [
            models.UniqueConstraint(
                fields=["colaborador", "ano", "mes"], name="uniq_fechamento_mes"
            )
        ]
        indexes = [models.Index(fields=["empresa", "ano", "mes"])]

    def __str__(self):
        return f"{self.colaborador.nome_exibicao} — {self.mes:02d}/{self.ano}"

    @property
    def periodo(self) -> str:
        return f"{self.mes:02d}/{self.ano}"

    @property
    def codigo_verificacao(self) -> str:
        from apps.core.utils import hash_curto

        return hash_curto(self.hash_documento)

    @property
    def editavel(self) -> bool:
        return not self.assinado
