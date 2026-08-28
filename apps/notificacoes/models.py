"""
Kronus — notificacoes in-app e por e-mail (Secao 8.7 do plano).
"""
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class Notificacao(BaseModel):
    class Evento(models.TextChoices):
        ESQUECIMENTO_PONTO = "esquecimento_ponto", "Esquecimento de ponto"
        PONTO_REGISTRADO = "ponto_registrado", "Ponto registrado"
        BANCO_NEGATIVO = "banco_negativo", "Banco de horas negativo"
        ATESTADO_PENDENTE = "atestado_pendente", "Atestado pendente"
        TOTEM_OFFLINE = "totem_offline", "Totem offline"
        JUSTIFICATIVA_PENDENTE = "justificativa_pendente", "Justificativa pendente"
        ESPELHO_PENDENTE = "espelho_pendente", "Assinatura de espelho pendente"
        FRAUDE_GPS = "fraude_gps", "Tentativa de fraude (GPS fictício)"
        FACIAL_DEGRADADO = (
            "facial_degradado", "Reconhecimento facial perdendo precisão"
        )
        SISTEMA = "sistema", "Aviso do sistema"

    class Canal(models.TextChoices):
        IN_APP = "in_app", "No sistema"
        EMAIL = "email", "E-mail"
        AMBOS = "ambos", "E-mail e sistema"

    class Nivel(models.TextChoices):
        INFO = "info", "Informação"
        SUCESSO = "sucesso", "Sucesso"
        ALERTA = "alerta", "Alerta"
        ERRO = "erro", "Erro"

    destinatario = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="notificacoes",
        verbose_name="Destinatário",
    )
    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notificacoes",
        verbose_name="Empresa",
    )
    evento = models.CharField("Evento", max_length=25, choices=Evento.choices, db_index=True)
    nivel = models.CharField("Nível", max_length=10, choices=Nivel.choices, default=Nivel.INFO)
    canal = models.CharField("Canal", max_length=6, choices=Canal.choices, default=Canal.IN_APP)

    titulo = models.CharField("Título", max_length=150)
    mensagem = models.TextField("Mensagem")
    url_acao = models.CharField("URL de ação", max_length=255, blank=True)
    metadados = models.JSONField("Metadados", default=dict, blank=True)

    lida = models.BooleanField("Lida", default=False, db_index=True)
    lida_em = models.DateTimeField("Lida em", null=True, blank=True)
    enviada_email = models.BooleanField("E-mail enviado", default=False)
    enviada_email_em = models.DateTimeField("E-mail enviado em", null=True, blank=True)

    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["destinatario", "lida", "-created_at"]),
            models.Index(fields=["evento", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.titulo} — {self.destinatario}"

    def marcar_lida(self):
        if not self.lida:
            self.lida = True
            self.lida_em = timezone.now()
            self.save(update_fields=["lida", "lida_em", "updated_at"])


class Webhook(BaseModel):
    """
    Notificacao de eventos para sistemas externos (Secao 8.8).

    O `segredo` assina o payload em `X-Kronus-Signature` (HMAC-SHA256),
    permitindo ao receptor validar a origem.
    """

    class Evento(models.TextChoices):
        PONTO_REGISTRADO = "ponto.registrado", "Ponto registrado"
        PONTO_AJUSTADO = "ponto.ajustado", "Ponto ajustado"
        COLABORADOR_CRIADO = "colaborador.criado", "Colaborador criado"
        COLABORADOR_DESLIGADO = "colaborador.desligado", "Colaborador desligado"
        ATESTADO_APROVADO = "atestado.aprovado", "Atestado aprovado"
        FECHAMENTO_CONCLUIDO = "fechamento.concluido", "Fechamento concluído"
        TOTEM_OFFLINE = "totem.offline", "Totem offline"

    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="webhooks",
        verbose_name="Empresa",
    )
    nome = models.CharField("Nome", max_length=100)
    url = models.URLField("URL de destino", max_length=500)
    eventos = models.JSONField(
        "Eventos assinados", default=list, help_text="Lista de códigos de evento."
    )
    segredo = models.CharField("Segredo (HMAC)", max_length=64)
    ativo = models.BooleanField("Ativo", default=True)

    ultima_entrega = models.DateTimeField("Última entrega", null=True, blank=True)
    ultimo_status = models.PositiveSmallIntegerField(
        "Último status HTTP", null=True, blank=True
    )
    falhas_consecutivas = models.PositiveSmallIntegerField("Falhas consecutivas", default=0)

    class Meta:
        verbose_name = "Webhook"
        verbose_name_plural = "Webhooks"
        ordering = ("nome",)

    def __str__(self):
        return f"{self.nome} → {self.url}"

    def save(self, *args, **kwargs):
        if not self.segredo:
            from apps.core.utils import gerar_token

            self.segredo = gerar_token(24)
        super().save(*args, **kwargs)

    def assina(self, evento: str) -> bool:
        return self.ativo and evento in (self.eventos or [])


