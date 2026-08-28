"""
Kronus — módulo de ponto dentro do painel RH (Fase 2).

    /rh/registros/          marcações da empresa, com filtros
    /rh/registros/<pk>/ajustar/   ajuste manual (regra 1 da Seção 14)
    /rh/banco-horas/        painel de saldos com cores por faixa
    /rh/espelhos/           espelho de ponto por colaborador e mês
    /rh/escalas/            CRUD de escalas + vínculo em massa
"""
import calendar
from datetime import date

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.constants import StatusDia
from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.ponto.forms import AjustePontoForm, EscalaTrabalhoForm, VinculoEscalaForm
from apps.ponto.models import BancoHoras, EscalaTrabalho, RegistroPonto
from apps.ponto.services import AjustePontoService, ConsolidacaoService
from apps.rh.models import Colaborador
from apps.rh.views import BaseRHFormView, BaseRHView


def _periodo_do_request(request):
    """Lê `inicio`/`fim` da querystring, com o mês corrente como padrão."""
    hoje = timezone.localdate()
    primeiro = hoje.replace(day=1)
    try:
        inicio = date.fromisoformat(request.GET.get("inicio") or primeiro.isoformat())
        fim = date.fromisoformat(request.GET.get("fim") or hoje.isoformat())
    except ValueError:
        inicio, fim = primeiro, hoje
    if fim < inicio:
        inicio, fim = fim, inicio
    return inicio, fim


# ══════════════════════════════════════════════════════════════
# Registros de ponto
# ══════════════════════════════════════════════════════════════
class RegistroPontoListView(BaseRHView, ListView):
    model = RegistroPonto
    template_name = "rh/pontos/registros.html"
    context_object_name = "registros"
    paginate_by = 50
    menu_ativo = "registros"
    extra_context = {"titulo": "Registros de ponto"}

    def get_queryset(self):
        inicio, fim = _periodo_do_request(self.request)
        qs = (
            super()
            .get_queryset()
            .select_related("colaborador", "totem")
            .filter(data_hora__date__gte=inicio, data_hora__date__lte=fim)
            .order_by("-data_hora")
        )
        colaborador = self.request.GET.get("colaborador")
        if colaborador:
            qs = qs.filter(colaborador_id=colaborador)
        metodo = self.request.GET.get("metodo")
        if metodo:
            qs = qs.filter(metodo=metodo)
        if self.request.GET.get("apenas_alertas") == "1":
            qs = qs.filter(Q(fora_area=True) | Q(suspeita_fraude=True) | Q(cancelado=True))
        return qs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        inicio, fim = _periodo_do_request(self.request)
        contexto.update(
            {
                "inicio": inicio,
                "fim": fim,
                "colaboradores": Colaborador.objects.filter(
                    empresa=self.request.empresa_ativa
                ).order_by("nome_completo"),
                "colaborador_selecionado": self.request.GET.get("colaborador", ""),
                "metodo_selecionado": self.request.GET.get("metodo", ""),
                "metodos": RegistroPonto._meta.get_field("metodo").choices,
            }
        )
        return contexto


@rh_required
@empresa_ativa_required
def ajustar_registro(request, pk=None):
    """
    Ajuste manual de marcação.

    Um registro de ponto nunca é editado: o ajuste inclui uma marcação
    nova, cancela a existente, ou faz as duas coisas — sempre com
    justificativa e trilha de auditoria (regra 1 da Seção 14).
    """
    registro = None
    colaborador = None

    if pk is not None:
        registro = get_object_or_404(
            RegistroPonto.objects.select_related("colaborador"),
            pk=pk,
            empresa=request.empresa_ativa,
        )
        colaborador = registro.colaborador
    else:
        colaborador_id = request.GET.get("colaborador") or request.POST.get("colaborador")
        if colaborador_id:
            colaborador = get_object_or_404(
                Colaborador, pk=colaborador_id, empresa=request.empresa_ativa
            )

    form = AjustePontoForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        if colaborador is None:
            messages.error(request, "Selecione o colaborador do ajuste.")
            return redirect("rh:registro_lista")

        acao = form.cleaned_data["acao"]
        justificativa = form.cleaned_data["justificativa"]

        try:
            if acao == "inclusao":
                AjustePontoService.incluir(
                    colaborador=colaborador,
                    data_hora=form.cleaned_data["data_hora"],
                    tipo=form.cleaned_data["tipo"],
                    justificativa=justificativa,
                    executado_por=request.user,
                    request=request,
                )
                mensagem = "Marcação incluída."
            elif acao == "cancelamento":
                if registro is None:
                    messages.error(request, "Selecione a marcação a cancelar.")
                    return redirect("rh:registro_lista")
                AjustePontoService.cancelar(
                    registro=registro,
                    justificativa=justificativa,
                    executado_por=request.user,
                    request=request,
                )
                mensagem = "Marcação cancelada."
            else:
                if registro is None:
                    messages.error(request, "Selecione a marcação a substituir.")
                    return redirect("rh:registro_lista")
                AjustePontoService.substituir(
                    registro=registro,
                    data_hora=form.cleaned_data["data_hora"],
                    tipo=form.cleaned_data["tipo"],
                    justificativa=justificativa,
                    executado_por=request.user,
                    request=request,
                )
                mensagem = "Marcação substituída."
        except Exception as erro:  # regra de negócio violada
            messages.error(request, str(erro))
            return redirect("rh:registro_lista")

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.AJUSTE_PONTO,
            descricao=f"{mensagem} — {colaborador.nome_exibicao}: {justificativa[:120]}",
            objeto=colaborador,
        )
        messages.success(request, mensagem)
        return redirect("rh:registro_lista")

    return render(
        request,
        "rh/pontos/ajuste.html",
        {
            "titulo": "Ajuste de ponto",
            "menu_ativo": "registros",
            "form": form,
            "registro": registro,
            "colaborador": colaborador,
            "colaboradores": Colaborador.objects.filter(
                empresa=request.empresa_ativa, ativo=True
            ).order_by("nome_completo"),
        },
    )


