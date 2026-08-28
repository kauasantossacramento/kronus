"""
Kronus — importação e exportação de dados do RH (Fase 6).

    /rh/dados/importar/          colaboradores por planilha, com conferência
    /rh/dados/importar/modelo/   baixa a planilha-modelo
    /rh/dados/folha/             exportação para o sistema de folha
    /rh/dados/folha/baixar/      download do arquivo

**A conferência é uma tela, não um passo opcional.** O importador roda
duas vezes: uma para validar e mostrar o laudo, outra para gravar. O RH
vê exatamente o que será criado e o que será recusado — com o motivo de
cada recusa — antes de qualquer escrita no banco.
"""
import logging
from datetime import date

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log

logger = logging.getLogger("kronus.rh")

#: Chave de sessão onde o CSV conferido espera a confirmação. Guardamos
#: o conteúdo, não o arquivo: o upload já terminou, e pedir o arquivo de
#: novo na confirmação faria o RH reanexar.
SESSAO_IMPORTACAO = "kronus_importacao_csv"


def _periodo(request):
    """Período pedido, ou o mês corrente."""
    hoje = timezone.localdate()
    try:
        inicio = date.fromisoformat(request.GET.get("data_inicio", ""))
    except ValueError:
        inicio = hoje.replace(day=1)
    try:
        fim = date.fromisoformat(request.GET.get("data_fim", ""))
    except ValueError:
        fim = hoje
    if inicio > fim:
        inicio, fim = fim, inicio
    return inicio, fim


# ══════════════════════════════════════════════════════════════
# Importação de colaboradores
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def importar_colaboradores(request):
    """Upload, conferência e confirmação — nesta ordem, sempre."""
    from apps.rh.importacao import ImportadorColaboradores

    empresa = request.empresa_ativa
    laudo = None

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "conferir":
            arquivo = request.FILES.get("planilha")
            if arquivo is None:
                messages.error(request, "Selecione a planilha.")
                return redirect("rh:importar_colaboradores")

            if arquivo.size > 5 * 1024 * 1024:
                messages.error(
                    request, "Arquivo acima de 5 MB. Divida a planilha em partes."
                )
                return redirect("rh:importar_colaboradores")

            conteudo = arquivo.read()
            laudo = ImportadorColaboradores(empresa, conteudo, request.user).conferir()
            # Guarda para a confirmação. `latin-1` é reversível byte a
            # byte, então o conteúdo volta intacto qualquer que seja a
            # codificação original.
            request.session[SESSAO_IMPORTACAO] = conteudo.decode(
                "latin-1", errors="replace"
            )

        elif acao == "confirmar":
            guardado = request.session.get(SESSAO_IMPORTACAO)
            if not guardado:
                messages.error(
                    request, "A conferência expirou. Envie a planilha novamente."
                )
                return redirect("rh:importar_colaboradores")

            importador = ImportadorColaboradores(
                empresa, guardado.encode("latin-1"), request.user
            )
            laudo = importador.importar()
            request.session.pop(SESSAO_IMPORTACAO, None)

            registrar_log(
                request=request,
                acao=LogAcesso.Acao.CRIACAO,
                descricao=(
                    f"Importação de colaboradores: {laudo.criados} criados, "
                    f"{len(laudo.invalidas)} recusados."
                ),
                empresa=empresa,
                metadados={
                    "criados": laudo.criados,
                    "recusados": len(laudo.invalidas),
                },
            )
            if laudo.criados:
                messages.success(
                    request,
                    f"{laudo.criados} colaborador(es) importado(s).",
                )
            if laudo.invalidas:
                messages.warning(
                    request,
                    f"{len(laudo.invalidas)} linha(s) recusada(s) — veja o laudo.",
                )

    return render(
        request,
        "rh/dados/importar.html",
        {
            "titulo": "Importar colaboradores",
            "menu_ativo": "colaboradores",
            "empresa": empresa,
            "laudo": laudo,
        },
    )


@rh_required
@empresa_ativa_required
def modelo_importacao(request):
    """Planilha-modelo, com uma linha de exemplo preenchida."""
    from apps.rh.importacao import modelo_csv

    resposta = HttpResponse(
        modelo_csv().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
    )
    resposta["Content-Disposition"] = (
        'attachment; filename="modelo_colaboradores_kronus.csv"'
    )
    return resposta


