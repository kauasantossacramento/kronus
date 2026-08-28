"""
Kronus — views transversais: roteamento por papel, selecao de empresa
e paginas de erro.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

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


@never_cache
def manifesto_do_painel(request):
    """
    Manifesto PWA da area administrativa (`/app/manifest.json`).

    O painel se instala com a identidade de quem esta usando: o RH de uma
    empresa recebe o icone e o nome dela; o Master recebe o Kronus. Um
    manifesto unico faria todo mundo instalar o mesmo icone generico, e
    quem administra duas empresas nao saberia qual e qual na tela inicial.
    """
    from django.http import JsonResponse

    from apps.core.icones_pwa import para_logo

    empresa = getattr(request, "empresa_ativa", None)
    if empresa is not None:
        nome = empresa.nome_exibicao
        icones = para_logo(empresa.logo.url if empresa.logo else None)
        cor = empresa.cor_primaria
    else:
        nome = "Kronus"
        icones = para_logo(None)
        cor = "#1E3A5F"

    return JsonResponse({
        "name": f"{nome} — Administração",
        "short_name": nome[:12],
        "description": f"Painel administrativo de {nome}",
        "start_url": "/app/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#F8FAFC",
        "theme_color": cor,
        "lang": "pt-BR",
        "icons": icones,
    })
