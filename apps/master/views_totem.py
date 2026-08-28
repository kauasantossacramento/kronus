"""
Kronus — gestão de totens e comodato no painel Master (Seção 11, Fase 5).

    /master/totens/                    parque de equipamentos, com status
    /master/totens/novo/               cadastro
    /master/totens/<pk>/               ficha, eventos e URL de quiosque
    /master/totens/<pk>/editar/
    /master/totens/<pk>/comodato/      contrato, instalação e devolução
    /master/totens/<pk>/token/         regenera o token de acesso
    /master/totens/<pk>/devolver/      encerra o comodato
    /master/grupos-totem/              grupos compartilhados entre empresas

**Por que isto vive no Master e não no RH.** O totem é *propriedade da
KS TEC* em comodato: quem cadastra, instala, troca e recolhe o
equipamento é a KS TEC. O RH configura a operação do totem que já tem
(mensagem de boas-vindas, tolerância), não o parque. Dar ao cliente o
poder de emitir totens permitiria estourar o limite do plano por dentro.
"""
import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.decorators import master_required
from apps.core.mixins import MasterRequiredMixin, SucessoMensagemMixin
from apps.core.utils import obter_ip
from apps.master.forms import ComodatoForm, GrupoTotemForm, TotemForm
from apps.master.models import LogAcessoMaster
from apps.totem.models import EventoTotem, GrupoTotem, Totem

logger = logging.getLogger("kronus.master")


def _log(request, acao, cliente=None, detalhes=""):
    LogAcessoMaster.objects.create(
        usuario=request.user,
        cliente=cliente,
        acao=acao,
        detalhes=detalhes,
        ip=obter_ip(request),
    )


# ══════════════════════════════════════════════════════════════
# Parque de totens
# ══════════════════════════════════════════════════════════════
class TotemListView(MasterRequiredMixin, ListView):
    """
    O parque inteiro, ordenado por criticidade.

    **Offline primeiro.** Um totem offline é um relógio de ponto que não
    está registrando: alguém na portaria de um cliente está sem bater
    ponto agora. Ordenar por nome deixaria isso enterrado na lista.
    """

    model = Totem
    template_name = "master/totens/lista.html"
    context_object_name = "totens"
    paginate_by = 30

    def get_queryset(self):
        queryset = Totem.objects.select_related(
            "empresa", "empresa__cliente", "grupo"
        )

        parametros = self.request.GET
        if busca := parametros.get("busca"):
            queryset = queryset.filter(
                Q(identificador__icontains=busca)
                | Q(apelido__icontains=busca)
                | Q(serial_tablet__icontains=busca)
                | Q(empresa__razao_social__icontains=busca)
                | Q(empresa__cliente__razao_social__icontains=busca)
            )

        situacao = parametros.get("situacao")
        limite = timezone.now() - timezone.timedelta(
            minutes=Totem.MINUTOS_PARA_OFFLINE
        )
        if situacao == "online":
            queryset = queryset.filter(ativo=True, ultimo_heartbeat__gte=limite)
        elif situacao == "offline":
            queryset = queryset.filter(ativo=True).filter(
                Q(ultimo_heartbeat__lt=limite) | Q(ultimo_heartbeat__isnull=True)
            )
        elif situacao == "inativo":
            queryset = queryset.filter(ativo=False)
        elif situacao == "comodato":
            queryset = queryset.filter(em_comodato=True, data_devolucao__isnull=True)

        if cliente := parametros.get("cliente"):
            queryset = queryset.filter(empresa__cliente_id=cliente)

        # `ultimo_heartbeat` nulo primeiro: totem que nunca deu sinal é
        # instalação que não terminou, o caso mais urgente da lista.
        return queryset.order_by("ultimo_heartbeat", "identificador")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        limite = timezone.now() - timezone.timedelta(
            minutes=Totem.MINUTOS_PARA_OFFLINE
        )
        base = Totem.objects.all()
        contexto.update({
            "titulo": "Parque de totens",
            "menu_ativo": "totens",
            "total": base.count(),
            "qtd_online": base.filter(ativo=True, ultimo_heartbeat__gte=limite).count(),
            "qtd_offline": base.filter(ativo=True)
            .filter(Q(ultimo_heartbeat__lt=limite) | Q(ultimo_heartbeat__isnull=True))
            .count(),
            "qtd_comodato": base.filter(
                em_comodato=True, data_devolucao__isnull=True
            ).count(),
            "busca": self.request.GET.get("busca", ""),
            "situacao": self.request.GET.get("situacao", ""),
        })
        return contexto


