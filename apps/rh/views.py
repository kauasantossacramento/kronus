"""
Kronus — painel do Admin RH.

Fase 1 entrega o esqueleto do painel e o CRUD de estrutura:
colaboradores, departamentos e cargos, todos escopados pela empresa
ativa. Os modulos de ponto, banco de horas, atestados e relatorios
sao preenchidos nas Fases 2 e 4.
"""
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.mixins import RHRequiredMixin, SucessoMensagemMixin, TenantScopedMixin
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.rh.forms import CargoForm, ColaboradorForm, DepartamentoForm
from apps.rh.models import Cargo, Colaborador, Departamento


class BaseRHView(RHRequiredMixin, TenantScopedMixin):
    """Toda view do RH exige papel de RH e escopo de empresa."""

    def dispatch(self, request, *args, **kwargs):
        resposta = super().dispatch(request, *args, **kwargs)
        return resposta

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["menu_ativo"] = getattr(self, "menu_ativo", "")
        return contexto


class BaseRHFormView(BaseRHView, SucessoMensagemMixin):
    """Injeta a empresa ativa nos formularios escopados."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa_ativa
        return kwargs

    def form_valid(self, form):
        if self.request.empresa_ativa is None:
            raise PermissionDenied("Selecione uma empresa antes de continuar.")
        resposta = super().form_valid(form)
        registrar_log(
            request=self.request,
            acao=LogAcesso.Acao.CRIACAO
            if form.instance._state.adding
            else LogAcesso.Acao.ALTERACAO,
            descricao=f"{self.object._meta.verbose_name}: {self.object}",
            objeto=self.object,
        )
        return resposta


# ==============================================================
# Dashboard
# ==============================================================
@rh_required
@empresa_ativa_required
def dashboard(request):
    """
    Dashboard do RH (Secao 6.6 do plano).

    Cards de resumo do dia, ultimos registros e alertas operacionais.
    Os graficos historicos entram na Fase 4.
    """
    from apps.core.constants import StatusAprovacao, StatusDia
    from apps.ponto.models import BancoHoras, RegistroPonto
    from apps.rh.models import Atestado, Justificativa

    empresa = request.empresa_ativa
    hoje = timezone.localdate()
    colaboradores = Colaborador.objects.filter(empresa=empresa)
    ativos = colaboradores.filter(ativo=True)

    registros_hoje = RegistroPonto.objects.filter(
        empresa=empresa, cancelado=False, data_hora__date=hoje
    )
    banco_hoje = BancoHoras.objects.filter(empresa=empresa, data=hoje)

    # Quem ja bateu hoje versus quem tinha jornada prevista.
    com_registro_hoje = set(registros_hoje.values_list("colaborador_id", flat=True))
    esperados_hoje = banco_hoje.filter(minutos_esperados__gt=0)

    ausentes = [
        b.colaborador
        for b in esperados_hoje.select_related("colaborador")
        if b.colaborador_id not in com_registro_hoje
    ]

    inicio_mes = hoje.replace(day=1)
    saldos = (
        BancoHoras.objects.filter(empresa=empresa, data__lte=hoje)
        .order_by("colaborador_id", "-data")
        .distinct("colaborador_id")
        if connection.vendor == "postgresql"
        else None
    )

    # `distinct("campo")` so existe no PostgreSQL; em SQLite (bootstrap
    # local) calculamos o ultimo saldo por colaborador em Python.
    if saldos is None:
        ultimos = {}
        for registro in BancoHoras.objects.filter(
            empresa=empresa, data__lte=hoje
        ).order_by("colaborador_id", "data").only(
            "colaborador_id", "saldo_acumulado", "data"
        ):
            ultimos[registro.colaborador_id] = registro.saldo_acumulado
        devedores_ids = [pk for pk, saldo in ultimos.items() if saldo < -120]
    else:
        devedores_ids = [b.colaborador_id for b in saldos if b.saldo_acumulado < -120]

    devedores = (
        Colaborador.objects.filter(pk__in=devedores_ids, ativo=True)
        .select_related("departamento")
        .order_by("nome_completo")[:10]
    )

    # Os contadores do dia saem de **uma** agregacao condicional, nao de
    # um COUNT por card: cinco COUNTs varrem a mesma tabela cinco vezes,
    # e o dashboard e a primeira tela que o RH abre todo dia.
    quadro = ativos.aggregate(
        total=Count("pk"),
        com_face=Count("pk", filter=Q(face_registrada=True)),
        sem_face=Count("pk", filter=Q(face_registrada=False)),
        sem_escala=Count("pk", filter=Q(escala__isnull=True)),
    )
    dia = banco_hoje.aggregate(
        atrasos=Count("pk", filter=Q(minutos_atraso__gt=0)),
        faltas=Count("pk", filter=Q(status=StatusDia.FALTA)),
        incompletos=Count("pk", filter=Q(status=StatusDia.INCOMPLETO)),
    )
    marcacoes = registros_hoje.aggregate(
        total=Count("pk"),
        alertas=Count("pk", filter=Q(fora_area=True) | Q(suspeita_fraude=True)),
    )
    # Uma consulta so para os totens: o total e a lista de offline saem
    # do mesmo resultado, ja materializado.
    totens_ativos = list(empresa.totens.filter(ativo=True))

    contexto = {
        "titulo": "Dashboard",
        "menu_ativo": "dashboard",
        "hoje": hoje,
        # -- estrutura --
        "total_colaboradores": quadro["total"],
        "total_com_face": quadro["com_face"],
        "total_departamentos": Departamento.objects.filter(
            empresa=empresa, ativo=True
        ).count(),
        "total_totens": len(totens_ativos),
        "totens_offline": [t for t in totens_ativos if not t.online],
        # -- ponto do dia --
        "registros_hoje": marcacoes["total"],
        "presentes_hoje": len(com_registro_hoje),
        "atrasos_hoje": dia["atrasos"],
        "faltas_hoje": dia["faltas"],
        "incompletos_hoje": dia["incompletos"],
        "ausentes": ausentes[:10],
        "ultimos_registros": registros_hoje.select_related("colaborador").order_by(
            "-data_hora"
        )[:10],
        "devedores": devedores,
        # -- pendencias estruturais --
        "admissoes_recentes": ativos.select_related("departamento").order_by(
            "-data_admissao"
        )[:5],
        "sem_escala": quadro["sem_escala"],
        "sem_face": quadro["sem_face"],
        "alertas_registro": marcacoes["alertas"],
        "periodo_mes": (inicio_mes, hoje),
        # -- pendencias de aprovacao (Fase 4) --
        "atestados_pendentes": Atestado.objects.filter(
            empresa=empresa, status=StatusAprovacao.PENDENTE
        ).count(),
        "justificativas_pendentes": Justificativa.objects.filter(
            empresa=empresa, status=StatusAprovacao.PENDENTE
        ).count(),
        # -- graficos (Secao 6.6) --
        "grafico_registros": _serie_registros(empresa, hoje),
        "grafico_status": _distribuicao_status(empresa, hoje),
    }
    return render(request, "rh/dashboard.html", contexto)


def _serie_registros(empresa, hoje, dias=30):
    """
    Registros por dia nos ultimos 30 dias (grafico de barras).

    Uma consulta agregada com `TruncDate` — nao um laco de 30 queries,
    que e o que deixaria o dashboard lento numa empresa grande.
    """
    from datetime import timedelta

    from django.db.models.functions import TruncDate

    from apps.ponto.models import RegistroPonto

    inicio = hoje - timedelta(days=dias - 1)
    contagem = {
        item["dia"]: item["total"]
        for item in RegistroPonto.objects.filter(
            empresa=empresa, cancelado=False, data_hora__date__gte=inicio
        )
        .annotate(dia=TruncDate("data_hora"))
        .values("dia")
        .annotate(total=Count("pk"))
    }

    rotulos, valores = [], []
    for deslocamento in range(dias):
        dia = inicio + timedelta(days=deslocamento)
        rotulos.append(dia.strftime("%d/%m"))
        valores.append(contagem.get(dia, 0))
    return {"rotulos": rotulos, "valores": valores}


def _distribuicao_status(empresa, hoje):
    """Status dos dias de hoje (grafico de rosca)."""
    from apps.core.constants import StatusDia
    from apps.ponto.models import BancoHoras

    rotulos_por_status = dict(StatusDia.choices)
    dados = (
        BancoHoras.objects.filter(empresa=empresa, data=hoje)
        .values("status")
        .annotate(total=Count("pk"))
        .order_by("-total")
    )
    #: Cores alinhadas ao design system (Secao 3.2).
    cores = {
        StatusDia.COMPLETO: "#10B981",
        StatusDia.INCOMPLETO: "#F59E0B",
        StatusDia.FALTA: "#EF4444",
        StatusDia.JUSTIFICADO: "#3B82F6",
        StatusDia.ATESTADO: "#8B5CF6",
        StatusDia.FOLGA: "#94A3B8",
        StatusDia.COMPENSADO: "#0EA5E9",
        StatusDia.FERIADO: "#D4A017",
        StatusDia.FERIAS: "#06B6D4",
        StatusDia.AFASTAMENTO: "#64748B",
    }
    return {
        "rotulos": [rotulos_por_status.get(d["status"], d["status"]) for d in dados],
        "valores": [d["total"] for d in dados],
        "cores": [cores.get(d["status"], "#CBD5E1") for d in dados],
    }


# ==============================================================
# Colaboradores
# ==============================================================
class ColaboradorListView(BaseRHView, ListView):
    model = Colaborador
    template_name = "rh/colaboradores/lista.html"
    context_object_name = "colaboradores"
    paginate_by = 25
    menu_ativo = "colaboradores"

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("departamento", "escala", "cargo_ref")
            .order_by("nome_completo")
        )
        busca = self.request.GET.get("q", "").strip()
        if busca:
            qs = qs.filter(
                Q(nome_completo__icontains=busca)
                | Q(nome_social__icontains=busca)
                | Q(cpf__icontains=busca)
                | Q(matricula__icontains=busca)
                | Q(email__icontains=busca)
            )
        situacao = self.request.GET.get("situacao", "ativos")
        if situacao == "ativos":
            qs = qs.filter(ativo=True)
        elif situacao == "inativos":
            qs = qs.filter(ativo=False)
        departamento = self.request.GET.get("departamento")
        if departamento:
            qs = qs.filter(departamento_id=departamento)
        face = self.request.GET.get("face")
        if face == "sim":
            qs = qs.filter(face_registrada=True)
        elif face == "nao":
            qs = qs.filter(face_registrada=False)
        return qs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Colaboradores"
        contexto["departamentos"] = Departamento.objects.filter(
            empresa=self.request.empresa_ativa, ativo=True
        )
        contexto["busca"] = self.request.GET.get("q", "")
        contexto["situacao"] = self.request.GET.get("situacao", "ativos")
        return contexto


class ColaboradorDetailView(BaseRHView, DetailView):
    model = Colaborador
    template_name = "rh/colaboradores/detalhe.html"
    context_object_name = "colaborador"
    menu_ativo = "colaboradores"

    def get_context_data(self, **kwargs):
        # As outras empresas da mesma assinatura. Vazio quando o cliente
        # so tem uma — e ai a transferencia nem aparece, em vez de
        # oferecer um destino que nao existe.
        from apps.clientes.models import Empresa

        kwargs["empresas_do_cliente"] = Empresa.objects.filter(
            cliente=self.request.empresa_ativa.cliente
        ).exclude(pk=self.object.empresa_id)
        from apps.ponto.services import ConsolidacaoService

        contexto = super().get_context_data(**kwargs)
        hoje = timezone.localdate()
        inicio_mes = hoje.replace(day=1)

        contexto["titulo"] = self.object.nome_exibicao
        contexto["atestados"] = self.object.atestados.all()[:10]
        contexto["justificativas"] = self.object.justificativas.all()[:10]
        contexto["registros_faciais"] = self.object.registros_faciais.filter(ativo=True)
        contexto["resumo_mes"] = ConsolidacaoService.resumo_periodo(
            self.object, inicio_mes, hoje
        )
        contexto["ultimos_registros"] = self.object.registros.filter(
            cancelado=False
        ).order_by("-data_hora")[:8]
        contexto["mes_atual"] = hoje.month
        contexto["ano_atual"] = hoje.year
        return contexto


class ColaboradorCreateView(BaseRHFormView, CreateView):
    model = Colaborador
    form_class = ColaboradorForm
    template_name = "rh/colaboradores/criar.html"
    mensagem_sucesso = "Colaborador cadastrado."
    menu_ativo = "colaboradores"
    extra_context = {"titulo": "Novo colaborador"}

    def get_queryset(self):
        return Colaborador.objects.all()

    def form_valid(self, form):
        cliente = self.request.empresa_ativa.cliente
        if not cliente.pode_adicionar_colaborador():
            form.add_error(
                None,
                f"O plano {cliente.plano} permite no máximo "
                f"{cliente.plano.max_colaboradores} colaboradores ativos.",
            )
            return self.form_invalid(form)
        resposta = super().form_valid(form)
        if form.cleaned_data.get("criar_acesso"):
            self._criar_usuario(self.object)
        return resposta

    def _criar_usuario(self, colaborador):
        """
        Cria as credenciais do colaborador e as entrega.

        Delega a `garantir_usuario`, que **vincula a empresa** ao
        usuario. A versao anterior criava o login sem esse vinculo: a
        pessoa entrava e nao enxergava nada, porque todo o sistema e
        escopado por empresa. O sintoma relatado era "não consigo acessar
        como colaborador".

        A senha vai por e-mail **e** na tela. Só por e-mail deixaria quem
        cadastrou sem nada para entregar se o envio falhasse; só na tela
        obriga a copiar antes de recarregar a página — e a mensagem some
        na primeira navegação.
        """
        from apps.rh.credenciais import enviar_credenciais

        _, senha = colaborador.garantir_usuario()
        if not senha:
            messages.info(
                self.request,
                f"{colaborador.nome_exibicao} já tinha acesso; a empresa foi "
                "vinculada ao login existente.",
            )
            return

        enviado = enviar_credenciais(colaborador, senha)
        if enviado:
            messages.success(
                self.request,
                f"Acesso criado para {colaborador.nome_exibicao} e enviado "
                f"para {colaborador.email}. Senha provisória: {senha} "
                "(será trocada no primeiro login).",
            )
        else:
            # Sem e-mail, ou envio falhou: quem cadastrou precisa saber
            # que a entrega ficou com ele.
            messages.warning(
                self.request,
                f"Acesso criado para {colaborador.nome_exibicao}, mas o "
                f"e-mail não foi enviado. Senha provisória: {senha} — "
                "entregue você mesmo, ela não aparece de novo.",
            )

    def get_success_url(self):
        # Quem marcou "cadastrar o rosto agora" vai direto para a
        # captura: voltar para a ficha e pedir que a pessoa ache o botão
        # é onde o cadastro facial costuma ficar para depois — e "depois"
        # vira nunca.
        if self.request.POST.get("ir_para_biometria"):
            return reverse("facial:cadastro", args=[self.object.pk])
        return reverse("rh:colaborador_detalhe", args=[self.object.pk])


class ColaboradorUpdateView(BaseRHFormView, UpdateView):
    model = Colaborador
    form_class = ColaboradorForm
    template_name = "rh/colaboradores/editar.html"
    mensagem_sucesso = "Colaborador atualizado."
    menu_ativo = "colaboradores"
    extra_context = {"titulo": "Editar colaborador"}

    def get_success_url(self):
        # Quem marcou "cadastrar o rosto agora" vai direto para a
        # captura: voltar para a ficha e pedir que a pessoa ache o botão
        # é onde o cadastro facial costuma ficar para depois — e "depois"
        # vira nunca.
        if self.request.POST.get("ir_para_biometria"):
            return reverse("facial:cadastro", args=[self.object.pk])
        return reverse("rh:colaborador_detalhe", args=[self.object.pk])

    def form_valid(self, form):
        """
        Marcar "criar credenciais" na edicao passa a funcionar.

        A caixa vive no formulario, que e o mesmo das duas telas — mas o
        gatilho existia so na criacao. Quem editava um colaborador,
        marcava a caixa e salvava recebia a tela de sucesso e **nada
        acontecia**: sem erro, sem aviso, sem acesso criado.

        A caixa nao guarda estado por isso mesmo: ela e uma acao, nao um
        campo. Quem quer saber se a pessoa tem acesso olha o bloco
        "Credenciais de acesso" na ficha, que mostra o login de verdade.
        """
        resposta = super().form_valid(form)
        # `.get` porque o campo some do formulario quando a pessoa ja
        # tem acesso: ausente e o mesmo que nao marcado.
        if form.cleaned_data.get("criar_acesso"):
            ColaboradorCreateView._criar_usuario(self, self.object)
        return resposta



@rh_required
@empresa_ativa_required
def colaborador_desligar(request, pk):
    """Desliga (ou reativa) um colaborador — nunca exclui o historico."""
    colaborador = get_object_or_404(
        Colaborador, pk=pk, empresa=request.empresa_ativa
    )
    if request.method == "POST":
        if colaborador.ativo:
            colaborador.ativo = False
            colaborador.data_demissao = (
                request.POST.get("data_demissao") or timezone.localdate()
            )
            colaborador.save(update_fields=["ativo", "data_demissao", "updated_at"])
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.ALTERACAO,
                descricao=f"Colaborador desligado: {colaborador}",
                objeto=colaborador,
            )
            messages.warning(request, f"{colaborador.nome_exibicao} foi desligado(a).")
        else:
            colaborador.ativo = True
            colaborador.data_demissao = None
            colaborador.save(update_fields=["ativo", "data_demissao", "updated_at"])
            messages.success(request, f"{colaborador.nome_exibicao} foi reativado(a).")
    return redirect("rh:colaborador_detalhe", pk=pk)


# ==============================================================
# Departamentos
# ==============================================================
class DepartamentoListView(BaseRHView, ListView):
    model = Departamento
    template_name = "rh/departamentos/lista.html"
    context_object_name = "departamentos"
    paginate_by = 30
    menu_ativo = "departamentos"
    extra_context = {"titulo": "Departamentos"}

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(qtd=Count("colaboradores", filter=Q(colaboradores__ativo=True)))
            .order_by("nome")
        )


class DepartamentoCreateView(BaseRHFormView, CreateView):
    model = Departamento
    form_class = DepartamentoForm
    template_name = "rh/departamentos/form.html"
    success_url = reverse_lazy("rh:departamento_lista")
    mensagem_sucesso = "Departamento criado."
    menu_ativo = "departamentos"
    extra_context = {"titulo": "Novo departamento"}

    def get_queryset(self):
        return Departamento.objects.all()


class DepartamentoUpdateView(BaseRHFormView, UpdateView):
    model = Departamento
    form_class = DepartamentoForm
    template_name = "rh/departamentos/form.html"
    success_url = reverse_lazy("rh:departamento_lista")
    mensagem_sucesso = "Departamento atualizado."
    menu_ativo = "departamentos"
    extra_context = {"titulo": "Editar departamento"}


# ==============================================================
# Cargos
# ==============================================================
class CargoListView(BaseRHView, ListView):
    model = Cargo
    template_name = "rh/cargos/lista.html"
    context_object_name = "cargos"
    paginate_by = 30
    menu_ativo = "cargos"
    extra_context = {"titulo": "Cargos"}

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(qtd=Count("colaboradores", filter=Q(colaboradores__ativo=True)))
            .order_by("nome")
        )


class CargoCreateView(BaseRHFormView, CreateView):
    model = Cargo
    form_class = CargoForm
    template_name = "rh/cargos/form.html"
    success_url = reverse_lazy("rh:cargo_lista")
    mensagem_sucesso = "Cargo criado."
    menu_ativo = "cargos"
    extra_context = {"titulo": "Novo cargo"}

    def get_queryset(self):
        return Cargo.objects.all()


class CargoUpdateView(BaseRHFormView, UpdateView):
    model = Cargo
    form_class = CargoForm
    template_name = "rh/cargos/form.html"
    success_url = reverse_lazy("rh:cargo_lista")
    mensagem_sucesso = "Cargo atualizado."
    menu_ativo = "cargos"
    extra_context = {"titulo": "Editar cargo"}


@rh_required
@empresa_ativa_required
@require_POST
def colaborador_gerar_acesso(request, pk):
    """
    Cria (ou repara) o login do colaborador depois do cadastro.

    A caixa "criar acesso" fica no cadastro, e quem nao a marcou na hora
    ficava sem caminho: era refazer o colaborador. Pior — quem marcou
    antes da correcao do vinculo de empresa tem login que entra e nao
    mostra nada, e `garantir_usuario` conserta esse caso tambem.

    A senha aparece **uma vez**, aqui. Guardar para mostrar depois
    exigiria guardar em texto puro.
    """
    colaborador = get_object_or_404(
        Colaborador, pk=pk, empresa=request.empresa_ativa
    )
    usuario, senha = colaborador.garantir_usuario()

    if senha:
        from apps.rh.credenciais import enviar_credenciais

        if enviar_credenciais(colaborador, senha):
            messages.success(
                request,
                f"Acesso criado para {colaborador.nome_exibicao} e enviado "
                f"para {colaborador.email}. Senha provisória: {senha} — "
                "será trocada no primeiro login.",
            )
        else:
            # Sem e-mail no cadastro, ou envio falhou. Quem clicou
            # precisa saber que a entrega ficou com ele.
            messages.warning(
                request,
                f"Acesso criado para {colaborador.nome_exibicao}, mas o "
                f"e-mail não foi enviado. Senha provisória: {senha} — anote "
                "agora, ela não será exibida de novo.",
            )
    else:
        messages.info(
            request,
            f"{colaborador.nome_exibicao} já tinha acesso; o vínculo com "
            f"{request.empresa_ativa.nome_exibicao} foi conferido.",
        )

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=f"Acesso gerado para {colaborador.nome_exibicao}",
        objeto=colaborador,
        empresa=request.empresa_ativa,
    )
    return redirect("rh:colaborador_detalhe", pk=pk)


@rh_required
@empresa_ativa_required
@require_POST
def colaborador_reenviar_credenciais(request, pk):
    """
    Gera uma senha nova e reenvia — para quem já tem acesso.

    `colaborador_gerar_acesso` não serve aqui: ele só cria senha para
    quem ainda não tem uma utilizável, e "já tinha acesso" era o fim de
    linha para quem clicava de novo depois que o primeiro e-mail não
    chegou. Não havia caminho nenhum de volta a não ser recadastrar a
    pessoa.

    A senha anterior para de funcionar no mesmo instante — quem clica
    aqui está confirmando que a antiga não chegou ou se perdeu.
    """
    colaborador = get_object_or_404(
        Colaborador, pk=pk, empresa=request.empresa_ativa
    )
    enviado, senha = colaborador.reenviar_credenciais()

    if enviado:
        messages.success(
            request,
            f"Nova senha gerada para {colaborador.nome_exibicao} e enviada "
            f"para {colaborador.email}. A senha anterior parou de funcionar.",
        )
    else:
        messages.warning(
            request,
            f"Nova senha gerada para {colaborador.nome_exibicao}, mas o "
            f"e-mail não foi enviado. Senha provisória: {senha} — anote "
            "agora, ela não será exibida de novo. A senha anterior parou "
            "de funcionar.",
        )

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.SEGURANCA,
        descricao=(
            f"Credenciais reenviadas para {colaborador.nome_exibicao} "
            f"({'e-mail enviado' if enviado else 'e-mail não enviado'})"
        ),
        objeto=colaborador,
        empresa=request.empresa_ativa,
    )
    return redirect("rh:colaborador_detalhe", pk=colaborador.pk)


@rh_required
@empresa_ativa_required
@require_POST
def colaborador_transferir(request, pk):
    """
    Move o colaborador para outra empresa do mesmo cliente.

    As batidas ja registradas ficam onde aconteceram — foi ali que o
    trabalho foi prestado, e cada uma carrega o NSR daquela empresa numa
    corrente encadeada.
    """
    from django.core.exceptions import ValidationError

    from apps.clientes.models import Empresa

    colaborador = get_object_or_404(
        Colaborador, pk=pk, empresa=request.empresa_ativa
    )
    destino = get_object_or_404(
        Empresa, pk=request.POST.get("destino"),
        cliente=request.empresa_ativa.cliente,
    )

    origem = colaborador.empresa
    try:
        colaborador.mover_para(destino)
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
        return redirect("rh:colaborador_detalhe", pk=pk)

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.ALTERACAO,
        descricao=(
            f"{colaborador.nome_exibicao} transferido de "
            f"{origem.nome_exibicao} para {destino.nome_exibicao}"
        ),
        objeto=colaborador,
        empresa=origem,
    )
    messages.success(
        request,
        f"{colaborador.nome_exibicao} agora é de {destino.nome_exibicao}. "
        f"As batidas anteriores continuam em {origem.nome_exibicao}.",
    )
    return redirect("rh:colaborador_lista")


@rh_required
def aniversariantes(request):
    """
    Calendario de aniversarios do mes.

    A data ja estava no cadastro; o que faltava era um lugar onde alguem
    olhasse. Quem abre esta tela quer saber quem vem primeiro — por isso
    a lista ao lado do calendario vai por dia, e nao por nome.

    Navega por mes porque o uso real e antecipar: em 28 de marco alguem
    quer saber quem faz aniversario em abril, para encomendar o bolo.
    """
    from apps.core.mixins import escopo_empresas
    from apps.rh import aniversariantes as calendario

    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get("ano") or hoje.year)
        mes = int(request.GET.get("mes") or hoje.month)
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month
    if not 1 <= mes <= 12:
        ano, mes = hoje.year, hoje.month

    empresas = escopo_empresas(request.user)
    lista = calendario.do_mes(empresas, ano, mes)

    anterior = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    proximo = (ano + 1, 1) if mes == 12 else (ano, mes + 1)

    return render(
        request,
        "rh/aniversariantes.html",
        {
            "menu_ativo": "aniversariantes",
            "titulo": "Aniversariantes",
            "ano": ano,
            "mes": mes,
            "mes_nome": calendario.MESES[mes - 1],
            "dias_semana": calendario.DIAS_DA_SEMANA,
            "semanas": calendario.grade(ano, mes, lista),
            "aniversariantes": lista,
            "com_email": sum(1 for a in lista if a["email"]),
            "anterior": {"ano": anterior[0], "mes": anterior[1]},
            "proximo": {"ano": proximo[0], "mes": proximo[1]},
        },
    )
