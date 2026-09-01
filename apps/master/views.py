"""
Kronus — painel Master (KS TEC).

Escopo da Fase 1: dashboard, CRUD de clientes, vinculo de empresas,
gestao de planos, suspensao/reativacao, API keys e logs.
A gestao de totens e comodato entra na Fase 5.
"""
from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.clientes.forms import ClienteForm, EmpresaForm
from apps.clientes.models import Cliente, Empresa
from apps.core.decorators import master_required
from apps.core.mixins import MasterRequiredMixin, SucessoMensagemMixin
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.core.utils import obter_ip
from apps.master.forms import PlanoForm
from apps.master.models import LogAcessoMaster, Plano
from apps.rh.models import Colaborador
from apps.totem.models import Totem


def _log_master(request, acao, cliente=None, detalhes=""):
    LogAcessoMaster.objects.create(
        usuario=request.user,
        cliente=cliente,
        acao=acao,
        detalhes=detalhes,
        ip=obter_ip(request),
    )


# ==============================================================
# Dashboard
# ==============================================================
@master_required
def dashboard(request):
    """Visao geral da plataforma (Secao 6.7 do plano)."""
    clientes = Cliente.objects.select_related("plano")
    ativos = clientes.filter(ativo=True, suspenso=False)

    receita = sum(
        (c.plano.preco_mensal or 0) for c in ativos.only("plano__preco_mensal")
    )

    totens = Totem.objects.filter(ativo=True)
    contexto = {
        "titulo": "Dashboard Master",
        "menu_ativo": "dashboard",
        "total_clientes": clientes.count(),
        "total_clientes_ativos": ativos.count(),
        "total_clientes_suspensos": clientes.filter(suspenso=True).count(),
        "total_empresas": Empresa.objects.filter(ativo=True).count(),
        "total_colaboradores": Colaborador.objects.filter(ativo=True).count(),
        "total_totens": totens.count(),
        "totens_offline": [t for t in totens.select_related("empresa") if not t.online],
        "receita_mensal": receita,
        "clientes_recentes": clientes.order_by("-created_at")[:8],
        "planos": Plano.objects.annotate(qtd_clientes=Count("clientes")),
    }
    return render(request, "master/dashboard.html", contexto)


# ==============================================================
# Clientes
# ==============================================================
class ClienteListView(MasterRequiredMixin, ListView):
    model = Cliente
    template_name = "master/clientes/lista.html"
    context_object_name = "clientes"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Cliente.objects.select_related("plano")
            .annotate(qtd_empresas=Count("empresas", distinct=True))
            .order_by("razao_social")
        )
        busca = self.request.GET.get("q", "").strip()
        if busca:
            qs = qs.filter(
                Q(razao_social__icontains=busca)
                | Q(nome_fantasia__icontains=busca)
                | Q(cnpj__icontains=busca)
                | Q(email_contato__icontains=busca)
            )
        status = self.request.GET.get("status")
        if status == "ativos":
            qs = qs.filter(ativo=True, suspenso=False)
        elif status == "suspensos":
            qs = qs.filter(suspenso=True)
        elif status == "inativos":
            qs = qs.filter(ativo=False)
        plano = self.request.GET.get("plano")
        if plano:
            qs = qs.filter(plano_id=plano)
        return qs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Clientes"
        contexto["menu_ativo"] = "clientes"
        contexto["planos"] = Plano.objects.all()
        contexto["busca"] = self.request.GET.get("q", "")
        contexto["status_selecionado"] = self.request.GET.get("status", "")
        return contexto


class ClienteDetailView(MasterRequiredMixin, DetailView):
    model = Cliente
    template_name = "master/clientes/detalhe.html"
    context_object_name = "cliente"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        cliente = self.object
        contexto["titulo"] = cliente.razao_social
        contexto["menu_ativo"] = "clientes"
        contexto["empresas"] = cliente.empresas.annotate(
            qtd_colaboradores=Count("colaborador_set", distinct=True)
        )
        contexto["usuarios"] = cliente.usuarios.all()
        contexto["totens"] = Totem.objects.filter(empresa__cliente=cliente).select_related(
            "empresa", "grupo"
        )
        contexto["logs"] = cliente.logs_master.select_related("usuario")[:20]
        contexto["uso"] = {
            "empresas": (cliente.total_empresas, cliente.limite_de_empresas),
            "colaboradores": (
                cliente.total_colaboradores,
                cliente.plano.max_colaboradores,
            ),
            "totens": (cliente.total_totens, cliente.plano.max_totems),
        }
        return contexto


