"""Kronus — views de autenticacao, perfil e recuperacao de senha."""
from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from apps.accounts.forms import LoginForm, PerfilForm, TrocarSenhaPrimeiroAcessoForm
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.core.utils import obter_ip


class KronusLoginView(LoginView):
    """
    Login unificado (Secao 6.2 do plano).

    Aceita CPF ou e-mail, registra a tentativa na trilha de auditoria e
    encaminha o usuario ao painel do seu papel.
    """

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Entrar no Kronus"
        return contexto

    def form_valid(self, form):
        resposta = super().form_valid(form)
        user = self.request.user

        if not form.cleaned_data.get("lembrar"):
            self.request.session.set_expiry(0)

        user.registrar_sucesso_login(ip=obter_ip(self.request))
        registrar_log(
            request=self.request,
            acao=LogAcesso.Acao.LOGIN,
            descricao=f"Login de {user.nome_completo} ({user.get_tipo_display()})",
        )

        if user.trocar_senha_no_proximo_login:
            return redirect("accounts:trocar_senha_primeiro_acesso")
        return resposta

    def form_invalid(self, form):
        registrar_log(
            request=self.request,
            acao=LogAcesso.Acao.LOGIN_FALHA,
            descricao=f"Falha de login para '{form.data.get('username', '')[:60]}'",
        )
        return super().form_invalid(form)


class LoginColaboradorView(KronusLoginView):
    """
    Variante visual para o colaborador (`/accounts/colaborador/`).

    Mesma logica de autenticacao, com layout focado em CPF e mobile-first.
    """

    template_name = "accounts/login_colaborador.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Acesso do colaborador"
        contexto["modo_colaborador"] = True
        return contexto


def logout_view(request):
    """
    Encerra a sessao e devolve o usuario a **porta por onde ele entrou**.

    Quem usa o app de uma empresa entra por `kronus.online/<empresa>`,
    com a logo e as cores dela. Jogar essa pessoa na capa comercial do
    Kronus ao sair troca a marca do empregador pela nossa no unico
    momento em que ela nao pediu nada — e, na pratica, ela perde o
    endereco de volta.
    """
    empresa = None
    if request.user.is_authenticated:
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.LOGOUT,
            descricao=f"Logout de {request.user.nome_completo}",
        )
        empresa = _empresa_de_entrada(request)

    auth_logout(request)
    messages.info(request, "Sessão encerrada.")

    if empresa is not None:
        return redirect("clientes:portal", slug=empresa.slug)
    return redirect("landing:index")


def _empresa_de_entrada(request):
    """
    Empresa cuja pagina de acesso serve a este usuario.

    Preferencia para a empresa ativa na sessao; na falta dela, a unica
    empresa do usuario. Com mais de uma e sem escolha feita, nao ha
    resposta certa — e mandar para a errada seria pior do que mandar
    para a capa.
    """
    from apps.core.constants import TipoUsuario

    if request.user.tipo == TipoUsuario.MASTER:
        return None

    empresa = getattr(request, "empresa_ativa", None)
    if empresa is None:
        disponiveis = list(request.user.empresas.filter(ativo=True)[:2])
        empresa = disponiveis[0] if len(disponiveis) == 1 else None

    return empresa if empresa is not None and empresa.slug else None


@login_required
def trocar_senha_primeiro_acesso(request):
    """Fluxo obrigatorio quando `trocar_senha_no_proximo_login` esta ativo."""
    if not request.user.trocar_senha_no_proximo_login:
        return redirect("core:home")

    form = TrocarSenhaPrimeiroAcessoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.set_password(form.cleaned_data["nova_senha"])
        request.user.trocar_senha_no_proximo_login = False
        request.user.save(update_fields=["password", "trocar_senha_no_proximo_login"])
        update_session_auth_hash(request, request.user)
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.SEGURANCA,
            descricao="Senha alterada no primeiro acesso",
        )
        messages.success(request, "Senha atualizada com sucesso.")
        return redirect("core:home")

    return render(
        request,
        "accounts/trocar_senha.html",
        {"form": form, "titulo": "Defina sua senha"},
    )


@login_required
def perfil(request):
    form = PerfilForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.ALTERACAO,
            descricao="Atualização do próprio perfil",
            objeto=request.user,
        )
        messages.success(request, "Perfil atualizado.")
        return redirect("accounts:perfil")
    return render(request, "accounts/perfil.html", {"form": form, "titulo": "Meu perfil"})


# ==============================================================
# Recuperacao de senha
# ==============================================================
class KronusPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/emails/password_reset_email.html"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_context = {"titulo": "Recuperar senha"}


class KronusPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"
    extra_context = {"titulo": "E-mail enviado"}


class KronusPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")
    extra_context = {"titulo": "Nova senha"}


class KronusPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
    extra_context = {"titulo": "Senha redefinida"}
