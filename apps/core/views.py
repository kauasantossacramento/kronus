"""
Kronus — views transversais: roteamento por papel, selecao de empresa
e paginas de erro.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.core.constants import TipoUsuario
from apps.core.middleware import CHAVE_SESSAO_EMPRESA
from apps.core.mixins import escopo_empresas


@login_required
def home(request):
    """
    Porta de entrada pos-login: encaminha cada papel ao seu painel.
    """
    tipo = request.user.tipo
    if tipo == TipoUsuario.MASTER:
        return redirect("master:dashboard")
    if tipo in (TipoUsuario.CLIENTE, TipoUsuario.RH):
        if request.empresa_ativa is None:
            return redirect("core:selecionar_empresa")
        return redirect("rh:dashboard")
    if tipo == TipoUsuario.CONTADOR:
        return redirect("relatorios:portal_contador")
    return redirect("ponto:registrar")


@login_required
def selecionar_empresa(request):
    """
    Seleciona a empresa ativa da sessao.

    Necessaria para usuarios com acesso a mais de uma empresa
    (Cliente com varias empresas, RH multi-filial, Master).
    """
    empresas = escopo_empresas(request.user).select_related("cliente")

    if request.method == "POST":
        pk = request.POST.get("empresa")
        empresa = empresas.filter(pk=pk).first()
        if empresa is None:
            messages.error(request, "Empresa inválida ou fora do seu escopo.")
        else:
            request.session[CHAVE_SESSAO_EMPRESA] = empresa.pk
            messages.success(request, f"Empresa ativa: {empresa.nome_exibicao}")
            return redirect("core:home")

    return render(
        request,
        "core/selecionar_empresa.html",
        {"empresas": empresas, "titulo": "Selecionar empresa"},
    )


@login_required
def cliente_suspenso(request):
    """Tela exibida quando a assinatura do cliente esta suspensa."""
    return render(request, "core/cliente_suspenso.html", status=403)


# ==============================================================
# Paginas de erro
# ==============================================================
def erro_403(request, exception=None):
    return render(
        request,
        "errors/403.html",
        {"mensagem": str(exception) if exception else ""},
        status=403,
    )


def erro_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def erro_500(request):
    return render(request, "errors/500.html", status=500)
