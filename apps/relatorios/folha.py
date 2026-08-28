"""
Kronus — exportação da apuração para sistemas de folha de pagamento.

O RH apura no Kronus, mas quem paga é a folha. Sem esta ponte o
resultado do mês seria redigitado à mão — e é exatamente aí que o erro
de digitação vira erro de pagamento, reclamação trabalhista e retrabalho.

**Layouts declarativos.** Cada folha tem o seu formato, e nenhum deles é
negociável do nosso lado. Em vez de um `if` por sistema espalhado pelo
código, cada layout é uma lista de `ColunaFolha` — nome, largura,
extrator e alinhamento. Adicionar um sistema novo é acrescentar uma
entrada em `LAYOUTS`, não mexer no gerador.

    LAYOUTS["dominio"]    Domínio Sistemas — posicional, .txt
    LAYOUTS["generico"]   CSV com cabeçalho, para importadores flexíveis
    LAYOUTS["totvs"]      TOTVS RM/Protheus — CSV delimitado por ;

**ATENÇÃO — CONFORMIDADE DE LAYOUT.** As larguras e os códigos de
evento aqui foram montados a partir da documentação pública de cada
sistema e **não foram conferidos contra um arquivo real aceito em
produção**. Antes do primeiro fechamento valendo, exporte um mês de
teste e peça ao contador para importar num ambiente de homologação. O
gerador foi escrito declarativamente justamente para que a correção,
quando vier, seja de uma linha por campo.

**O que é exportado.** Totais do período por colaborador, em **minutos e
em horas decimais**. A folha calcula em horas decimais (1h30 = 1,50),
não em HH:MM — entregar só o HH:MM obrigaria cada importador a
reconverter, e é onde o arredondamento diverge.
"""
import csv
import io
import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

logger = logging.getLogger("kronus.relatorios")


