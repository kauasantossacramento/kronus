"""
Kronus — middlewares.

TenantMiddleware      resolve cliente/empresa ativos e injeta em `request`
TimezoneMiddleware    ativa o fuso horario da empresa ativa (multi-fuso)
AuditoriaMiddleware   guarda IP/user-agent no contexto para os signals
SecurityHeadersMiddleware  aplica CSP e cabecalhos de seguranca
"""
import zoneinfo
from threading import local

from django.conf import settings
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from apps.core.constants import TipoUsuario

#: Contexto por thread — permite que signals (sem acesso ao request)
#: saibam quem disparou a acao. Ver apps.core.services.registrar_log.
_contexto = local()

CHAVE_SESSAO_EMPRESA = "kronus_empresa_ativa"


def contexto_atual() -> dict:
    return getattr(_contexto, "dados", {}) or {}


def definir_contexto(**kwargs):
    _contexto.dados = {**contexto_atual(), **kwargs}


def limpar_contexto():
    _contexto.dados = {}


class TenantMiddleware(MiddlewareMixin):
    """
    Resolve o tenant da requisicao.

    Injeta em `request`:
        request.cliente        — Cliente do usuario (None para Master sem contexto)
        request.empresa_ativa  — Empresa selecionada na sessao (ou unica disponivel)
        request.colaborador    — Colaborador vinculado, quando aplicavel

    Bloqueia o acesso de clientes suspensos (Secao 6.7 — acao "Suspender").
    """

    ROTAS_LIVRES = ("/totem/", "/api/v1/totem/", "/static/", "/media/", "/django-admin/")

    def process_request(self, request):
        request.cliente = None
        request.empresa_ativa = None
        request.colaborador = None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        request.cliente = getattr(user, "cliente", None)
        request.colaborador = getattr(user, "colaborador", None)
        request.empresa_ativa = self._resolver_empresa(request, user)

        definir_contexto(
            usuario=user,
            cliente=request.cliente,
            empresa=request.empresa_ativa,
            ip=self._ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
        )

        # Cliente suspenso: somente leitura do proprio painel e logout.
        if (
            request.cliente
            and request.cliente.suspenso
            and user.tipo != TipoUsuario.MASTER
            and not request.path.startswith(("/accounts/", "/app/suspenso"))
            and not request.path.startswith(self.ROTAS_LIVRES)
        ):
            from django.shortcuts import redirect

            return redirect("core:cliente_suspenso")
        return None

    def process_response(self, request, response):
        limpar_contexto()
        return response

    # -- internos ----------------------------------------------
    @staticmethod
    def _ip(request):
        encaminhado = request.META.get("HTTP_X_FORWARDED_FOR")
        if encaminhado:
            return encaminhado.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    @staticmethod
    def _resolver_empresa(request, user):
        from apps.core.mixins import escopo_empresas

        empresas = escopo_empresas(user)
        pk_sessao = request.session.get(CHAVE_SESSAO_EMPRESA)
        if pk_sessao:
            empresa = empresas.filter(pk=pk_sessao).first()
            if empresa is not None:
                return empresa
            request.session.pop(CHAVE_SESSAO_EMPRESA, None)
        if user.tipo == TipoUsuario.MASTER:
            return None
        # Usuario com uma unica empresa: seleciona automaticamente.
        primeira = empresas.first()
        if primeira is not None and empresas.count() == 1:
            request.session[CHAVE_SESSAO_EMPRESA] = primeira.pk
            return primeira
        return primeira


class TimezoneMiddleware(MiddlewareMixin):
    """
    Ativa o fuso horario da empresa ativa (Secao 8.8 — multi-fuso horario).

    Sem empresa ativa, mantem `settings.TIME_ZONE`.
    """

    def process_request(self, request):
        empresa = getattr(request, "empresa_ativa", None)
        nome_fuso = getattr(empresa, "fuso_horario", None) or settings.TIME_ZONE
        try:
            timezone.activate(zoneinfo.ZoneInfo(nome_fuso))
        except Exception:  # fuso invalido cadastrado — nao derruba a requisicao
            timezone.activate(zoneinfo.ZoneInfo(settings.TIME_ZONE))
        return None

    def process_response(self, request, response):
        timezone.deactivate()
        return response


class AuditoriaMiddleware(MiddlewareMixin):
    """
    Anexa metadados da requisicao ao contexto de thread.

    Complementa o TenantMiddleware para rotas anonimas (ex.: login),
    onde ainda assim queremos IP e user-agent nos logs.
    """

    def process_request(self, request):
        if not contexto_atual():
            definir_contexto(
                ip=TenantMiddleware._ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
            )
        return None


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Cabecalhos de seguranca (Secao 9 do plano).

    A CSP e permissiva com `unsafe-inline` porque Alpine.js e HTMX usam
    atributos inline; scripts externos ficam restritos aos CDNs declarados.
    """

    def process_response(self, request, response):
        if not hasattr(settings, "CSP_DEFAULT_SRC"):
            return response
        if request.path.startswith("/totem/"):
            # O totem usa blob: para frames de camera e workers.
            extra_script = " blob:"
            extra_worker = "worker-src 'self' blob:; "
        else:
            extra_script = ""
            extra_worker = ""
        politica = (
            f"default-src {settings.CSP_DEFAULT_SRC}; "
            f"img-src {settings.CSP_IMG_SRC}; "
            f"script-src {settings.CSP_SCRIPT_SRC}{extra_script}; "
            f"style-src {settings.CSP_STYLE_SRC}; "
            f"font-src {settings.CSP_FONT_SRC}; "
            f"connect-src {settings.CSP_CONNECT_SRC}; "
            f"{extra_worker}"
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.setdefault("Content-Security-Policy", politica)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault(
            "Permissions-Policy", "camera=(self), geolocation=(self), microphone=()"
        )
        return response
