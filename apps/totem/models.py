"""
Kronus — equipamentos de totem.

`GrupoTotem` pertence ao Cliente e permite compartilhar um conjunto de
totens entre empresas do mesmo grupo economico. Um colaborador so e
reconhecido em totens da sua empresa ou do grupo vinculado (regra 12
da Secao 14 do plano).
"""
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel
from apps.core.utils import gerar_token


class GrupoTotem(BaseModel):
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.CASCADE,
        related_name="grupos_totem",
        verbose_name="Cliente",
    )
    nome = models.CharField("Nome", max_length=100)
    descricao = models.CharField("Descrição", max_length=255, blank=True)
    empresas = models.ManyToManyField(
        "clientes.Empresa",
        blank=True,
        related_name="grupos_totem",
        verbose_name="Empresas atendidas",
        help_text="Colaboradores destas empresas são reconhecidos nos totens do grupo.",
    )
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Grupo de totens"
        verbose_name_plural = "Grupos de totens"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=["cliente", "nome"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_grupo_totem_por_cliente",
            )
        ]

    def __str__(self):
        return self.nome

    @property
    def total_totens(self) -> int:
        return self.totens.filter(ativo=True).count()


class Totem(BaseModel):
    """
    Equipamento fisico (tablet) rodando a interface de quiosque.

    Autenticacao por token opaco na URL `/totem/<token_acesso>/` e no
    header `Authorization: Token ...` das chamadas de API.
    """

    #: Minutos sem heartbeat apos os quais o totem e considerado offline
    #: (Secao 8.7 — alerta de "totem offline > 10min").
    MINUTOS_PARA_OFFLINE = 10

    #: Prefixo do patrimonio. O equipamento e da KS TEC, inclusive
    #: quando esta em comodato na empresa cliente — e a etiqueta colada
    #: nele precisa dizer isso a quem o encontrar.
    PREFIXO_PATRIMONIO = "KST"

    identificador = models.CharField(
        "Identificador", max_length=40, unique=True, db_index=True,
        blank=True,
        help_text=(
            "Gerado pelo sistema no formato KST-AAAA-NNNN. "
            "Deixe em branco para gerar."
        ),
    )
    apelido = models.CharField("Apelido", max_length=100, blank=True)
    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="totens",
        verbose_name="Empresa",
    )
    grupo = models.ForeignKey(
        GrupoTotem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="totens",
        verbose_name="Grupo",
    )
    local_instalacao = models.CharField("Local de instalação", max_length=150, blank=True)

    # -- Equipamento / comodato --------------------------------
    modelo_tablet = models.CharField(
        "Modelo do tablet", max_length=100, blank=True, default="Positivo Tab 7 Vision"
    )
    serial_tablet = models.CharField("Serial", max_length=60, blank=True)
    em_comodato = models.BooleanField("Em comodato", default=False)
    data_instalacao = models.DateField("Data de instalação", null=True, blank=True)
    data_devolucao = models.DateField("Data de devolução", null=True, blank=True)
    contrato_comodato = models.FileField(
        "Contrato de comodato", upload_to="comodatos/", null=True, blank=True
    )

    # -- Operacao ----------------------------------------------
    token_acesso = models.CharField(
        "Token de acesso", max_length=64, unique=True, db_index=True
    )
    #: Preenchido pelo proprio totem no heartbeat, nunca digitado.
    #:
    #: Versao digitada envelhece em silencio: alguem cadastra "1.0" e o
    #: campo continua dizendo "1.0" tres atualizacoes depois. Vindo do
    #: aparelho, o valor responde a pergunta que importa no suporte —
    #: "este totem esta rodando a versao atual?".
    versao_firmware = models.CharField(
        "Versão do app", max_length=20, blank=True,
        help_text="Informada pelo próprio totem a cada sinal de vida.",
    )
    ultimo_heartbeat = models.DateTimeField("Último heartbeat", null=True, blank=True)
    ultimo_ip = models.GenericIPAddressField("Último IP", null=True, blank=True)
    bateria_percentual = models.PositiveSmallIntegerField(
        "Bateria (%)", null=True, blank=True
    )
    ativo = models.BooleanField("Ativo", default=True, db_index=True)

    # -- Configuracao da interface -----------------------------
    #: Saida de emergencia quando o rosto nao e reconhecido.
    #:
    #: O reconhecimento facial falha por motivos banais — barba nova,
    #: oculos, contraluz, camera suja, gemeo. Sem alternativa, a pessoa
    #: fica impedida de registrar o ponto, e a empresa passa a ter um
    #: problema trabalhista, nao um problema tecnico. Com o fallback, ela
    #: digita o CPF e a batida acontece, marcada como registro por
    #: digitacao para que o RH saiba o que aconteceu.
    #:
    #: Desligar so faz sentido em operacao onde a identificacao por rosto
    #: e obrigatoria por politica interna — e mesmo ali, alguem precisa
    #: garantir outro caminho para quem o sistema nao reconhecer.
    permite_fallback_cpf = models.BooleanField(
        "Permitir digitar o CPF quando o rosto não for reconhecido",
        default=True,
        help_text=(
            "Saída de emergência do totem. Sem ela, quem o reconhecimento "
            "facial não identificar fica sem registrar o ponto."
        ),
    )
    segundos_tela_sucesso = models.PositiveSmallIntegerField(
        "Segundos na tela de sucesso", default=5
    )
    segundos_countdown_offline = models.PositiveSmallIntegerField(
        "Segundos do countdown offline", default=120
    )
    observacoes = models.TextField("Observações", blank=True)

    #: Pedido pontual de recarga, atendido no proximo heartbeat.
    #: Diferente da versao de configuracao da empresa: serve para o
    #: suporte destravar **um** equipamento sem mexer nos outros.
    recarga_solicitada_em = models.DateTimeField(
        "Recarga solicitada em", null=True, blank=True
    )

    class Meta:
        verbose_name = "Totem"
        verbose_name_plural = "Totens"
        ordering = ("identificador",)
        indexes = [
            models.Index(fields=["empresa", "ativo"]),
            models.Index(fields=["-ultimo_heartbeat"]),
        ]

    def __str__(self):
        return self.apelido or self.identificador

    def save(self, *args, **kwargs):
        if not self.token_acesso:
            self.token_acesso = gerar_token(32)

        # O patrimonio sai do `pk`, que o banco nunca reaproveita. Contar
        # os totens existentes devolveria um numero ja emitido assim que
        # o ultimo fosse excluido — e duas etiquetas iguais em clientes
        # diferentes e o tipo de erro que so aparece quando ja e caro.
        # Como o `pk` so existe depois do INSERT, a criacao grava um
        # marcador unico e o troca em seguida.
        provisorio = False
        if not self.identificador:
            self.identificador = f"novo-{gerar_token(16)}"
            provisorio = True

        super().save(*args, **kwargs)

        if provisorio:
            self.identificador = self.montar_identificador()
            # `update_fields` restrito: um `save()` completo aqui
            # dispararia de novo toda a logica acima.
            super().save(update_fields=["identificador"])

    # -- estado ------------------------------------------------
    @property
    def online(self) -> bool:
        if not self.ultimo_heartbeat:
            return False
        limite = timezone.now() - timezone.timedelta(minutes=self.MINUTOS_PARA_OFFLINE)
        return self.ultimo_heartbeat >= limite

    @property
    def status(self) -> str:
        if not self.ativo:
            return "Inativo"
        return "Online" if self.online else "Offline"

    @property
    def minutos_desde_heartbeat(self) -> int | None:
        if not self.ultimo_heartbeat:
            return None
        return int((timezone.now() - self.ultimo_heartbeat).total_seconds() // 60)

    @property
    def url_kiosk(self) -> str:
        return f"/totem/{self.token_acesso}/"

    # -- identidade do equipamento -----------------------------
    def montar_identificador(self) -> str:
        """
        Patrimonio no formato `KST-AAAA-NNNNN`.

        O ano diz quando o equipamento entrou na frota; o numero vem do
        `pk`, que e unico para sempre. A sequencia nao e continua dentro
        do ano — e nem precisa ser: numero de patrimonio serve para
        identificar um aparelho, nao para contar quantos existem.
        """
        ano = (self.created_at or timezone.now()).year
        return f"{self.PREFIXO_PATRIMONIO}-{ano}-{self.pk:05d}"

    @property
    def codigo_autenticidade(self) -> str:
        """
        Codigo publico de conferencia, impresso na etiqueta.

        Derivado do token de acesso, **nunca o proprio token**: a
        etiqueta fica visivel em recepcao, e quem a fotografa nao pode
        sair com a credencial que abre o totem. Um digest truncado
        confirma a autenticidade sem conceder acesso.
        """
        import hashlib

        from django.conf import settings

        semente = f"{self.pk}|{self.token_acesso}|{settings.SECRET_KEY}"
        return hashlib.sha256(semente.encode()).hexdigest()[:12].upper()

    @property
    def url_autenticidade(self) -> str:
        return f"/totem/autenticidade/{self.codigo_autenticidade}/"

    def registrar_heartbeat(self, ip=None, versao=None, bateria=None):
        self.ultimo_heartbeat = timezone.now()
        campos = ["ultimo_heartbeat", "updated_at"]
        if ip:
            self.ultimo_ip = ip
            campos.append("ultimo_ip")
        if versao:
            self.versao_firmware = versao[:20]
            campos.append("versao_firmware")
        if bateria is not None:
            self.bateria_percentual = max(0, min(100, int(bateria)))
            campos.append("bateria_percentual")
        self.save(update_fields=campos)

    def solicitar_recarga(self):
        """Faz o totem recarregar a pagina no proximo heartbeat."""
        self.recarga_solicitada_em = timezone.now()
        self.save(update_fields=["recarga_solicitada_em", "updated_at"])

    def regenerar_token(self) -> str:
        self.token_acesso = gerar_token(32)
        self.save(update_fields=["token_acesso", "updated_at"])
        return self.token_acesso

    def empresas_atendidas(self):
        """
        Empresas cujos colaboradores podem ser reconhecidos neste totem
        (regra 12 da Secao 14).
        """
        from apps.clientes.models import Empresa

        if self.grupo_id:
            do_grupo = self.grupo.empresas.all()
            if do_grupo.exists():
                return do_grupo
        return Empresa.objects.filter(pk=self.empresa_id)


class EventoTotem(BaseModel):
    """Diario de bordo do equipamento — util no suporte e na auditoria."""

    class Tipo(models.TextChoices):
        ONLINE = "online", "Voltou a ficar online"
        OFFLINE = "offline", "Ficou offline"
        RECONHECIMENTO_OK = "reconhecimento_ok", "Reconhecimento bem-sucedido"
        RECONHECIMENTO_FALHA = "reconhecimento_falha", "Falha no reconhecimento"
        FALLBACK_CPF = "fallback_cpf", "Registro por CPF"
        ERRO = "erro", "Erro na aplicação do totem"
        # Acoes administrativas da KS TEC sobre o equipamento
        # (regeneracao de token, devolucao de comodato). Ficam no mesmo
        # diario que os eventos operacionais porque, no suporte, a
        # pergunta e sempre "o que aconteceu com este totem" — e a
        # resposta costuma ser uma mistura das duas coisas.
        CONFIGURACAO = "configuracao", "Alteração de configuração"

    totem = models.ForeignKey(
        Totem, on_delete=models.CASCADE, related_name="eventos", verbose_name="Totem"
    )
    tipo = models.CharField("Tipo", max_length=25, choices=Tipo.choices, db_index=True)
    detalhes = models.CharField("Detalhes", max_length=255, blank=True)
    metadados = models.JSONField("Metadados", default=dict, blank=True)

    class Meta:
        verbose_name = "Evento do totem"
        verbose_name_plural = "Eventos dos totens"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["totem", "-created_at"])]

    def __str__(self):
        return f"{self.totem} — {self.get_tipo_display()}"
