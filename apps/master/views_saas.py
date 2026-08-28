"""
Kronus — administração da plataforma pelo Master (KS TEC).

    /master/gateway/            credenciais do ASAAS e teste de conexão
    /master/assinaturas/        carteira: quem paga, quanto, e quem atrasou
    /master/usuarios/           todos os usuários, de todos os clientes
    /master/usuarios/novo/      criação de usuário em qualquer conta
    /master/usuarios/<pk>/      edição, reset de senha, ativação
    /master/auditoria/          logs de todos os clientes, num lugar só

**O que justifica o Master ver tudo.** A KS TEC opera a plataforma: sem
uma visão consolidada de usuários e logs, todo chamado de suporte
("fulano não consegue entrar", "quem apagou este ajuste?") exige acesso
ao banco. O preço disso é que o Master é a credencial mais poderosa do
sistema — e por isso cada ação aqui grava `LogAcessoMaster`, que é
imutável por construção.
"""
import logging

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.constants import TipoUsuario
from apps.core.decorators import master_required
from apps.core.utils import obter_ip
from apps.master.models import LogAcessoMaster

logger = logging.getLogger("kronus.master")


def _log(request, acao, cliente=None, detalhes=""):
    LogAcessoMaster.objects.create(
        usuario=request.user, cliente=cliente, acao=acao,
        detalhes=detalhes, ip=obter_ip(request),
    )


# ══════════════════════════════════════════════════════════════
# Gateway de pagamento
# ══════════════════════════════════════════════════════════════
@master_required
def gateway(request):
    """
    Credenciais do ASAAS.

    A chave só é gravada quando o campo vem preenchido: um POST com o
    campo vazio **mantém** a chave atual. Sem essa regra, salvar
    qualquer outro ajuste da tela apagaria a credencial, porque a chave
    nunca é reexibida para ser reenviada.
    """
    from apps.faturamento.models import ConfiguracaoGateway

    config = ConfiguracaoGateway.carregar()
    diagnostico = None

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "salvar":
            config.ambiente = request.POST.get("ambiente", config.ambiente)
            config.ativo = request.POST.get("ativo") == "on"

            chave = (request.POST.get("api_key") or "").strip()
            if chave:
                config.api_key = chave

            token = (request.POST.get("webhook_token") or "").strip()
            if token:
                if len(token) < 32:
                    messages.error(
                        request,
                        "O token do webhook precisa ter ao menos 32 caracteres — "
                        "é ele que impede alguém de forjar uma confirmação de pagamento.",
                    )
                    return redirect("master:gateway")
                config.webhook_token = token

            try:
                config.dias_ate_vencimento = int(request.POST.get("dias_ate_vencimento", 7))
                config.dias_tolerancia_suspensao = int(
                    request.POST.get("dias_tolerancia_suspensao", 5)
                )
            except ValueError:
                messages.error(request, "Os prazos devem ser números inteiros.")
                return redirect("master:gateway")

            config.emitir_nota_fiscal = request.POST.get("emitir_nota_fiscal") == "on"
            config.nota_fiscal_descricao = (
                request.POST.get("nota_fiscal_descricao")
                or config.nota_fiscal_descricao
            )[:255]

            if config.ativo and not config.configurado:
                messages.error(
                    request,
                    "Para ativar a cobrança, preencha a chave de API e o token do webhook.",
                )
                return redirect("master:gateway")

            config.save()
            _log(
                request, LogAcessoMaster.Acao.API_KEY_GERADA,
                detalhes=(
                    f"Gateway ASAAS atualizado: ambiente={config.ambiente}, "
                    f"ativo={config.ativo}"
                ),
            )
            messages.success(request, "Configuração do gateway salva.")
            return redirect("master:gateway")

        if acao == "testar":
            from apps.faturamento.asaas import ClienteAsaas, ErroGateway

            try:
                diagnostico = ClienteAsaas(config.api_key, config.url_base).testar()
                messages.success(
                    request,
                    f"Conexão com o ASAAS ({config.get_ambiente_display()}) confirmada.",
                )
            except ErroGateway as erro:
                diagnostico = {"ok": False, "erro": erro.descricao}
                messages.error(request, f"O gateway recusou: {erro.descricao}")

        if acao == "gerar_token":
            from apps.core.utils import gerar_token as novo_token

            config.webhook_token = novo_token(32)
            config.save(update_fields=["webhook_token", "updated_at"])
            messages.success(
                request,
                "Token gerado. Copie e cadastre no painel do ASAAS, em "
                "Integrações › Webhooks.",
            )

    url_webhook = request.build_absolute_uri("/faturamento/webhook/asaas/")
    return render(
        request,
        "master/saas/gateway.html",
        {
            "titulo": "Gateway de pagamento",
            "menu_ativo": "gateway",
            "config": config,
            "diagnostico": diagnostico,
            "url_webhook": url_webhook,
        },
    )


