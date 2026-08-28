"""Kronus — permissões específicas da API REST."""
from rest_framework.permissions import BasePermission


class TotemAutenticado(BasePermission):
    """Exige um token de totem válido (ver apps.api.authentication)."""

    message = "Esta operação exige autenticação de totem."

    def has_permission(self, request, view):
        return getattr(request, "totem", None) is not None


class APIKeyAutenticada(BasePermission):
    """Exige uma chave de API válida, de empresa ou de cliente."""

    message = "Esta operação exige uma chave de API válida."

    def has_permission(self, request, view):
        return bool(getattr(request, "api_empresas", None))


class APIKeyEscrita(APIKeyAutenticada):
    """Bloqueia escrita em chaves marcadas como somente leitura."""

    message = "Esta chave de API é somente leitura."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        api_key = getattr(request, "api_key", None)
        return api_key is None or not api_key.somente_leitura