# ══════════════════════════════════════════════════════════════
# Banco de horas
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def banco_horas(request):
    """
    Painel de banco de horas (Seção 8.4).

    Mostra o saldo corrente de cada colaborador, colorido por faixa:
    verde acima de zero, amarelo entre -2h e 0, vermelho abaixo disso.
    """
    empresa = request.empresa_ativa
    inicio, fim = _periodo_do_request(request)

    colaboradores = (
        Colaborador.objects.filter(empresa=empresa, ativo=True)
        .select_related("departamento", "escala")
        .order_by("nome_completo")
    )

    departamento = request.GET.get("departamento")
    if departamento:
        colaboradores = colaboradores.filter(departamento_id=departamento)

    linhas = []
    for colaborador in colaboradores:
        agregado = BancoHoras.objects.filter(
            colaborador=colaborador, data__gte=inicio, data__lte=fim
        ).aggregate(
            trabalhado=Sum("minutos_trabalhados"),
            esperado=Sum("minutos_esperados"),
            extras=Sum("minutos_extras"),
            noturnas=Sum("minutos_noturnos"),
            atraso=Sum("minutos_atraso"),
            saldo=Sum("saldo_dia"),
            faltas=Count("pk", filter=Q(status=StatusDia.FALTA)),
            incompletos=Count("pk", filter=Q(status=StatusDia.INCOMPLETO)),
        )
        ultimo = (
            BancoHoras.objects.filter(colaborador=colaborador, data__lte=fim)
            .order_by("-data")
            .values_list("saldo_acumulado", flat=True)
            .first()
            or 0
        )
        linhas.append(
            {
                "colaborador": colaborador,
                "trabalhado": agregado["trabalhado"] or 0,
                "esperado": agregado["esperado"] or 0,
                "extras": agregado["extras"] or 0,
                "noturnas": agregado["noturnas"] or 0,
                "atraso": agregado["atraso"] or 0,
                "saldo_periodo": agregado["saldo"] or 0,
                "saldo_acumulado": ultimo,
                "faltas": agregado["faltas"] or 0,
                "incompletos": agregado["incompletos"] or 0,
            }
        )

    ordem = request.GET.get("ordem")
    if ordem == "saldo":
        linhas.sort(key=lambda linha: linha["saldo_acumulado"])
    elif ordem == "-saldo":
        linhas.sort(key=lambda linha: linha["saldo_acumulado"], reverse=True)

    from apps.rh.models import Departamento

    return render(
        request,
        "rh/banco_horas/painel.html",
        {
            "titulo": "Banco de horas",
            "menu_ativo": "banco_horas",
            "inicio": inicio,
            "fim": fim,
            "linhas": linhas,
            "departamentos": Departamento.objects.filter(empresa=empresa, ativo=True),
            "total_devedores": sum(1 for linha in linhas if linha["saldo_acumulado"] < 0),
            "total_credores": sum(1 for linha in linhas if linha["saldo_acumulado"] > 0),
            "saldo_total": sum(linha["saldo_acumulado"] for linha in linhas),
        },
    )


@rh_required
@empresa_ativa_required
def recalcular_periodo(request, colaborador_id):
    """Reprocessa o banco de horas de um colaborador no período filtrado."""
    colaborador = get_object_or_404(
        Colaborador, pk=colaborador_id, empresa=request.empresa_ativa
    )
    if request.method == "POST":
        inicio, fim = _periodo_do_request(request)
        resultados = ConsolidacaoService.consolidar_periodo(colaborador, inicio, fim)
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.ALTERACAO,
            descricao=(
                f"Banco de horas recalculado de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} "
                f"para {colaborador.nome_exibicao}"
            ),
            objeto=colaborador,
        )
        messages.success(
            request, f"{len(resultados)} dia(s) recalculado(s) para {colaborador.nome_exibicao}."
        )
    destino = request.META.get("HTTP_REFERER") or reverse("rh:banco_horas")
    return redirect(destino)


