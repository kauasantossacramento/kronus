"""
Kronus — atestados, justificativas, afastamentos e fechamento mensal.

    /rh/atestados/          lista, upload e aprovação (Seção 8.6)
    /rh/justificativas/     lista, criação e aprovação
    /rh/afastamentos/       férias, licenças, INSS
    /rh/fechamento/         apuração e fechamento do período (Seção 8.5)

**Aprovar não é só mudar um status.** Um atestado aprovado abona os dias
que cobre; uma justificativa aprovada abona o dia. Por isso toda decisão
dispara o recálculo do banco de horas do período afetado — senão o
espelho de ponto e o AEJ ficariam contando falta em dia já abonado.
"""
import calendar
import logging
from datetime import date

from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.constants import StatusAprovacao
from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.ponto.models import BancoHoras, FechamentoMensal
from apps.ponto.services import ConsolidacaoService
from apps.rh.forms_rh import (
    AfastamentoForm,
    AtestadoForm,
    AvaliacaoForm,
    JustificativaForm,
)
from apps.rh.models import Afastamento, Atestado, Colaborador, Justificativa
from apps.rh.views import BaseRHFormView, BaseRHView
from apps.core.utils import meses_do_ano, nome_do_mes

logger = logging.getLogger("kronus.rh")


def _reconsolidar(colaborador, inicio: date, fim: date):
    """
    Recalcula o período afetado por uma decisão.

    Limitado a hoje: consolidar o futuro criaria faltas em dias que
    ainda não aconteceram.
    """
    fim_real = min(fim, timezone.localdate())
    if inicio <= fim_real:
        ConsolidacaoService.consolidar_periodo(colaborador, inicio, fim_real)


# ══════════════════════════════════════════════════════════════
# Atestados
# ══════════════════════════════════════════════════════════════
class AtestadoListView(BaseRHView, ListView):
    model = Atestado
    template_name = "rh/atestados/lista.html"
    context_object_name = "atestados"
    paginate_by = 25
    menu_ativo = "atestados"
    extra_context = {"titulo": "Atestados"}

    def get_queryset(self):
        qs = super().get_queryset().select_related("colaborador", "aprovado_por")
        status = self.request.GET.get("status", "pendente")
        if status in dict(StatusAprovacao.choices):
            qs = qs.filter(status=status)
        colaborador = self.request.GET.get("colaborador")
        if colaborador:
            qs = qs.filter(colaborador_id=colaborador)
        return qs.order_by("-data_inicio")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        empresa = self.request.empresa_ativa
        contexto.update({
            "status_selecionado": self.request.GET.get("status", "pendente"),
            "status_opcoes": StatusAprovacao.choices,
            "colaboradores": Colaborador.objects.filter(empresa=empresa, ativo=True),
            "contagem": {
                item["status"]: item["total"]
                for item in Atestado.objects.filter(empresa=empresa)
                .values("status")
                .annotate(total=Count("pk"))
            },
        })
        return contexto


class AtestadoCreateView(BaseRHFormView, CreateView):
    model = Atestado
    form_class = AtestadoForm
    template_name = "rh/atestados/form.html"
    success_url = reverse_lazy("rh:atestado_lista")
    mensagem_sucesso = "Atestado registrado. Aguardando aprovação."
    menu_ativo = "atestados"
    extra_context = {"titulo": "Novo atestado"}

    def get_queryset(self):
        return Atestado.objects.all()

    def form_valid(self, form):
        form.instance.enviado_por = self.request.user
        return super().form_valid(form)


@rh_required
@empresa_ativa_required
def avaliar_atestado(request, pk):
    """
    Aprova ou rejeita um atestado.

    A aprovação **abona os dias cobertos**: o recálculo transforma as
    faltas do período em dias de atestado, e isso se propaga ao espelho
    de ponto e ao AEJ.
    """
    atestado = get_object_or_404(
        Atestado.objects.select_related("colaborador"),
        pk=pk,
        empresa=request.empresa_ativa,
    )
    form = AvaliacaoForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        parecer = form.cleaned_data["parecer"]

        if form.cleaned_data["decisao"] == "aprovar":
            atestado.aprovar(request.user)
            acao = "aprovado"
        else:
            atestado.rejeitar(request.user, parecer)
            acao = "rejeitado"

        # Aprovar ou rejeitar muda a apuração dos dias cobertos.
        _reconsolidar(atestado.colaborador, atestado.data_inicio, atestado.data_fim)

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.ALTERACAO,
            descricao=(
                f"Atestado {acao} — {atestado.colaborador.nome_exibicao} "
                f"({atestado.data_inicio:%d/%m/%Y} a {atestado.data_fim:%d/%m/%Y})"
            ),
            objeto=atestado,
        )
        messages.success(
            request,
            f"Atestado {acao}. {atestado.dias} dia(s) reprocessado(s) no banco de horas.",
        )
        return redirect("rh:atestado_lista")

    return render(
        request,
        "rh/atestados/avaliar.html",
        {
            "titulo": "Avaliar atestado",
            "menu_ativo": "atestados",
            "atestado": atestado,
            "form": form,
            "dias_afetados": _dias_do_periodo(
                atestado.colaborador, atestado.data_inicio, atestado.data_fim
            ),
        },
    )


