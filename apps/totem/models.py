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
    #: Como a pagina esta aberta no aparelho.
    #:
    #: Decide se a atualizacao chega sozinha. Instalado como aplicativo,
    #: o manifesto pede `display: fullscreen` e uma recarga nao perde a
    #: tela cheia — o codigo novo entra sem ninguem tocar no equipamento.
    #: Aberto numa aba, a recarga derruba a tela cheia, e o navegador so
    #: a devolve mediante gesto do usuario, por regra propria.
    #:
    #: Sem este campo nao havia como saber quais totens estao em qual
    #: situacao sem ir ate eles.
    modo_exibicao = models.CharField(
        "Modo de exibição",
        max_length=20,
        blank=True,
        help_text="Como a página está aberta: aplicativo instalado ou aba do navegador.",
    )
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
    #: Recarga de verdade, pedida pelo suporte.
    #:
    #: Diferente de `recarga_solicitada_em`, que so faz o totem buscar a
    #: configuracao e aplicar ao vivo — cores, logo, mensagens. Isso
    #: cobre quase tudo e nao derruba a tela cheia, e por isso e o
    #: padrao. Mas nao traz codigo novo, e quando o problema esta no
    #: codigo o unico caminho e recarregar a pagina.
    #:
    #: Fica separado para a escolha ser deliberada: quem clica em
    #: "recarregar" sabe que a tela vai piscar.
    #: O totem atende as outras empresas do mesmo cliente?
    #:
    #: Um cliente com matriz e filiais tem uma assinatura so, e quem
    #: trabalha numa unidade passa pela outra. Obrigar a montar um grupo
    #: para cada combinacao e trabalho de cadastro que so existe porque o
    #: sistema pede.
    #:
    #: Desligado por padrao. Ligar amplia quem pode bater ponto ali, e
    #: essa e uma decisao de quem administra — nao um efeito colateral de
    #: cadastrar a segunda empresa.
    #:
    #: Nunca atravessa a fronteira do cliente: o alcance maximo e a
    #: propria assinatura.
    #: Como este equipamento comeca: sozinho, ou ao toque.
    #:
    #: A empresa define o padrao; o totem pode discordar. Dois
    #: equipamentos da mesma empresa vivem em lugares diferentes — um na
    #: portaria, com movimento medido, outro na copa, por onde todo mundo
    #: passa o dia inteiro. Na copa a deteccao automatica acende a tela
    #: para quem so foi pegar cafe.
    class Inicio(models.TextChoices):
        EMPRESA = "empresa", "Seguir a configuração da empresa"
        PRESENCA = "presenca", "Reconhecer a presença automaticamente"
        TOQUE = "toque", "Somente ao tocar na tela"

    inicio_do_ponto = models.CharField(
        "Início do reconhecimento",
        max_length=10,
        choices=Inicio.choices,
        default=Inicio.EMPRESA,
    )

    atende_todo_o_cliente = models.BooleanField(
        "Atende todas as empresas do cliente",
        default=False,
        help_text=(
            "Colaboradores de qualquer empresa deste cliente podem bater "
            "ponto neste equipamento. A batida continua sendo registrada "
            "na empresa de cada um."
        ),
    )
    recarga_total_em = models.DateTimeField(
        "Recarga total pedida em", null=True, blank=True
    )
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
        """
        Faz o totem buscar a configuracao e aplicar ao vivo.

        O nome ficou de quando isto recarregava a pagina de verdade. Hoje
        so atualiza cores, logo, mensagens e imagens — o que cobre quase
        toda mudanca do painel e nao derruba a tela cheia. Para trazer
        codigo novo, `pedir_recarga_total`.
        """
        self.recarga_solicitada_em = timezone.now()
        self.save(update_fields=["recarga_solicitada_em", "updated_at"])

    def pedir_recarga_total(self):
        """
        Pede a recarga da pagina, e nao so da configuracao.

        Usar quando o problema esta no codigo — a atualizacao ao vivo
        nao traz arquivo novo. O totem espera ficar ocioso antes de
        recarregar, entao ninguem e interrompido no meio de uma batida.
        """
        agora = timezone.now()
        self.recarga_total_em = agora
        # Tambem o campo antigo: um totem que ainda nao recebeu esta
        # versao ignora `recarga_total_em`, mas entende este — e ao
        # menos reaplica a configuracao em vez de o clique nao fazer
        # absolutamente nada.
        self.recarga_solicitada_em = agora
        self.save(update_fields=[
            "recarga_total_em", "recarga_solicitada_em", "updated_at",
        ])

    @property
    def recebeu_a_atualizacao(self) -> bool:
        """
        O totem ja carregou uma versao que sabe se atualizar sozinha?

        `modo_exibicao` so passou a ser enviado nessa versao. Um totem
        que nunca mandou o campo esta rodando codigo anterior — e nele o
        pedido de recarga da pagina nao tem efeito, porque o mecanismo
        que o escuta ainda nao chegou la.
        """
        return bool(self.modo_exibicao)

    def regenerar_token(self) -> str:
        self.token_acesso = gerar_token(32)
        self.save(update_fields=["token_acesso", "updated_at"])
        return self.token_acesso

    @property
    def comeca_por_toque(self) -> bool:
        """
        Resolve o padrao da empresa com a escolha deste equipamento.

        A escolha do totem vence quando existe; "seguir a empresa" e o
        que mantem o comportamento de quem nunca mexeu nisso.
        """
        if self.inicio_do_ponto == self.Inicio.TOQUE:
            return True
        if self.inicio_do_ponto == self.Inicio.PRESENCA:
            return False
        return bool(self.empresa.iniciar_por_toque)

    def empresas_atendidas(self):
        """
        Empresas cujos colaboradores podem bater ponto neste equipamento.

        Vale para os dois caminhos: reconhecimento facial e digitacao do
        CPF. O escopo e sempre explicito — nunca "todos os colaboradores
        do sistema".

        **A empresa do proprio totem entra sempre.** O grupo *amplia* o
        alcance, nao o substitui: o equipamento esta fisicamente instalado
        naquela empresa, e recusar quem trabalha ali porque alguem
        esqueceu de marcar a empresa no grupo seria negar o ponto a quem
        esta parado na frente da maquina. Antes, um grupo montado so com
        as filiais fazia a matriz perder acesso ao proprio totem.

        Nao ha risco de vazamento entre contas: o grupo pertence a um
        cliente e so aceita empresas dele, entao a uniao nunca atravessa
        a fronteira do tenant.
        """
        from django.db.models import Q

        from apps.clientes.models import Empresa

        filtro = Q(pk=self.empresa_id)
        if self.grupo_id:
            filtro |= Q(grupos_totem=self.grupo_id)
        if self.atende_todo_o_cliente and self.empresa.cliente_id:
            # O teto continua sendo a assinatura: um totem nunca alcanca
            # empresa de outro cliente, marcado ou nao.
            filtro |= Q(cliente_id=self.empresa.cliente_id)
        return Empresa.objects.filter(filtro).distinct()


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
