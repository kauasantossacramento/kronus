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
    formatar_cnpj_ou_cpf,
    gerar_token,
    hash_api_key,
    tipo_identificador,
    validar_cnpj_ou_cpf,
)


class Cliente(BaseModel):
    """Contratante da assinatura Kronus."""

    razao_social = models.CharField("Razão social", max_length=200)
    nome_fantasia = models.CharField("Nome fantasia", max_length=200, blank=True)
    #: CNPJ (14 digitos) **ou** CPF (11).
    #:
    #: O empregador domestico e o produtor rural pessoa fisica registram
    #: ponto e sao alcancados pela Portaria 671 como qualquer outro.
    #: Exigir CNPJ deixaria essa faixa inteira de fora — e o AFD ja
    #: prevê o caso, com `tipo_identificador` 1 para CNPJ e 2 para CPF.
    cnpj = models.CharField(
        "CNPJ ou CPF", max_length=14, unique=True,
        validators=[validar_cnpj_ou_cpf], db_index=True,
        help_text="CNPJ para empresa, CPF para empregador pessoa física.",
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

    #: Ambiente de demonstracao com prazo.
    #:
    #: E um cliente comum, marcado — nao um "modo demo" do sistema. O
    #: visitante ve exatamente o produto que vai contratar, e converter e
    #: so limpar estes dois campos: nada precisa ser migrado.
    eh_demonstracao = models.BooleanField(
        "É demonstração", default=False, db_index=True
    )
    demo_expira_em = models.DateTimeField(
        "Demonstração expira em", null=True, blank=True, db_index=True
    )

    #: Libera API e webhooks para este cliente, independente do plano.
    #:
    #: `None` segue o plano — o caso normal. `True` e `False` sao
    #: excecoes que so o Master define: liberar para um cliente que esta
    #: em piloto, ou fechar para um que abusou da cota sem trocar de
    #: plano. Sem esta valvula, a unica saida seria criar um plano
    #: sob medida para cada excecao.
    integracoes_liberadas = models.BooleanField(
        "Integrações liberadas",
        null=True,
        blank=True,
        help_text=(
            "Vazio segue o plano. Marcado libera API e webhooks mesmo em "
            "plano que não inclui; desmarcado bloqueia mesmo em plano que inclui."
        ),
    )
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

    # -- Cadastro facial no proprio totem ----------------------
    #
    # Por que existe: um rosto cadastrado por uma camera e reconhecido
    # por outra com folga bem menor. Cadastrar no mesmo equipamento em
    # que a pessoa vai bater o ponto elimina a diferenca de uma vez — a
    # captura e o reconhecimento passam a vir da mesma otica, da mesma
    # resolucao e da mesma iluminacao.
    #
    # Desligado por padrao: abre uma porta de manutencao num aparelho de
    # parede, e isso e decisao de quem contrata.
    cadastro_facial_no_totem = models.BooleanField(
        "Permitir cadastro facial pelo totem",
        default=False,
        help_text=(
            "Libera no totem um modo de manutenção protegido por senha, "
            "para refazer a biometria dos colaboradores no próprio "
            "equipamento."
        ),
    )
    senha_totem = models.CharField(
        "Senha de manutenção do totem", max_length=128, blank=True,
        help_text="Guardada com hash — nunca em texto puro.",
    )
    senha_totem_definida_em = models.DateTimeField(
        "Senha do totem definida em", null=True, blank=True
    )

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
        return formatar_cnpj_ou_cpf(self.cnpj)

    @property
    def pessoa_fisica(self) -> bool:
        return len(apenas_digitos(self.cnpj)) == 11

    @property
    def rotulo_documento(self) -> str:
        return "CPF" if self.pessoa_fisica else "CNPJ"

    @property
    def status(self) -> str:
        if self.suspenso:
            return "Suspenso"
        return "Ativo" if self.ativo else "Inativo"

    @property
    def operacional(self) -> bool:
        return self.ativo and not self.suspenso

    # -- Senha de manutencao do totem --------------------------
    def definir_senha_totem(self, senha: str) -> None:
        """
        Guarda a senha com hash.

        Ela abre um modo de manutencao num tablet de parede, ao alcance
        de quem estiver fisicamente na frente dele. Guardar em texto puro
        colocaria essa porta inteira dentro de um `SELECT`.
        """
        from django.contrib.auth.hashers import make_password

        self.senha_totem = make_password(senha)
        self.senha_totem_definida_em = timezone.now()
        self.save(update_fields=[
            "senha_totem", "senha_totem_definida_em", "updated_at",
        ])

    def conferir_senha_totem(self, senha: str) -> bool:
        from django.contrib.auth.hashers import check_password

        if not self.senha_totem or not senha:
            return False
        return check_password(senha, self.senha_totem)

    @property
    def cadastro_no_totem_disponivel(self) -> bool:
        """Ligado **e** com senha definida — um sem o outro nao abre."""
        return bool(self.cadastro_facial_no_totem and self.senha_totem)

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

    @property
    def limite_de_totens(self) -> int:
        """
        Totens incluidos no plano mais os contratados como adicional.

        O limite vive aqui, e nao em `plano.max_totems`, porque o cliente
        pode comprar totem avulso — inclusive num plano que nao inclui
        nenhum. Ler o plano direto barraria um totem ja pago.
        """
        base = self.plano.max_totems or 0
        assinatura = getattr(self, "assinatura", None)
        if assinatura is None:
            return base
        return base + (assinatura.totens_contratados or 0)

    def pode_adicionar_totem(self) -> bool:
        return self.total_totens < self.limite_de_totens

    # -- empresa propria ---------------------------------------
    def garantir_empresa_propria(self):
        """
        Cria a `Empresa` que corresponde ao proprio cliente.

        O contratante **e** uma empresa: tem CNPJ, razao social e
        colaboradores. As demais `Empresa`s de um cliente sao filiais ou
        outros CNPJs do grupo, vinculadas depois.

        Sem isto o cadastro terminava num beco: o cliente nascia sem
        nenhuma empresa, a lista "Empresas com acesso" vinha vazia e o
        Master nao conseguia criar um Admin RH — que exige ao menos uma.

        Idempotente: se ja existir qualquer empresa, devolve a primeira e
        nao cria nada.
        """
        existente = self.empresas.order_by("created_at").first()
        if existente is not None:
            return existente

        return Empresa.objects.create(
            cliente=self,
            razao_social=self.razao_social,
            nome_fantasia=self.nome_fantasia,
            cnpj=self.cnpj,
            slug=Empresa.slug_disponivel(self.nome_fantasia or self.razao_social),
            cep=self.cep,
            logradouro=self.logradouro,
            numero=self.numero,
            complemento=self.complemento,
            bairro=self.bairro,
            cidade=self.cidade,
            uf=self.uf,
        )

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


    @property
    def pode_integrar(self) -> bool:
        """
        Se este cliente ve API e webhooks.

        A decisao mora aqui, e nao espalhada nas telas: liberar por
        excecao e uma decisao comercial, e ter dois lugares avaliando a
        mesma regra e como se descobre depois que uma tela liberava o
        que a outra bloqueava.
        """
        if self.integracoes_liberadas is not None:
            return self.integracoes_liberadas
        plano = self.plano
        return bool(plano and (plano.tem_api or plano.tem_webhook))


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
        "CNPJ ou CPF", max_length=14, unique=True,
        validators=[validar_cnpj_ou_cpf], db_index=True,
        help_text="CNPJ para empresa, CPF para empregador pessoa física.",
    )
    inscricao_estadual = models.CharField("Inscrição estadual", max_length=30, blank=True)
    cei_caepf = models.CharField(
        "CEI/CAEPF/CNO",
        max_length=20,
        blank=True,
        help_text=(
            "Vai no cabeçalho do AFD. Obrigatório na prática para "
            "empregador pessoa física — é o que identifica a matrícula "
            "junto à Previdência."
        ),
    )

    # -- Endereco ----------------------------------------------
    cep = models.CharField("CEP", max_length=9, blank=True)
    logradouro = models.CharField("Logradouro", max_length=200, blank=True)
    numero = models.CharField("Número", max_length=20, blank=True)
    complemento = models.CharField("Complemento", max_length=100, blank=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True)
    cidade = models.CharField("Cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)

    # -- Identidade na web -------------------------------------
    slug = models.SlugField(
        "Endereço da empresa",
        max_length=60,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Usado em kronus.online/<slug>. Deixe vazio para acesso apenas "
            "pela página geral de login."
        ),
    )

    # -- Personalizacao white-label ----------------------------
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
    msg_sucesso_ponto = models.CharField(
        "Mensagem após registrar o ponto",
        max_length=120,
        default="Ponto registrado!",
        help_text="Use {nome} para o primeiro nome e {hora} para o horário.",
    )
    frases_sucesso = models.TextField(
        "Frases após o ponto",
        blank=True,
        help_text=(
            "Uma por linha. Deixe em branco para usar as frases padrão."
        ),
    )
    frases_sorteadas = models.BooleanField(
        "Sortear a frase a cada batida",
        default=True,
        help_text=(
            "Desligado, o totem mostra sempre a primeira da lista — útil "
            "quando a mensagem faz parte do procedimento e precisa ser "
            "sempre a mesma."
        ),
    )
    som_confirmacao = models.BooleanField(
        "Som ao registrar o ponto",
        default=True,
        help_text=(
            "Confirmação sonora além da visual. Numa portaria movimentada "
            "quem está de costas não vê a tela."
        ),
    )

    # -- Identidade visual do totem ----------------------------
    logo_altura_px = models.PositiveSmallIntegerField(
        "Altura da marca no totem (px)",
        default=64,
        validators=[MinValueValidator(24), MaxValueValidator(240)],
        help_text=(
            "Vale para a logo da empresa e, quando ela não tiver logo, "
            "para a marca do Kronus que aparece no lugar."
        ),
    )
    logo_deslocamento_px = models.SmallIntegerField(
        "Deslocamento vertical da logo (px)",
        default=0,
        validators=[MinValueValidator(-200), MaxValueValidator(200)],
        help_text="Negativo sobe, positivo desce. Ajusta a logo sobre a câmera.",
    )
    #: A regra pronta, por tela.
    #:
    #: Antes so existia o campo livre `logo_css`, que exigia saber CSS e
    #: valia para o sistema inteiro de uma vez. Mas a necessidade real e
    #: quase sempre a mesma — a logo e escura e some no fundo escuro do
    #: totem — e ela nao vale nas duas telas ao mesmo tempo: a tela de
    #: login costuma ter fundo claro, onde a logo branca sumiria.
    logo_branca_totem = models.BooleanField(
        "Logo branca no totem",
        default=False,
        help_text="Marque se a logo some no fundo escuro do totem.",
    )
    logo_branca_login = models.BooleanField(
        "Logo branca na tela de login",
        default=False,
        help_text="Marque se a tela de login tiver fundo escuro.",
    )
    logo_css = models.TextField(
        "CSS adicional da logo",
        blank=True,
        help_text=(
            "Só para ajustes que as opções acima não cobrem. "
            "Ex.: opacity: .8; — vale em todas as telas."
        ),
    )

    #: Frase sob a mensagem de boas-vindas, na tela ociosa do totem.
    #:
    #: Vinha de uma constante do sistema ("Seu tempo, registrado com
    #: precisao"), igual para todo cliente. E texto de vitrine numa tela
    #: ligada o dia inteiro na portaria — quem conhece a operacao sabe o
    #: que escrever ali melhor do que nos.
    slogan_totem = models.CharField(
        "Frase do totem",
        max_length=120,
        blank=True,
        help_text=(
            "Aparece sob a mensagem de boas-vindas. "
            "Em branco, usa a frase padrão do Kronus."
        ),
    )

    #: Quantas tentativas de reconhecimento antes de oferecer o CPF.
    #:
    #: Hoje o totem insiste ate o tempo da camera esgotar, e a pessoa
    #: fica parada na frente do aparelho sem saber se deve esperar ou
    #: desistir. Contar as tentativas e oferecer a alternativa no momento
    #: certo resolve a fila — e uma segunda chance evita mandar para a
    #: digitacao quem so estava mal enquadrado na primeira foto.
    #:
    #: Zero mantem o comportamento antigo: insistir ate o tempo acabar.
    tentativas_antes_do_cpf = models.PositiveSmallIntegerField(
        "Tentativas antes de oferecer o CPF",
        default=2,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text=(
            "Depois desse número de tentativas sem reconhecer, o totem "
            "oferece o registro por CPF. Zero insiste até o tempo acabar."
        ),
    )

    #: Tamanho dos textos do totem.
    #:
    #: Fixos no CSS, ficavam pequenos numa tela de 7 polegadas vista a
    #: um metro de distancia — que e a distancia de quem passa pela
    #: portaria. O tamanho certo depende do tablet e de onde ele foi
    #: instalado, e nao ha um valor que sirva para todos.
    msg_boas_vindas_px = models.PositiveSmallIntegerField(
        "Tamanho da mensagem de boas-vindas (px)",
        default=19,
        validators=[MinValueValidator(12), MaxValueValidator(72)],
    )
    slogan_px = models.PositiveSmallIntegerField(
        "Tamanho da frase do totem (px)",
        default=13,
        validators=[MinValueValidator(10), MaxValueValidator(48)],
    )
    msg_sucesso_px = models.PositiveSmallIntegerField(
        "Tamanho da mensagem de confirmação (px)",
        default=16,
        validators=[MinValueValidator(12), MaxValueValidator(64)],
    )

    #: Altura da assinatura no rodape do totem (KS TEC ou Kronus).
    #:
    #: Fixa em 1rem, ela some numa tela de 7 polegadas vista a um metro
    #: de distancia — que e exatamente a distancia de quem passa pela
    #: portaria.
    assinatura_altura_px = models.PositiveSmallIntegerField(
        "Altura da assinatura KS TEC no totem (px)",
        default=16,
        validators=[MinValueValidator(10), MaxValueValidator(72)],
        help_text="Tamanho da marca da KS TEC no rodapé da tela do totem.",
    )
    #: A palavra "Kronus" no rodape, separada da assinatura da KS TEC.
    #:
    #: Sao duas marcas, com pesos diferentes: numa tela de 7 polegadas em
    #: pe, o que cabe de uma nao e o que cabe da outra. Um numero so para
    #: as duas obrigava a escolher qual ficaria errada.
    marca_kronus_px = models.PositiveSmallIntegerField(
        "Altura da marca Kronus no totem (px)",
        default=13,
        validators=[MinValueValidator(8), MaxValueValidator(48)],
        help_text="Tamanho da palavra Kronus no rodapé da tela do totem.",
    )

    #: Fundo da pagina de acesso da empresa.
    #:
    #: Separado da cor primaria: a primaria pinta botao e destaque, e uma
    #: cor forte o suficiente para um botao costuma ser escura demais
    #: para cobrir a tela inteira.
    cor_fundo_login = models.CharField(
        "Cor de fundo da tela de login",
        max_length=7,
        default="#F8FAFC",
        help_text="Fundo da página onde o colaborador entra.",
    )

    # -- Tela de ociosidade ------------------------------------
    class TransicaoSlide(models.TextChoices):
        FADE = "fade", "Dissolver"
        DESLIZAR = "deslizar", "Deslizar"
        ZOOM = "zoom", "Zoom suave"
        NENHUMA = "nenhuma", "Troca seca"

    slides_transicao = models.CharField(
        "Transição entre as imagens",
        max_length=10,
        choices=TransicaoSlide.choices,
        default=TransicaoSlide.FADE,
    )
    slides_segundos = models.PositiveSmallIntegerField(
        "Segundos por imagem",
        default=8,
        validators=[MinValueValidator(3), MaxValueValidator(120)],
    )

    #: Sobe a cada mudanca de personalizacao. O totem le no heartbeat e,
    #: vendo um numero maior do que o que carregou, recarrega sozinho.
    #:
    #: Comparar um inteiro e mais barato e mais confiavel do que
    #: diferenciar a configuracao inteira, e funciona mesmo quando o
    #: totem passou horas offline.
    config_versao = models.PositiveIntegerField("Versão da configuração", default=1)

    def marcar_configuracao_alterada(self):
        """
        Sinaliza aos totens que a identidade visual mudou.

        Chamado ao salvar a personalizacao. Sem isso, trocar a logo ou a
        cor exigiria alguem ir ate cada tablet e recarregar a pagina.
        """
        type(self).objects.filter(pk=self.pk).update(
            config_versao=models.F("config_versao") + 1
        )
        self.refresh_from_db(fields=["config_versao"])
        return self.config_versao

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

    @staticmethod
    def slug_disponivel(nome: str) -> str:
        """
        Slug livre a partir do nome, sem colidir com um ja existente.

        O campo e `unique`; deixar a colisao estourar no banco
        transformaria "duas empresas com nome parecido" num erro 500 no
        meio de um cadastro.
        """
        import secrets
        import unicodedata

        from django.utils.text import slugify

        raiz = slugify(unicodedata.normalize("NFKD", nome or ""))[:50] or "empresa"
        candidato = raiz
        while Empresa.objects.filter(slug=candidato).exists():
            candidato = f"{raiz}-{secrets.token_hex(2)}"
        return candidato

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ("razao_social",)
        indexes = [models.Index(fields=["cliente", "ativo"])]

    def gerar_slug(self):
        """
        Deriva um slug do nome fantasia ou da razao social.

        Chamado no primeiro save de uma empresa sem slug. Colisao ganha
        sufixo numerico: dois "Aurora" em clientes diferentes precisam de
        enderecos distintos, e falhar aqui deixaria a empresa sem acesso
        personalizado por um detalhe de cadastro.
        """
        from django.utils.text import slugify

        base = slugify(self.nome_fantasia or self.razao_social)[:52] or "empresa"
        candidato, sufixo = base, 1
        while (
            type(self).objects.filter(slug=candidato).exclude(pk=self.pk).exists()
        ):
            sufixo += 1
            candidato = f"{base}-{sufixo}"[:60]
        return candidato


    def __str__(self):
        return self.nome_exibicao

    def save(self, *args, **kwargs):
        self.cnpj = apenas_digitos(self.cnpj)
        if not self.salt_registro:
            self.salt_registro = gerar_token(24)
        if not self.slug:
            self.slug = self.gerar_slug()
        criando = self._state.adding
        super().save(*args, **kwargs)
        if criando:
            ConfiguracaoEmpresa.objects.get_or_create(empresa=self)

    #: Regra que deixa a logo branca preservando a forma.
    #:
    #: `brightness(0)` achata tudo para preto, `invert(1)` inverte para
    #: branco. Trocar a cor no CSS nao funcionaria: a logo e uma imagem,
    #: nao um vetor que o navegador saiba recolorir.
    CSS_LOGO_BRANCA = "filter: brightness(0) invert(1);"

    def css_da_logo(self, tela: str = "") -> str:
        """
        Regras CSS da logo para a tela indicada (`totem` ou `login`).

        Devolve string vazia quando nao ha nada a aplicar, para que o
        template possa omitir a tag `<style>` inteira.
        """
        regras = []
        if tela == "totem" and self.logo_branca_totem:
            regras.append(self.CSS_LOGO_BRANCA)
        elif tela == "login" and self.logo_branca_login:
            regras.append(self.CSS_LOGO_BRANCA)
        if self.logo_css:
            regras.append(self.logo_css.strip().rstrip(";") + ";")
        return " ".join(regras)

    def frases_de_sucesso(self) -> list[str]:
        """
        Frases que acompanham o "ponto registrado".

        Configuraveis porque a segunda linha e a voz da empresa: "Bom
        trabalho!" cai bem num escritorio e soa estranho num hospital as
        tres da manha. Em branco devolve as padrao — uma lista vazia
        deixaria a tela com metade da mensagem.
        """
        from apps.core.constants import MENSAGENS_TOTEM

        linhas = [
            linha.strip()
            for linha in (self.frases_sucesso or "").splitlines()
            if linha.strip()
        ]
        return linhas or list(MENSAGENS_TOTEM)

    def frase_de_sucesso(self) -> str:
        """
        A frase da vez.

        Sortear e agradavel numa portaria movimentada e ruim onde a
        mensagem faz parte do procedimento — ali a pessoa precisa ver
        sempre a mesma coisa para notar quando algo mudou. Por isso a
        escolha e da empresa; sem sorteio, vale a primeira da lista.
        """
        import random

        frases = self.frases_de_sucesso()
        return random.choice(frases) if self.frases_sorteadas else frases[0]

    @property
    def nome_exibicao(self) -> str:
        return self.nome_fantasia or self.razao_social

    @property
    def cnpj_formatado(self) -> str:
        return formatar_cnpj_ou_cpf(self.cnpj)

    @property
    def pessoa_fisica(self) -> bool:
        return len(apenas_digitos(self.cnpj)) == 11

    @property
    def rotulo_documento(self) -> str:
        return "CPF" if self.pessoa_fisica else "CNPJ"

    @property
    def tipo_identificador_afd(self) -> str:
        """`1` para CNPJ, `2` para CPF — campo do cabeçalho do AFD."""
        return tipo_identificador(self.cnpj)

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

    # -- LGPD --------------------------------------------------
    guardar_frames_reconhecimento = models.BooleanField(
        "Guardar as fotos das batidas",
        default=False,
        help_text=(
            "Guarda a imagem de cada tentativa no totem. Serve para "
            "diagnosticar reconhecimento — e dado biométrico sensível "
            "(LGPD Art. 11): mantenha ligado apenas durante a análise."
        ),
    )
    apagar_foto_apos_encoding = models.BooleanField(
        "Descartar fotos após gerar o embedding",
        default=False,
        help_text=(
            "Guardar apenas o vetor matemático do rosto, e não a foto. "
            "Reduz o dado sensível retido, conforme a LGPD."
        ),
    )
    retencao_faces_dias = models.PositiveSmallIntegerField(
        "Retenção de dados faciais após desligamento (dias)", default=30
    )

    class Meta:
        verbose_name = "Configuração da empresa"
        verbose_name_plural = "Configurações das empresas"

    def __str__(self):
        return f"Configuração — {self.empresa.nome_exibicao}"