def _dias_do_periodo(colaborador, inicio, fim):
    """Como o período está apurado hoje — mostrado antes da decisão."""
    return BancoHoras.objects.filter(
        colaborador=colaborador, data__gte=inicio, data__lte=fim
    ).order_by("data")


# ══════════════════════════════════════════════════════════════
# Justificativas
# ══════════════════════════════════════════════════════════════
class JustificativaListView(BaseRHView, ListView):
    model = Justificativa
    template_name = "rh/justificativas/lista.html"
    context_object_name = "justificativas"
    paginate_by = 25
    menu_ativo = "justificativas"
    extra_context = {"titulo": "Justificativas"}

    def get_queryset(self):
        qs = super().get_queryset().select_related("colaborador", "aprovada_por")
        status = self.request.GET.get("status", "pendente")
        if status in dict(StatusAprovacao.choices):
            qs = qs.filter(status=status)
        return qs.order_by("-data")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        empresa = self.request.empresa_ativa
        contexto.update({
            "status_selecionado": self.request.GET.get("status", "pendente"),
            "status_opcoes": StatusAprovacao.choices,
            "contagem": {
                item["status"]: item["total"]
                for item in Justificativa.objects.filter(empresa=empresa)
                .values("status")
                .annotate(total=Count("pk"))
            },
        })
        return contexto


class JustificativaCreateView(BaseRHFormView, CreateView):
    model = Justificativa
    form_class = JustificativaForm
    template_name = "rh/justificativas/form.html"
    success_url = reverse_lazy("rh:justificativa_lista")
    mensagem_sucesso = "Justificativa registrada."
    menu_ativo = "justificativas"
    extra_context = {"titulo": "Nova justificativa"}

    def get_queryset(self):
        return Justificativa.objects.all()

    def form_valid(self, form):
        form.instance.solicitada_por = self.request.user
        resposta = super().form_valid(form)

        # Quem concede folga compensatoria precisa ver a conta. O debito
        # so acontece na aprovacao, mas dizer aqui evita a descoberta
        # tardia de que o saldo nao cobria o dia.
        aviso = form.aviso_de_saldo()
        if aviso:
            messages.info(self.request, _texto_do_saldo(aviso))
        return resposta


def _texto_do_saldo(aviso) -> str:
    """Frase unica sobre o efeito da folga no banco."""
    if not aviso.get("minutos"):
        return (
            "Neste dia a escala não prevê jornada, então a folga não "
            "debita nada do banco de horas."
        )

    def hm(minutos):
        sinal = "-" if minutos < 0 else ""
        minutos = abs(int(minutos))
        return f"{sinal}{minutos // 60}h{minutos % 60:02d}"

    frase = (
        f"Ao aprovar, {hm(aviso['minutos'])} serão descontadas do banco "
        f"de horas ({hm(aviso['saldo_antes'])} → "
        f"{hm(aviso['saldo_depois'])})."
    )
    if aviso["saldo_depois"] < 0:
        frase += " O saldo ficará negativo."
    return frase


@rh_required
@empresa_ativa_required
def avaliar_justificativa(request, pk):
    """Aprova ou rejeita; a aprovação abona o dia, se marcada para isso."""
    justificativa = get_object_or_404(
        Justificativa.objects.select_related("colaborador"),
        pk=pk,
        empresa=request.empresa_ativa,
    )
    form = AvaliacaoForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        parecer = form.cleaned_data["parecer"]

        if form.cleaned_data["decisao"] == "aprovar":
            justificativa.aprovar(request.user, parecer)
            acao = "aprovada"
        else:
            justificativa.rejeitar(request.user, parecer)
            acao = "rejeitada"

        _reconsolidar(justificativa.colaborador, justificativa.data, justificativa.data)

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.ALTERACAO,
            descricao=(
                f"Justificativa {acao} — {justificativa.colaborador.nome_exibicao} "
                f"({justificativa.data:%d/%m/%Y})"
            ),
            objeto=justificativa,
        )
        messages.success(request, f"Justificativa {acao}.")
        return redirect("rh:justificativa_lista")

    return render(
        request,
        "rh/justificativas/avaliar.html",
        {
            "titulo": "Avaliar justificativa",
            "menu_ativo": "justificativas",
            "justificativa": justificativa,
            "form": form,
            "dia": BancoHoras.objects.filter(
                colaborador=justificativa.colaborador, data=justificativa.data
            ).first(),
        },
    )


