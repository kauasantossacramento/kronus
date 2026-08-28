"""
Kronus — Cliente, Empresa e ConfiguracaoEmpresa.

Hierarquia (Secao 1.5):  Master -> Cliente -> Empresa -> Colaborador

O `Cliente` e o contratante da assinatura; cada Cliente pode ter varias
`Empresa`s (matriz e filiais, ou CNPJs distintos do mesmo grupo).
Toda a personalizacao white-label parcial (Secao 3.6) vive na Empresa.
"""
from datetime import time

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.constants import (
    ADICIONAL_NOTURNO_PERCENTUAL_PADRAO,
    HORA_FIM_NOTURNO_PADRAO,
    HORA_INICIO_NOTURNO_PADRAO,
    ModoCompensacao,
)
from apps.core.models import BaseModel
from apps.core.utils import (
    apenas_digitos,
    formatar_cnpj,
    gerar_token,
    hash_api_key,
    validar_cnpj,
)


class Cliente(BaseModel):
    """Contratante da assinatura Kronus."""

    razao_social = models.CharField("Razão social", max_length=200)
    nome_fantasia = models.CharField("Nome fantasia", max_length=200, blank=True)
    cnpj = models.CharField(
        "CNPJ", max_length=14, unique=True, validators=[validar_cnpj], db_index=True
    )
    plano = models.ForeignKey(
        "master.Plano",
        on_delete=models.PROTECT,
        related_name="clientes",
        verbose_name="Plano",
    )

    # -- Contato -----------------------------------------------
    email_contato = models.EmailField("E-mail de contato")
    telefone = models.CharField("Telefone", max_length=20, blank=True)
    responsavel = models.CharField("Responsável", max_length=150, blank=True)

    # -- Endereco ----------------------------------------------
    cep = models.CharField("CEP", max_length=9, blank=True)
    logradouro = models.CharField("Logradouro", max_length=200, blank=True)
    numero = models.CharField("Número", max_length=20, blank=True)
    complemento = models.CharField("Complemento", max_length=100, blank=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True)
    cidade = models.CharField("Cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)

    # -- Assinatura --------------------------------------------
    ativo = models.BooleanField("Ativo", default=True, db_index=True)
    suspenso = models.BooleanField("Suspenso", default=False, db_index=True)
    motivo_suspensao = models.CharField("Motivo da suspensão", max_length=255, blank=True)
    data_cadastro = models.DateField("Data de cadastro", default=timezone.localdate)
    data_inicio_contrato = models.DateField("Início do contrato", null=True, blank=True)
    data_fim_contrato = models.DateField("Fim do contrato", null=True, blank=True)
    dia_vencimento = models.PositiveSmallIntegerField(
        "Dia de vencimento",
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
    )
    ultimo_acesso = models.DateTimeField("Último acesso", null=True, blank=True)

    # -- Integracao (Secao 7.4) --------------------------------
    api_key_hash = models.CharField("Hash da API key", max_length=64, blank=True)
    api_key_prefixo = models.CharField(
        "Prefixo da API key",
        max_length=12,
        blank=True,
        help_text="Primeiros caracteres, exibidos na interface para identificação.",
    )
    api_key_ativa = models.BooleanField("API key ativa", default=False)
    api_key_gerada_em = models.DateTimeField("API key gerada em", null=True, blank=True)

    # -- LGPD --------------------------------------------------
    dpo_nome = models.CharField("Encarregado de dados (DPO)", max_length=150, blank=True)
    dpo_email = models.EmailField("E-mail do DPO", blank=True)

    observacoes = models.TextField("Observações internas", blank=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ("razao_social",)
        indexes = [models.Index(fields=["ativo", "suspenso"])]

    def __str__(self):
        return self.nome_fantasia or self.razao_social

    def save(self, *args, **kwargs):
        self.cnpj = apenas_digitos(self.cnpj)
        super().save(*args, **kwargs)

    # -- apresentacao ------------------------------------------
    @property
    def cnpj_formatado(self) -> str:
        return formatar_cnpj(self.cnpj)

    @property
    def status(self) -> str:
        if self.suspenso:
            return "Suspenso"
        return "Ativo" if self.ativo else "Inativo"

    @property
    def operacional(self) -> bool:
        return self.ativo and not self.suspenso

    # -- limites do plano --------------------------------------
    @property
    def total_empresas(self) -> int:
        return self.empresas.count()

    @property
    def total_colaboradores(self) -> int:
        from apps.rh.models import Colaborador

        return Colaborador.objects.filter(
            empresa__cliente=self, ativo=True
        ).count()

    @property
    def total_totens(self) -> int:
        from apps.totem.models import Totem

        return Totem.objects.filter(empresa__cliente=self, ativo=True).count()

    def pode_adicionar_empresa(self) -> bool:
        return self.total_empresas < self.plano.max_empresas

    def pode_adicionar_colaborador(self) -> bool:
        return self.total_colaboradores < self.plano.max_colaboradores

    def pode_adicionar_totem(self) -> bool:
        return self.total_totens < self.plano.max_totems

    # -- API key -----------------------------------------------
    def gerar_api_key(self) -> str:
        """
        Gera uma nova API key. O valor em texto plano e retornado UMA
        unica vez; apenas o hash fica persistido (Secao 9).
        """
        chave = f"kr_{gerar_token(24)}"
        self.api_key_hash = hash_api_key(chave)
        self.api_key_prefixo = chave[:12]
        self.api_key_ativa = True
        self.api_key_gerada_em = timezone.now()
        self.save(
            update_fields=[
                "api_key_hash",
                "api_key_prefixo",
                "api_key_ativa",
                "api_key_gerada_em",
                "updated_at",
            ]
        )
        return chave

    def revogar_api_key(self):
        self.api_key_ativa = False
        self.save(update_fields=["api_key_ativa", "updated_at"])

    def suspender(self, motivo: str = ""):
        self.suspenso = True
        self.motivo_suspensao = motivo[:255]
        self.save(update_fields=["suspenso", "motivo_suspensao", "updated_at"])

    def reativar(self):
        self.suspenso = False
        self.motivo_suspensao = ""
        self.save(update_fields=["suspenso", "motivo_suspensao", "updated_at"])


class Empresa(BaseModel):
    """
    Empresa (CNPJ) vinculada a um Cliente. E a unidade de isolamento de
    dados: colaboradores, pontos, escalas e totens pertencem a uma Empresa.
    """

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="empresas",
        verbose_name="Cliente",
    )
    razao_social = models.CharField("Razão social", max_length=200)
    nome_fantasia = models.CharField("Nome fantasia", max_length=200, blank=True)
    cnpj = models.CharField(
        "CNPJ", max_length=14, unique=True, validators=[validar_cnpj], db_index=True
    )
    inscricao_estadual = models.CharField("Inscrição estadual", max_length=30, blank=True)
    cei_caepf = models.CharField(
        "CEI/CAEPF",
        max_length=20,
        blank=True,
        help_text="Usado no cabeçalho do AFD quando aplicável.",
    )

    # -- Endereco ----------------------------------------------
    cep = models.CharField("CEP", max_length=9, blank=True)
    logradouro = models.CharField("Logradouro", max_length=200, blank=True)
    numero = models.CharField("Número", max_length=20, blank=True)
    complemento = models.CharField("Complemento", max_length=100, blank=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True)
    cidade = models.CharField("Cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)

    # -- Personalizacao white-label (Secao 3.6) ----------------
    logo = models.ImageField("Logo", upload_to="logos/", null=True, blank=True)
    cor_primaria = models.CharField(
        "Cor primária",
        max_length=7,
        default="#1E3A5F",
        help_text="Hex. Substitui --kronus-primary-500/600 na interface do cliente.",
    )
    cor_secundaria = models.CharField(
        "Cor secundária",
        max_length=7,
        default="#D4A017",
        help_text="Hex. Substitui --kronus-gold-500.",
    )
    idle_screen_img = models.ImageField(
        "Imagem de ociosidade do totem",
        upload_to="idle_screens/",
        null=True,
        blank=True,
        help_text="Vertical, proporção 9:16 ou 10:16 (tablets 7\").",
    )
    msg_boas_vindas = models.CharField(
        "Mensagem de boas-vindas do totem", max_length=120, default="Registre seu ponto"
    )

    # -- Operacao ----------------------------------------------
    fuso_horario = models.CharField(
        "Fuso horário", max_length=50, default="America/Bahia"
    )
    modo_compensacao = models.CharField(
        "Modo de compensação",
        max_length=10,
        choices=ModoCompensacao.choices,
        default=ModoCompensacao.ATIVO,
    )
    permite_ver_ponto = models.BooleanField(
        "Colaborador pode ver os próprios registros",
        default=True,
        help_text="Controla o acesso à tela /ponto/meus-pontos.",
    )

    # -- Geofencing (Secao 8.3) --------------------------------
    geofencing_ativo = models.BooleanField("Geofencing ativo", default=False)
    geofencing_lat = models.DecimalField(
        "Latitude do ponto central", max_digits=10, decimal_places=7, null=True, blank=True
    )
    geofencing_lng = models.DecimalField(
        "Longitude do ponto central",
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )
    geofencing_raio = models.PositiveIntegerField(
        "Raio autorizado (metros)", default=200
    )
    geofencing_bloqueia = models.BooleanField(
        "Bloquear registro fora da área",
        default=False,
        help_text="Se desmarcado, o registro é aceito e sinalizado com a flag 'fora da área'.",
    )

    # -- Portaria 671 ------------------------------------------
    nsr_atual = models.PositiveBigIntegerField(
        "NSR atual",
        default=0,
        help_text="Número Sequencial de Registro — incrementado a cada batida.",
    )
    salt_registro = models.CharField(
        "Salt de integridade",
        max_length=64,
        blank=True,
        help_text="Componente do hash SHA-256 dos registros desta empresa.",
    )

    ativo = models.BooleanField("Ativa", default=True, db_index=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ("razao_social",)
        indexes = [models.Index(fields=["cliente", "ativo"])]

    def __str__(self):
        return self.nome_exibicao

    def save(self, *args, **kwargs):
        self.cnpj = apenas_digitos(self.cnpj)
        if not self.salt_registro:
            self.salt_registro = gerar_token(24)
        criando = self._state.adding
        super().save(*args, **kwargs)
        if criando:
            ConfiguracaoEmpresa.objects.get_or_create(empresa=self)

    @property
    def nome_exibicao(self) -> str:
        return self.nome_fantasia or self.razao_social

    @property
    def cnpj_formatado(self) -> str:
        return formatar_cnpj(self.cnpj)

    @property
    def endereco_completo(self) -> str:
        partes = [
            f"{self.logradouro}, {self.numero}" if self.logradouro else "",
            self.bairro,
            f"{self.cidade}/{self.uf}" if self.cidade else "",
            self.cep,
        ]
        return " — ".join([p for p in partes if p])

    @property
    def configuracao(self):
        config, _ = ConfiguracaoEmpresa.objects.get_or_create(empresa=self)
        return config

    def proximo_nsr(self) -> int:
        """
        Reserva o proximo NSR de forma atomica (regra 2 da Secao 14:
        sequencial, sem lacunas nem repeticoes por empresa).

        Deve ser chamado dentro de uma transacao, com a linha travada
        por `select_for_update()`.
        """
        self.nsr_atual = models.F("nsr_atual") + 1
        self.save(update_fields=["nsr_atual"])
        self.refresh_from_db(fields=["nsr_atual"])
        return self.nsr_atual


class ConfiguracaoEmpresa(BaseModel):
    """
    Parametros operacionais da empresa (Secao 4.1).

    Criada automaticamente junto com a Empresa.
    """

    class FormatoExportacao(models.TextChoices):
        JSON = "json", "JSON"
        CSV = "csv", "CSV"
        AFD = "afd", "AFD (Portaria 671)"
        XLSX = "xlsx", "Excel (XLSX)"

    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        related_name="config",
        verbose_name="Empresa",
    )

    # -- Jornada -----------------------------------------------
    tolerancia_atraso_min = models.PositiveSmallIntegerField(
        "Tolerância de atraso (min)",
        default=5,
        help_text="Art. 58 §1º da CLT: até 5 min por marcação, 10 min diários.",
    )
    intervalo_minimo_min = models.PositiveSmallIntegerField(
        "Intervalo intrajornada mínimo (min)",
        default=60,
        help_text="Art. 71 da CLT: 1 hora para jornadas acima de 6h.",
    )
    jornada_diaria_padrao_min = models.PositiveSmallIntegerField(
        "Jornada diária padrão (min)", default=480
    )

    # -- Horas extras e adicionais -----------------------------
    hora_extra_percentual = models.PositiveSmallIntegerField(
        "Percentual de hora extra (%)", default=50
    )
    hora_extra_percentual_2 = models.PositiveSmallIntegerField(
        "Percentual da 3ª hora extra em diante (%)", default=70
    )
    hora_extra_percentual_dsr = models.PositiveSmallIntegerField(
        "Percentual em domingos e feriados (%)", default=100
    )
    limite_hora_extra_diaria_min = models.PositiveSmallIntegerField(
        "Limite diário de hora extra (min)", default=120
    )

    adicional_noturno = models.BooleanField("Calcular adicional noturno", default=True)
    adicional_noturno_percentual = models.PositiveSmallIntegerField(
        "Adicional noturno (%)", default=ADICIONAL_NOTURNO_PERCENTUAL_PADRAO
    )
    hora_ini_noturno = models.TimeField(
        "Início do período noturno", default=time(HORA_INICIO_NOTURNO_PADRAO, 0)
    )
    hora_fim_noturno = models.TimeField(
        "Fim do período noturno", default=time(HORA_FIM_NOTURNO_PADRAO, 0)
    )
    hora_noturna_reduzida = models.BooleanField(
        "Aplicar hora noturna reduzida (52min30s)", default=True
    )

    # -- Marcação ----------------------------------------------
    minutos_entre_marcacoes = models.PositiveSmallIntegerField(
        "Intervalo mínimo entre marcações (min)",
        default=10,
        validators=[MinValueValidator(0), MaxValueValidator(120)],
        help_text=(
            "Impede a batida em duplicidade por engano — o toque a mais no "
            "totem, o clique repetido. Zero desativa a trava."
        ),
    )

    # -- Reconhecimento facial ---------------------------------
    exigir_liveness = models.BooleanField(
        "Exigir prova de vida no totem",
        default=False,
        help_text=(
            "Pede um gesto e analisa vários quadros. Impede foto impressa e "
            "tela parada; NÃO impede vídeo gravado. Deixa o registro alguns "
            "segundos mais lento."
        ),
    )

    # -- Regime de horas extras --------------------------------
    class RegimeHoras(models.TextChoices):
        BANCO = "banco", "Banco de horas (compensação)"
        PAGAMENTO = "pagamento", "Pagamento de horas extras"
        AMBOS = "ambos", "Banco, com pagamento do excedente"

    regime_horas = models.CharField(
        "Regime de horas extras",
        max_length=10,
        choices=RegimeHoras.choices,
        default=RegimeHoras.BANCO,
        help_text=(
            "Define se o excedente vira crédito no banco ou hora extra a pagar. "
            "Muda o que a exportação para a folha envia."
        ),
    )
    exibir_custos_hora_extra = models.BooleanField(
        "Exibir custos de horas extras",
        default=False,
        help_text=(
            "Mostra o valor em reais das horas extras nos relatórios. "
            "Exige que os salários estejam preenchidos."
        ),
    )
    exibir_salarios = models.BooleanField(
        "Exibir salários no painel",
        default=False,
        help_text=(
            "Salário é dado sensível dentro da própria empresa. Desligado, "
            "o campo some das telas e dos relatórios do RH."
        ),
    )

    # -- Banco de horas ----------------------------------------
    modo_compensacao = models.BooleanField(
        "Compensação automática", default=True
    )
    fecha_banco_dia = models.PositiveSmallIntegerField(
        "Dia de fechamento do banco de horas",
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
    )
    prazo_compensacao_meses = models.PositiveSmallIntegerField(
        "Prazo de compensação (meses)", default=6
    )

    # -- Exportacao --------------------------------------------
    exporta_formato = models.CharField(
        "Formato de exportação padrão",
        max_length=6,
        choices=FormatoExportacao.choices,
        default=FormatoExportacao.AFD,
    )
    layout_folha_pagamento = models.CharField(
        "Layout de folha de pagamento",
        max_length=40,
        blank=True,
        help_text="Ex.: dominio, metadados, questor, customizado.",
    )

    # -- Notificacoes (Secao 8.7) ------------------------------
    notif_esq_ponto = models.BooleanField(
        "Notificar esquecimento de ponto", default=True
    )
    notif_banco_negativo = models.BooleanField(
        "Notificar banco de horas negativo", default=True
    )
    notif_comprovante_email = models.BooleanField(
        "Enviar comprovante por e-mail a cada batida", default=False
    )
    notif_totem_offline = models.BooleanField(
        "Notificar totem offline", default=True
    )
    email_notificacoes = models.EmailField(
        "E-mail para notificações do RH", blank=True
    )

    # -- Antifraude --------------------------------------------
    anti_fake_gps = models.BooleanField("Detectar GPS fictício", default=True)
    exige_foto_registro_web = models.BooleanField(
        "Exigir selfie no registro web", default=False
    )
    liveness_no_totem = models.BooleanField(
        "Exigir prova de vida no totem", default=False
    )

    # -- LGPD --------------------------------------------------
    apagar_foto_apos_encoding = models.BooleanField(
        "Descartar fotos após gerar o embedding",
        default=False,
        help_text="Minimização de dados (Seção 10 do plano).",
    )
    retencao_faces_dias = models.PositiveSmallIntegerField(
        "Retenção de dados faciais após desligamento (dias)", default=30
    )

    class Meta:
        verbose_name = "Configuração da empresa"
        verbose_name_plural = "Configurações das empresas"

    def __str__(self):
        return f"Configuração — {self.empresa.nome_exibicao}"
