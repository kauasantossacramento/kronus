"""
Kronus — models do painel Master (KS TEC).

Contem a modelagem comercial da plataforma: planos vendidos, limites
contratuais e a trilha de acesso administrativo.
"""
from django.db import models

from apps.core.models import BaseModel


class Plano(BaseModel):
    """
    Plano comercial contratado por um Cliente (Secao 4.1 do plano).

    Os campos `max_*` sao limites rigidos verificados no cadastro; os
    campos `tem_*` habilitam funcionalidades (ver `core.decorators.plano_requer`).
    """

    nome = models.CharField("Nome", max_length=60, unique=True)
    slug = models.SlugField("Slug", max_length=60, unique=True)
    descricao = models.TextField("Descrição", blank=True)
    destaque = models.BooleanField(
        "Destacar na landing", default=False, help_text="Marca o plano como recomendado."
    )
    ordem = models.PositiveSmallIntegerField("Ordem de exibição", default=0)

    # -- Limites -----------------------------------------------
    max_empresas = models.PositiveIntegerField("Máx. de empresas", default=1)
    max_colaboradores = models.PositiveIntegerField("Máx. de colaboradores", default=25)
    max_totems = models.PositiveIntegerField("Máx. de totens", default=0)

    # -- Comercial ---------------------------------------------
    preco_mensal = models.DecimalField(
        "Preço mensal (R$)", max_digits=10, decimal_places=2, default=0
    )
    preco_por_colaborador = models.DecimalField(
        "Preço adicional por colaborador (R$)",
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    # -- Funcionalidades ---------------------------------------
    tem_api = models.BooleanField("API REST", default=False)
    tem_geofencing = models.BooleanField("Geofencing", default=False)
    tem_totem = models.BooleanField("Totem facial", default=False)
    tem_offline = models.BooleanField("Modo offline do totem", default=False)
    tem_banco_horas = models.BooleanField("Banco de horas", default=True)
    tem_webhook = models.BooleanField("Webhooks", default=False)
    tem_portal_contador = models.BooleanField("Portal do contador", default=False)
    tem_esocial = models.BooleanField("Exportação eSocial", default=False)

    rate_limit_api_hora = models.PositiveIntegerField(
        "Limite de requisições da API por hora", default=1000
    )
    ativo = models.BooleanField("Disponível para contratação", default=True)

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"
        ordering = ("ordem", "preco_mensal")

    def __str__(self):
        return self.nome

    @property
    def recursos_habilitados(self) -> list[str]:
        rotulos = {
            "tem_api": "API REST",
            "tem_geofencing": "Geofencing",
            "tem_totem": "Totem com reconhecimento facial",
            "tem_offline": "Modo offline",
            "tem_banco_horas": "Banco de horas",
            "tem_webhook": "Webhooks",
            "tem_portal_contador": "Portal do contador",
            "tem_esocial": "Exportação eSocial",
        }
        return [texto for campo, texto in rotulos.items() if getattr(self, campo)]


class LogAcessoMaster(BaseModel):
    """
    Acoes administrativas do Master sobre clientes (suspensao, criacao,
    regeneracao de API key). Separado de `core.LogAcesso` por ter
    retencao e criticidade proprias.
    """

    class Acao(models.TextChoices):
        CLIENTE_CRIADO = "cliente_criado", "Cliente criado"
        CLIENTE_EDITADO = "cliente_editado", "Cliente editado"
        CLIENTE_SUSPENSO = "cliente_suspenso", "Cliente suspenso"
        CLIENTE_REATIVADO = "cliente_reativado", "Cliente reativado"
        EMPRESA_VINCULADA = "empresa_vinculada", "Empresa vinculada"
        EMPRESA_DESVINCULADA = "empresa_desvinculada", "Empresa desvinculada"
        PLANO_ALTERADO = "plano_alterado", "Plano alterado"
        API_KEY_GERADA = "api_key_gerada", "API key gerada/regenerada"
        API_KEY_REVOGADA = "api_key_revogada", "API key revogada"
        TOTEM_CADASTRADO = "totem_cadastrado", "Totem cadastrado"
        TOTEM_COMODATO = "totem_comodato", "Comodato registrado"
        TOTEM_DEVOLVIDO = "totem_devolvido", "Totem devolvido"
        CONFIG_ALTERADA = "config_alterada", "Configuração da plataforma alterada"
        DEMO_PRORROGADA = "demo_prorrogada", "Demonstração prorrogada"
        DEMO_CONVERTIDA = "demo_convertida", "Demonstração convertida em cliente"
        DEMO_ENCERRADA = "demo_encerrada", "Demonstração encerrada"

    usuario = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="acoes_master",
        verbose_name="Operador",
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs_master",
        verbose_name="Cliente",
    )
    acao = models.CharField("Ação", max_length=25, choices=Acao.choices)
    detalhes = models.TextField("Detalhes", blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)

    class Meta:
        verbose_name = "Log do Master"
        verbose_name_plural = "Logs do Master"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_acao_display()} — {self.cliente or '—'}"

    def delete(self, *args, **kwargs):  # pragma: no cover
        raise PermissionError("Logs do Master são imutáveis.")
