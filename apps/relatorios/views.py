"""
Kronus — relatórios e exportações fiscais (Fase 4).

    /relatorios/fiscais/        tela de geração de AFD e AEJ
    /relatorios/afd/            download do AFD
    /relatorios/aej/            download do AEJ
    /relatorios/gerenciais/     horas extras, atrasos e faltas
    /relatorios/contador/       portal do contador (somente leitura)

O AFD e o AEJ são o que a fiscalização do trabalho pede. Por isso todo
download passa pela trilha de auditoria: numa inspeção, saber quem
gerou o arquivo e quando faz parte da defesa.
"""
import csv
import logging
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.constants import StatusDia, TipoUsuario
from apps.core.decorators import empresa_ativa_required, rh_required, tipos_permitidos
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.ponto.models import BancoHoras
from apps.relatorios.aej import AEJGenerator
from apps.relatorios.afd import AFDGenerator
from apps.rh.models import Colaborador, Departamento

logger = logging.getLogger("kronus.relatorios")


def _periodo(request, dias_padrao=30):
    hoje = timezone.localdate()
    try:
        inicio = date.fromisoformat(
            request.GET.get("inicio") or (hoje - timedelta(days=dias_padrao)).isoformat()
        )
        fim = date.fromisoformat(request.GET.get("fim") or hoje.isoformat())
    except ValueError:
        inicio, fim = hoje - timedelta(days=dias_padrao), hoje
    return (fim, inicio) if fim < inicio else (inicio, fim)


# ══════════════════════════════════════════════════════════════
# Arquivos fiscais — AFD e AEJ
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def fiscais(request):
    """
    Tela de geração dos arquivos exigidos pela Portaria 671.

    Mostra a **pré-verificação** antes do download: continuidade do NSR,
    contagem de registros e tamanho do arquivo. Descobrir uma lacuna de
    NSR aqui é muito melhor do que descobrir na frente do auditor.
    """
    empresa = request.empresa_ativa
    inicio, fim = _periodo(request)

    afd = AFDGenerator(empresa, inicio, fim)
    aej = AEJGenerator(empresa, inicio, fim)

    try:
        verificacao_afd = afd.verificar()
    except Exception as erro:
        logger.exception("Falha ao verificar o AFD")
        verificacao_afd = {"valido": False, "problemas": [str(erro)], "marcacoes": 0}

    try:
        verificacao_aej = aej.verificar()
    except Exception as erro:
        logger.exception("Falha ao verificar o AEJ")
        verificacao_aej = {"valido": False, "problemas": [str(erro)], "dias": 0}

    return render(
        request,
        "relatorios/fiscais.html",
        {
            "titulo": "Arquivos fiscais",
            "menu_ativo": "relatorios",
            "inicio": inicio,
            "fim": fim,
            "afd": verificacao_afd,
            "aej": verificacao_aej,
            "nome_afd": afd.nome_arquivo(),
            "nome_aej": aej.nome_arquivo(),
        },
    )


def _entregar_txt(conteudo: bytes, nome: str) -> HttpResponse:
    resposta = HttpResponse(conteudo, content_type="text/plain; charset=iso-8859-1")
    resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resposta


@rh_required
@empresa_ativa_required
def baixar_afd(request):
    empresa = request.empresa_ativa
    inicio, fim = _periodo(request)
    gerador = AFDGenerator(empresa, inicio, fim)

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.DOWNLOAD,
        descricao=f"AFD gerado — {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}",
        objeto=empresa,
        empresa=empresa,
        metadados={"tipo": "afd", "inicio": inicio.isoformat(), "fim": fim.isoformat()},
    )
    return _entregar_txt(gerador.gerar_bytes(), gerador.nome_arquivo())


@rh_required
@empresa_ativa_required
def baixar_aej(request):
    empresa = request.empresa_ativa
    inicio, fim = _periodo(request)
    gerador = AEJGenerator(empresa, inicio, fim)

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.DOWNLOAD,
        descricao=f"AEJ gerado — {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}",
        objeto=empresa,
        empresa=empresa,
        metadados={"tipo": "aej", "inicio": inicio.isoformat(), "fim": fim.isoformat()},
    )
    return _entregar_txt(gerador.gerar_bytes(), gerador.nome_arquivo())


# ══════════════════════════════════════════════════════════════
# Relatórios gerenciais
# ══════════════════════════════════════════════════════════════
def _agregar(empresa, inicio, fim, departamento=None):
    """Agrega o banco de horas por colaborador no período."""
    colaboradores = Colaborador.objects.filter(empresa=empresa, ativo=True)
    if departamento:
        colaboradores = colaboradores.filter(departamento_id=departamento)

    linhas = []
    for colaborador in colaboradores.select_related("departamento", "cargo_ref"):
        totais = BancoHoras.objects.filter(
            colaborador=colaborador, data__gte=inicio, data__lte=fim
        ).aggregate(
            trabalhado=Sum("minutos_trabalhados"),
            previsto=Sum("minutos_esperados"),
            extras=Sum("minutos_extras"),
            noturnas=Sum("minutos_noturnos"),
            atraso=Sum("minutos_atraso"),
            antecipada=Sum("minutos_saida_antecipada"),
            saldo=Sum("saldo_dia"),
            faltas=Count("pk", filter=Q(status=StatusDia.FALTA)),
            atestados=Count("pk", filter=Q(status=StatusDia.ATESTADO)),
            incompletos=Count("pk", filter=Q(status=StatusDia.INCOMPLETO)),
            dias_com_atraso=Count("pk", filter=Q(minutos_atraso__gt=0)),
        )
        linhas.append(
            {
                "colaborador": colaborador,
                **{chave: (valor or 0) for chave, valor in totais.items()},
            }
        )
    return linhas


