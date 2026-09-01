"""
Kronus — models do dominio de RH.

Departamento, Cargo e Colaborador (Secao 4.1), alem dos fluxos de
Atestado, Justificativa e Afastamento (Secoes 8.6 e 8.8).
"""
from datetime import date

import numpy as np
from django.db import models
from django.utils import timezone

from apps.core.constants import (
    StatusAprovacao,
    TipoAfastamento,
    TipoJustificativa,
)
from apps.core.models import TenantBaseModel
from apps.core.utils import (
    apenas_digitos,
    formatar_cpf,
    mascarar_cpf,
    validar_cpf,
    validar_pis,
)


# ==============================================================
# Estrutura organizacional
# ==============================================================
class Departamento(TenantBaseModel):
    nome = models.CharField("Nome", max_length=100)
    descricao = models.CharField("Descrição", max_length=255, blank=True)
    responsavel = models.ForeignKey(
        "rh.Colaborador",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departamentos_gerenciados",
        verbose_name="Responsável",
    )
    centro_custo = models.CharField("Centro de custo", max_length=30, blank=True)
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Departamento"
        verbose_name_plural = "Departamentos"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_departamento_por_empresa",
            )
        ]

    def __str__(self):
        return self.nome

    @property
    def total_colaboradores(self) -> int:
        return self.colaboradores.filter(ativo=True).count()


class Cargo(TenantBaseModel):
    nome = models.CharField("Nome", max_length=100)
    cbo = models.CharField(
        "CBO", max_length=10, blank=True, help_text="Classificação Brasileira de Ocupações."
    )
    descricao = models.CharField("Descrição", max_length=255, blank=True)
    salario_base = models.DecimalField(
        "Salário base (R$)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"
        ordering = ("nome",)
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_cargo_por_empresa",
            )
        ]

    def __str__(self):
        return self.nome


# ==============================================================
# Colaborador
# ==============================================================
class ColaboradorQuerySet(models.QuerySet):
    def ativos(self):
        return self.filter(ativo=True, deleted_at__isnull=True)

    def com_face(self):
        return self.filter(face_registrada=True, face_embedding__isnull=False)

    def da_empresa(self, empresa):
        return self.filter(empresa=empresa)