# ══════════════════════════════════════════════════════════════
# Carteira de assinaturas
# ══════════════════════════════════════════════════════════════
@master_required
def assinaturas(request):
    """A carteira: quem paga, quanto, e o que está vencido."""
    from apps.faturamento.models import Assinatura, Cobranca

    consulta = Assinatura.objects.select_related(
        "cliente", "plano"
    ).order_by("-created_at")

    situacao = request.GET.get("status")
    busca = request.GET.get("busca", "")
    if situacao:
        consulta = consulta.filter(status=situacao)
    if busca:
        consulta = consulta.filter(
            Q(cliente__razao_social__icontains=busca)
            | Q(cliente__cnpj__icontains=busca)
        )

    hoje = timezone.localdate()
    vencidas = Cobranca.objects.filter(vencimento__lt=hoje).exclude(
        status__in=list(Cobranca.STATUS_PAGOS) + ["cancelada"]
    )

    recebido_mes = Cobranca.objects.filter(
        status__in=Cobranca.STATUS_PAGOS,
        pago_em__year=hoje.year,
        pago_em__month=hoje.month,
    ).aggregate(total=Sum("valor"))["total"] or 0

    mrr = Assinatura.objects.filter(
        status__in=[Assinatura.Status.ATIVA, Assinatura.Status.TESTE]
    ).aggregate(total=Sum("valor"))["total"] or 0

    return render(
        request,
        "master/saas/assinaturas.html",
        {
            "titulo": "Assinaturas",
            "menu_ativo": "assinaturas",
            "assinaturas": consulta[:200],
            "total": consulta.count(),
            "mrr": mrr,
            "recebido_mes": recebido_mes,
            "qtd_vencidas": vencidas.count(),
            "valor_vencido": vencidas.aggregate(t=Sum("valor"))["t"] or 0,
            "status_choices": Assinatura.Status.choices,
            "status_atual": situacao or "",
            "busca": busca,
        },
    )


@master_required
def assinatura_detalhe(request, pk):
    """Ficha da assinatura, com as faturas e ações de reconciliação."""
    from apps.faturamento.models import Assinatura
    from apps.faturamento.services import AssinaturaService

    assinatura = get_object_or_404(
        Assinatura.objects.select_related("cliente", "plano"), pk=pk
    )

    if request.method == "POST":
        acao = request.POST.get("acao")
        try:
            if acao == "sincronizar":
                AssinaturaService.sincronizar_no_gateway(assinatura)
                messages.success(request, "Assinatura sincronizada com o gateway.")
            elif acao == "importar":
                total = AssinaturaService.importar_cobrancas(assinatura)
                messages.success(request, f"{total} cobrança(s) importada(s).")
            elif acao == "reavaliar":
                novo = AssinaturaService.avaliar_inadimplencia(assinatura)
                messages.info(request, f"Situação reavaliada: {novo}.")
            elif acao == "cancelar":
                AssinaturaService.cancelar(
                    assinatura=assinatura,
                    motivo=request.POST.get("motivo", "Cancelada pelo Master"),
                )
                messages.warning(request, "Assinatura cancelada.")
        except Exception as erro:
            logger.exception("Falha na acao %s da assinatura %s.", acao, pk)
            messages.error(request, f"Não foi possível concluir: {erro}")
        return redirect("master:assinatura_detalhe", pk=pk)

    return render(
        request,
        "master/saas/assinatura_detalhe.html",
        {
            "titulo": f"Assinatura — {assinatura.cliente}",
            "menu_ativo": "assinaturas",
            "assinatura": assinatura,
            "cobrancas": assinatura.cobrancas.order_by("-vencimento")[:36],
        },
    )


