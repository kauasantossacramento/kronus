"""
Kronus — assinatura eletrônica do espelho de ponto (Seção 8.5).

    /ponto/espelhos/            espelhos do colaborador, com pendências
    /ponto/espelhos/<pk>/       conferência e assinatura

**O que é a assinatura aqui.** Não é certificado ICP-Brasil: é o aceite
digital previsto na Seção 8.5 — o colaborador declara conferir o
conteúdo, e o sistema grava data/hora, IP e o hash do documento naquele
instante. O valor probatório vem da combinação: o hash prova *qual*
conteúdo foi assinado, e a imutabilidade posterior (regra 4 da Seção 14)
prova que ele não mudou depois.
"""
import calendar
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.decorators import colaborador_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.core.utils import gerar_hash_documento, obter_ip, meses_do_ano, nome_do_mes
from apps.ponto.models import FechamentoMensal

logger = logging.getLogger("kronus.ponto")


def _colaborador(request):
    return getattr(request, "colaborador", None) or getattr(
        request.user, "colaborador", None
    )


@login_required
@colaborador_required
def meus_espelhos(request):
    """Espelhos fechados do colaborador, com destaque para os pendentes."""
    colaborador = _colaborador(request)
    if colaborador is None:
        messages.error(request, "Seu usuário não está vinculado a um colaborador.")
        return redirect("accounts:perfil")

    espelhos = (
        FechamentoMensal.objects.filter(colaborador=colaborador, fechado=True)
        .order_by("-ano", "-mes")
    )

    return render(
        request,
        "ponto/meus_espelhos.html",
        {
            "titulo": "Meus espelhos de ponto",
            "menu_ativo": "espelhos",
            "colaborador": colaborador,
            "espelhos": espelhos,
            "pendentes": [e for e in espelhos if not e.assinado],
            "meses": dict(meses_do_ano()),
        },
    )


@login_required
@colaborador_required
def conferir_espelho(request, pk):
    """Tela de conferência antes da assinatura."""
    colaborador = _colaborador(request)
    espelho = get_object_or_404(
        FechamentoMensal.objects.select_related("colaborador", "empresa"),
        pk=pk,
        colaborador=colaborador,
        fechado=True,
    )

    from apps.relatorios.generators import EspelhoPontoGenerator

    gerador = EspelhoPontoGenerator(colaborador, espelho.ano, espelho.mes)
    contexto = gerador.contexto()

    # Se o conteúdo mudou depois do fechamento, o colaborador precisa
    # saber antes de assinar — assinar um documento divergente do que
    # foi apurado esvaziaria o valor da assinatura.
    divergente = bool(
        espelho.hash_documento and espelho.hash_documento != contexto["hash_documento"]
    )

    return render(
        request,
        "ponto/conferir_espelho.html",
        {
            "titulo": f"Espelho de {espelho.mes:02d}/{espelho.ano}",
            "menu_ativo": "espelhos",
            "espelho": espelho,
            "linhas": contexto["linhas"],
            "totais": contexto["totais"],
            "resumo": contexto["resumo"],
            "codigo_verificacao": contexto["codigo_verificacao"],
            "divergente": divergente,
            "nome_mes": nome_do_mes(espelho.mes),
        },
    )


@login_required
@colaborador_required
@require_POST
def assinar_espelho(request, pk):
    """
    Registra o aceite digital.

    Grava data/hora, IP e um hash que amarra a assinatura ao conteúdo e
    ao signatário. A partir daqui o espelho não pode ser reaberto pelo
    RH (regra 4 da Seção 14).
    """
    colaborador = _colaborador(request)
    espelho = get_object_or_404(
        FechamentoMensal, pk=pk, colaborador=colaborador, fechado=True
    )

    if espelho.assinado:
        messages.info(request, "Este espelho já estava assinado.")
        return redirect("ponto:meus_espelhos")

    if request.POST.get("aceite") != "1":
        messages.error(request, "Marque a confirmação de conferência para assinar.")
        return redirect("ponto:conferir_espelho", pk=pk)

    agora = timezone.now()
    ip = obter_ip(request)

    # A assinatura amarra: documento + signatário + instante + origem.
    # Trocar qualquer um dos quatro produz um hash diferente.
    espelho.assinatura_hash = gerar_hash_documento(
        "|".join([
            espelho.hash_documento or "",
            colaborador.cpf,
            agora.isoformat(),
            ip or "",
        ])
    )
    espelho.assinado = True
    espelho.assinado_em = agora
    espelho.assinatura_ip = ip
    espelho.save(
        update_fields=[
            "assinado", "assinado_em", "assinatura_ip", "assinatura_hash", "updated_at",
        ]
    )

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.SEGURANCA,
        descricao=(
            f"Espelho {espelho.mes:02d}/{espelho.ano} assinado por "
            f"{colaborador.nome_exibicao}"
        ),
        objeto=espelho,
        empresa=espelho.empresa,
        metadados={"hash_documento": espelho.hash_documento},
    )
    messages.success(
        request,
        f"Espelho de {espelho.mes:02d}/{espelho.ano} assinado. "
        "O documento não pode mais ser alterado.",
    )
    return redirect("ponto:meus_espelhos")


@login_required
@colaborador_required
def solicitar_justificativa(request):
    """
    Solicitação de justificativa pelo próprio colaborador (Seção 6.4).

    Nasce pendente: quem decide se abona é o RH.
    """
    from apps.rh.forms_rh import JustificativaColaboradorForm

    colaborador = _colaborador(request)
    if colaborador is None:
        messages.error(request, "Seu usuário não está vinculado a um colaborador.")
        return redirect("accounts:perfil")

    form = JustificativaColaboradorForm(
        request.POST or None,
        request.FILES or None,
        empresa=colaborador.empresa,
    )

    if request.method == "POST" and form.is_valid():
        justificativa = form.save(commit=False)
        justificativa.empresa = colaborador.empresa
        justificativa.colaborador = colaborador
        justificativa.solicitada_por = request.user
        # O colaborador não decide o abono — o RH decide na aprovação.
        justificativa.abona_dia = True
        justificativa.save()

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.CRIACAO,
            descricao=f"Justificativa solicitada para {justificativa.data:%d/%m/%Y}",
            objeto=justificativa,
            empresa=colaborador.empresa,
        )
        messages.success(
            request, "Solicitação enviada. O RH será notificado para avaliação."
        )
        return redirect("ponto:meus_pontos")

    return render(
        request,
        "ponto/solicitar_justificativa.html",
        {
            "titulo": "Solicitar justificativa",
            "menu_ativo": "meus_pontos",
            "form": form,
            "colaborador": colaborador,
        },
    )