class TotemCreateView(MasterRequiredMixin, SucessoMensagemMixin, CreateView):
    model = Totem
    form_class = TotemForm
    template_name = "master/totens/editar.html"
    mensagem_sucesso = "Totem cadastrado. Abra a ficha para pegar a URL do quiosque."
    extra_context = {"titulo": "Novo totem", "menu_ativo": "totens"}

    def get_success_url(self):
        return reverse("master:totem_detalhe", args=[self.object.pk])

    def form_valid(self, form):
        resposta = super().form_valid(form)
        _log(
            self.request,
            LogAcessoMaster.Acao.TOTEM_CADASTRADO,
            cliente=self.object.empresa.cliente,
            detalhes=(
                f"{self.object.identificador} → {self.object.empresa.razao_social}"
            ),
        )
        return resposta


class TotemUpdateView(MasterRequiredMixin, SucessoMensagemMixin, UpdateView):
    model = Totem
    form_class = TotemForm
    template_name = "master/totens/editar.html"
    mensagem_sucesso = "Totem atualizado."
    extra_context = {"titulo": "Editar totem", "menu_ativo": "totens"}

    def get_success_url(self):
        return reverse("master:totem_detalhe", args=[self.object.pk])


@master_required
def totem_detalhe(request, pk):
    """
    Ficha do equipamento.

    Mostra a URL do quiosque **em texto completo, com o token**: é ela
    que o técnico digita no tablet durante a instalação. Não faz sentido
    mascarar aqui — quem tem acesso ao painel Master já pode regenerar o
    token de qualquer forma.
    """
    totem = get_object_or_404(
        Totem.objects.select_related("empresa", "empresa__cliente", "grupo"), pk=pk
    )

    eventos = (
        EventoTotem.objects.filter(totem=totem)
        .order_by("-created_at")[:50]
    )

    from apps.ponto.models import RegistroPonto

    hoje = timezone.localdate()
    registros_hoje = RegistroPonto.objects.filter(
        totem=totem, data_hora__date=hoje
    ).count()

    base_url = request.build_absolute_uri("/").rstrip("/")

    return render(
        request,
        "master/totens/detalhe.html",
        {
            "titulo": totem.apelido or totem.identificador,
            "menu_ativo": "totens",
            "totem": totem,
            "eventos": eventos,
            "registros_hoje": registros_hoje,
            "url_kiosk_absoluta": f"{base_url}{totem.url_kiosk}",
            "empresas_atendidas": totem.empresas_atendidas(),
        },
    )


