"""
Kronus — models base compartilhados.

Fornece:
    * BaseModel        — timestamps + soft-delete
    * TenantBaseModel  — BaseModel + escopo obrigatorio de empresa
    * LogAcesso        — trilha de auditoria (Secao 4.1 e 8.8 do plano)
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


# ==============================================================
# Managers
# ==============================================================
class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet que entende o campo `deleted_at`."""

    def ativos(self):
        return self.filter(deleted_at__isnull=True)

    def excluidos(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):
        """Soft-delete em massa."""
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Manager padrao: esconde registros soft-deletados."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(
            deleted_at__isnull=True
        )


class AllObjectsManager(models.Manager):
    """Manager irrestrito — inclui registros soft-deletados."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


# ==============================================================
# Models base
# ==============================================================
class BaseModel(models.Model):
    """
    Base de todos os models do Kronus.

    * `uuid`        — identificador publico, usado em URLs e na API
    * `created_at`  — carimbo de criacao
    * `updated_at`  — carimbo de ultima alteracao
    * `deleted_at`  — soft-delete (nunca removemos linhas com valor legal)
    """

    uuid = models.UUIDField(
        "UUID", default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    created_at = models.DateTimeField("Criado em", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)
    deleted_at = models.DateTimeField("Excluído em", null=True, blank=True, editable=False)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True
        ordering = ("-created_at",)

    # -- soft delete -------------------------------------------
    def delete(self, using=None, keep_parents=False, hard=False):
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])
        return (1, {self._meta.label: 1})

    def restaurar(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])

    @property
    def excluido(self) -> bool:
        return self.deleted_at is not None


class TenantBaseModel(BaseModel):
    """
    Base para models isolados por empresa (row-level tenancy).

    O isolamento multi-tenant do Kronus e por linha (shared schema):
    todo model de dominio carrega `empresa`, e o acesso e filtrado pelo
    escopo do usuario autenticado (ver apps.core.mixins.TenantScopedMixin).
    """

    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="%(class)s_set",
        verbose_name="Empresa",
        db_index=True,
    )

    class Meta:
        abstract = True
        ordering = ("-created_at",)


# ==============================================================
# Auditoria (Secao 8.8 — "Auditoria completa")
# ==============================================================
class LogAcesso(BaseModel):
    """
    Registro imutavel de acoes relevantes: quem fez, quando, o que, de onde.
    """

    class Acao(models.TextChoices):
        LOGIN = "login", "Login"
        LOGIN_FALHA = "login_falha", "Tentativa de login malsucedida"
        LOGOUT = "logout", "Logout"
        CRIACAO = "criacao", "Criação de registro"
        ALTERACAO = "alteracao", "Alteração de registro"
        EXCLUSAO = "exclusao", "Exclusão de registro"
        PONTO = "ponto", "Registro de ponto"
        AJUSTE_PONTO = "ajuste_ponto", "Ajuste manual de ponto"
        DOWNLOAD = "download", "Download de arquivo/relatório"
        API = "api", "Acesso via API"
        CONFIG = "config", "Alteração de configuração"
        SEGURANCA = "seguranca", "Evento de segurança"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs_acesso",
        verbose_name="Usuário",
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs_acesso",
        verbose_name="Cliente",
    )
    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs_acesso",
        verbose_name="Empresa",
    )
    acao = models.CharField("Ação", max_length=20, choices=Acao.choices, db_index=True)
    descricao = models.CharField("Descrição", max_length=255, blank=True)
    objeto_tipo = models.CharField("Tipo do objeto", max_length=100, blank=True)
    objeto_id = models.CharField("ID do objeto", max_length=64, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.TextField("User agent", blank=True)
    metadados = models.JSONField("Metadados", default=dict, blank=True)

    class Meta:
        verbose_name = "Log de acesso"
        verbose_name_plural = "Logs de acesso"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["cliente", "-created_at"]),
            models.Index(fields=["usuario", "-created_at"]),
            models.Index(fields=["acao", "-created_at"]),
        ]

    def __str__(self):
        quem = self.usuario or "anônimo"
        return f"{quem} — {self.get_acao_display()} em {self.created_at:%d/%m/%Y %H:%M}"

    # Logs sao append-only (Secao 9 do plano)
    def delete(self, *args, **kwargs):  # pragma: no cover
        raise PermissionError("Logs de acesso são imutáveis e não podem ser excluídos.")


class Feriado(BaseModel):
    """
    Feriados nacionais, estaduais e municipais (Secao 8.8).

    Feriados nacionais tem `empresa` nulo e valem para toda a plataforma.
    """

    class Abrangencia(models.TextChoices):
        NACIONAL = "nacional", "Nacional"
        ESTADUAL = "estadual", "Estadual"
        MUNICIPAL = "municipal", "Municipal"
        EMPRESA = "empresa", "Interno da empresa"

    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="feriados",
        verbose_name="Empresa",
        help_text="Vazio = feriado válido para toda a plataforma.",
    )
    nome = models.CharField("Nome", max_length=120)
    data = models.DateField("Data", db_index=True)
    abrangencia = models.CharField(
        "Abrangência",
        max_length=12,
        choices=Abrangencia.choices,
        default=Abrangencia.NACIONAL,
    )
    uf = models.CharField("UF", max_length=2, blank=True)
    municipio = models.CharField("Município", max_length=100, blank=True)
    recorrente = models.BooleanField(
        "Recorrente", default=False, help_text="Repete todo ano na mesma data."
    )
    meio_periodo = models.BooleanField("Meio período", default=False)

    class Meta:
        verbose_name = "Feriado"
        verbose_name_plural = "Feriados"
        ordering = ("data",)
        indexes = [models.Index(fields=["empresa", "data"])]

    def __str__(self):
        return f"{self.nome} — {self.data:%d/%m/%Y}"
