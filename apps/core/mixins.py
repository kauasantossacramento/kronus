"""
Kronus — mixins de views e models.

`TenantScopedMixin` e a peca central do isolamento multi-tenant por linha:
toda listagem administrativa passa por `escopo_empresas()`, que nunca
devolve dados fora do alcance do usuario autenticado.
"""
from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from apps.core.constants import TipoUsuario
from apps.core.permissions import (
    eh_admin_cliente,
    eh_admin_rh,
    eh_colaborador,
    eh_master,
    pode_gerenciar_empresa,
)


# ==============================================================
# Escopo de tenant
# ==============================================================
def escopo_empresas(user) -> QuerySet:
    """
    QuerySet de `clientes.Empresa` visiveis para o usuario.

    Master        -> todas
    Cliente       -> todas as empresas do seu cliente
    RH / Contador -> apenas as empresas vinculadas ao usuario
    Colaborador   -> apenas a propria empresa
    """
    from apps.clientes.models import Empresa

    if not user or not user.is_authenticated:
        return Empresa.objects.none()
    if eh_master(user):
        return Empresa.objects.all()
    if eh_admin_cliente(user):
        return Empresa.objects.filter(cliente_id=user.cliente_id)
    if eh_colaborador(user):
        colaborador = getattr(user, "colaborador", None)
        if colaborador is None:
            return Empresa.objects.none()
        return Empresa.objects.filter(pk=colaborador.empresa_id)
    return user.empresas.all()


class TenantScopedMixin(LoginRequiredMixin):
    """
    Mixin de CBV que restringe o queryset ao escopo do tenant.

    A view declara `tenant_field` (default: "empresa") e o mixin aplica
    o filtro. Views cujo model se relaciona indiretamente com a empresa
    devem sobrescrever `filtrar_por_tenant`.
    """

    tenant_field = "empresa"

    def get_queryset(self):
        queryset = super().get_queryset()
        return self.filtrar_por_tenant(queryset)

    def filtrar_por_tenant(self, queryset: QuerySet) -> QuerySet:
        if eh_master(self.request.user) and self.request.empresa_ativa is None:
            return queryset
        empresas = escopo_empresas(self.request.user)
        if self.request.empresa_ativa is not None:
            empresas = empresas.filter(pk=self.request.empresa_ativa.pk)
        return queryset.filter(**{f"{self.tenant_field}__in": empresas})

    @property
    def empresa_atual(self):
        return self.request.empresa_ativa

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["empresa_atual"] = self.request.empresa_ativa
        contexto["empresas_disponiveis"] = escopo_empresas(self.request.user)
        return contexto


# ==============================================================
# Controle de papel
# ==============================================================
class RoleRequiredMixin(AccessMixin):
    """Exige que `request.user.tipo` esteja em `tipos_permitidos`."""

    tipos_permitidos: tuple = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.tipo == TipoUsuario.MASTER:
            return super().dispatch(request, *args, **kwargs)
        if self.tipos_permitidos and request.user.tipo not in self.tipos_permitidos:
            raise PermissionDenied("Você não tem permissão para acessar esta área.")
        return super().dispatch(request, *args, **kwargs)


class MasterRequiredMixin(RoleRequiredMixin):
    tipos_permitidos = (TipoUsuario.MASTER,)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not eh_master(request.user):
            raise PermissionDenied("Área restrita ao Master (KS TEC).")
        return super(RoleRequiredMixin, self).dispatch(request, *args, **kwargs)


class RHRequiredMixin(RoleRequiredMixin):
    tipos_permitidos = (TipoUsuario.RH, TipoUsuario.CLIENTE)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (eh_master(request.user) or eh_admin_rh(request.user)):
            raise PermissionDenied("Área restrita ao RH.")
        return super(RoleRequiredMixin, self).dispatch(request, *args, **kwargs)


class ColaboradorRequiredMixin(RoleRequiredMixin):
    tipos_permitidos = (TipoUsuario.COLABORADOR,)


# ==============================================================
# Auditoria automatica em CBVs de escrita
# ==============================================================
class AuditMixin:
    """
    Grava um `LogAcesso` apos create/update/delete bem-sucedido.

    A view pode customizar `descricao_auditoria(objeto)`.
    """

    acao_auditoria = None

    def descricao_auditoria(self, objeto) -> str:
        return f"{objeto._meta.verbose_name}: {objeto}"

    def registrar_auditoria(self, objeto, acao=None):
        from apps.core.services import registrar_log

        registrar_log(
            request=self.request,
            acao=acao or self.acao_auditoria,
            descricao=self.descricao_auditoria(objeto),
            objeto=objeto,
        )

    def form_valid(self, form):
        resposta = super().form_valid(form)
        self.registrar_auditoria(self.object)
        return resposta


class SucessoMensagemMixin:
    """Mensagem de sucesso padronizada (toast) apos operacoes."""

    mensagem_sucesso = "Operação realizada com sucesso."

    def form_valid(self, form):
        from django.contrib import messages

        resposta = super().form_valid(form)
        messages.success(self.request, self.mensagem_sucesso)
        return resposta


# ==============================================================
# Helpers
# ==============================================================
def obter_empresa_do_escopo(user, pk_ou_uuid):
    """Busca uma empresa garantindo que ela pertence ao escopo do usuario."""
    empresas = escopo_empresas(user)
    campo = "uuid" if not str(pk_ou_uuid).isdigit() else "pk"
    empresa = get_object_or_404(empresas, **{campo: pk_ou_uuid})
    if not pode_gerenciar_empresa(user, empresa) and not eh_colaborador(user):
        raise PermissionDenied("Empresa fora do seu escopo de acesso.")
    return empresa