# ══════════════════════════════════════════════════════════════
# Usuários de todos os clientes
# ══════════════════════════════════════════════════════════════
@master_required
def usuarios(request):
    """Todos os usuários da plataforma, com filtro por conta e por papel."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    consulta = User.objects.select_related("cliente").order_by("-date_joined")

    if busca := request.GET.get("busca"):
        consulta = consulta.filter(
            Q(username__icontains=busca)
            | Q(nome_completo__icontains=busca)
            | Q(email__icontains=busca)
            | Q(cliente__razao_social__icontains=busca)
        )
    if tipo := request.GET.get("tipo"):
        consulta = consulta.filter(tipo=tipo)
    if cliente_id := request.GET.get("cliente"):
        consulta = consulta.filter(cliente_id=cliente_id)
    if request.GET.get("situacao") == "inativos":
        consulta = consulta.filter(is_active=False)
    elif request.GET.get("situacao") == "ativos":
        consulta = consulta.filter(is_active=True)

    from apps.clientes.models import Cliente

    return render(
        request,
        "master/saas/usuarios.html",
        {
            "titulo": "Usuários da plataforma",
            "menu_ativo": "usuarios",
            "usuarios": consulta[:300],
            "total": consulta.count(),
            "tipos": TipoUsuario.choices,
            "clientes": Cliente.objects.order_by("razao_social"),
            "busca": request.GET.get("busca", ""),
            "tipo_atual": request.GET.get("tipo", ""),
            "cliente_atual": request.GET.get("cliente", ""),
            "situacao": request.GET.get("situacao", ""),
        },
    )


@master_required
def usuario_criar(request):
    """
    Cria um usuário em qualquer conta.

    A senha **não** é escolhida pelo Master: geramos uma provisória e a
    exibimos uma única vez. Definir a senha de outra pessoa cria um
    período em que duas pessoas a conhecem, e o rastro de quem fez o quê
    deixa de valer.
    """
    from apps.master.forms import UsuarioMasterForm

    form = UsuarioMasterForm(request.POST or None)
    senha_provisoria = None

    if request.method == "POST" and form.is_valid():
        from apps.core.utils import gerar_token

        senha_provisoria = gerar_token(9)
        usuario = form.save(commit=False)
        usuario.set_password(senha_provisoria)
        usuario.trocar_senha_no_proximo_login = True
        usuario.save()
        form.save_m2m()

        _log(
            request, LogAcessoMaster.Acao.CLIENTE_EDITADO,
            cliente=usuario.cliente,
            detalhes=f"Usuario criado: {usuario.username} ({usuario.tipo})",
        )
        messages.success(
            request,
            f"Usuário {usuario.username} criado. Copie a senha provisória agora — "
            "ela não será exibida de novo.",
        )
        return render(
            request,
            "master/saas/usuario_criado.html",
            {
                "titulo": "Usuário criado",
                "menu_ativo": "usuarios",
                "usuario": usuario,
                "senha_provisoria": senha_provisoria,
            },
        )

    return render(
        request,
        "master/saas/usuario_form.html",
        {
            "titulo": "Novo usuário",
            "menu_ativo": "usuarios",
            "form": form,
        },
    )


@master_required
def usuario_editar(request, pk):
    """Edição do cadastro, sem tocar em senha."""
    from django.contrib.auth import get_user_model

    from apps.master.forms import UsuarioMasterForm

    User = get_user_model()
    usuario = get_object_or_404(User, pk=pk)
    form = UsuarioMasterForm(request.POST or None, instance=usuario)

    if request.method == "POST" and form.is_valid():
        form.save()
        _log(
            request, LogAcessoMaster.Acao.CLIENTE_EDITADO,
            cliente=usuario.cliente,
            detalhes=f"Usuario editado: {usuario.username}",
        )
        messages.success(request, "Usuário atualizado.")
        return redirect("master:usuarios")

    return render(
        request,
        "master/saas/usuario_form.html",
        {
            "titulo": f"Editar {usuario.username}",
            "menu_ativo": "usuarios",
            "form": form,
            "usuario": usuario,
        },
    )


@master_required
@require_POST
def usuario_resetar_senha(request, pk):
    """Gera nova senha provisória e força a troca no próximo acesso."""
    from django.contrib.auth import get_user_model

    from apps.core.utils import gerar_token

    User = get_user_model()
    usuario = get_object_or_404(User, pk=pk)

    senha = gerar_token(9)
    usuario.set_password(senha)
    usuario.trocar_senha_no_proximo_login = True
    usuario.save(update_fields=["password", "trocar_senha_no_proximo_login"])

    _log(
        request, LogAcessoMaster.Acao.CLIENTE_EDITADO,
        cliente=usuario.cliente,
        detalhes=f"Senha redefinida para {usuario.username}",
    )
    return render(
        request,
        "master/saas/usuario_criado.html",
        {
            "titulo": "Senha redefinida",
            "menu_ativo": "usuarios",
            "usuario": usuario,
            "senha_provisoria": senha,
            "redefinicao": True,
        },
    )


@master_required
@require_POST
def usuario_alternar_ativo(request, pk):
    """
    Ativa ou desativa o acesso.

    **Nunca apaga.** O usuário aparece em logs de acesso, em ajustes de
    ponto e em aprovações de atestado; excluí-lo deixaria esses
    registros apontando para o vazio, e a auditoria perderia o autor.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    usuario = get_object_or_404(User, pk=pk)

    if usuario.pk == request.user.pk:
        messages.error(request, "Você não pode desativar o próprio acesso.")
        return redirect("master:usuarios")

    usuario.is_active = not usuario.is_active
    usuario.save(update_fields=["is_active"])

    _log(
        request, LogAcessoMaster.Acao.CLIENTE_EDITADO,
        cliente=usuario.cliente,
        detalhes=(
            f"Usuario {usuario.username} "
            f"{'reativado' if usuario.is_active else 'desativado'}"
        ),
    )
    messages.success(
        request,
        f"Usuário {'reativado' if usuario.is_active else 'desativado'}.",
    )
    return redirect("master:usuarios")


