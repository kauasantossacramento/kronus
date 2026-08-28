"""
Kronus — geração do AEJ (Arquivo Eletrônico de Jornada).

O AEJ é o arquivo que apresenta a **jornada apurada**: quem trabalha,
qual o horário contratual, quais marcações foram consideradas e quais
ausências e movimentos de banco de horas houve. O AFD mostra o que o
relógio registrou; o AEJ mostra o que o RH apurou a partir disso.

═══════════════════════════════════════════════════════════════════
CONFORMIDADE DE LAYOUT — CONFERIDO

Layout conferido campo a campo contra o **Anexo VI da Portaria
671/2021**, na íntegra publicada no DOU:

    https://www.in.gov.br/en/web/dou/-/portaria-359094139

**O AEJ não é de largura fixa.** É a diferença mais importante em
relação ao AFD, e a implementação anterior errava exatamente nisto. O
Anexo VI, item 5, é explícito:

    "Cada linha do arquivo digital representará um registro e deve
     conter os campos que estão no leiaute definido para o registro. Ao
     final de cada campo, com exceção do último campo do registro, deve
     ser inserido o caractere delimitador '|' (pipe ou barra vertical)."

Ou seja: campos de tamanho variável, separados por `|`, sem
preenchimento. Um AEJ de largura fixa é recusado na importação.

Registros (Anexo VI):

    01  cabeçalho
    02  REPs utilizados
    03  vínculos (empregados)
    04  horário contratual
    05  marcações
    06  matrícula no eSocial (só com mais de um vínculo)
    07  ausências e banco de horas
    08  identificação do PTRP
    99  trailer

Pendente, e não é layout: o **registro no INPI** do programa, exigido
no campo `nrRep` do registro 02. Sai vazio enquanto não existir.
═══════════════════════════════════════════════════════════════════
"""
import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

from django.utils import timezone

from apps.core.utils import apenas_digitos

logger = logging.getLogger("kronus.relatorios")

#: Versão do leiaute declarada no cabeçalho (Anexo VI, registro 01).
VERSAO_LAYOUT = "001"

#: Delimitador de campo (Anexo VI, item 5).
PIPE = "|"


@dataclass(frozen=True)
class CampoAEJ:
    """
    Um campo do AEJ.

    `tamanho_max` é limite, não largura: o campo **não** é preenchido
    até o tamanho. Está declarado para que o gerador possa truncar com
    aviso em vez de emitir um registro que o importador recusa.

    `obrigatorio=False` significa que o campo pode sair vazio — e vazio,
    aqui, é a string vazia entre dois pipes, não espaços.
    """

    nome: str
    tamanho_max: int
    tipo: str = "A"          # N | A | D | H | DH
    obrigatorio: bool = True

    def formatar(self, valor) -> str:
        texto = "" if valor is None else str(valor)
        if len(texto) > self.tamanho_max:
            logger.warning(
                "AEJ: campo %s truncado de %s para %s caracteres",
                self.nome, len(texto), self.tamanho_max,
            )
            texto = texto[: self.tamanho_max]
        return texto


def _c(nome, tamanho, tipo="A", obrigatorio=True):
    return CampoAEJ(nome, tamanho, tipo, obrigatorio)