class Colaborador(TenantBaseModel):
    """
    Funcionario que registra ponto.

    O vinculo com `accounts.CustomUser` e opcional: colaboradores que
    batem ponto apenas no totem nao precisam de credenciais de acesso.
    """

    user = models.OneToOneField(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="colaborador",
        verbose_name="Usuário de acesso",
    )
    departamento = models.ForeignKey(
        Departamento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="colaboradores",
        verbose_name="Departamento",
    )
    cargo_ref = models.ForeignKey(
        Cargo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="colaboradores",
        verbose_name="Cargo (cadastrado)",
    )
    escala = models.ForeignKey(
        "ponto.EscalaTrabalho",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="colaboradores",
        verbose_name="Escala de trabalho",
    )

    # -- Identificacao -----------------------------------------
    cpf = models.CharField("CPF", max_length=11, validators=[validar_cpf], db_index=True)
    nome_completo = models.CharField("Nome completo", max_length=150)
    nome_social = models.CharField("Nome social", max_length=150, blank=True)
    data_nascimento = models.DateField("Data de nascimento")
    email = models.EmailField("E-mail", blank=True)
    telefone = models.CharField("Telefone", max_length=20, blank=True)

    # -- Vinculo trabalhista -----------------------------------
    cargo = models.CharField("Cargo (texto livre)", max_length=100, blank=True)
    matricula = models.CharField("Matrícula", max_length=30, blank=True, db_index=True)
    data_admissao = models.DateField("Data de admissão")
    data_demissao = models.DateField("Data de demissão", null=True, blank=True)
    ativo = models.BooleanField("Ativo", default=True, db_index=True)
    pis_pasep = models.CharField(
        "PIS/PASEP", max_length=11, blank=True, validators=[validar_pis]
    )
    ctps = models.CharField("CTPS", max_length=20, blank=True)
    ctps_serie = models.CharField("Série da CTPS", max_length=10, blank=True)

    # -- Biometria facial (Secao 8.2) --------------------------
    foto_perfil = models.ImageField(
        "Foto de perfil", upload_to="faces/perfil/", null=True, blank=True
    )
    face_embedding = models.BinaryField(
        "Embedding facial",
        null=True,
        blank=True,
        editable=False,
        help_text="Vetor ArcFace (512 dims) serializado com numpy.tobytes().",
    )
    face_registrada = models.BooleanField("Face cadastrada", default=False, db_index=True)
    face_atualizada_em = models.DateTimeField(
        "Face atualizada em", null=True, blank=True
    )
    consentimento_biometrico = models.BooleanField(
        "Consentimento biométrico (LGPD)",
        default=False,
        help_text="Consentimento explícito exigido pela LGPD para dado sensível.",
    )
    consentimento_biometrico_em = models.DateTimeField(
        "Consentimento em", null=True, blank=True
    )

    # -- Operacao ----------------------------------------------
    permite_ponto_web = models.BooleanField("Pode bater ponto pela web", default=True)
    observacoes = models.TextField("Observações", blank=True)

    objects = ColaboradorQuerySet.as_manager()

    class Meta:
        verbose_name = "Colaborador"
        verbose_name_plural = "Colaboradores"
        ordering = ("nome_completo",)
        constraints = [
            # O CPF e unico dentro da empresa: a mesma pessoa pode ter
            # vinculo em mais de uma empresa do mesmo cliente.
            models.UniqueConstraint(
                fields=["empresa", "cpf"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_cpf_por_empresa",
            ),
            models.UniqueConstraint(
                fields=["empresa", "matricula"],
                condition=models.Q(deleted_at__isnull=True) & ~models.Q(matricula=""),
                name="uniq_matricula_por_empresa",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "ativo"]),
            models.Index(fields=["cpf", "data_nascimento"]),
        ]

    def __str__(self):
        return self.nome_completo

    def save(self, *args, **kwargs):
        self.cpf = apenas_digitos(self.cpf)
        self.pis_pasep = apenas_digitos(self.pis_pasep)
        super().save(*args, **kwargs)

    # -- acesso ao sistema -------------------------------------
    def mover_para(self, destino):
        """
        Transfere o colaborador para outra empresa do mesmo cliente.

        Acontece de verdade: a pessoa e contratada por uma unidade e passa
        a atuar em outra do mesmo grupo. Sem isto, o caminho era apagar e
        recadastrar — e junto se perdia o historico de ponto, que e prova
        trabalhista.

        O que **nao** se move: as batidas ja registradas. Elas ficam na
        empresa onde aconteceram, porque foi ali que o trabalho foi
        prestado, e cada uma carrega o NSR daquela empresa numa corrente
        encadeada. Reescrever isso quebraria a corrente inteira e
        falsificaria o arquivo fiscal.

        O que se move: o cadastro, o vinculo de acesso e o
        reconhecimento facial — daqui para a frente a pessoa e da nova
        empresa.

        Recusa fora do cliente: a fronteira da assinatura e o limite de
        tudo neste sistema.
        """
        from django.core.exceptions import ValidationError

        if destino.pk == self.empresa_id:
            return self

        if destino.cliente_id != self.empresa.cliente_id:
            raise ValidationError(
                "A empresa de destino pertence a outro cliente."
            )

        origem = self.empresa
        self.empresa = destino
        # A escala e da empresa antiga e pode nem existir na nova; deixar
        # apontando para fora produziria uma jornada que o destino nao
        # reconhece.
        if self.escala_id and self.escala.empresa_id != destino.pk:
            self.escala = None
        if self.departamento_id and self.departamento.empresa_id != destino.pk:
            self.departamento = None
        if self.cargo_ref_id and self.cargo_ref.empresa_id != destino.pk:
            self.cargo_ref = None
        self.save(update_fields=[
            "empresa", "escala", "departamento", "cargo_ref", "updated_at",
        ])

        # O acesso acompanha: sem o vinculo, a pessoa entra e nao ve nada.
        from apps.accounts.models import CustomUser

        usuario = None
        if self.cpf:
            usuario = CustomUser.objects.filter(cpf=self.cpf).first()
        if usuario is None and self.email:
            usuario = CustomUser.objects.filter(email=self.email).first()
        if usuario:
            usuario.empresas.add(destino)
            usuario.empresas.remove(origem)

        # As amostras faciais pertencem ao colaborador, e nao a empresa:
        # elas seguem sozinhas. O que precisa mudar e o cache de
        # candidatos das duas pontas, que e montado por empresa.
        from apps.facial.services import FaceRecognitionService

        FaceRecognitionService.invalidar_cache(origem.pk)
        FaceRecognitionService.invalidar_cache(destino.pk)
        return self

    def garantir_usuario(self, criar_senha=True):
        """
        Cria (ou vincula) o login do colaborador.

        Sem isto o cadastro nasce sem acesso: a pessoa existe para o
        ponto, aparece nos relatorios, e nao consegue entrar para ver o
        proprio saldo nem assinar o espelho. Era o caso de dezesseis dos
        dezessete colaboradores em producao.

        Devolve `(usuario, senha_provisoria)`. A senha so existe no
        retorno — nao e guardada em lugar nenhum, e quem cadastra precisa
        entrega-la na hora.

        Vincula tambem a **empresa**: sem esse vinculo o usuario entra e
        nao enxerga nada, porque todo o sistema e escopado por empresa.
        """
        from apps.accounts.models import CustomUser
        from apps.core.constants import TipoUsuario
        from apps.core.utils import gerar_token

        senha = None
        usuario = self.user

        if usuario is None and self.cpf:
            # Reaproveita um login existente com o mesmo CPF: criar um
            # segundo esbarraria na unicidade e deixaria a pessoa com
            # dois cadastros.
            usuario = CustomUser.objects.filter(cpf=self.cpf).first()

        if usuario is None:
            senha = gerar_token(9)
            usuario = CustomUser.objects.create_user(
                cpf=self.cpf,
                email=self.email or None,
                password=senha,
                nome_completo=self.nome_completo,
                tipo=TipoUsuario.COLABORADOR,
                cliente=self.empresa.cliente,
            )
            usuario.trocar_senha_no_proximo_login = True
            usuario.save(update_fields=["trocar_senha_no_proximo_login"])
        elif criar_senha and not usuario.has_usable_password():
            senha = gerar_token(9)
            usuario.set_password(senha)
            usuario.trocar_senha_no_proximo_login = True
            usuario.save(update_fields=["password", "trocar_senha_no_proximo_login"])

        usuario.empresas.add(self.empresa)
        if usuario.cliente_id is None:
            usuario.cliente = self.empresa.cliente
            usuario.save(update_fields=["cliente"])

        # O e-mail da ficha vale mais que o do login.
        #
        # So era copiado na criacao. Quem tinha acesso criado sem e-mail
        # e recebia o endereco depois ficava com o login sem e-mail para
        # sempre — e a recuperacao de senha procura o usuario **por
        # e-mail**: a pessoa pedia, a tela dizia "enviado", e nada saia.
        #
        # A ficha e onde o RH mantem o cadastro; o login e consequencia.
        # Por isso a ficha manda.
        if self.email and usuario.email != self.email:
            usuario.email = self.email
            usuario.save(update_fields=["email"])

        if self.user_id != usuario.pk:
            self.user = usuario
            self.save(update_fields=["user", "updated_at"])

        return usuario, senha

    def sincronizar_email_do_login(self) -> bool:
        """
        Leva o e-mail da ficha para o login, quando ele mudar.

        Devolve `True` quando mexeu. Chamado no `save`: sem isso, editar
        o e-mail na ficha nao alcancava o login, e a recuperacao de
        senha — que procura por e-mail — continuava sem encontrar a
        pessoa.

        Nunca apaga: e-mail em branco na ficha nao remove o do login. Um
        campo esvaziado por engano tirava o unico caminho de recuperacao
        que a pessoa tinha.
        """
        if not self.user_id or not self.email:
            return False
        if self.user.email == self.email:
            return False
        self.user.email = self.email
        self.user.save(update_fields=["email"])
        return True

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            self.sincronizar_email_do_login()
        except Exception:
            # Falha aqui nao pode impedir de salvar o colaborador: o
            # cadastro e o essencial, a sincronia e consequencia.
            import logging

            logging.getLogger("kronus.rh").exception(
                "Falha ao sincronizar o e-mail do login de %s", self.pk
            )

    # -- apresentacao ------------------------------------------
    @property
    def nome_exibicao(self) -> str:
        return self.nome_social or self.nome_completo

    @property
    def primeiro_nome(self) -> str:
        return self.nome_exibicao.split(" ")[0]

    @property
    def cpf_formatado(self) -> str:
        return formatar_cpf(self.cpf)

    @property
    def cpf_mascarado(self) -> str:
        return mascarar_cpf(self.cpf)

    @property
    def iniciais(self) -> str:
        partes = [p for p in self.nome_exibicao.split(" ") if p]
        if len(partes) >= 2:
            return (partes[0][0] + partes[-1][0]).upper()
        return (partes[0][:2] if partes else "?").upper()

    @property
    def idade(self) -> int | None:
        if not self.data_nascimento:
            return None
        hoje = date.today()
        return (
            hoje.year
            - self.data_nascimento.year
            - ((hoje.month, hoje.day) < (self.data_nascimento.month, self.data_nascimento.day))
        )

    @property
    def desligado(self) -> bool:
        return self.data_demissao is not None and self.data_demissao <= date.today()

    # -- biometria ---------------------------------------------
    def obter_embedding(self) -> "np.ndarray | None":
        """Deserializa o embedding facial para um vetor numpy float32."""
        if not self.face_embedding:
            return None
        return np.frombuffer(bytes(self.face_embedding), dtype=np.float32)

    def definir_embedding(self, vetor, salvar: bool = True):
        """Serializa e persiste o embedding medio do colaborador."""
        vetor = np.asarray(vetor, dtype=np.float32)
        self.face_embedding = vetor.tobytes()
        self.face_registrada = True
        self.face_atualizada_em = timezone.now()
        if salvar:
            self.save(
                update_fields=[
                    "face_embedding",
                    "face_registrada",
                    "face_atualizada_em",
                    "updated_at",
                ]
            )

    def limpar_biometria(self):
        """Direito de exclusão (Secao 10) e expurgo pos-desligamento."""
        self.face_embedding = None
        self.face_registrada = False
        self.face_atualizada_em = None
        self.save(
            update_fields=[
                "face_embedding",
                "face_registrada",
                "face_atualizada_em",
                "updated_at",
            ]
        )
        self.registros_faciais.all().delete()

    def registrar_consentimento_biometrico(self):
        self.consentimento_biometrico = True
        self.consentimento_biometrico_em = timezone.now()
        self.save(
            update_fields=[
                "consentimento_biometrico",
                "consentimento_biometrico_em",
                "updated_at",
            ]
        )