@rh_required
@empresa_ativa_required
def gerenciais(request):
    """
    Horas extras, atrasos e faltas — Seção 8.8 do plano.

    O custo estimado de hora extra usa o salário do cargo cadastrado.
    Sem salário, o custo fica em branco em vez de zero: zero seria lido
    como "não custou nada", o que é diferente de "não sei".
    """
    empresa = request.empresa_ativa
    inicio, fim = _periodo(request)
    departamento = request.GET.get("departamento") or None
    aba = request.GET.get("aba", "extras")

    linhas = _agregar(empresa, inicio, fim, departamento)
    config = empresa.configuracao

    for linha in linhas:
        cargo = linha["colaborador"].cargo_ref
        salario = cargo.salario_base if cargo and cargo.salario_base else None
        if salario and linha["extras"]:
            # Hora normal = salário / carga mensal (220h padrão CLT).
            valor_hora = float(salario) / 220
            acrescimo = 1 + config.hora_extra_percentual / 100
            linha["custo_extras"] = round(
                linha["extras"] / 60 * valor_hora * acrescimo, 2
            )
        else:
            linha["custo_extras"] = None

    ordens = {
        "extras": lambda x: -x["extras"],
        "atrasos": lambda x: -x["atraso"],
        "faltas": lambda x: -x["faltas"],
        "saldo": lambda x: x["saldo"],
    }
    linhas.sort(key=ordens.get(aba, ordens["extras"]))

    total_custo = sum(l["custo_extras"] or 0 for l in linhas)

    return render(
        request,
        "relatorios/gerenciais.html",
        {
            "titulo": "Relatórios gerenciais",
            "menu_ativo": "relatorios",
            "inicio": inicio,
            "fim": fim,
            "aba": aba,
            "linhas": linhas,
            "departamentos": Departamento.objects.filter(empresa=empresa, ativo=True),
            "departamento_selecionado": departamento,
            "totais": {
                "extras": sum(l["extras"] for l in linhas),
                "atraso": sum(l["atraso"] for l in linhas),
                "faltas": sum(l["faltas"] for l in linhas),
                "noturnas": sum(l["noturnas"] for l in linhas),
                "custo": total_custo,
            },
        },
    )


@rh_required
@empresa_ativa_required
def exportar_csv(request):
    """Exportação do relatório gerencial para planilha."""
    empresa = request.empresa_ativa
    inicio, fim = _periodo(request)
    linhas = _agregar(empresa, inicio, fim, request.GET.get("departamento") or None)

    resposta = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    resposta["Content-Disposition"] = (
        f'attachment; filename="relatorio_{inicio:%Y%m%d}_{fim:%Y%m%d}.csv"'
    )
    # BOM para o Excel abrir com acentos corretos.
    resposta.write("﻿")

    escritor = csv.writer(resposta, delimiter=";")
    escritor.writerow([
        "CPF", "Nome", "Departamento", "Cargo",
        "Minutos trabalhados", "Minutos previstos", "Minutos extras",
        "Minutos noturnos", "Minutos de atraso", "Saldo (min)",
        "Faltas", "Atestados", "Dias incompletos",
    ])
    for linha in linhas:
        colaborador = linha["colaborador"]
        escritor.writerow([
            colaborador.cpf_formatado,
            colaborador.nome_exibicao,
            colaborador.departamento or "",
            colaborador.cargo or "",
            linha["trabalhado"], linha["previsto"], linha["extras"],
            linha["noturnas"], linha["atraso"], linha["saldo"],
            linha["faltas"], linha["atestados"], linha["incompletos"],
        ])

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.DOWNLOAD,
        descricao=f"Relatório gerencial exportado — {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}",
        empresa=empresa,
    )
    return resposta


# ══════════════════════════════════════════════════════════════
# Portal do contador
# ══════════════════════════════════════════════════════════════
@tipos_permitidos(TipoUsuario.CONTADOR, TipoUsuario.CLIENTE, TipoUsuario.RH)
def portal_contador(request):
    """
    Acesso somente leitura para o escritório de contabilidade
    (Seção 8.8 do plano).

    O contador vê os arquivos fiscais e o resumo do período — não edita
    marcação, não aprova atestado, não altera configuração.
    """
    from apps.core.mixins import escopo_empresas

    empresas = escopo_empresas(request.user)
    empresa = request.empresa_ativa or empresas.first()

    if empresa is None:
        return render(
            request,
            "relatorios/portal_contador.html",
            {"titulo": "Portal do contador", "sem_empresa": True},
        )

    inicio, fim = _periodo(request)
    linhas = _agregar(empresa, inicio, fim)

    return render(
        request,
        "relatorios/portal_contador.html",
        {
            "titulo": "Portal do contador",
            "empresa": empresa,
            "empresas": empresas,
            "inicio": inicio,
            "fim": fim,
            "linhas": linhas,
            "totais": {
                "trabalhado": sum(l["trabalhado"] for l in linhas),
                "extras": sum(l["extras"] for l in linhas),
                "noturnas": sum(l["noturnas"] for l in linhas),
                "faltas": sum(l["faltas"] for l in linhas),
            },
        },
    )