def minutos_para_decimal(minutos: int) -> Decimal:
    """
    Converte minutos em horas decimais, com 2 casas.

    Arredondamento **HALF_UP**, não o bancário do Python: a folha
    brasileira arredonda meio para cima, e divergir por um centavo de
    hora num total mensal gera diferença de pagamento que o RH terá de
    justificar.
    """
    return (Decimal(minutos) / Decimal(60)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


@dataclass(frozen=True)
class ColunaFolha:
    """Uma coluna do arquivo de folha."""

    nome: str
    extrator: Callable
    tamanho: int = 0          # 0 = livre (formatos delimitados)
    alinhamento: str = "esquerda"
    preenchimento: str = " "

    def valor(self, linha) -> str:
        bruto = self.extrator(linha)
        return "" if bruto is None else str(bruto)

    def formatar(self, linha) -> str:
        """Aplica largura fixa. Trunca com log, em vez de estourar a coluna."""
        texto = self.valor(linha)
        if not self.tamanho:
            return texto

        if len(texto) > self.tamanho:
            logger.warning(
                "Campo '%s' truncado de %s para %s caracteres: %r",
                self.nome, len(texto), self.tamanho, texto,
            )
            texto = texto[: self.tamanho]

        if self.alinhamento == "direita":
            return texto.rjust(self.tamanho, self.preenchimento)
        return texto.ljust(self.tamanho, self.preenchimento)


# ══════════════════════════════════════════════════════════════
# Extratores
# ══════════════════════════════════════════════════════════════
def _dec(campo):
    """Horas decimais com vírgula — separador que a folha brasileira espera."""
    return lambda linha: str(minutos_para_decimal(linha[campo])).replace(".", ",")


def _dec_ponto(campo):
    """Horas decimais com ponto, para importadores que esperam formato ISO."""
    return lambda linha: str(minutos_para_decimal(linha[campo]))


def _int(campo):
    return lambda linha: str(linha[campo])


def _num_fixo(campo, casas=2):
    """Numérico posicional: sem separador, zeros à esquerda, casas implícitas."""

    def extrair(linha):
        valor = minutos_para_decimal(linha[campo])
        return str(int(valor * (10**casas)))

    return extrair


def _txt(campo):
    return lambda linha: linha[campo]


# ══════════════════════════════════════════════════════════════
# Layouts
# ══════════════════════════════════════════════════════════════
LAYOUTS: dict[str, dict] = {
    "generico": {
        "rotulo": "CSV genérico (com cabeçalho)",
        "extensao": "csv",
        "formato": "csv",
        "delimitador": ";",
        "codificacao": "utf-8-sig",   # BOM: o Excel brasileiro precisa dele
        "descricao": (
            "Uma linha por colaborador, com todos os totais do período em "
            "minutos e em horas decimais. Serve para importadores flexíveis "
            "e para conferência em planilha."
        ),
        "colunas": [
            ColunaFolha("matricula", _txt("matricula")),
            ColunaFolha("cpf", _txt("cpf")),
            ColunaFolha("nome", _txt("nome")),
            ColunaFolha("admissao", lambda l: l["admissao"].strftime("%d/%m/%Y") if l["admissao"] else ""),
            ColunaFolha("dias_trabalhados", _int("dias_trabalhados")),
            ColunaFolha("horas_trabalhadas", _dec("minutos_trabalhados")),
            ColunaFolha("horas_previstas", _dec("minutos_esperados")),
            ColunaFolha("horas_extras", _dec("minutos_extras")),
            ColunaFolha("horas_noturnas", _dec("minutos_noturnos")),
            ColunaFolha("horas_atraso", _dec("minutos_atraso")),
            ColunaFolha("saldo_banco", _dec("saldo_periodo")),
            ColunaFolha("faltas", _int("dias_falta")),
            ColunaFolha("atestados", _int("dias_atestado")),
            ColunaFolha("dsr", _int("dias_dsr")),
            ColunaFolha("minutos_trabalhados", _int("minutos_trabalhados")),
            ColunaFolha("minutos_extras", _int("minutos_extras")),
            ColunaFolha("minutos_noturnos", _int("minutos_noturnos")),
        ],
    },
    "dominio": {
        "rotulo": "Domínio Sistemas (posicional)",
        "extensao": "txt",
        "formato": "posicional",
        "codificacao": "iso-8859-1",
        "quebra": "\r\n",
        "descricao": (
            "Arquivo de largura fixa. Cada linha é um lançamento: matrícula, "
            "código do evento e quantidade em centésimos de hora."
        ),
        # Um lançamento por evento, não uma linha por colaborador: é
        # assim que a Domínio importa horas extras, faltas e adicional
        # noturno — cada um com o seu código.
        "por_evento": True,
        "eventos": [
            ("001", "minutos_extras", "Horas extras"),
            ("002", "minutos_noturnos", "Adicional noturno"),
            ("003", "minutos_atraso", "Atrasos"),
        ],
        "colunas": [
            ColunaFolha("matricula", _txt("matricula"), 10, "direita", "0"),
            ColunaFolha("cpf", _txt("cpf"), 11, "direita", "0"),
            ColunaFolha("evento", _txt("evento_codigo"), 4, "direita", "0"),
            ColunaFolha("quantidade", _num_fixo("evento_minutos"), 9, "direita", "0"),
            ColunaFolha("competencia", _txt("competencia"), 6),
        ],
    },
    "totvs": {
        "rotulo": "TOTVS RM / Protheus (CSV)",
        "extensao": "csv",
        "formato": "csv",
        "delimitador": ";",
        "codificacao": "iso-8859-1",
        "descricao": (
            "CSV delimitado por ponto e vírgula, com horas em decimal e "
            "ponto como separador."
        ),
        "colunas": [
            ColunaFolha("CHAPA", _txt("matricula")),
            ColunaFolha("CPF", _txt("cpf")),
            ColunaFolha("NOME", _txt("nome")),
            ColunaFolha("COMPETENCIA", _txt("competencia")),
            ColunaFolha("HORASNORMAIS", _dec_ponto("minutos_trabalhados")),
            ColunaFolha("HORASEXTRAS", _dec_ponto("minutos_extras")),
            ColunaFolha("ADICNOTURNO", _dec_ponto("minutos_noturnos")),
            ColunaFolha("ATRASOS", _dec_ponto("minutos_atraso")),
            ColunaFolha("FALTAS", _int("dias_falta")),
            ColunaFolha("DSR", _int("dias_dsr")),
        ],
    },
}


# ══════════════════════════════════════════════════════════════
# Gerador
# ══════════════════════════════════════════════════════════════
class FolhaExporter:
    """
    Monta o arquivo de folha de um período.

    Uso:

        exportador = FolhaExporter(empresa, inicio, fim, layout="dominio")
        conteudo = exportador.gerar()          # str
        bytes_ = exportador.gerar_bytes()      # já na codificação certa
        nome = exportador.nome_arquivo()
    """

    def __init__(self, empresa, data_inicio: date, data_fim: date, layout="generico",
                 colaboradores=None):
        if layout not in LAYOUTS:
            raise ValueError(
                f"Layout '{layout}' desconhecido. Disponíveis: "
                f"{', '.join(sorted(LAYOUTS))}."
            )
        self.empresa = empresa
        self.data_inicio = data_inicio
        self.data_fim = data_fim
        self.layout_nome = layout
        self.layout = LAYOUTS[layout]
        self._colaboradores = colaboradores

    # -- coleta -------------------------------------------------
    def linhas(self) -> list[dict]:
        """
        Um dicionário por colaborador, com os totais do período.

        Só entram colaboradores **com apuração no período**: exportar
        alguém sem nenhum dia apurado mandaria zeros para a folha, o que
        é diferente de não mandar nada — e a folha trataria como mês sem
        horas em vez de mês sem informação.
        """
        from django.db.models import Count, Q, Sum

        from apps.core.constants import StatusDia
        from apps.ponto.models import BancoHoras
        from apps.rh.models import Colaborador

        base = BancoHoras.objects.filter(
            empresa=self.empresa,
            data__gte=self.data_inicio,
            data__lte=self.data_fim,
        )
        if self._colaboradores is not None:
            base = base.filter(colaborador__in=self._colaboradores)

        # Os alias levam sufixo `_tot` de proposito: nomear a anotacao
        # igual ao campo agregado faz o filtro de `dias_trabalhados`
        # enxergar o SUM() em vez da coluna, e o banco recusa
        # ("misuse of aggregate function").
        agregado = (
            base.values("colaborador_id")
            .annotate(
                trabalhados_tot=Sum("minutos_trabalhados"),
                esperados_tot=Sum("minutos_esperados"),
                extras_tot=Sum("minutos_extras"),
                noturnos_tot=Sum("minutos_noturnos"),
                atraso_tot=Sum("minutos_atraso"),
                saldo_tot=Sum("saldo_dia"),
                dias_trabalhados=Count("pk", filter=Q(minutos_trabalhados__gt=0)),
                dias_falta=Count("pk", filter=Q(status=StatusDia.FALTA)),
                dias_atestado=Count("pk", filter=Q(status=StatusDia.ATESTADO)),
                dias_dsr=Count("pk", filter=Q(status=StatusDia.FOLGA)),
            )
        )
        totais = {item["colaborador_id"]: item for item in agregado}
        if not totais:
            return []

        colaboradores = Colaborador.objects.filter(pk__in=totais).order_by(
            "matricula", "nome_completo"
        )

        competencia = f"{self.data_fim:%m%Y}"
        linhas = []
        for colaborador in colaboradores:
            item = totais[colaborador.pk]
            linhas.append({
                "matricula": colaborador.matricula or str(colaborador.pk),
                "cpf": colaborador.cpf,
                "nome": colaborador.nome_exibicao,
                "admissao": colaborador.data_admissao,
                "competencia": competencia,
                "minutos_trabalhados": item["trabalhados_tot"] or 0,
                "minutos_esperados": item["esperados_tot"] or 0,
                "minutos_extras": item["extras_tot"] or 0,
                "minutos_noturnos": item["noturnos_tot"] or 0,
                "minutos_atraso": item["atraso_tot"] or 0,
                "saldo_periodo": item["saldo_tot"] or 0,
                "dias_trabalhados": item["dias_trabalhados"],
                "dias_falta": item["dias_falta"],
                "dias_atestado": item["dias_atestado"],
                "dias_dsr": item["dias_dsr"],
            })
        return linhas

    # -- geração ------------------------------------------------
    def gerar(self) -> str:
        if self.layout["formato"] == "posicional":
            return self._gerar_posicional()
        return self._gerar_csv()

    def gerar_bytes(self) -> bytes:
        return self.gerar().encode(
            self.layout["codificacao"], errors="replace"
        )

    def _gerar_csv(self) -> str:
        buffer = io.StringIO()
        escritor = csv.writer(
            buffer,
            delimiter=self.layout["delimitador"],
            lineterminator="\r\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        colunas = self.layout["colunas"]
        escritor.writerow([coluna.nome for coluna in colunas])
        for linha in self.linhas():
            escritor.writerow([coluna.valor(linha) for coluna in colunas])
        return buffer.getvalue()

    def _gerar_posicional(self) -> str:
        colunas = self.layout["colunas"]
        quebra = self.layout.get("quebra", "\r\n")
        saida = []

        for linha in self.linhas():
            for codigo, campo, _rotulo in self.layout["eventos"]:
                minutos = linha.get(campo, 0)
                if not minutos:
                    # Evento zerado não vira lançamento. Mandar "0 horas
                    # extras" faz a folha registrar um lançamento vazio
                    # que o RH depois precisa explicar.
                    continue
                registro = dict(linha)
                registro["evento_codigo"] = codigo
                registro["evento_minutos"] = minutos
                saida.append("".join(c.formatar(registro) for c in colunas))

        return quebra.join(saida) + (quebra if saida else "")

    # -- metadados ----------------------------------------------
    def nome_arquivo(self) -> str:
        return (
            f"folha_{self.layout_nome}_{self.empresa.cnpj}_"
            f"{self.data_inicio:%Y%m%d}_{self.data_fim:%Y%m%d}."
            f"{self.layout['extensao']}"
        )

    def content_type(self) -> str:
        codificacao = self.layout["codificacao"].replace("-sig", "")
        if self.layout["formato"] == "csv":
            return f"text/csv; charset={codificacao}"
        return f"text/plain; charset={codificacao}"

    def resumo(self) -> dict:
        """Totais do arquivo — mostrados na tela antes do download."""
        linhas = self.linhas()
        return {
            "colaboradores": len(linhas),
            "minutos_trabalhados": sum(l["minutos_trabalhados"] for l in linhas),
            "minutos_extras": sum(l["minutos_extras"] for l in linhas),
            "minutos_noturnos": sum(l["minutos_noturnos"] for l in linhas),
            "dias_falta": sum(l["dias_falta"] for l in linhas),
            "horas_extras_decimal": minutos_para_decimal(
                sum(l["minutos_extras"] for l in linhas)
            ),
        }