# ==============================================================
# Atestados (Secao 8.6)
# ==============================================================
class Atestado(TenantBaseModel):
    colaborador = models.ForeignKey(
        Colaborador,
        on_delete=models.CASCADE,
        related_name="atestados",
        verbose_name="Colaborador",
    )
    arquivo = models.FileField(
        "Arquivo", upload_to="atestados/%Y/%m/", help_text="PDF, JPG ou PNG (até 10MB)."
    )
    data_inicio = models.DateField("Início do afastamento")
    data_fim = models.DateField("Fim do afastamento")
    cid = models.CharField("CID", max_length=10, blank=True)
    dias = models.PositiveSmallIntegerField("Dias", default=1, editable=False)
    observacoes = models.TextField("Observações", blank=True)

    status = models.CharField(
        "Status",
        max_length=10,
        choices=StatusAprovacao.choices,
        default=StatusAprovacao.PENDENTE,
        db_index=True,
    )
    aprovado_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="atestados_avaliados",
        verbose_name="Avaliado por",
    )
    avaliado_em = models.DateTimeField("Avaliado em", null=True, blank=True)
    motivo_rejeicao = models.CharField("Motivo da rejeição", max_length=255, blank=True)

    enviado_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="atestados_enviados",
        verbose_name="Enviado por",
    )

    class Meta:
        verbose_name = "Atestado"
        verbose_name_plural = "Atestados"
        ordering = ("-data_inicio",)
        indexes = [
            models.Index(fields=["colaborador", "data_inicio"]),
            models.Index(fields=["empresa", "status"]),
        ]

    def __str__(self):
        return f"Atestado {self.colaborador.nome_exibicao} — {self.data_inicio:%d/%m/%Y}"

    def save(self, *args, **kwargs):
        if self.data_inicio and self.data_fim:
            self.dias = (self.data_fim - self.data_inicio).days + 1
        super().save(*args, **kwargs)

    @property
    def aprovado(self) -> bool:
        return self.status == StatusAprovacao.APROVADO

    def cobre(self, dia: date) -> bool:
        return self.aprovado and self.data_inicio <= dia <= self.data_fim

    def aprovar(self, usuario):
        self.status = StatusAprovacao.APROVADO
        self.aprovado_por = usuario
        self.avaliado_em = timezone.now()
        self.save(update_fields=["status", "aprovado_por", "avaliado_em", "updated_at"])

    def rejeitar(self, usuario, motivo: str = ""):
        self.status = StatusAprovacao.REJEITADO
        self.aprovado_por = usuario
        self.avaliado_em = timezone.now()
        self.motivo_rejeicao = motivo[:255]
        self.save(
            update_fields=[
                "status",
                "aprovado_por",
                "avaliado_em",
                "motivo_rejeicao",
                "updated_at",
            ]
        )