class ClienteCreateView(MasterRequiredMixin, SucessoMensagemMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "master/clientes/criar.html"
    mensagem_sucesso = "Cliente cadastrado com sucesso."
    extra_context = {"titulo": "Novo cliente", "menu_ativo": "clientes"}

    def get_success_url(self):
        return reverse("master:cliente_detalhe", args=[self.object.pk])

    def form_valid(self, form):
        resposta = super().form_valid(form)

        # O contratante e, ele mesmo, uma empresa. Sem criar aqui, o
        # cliente nascia sem nenhuma — e o proximo passo natural (criar o
        # Admin RH) ficava impossivel, porque o papel exige ao menos uma.
        empresa = self.object.garantir_empresa_propria()

        _log_master(
            self.request,
            LogAcessoMaster.Acao.CLIENTE_CRIADO,
            self.object,
            f"Plano: {self.object.plano}; empresa própria: {empresa.razao_social}",
        )
        registrar_log(
            request=self.request,
            acao=LogAcesso.Acao.CRIACAO,
            descricao=f"Cliente criado: {self.object}",
            objeto=self.object,
        )
        return resposta


class ClienteUpdateView(MasterRequiredMixin, SucessoMensagemMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "master/clientes/editar.html"
    mensagem_sucesso = "Cliente atualizado."
    extra_context = {"titulo": "Editar cliente", "menu_ativo": "clientes"}

    def get_success_url(self):
        return reverse("master:cliente_detalhe", args=[self.object.pk])

    def form_valid(self, form):
        plano_anterior = Cliente.objects.get(pk=self.object.pk).plano
        resposta = super().form_valid(form)
        if plano_anterior != self.object.plano:
            _log_master(
                self.request,
                LogAcessoMaster.Acao.PLANO_ALTERADO,
                self.object,
                f"{plano_anterior} → {self.object.plano}",
            )
        else:
            _log_master(self.request, LogAcessoMaster.Acao.CLIENTE_EDITADO, self.object)
        return resposta


@master_required
def cliente_suspender(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == "POST":
        motivo = request.POST.get("motivo", "")
        if cliente.suspenso:
            cliente.reativar()
            _log_master(request, LogAcessoMaster.Acao.CLIENTE_REATIVADO, cliente)
            messages.success(request, f"Cliente {cliente} reativado.")
        else:
            cliente.suspender(motivo)
            _log_master(
                request, LogAcessoMaster.Acao.CLIENTE_SUSPENSO, cliente, motivo
            )
            messages.warning(request, f"Cliente {cliente} suspenso.")
    return redirect("master:cliente_detalhe", pk=pk)


@master_required
def cliente_api_key(request, pk):
    """Gera ou revoga a API key de conta do cliente (Secao 7.4)."""
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "revogar":
            cliente.revogar_api_key()
            _log_master(request, LogAcessoMaster.Acao.API_KEY_REVOGADA, cliente)
            messages.info(request, "API key revogada.")
        else:
            chave = cliente.gerar_api_key()
            _log_master(request, LogAcessoMaster.Acao.API_KEY_GERADA, cliente)
            messages.success(
                request,
                "Nova API key gerada. Copie agora — ela não será exibida novamente: "
                f"{chave}",
            )
    return redirect("master:cliente_detalhe", pk=pk)


# ==============================================================
# Empresas
# ==============================================================
class EmpresaListView(MasterRequiredMixin, ListView):
    model = Empresa
    template_name = "master/empresas/lista.html"
    context_object_name = "empresas"
    paginate_by = 25

    def get_queryset(self):
        qs = Empresa.objects.select_related("cliente").annotate(
            qtd_colaboradores=Count("colaborador_set", distinct=True)
        )
        busca = self.request.GET.get("q", "").strip()
        if busca:
            qs = qs.filter(
                Q(razao_social__icontains=busca)
                | Q(nome_fantasia__icontains=busca)
                | Q(cnpj__icontains=busca)
            )
        cliente = self.request.GET.get("cliente")
        if cliente:
            qs = qs.filter(cliente_id=cliente)
        return qs.order_by("cliente__razao_social", "razao_social")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["titulo"] = "Empresas"
        contexto["menu_ativo"] = "empresas"
        contexto["clientes"] = Cliente.objects.all()
        contexto["busca"] = self.request.GET.get("q", "")
        return contexto


class EmpresaCreateView(MasterRequiredMixin, SucessoMensagemMixin, CreateView):
    model = Empresa
    form_class = EmpresaForm
    template_name = "master/empresas/vincular.html"
    mensagem_sucesso = "Empresa vinculada ao cliente."
    extra_context = {"titulo": "Vincular empresa", "menu_ativo": "empresas"}

    def get_initial(self):
        inicial = super().get_initial()
        cliente = self.request.GET.get("cliente")
        if cliente:
            inicial["cliente"] = cliente
        return inicial

    def form_valid(self, form):
        cliente = form.cleaned_data["cliente"]
        if not cliente.pode_adicionar_empresa():
            form.add_error(
                "cliente",
                f"O plano {cliente.plano} permite no máximo "
                f"{cliente.limite_de_empresas} empresa(s). Para liberar "
                f"mais, ajuste “Empresas adicionais” na assinatura.",
            )
            return self.form_invalid(form)
        resposta = super().form_valid(form)
        _log_master(
            self.request,
            LogAcessoMaster.Acao.EMPRESA_VINCULADA,
            cliente,
            f"Empresa: {self.object}",
        )
        return resposta

    def get_success_url(self):
        return reverse("master:cliente_detalhe", args=[self.object.cliente_id])


class EmpresaUpdateView(MasterRequiredMixin, SucessoMensagemMixin, UpdateView):
    model = Empresa
    form_class = EmpresaForm
    template_name = "master/empresas/vincular.html"
    mensagem_sucesso = "Empresa atualizada."
    extra_context = {"titulo": "Editar empresa", "menu_ativo": "empresas"}

    def get_success_url(self):
        return reverse("master:cliente_detalhe", args=[self.object.cliente_id])


# ==============================================================
# Planos
# ==============================================================
class PlanoListView(MasterRequiredMixin, ListView):
    model = Plano
    template_name = "master/planos/lista.html"
    context_object_name = "planos"
    extra_context = {"titulo": "Planos", "menu_ativo": "planos"}

    def get_queryset(self):
        return Plano.objects.annotate(
            qtd_clientes=Count(
                "clientes", filter=Q(clientes__ativo=True, clientes__suspenso=False)
            )
        ).order_by("ordem", "preco_mensal")


class PlanoCreateView(MasterRequiredMixin, SucessoMensagemMixin, CreateView):
    model = Plano
    form_class = PlanoForm
    template_name = "master/planos/editar.html"
    success_url = reverse_lazy("master:plano_lista")
    mensagem_sucesso = "Plano criado."
    extra_context = {"titulo": "Novo plano", "menu_ativo": "planos"}


class PlanoUpdateView(MasterRequiredMixin, SucessoMensagemMixin, UpdateView):
    model = Plano
    form_class = PlanoForm
    template_name = "master/planos/editar.html"
    success_url = reverse_lazy("master:plano_lista")
    mensagem_sucesso = "Plano atualizado."
    extra_context = {"titulo": "Editar plano", "menu_ativo": "planos"}


class PlanoDeleteView(MasterRequiredMixin, DeleteView):
    model = Plano
    success_url = reverse_lazy("master:plano_lista")
    template_name = "master/planos/confirmar_exclusao.html"

    def form_valid(self, form):
        if self.get_object().clientes.exists():
            messages.error(
                self.request, "Não é possível excluir um plano com clientes vinculados."
            )
            return HttpResponseRedirect(self.success_url)
        messages.success(self.request, "Plano excluído.")
        return super().form_valid(form)


# ==============================================================
# Logs
# ==============================================================
class LogAcessoListView(MasterRequiredMixin, ListView):
    model = LogAcesso
    template_name = "master/logs/acessos.html"
    context_object_name = "logs"
    paginate_by = 50
    extra_context = {"titulo": "Logs de acesso", "menu_ativo": "logs"}

    def get_queryset(self):
        qs = LogAcesso.objects.select_related("usuario", "cliente", "empresa")
        cliente = self.request.GET.get("cliente")
        if cliente:
            qs = qs.filter(cliente_id=cliente)
        acao = self.request.GET.get("acao")
        if acao:
            qs = qs.filter(acao=acao)
        return qs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["clientes"] = Cliente.objects.all()
        contexto["acoes"] = LogAcesso.Acao.choices
        return contexto


@master_required
def empresa_personalizacao(request, pk):
    """
    Logo, cores e capa do totem de uma empresa, pelo Master.

    A mesma tela existe no RH, mas so alcanca `request.empresa_ativa` — e
    o Master nao tem empresa ativa. Na pratica, quem faz a implantacao do
    cliente nao conseguia subir a logo dele em lugar nenhum.

    Reusa `PersonalizacaoEmpresaForm` de proposito: duplicar os campos
    aqui criaria dois formularios para a mesma coisa, que divergem no
    primeiro campo novo.
    """
    from apps.clientes.forms import PersonalizacaoEmpresaForm
    from apps.clientes.models import Empresa, SlideTotem

    empresa = get_object_or_404(
        Empresa.objects.select_related("cliente"), pk=pk
    )

    if request.method == "POST" and request.POST.get("acao") == "slide":
        return _slide_do_master(request, empresa, SlideTotem)

    form = PersonalizacaoEmpresaForm(
        request.POST or None, request.FILES or None, instance=empresa
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        _log_master(
            request, LogAcessoMaster.Acao.EMPRESA_VINCULADA, empresa.cliente,
            f"Personalização de {empresa.razao_social}: "
            f"{', '.join(form.changed_data) or 'sem alteração'}",
        )
        _avisar_totens_da_empresa(empresa)
        messages.success(request, "Personalização salva. Os totens serão atualizados.")
        return redirect("master:empresa_personalizacao", pk=pk)

    return render(request, "master/empresas/personalizacao.html", {
        "titulo": f"Personalização — {empresa.nome_exibicao}",
        "menu_ativo": "empresas",
        "empresa": empresa,
        "form": form,
        "slides": empresa.slides.order_by("ordem"),
        "totens": empresa.totens.filter(ativo=True),
    })


def _slide_do_master(request, empresa, SlideTotem):
    """Adiciona ou remove um slide da tela de ociosidade."""
    remover = request.POST.get("remover")
    if remover:
        empresa.slides.filter(pk=remover).delete()
        _avisar_totens_da_empresa(empresa)
        messages.success(request, "Slide removido.")
        return redirect("master:empresa_personalizacao", pk=empresa.pk)

    imagem = request.FILES.get("imagem")
    if imagem is None:
        messages.error(request, "Selecione uma imagem.")
    elif imagem.size > 8 * 1024 * 1024:
        # O totem baixa a imagem a cada troca de slide; num link de
        # portaria, um arquivo grande trava a tela em vez de enfeitá-la.
        messages.error(
            request,
            "Imagem acima de 8 MB. O totem carrega isso a cada troca de "
            "slide — comprima antes de enviar.",
        )
    else:
        ultima = empresa.slides.order_by("-ordem").first()
        SlideTotem.objects.create(
            empresa=empresa,
            imagem=imagem,
            legenda=(request.POST.get("legenda") or "")[:120],
            ordem=(ultima.ordem + 1) if ultima else 0,
        )
        _avisar_totens_da_empresa(empresa)
        messages.success(request, "Slide adicionado.")
    return redirect("master:empresa_personalizacao", pk=empresa.pk)


def _avisar_totens_da_empresa(empresa) -> None:
    """
    Pede aos totens da empresa que recarreguem a configuracao.

    Sem isto, a logo nova so apareceria quando alguem reiniciasse o
    tablet — e ninguem reinicia um totem de portaria.
    """
    from django.utils import timezone

    empresa.totens.filter(ativo=True).update(
        recarga_solicitada_em=timezone.now()
    )


# ══════════════════════════════════════════════════════════════
# Auditoria do reconhecimento facial
# ══════════════════════════════════════════════════════════════
@master_required
def reconhecimentos(request):
    """
    O que a câmera viu, e o que o sistema decidiu.

    Existe porque a pergunta que sempre aparece depois de um problema é
    a mesma: *foi a pessoa certa?* Sem a foto e a distância medida, a
    resposta era conversa — e a conversa é onde uma dúvida sobre ponto
    vira litígio.

    Cada linha traz o quadro recebido, o que foi decidido e o número que
    decidiu. Quem lê consegue conferir sozinho, sem depender de alguém
    interpretar o log.
    """
    from django.core.paginator import Paginator

    from apps.clientes.models import Empresa
    from apps.facial.models import TentativaReconhecimento
    from apps.rh.models import Colaborador

    tentativas = (
        TentativaReconhecimento.objects.select_related(
            "colaborador", "empresa", "totem"
        ).order_by("-created_at")
    )

    empresa_id = request.GET.get("empresa") or ""
    colaborador_id = request.GET.get("colaborador") or ""
    resultado = request.GET.get("resultado") or ""
    data = request.GET.get("data") or ""
    so_com_foto = request.GET.get("com_foto") == "1"

    if empresa_id:
        tentativas = tentativas.filter(empresa_id=empresa_id)
    if colaborador_id:
        tentativas = tentativas.filter(colaborador_id=colaborador_id)
    if resultado:
        tentativas = tentativas.filter(resultado=resultado)
    if data:
        tentativas = tentativas.filter(created_at__date=data)
    if so_com_foto:
        tentativas = tentativas.exclude(imagem="")

    pagina = Paginator(tentativas, 40).get_page(request.GET.get("pagina"))

    return render(
        request,
        "master/reconhecimentos.html",
        {
            "pagina": pagina,
            "empresas": Empresa.objects.order_by("razao_social"),
            "colaboradores": (
                Colaborador.objects.filter(empresa_id=empresa_id)
                .order_by("nome_completo")
                if empresa_id else Colaborador.objects.none()
            ),
            "resultados": TentativaReconhecimento.Resultado.choices,
            "filtros": {
                "empresa": empresa_id,
                "colaborador": colaborador_id,
                "resultado": resultado,
                "data": data,
                "com_foto": so_com_foto,
            },
            "limiar": settings.FACE_RECOGNITION_THRESHOLD,
            "menu_ativo": "reconhecimentos",
            "titulo": "Reconhecimento facial",
        },
    )


@master_required
def entrar_como(request, pk):
    """
    Abre o ambiente do cliente com os olhos dele.

    O master ja enxerga todas as empresas — o que faltava era a porta e,
    sobretudo, o aviso. Navegar no ambiente de um cliente sem saber
    disso e como se descobre, depois de meia hora, que a alteracao foi
    feita na empresa errada.

    Nao troca de usuario: continua sendo o master, com as permissoes
    dele. O que muda e a empresa ativa da sessao — e a faixa no topo,
    que nao deixa esquecer.

    Fica na auditoria porque entrar no ambiente de um cliente e acesso a
    dado de terceiro, e quem responde por LGPD precisa saber quando
    aconteceu.
    """
    from apps.clientes.models import Empresa
    from apps.core.middleware import CHAVE_SESSAO_EMPRESA

    empresa = get_object_or_404(Empresa, pk=pk)
    request.session[CHAVE_SESSAO_EMPRESA] = empresa.pk

    _log_master(
        request,
        LogAcessoMaster.Acao.CLIENTE_EDITADO,
        empresa.cliente,
        f"Entrou no ambiente de {empresa.nome_exibicao} para suporte",
    )
    messages.info(
        request,
        f"Você está vendo o ambiente de {empresa.nome_exibicao}. "
        f"Use “Sair do ambiente” quando terminar.",
    )
    return redirect("rh:dashboard")


@master_required
def sair_do_ambiente(request):
    """Volta para o painel da KS TEC."""
    from apps.core.middleware import CHAVE_SESSAO_EMPRESA

    request.session.pop(CHAVE_SESSAO_EMPRESA, None)
    return redirect("master:dashboard")


@master_required
def semelhancas(request):
    """
    Quem se parece com quem, por empresa, e o que fazer a respeito.

    Semelhanca entre cadastros nao e defeito: irmaos existem. O que esta
    tela responde nao e "ha semelhanca?", e sim "esta semelhanca ja
    atrapalha, e o que resolve?" — por isso cada par vem com acao.

    O calculo compara todos contra todos e e caro. Fica em cache; o
    botao "recalcular" existe para depois de um recadastro, quando quem
    esta olhando quer ver o efeito do que acabou de fazer.
    """
    from apps.clientes.models import Empresa
    from apps.facial import semelhancas as analise

    empresas = Empresa.objects.select_related("cliente").filter(
        ativo=True
    ).order_by("cliente__razao_social", "razao_social")

    escolhida = request.GET.get("empresa")
    empresa = None
    if escolhida:
        empresa = empresas.filter(pk=escolhida).first()
    if empresa is None:
        empresa = empresas.first()

    relatorio = None
    if empresa is not None:
        recalcular = request.GET.get("recalcular") == "1"
        if recalcular:
            analise.esquecer(empresa.pk)
        relatorio = analise.levantar(empresa, usar_cache=not recalcular)

    return render(
        request,
        "master/semelhancas.html",
        {
            "empresas": empresas,
            "empresa": empresa,
            "relatorio": relatorio,
            "titulo": "Semelhanças entre cadastros",
        },
    )


@master_required
def tela_ociosa(request):
    """
    O acervo da tela ociosa: frases e imagens, com procedencia.

    A fonte e a licenca aparecem em cada imagem porque e o que permite
    conferir depois. Imagem de terceiro num totem comercial sem licenca
    conferida e risco juridico do cliente que instalou o equipamento —
    e o equipamento esta na parede dele, com a marca dele.
    """
    from apps.clientes.ambiente import FraseAmbiente, ImagemAmbiente, Periodo
    from apps.clientes.ambiente_servico import esquecer

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "remover_imagem":
            alvo = ImagemAmbiente.objects.filter(
                pk=request.POST.get("id")
            ).first()
            if alvo:
                alvo.delete()
                esquecer()
                messages.success(request, "Imagem removida do acervo.")

        elif acao == "alternar_imagem":
            alvo = ImagemAmbiente.objects.filter(
                pk=request.POST.get("id")
            ).first()
            if alvo:
                alvo.ativo = not alvo.ativo
                alvo.save(update_fields=["ativo", "updated_at"])
                esquecer()
                messages.success(
                    request,
                    "Imagem ativada." if alvo.ativo else "Imagem desativada.",
                )

        elif acao == "adicionar_imagem":
            arquivo = request.FILES.get("imagem")
            licenca = (request.POST.get("licenca") or "").strip()
            fonte = (request.POST.get("fonte") or "").strip()
            if not (arquivo and licenca and fonte):
                messages.error(
                    request,
                    "Imagem, licença e origem são obrigatórias — sem elas "
                    "não dá para conferir o uso depois.",
                )
            else:
                ImagemAmbiente.objects.create(
                    periodo=request.POST.get("periodo") or Periodo.MANHA,
                    imagem=arquivo,
                    titulo=(request.POST.get("titulo") or "").strip()[:120],
                    autor=(request.POST.get("autor") or "").strip()[:120],
                    fonte=fonte[:500],
                    licenca=licenca[:80],
                )
                esquecer()
                messages.success(request, "Imagem adicionada ao acervo.")

        elif acao == "alternar_frase":
            frase = FraseAmbiente.objects.filter(
                pk=request.POST.get("id")
            ).first()
            if frase:
                frase.ativo = not frase.ativo
                frase.save(update_fields=["ativo", "updated_at"])
                esquecer()

        elif acao == "adicionar_frase":
            texto = (request.POST.get("texto") or "").strip()
            if texto:
                FraseAmbiente.objects.create(
                    periodo=request.POST.get("periodo") or Periodo.MANHA,
                    tipo=request.POST.get("tipo") or FraseAmbiente.Tipo.SAUDACAO,
                    texto=texto[:160],
                )
                esquecer()
                messages.success(request, "Frase adicionada.")

        elif acao == "remover_frase":
            FraseAmbiente.objects.filter(pk=request.POST.get("id")).delete()
            esquecer()
            messages.success(request, "Frase removida.")

        return redirect("master:tela_ociosa")

    periodo = request.GET.get("periodo") or Periodo.MANHA
    if periodo not in Periodo.values:
        periodo = Periodo.MANHA

    return render(
        request,
        "master/tela_ociosa.html",
        {
            "menu_ativo": "tela_ociosa",
            "titulo": "Tela ociosa do totem",
            "periodo": periodo,
            "periodos": Periodo.choices,
            "tipos": FraseAmbiente.Tipo.choices,
            "imagens": ImagemAmbiente.objects.filter(periodo=periodo),
            "frases": FraseAmbiente.objects.filter(periodo=periodo),
            "total_imagens": ImagemAmbiente.objects.count(),
            "total_frases": FraseAmbiente.objects.count(),
        },
    )
