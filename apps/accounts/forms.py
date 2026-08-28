"""Kronus — formularios de autenticacao e perfil."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.core.constants import TipoUsuario
from apps.core.utils import apenas_digitos, cpf_valido

User = get_user_model()

CLASSES_INPUT = (
    "block w-full rounded-lg border-0 py-2.5 px-3 text-slate-900 shadow-sm "
    "ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 "
    "focus:ring-2 focus:ring-inset focus:ring-[var(--kronus-primary-500)] "
    "sm:text-sm sm:leading-6"
)


class LoginForm(AuthenticationForm):
    """
    Login unificado: o campo `username` aceita CPF (com ou sem mascara)
    ou e-mail. O toggle da tela apenas troca a mascara do input.
    """

    username = forms.CharField(
        label="CPF ou e-mail",
        widget=forms.TextInput(
            attrs={
                "class": CLASSES_INPUT,
                "autofocus": True,
                "autocomplete": "username",
                "placeholder": "000.000.000-00 ou voce@empresa.com",
                "x-model": "identificador",
            }
        ),
    )
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(
            attrs={
                "class": CLASSES_INPUT,
                "autocomplete": "current-password",
                "placeholder": "••••••••",
            }
        ),
    )
    lembrar = forms.BooleanField(
        label="Lembrar-me",
        required=False,
        widget=forms.CheckboxInput(
            attrs={
                "class": "h-4 w-4 rounded border-slate-300 "
                "text-[var(--kronus-primary-600)] focus:ring-[var(--kronus-primary-500)]"
            }
        ),
    )

    error_messages = {
        "invalid_login": "CPF/e-mail ou senha incorretos.",
        "inactive": "Esta conta está inativa. Fale com o administrador.",
    }

    def clean_username(self):
        valor = (self.cleaned_data.get("username") or "").strip()
        if "@" in valor:
            return valor.lower()
        digitos = apenas_digitos(valor)
        return digitos if digitos else valor


class TrocarSenhaPrimeiroAcessoForm(forms.Form):
    """Troca obrigatoria de senha no primeiro acesso."""

    nova_senha = forms.CharField(
        label="Nova senha",
        widget=forms.PasswordInput(attrs={"class": CLASSES_INPUT}),
        min_length=8,
    )
    confirmacao = forms.CharField(
        label="Confirme a nova senha",
        widget=forms.PasswordInput(attrs={"class": CLASSES_INPUT}),
    )

    def clean(self):
        dados = super().clean()
        if dados.get("nova_senha") != dados.get("confirmacao"):
            raise forms.ValidationError("As senhas não conferem.")
        return dados


class PerfilForm(forms.ModelForm):
    """Edicao dos proprios dados pelo usuario autenticado."""

    class Meta:
        model = User
        fields = ("nome_completo", "email", "telefone", "avatar")
        widgets = {
            "nome_completo": forms.TextInput(attrs={"class": CLASSES_INPUT}),
            "email": forms.EmailInput(attrs={"class": CLASSES_INPUT}),
            "telefone": forms.TextInput(
                attrs={"class": CLASSES_INPUT, "placeholder": "(00) 00000-0000"}
            ),
        }


class UsuarioAdminForm(UserCreationForm):
    """Criacao de usuarios administrativos (Master, Cliente, RH, Contador)."""

    class Meta:
        model = User
        fields = ("nome_completo", "email", "cpf", "tipo", "cliente", "empresas")
        widgets = {
            "nome_completo": forms.TextInput(attrs={"class": CLASSES_INPUT}),
            "email": forms.EmailInput(attrs={"class": CLASSES_INPUT}),
            "cpf": forms.TextInput(
                attrs={"class": CLASSES_INPUT, "placeholder": "000.000.000-00"}
            ),
            "tipo": forms.Select(attrs={"class": CLASSES_INPUT}),
            "cliente": forms.Select(attrs={"class": CLASSES_INPUT}),
            "empresas": forms.SelectMultiple(attrs={"class": CLASSES_INPUT, "size": 6}),
        }

    def clean_cpf(self):
        valor = apenas_digitos(self.cleaned_data.get("cpf") or "")
        if valor and not cpf_valido(valor):
            raise forms.ValidationError("CPF inválido.")
        return valor or None

    def clean(self):
        dados = super().clean()
        tipo = dados.get("tipo")
        cliente = dados.get("cliente")
        if tipo != TipoUsuario.MASTER and not cliente:
            self.add_error("cliente", "Informe o cliente ao qual este usuário pertence.")
        if tipo == TipoUsuario.MASTER and cliente:
            self.add_error("cliente", "Usuário Master não pertence a um cliente.")
        if not dados.get("email") and not dados.get("cpf"):
            raise forms.ValidationError("Informe pelo menos um e-mail ou um CPF.")
        return dados