# ==============================================================
# Justificativas e abonos
# ==============================================================
class Justificativa(TenantBaseModel):
    colaborador = models.ForeignKey(
        Colaborador,
        on_delete=models.CASCADE,
        related_name="justificativas",
        verbose_name="Colaborador",
    )
    data = models.DateField("Data", db_index=True)
    tipo = models.CharField("Tipo", max_length=20, choices=TipoJustificativa.choices)
    motivo = models.TextField("Motivo")
    arquivo_comprovante = models.FileField(
        "Comprovante", upload_to="justificativas/%Y/%m/", null=True, blank=True
    )
    abona_dia = models.BooleanField(
        "Abona o dia",
        default=True,
        help_text="Se marcado, o dia deixa de contar como falta/atraso no espelho.",
    )

    status = models.CharField(
        "Status",
        max_length=10,
        choices=StatusAprovacao.choices,
        default=StatusAprovacao.PENDENTE,
        db_index=True,
    )
    aprovada_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="justificativas_avaliadas",
        verbose_name="Avaliada por",
    )
    avaliada_em = models.DateTimeField("Avaliada em", null=True, blank=True)
    parecer = models.CharField("Parecer", max_length=255, blank=True)

    solicitada_por = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="justificativas_solicitadas",
        verbose_name="Solicitada por",
    )

    class Meta:
        verbose_name = "Justificativa"
        verbose_name_plural = "Justificativas"
        ordering = ("-data",)
        indexes = [
            models.Index(fields=["colaborador", "data"]),
            models.Index(fields=["empresa", "status"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.colaborador.nome_exibicao} ({self.data:%d/%m/%Y})"

    @property
    def aprovada(self) -> bool:
        return self.status == StatusAprovacao.APROVADO

    def aprovar(self, usuario, parecer: str = ""):
        self.status = StatusAprovacao.APROVADO
        self.aprovada_por = usuario
        self.avaliada_em = timezone.now()
        self.parecer = parecer[:255]
        self.save(
            update_fields=["status", "aprovada_por", "avaliada_em", "parecer", "updated_at"]
        )

    def rejeitar(self, usuario, parecer: str = ""):
        self.status = StatusAprovacao.REJEITADO
        self.aprovada_por = usuario
        self.avaliada_em = timezone.now()
        self.parecer = parecer[:255]
        self.save(
            update_fields=["status", "aprovada_por", "avaliada_em", "parecer", "updated_at"]
        )


# ==============================================================
# Afastamentos (Secao 8.8 — "Periodo de afastamento")
# ==============================================================
class Afastamento(TenantBaseModel):
    colaborador = models.ForeignKey(
        Colaborador,
        on_delete=models.CASCADE,
        related_name="afastamentos",
        verbose_name="Colaborador",
    )
    tipo = models.CharField("Tipo", max_length=25, choices=TipoAfastamento.choices)
    data_inicio = models.DateField("Início")
    data_fim = models.DateField("Fim")
    observacoes = models.TextField("Observações", blank=True)
    documento = models.FileField(
        "Documento", upload_to="afastamentos/%Y/%m/", null=True, blank=True
    )

    class Meta:
        verbose_name = "Afastamento"
        verbose_name_plural = "Afastamentos"
        ordering = ("-data_inicio",)
        indexes = [models.Index(fields=["colaborador", "data_inicio", "data_fim"])]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.colaborador.nome_exibicao}"

    @property
    def dias(self) -> int:
        return (self.data_fim - self.data_inicio).days + 1

    def cobre(self, dia: date) -> bool:
        return self.data_inicio <= dia <= self.data_fim