# ══════════════════════════════════════════════════════════════
# Auditoria consolidada
# ══════════════════════════════════════════════════════════════
@master_required
def auditoria(request):
    """
    Logs de todos os clientes num lugar só.

    O RH vê os logs da própria empresa; o Master vê os de todas — é o
    que permite responder "quem apagou este ajuste?" sem abrir o banco.
    """
    from apps.core.models import LogAcesso

    consulta = LogAcesso.objects.select_related(
        "usuario", "empresa", "cliente"
    ).order_by("-created_at")

    if busca := request.GET.get("busca"):
        consulta = consulta.filter(
            Q(descricao__icontains=busca)
            | Q(usuario__username__icontains=busca)
            | Q(usuario__nome_completo__icontains=busca)
            | Q(empresa__razao_social__icontains=busca)
        )
    if acao := request.GET.get("acao"):
        consulta = consulta.filter(acao=acao)
    if cliente_id := request.GET.get("cliente"):
        consulta = consulta.filter(
            Q(cliente_id=cliente_id) | Q(empresa__cliente_id=cliente_id)
        )
    if desde := request.GET.get("desde"):
        consulta = consulta.filter(created_at__date__gte=desde)

    from apps.clientes.models import Cliente

    resumo = (
        LogAcesso.objects.values("acao")
        .annotate(total=Count("pk"))
        .order_by("-total")[:8]
    )

    return render(
        request,
        "master/saas/auditoria.html",
        {
            "titulo": "Auditoria da plataforma",
            "menu_ativo": "auditoria",
            "logs": consulta[:400],
            "total": consulta.count(),
            "acoes": LogAcesso.Acao.choices,
            "clientes": Cliente.objects.order_by("razao_social"),
            "resumo": resumo,
            "busca": request.GET.get("busca", ""),
            "acao_atual": request.GET.get("acao", ""),
            "cliente_atual": request.GET.get("cliente", ""),
            "desde": request.GET.get("desde", ""),
        },
    )
