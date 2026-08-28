"""
Kronus — area comercial do Master.

    /master/comercial/          contato publico e regras da demonstracao
    /master/comercial/demos/    quem pediu demonstracao e o que aconteceu

O numero de WhatsApp da capa morava no template. Trocar um telefone
exigia editar codigo e fazer deploy — o que garante que, na primeira
troca urgente, o numero fica errado no ar por horas.
"""
import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.comercial.models import ConfiguracaoComercial, SolicitacaoDemonstracao
from apps.core.decorators import master_required
from apps.master.models import LogAcessoMaster

logger = logging.getLogger("kronus.master")


def _log(request, acao, cliente=None, detalhes=""):
    from apps.core.utils import obter_ip

    LogAcessoMaster.objects.create(
        usuario=request.user, acao=acao, cliente=cliente,
        detalhes=detalhes, ip=obter_ip(request),
    )


@master_required
def configuracao(request):
    """Contato publico da capa e regras da demonstracao automatica."""
    config = ConfiguracaoComercial.carregar()

    if request.method == "POST":
        config.whatsapp = "".join(
            c for c in request.POST.get("whatsapp", "") if c.isdigit()
        )[:20]
        config.whatsapp_mensagem = request.POST.get(
            "whatsapp_mensagem", ""
        ).strip()[:255] or "Olá, quero conhecer o Kronus."
        config.email_contato = request.POST.get("email_contato", "").strip()
        config.telefone = request.POST.get("telefone", "").strip()[:20]

        config.demo_ativa = request.POST.get("demo_ativa") == "on"
        for campo, minimo, maximo, padrao in (
            ("demo_horas", 1, 720, 24),
            ("demo_limite_diario", 0, 500, 20),
            ("demo_colaboradores_exemplo", 0, 12, 8),
        ):
            try:
                valor = int(request.POST.get(campo, padrao))
            except (TypeError, ValueError):
                valor = padrao
            setattr(config, campo, max(minimo, min(maximo, valor)))

        config.save()
        _log(request, LogAcessoMaster.Acao.CONFIG_ALTERADA,
             detalhes="Configuração comercial atualizada")
        messages.success(request, "Configuração comercial salva.")
        return redirect("master:comercial_config")

    return render(request, "master/comercial/configuracao.html", {
        "config": config,
        "titulo": "Comercial",
        "menu_ativo": "comercial",
    })


@master_required
def demonstracoes(request):
    """Quem pediu demonstracao, em que estado esta, e quem virou cliente."""
    consulta = SolicitacaoDemonstracao.objects.select_related("cliente")

    situacao = request.GET.get("status", "")
    if situacao in dict(SolicitacaoDemonstracao.Status.choices):
        consulta = consulta.filter(status=situacao)

    busca = request.GET.get("q", "").strip()
    if busca:
        consulta = consulta.filter(
            Q(empresa__icontains=busca)
            | Q(nome__icontains=busca)
            | Q(email__icontains=busca)
        )

    resumo = SolicitacaoDemonstracao.objects.aggregate(
        total=Count("id"),
        ativas=Count("id", filter=Q(status=SolicitacaoDemonstracao.Status.ATIVA)),
        convertidas=Count(
            "id", filter=Q(status=SolicitacaoDemonstracao.Status.CONVERTIDA)
        ),
        expiradas=Count(
            "id", filter=Q(status=SolicitacaoDemonstracao.Status.EXPIRADA)
        ),
    )
    # Taxa de conversao sobre o que ja terminou: incluir as demonstracoes
    # ainda rodando no denominador faria a taxa parecer pior do que e.
    encerradas = resumo["convertidas"] + resumo["expiradas"]
    resumo["conversao"] = (
        round(100 * resumo["convertidas"] / encerradas) if encerradas else None
    )

    return render(request, "master/comercial/demonstracoes.html", {
        "solicitacoes": consulta[:200],
        "resumo": resumo,
        "status_escolhido": situacao,
        "busca": busca,
        "situacoes": SolicitacaoDemonstracao.Status.choices,
        "titulo": "Demonstrações",
        "menu_ativo": "comercial",
    })


@master_required
@require_POST
def demonstracao_prorrogar(request, pk):
    """Estende o prazo. Reativa o cliente quando ja tinha expirado."""
    from datetime import timedelta

    from apps.clientes.models import Cliente

    solicitacao = get_object_or_404(SolicitacaoDemonstracao, pk=pk)
    try:
        horas = max(1, min(720, int(request.POST.get("horas", 24))))
    except (TypeError, ValueError):
        horas = 24

    base = max(solicitacao.expira_em, timezone.now())
    solicitacao.expira_em = base + timedelta(hours=horas)
    solicitacao.status = SolicitacaoDemonstracao.Status.ATIVA
    solicitacao.save(update_fields=["expira_em", "status", "updated_at"])

    if solicitacao.cliente_id:
        Cliente.objects.filter(pk=solicitacao.cliente_id).update(
            suspenso=False, motivo_suspensao="",
            demo_expira_em=solicitacao.expira_em, updated_at=timezone.now(),
        )

    _log(request, LogAcessoMaster.Acao.DEMO_PRORROGADA, solicitacao.cliente,
         f"Demonstração prorrogada por {horas}h")
    messages.success(request, f"Demonstração prorrogada por {horas} horas.")
    return redirect("master:comercial_demos")


@master_required
@require_POST
def demonstracao_converter(request, pk):
    """
    Tira a marca de demonstracao: o ambiente vira cliente de verdade.

    Nada e migrado — o ambiente ja era um `Cliente` comum. E por isso que
    a demonstracao nao foi feita como "modo demo" do sistema.
    """
    from apps.clientes.models import Cliente

    solicitacao = get_object_or_404(SolicitacaoDemonstracao, pk=pk)
    if not solicitacao.cliente_id:
        messages.error(request, "Esta solicitação não gerou ambiente.")
        return redirect("master:comercial_demos")

    Cliente.objects.filter(pk=solicitacao.cliente_id).update(
        eh_demonstracao=False, demo_expira_em=None,
        suspenso=False, motivo_suspensao="", updated_at=timezone.now(),
    )
    solicitacao.status = SolicitacaoDemonstracao.Status.CONVERTIDA
    solicitacao.convertida_em = timezone.now()
    solicitacao.save(update_fields=["status", "convertida_em", "updated_at"])

    _log(request, LogAcessoMaster.Acao.DEMO_CONVERTIDA, solicitacao.cliente,
         "Demonstração convertida em cliente")
    messages.success(
        request,
        f"{solicitacao.empresa} agora é cliente. Confira o plano e a cobrança.",
    )
    return redirect("master:cliente_detalhe", pk=solicitacao.cliente_id)


@master_required
@require_POST
def demonstracao_encerrar(request, pk):
    """Encerra antes do prazo — para abuso ou pedido do proprio interessado."""
    from apps.clientes.models import Cliente

    solicitacao = get_object_or_404(SolicitacaoDemonstracao, pk=pk)
    solicitacao.status = SolicitacaoDemonstracao.Status.CANCELADA
    solicitacao.save(update_fields=["status", "updated_at"])

    if solicitacao.cliente_id:
        Cliente.objects.filter(pk=solicitacao.cliente_id).update(
            suspenso=True, motivo_suspensao="Demonstração encerrada pelo Master",
            updated_at=timezone.now(),
        )

    _log(request, LogAcessoMaster.Acao.DEMO_ENCERRADA, solicitacao.cliente,
         "Demonstração encerrada")
    messages.success(request, "Demonstração encerrada.")
    return redirect("master:comercial_demos")