# ══════════════════════════════════════════════════════════════
# Afastamentos
# ══════════════════════════════════════════════════════════════
class AfastamentoListView(BaseRHView, ListView):
    model = Afastamento
    template_name = "rh/afastamentos/lista.html"
    context_object_name = "afastamentos"
    paginate_by = 25
    menu_ativo = "afastamentos"
    extra_context = {"titulo": "Afastamentos"}

    def get_queryset(self):
        return super().get_queryset().select_related("colaborador").order_by("-data_inicio")


class AfastamentoCreateView(BaseRHFormView, CreateView):
    model = Afastamento
    form_class = AfastamentoForm
    template_name = "rh/afastamentos/form.html"
    success_url = reverse_lazy("rh:afastamento_lista")
    mensagem_sucesso = "Afastamento registrado."
    menu_ativo = "afastamentos"
    extra_context = {"titulo": "Novo afastamento"}

    def get_queryset(self):
        return Afastamento.objects.all()

    def form_valid(self, form):
        resposta = super().form_valid(form)
        _reconsolidar(self.object.colaborador, self.object.data_inicio, self.object.data_fim)
        return resposta


class AfastamentoUpdateView(BaseRHFormView, UpdateView):
    model = Afastamento
    form_class = AfastamentoForm
    template_name = "rh/afastamentos/form.html"
    success_url = reverse_lazy("rh:afastamento_lista")
    mensagem_sucesso = "Afastamento atualizado."
    menu_ativo = "afastamentos"
    extra_context = {"titulo": "Editar afastamento"}

    def form_valid(self, form):
        resposta = super().form_valid(form)
        _reconsolidar(self.object.colaborador, self.object.data_inicio, self.object.data_fim)
        return resposta


# ══════════════════════════════════════════════════════════════
# Fechamento mensal
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def fechamento(request):
    """
    Apuração e fechamento do período (Seção 8.5).

    Fechar congela os dias: `BancoHoras.fechado` passa a bloquear o
    recálculo automático. Sem isso, uma marcação lançada depois mudaria
    silenciosamente um mês já pago.
    """
    empresa = request.empresa_ativa
    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get("ano", hoje.year))
        mes = int(request.GET.get("mes", hoje.month))
        date(ano, mes, 1)
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month

    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])

    colaboradores = (
        Colaborador.objects.filter(empresa=empresa, ativo=True)
        .select_related("departamento")
        .order_by("nome_completo")
    )

    fechamentos = {
        f.colaborador_id: f
        for f in FechamentoMensal.objects.filter(
            empresa=empresa, ano=ano, mes=mes
        ).select_related("colaborador")
    }

    linhas = []
    for colaborador in colaboradores:
        resumo = ConsolidacaoService.resumo_periodo(colaborador, inicio, fim)
        registro = fechamentos.get(colaborador.pk)
        linhas.append({
            "colaborador": colaborador,
            "resumo": resumo,
            "fechamento": registro,
            "fechado": bool(registro and registro.fechado),
            "assinado": bool(registro and registro.assinado),
            "pendencias": resumo["dias_incompletos"],
        })

    return render(
        request,
        "rh/fechamento/painel.html",
        {
            "titulo": "Fechamento mensal",
            "menu_ativo": "fechamento",
            "ano": ano,
            "mes": mes,
            "nome_mes": nome_do_mes(mes),
            "inicio": inicio,
            "fim": fim,
            "linhas": linhas,
            "meses": meses_do_ano(),
            "anos": range(hoje.year - 3, hoje.year + 1),
            "total_fechados": sum(1 for l in linhas if l["fechado"]),
            "total_pendencias": sum(l["pendencias"] for l in linhas),
            "periodo_futuro": inicio > hoje,
        },
    )


