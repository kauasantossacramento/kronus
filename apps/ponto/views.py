"""
Kronus — interface do colaborador (Seções 6.3 e 6.4 do plano).

    /ponto/registrar/            bater ponto pela web, com geolocalização
    /ponto/meus-pontos/          histórico e espelho do mês
    /ponto/comprovante/<uuid>/   comprovante de uma batida (PDF ou HTML)
    /ponto/espelho/<ano>/<mes>/  espelho de ponto do próprio colaborador
"""
import calendar
import json
import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.constants import TipoRegistro
from apps.core.decorators import colaborador_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.ponto import validators
from apps.ponto.models import RegistroPonto
from apps.ponto.services import ConsolidacaoService, RegistroPontoService
from apps.relatorios.generators import (
    ComprovanteGenerator,
    EspelhoPontoGenerator,
    PDFIndisponivel,
)

logger = logging.getLogger("kronus.ponto")

#: Cor do botão por tipo de marcação esperada (Seção 6.3 do plano).
CORES_POR_TIPO = {
    TipoRegistro.ENTRADA: "primaria",
    TipoRegistro.INTERVALO_INICIO: "alerta",
    TipoRegistro.INTERVALO_FIM: "info",
    TipoRegistro.SAIDA: "sucesso",
}

ROTULOS_POR_TIPO = {
    TipoRegistro.ENTRADA: "Registrar entrada",
    TipoRegistro.INTERVALO_INICIO: "Registrar saída para intervalo",
    TipoRegistro.INTERVALO_FIM: "Registrar retorno do intervalo",
    TipoRegistro.SAIDA: "Registrar saída",
}


def _colaborador_da_sessao(request):
    colaborador = getattr(request, "colaborador", None)
    if colaborador is None:
        colaborador = getattr(request.user, "colaborador", None)
    return colaborador


# ══════════════════════════════════════════════════════════════
# Bater ponto
# ══════════════════════════════════════════════════════════════
@login_required
@colaborador_required
def registrar(request):
    """Tela de registro de ponto web (desktop e mobile)."""
    colaborador = _colaborador_da_sessao(request)
    if colaborador is None:
        messages.error(request, "Seu usuário não está vinculado a um colaborador.")
        return redirect("accounts:perfil")

    hoje = timezone.localdate()
    registros = RegistroPontoService.registros_do_dia(colaborador, hoje)
    proximo = RegistroPontoService.proximo_tipo(colaborador, hoje)
    banco_hoje = colaborador.banco_horas.filter(data=hoje).first()

    contexto = {
        "titulo": "Registrar ponto",
        "menu_ativo": "registrar",
        "colaborador": colaborador,
        "empresa": colaborador.empresa,
        "hoje": hoje,
        "registros": registros,
        "proximo_tipo": proximo,
        "proximo_rotulo": ROTULOS_POR_TIPO.get(proximo, "Registrar ponto"),
        "proximo_cor": CORES_POR_TIPO.get(proximo, "primaria"),
        "banco_hoje": banco_hoje,
        "exige_geolocalizacao": colaborador.empresa.geofencing_ativo,
        "geofencing_bloqueia": colaborador.empresa.geofencing_bloqueia,
        "pode_ver_historico": colaborador.empresa.permite_ver_ponto,
    }
    return render(request, "ponto/bater_ponto.html", contexto)


@login_required
@colaborador_required
@require_POST
def registrar_batida(request):
    """
    Recebe a batida via fetch/HTMX e devolve JSON.

    Mantemos a resposta em JSON (e não um redirect) para que a interface
    mostre a confirmação sem recarregar a página — o colaborador costuma
    bater o ponto no celular, muitas vezes com conexão instável.
    """
    colaborador = _colaborador_da_sessao(request)
    if colaborador is None:
        return JsonResponse(
            {"ok": False, "mensagem": "Usuário sem colaborador vinculado."}, status=400
        )

    if not colaborador.permite_ponto_web:
        return JsonResponse(
            {
                "ok": False,
                "codigo": "web_bloqueado",
                "mensagem": "Seu registro deve ser feito no totem da empresa.",
            },
            status=403,
        )

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = request.POST

    def numero(chave):
        valor = payload.get(chave)
        try:
            return float(valor) if valor not in (None, "") else None
        except (TypeError, ValueError):
            return None

    try:
        registro = RegistroPontoService.registrar(
            colaborador=colaborador,
            metodo="web",
            latitude=numero("latitude"),
            longitude=numero("longitude"),
            precisao_gps=numero("precisao"),
            request=request,
        )
    except validators.RegistroInvalido as erro:
        return JsonResponse(
            {
                "ok": False,
                "codigo": erro.codigo,
                "mensagem": erro.mensagem,
                "detalhes": erro.detalhes,
            },
            status=422,
        )

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.PONTO,
        descricao=f"Ponto registrado ({registro.get_tipo_display()}) NSR {registro.nsr}",
        objeto=registro,
        empresa=colaborador.empresa,
    )

    momento = timezone.localtime(registro.data_hora)
    proximo = RegistroPontoService.proximo_tipo(colaborador, momento.date())

    return JsonResponse(
        {
            "ok": True,
            "tipo": registro.tipo,
            "tipo_exibicao": registro.get_tipo_display(),
            "hora": momento.strftime("%H:%M:%S"),
            "data": momento.strftime("%d/%m/%Y"),
            "nsr": registro.nsr,
            "codigo_verificacao": registro.codigo_verificacao,
            "fora_area": registro.fora_area,
            "comprovante_url": f"/ponto/comprovante/{registro.uuid}/",
            "proximo_tipo": proximo,
            "proximo_rotulo": ROTULOS_POR_TIPO.get(proximo, "Registrar ponto"),
            "proximo_cor": CORES_POR_TIPO.get(proximo, "primaria"),
        }
    )


