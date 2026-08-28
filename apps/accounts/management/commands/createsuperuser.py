"""
Kronus — `manage.py createsuperuser` adaptado ao login por e-mail ou CPF.

O comando padrão do Django pede o USERNAME_FIELD cru. Aqui ele:

  * pergunta explicitamente **"E-mail ou CPF"**;
  * aceita o CPF com máscara (`529.982.247-25`) e normaliza para dígitos;
  * valida o identificador no próprio prompt, em vez de estourar depois;
  * preenche `email` **ou** `cpf` conforme o que foi informado, de modo
    que os dois backends de autenticação funcionem em seguida;
  * cria o usuário já com `tipo = master` (o papel da KS TEC).

Uso:
    python manage.py createsuperuser
    python manage.py createsuperuser --username admin@kstec.online --nome_completo "Admin"
    python manage.py createsuperuser --noinput --username 529.982.247-25 \
        --nome_completo "Admin" --password ...      # apenas para automação
"""
from django.contrib.auth.management.commands import createsuperuser
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

from apps.accounts.models import separar_identificador, validar_email_ou_cpf
from apps.core.constants import TipoUsuario
from apps.core.utils import apenas_digitos, formatar_cpf


class Command(createsuperuser.Command):
    help = (
        "Cria um usuário Master (KS TEC). O identificador de acesso pode ser "
        "um e-mail ou um CPF."
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--password",
            dest="password",
            default=None,
            help=(
                "Define a senha diretamente. Use apenas em automação — a senha "
                "fica visível no histórico do shell."
            ),
        )

    # -- normalização e validação do identificador -------------
    def get_input_data(self, field, message, default=None):
        """
        Intercepta o prompt do USERNAME_FIELD para aceitar máscara de CPF
        e recusar identificadores inválidos antes de seguir adiante.
        """
        valor = super().get_input_data(field, message, default)
        if field.name != "username" or not valor:
            return valor

        valor = valor.strip()
        if "@" not in valor:
            valor = apenas_digitos(valor)

        try:
            validar_email_ou_cpf(valor)
        except ValidationError as erro:
            self.stderr.write(self.style.ERROR(f"Erro: {erro.messages[0]}"))
            return None  # o Django repete o prompt
        return valor

    def handle(self, *args, **options):
        username = options.get("username")
        if username:
            if "@" not in username:
                username = apenas_digitos(username)
            try:
                validar_email_ou_cpf(username)
            except ValidationError as erro:
                raise CommandError(erro.messages[0])
            options["username"] = username

        senha = options.pop("password", None)

        if options.get("interactive", True):
            self.stdout.write(
                self.style.MIGRATE_HEADING("\nKronus — criação de usuário Master")
            )
            self.stdout.write(
                "O identificador de acesso pode ser um e-mail (ex.: admin@kstec.online) "
                "ou um CPF (ex.: 529.982.247-25).\n"
            )

        super().handle(*args, **options)

        # O comando do Django não devolve o objeto criado; recuperamos pelo
        # identificador para completar os campos próprios do Kronus.
        criado = self.UserModel._default_manager.db_manager(
            options.get("database")
        ).filter(username=options.get("username")).first()

        if criado is None:
            return

        email, cpf = separar_identificador(criado.username)
        campos = []
        if email and not criado.email:
            criado.email = email
            campos.append("email")
        if cpf and not criado.cpf:
            criado.cpf = cpf
            campos.append("cpf")
        if criado.tipo != TipoUsuario.MASTER:
            criado.tipo = TipoUsuario.MASTER
            campos.append("tipo")
        if senha:
            criado.set_password(senha)
            campos.append("password")
        if campos:
            criado.save(update_fields=campos)

        identificacao = criado.email or formatar_cpf(criado.cpf or "")
        self.stdout.write(
            self.style.SUCCESS(
                f"Usuário Master criado: {criado.nome_completo} ({identificacao}). "
                "Acesse /accounts/login/ usando este identificador."
            )
        )