@rh_required
@empresa_ativa_required
def fechar_periodo(request, ano, mes, colaborador_id=None):
    """
    Fecha o período de um colaborador ou de todos.

    Recusa fechar quando há jornada em aberto: fechar com marcação
    faltando congelaria um erro conhecido.
    """
    if request.method != "POST":
        return redirect("rh:fechamento")

    empresa = request.empresa_ativa
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    forcar = request.POST.get("forcar") == "1"

    alvos = Colaborador.objects.filter(empresa=empresa, ativo=True)
    if colaborador_id:
        alvos = alvos.filter(pk=colaborador_id)

    fechados, bloqueados = 0, []

    for colaborador in alvos:
        resumo = ConsolidacaoService.resumo_periodo(colaborador, inicio, fim)

        if resumo["dias_incompletos"] and not forcar:
            bloqueados.append(
                f"{colaborador.nome_exibicao} ({resumo['dias_incompletos']} dia(s) em aberto)"
            )
            continue

        registro, _ = FechamentoMensal.objects.update_or_create(
            colaborador=colaborador,
            ano=ano,
            mes=mes,
            defaults={
                "empresa": empresa,
                "data_inicio": inicio,
                "data_fim": fim,
                "minutos_trabalhados": resumo["minutos_trabalhados"],
                "minutos_esperados": resumo["minutos_esperados"],
                "minutos_extras": resumo["minutos_extras"],
                "minutos_noturnos": resumo["minutos_noturnos"],
                "minutos_atraso": resumo["minutos_atraso"],
                "saldo_periodo": resumo["saldo_periodo"],
                "saldo_anterior": resumo["saldo_anterior"],
                "saldo_final": resumo["saldo_final"],
                "dias_falta": resumo["dias_falta"],
                "dias_atestado": resumo["dias_atestado"],
                "fechado": True,
                "fechado_em": timezone.now(),
                "fechado_por": request.user,
            },
        )

        # Congela os dias — a partir daqui o recálculo automático os ignora.
        BancoHoras.objects.filter(
            colaborador=colaborador, data__gte=inicio, data__lte=fim
        ).update(fechado=True)

        _gravar_hash_do_espelho(registro)
        fechados += 1

    if fechados:
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.CONFIG,
            descricao=f"Fechamento {mes:02d}/{ano} — {fechados} colaborador(es)",
            empresa=empresa,
        )
        messages.success(request, f"{fechados} colaborador(es) com período fechado.")

    if bloqueados:
        messages.warning(
            request,
            "Não fechados por jornada em aberto: " + "; ".join(bloqueados[:5])
            + ("…" if len(bloqueados) > 5 else "")
            + ". Corrija as marcações ou use 'forçar fechamento'.",
        )

    return redirect(f"{reverse('rh:fechamento')}?ano={ano}&mes={mes}")


def _gravar_hash_do_espelho(fechamento):
    """
    Calcula e grava o hash de integridade do espelho.

    Feito no fechamento — não na emissão do PDF — para que o código de
    verificação seja o mesmo em toda reimpressão do documento.
    """
    from apps.relatorios.generators import EspelhoPontoGenerator

    try:
        gerador = EspelhoPontoGenerator(
            fechamento.colaborador, fechamento.ano, fechamento.mes
        )
        contexto = gerador.contexto()
        fechamento.hash_documento = contexto["hash_documento"]
        fechamento.save(update_fields=["hash_documento", "updated_at"])
    except Exception:
        logger.exception("Falha ao calcular o hash do espelho %s", fechamento.pk)


@rh_required
@empresa_ativa_required
def reabrir_periodo(request, ano, mes, colaborador_id):
    """
    Reabre um período fechado.

    Um espelho **assinado** não reabre (regra 4 da Seção 14): o
    colaborador atestou aquele conteúdo, e alterá-lo depois destruiria
    o valor probatório da assinatura.
    """
    if request.method != "POST":
        return redirect("rh:fechamento")

    registro = get_object_or_404(
        FechamentoMensal,
        colaborador_id=colaborador_id,
        ano=ano,
        mes=mes,
        empresa=request.empresa_ativa,
    )

    if registro.assinado:
        messages.error(
            request,
            "Este espelho já foi assinado pelo colaborador e não pode ser reaberto "
            "(regra 4 da Seção 14 do plano).",
        )
        return redirect(f"{reverse('rh:fechamento')}?ano={ano}&mes={mes}")

    motivo = (request.POST.get("motivo") or "").strip()
    if len(motivo) < 10:
        messages.error(request, "Informe o motivo da reabertura (mínimo 10 caracteres).")
        return redirect(f"{reverse('rh:fechamento')}?ano={ano}&mes={mes}")

    BancoHoras.objects.filter(
        colaborador_id=colaborador_id,
        data__gte=registro.data_inicio,
        data__lte=registro.data_fim,
    ).update(fechado=False)

    registro.fechado = False
    registro.save(update_fields=["fechado", "updated_at"])

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=(
            f"Período {mes:02d}/{ano} reaberto — "
            f"{registro.colaborador.nome_exibicao}: {motivo[:120]}"
        ),
        objeto=registro,
    )
    messages.warning(request, "Período reaberto. Os dias voltam a ser recalculados.")
    return redirect(f"{reverse('rh:fechamento')}?ano={ano}&mes={mes}")