# ══════════════════════════════════════════════════════════════
# Exportação para folha
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def exportar_folha(request):
    """
    Tela de exportação, com prévia dos totais.

    A prévia existe para o RH conferir **antes** de mandar para a folha:
    um total de horas extras absurdo é sinal de apuração incompleta, e
    descobrir isso depois do fechamento da folha custa caro.
    """
    from apps.relatorios.folha import LAYOUTS, FolhaExporter

    empresa = request.empresa_ativa
    inicio, fim = _periodo(request)
    layout = request.GET.get("layout", "generico")
    if layout not in LAYOUTS:
        layout = "generico"

    exportador = FolhaExporter(empresa, inicio, fim, layout=layout)
    try:
        resumo = exportador.resumo()
        amostra = exportador.gerar().splitlines()[:6]
        erro = None
    except Exception as falha:
        logger.exception("Falha ao pré-visualizar exportação de folha.")
        resumo, amostra, erro = None, [], str(falha)

    return render(
        request,
        "rh/dados/folha.html",
        {
            "titulo": "Exportar para folha",
            "menu_ativo": "relatorios",
            "empresa": empresa,
            "data_inicio": inicio,
            "data_fim": fim,
            "layout": layout,
            "layouts": [
                {"chave": chave, **{k: v for k, v in dados.items() if k != "colunas"}}
                for chave, dados in LAYOUTS.items()
            ],
            "layout_atual": LAYOUTS[layout],
            "resumo": resumo,
            "amostra": amostra,
            "erro": erro,
        },
    )


@rh_required
@empresa_ativa_required
def baixar_folha(request):
    """Download do arquivo de folha."""
    from apps.relatorios.folha import LAYOUTS, FolhaExporter

    empresa = request.empresa_ativa
    inicio, fim = _periodo(request)
    layout = request.GET.get("layout", "generico")
    if layout not in LAYOUTS:
        messages.error(request, "Layout de folha desconhecido.")
        return redirect("rh:exportar_folha")

    exportador = FolhaExporter(empresa, inicio, fim, layout=layout)
    conteudo = exportador.gerar_bytes()

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.DOWNLOAD,
        descricao=(
            f"Exportação para folha ({layout}) de {inicio:%d/%m/%Y} a "
            f"{fim:%d/%m/%Y}."
        ),
        empresa=empresa,
        metadados={"layout": layout, "bytes": len(conteudo)},
    )

    resposta = HttpResponse(conteudo, content_type=exportador.content_type())
    resposta["Content-Disposition"] = (
        f'attachment; filename="{exportador.nome_arquivo()}"'
    )
    # Mesmo aviso do AFD: o layout foi montado a partir de documentação
    # pública e não foi validado contra um arquivo aceito em produção.
    resposta["X-Kronus-Layout"] = "nao-validado-em-homologacao"
    return resposta


# ══════════════════════════════════════════════════════════════
# Equipamentos (visão do RH)
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def equipamentos(request):
    """
    Os totens da empresa, **somente leitura**.

    O RH precisa saber se o equipamento da portaria está online — é ele
    que atende o telefone quando o colaborador não consegue bater ponto.
    O que ele não faz aqui é cadastrar, mover ou dar baixa: o totem é
    propriedade da KS TEC em comodato, e emitir equipamento pelo painel
    do cliente permitiria furar o limite do plano por dentro.
    """
    from apps.ponto.models import RegistroPonto
    from apps.totem.models import EventoTotem, Totem

    empresa = request.empresa_ativa
    totens = (
        Totem.objects.filter(empresa=empresa)
        .select_related("grupo")
        .order_by("-ativo", "identificador")
    )
    hoje = timezone.localdate()

    fichas = []
    for totem in totens:
        fichas.append({
            "totem": totem,
            "registros_hoje": RegistroPonto.objects.filter(
                totem=totem, data_hora__date=hoje
            ).count(),
            "ultimo_evento": EventoTotem.objects.filter(totem=totem)
            .order_by("-created_at")
            .first(),
        })

    return render(
        request,
        "rh/dados/equipamentos.html",
        {
            "titulo": "Equipamentos",
            "menu_ativo": "equipamentos",
            "empresa": empresa,
            "fichas": fichas,
            "offline": [f for f in fichas if f["totem"].ativo and not f["totem"].online],
        },
    )
