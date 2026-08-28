"""
Kronus — configurações da empresa e personalização (Fase 4).

    /rh/configuracoes/                parâmetros de jornada e cálculo
    /rh/configuracoes/personalizacao/ logo, cores e tela do totem
    /rh/configuracoes/notificacoes/   quais avisos enviar
    /rh/configuracoes/integracao/     chaves de API

Alterar a tolerância ou o adicional noturno muda o **cálculo** de todos
os dias em aberto. Por isso a tela avisa e oferece o reprocessamento do
mês corrente — mudar o parâmetro sem recalcular deixaria o painel
mostrando números apurados por uma regra que já não vale.
"""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.api.models import APIKey
from apps.clientes.forms import (
    ConfiguracaoEmpresaForm,
    OperacaoEmpresaForm,
    PersonalizacaoEmpresaForm,
)
from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.ponto.services import ConsolidacaoService
from apps.rh.models import Colaborador

logger = logging.getLogger("kronus.rh")

#: Campos cuja alteração muda o resultado do cálculo de jornada.
CAMPOS_QUE_AFETAM_CALCULO = {
    "tolerancia_atraso_min",
    "intervalo_minimo_min",
    "jornada_diaria_padrao_min",
    "hora_extra_percentual",
    "hora_extra_percentual_2",
    "limite_hora_extra_diaria_min",
    "adicional_noturno",
    "hora_ini_noturno",
    "hora_fim_noturno",
    "hora_noturna_reduzida",
    "modo_compensacao",
}


@rh_required
@empresa_ativa_required
def configuracoes(request):
    """Parâmetros de jornada, horas extras, adicional noturno e banco."""
    empresa = request.empresa_ativa
    config = empresa.configuracao

    form_config = ConfiguracaoEmpresaForm(request.POST or None, instance=config)
    form_operacao = OperacaoEmpresaForm(request.POST or None, instance=empresa)

    if request.method == "POST":
        if form_config.is_valid() and form_operacao.is_valid():
            alterados = set(form_config.changed_data) | set(form_operacao.changed_data)
            form_config.save()
            form_operacao.save()

            registrar_log(
                request=request,
                acao=LogAcesso.Acao.CONFIG,
                descricao=(
                    f"Configurações alteradas: {', '.join(sorted(alterados)) or 'nenhuma'}"
                ),
                objeto=empresa,
            )

            afeta_calculo = alterados & CAMPOS_QUE_AFETAM_CALCULO
            if afeta_calculo:
                messages.warning(
                    request,
                    "Você alterou parâmetros que mudam o cálculo de jornada "
                    f"({', '.join(sorted(afeta_calculo))}). Os dias já apurados "
                    "seguem com o cálculo antigo até serem reprocessados.",
                )
            else:
                messages.success(request, "Configurações salvas.")
            return redirect("rh:configuracoes")
        messages.error(request, "Corrija os campos destacados.")

    return render(
        request,
        "rh/configuracoes/empresa.html",
        {
            "titulo": "Configurações da empresa",
            "menu_ativo": "configuracoes",
            "form_config": form_config,
            "form_operacao": form_operacao,
            "empresa": empresa,
        },
    )


@rh_required
@empresa_ativa_required
def reprocessar_mes(request):
    """Recalcula o mês corrente após mudança de parâmetro."""
    if request.method != "POST":
        return redirect("rh:configuracoes")

    empresa = request.empresa_ativa
    hoje = timezone.localdate()
    inicio = hoje.replace(day=1)

    total = 0
    for colaborador in Colaborador.objects.filter(empresa=empresa, ativo=True):
        ConsolidacaoService.consolidar_periodo(colaborador, inicio, hoje)
        total += 1

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=f"Mês corrente reprocessado para {total} colaborador(es)",
        objeto=empresa,
    )
    messages.success(
        request,
        f"{total} colaborador(es) reprocessado(s) de {inicio:%d/%m} a {hoje:%d/%m}. "
        "Dias já fechados não foram alterados.",
    )
    return redirect("rh:configuracoes")


