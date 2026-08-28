"""
Kronus — backends de autenticacao.

O plano preve login por CPF **ou** e-mail (Secao 6.2). Cada backend
resolve o identificador para um `CustomUser` e delega a verificacao de
senha ao Django.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from apps.core.utils import apenas_digitos

User = get_user_model()


class _BaseKronusBackend(ModelBackend):
    """Compartilha o tratamento de bloqueio por tentativas."""

    def _finalizar(self, user, password, request=None):
        if user is None:
            # Roda o hasher mesmo sem usuario para nao vazar tempo de resposta.
            User().set_password(password)
            return None
        if user.esta_bloqueado:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        user.registrar_falha_login()
        return None


class CPFAuthBackend(_BaseKronusBackend):
    """Autentica por CPF (com ou sem mascara)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        identificador = username or kwargs.get("cpf")
        if not identificador or not password:
            return None
        cpf = apenas_digitos(identificador)
        if len(cpf) != 11:
            return None
        user = User.objects.filter(cpf=cpf).first()
        return self._finalizar(user, password, request)


class EmailAuthBackend(_BaseKronusBackend):
    """Autentica por e-mail (case-insensitive)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        identificador = username or kwargs.get("email")
        if not identificador or not password:
            return None
        if "@" not in identificador:
            return None
        user = User.objects.filter(email__iexact=identificador.strip()).first()
        return self._finalizar(user, password, request)
