"""
Kronus — usuarios e autenticacao.

`CustomUser` unifica os quatro papeis do plano (Master, Cliente, RH,
Colaborador). O login aceita **CPF ou e-mail** (Secao 6.2); internamente
o Django continua usando `username`, preenchido automaticamente com o
e-mail ou com os digitos do CPF.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.utils import timezone

from apps.core.constants import TipoUsuario
from apps.core.utils import apenas_digitos, cpf_valido, formatar_cpf, mascarar_cpf


def validar_email_ou_cpf(valor: str):
    """
    Validator do campo `username`.

    O identificador de acesso do Kronus e um e-mail OU um CPF — nunca um
    apelido livre. Validar aqui faz o `manage.py createsuperuser` recusar
    entradas invalidas no proprio prompt, em vez de falhar depois.
    """
    valor = (valor or "").strip()
    if "@" in valor:
        try:
            validate_email(valor)
        except ValidationError:
            raise ValidationError(
                "E-mail invalido. Informe um e-mail valido ou um CPF.",
                code="identificador_invalido",
            )
        return
    digitos = apenas_digitos(valor)
    if not digitos:
        raise ValidationError(
            "Informe um e-mail ou um CPF.", code="identificador_invalido"
        )
    if not cpf_valido(digitos):
        raise ValidationError(
            "CPF invalido. Informe um e-mail valido ou um CPF com 11 digitos.",
            code="identificador_invalido",
        )


def separar_identificador(valor: str) -> tuple[str | None, str | None]:
    """Devolve `(email, cpf)` a partir de um identificador unico."""
    valor = (valor or "").strip()
    if not valor:
        return None, None
    if "@" in valor:
        return valor.lower(), None
    digitos = apenas_digitos(valor)
    return None, (digitos or None)


class CustomUserManager(BaseUserManager):
    """Manager que aceita criacao por e-mail ou por CPF."""

    use_in_migrations = True

    def _criar(self, *, email=None, cpf=None, password=None, **extra):
        # `createsuperuser` entrega apenas o USERNAME_FIELD; quando ele vem
        # sozinho, deduzimos se e um e-mail ou um CPF.
        username = extra.pop("username", None)
        if not email and not cpf and username:
            email, cpf = separar_identificador(username)
        if not email and not cpf:
            raise ValueError("Informe um e-mail ou um CPF para criar o usuário.")
        email = self.normalize_email(email).strip().lower() if email else None
        cpf = apenas_digitos(cpf) if cpf else None
        username = username or email or cpf
        user = self.model(username=username, email=email, cpf=cpf, **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"], validate_unique=False)
        user.save(using=self._db)
        return user

    def create_user(self, email=None, cpf=None, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        extra.setdefault("tipo", TipoUsuario.COLABORADOR)
        return self._criar(email=email, cpf=cpf, password=password, **extra)

    def create_superuser(self, email=None, cpf=None, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("tipo", TipoUsuario.MASTER)
        extra.setdefault("nome_completo", "Administrador Master")
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("Superusuário precisa de is_staff e is_superuser.")
        return self._criar(email=email, cpf=cpf, password=password, **extra)


class CustomUser(AbstractUser):
    """
    Usuario da plataforma.

    Regras de vinculo:
        MASTER      -> cliente vazio
        CLIENTE     -> cliente obrigatorio; acessa todas as empresas dele
        RH          -> cliente obrigatorio + empresas vinculadas
        CONTADOR    -> cliente obrigatorio + empresas vinculadas (somente leitura)
        COLABORADOR -> cliente obrigatorio; empresa vem de `rh.Colaborador`
    """

    # AbstractUser ja traz: username, first_name, last_name, email,
    # is_staff, is_active, is_superuser, date_joined, last_login.
    first_name = None
    last_name = None

    #: O `username` do Kronus nao e um apelido: e o proprio identificador
    #: de acesso — um e-mail OU um CPF. O verbose_name vira o rotulo do
    #: prompt do `manage.py createsuperuser`.
    username = models.CharField(
        "E-mail ou CPF",
        max_length=150,
        unique=True,
        validators=[validar_email_ou_cpf],
        help_text="Identificador de acesso: um e-mail válido ou um CPF.",
        error_messages={"unique": "Já existe um usuário com este identificador."},
    )

    email = models.EmailField("E-mail", unique=True, null=True, blank=True)
    cpf = models.CharField(
        "CPF", max_length=11, unique=True, null=True, blank=True, db_index=True
    )
    nome_completo = models.CharField("Nome completo", max_length=150)
    telefone = models.CharField("Telefone", max_length=20, blank=True)
    avatar = models.ImageField("Avatar", upload_to="avatares/", null=True, blank=True)

    tipo = models.CharField(
        "Tipo de usuário",
        max_length=15,
        choices=TipoUsuario.choices,
        default=TipoUsuario.COLABORADOR,
        db_index=True,
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="usuarios",
        verbose_name="Cliente",
    )
    empresas = models.ManyToManyField(
        "clientes.Empresa",
        blank=True,
        related_name="usuarios",
        verbose_name="Empresas com acesso",
        help_text="Aplicável a Admin RH e Contador. O Admin do Cliente acessa todas.",
    )

    # -- Seguranca / auditoria ---------------------------------
    trocar_senha_no_proximo_login = models.BooleanField(
        "Trocar senha no próximo login", default=False
    )
    ultimo_acesso_ip = models.GenericIPAddressField("Último IP", null=True, blank=True)
    tentativas_login_falhas = models.PositiveSmallIntegerField(
        "Tentativas de login falhas", default=0
    )
    bloqueado_ate = models.DateTimeField("Bloqueado até", null=True, blank=True)

    # -- LGPD (Secao 10) ---------------------------------------
    aceite_termos_em = models.DateTimeField("Aceite dos termos em", null=True, blank=True)
    aceite_biometria_em = models.DateTimeField(
        "Consentimento biométrico em",
        null=True,
        blank=True,
        help_text="Consentimento explícito para uso de dados faciais (LGPD).",
    )

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["nome_completo"]

    objects = CustomUserManager()

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"
        ordering = ("nome_completo",)
        indexes = [
            models.Index(fields=["tipo", "cliente"]),
        ]

    def __str__(self):
        return self.nome_completo or self.username

    # -- normalizacao ------------------------------------------
    def clean(self):
        super().clean()
        if self.cpf:
            self.cpf = apenas_digitos(self.cpf)
        if self.email:
            self.email = self.email.strip().lower()
        if not self.username:
            self.username = self.email or self.cpf

    def save(self, *args, **kwargs):
        # Vazio vira NULL, sempre — nao apenas quando ja veio preenchido.
        # `email` e `cpf` sao `unique`, e no SQL dois `''` sao iguais
        # enquanto dois `NULL` nao sao: guardar string vazia faria o
        # segundo usuario sem e-mail colidir com o primeiro. Como o
        # sistema aceita cadastro so com CPF, esse segundo usuario chega
        # rapido.
        self.cpf = apenas_digitos(self.cpf) or None if self.cpf else None
        self.email = (self.email or "").strip().lower() or None
        if not self.username:
            self.username = self.email or self.cpf
        super().save(*args, **kwargs)

    # -- apresentacao ------------------------------------------
    @property
    def cpf_formatado(self) -> str:
        return formatar_cpf(self.cpf) if self.cpf else ""

    @property
    def cpf_mascarado(self) -> str:
        return mascarar_cpf(self.cpf) if self.cpf else ""

    @property
    def primeiro_nome(self) -> str:
        return (self.nome_completo or "").split(" ")[0]

    @property
    def iniciais(self) -> str:
        partes = [p for p in (self.nome_completo or "").split(" ") if p]
        if not partes:
            return "?"
        if len(partes) == 1:
            return partes[0][:2].upper()
        return (partes[0][0] + partes[-1][0]).upper()

    def get_full_name(self):
        return self.nome_completo

    def get_short_name(self):
        return self.primeiro_nome

    # -- papeis ------------------------------------------------
    @property
    def eh_master(self) -> bool:
        return self.tipo == TipoUsuario.MASTER

    @property
    def eh_admin_cliente(self) -> bool:
        return self.tipo == TipoUsuario.CLIENTE

    @property
    def eh_rh(self) -> bool:
        return self.tipo in (TipoUsuario.RH, TipoUsuario.CLIENTE)

    @property
    def eh_colaborador(self) -> bool:
        return self.tipo == TipoUsuario.COLABORADOR

    @property
    def cpf_e_valido(self) -> bool:
        return bool(self.cpf) and cpf_valido(self.cpf)

    # -- bloqueio por tentativas -------------------------------
    @property
    def esta_bloqueado(self) -> bool:
        return bool(self.bloqueado_ate and self.bloqueado_ate > timezone.now())

    def registrar_falha_login(self, limite=5, minutos_bloqueio=15):
        self.tentativas_login_falhas += 1
        if self.tentativas_login_falhas >= limite:
            self.bloqueado_ate = timezone.now() + timezone.timedelta(
                minutes=minutos_bloqueio
            )
            self.tentativas_login_falhas = 0
        self.save(update_fields=["tentativas_login_falhas", "bloqueado_ate"])

    def registrar_sucesso_login(self, ip=None):
        self.tentativas_login_falhas = 0
        self.bloqueado_ate = None
        self.ultimo_acesso_ip = ip
        self.save(
            update_fields=["tentativas_login_falhas", "bloqueado_ate", "ultimo_acesso_ip"]
        )