# ══════════════════════════════════════════════════════════════
# Espelho de ponto
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def espelho_lista(request):
    """Seleção de colaborador e período para emitir o espelho."""
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

    resumos = []
    for colaborador in colaboradores:
        agregado = BancoHoras.objects.filter(
            colaborador=colaborador, data__gte=inicio, data__lte=fim
        ).aggregate(
            trabalhado=Sum("minutos_trabalhados"),
            esperado=Sum("minutos_esperados"),
            saldo=Sum("saldo_dia"),
            faltas=Count("pk", filter=Q(status=StatusDia.FALTA)),
            incompletos=Count("pk", filter=Q(status=StatusDia.INCOMPLETO)),
        )
        resumos.append(
            {
                "colaborador": colaborador,
                "trabalhado": agregado["trabalhado"] or 0,
                "esperado": agregado["esperado"] or 0,
                "saldo": agregado["saldo"] or 0,
                "faltas": agregado["faltas"] or 0,
                "incompletos": agregado["incompletos"] or 0,
            }
        )

    return render(
        request,
        "rh/pontos/espelho.html",
        {
            "titulo": "Espelho de ponto",
            "menu_ativo": "espelho",
            "ano": ano,
            "mes": mes,
            "nome_mes": calendar.month_name[mes],
            "resumos": resumos,
            "meses": [(i, calendar.month_name[i]) for i in range(1, 13)],
            "anos": range(hoje.year - 3, hoje.year + 1),
        },
    )


# ══════════════════════════════════════════════════════════════
# Escalas de trabalho
# ══════════════════════════════════════════════════════════════
class EscalaListView(BaseRHView, ListView):
    model = EscalaTrabalho
    template_name = "rh/escalas/lista.html"
    context_object_name = "escalas"
    paginate_by = 30
    menu_ativo = "escalas"
    extra_context = {"titulo": "Escalas de trabalho"}

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(qtd=Count("colaboradores", filter=Q(colaboradores__ativo=True)))
            .order_by("nome")
        )


class EscalaCreateView(BaseRHFormView, CreateView):
    model = EscalaTrabalho
    form_class = EscalaTrabalhoForm
    template_name = "rh/escalas/form.html"
    success_url = reverse_lazy("rh:escala_lista")
    mensagem_sucesso = "Escala criada."
    menu_ativo = "escalas"
    extra_context = {"titulo": "Nova escala"}

    def get_queryset(self):
        return EscalaTrabalho.objects.all()


class EscalaUpdateView(BaseRHFormView, UpdateView):
    model = EscalaTrabalho
    form_class = EscalaTrabalhoForm
    template_name = "rh/escalas/form.html"
    success_url = reverse_lazy("rh:escala_lista")
    mensagem_sucesso = "Escala atualizada."
    menu_ativo = "escalas"
    extra_context = {"titulo": "Editar escala"}

    def form_valid(self, form):
        """
        Alterar a jornada muda o cálculo dos dias em aberto — o recálculo
        do mês corrente evita que o painel fique inconsistente.
        """
        resposta = super().form_valid(form)
        hoje = timezone.localdate()
        inicio = hoje.replace(day=1)
        for colaborador in self.object.colaboradores.filter(ativo=True):
            ConsolidacaoService.consolidar_periodo(colaborador, inicio, hoje)
        return resposta


@rh_required
@empresa_ativa_required
def vincular_escala(request, pk):
    """Vincula a escala a vários colaboradores de uma vez."""
    escala = get_object_or_404(EscalaTrabalho, pk=pk, empresa=request.empresa_ativa)
    form = VinculoEscalaForm(request.POST or None, empresa=request.empresa_ativa)

    if request.method == "POST" and form.is_valid():
        colaboradores = form.cleaned_data["colaboradores"]
        atualizados = colaboradores.update(escala=escala)
        hoje = timezone.localdate()
        for colaborador in colaboradores:
            ConsolidacaoService.consolidar_periodo(
                colaborador, hoje.replace(day=1), hoje
            )
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.ALTERACAO,
            descricao=f"Escala '{escala.nome}' vinculada a {atualizados} colaborador(es)",
            objeto=escala,
        )
        messages.success(
            request, f"Escala vinculada a {atualizados} colaborador(es)."
        )
        return redirect("rh:escala_lista")

    return render(
        request,
        "rh/escalas/vincular.html",
        {
            "titulo": f"Vincular — {escala.nome}",
            "menu_ativo": "escalas",
            "escala": escala,
            "form": form,
            "vinculados": escala.colaboradores.filter(ativo=True).order_by(
                "nome_completo"
            ),
        },
    )
