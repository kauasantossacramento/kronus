"""
Kronus — captacao comercial: contato configuravel e demonstracao de 24h.

Duas coisas moram aqui:

1. `ConfiguracaoComercial` — o WhatsApp e o e-mail que aparecem na capa.
   Estavam escritos no template, o que obrigava um deploy para trocar um
   numero de telefone. Numero de contato e dado operacional, nao codigo.

2. `SolicitacaoDemonstracao` — o visitante cria o proprio ambiente de
   teste e recebe o link na hora. A alternativa (esperar um humano
   responder) perde o interessado no momento em que ele esta com a
   atencao no produto.
"""
import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class ConfiguracaoComercial(BaseModel):
    """
    Registro unico com os dados de contato e as regras da demonstracao.

    Segue o mesmo padrao de `ConfiguracaoGateway`: uma linha so, carregada
    por `carregar()`, que cria a linha na primeira chamada.
    """

    whatsapp = models.CharField(
        "WhatsApp",
        max_length=20,
        blank=True,
        help_text="Somente digitos, com DDI e DDD. Ex.: 5573988310101",
    )
    whatsapp_mensagem = models.CharField(
        "Mensagem inicial do WhatsApp",
        max_length=255,
        default="Olá, quero conhecer o Kronus.",
        help_text="Texto que ja vem digitado quando a conversa abre.",
    )
    email_contato = models.EmailField("E-mail de contato", blank=True)
    telefone = models.CharField("Telefone fixo", max_length=20, blank=True)

    # -- demonstracao ------------------------------------------
    demo_ativa = models.BooleanField(
        "Demonstração automática ativa",
        default=True,
        help_text="Desligado, a capa passa a oferecer apenas o contato direto.",
    )
    demo_horas = models.PositiveSmallIntegerField(
        "Duração da demonstração (horas)", default=24
    )
    demo_limite_diario = models.PositiveSmallIntegerField(
        "Limite de demonstrações por dia",
        default=20,
        help_text="Protege contra criação automatizada em massa.",
    )

    # -- aparencia do painel -----------------------------------
    #
    # Tamanho das marcas no administrativo. Fixos no CSS, eles ficavam
    # pequenos demais numa tela grande e grandes demais numa pequena, e
    # trocar exigia deploy — para um ajuste que e questao de gosto e de
    # monitor.
    logo_kronus_altura_px = models.PositiveSmallIntegerField(
        "Altura da marca Kronus no painel (px)",
        default=32,
        validators=[MinValueValidator(16), MaxValueValidator(96)],
    )
    logo_kstec_altura_px = models.PositiveSmallIntegerField(
        "Altura da marca KS TEC no painel (px)",
        default=16,
        validators=[MinValueValidator(10), MaxValueValidator(72)],
    )

    class Meta:
        verbose_name = "Configuração comercial"
        verbose_name_plural = "Configuração comercial"

    def __str__(self):
        return "Configuração comercial"

    @classmethod
    def carregar(cls) -> "ConfiguracaoComercial":
        config = cls.objects.first()
        if config is None:
            config = cls.objects.create()
        return config

    @property
    def link_whatsapp(self) -> str:
        """URL pronta do wa.me, ou vazio quando nao ha numero configurado."""
        if not self.whatsapp:
            return ""
        from urllib.parse import quote

        numero = "".join(c for c in self.whatsapp if c.isdigit())
        return f"https://wa.me/{numero}?text={quote(self.whatsapp_mensagem)}"

    @property
    def whatsapp_formatado(self) -> str:
        numero = "".join(c for c in self.whatsapp if c.isdigit())
        if len(numero) == 13:  # 55 + DDD + 9 digitos
            return f"+{numero[:2]} ({numero[2:4]}) {numero[4:9]}-{numero[9:]}"
        return self.whatsapp


class SolicitacaoDemonstracao(BaseModel):
    """
    Um pedido de demonstracao e o ambiente que ele gerou.

    O ambiente e um `Cliente` de verdade, marcado como demonstracao — nao
    um modo especial do sistema. Assim o visitante ve exatamente o produto
    que vai contratar, e a conversao e so tirar a marca de demonstracao,
    sem migrar dado nenhum.
    """

    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        EXPIRADA = "expirada", "Expirada"
        CONVERTIDA = "convertida", "Convertida em cliente"
        CANCELADA = "cancelada", "Cancelada"

    nome = models.CharField("Nome do interessado", max_length=150)
    empresa = models.CharField("Empresa", max_length=200)
    email = models.EmailField("E-mail")
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True)
    porte = models.CharField(
        "Nº de colaboradores", max_length=30, blank=True
    )

    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="demonstracoes",
        verbose_name="Ambiente gerado",
    )
    # Senha em texto claro nao e guardada: o link leva ao login e a senha
    # so existe no e-mail enviado no momento da criacao.
    token = models.CharField("Token do link", max_length=43, unique=True, db_index=True)
    expira_em = models.DateTimeField("Expira em", db_index=True)
    status = models.CharField(
        "Situação", max_length=12, choices=Status.choices,
        default=Status.ATIVA, db_index=True,
    )

    ip = models.GenericIPAddressField("IP de origem", null=True, blank=True)
    user_agent = models.CharField("User-Agent", max_length=255, blank=True)
    acessos = models.PositiveIntegerField("Acessos", default=0)
    primeiro_acesso_em = models.DateTimeField(
        "Primeiro acesso", null=True, blank=True
    )
    ultimo_acesso_em = models.DateTimeField("Último acesso", null=True, blank=True)
    convertida_em = models.DateTimeField("Convertida em", null=True, blank=True)
    observacoes = models.TextField("Observações internas", blank=True)

    class Meta:
        verbose_name = "Solicitação de demonstração"
        verbose_name_plural = "Solicitações de demonstração"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("status", "expira_em"))]

    def __str__(self):
        return f"{self.empresa} ({self.get_status_display()})"

    @staticmethod
    def novo_token() -> str:
        return secrets.token_urlsafe(32)[:43]

    @property
    def expirada(self) -> bool:
        return timezone.now() >= self.expira_em

    @property
    def horas_restantes(self) -> int:
        restante = self.expira_em - timezone.now()
        return max(0, int(restante.total_seconds() // 3600))