#: Leiaute de cada registro. Os comentários trazem o tamanho oficial
#: ("1 a 9" significa variável até 9), para conferência sem sair daqui.
LAYOUT = {
    "01": [
        _c("tipoReg", 2, "N"),
        _c("tpIdtEmpregador", 1, "N"),
        _c("idtEmpregador", 14, "N"),        # 11 ou 14
        _c("caepf", 14, "N", False),
        _c("cno", 12, "N", False),
        _c("razaoOuNome", 150),              # 1 a 150
        _c("dataInicialAej", 10, "D"),
        _c("dataFinalAej", 10, "D"),
        _c("dataHoraGerAej", 24, "DH"),
        _c("versaoAej", 3),
    ],
    "02": [
        _c("tipoReg", 2, "N"),
        _c("idRepAej", 9, "N"),              # 1 a 9
        _c("tpRep", 1, "N"),                 # 3 = REP-P
        _c("nrRep", 17, "N", False),         # registro no INPI
    ],
    "03": [
        _c("tipoReg", 2, "N"),
        _c("idtVinculoAej", 9, "N"),
        _c("cpf", 11, "N"),
        _c("nomeEmp", 150),
    ],
    "04": [
        _c("tipoReg", 2, "N"),
        _c("codHorContratual", 30),
        _c("durJornada", 12, "N"),           # minutos
        _c("hrEntrada01", 4, "H"),
        _c("hrSaida01", 4, "H"),
        _c("hrEntrada02", 4, "H", False),
        _c("hrSaida02", 4, "H", False),
    ],
    "05": [
        _c("tipoReg", 2, "N"),
        _c("idtVinculoAej", 9, "N"),
        _c("dataHoraMarc", 24, "DH"),
        _c("idRepAej", 9, "N", False),
        _c("tpMarc", 1),                     # E | S | D
        _c("seqEntSaida", 3, "N"),
        _c("fonteMarc", 1),                  # O | I | P | X | T
        _c("codHorContratual", 30, "A", False),
        _c("motivo", 150, "A", False),
    ],
    "06": [
        _c("tipoReg", 2, "N"),
        _c("idtVinculoAej", 9, "N"),
        _c("matEsocial", 30),
    ],
    "07": [
        _c("tipoReg", 2, "N"),
        _c("idtVinculoAej", 9, "N"),
        _c("tipoAusenOuComp", 1, "N"),
        _c("data", 10, "D"),
        _c("qtMinutos", 12, "N", False),
        _c("tipoMovBH", 1, "N", False),
    ],
    "08": [
        _c("tipoReg", 2, "N"),
        _c("nomeProg", 150),
        _c("versaoProg", 8),
        _c("tpIdtDesenv", 1, "N"),
        _c("idtDesenv", 14, "N"),
        _c("razaoNomeDesenv", 150),
        _c("emailDesenv", 50),
    ],
    "99": [
        _c("tipoReg", 2, "N"),
        _c("qtRegistrosTipo01", 9, "N"),
        _c("qtRegistrosTipo02", 9, "N"),
        _c("qtRegistrosTipo03", 9, "N"),
        _c("qtRegistrosTipo04", 9, "N"),
        _c("qtRegistrosTipo05", 9, "N"),
        _c("qtRegistrosTipo06", 9, "N"),
        _c("qtRegistrosTipo07", 9, "N"),
        _c("qtRegistrosTipo08", 9, "N"),
    ],
}

#: Campo `tipoAusenOuComp` do registro 07.
AUSENCIA = {
    "dsr": "1",
    "falta": "2",
    "banco_horas": "3",
    "folga_compensatoria": "4",
}

#: Campo `fonteMarc` do registro 05.
FONTE = {
    "original": "O",     # veio do REP
    "incluida": "I",     # inclusão manual do RH
    "preassinalada": "P",
    "excecao": "X",
    "outra": "T",
}

#: De onde a marcação veio para a fonte declarada no AEJ.
FONTE_POR_METODO = {
    "facial": FONTE["original"],
    "cpf": FONTE["original"],
    "web": FONTE["original"],
    "api": FONTE["original"],
    "manual": FONTE["incluida"],
    "importacao": FONTE["incluida"],
}


def montar_linha(tipo: str, valores: dict) -> str:
    """
    Monta uma linha do AEJ: campos separados por `|`, sem preenchimento.

    O último campo **não** leva delimitador ao final (Anexo VI, item 5).
    `"|".join(...)` já garante isso — escrever o pipe a cada campo e
    remover o último seria o caminho para o erro clássico do pipe
    sobrando na ponta.
    """
    campos = LAYOUT[tipo]
    return PIPE.join(campo.formatar(valores.get(campo.nome, "")) for campo in campos)