class SlideTotem(BaseModel):
    """
    Uma imagem da tela de ociosidade do totem.

    Antes havia um único `idle_screen_img` por empresa. Uma imagem só
    numa tela que fica ligada o dia inteiro é desperdício de um canal
    que a empresa já tem: comunicado interno, campanha de segurança,
    aniversariantes do mês. Vários slides transformam o totem parado em
    mural.

    A ordem é explícita (`ordem`) em vez de derivada da data de envio:
    quem monta a sequência quer controlá-la sem reenviar arquivos.
    """

    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="slides",
        verbose_name="Empresa",
    )
    imagem = models.ImageField("Imagem", upload_to="idle_screens/")
    legenda = models.CharField("Legenda", max_length=120, blank=True)
    ordem = models.PositiveSmallIntegerField("Ordem", default=0)
    ativo = models.BooleanField("Ativo", default=True)

    #: Janela de exibição. Um comunicado de campanha tem prazo; sem
    #: isso, alguém precisa lembrar de removê-lo.
    inicio_exibicao = models.DateField("Exibir a partir de", null=True, blank=True)
    fim_exibicao = models.DateField("Exibir até", null=True, blank=True)

    class Meta:
        verbose_name = "Slide do totem"
        verbose_name_plural = "Slides do totem"
        ordering = ("ordem", "created_at")

    def __str__(self):
        return self.legenda or f"Slide {self.ordem}"

    @property
    def vigente(self) -> bool:
        from django.utils import timezone

        if not self.ativo:
            return False
        hoje = timezone.localdate()
        if self.inicio_exibicao and hoje < self.inicio_exibicao:
            return False
        if self.fim_exibicao and hoje > self.fim_exibicao:
            return False
        return True
