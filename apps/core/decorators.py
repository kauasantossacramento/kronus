"""Kronus — decorators para function-based views."""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from apps.core.constants import TipoUsuario
from apps.core.permissions import eh_admin_rh, eh_colaborador, eh_master


def _exigir(teste, mensagem):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("accounts:login")
            if not teste(request.user):
                raise PermissionDenied(mensagem)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


master_required = _exigir(eh_master, "Área restrita ao Master (KS TEC).")

rh_required = _exigir(
    lambda u: eh_master(u) or eh_admin_rh(u), "Área restrita ao RH."
)

colaborador_required = _exigir(eh_colaborador, "Área restrita a colaboradores.")


def tipos_permitidos(*tipos):
    """Uso: @tipos_permitidos(TipoUsuario.RH, TipoUsuario.CLIENTE)"""
    tipos = set(tipos) | {TipoUsuario.MASTER}
    return _exigir(
        lambda u: u.tipo in tipos, "Você não tem permissão para acessar esta área."
    )


def empresa_ativa_required(view_func):
    """
    Garante que ha uma empresa selecionada no contexto.

    Sem empresa ativa (caso tipico do Master), redireciona para a
    tela de selecao de empresa.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        if getattr(request, "empresa_ativa", None) is None:
            return redirect("core:selecionar_empresa")
        return view_func(request, *args, **kwargs)

    return _wrapped


def plano_requer(recurso: str):
    """
    Bloqueia funcionalidades nao contratadas (Secao 4.1 — flags do Plano).

    Exemplo: @plano_requer("tem_api")
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            cliente = getattr(request, "cliente", None)
            if cliente is not None and not getattr(cliente.plano, recurso, False):
                raise PermissionDenied(
                    "Este recurso não está incluído no plano contratado."
                )
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