# ══════════════════════════════════════════════════════════════
# Histórico do colaborador
# ══════════════════════════════════════════════════════════════
@login_required
@colaborador_required
def meus_pontos(request):
    """Histórico mensal — visível apenas se `empresa.permite_ver_ponto`."""
    colaborador = _colaborador_da_sessao(request)
    if colaborador is None:
        messages.error(request, "Seu usuário não está vinculado a um colaborador.")
        return redirect("accounts:perfil")

    if not colaborador.empresa.permite_ver_ponto:
        messages.warning(
            request, "Sua empresa não habilitou a consulta dos próprios registros."
        )
        return redirect("ponto:registrar")

    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get("ano", hoje.year))
        mes = int(request.GET.get("mes", hoje.month))
        date(ano, mes, 1)
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month

    gerador = EspelhoPontoGenerator(colaborador, ano, mes)
    contexto_espelho = gerador.contexto()

    contexto = {
        "titulo": "Meus registros",
        "menu_ativo": "meus_pontos",
        "colaborador": colaborador,
        "ano": ano,
        "mes": mes,
        "nome_mes": calendar.month_name[mes],
        "linhas": contexto_espelho["linhas"],
        "resumo": contexto_espelho["resumo"],
        "totais": contexto_espelho["totais"],
        "codigo_verificacao": contexto_espelho["codigo_verificacao"],
        "meses": [(i, calendar.month_name[i]) for i in range(1, 13)],
        "anos": range(hoje.year - 3, hoje.year + 1),
    }
    return render(request, "ponto/meus_pontos.html", contexto)


# ══════════════════════════════════════════════════════════════
# Documentos
# ══════════════════════════════════════════════════════════════
def _responder_documento(request, gerador, nome_arquivo: str, contexto_extra=None):
    """
    Entrega o PDF quando o ambiente suporta; caso contrário, devolve o
    HTML equivalente com um aviso. Assim o desenvolvimento no Windows
    (sem GTK) segue possível sem mascarar a limitação.
    """
    try:
        pdf = gerador.render_pdf()
    except PDFIndisponivel as erro:
        logger.warning("PDF indisponível: %s", erro)
        resposta = HttpResponse(gerador.render_html())
        resposta["X-Kronus-PDF"] = "indisponivel"
        return resposta

    resposta = HttpResponse(pdf, content_type="application/pdf")
    resposta["Content-Disposition"] = f'inline; filename="{nome_arquivo}"'
    return resposta


@login_required
def comprovante(request, uuid):
    """
    Comprovante de uma batida (Portaria 671).

    O colaborador vê apenas os próprios comprovantes; o RH vê os das
    empresas sob seu escopo.
    """
    from apps.core.mixins import escopo_empresas
    from apps.core.permissions import eh_colaborador

    registro = get_object_or_404(
        RegistroPonto.objects.select_related("colaborador", "empresa", "totem"),
        uuid=uuid,
    )

    if eh_colaborador(request.user):
        colaborador = _colaborador_da_sessao(request)
        if colaborador is None or registro.colaborador_id != colaborador.pk:
            return render(request, "errors/403.html", status=403)
    elif not escopo_empresas(request.user).filter(pk=registro.empresa_id).exists():
        return render(request, "errors/403.html", status=403)

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.DOWNLOAD,
        descricao=f"Comprovante do NSR {registro.nsr}",
        objeto=registro,
        empresa=registro.empresa,
    )

    gerador = ComprovanteGenerator(registro)
    return _responder_documento(request, gerador, gerador.nome_arquivo())


@login_required
def espelho(request, ano, mes, colaborador_id=None):
    """
    Espelho de ponto mensal em PDF.

    Sem `colaborador_id`, entrega o espelho do próprio usuário.
    """
    from apps.core.mixins import escopo_empresas
    from apps.core.permissions import eh_colaborador
    from apps.rh.models import Colaborador

    if colaborador_id is None:
        colaborador = _colaborador_da_sessao(request)
        if colaborador is None:
            return render(request, "errors/403.html", status=403)
    else:
        colaborador = get_object_or_404(
            Colaborador.objects.select_related("empresa"), pk=colaborador_id
        )
        if eh_colaborador(request.user):
            proprio = _colaborador_da_sessao(request)
            if proprio is None or proprio.pk != colaborador.pk:
                return render(request, "errors/403.html", status=403)
        elif not escopo_empresas(request.user).filter(pk=colaborador.empresa_id).exists():
            return render(request, "errors/403.html", status=403)

    try:
        ano, mes = int(ano), int(mes)
        date(ano, mes, 1)
    except (TypeError, ValueError):
        return render(request, "errors/404.html", status=404)

    # Garante que o período está consolidado antes de emitir o documento.
    gerador = EspelhoPontoGenerator(colaborador, ano, mes)
    ConsolidacaoService.consolidar_periodo(
        colaborador, gerador.data_inicio, min(gerador.data_fim, timezone.localdate())
    )

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.DOWNLOAD,
        descricao=f"Espelho de ponto {mes:02d}/{ano} de {colaborador.nome_exibicao}",
        objeto=colaborador,
        empresa=colaborador.empresa,
    )

    return _responder_documento(request, gerador, gerador.nome_arquivo())
