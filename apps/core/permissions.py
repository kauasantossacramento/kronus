"""
Kronus — permissoes (DRF e verificacoes reutilizaveis).

Hierarquia (Secao 1.5 do plano):
    Master (KS TEC) > Cliente > Admin RH > Colaborador

O Master enxerga tudo. O Cliente enxerga apenas as suas empresas.
O Admin RH enxerga apenas as empresas as quais foi vinculado.
O Colaborador enxerga apenas os proprios dados.
"""
from rest_framework.permissions import BasePermission

from apps.core.constants import TipoUsuario


# ==============================================================
# Verificacoes puras (usadas tambem por views e templates)
# ==============================================================
def eh_master(user) -> bool:
    return bool(user and user.is_authenticated and user.tipo == TipoUsuario.MASTER)


def eh_admin_cliente(user) -> bool:
    return bool(user and user.is_authenticated and user.tipo == TipoUsuario.CLIENTE)


def eh_admin_rh(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.tipo in (TipoUsuario.RH, TipoUsuario.CLIENTE)
    )


def eh_colaborador(user) -> bool:
    return bool(user and user.is_authenticated and user.tipo == TipoUsuario.COLABORADOR)


def eh_contador(user) -> bool:
    return bool(user and user.is_authenticated and user.tipo == TipoUsuario.CONTADOR)


def pode_gerenciar_empresa(user, empresa) -> bool:
    """O usuario tem poder administrativo sobre esta empresa?"""
    if not user or not user.is_authenticated or empresa is None:
        return False
    if eh_master(user):
        return True
    if user.cliente_id and user.cliente_id != empresa.cliente_id:
        return False
    if eh_admin_cliente(user):
        return True
    if user.tipo in (TipoUsuario.RH, TipoUsuario.CONTADOR):
        return user.empresas.filter(pk=empresa.pk).exists()
    return False


def pode_ver_colaborador(user, colaborador) -> bool:
    if not user or not user.is_authenticated or colaborador is None:
        return False
    if eh_master(user):
        return True
    if eh_colaborador(user):
        return getattr(user, "colaborador", None) == colaborador
    return pode_gerenciar_empresa(user, colaborador.empresa)


# ==============================================================
# Permissoes DRF
# ==============================================================
class IsMaster(BasePermission):
    message = "Acesso restrito ao administrador Master (KS TEC)."

    def has_permission(self, request, view):
        return eh_master(request.user)


class IsClientAdmin(BasePermission):
    message = "Acesso restrito ao administrador do cliente."

    def has_permission(self, request, view):
        return eh_master(request.user) or eh_admin_cliente(request.user)


class IsRHAdmin(BasePermission):
    message = "Acesso restrito ao RH."

    def has_permission(self, request, view):
        return eh_master(request.user) or eh_admin_rh(request.user)


class IsColaborador(BasePermission):
    message = "Acesso restrito a colaboradores."

    def has_permission(self, request, view):
        return eh_colaborador(request.user)


class IsContador(BasePermission):
    message = "Acesso restrito ao portal do contador."

    def has_permission(self, request, view):
        return eh_master(request.user) or eh_contador(request.user)


class PertenceAoTenant(BasePermission):
    """
    Garante, no nivel do objeto, que o recurso pertence ao escopo do usuario.

    Funciona com qualquer objeto que exponha `empresa` ou `cliente`.
    """

    message = "Este recurso não pertence ao seu escopo de acesso."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if eh_master(user):
            return True
        empresa = getattr(obj, "empresa", None)
        if empresa is not None:
            if eh_colaborador(user):
                colaborador = getattr(user, "colaborador", None)
                return colaborador is not None and colaborador.empresa_id == empresa.pk
            return pode_gerenciar_empresa(user, empresa)
        cliente = getattr(obj, "cliente", None)
        if cliente is not None:
            return user.cliente_id == cliente.pk
        return False


class SomenteLeitura(BasePermission):
    def has_permission(self, request, view):
        return request.method in ("GET", "HEAD", "OPTIONS")