@rh_required
@empresa_ativa_required
def personalizacao(request):
    """
    White-label parcial (Seção 3.6): logo, cores e tela do totem.

    A marca Kronus e a assinatura KS TEC não são customizáveis — a tela
    deixa isso explícito para evitar a expectativa errada.
    """
    empresa = request.empresa_ativa
    form = PersonalizacaoEmpresaForm(
        request.POST or None, request.FILES or None, instance=empresa
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.CONFIG,
            descricao=f"Personalização visual alterada: {', '.join(form.changed_data)}",
            objeto=empresa,
        )
        # Avisa os totens da empresa para recarregarem a configuração.
        _avisar_totens(empresa)
        messages.success(request, "Personalização salva. Os totens serão atualizados.")
        return redirect("rh:personalizacao")

    return render(
        request,
        "rh/configuracoes/personalizacao.html",
        {
            "titulo": "Personalização",
            "menu_ativo": "configuracoes",
            "form": form,
            "empresa": empresa,
            "totens": empresa.totens.filter(ativo=True),
        },
    )


def _avisar_totens(empresa):
    """Publica 'config alterada' no canal WebSocket de cada totem."""
    from apps.totem.consumers import comandar_totem

    for totem in empresa.totens.filter(ativo=True):
        comandar_totem(totem, "totem.config_alterada")


@rh_required
@empresa_ativa_required
def notificacoes(request):
    """Quais eventos geram aviso e para qual e-mail (Seção 8.7)."""
    empresa = request.empresa_ativa
    config = empresa.configuracao

    campos = [
        ("notif_esq_ponto", "Esquecimento de ponto", "Avisa o colaborador que não registrou a jornada completa."),
        ("notif_banco_negativo", "Banco de horas negativo", "Avisa RH e colaborador quando o saldo fica abaixo de -2h."),
        ("notif_comprovante_email", "Comprovante por e-mail", "Envia o comprovante ao colaborador a cada batida."),
        ("notif_totem_offline", "Totem offline", "Avisa quando um equipamento passa de 10 min sem sinal."),
    ]

    if request.method == "POST":
        for campo, _rotulo, _ajuda in campos:
            setattr(config, campo, request.POST.get(campo) == "on")
        config.email_notificacoes = (request.POST.get("email_notificacoes") or "").strip()
        config.save()

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.CONFIG,
            descricao="Preferências de notificação alteradas",
            objeto=empresa,
        )
        messages.success(request, "Preferências de notificação salvas.")
        return redirect("rh:notificacoes_config")

    return render(
        request,
        "rh/configuracoes/notificacoes.html",
        {
            "titulo": "Notificações",
            "menu_ativo": "configuracoes",
            "config": config,
            "campos": [
                {"nome": c, "rotulo": r, "ajuda": a, "ativo": getattr(config, c)}
                for c, r, a in campos
            ],
        },
    )


@rh_required
@empresa_ativa_required
def integracao(request):
    """
    Chaves de API da empresa (Seção 7.4).

    A chave em texto plano aparece **uma única vez**, no momento da
    emissão. Depois só o hash permanece — se o cliente perder, emite
    outra; não há como recuperar.
    """
    empresa = request.empresa_ativa
    chaves = APIKey.objects.filter(empresa=empresa).order_by("-created_at")
    chave_nova = None

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "emitir":
            nome = (request.POST.get("nome") or "").strip()
            if not nome:
                messages.error(request, "Dê um nome à integração.")
                return redirect("rh:integracao")

            if not empresa.cliente.plano.tem_api:
                messages.error(
                    request,
                    f"O plano {empresa.cliente.plano} não inclui acesso à API. "
                    "Fale com a KS TEC para contratar.",
                )
                return redirect("rh:integracao")

            _, chave_nova = APIKey.emitir(
                empresa=empresa,
                nome=nome,
                criada_por=request.user,
                somente_leitura=request.POST.get("somente_leitura") == "on",
                rate_limit_hora=empresa.cliente.plano.rate_limit_api_hora,
            )
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.SEGURANCA,
                descricao=f"Chave de API emitida: {nome}",
                objeto=empresa,
            )
            messages.success(
                request,
                "Chave emitida. Copie agora — ela não será exibida novamente.",
            )
            chaves = APIKey.objects.filter(empresa=empresa).order_by("-created_at")

        elif acao == "revogar":
            chave = get_object_or_404(
                APIKey, pk=request.POST.get("chave"), empresa=empresa
            )
            chave.revogar()
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.SEGURANCA,
                descricao=f"Chave de API revogada: {chave.nome}",
                objeto=empresa,
            )
            messages.warning(request, f"Chave '{chave.nome}' revogada.")
            return redirect("rh:integracao")

    return render(
        request,
        "rh/configuracoes/integracao.html",
        {
            "titulo": "Integrações",
            "menu_ativo": "configuracoes",
            "empresa": empresa,
            "chaves": chaves,
            "chave_nova": chave_nova,
            "plano_tem_api": empresa.cliente.plano.tem_api,
        },
    )