def fatiar_linha(linha: str) -> dict:
    """Converte uma linha do AEJ de volta em dicionário de campos."""
    partes = linha.split(PIPE)
    tipo = partes[0] if partes else ""
    if tipo not in LAYOUT:
        return {"tipoReg": tipo, "erro": "tipo desconhecido"}
    return {
        campo.nome: (partes[indice] if indice < len(partes) else "")
        for indice, campo in enumerate(LAYOUT[tipo])
    }


def quantidade_de_campos(tipo: str) -> int:
    return len(LAYOUT[tipo])


# ══════════════════════════════════════════════════════════════
# Gerador
# ══════════════════════════════════════════════════════════════
class AEJGenerator:
    """
    Monta o AEJ de uma empresa em um intervalo de datas.

        gerador = AEJGenerator(empresa, inicio, fim)
        conteudo = gerador.gerar()
    """

    CODIFICACAO = "iso-8859-1"
    QUEBRA = "\r\n"

    def __init__(self, empresa, data_inicio: date, data_fim: date, colaboradores=None):
        self.empresa = empresa
        self.data_inicio = data_inicio
        self.data_fim = data_fim
        self._colaboradores = colaboradores
        self._contagem = {f"0{n}": 0 for n in range(1, 9)}
        #: identificador sequencial de cada vínculo dentro do arquivo
        self._vinculos: dict[int, int] = {}
        #: horários contratuais já emitidos, por código
        self._horarios: set[str] = set()

    # -- formatos ----------------------------------------------
    @staticmethod
    def _data(valor: date) -> str:
        """Tipo D: "AAAA-MM-dd"."""
        return valor.strftime("%Y-%m-%d")

    @staticmethod
    def _iso(valor: datetime) -> str:
        """Tipo DH: "AAAA-MM-ddThh:mm:00ZZZZZ" — segundos fixos, fuso sem `:`."""
        return timezone.localtime(valor).strftime("%Y-%m-%dT%H:%M:00%z")

    @staticmethod
    def _hora(minutos_do_dia: int) -> str:
        """Tipo H: "hhmm"."""
        return f"{minutos_do_dia // 60:02d}{minutos_do_dia % 60:02d}"

    @staticmethod
    def _ascii(texto: str) -> str:
        """
        Remove acentos e o próprio delimitador.

        Um `|` dentro da razão social partiria o registro em dois campos
        e deslocaria todos os seguintes — é a falha específica de
        formatos delimitados, e vale mais preveni-la aqui do que
        depender de quem preencheu o cadastro.
        """
        sem_acento = "".join(
            c for c in unicodedata.normalize("NFD", texto or "")
            if unicodedata.category(c) != "Mn"
        )
        return sem_acento.replace(PIPE, "-").encode("ascii", "ignore").decode()

    @property
    def identificador_rep(self) -> str:
        from django.conf import settings

        return apenas_digitos(settings.KRONUS.get("REGISTRO_INPI", ""))

    # -- coleta ------------------------------------------------
    def colaboradores(self):
        from apps.rh.models import Colaborador

        if self._colaboradores is not None:
            return self._colaboradores
        return Colaborador.objects.filter(empresa=self.empresa).order_by(
            "nome_completo"
        )

    def _id_vinculo(self, colaborador) -> str:
        """Identificador do vínculo dentro deste arquivo (registro 03)."""
        if colaborador.pk not in self._vinculos:
            self._vinculos[colaborador.pk] = len(self._vinculos) + 1
        return str(self._vinculos[colaborador.pk])

    def _bancos(self, colaborador):
        from apps.ponto.models import BancoHoras

        return BancoHoras.objects.filter(
            colaborador=colaborador,
            data__gte=self.data_inicio,
            data__lte=self.data_fim,
        ).order_by("data")

    def _marcacoes(self, colaborador):
        from apps.ponto.models import RegistroPonto

        return RegistroPonto.objects.filter(
            colaborador=colaborador,
            data_hora__date__gte=self.data_inicio,
            data_hora__date__lte=self.data_fim,
        ).order_by("data_hora")

    # -- registros ---------------------------------------------
    def cabecalho(self) -> str:
        self._contagem["01"] += 1
        return montar_linha("01", {
            "tipoReg": "01",
            "tpIdtEmpregador": "1",          # CNPJ
            "idtEmpregador": apenas_digitos(self.empresa.cnpj),
            "caepf": apenas_digitos(self.empresa.cei_caepf),
            "cno": "",
            "razaoOuNome": self._ascii(self.empresa.razao_social),
            "dataInicialAej": self._data(self.data_inicio),
            "dataFinalAej": self._data(self.data_fim),
            "dataHoraGerAej": self._iso(timezone.localtime()),
            "versaoAej": VERSAO_LAYOUT,
        })

    def registro_rep(self) -> str:
        """Registro 02 — o REP que originou as marcações. Somos REP-P."""
        self._contagem["02"] += 1
        return montar_linha("02", {
            "tipoReg": "02",
            "idRepAej": "1",
            "tpRep": "3",                    # REP-P
            "nrRep": self.identificador_rep,
        })

    def registro_ptrp(self) -> str:
        """
        Registro 08 — identificação do programa de tratamento.

        O Kronus faz as duas pontas: é o REP-P que coleta e o PTRP que
        trata. Por isso aparece nos registros 02 e 08.
        """
        from django.conf import settings

        self._contagem["08"] += 1
        return montar_linha("08", {
            "tipoReg": "08",
            "nomeProg": "Kronus",
            "versaoProg": settings.KRONUS.get("VERSAO", "1.0"),
            "tpIdtDesenv": "1",
            "idtDesenv": apenas_digitos(settings.KRONUS["DESENVOLVEDORA_CNPJ"]),
            "razaoNomeDesenv": self._ascii(settings.KRONUS.get("DESENVOLVEDORA", "KS TEC")),
            "emailDesenv": settings.KRONUS.get("EMAIL_SUPORTE", ""),
        })

    def registro_vinculo(self, colaborador) -> str:
        self._contagem["03"] += 1
        return montar_linha("03", {
            "tipoReg": "03",
            "idtVinculoAej": self._id_vinculo(colaborador),
            "cpf": colaborador.cpf,
            "nomeEmp": self._ascii(colaborador.nome_exibicao),
        })

    def registro_horario(self, colaborador) -> str | None:
        """
        Registro 04 — horário contratual do vínculo.

        Emitido uma vez por escala distinta. Colaboradores que
        compartilham a escala compartilham o código, que é o que o
        registro 05 referencia na primeira entrada do dia.
        """
        escala = colaborador.escala
        if escala is None:
            return None

        codigo = f"ESC{escala.pk}"
        if codigo in self._horarios:
            return None
        self._horarios.add(codigo)
        self._contagem["04"] += 1

        entrada, saida, volta, fim = self._pares_da_escala(escala)
        return montar_linha("04", {
            "tipoReg": "04",
            "codHorContratual": codigo,
            "durJornada": str(escala.carga_diaria_min or 0),
            "hrEntrada01": entrada,
            "hrSaida01": saida,
            "hrEntrada02": volta,
            "hrSaida02": fim,
        })

    @staticmethod
    def _pares_da_escala(escala) -> tuple[str, str, str, str]:
        """
        Extrai os pares entrada/saída da configuração da escala.

        A `jornada_config` é livre por desenho (escalas 12x36, 6x1 e
        flexível não cabem num molde único). Aqui pegamos o padrão mais
        comum — entrada, intervalo, retorno, saída — e caímos num
        horário comercial quando a escala não declara.
        """
        config = escala.jornada_config or {}
        padrao = config.get("padrao") or config.get("segunda") or {}

        def limpar(valor, alternativa):
            texto = apenas_digitos(str(valor or ""))
            return texto[:4] if len(texto) >= 4 else alternativa

        return (
            limpar(padrao.get("entrada"), "0800"),
            limpar(padrao.get("intervalo_inicio"), "1200"),
            limpar(padrao.get("intervalo_fim"), "1300"),
            limpar(padrao.get("saida"), "1700"),
        )

    def registros_marcacoes(self, colaborador) -> list[str]:
        """
        Registro 05 — uma linha por marcação.

        O par entrada/saída é **posicional**: a primeira marcação do dia
        é entrada, a segunda é saída, e assim por diante. É a mesma
        regra que `ponto/calculators.py` usa para apurar — usar o `tipo`
        declarado aqui e a posição lá produziria AEJ e espelho
        divergentes para o mesmo dia.

        Marcações canceladas entram como `tpMarc="D"` (desconsiderada),
        com o motivo. Some-las esconderia do fiscal que houve ajuste.
        """
        linhas = []
        id_vinculo = self._id_vinculo(colaborador)
        codigo_horario = f"ESC{colaborador.escala.pk}" if colaborador.escala_id else ""

        por_dia: dict[date, list] = {}
        for registro in self._marcacoes(colaborador):
            dia = timezone.localtime(registro.data_hora).date()
            por_dia.setdefault(dia, []).append(registro)

        for dia in sorted(por_dia):
            sequencia = 0
            posicao = 0
            for registro in por_dia[dia]:
                if registro.cancelado:
                    tipo_marcacao = "D"
                    motivo = self._ascii(registro.observacao or "Marcacao cancelada")[:150]
                    sequencia_atual = sequencia if sequencia else 1
                else:
                    tipo_marcacao = "E" if posicao % 2 == 0 else "S"
                    motivo = ""
                    if tipo_marcacao == "E":
                        sequencia += 1
                    sequencia_atual = sequencia
                    posicao += 1

                fonte = FONTE_POR_METODO.get(registro.metodo, FONTE["outra"])
                if fonte == FONTE["incluida"] and not motivo:
                    motivo = self._ascii(registro.observacao or "Ajuste do RH")[:150]

                self._contagem["05"] += 1
                linhas.append(montar_linha("05", {
                    "tipoReg": "05",
                    "idtVinculoAej": id_vinculo,
                    "dataHoraMarc": self._iso(registro.data_hora),
                    # Só marcações originais do REP referenciam o REP.
                    "idRepAej": "1" if fonte == FONTE["original"] else "",
                    "tpMarc": tipo_marcacao,
                    "seqEntSaida": f"{sequencia_atual:03d}",
                    "fonteMarc": fonte,
                    # Obrigatório apenas na primeira entrada do dia.
                    "codHorContratual": (
                        codigo_horario
                        if tipo_marcacao == "E" and sequencia_atual == 1
                        else ""
                    ),
                    "motivo": motivo,
                }))
        return linhas

    def registros_ausencias(self, colaborador) -> list[str]:
        """
        Registro 07 — ausências e movimentos de banco de horas.

        Um dia pode gerar duas linhas: a ausência (falta ou DSR) e o
        movimento de banco, que são fatos diferentes e a Portaria
        codifica separadamente.
        """
        from apps.core.constants import StatusDia

        linhas = []
        id_vinculo = self._id_vinculo(colaborador)

        mapa = {
            StatusDia.FALTA: AUSENCIA["falta"],
            StatusDia.FOLGA: AUSENCIA["dsr"],
        }

        for banco in self._bancos(colaborador):
            codigo = mapa.get(banco.status)
            if codigo:
                self._contagem["07"] += 1
                linhas.append(montar_linha("07", {
                    "tipoReg": "07",
                    "idtVinculoAej": id_vinculo,
                    "tipoAusenOuComp": codigo,
                    "data": self._data(banco.data),
                    "qtMinutos": "",
                    "tipoMovBH": "",
                }))

            if banco.saldo_dia:
                self._contagem["07"] += 1
                linhas.append(montar_linha("07", {
                    "tipoReg": "07",
                    "idtVinculoAej": id_vinculo,
                    "tipoAusenOuComp": AUSENCIA["banco_horas"],
                    "data": self._data(banco.data),
                    "qtMinutos": str(abs(banco.saldo_dia)),
                    # "1" credita horas no banco, "2" compensa. O sinal do
                    # saldo do dia diz qual dos dois aconteceu.
                    "tipoMovBH": "1" if banco.saldo_dia > 0 else "2",
                }))
        return linhas

    def trailer(self) -> str:
        return montar_linha("99", {
            "tipoReg": "99",
            **{
                f"qtRegistrosTipo{n:02d}": str(self._contagem[f"{n:02d}"])
                for n in range(1, 9)
            },
        })

    # -- montagem ----------------------------------------------
    def gerar(self) -> str:
        """
        Monta o arquivo completo.

        Zera contadores e identificadores a cada chamada: `verificar()`
        chama `gerar()` internamente, e sem o reset a segunda geração
        somaria as contagens e emitiria um trailer errado.
        """
        self._contagem = {f"0{n}": 0 for n in range(1, 9)}
        self._vinculos = {}
        self._horarios = set()

        linhas = [self.cabecalho(), self.registro_rep(), self.registro_ptrp()]

        # Ordem do Anexo VI: vínculos e horários antes das marcações,
        # porque o registro 05 referencia os dois por identificador.
        colaboradores = list(self.colaboradores())
        for colaborador in colaboradores:
            linhas.append(self.registro_vinculo(colaborador))

        for colaborador in colaboradores:
            horario = self.registro_horario(colaborador)
            if horario:
                linhas.append(horario)

        for colaborador in colaboradores:
            linhas.extend(self.registros_marcacoes(colaborador))
            linhas.extend(self.registros_ausencias(colaborador))

        linhas.append(self.trailer())
        return self.QUEBRA.join(linhas) + self.QUEBRA

    def gerar_bytes(self) -> bytes:
        return self.gerar().encode(self.CODIFICACAO, errors="replace")

    def nome_arquivo(self) -> str:
        return (
            f"AEJ_{apenas_digitos(self.empresa.cnpj)}_"
            f"{self.data_inicio:%Y%m%d}_{self.data_fim:%Y%m%d}.txt"
        )

    # -- verificação -------------------------------------------
    def verificar(self) -> dict:
        """Confere o arquivo: tipos conhecidos, contagem de campos e trailer."""
        linhas = [l for l in self.gerar().split(self.QUEBRA) if l]
        problemas = []
        contagem = {chave: 0 for chave in LAYOUT}

        for numero, linha in enumerate(linhas, 1):
            tipo = linha.split(PIPE)[0]
            if tipo not in LAYOUT:
                problemas.append(f"linha {numero}: tipo desconhecido {tipo!r}")
                continue
            contagem[tipo] += 1

            partes = linha.split(PIPE)
            esperado = quantidade_de_campos(tipo)
            if len(partes) != esperado:
                problemas.append(
                    f"linha {numero} (tipo {tipo}): {len(partes)} campos, "
                    f"esperado {esperado}"
                )

            for campo, valor in zip(LAYOUT[tipo], partes):
                if campo.obrigatorio and not valor:
                    problemas.append(
                        f"linha {numero} (tipo {tipo}): campo obrigatorio "
                        f"{campo.nome!r} vazio"
                    )
                if len(valor) > campo.tamanho_max:
                    problemas.append(
                        f"linha {numero} (tipo {tipo}): campo {campo.nome!r} "
                        f"com {len(valor)} caracteres, maximo {campo.tamanho_max}"
                    )

        if linhas and linhas[-1].split(PIPE)[0] != "99":
            problemas.append("arquivo nao termina com o trailer (tipo 99)")
        else:
            declarado = fatiar_linha(linhas[-1])
            for numero in range(1, 9):
                chave = f"{numero:02d}"
                dito = declarado.get(f"qtRegistrosTipo{chave}", "0") or "0"
                if int(dito) != contagem[chave]:
                    problemas.append(
                        f"trailer declara {dito} registros do tipo {chave}, "
                        f"arquivo tem {contagem[chave]}"
                    )

        return {
            "valido": not problemas,
            "problemas": problemas,
            "linhas": len(linhas),
            "marcacoes": contagem["05"],
            "vinculos": contagem["03"],
            "bytes": len(self.gerar_bytes()),
        }
