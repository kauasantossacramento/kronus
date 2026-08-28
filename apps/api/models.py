"""
Kronus — credenciais e telemetria da API REST publica.

Existem duas famílias de credencial (Secao 7.4 do plano):

* **Chave do Cliente** (`clientes.Cliente.api_key_*`) — emitida pelo
  Master, alcanca todas as empresas do cliente.
* **Chave de Empresa** (`api.APIKey`) — emitida pelo Admin RH em
  Configurações › Integrações, restrita a uma empresa.

Em ambos os casos apenas o hash SHA-256 e persistido.
"""
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel
from apps.core.utils import gerar_token, hash_api_key


class APIKey(BaseModel):
    """Chave de integracao com escopo de uma empresa."""

    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name="Empresa",
    )
    nome = models.CharField(
        "Nome", max_length=100, help_text="Identifica a integração, ex.: 'ERP Domínio'."
    )
    chave_hash = models.CharField("Hash da chave", max_length=64, unique=True, db_index=True)
    prefixo = models.CharField("Prefixo", max_length=12, db_index=True)

    somente_leitura = models.BooleanField("Somente leitura", default=True)
    ips_permitidos = models.JSONField(
        "IPs permitidos", default=list, blank=True,
        help_text="Lista de IPs/CIDRs. Vazio = sem restrição de origem."
    )
    rate_limit_hora = models.PositiveIntegerField("Limite por hora", default=1000)

    ativa = models.BooleanField("Ativa", default=True, db_index=True)
    expira_em = models.DateTimeField("Expira em", null=True, blank=True)
    ultimo_uso = models.DateTimeField("Último uso", null=True, blank=True)
    total_requisicoes = models.PositiveBigIntegerField("Total de requisições", default=0)

    criada_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_keys_criadas",
        verbose_name="Criada por",
    )
    revogada_em = models.DateTimeField("Revogada em", null=True, blank=True)

    class Meta:
        verbose_name = "Chave de API"
        verbose_name_plural = "Chaves de API"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["empresa", "ativa"])]

    def __str__(self):
        return f"{self.nome} ({self.prefixo}…)"

    @classmethod
    def emitir(cls, *, empresa, nome, criada_por=None, **extra) -> tuple["APIKey", str]:
        """
        Cria uma chave e devolve `(objeto, chave_em_texto_plano)`.

        O texto plano so existe neste retorno — depois disso, apenas o hash.
        """
        chave = f"kr_{empresa.pk}_{gerar_token(24)}"
        objeto = cls.objects.create(
            empresa=empresa,
            nome=nome,
            chave_hash=hash_api_key(chave),
            prefixo=chave[:12],
            criada_por=criada_por,
            **extra,
        )
        return objeto, chave

    @property
    def valida(self) -> bool:
        if not self.ativa or self.revogada_em:
            return False
        if self.expira_em and self.expira_em < timezone.now():
            return False
        return True

    def revogar(self):
        self.ativa = False
        self.revogada_em = timezone.now()
        self.save(update_fields=["ativa", "revogada_em", "updated_at"])

    def registrar_uso(self):
        self.ultimo_uso = timezone.now()
        self.total_requisicoes = models.F("total_requisicoes") + 1
        self.save(update_fields=["ultimo_uso", "total_requisicoes"])


class RequisicaoAPI(BaseModel):
    """Telemetria de uso da API — base para cobranca e diagnostico."""

    api_key = models.ForeignKey(
        APIKey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requisicoes",
        verbose_name="Chave",
    )
    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="requisicoes_api",
        verbose_name="Empresa",
    )
    metodo = models.CharField("Método", max_length=8)
    caminho = models.CharField("Caminho", max_length=255)
    status_code = models.PositiveSmallIntegerField("Status HTTP")
    duracao_ms = models.PositiveIntegerField("Duração (ms)", default=0)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)

    class Meta:
        verbose_name = "Requisição da API"
        verbose_name_plural = "Requisições da API"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["empresa", "-created_at"]),
            models.Index(fields=["api_key", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.metodo} {self.caminho} — {self.status_code}"