@master_required
def totem_comodato(request, pk):
    """Registro do contrato de comodato — instalação, contrato e devolução."""
    totem = get_object_or_404(
        Totem.objects.select_related("empresa", "empresa__cliente"), pk=pk
    )
    form = ComodatoForm(
        request.POST or None, request.FILES or None, instance=totem
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        _log(
            request,
            LogAcessoMaster.Acao.TOTEM_COMODATO,
            cliente=totem.empresa.cliente,
            detalhes=(
                f"{totem.identificador}: comodato "
                f"{'ativo' if totem.em_comodato else 'desmarcado'}, "
                f"instalação {totem.data_instalacao or '—'}"
            ),
        )
        messages.success(request, "Dados do comodato atualizados.")
        return redirect("master:totem_detalhe", pk=totem.pk)

    return render(
        request,
        "master/totens/comodato.html",
        {
            "titulo": f"Comodato — {totem.identificador}",
            "menu_ativo": "totens",
            "totem": totem,
            "form": form,
        },
    )


@master_required
@require_POST
def totem_regenerar_token(request, pk):
    """
    Emite um novo token e invalida o anterior.

    Usado quando o tablet é perdido ou roubado: a URL antiga para de
    funcionar no mesmo instante. O totem precisa ser reconfigurado com a
    URL nova, e é por isso que a ação exige confirmação na tela.
    """
    totem = get_object_or_404(Totem.objects.select_related("empresa__cliente"), pk=pk)
    totem.regenerar_token()

    EventoTotem.objects.create(
        totem=totem,
        tipo=EventoTotem.Tipo.CONFIGURACAO,
        detalhes="Token de acesso regenerado pelo Master.",
    )
    _log(
        request,
        LogAcessoMaster.Acao.API_KEY_GERADA,
        cliente=totem.empresa.cliente,
        detalhes=f"Token do totem {totem.identificador} regenerado.",
    )
    messages.warning(
        request,
        "Token regenerado. A URL anterior parou de funcionar — reconfigure o tablet.",
    )
    return redirect("master:totem_detalhe", pk=totem.pk)


@master_required
@require_POST
def totem_devolver(request, pk):
    """
    Encerra o comodato: marca a devolução e desativa o equipamento.

    **Não apaga nada.** Os registros de ponto feitos naquele totem
    continuam apontando para ele — o AFD referencia o identificador do
    dispositivo, e apagar o totem deixaria as marcações órfãs num
    arquivo que precisa ser reproduzível anos depois.
    """
    totem = get_object_or_404(Totem.objects.select_related("empresa__cliente"), pk=pk)

    totem.data_devolucao = timezone.localdate()
    totem.ativo = False
    totem.save(update_fields=["data_devolucao", "ativo", "updated_at"])

    EventoTotem.objects.create(
        totem=totem,
        tipo=EventoTotem.Tipo.CONFIGURACAO,
        detalhes=f"Equipamento devolvido em {totem.data_devolucao:%d/%m/%Y}.",
    )
    _log(
        request,
        LogAcessoMaster.Acao.TOTEM_DEVOLVIDO,
        cliente=totem.empresa.cliente,
        detalhes=f"{totem.identificador} devolvido.",
    )
    messages.success(
        request,
        "Comodato encerrado. O histórico de marcações do equipamento foi preservado.",
    )
    return redirect("master:totem_lista")


# ══════════════════════════════════════════════════════════════
# Grupos de totens
# ══════════════════════════════════════════════════════════════
class GrupoTotemListView(MasterRequiredMixin, ListView):
    model = GrupoTotem
    template_name = "master/totens/grupos.html"
    context_object_name = "grupos"
    extra_context = {"titulo": "Grupos de totens", "menu_ativo": "totens"}

    def get_queryset(self):
        return (
            GrupoTotem.objects.select_related("cliente")
            .annotate(
                qtd_totens=Count("totens", filter=Q(totens__ativo=True), distinct=True),
                qtd_empresas=Count("empresas", distinct=True),
            )
            .order_by("cliente__razao_social", "nome")
        )


class GrupoTotemCreateView(MasterRequiredMixin, SucessoMensagemMixin, CreateView):
    model = GrupoTotem
    form_class = GrupoTotemForm
    template_name = "master/totens/grupo_editar.html"
    success_url = reverse_lazy("master:grupo_totem_lista")
    mensagem_sucesso = "Grupo criado."
    extra_context = {"titulo": "Novo grupo de totens", "menu_ativo": "totens"}


class GrupoTotemUpdateView(MasterRequiredMixin, SucessoMensagemMixin, UpdateView):
    model = GrupoTotem
    form_class = GrupoTotemForm
    template_name = "master/totens/grupo_editar.html"
    success_url = reverse_lazy("master:grupo_totem_lista")
    mensagem_sucesso = "Grupo atualizado."
    extra_context = {"titulo": "Editar grupo", "menu_ativo": "totens"}