class Lead(BaseModel):
    """Contato capturado no formulario da landing page (Secao 6.1)."""

    class Situacao(models.TextChoices):
        NOVO = "novo", "Novo"
        EM_CONTATO = "em_contato", "Em contato"
        QUALIFICADO = "qualificado", "Qualificado"
        CONVERTIDO = "convertido", "Convertido"
        DESCARTADO = "descartado", "Descartado"

    nome = models.CharField("Nome", max_length=150)
    email = models.EmailField("E-mail")
    telefone = models.CharField("Telefone", max_length=20, blank=True)
    empresa = models.CharField("Empresa", max_length=150, blank=True)
    num_colaboradores = models.CharField("Nº de colaboradores", max_length=30, blank=True)
    mensagem = models.TextField("Mensagem", blank=True)
    plano_interesse = models.ForeignKey(
        "master.Plano",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Plano de interesse",
    )
    origem = models.CharField("Origem", max_length=60, blank=True, default="landing")
    situacao = models.CharField(
        "Situação", max_length=12, choices=Situacao.choices, default=Situacao.NOVO
    )
    ip = models.GenericIPAddressField("IP", null=True, blank=True)

    class Meta:
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.nome} — {self.empresa or self.email}"


class EntregaWebhook(BaseModel):
    """
    Uma tentativa de entrega de um evento a um webhook.

    Existe para que uma falha de rede não apague o evento. O payload é
    congelado no momento do disparo: se o registro de ponto for
    cancelado depois, a entrega ainda descreve o que aconteceu quando
    aconteceu — reenviar precisa reproduzir o fato original, não o
    estado atual do banco.

    O `identificador` vai no header `X-Kronus-Delivery` e é estável
    entre retentativas: é assim que o receptor deduplica quando nos
    responde 500 depois de já ter processado.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ENTREGUE = "entregue", "Entregue"
        DESISTIU = "desistiu", "Desistiu"

    webhook = models.ForeignKey(
        Webhook,
        on_delete=models.CASCADE,
        related_name="entregas",
        verbose_name="Webhook",
    )
    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="entregas_webhook",
        verbose_name="Empresa",
    )
    evento = models.CharField("Evento", max_length=40, db_index=True)
    identificador = models.UUIDField("Identificador da entrega", db_index=True)
    payload = models.JSONField("Payload enviado", default=dict)

    status = models.CharField(
        "Status", max_length=10, choices=Status.choices,
        default=Status.PENDENTE, db_index=True,
    )
    tentativas = models.PositiveSmallIntegerField("Tentativas", default=0)
    ultima_tentativa = models.DateTimeField("Última tentativa", null=True, blank=True)
    proxima_tentativa = models.DateTimeField(
        "Próxima tentativa", null=True, blank=True, db_index=True
    )
    entregue_em = models.DateTimeField("Entregue em", null=True, blank=True)
    status_code = models.PositiveSmallIntegerField(
        "Status HTTP", null=True, blank=True
    )
    resposta = models.CharField("Resposta do receptor", max_length=500, blank=True)

    class Meta:
        verbose_name = "Entrega de webhook"
        verbose_name_plural = "Entregas de webhook"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["webhook", "-created_at"]),
            models.Index(fields=["status", "proxima_tentativa"]),
        ]

    def __str__(self):
        return f"{self.evento} → {self.webhook.nome} ({self.get_status_display()})"

    @property
    def pode_retentar(self) -> bool:
        return (
            self.status == self.Status.PENDENTE
            and self.proxima_tentativa is not None
            and self.proxima_tentativa <= timezone.now()
        )
