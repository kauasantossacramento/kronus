"""
Kronus — geração do AFD (Arquivo Fonte de Dados).

O AFD é o arquivo que o **Auditor-Fiscal do Trabalho** exige numa
inspeção: texto puro, uma linha por evento, na ordem do NSR. Ele não
olha o banco de dados nem a interface — pede o TXT e confere. Se houver
lacuna ou repetição de NSR, o sistema é considerado inidôneo e a empresa
é autuada.

    Registro 1  cabeçalho (identificação do empregador e do período)
    Registro 2  inclusão/alteração de empregador
    Registro 3  marcação de ponto (REP-C / REP-A) — não usado no REP-P
    Registro 4  ajuste de relógio — não se aplica ao REP-P
    Registro 5  inclusão/alteração/exclusão de empregado
    Registro 6  eventos sensíveis (REP-C) — não se aplica
    Registro 7  MARCAÇÃO DE PONTO REP-P  ← o registro central aqui
    Registro 9  trailer (contagem por tipo)

═══════════════════════════════════════════════════════════════════
CONFORMIDADE DE LAYOUT — CONFERIDO

O layout abaixo foi **conferido campo a campo contra o Anexo V da
Portaria 671/2021**, na íntegra publicada no Diário Oficial da União:

    https://www.in.gov.br/en/web/dou/-/portaria-359094139

Conferidos e batendo: os tamanhos de linha (1=302, 2=331, 3=50, 4=73,
5=118, 6=36, 7=137, 9=64, assinatura=100), a posição de cada campo, o
formato D ("AAAA-MM-dd"), o formato DH ("AAAA-MM-ddThh:mm:00ZZZZZ" —
segundos fixos em "00" e fuso sem dois-pontos), o CRC-16 dos registros
1 a 5 (item 17) e a composição do hash SHA-256 do registro 7 (item 18).

O que **continua pendente**, e não é layout:

* **Registro do programa no INPI.** O campo 7 do cabeçalho e o nome do
  arquivo exigem esse número (itens 7 e 19.3). Enquanto ele não existir,
  o campo sai em branco — declarando a pendência em vez de simulá-la.
* **Assinatura digital do arquivo.** A linha de 100 posições é emitida
  vazia; o Kronus ainda não assina com certificado ICP-Brasil.

Todo o layout está declarado em `LAYOUT`, como dados: ajustar um campo é
editar uma linha, não reescrever o gerador.
═══════════════════════════════════════════════════════════════════
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime

from django.utils import timezone

from apps.core.utils import apenas_digitos

logger = logging.getLogger("kronus.relatorios")

#: Versão do layout declarada no cabeçalho.
VERSAO_LAYOUT = "003"


# ══════════════════════════════════════════════════════════════
# Especificação declarativa do layout
# ══════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Campo:
    """
    Um campo de largura fixa do AFD.

    `alinhamento` define o preenchimento: numéricos são alinhados à
    direita com zeros; textuais, à esquerda com espaços. Errar isso é o
    defeito mais comum em geradores de AFD — um NSR com espaço à
    esquerda invalida o arquivo inteiro.
    """

    nome: str
    tamanho: int
    alinhamento: str = "esquerda"  # "esquerda" (texto) | "direita" (numérico)
    preenchimento: str = " "

    def formatar(self, valor) -> str:
        texto = "" if valor is None else str(valor)
        if len(texto) > self.tamanho:
            # Truncar é preferível a estourar a linha: um campo longo
            # demais desloca todos os seguintes e corrompe o arquivo.
            logger.warning(
                "AFD: campo %s truncado de %s para %s caracteres",
                self.nome,
                len(texto),
                self.tamanho,
            )
            texto = texto[: self.tamanho]
        if self.alinhamento == "direita":
            return texto.rjust(self.tamanho, self.preenchimento)
        return texto.ljust(self.tamanho, self.preenchimento)


def _num(nome, tamanho):
    return Campo(nome, tamanho, alinhamento="direita", preenchimento="0")


def _txt(nome, tamanho):
    return Campo(nome, tamanho)


#: Layout de cada tipo de registro. Fonte única de verdade.
#:
#: CONFERIDO contra o Anexo V da Portaria 671/2021, publicado no DOU
#: (https://www.in.gov.br/en/web/dou/-/portaria-359094139). Cada campo
#: abaixo traz a posição oficial em comentário para que a conferência
#: possa ser refeita sem sair do arquivo.
LAYOUT = {
    # ── Tipo 1 — cabeçalho ── 302 posições ────────────────────
    "1": [
        _num("nsr", 9),                   # 001-009  fixo "000000000"
        _num("tipo", 1),                  # 010-010  "1"
        _num("tipo_identificador", 1),    # 011-011  1=CNPJ, 2=CPF
        _num("identificador", 14),        # 012-025  CNPJ/CPF do empregador
        _num("cno_caepf", 14),            # 026-039  CNO ou CAEPF, quando existir
        _txt("razao_social", 150),        # 040-189
        _num("identificador_rep", 17),    # 190-206  registro no INPI (REP-P)
        _txt("data_inicial", 10),         # 207-216  D  AAAA-MM-dd
        _txt("data_final", 10),           # 217-226  D  AAAA-MM-dd
        _txt("data_hora_geracao", 24),    # 227-250  DH
        _num("versao_layout", 3),         # 251-253  "003"
        _num("tipo_id_desenvolvedor", 1), # 254-254  1=CNPJ, 2=CPF
        _num("id_desenvolvedor", 14),     # 255-268  CNPJ/CPF do desenvolvedor
        _txt("modelo", 30),               # 269-298  só REP-C
        _txt("crc16", 4),                 # 299-302
    ],
    # ── Tipo 2 — inclusão/alteração do empregador ── 331 ───────
    "2": [
        _num("nsr", 9),                   # 001-009
        _num("tipo", 1),                  # 010-010  "2"
        _txt("data_hora", 24),            # 011-034  DH
        _num("cpf_responsavel", 14),       # 035-048  CPF de quem alterou
        _num("tipo_identificador", 1),    # 049-049
        _num("identificador", 14),        # 050-063
        _num("cno_caepf", 14),            # 064-077
        _txt("razao_social", 150),        # 078-227
        _txt("local", 100),               # 228-327
        _txt("crc16", 4),                 # 328-331
    ],
    # ── Tipo 3 — marcação REP-C / REP-A ── 50 ─────────────────
    #  Não é gerado pelo Kronus (somos REP-P, que usa o tipo 7), mas o
    #  layout fica declarado para que a leitura de arquivos de terceiros
    #  e a contagem do trailer sejam possíveis.
    "3": [
        _num("nsr", 9),                   # 001-009
        _txt("tipo", 1),                  # 010-010  "3"
        _txt("data_hora", 24),            # 011-034  DH
        _num("cpf", 12),                  # 035-046
        _txt("crc16", 4),                 # 047-050
    ],
    # ── Tipo 4 — ajuste do relógio ── 73 ──────────────────────
    "4": [
        _num("nsr", 9),                   # 001-009
        _num("tipo", 1),                  # 010-010  "4"
        _txt("data_hora_antes", 24),      # 011-034  DH
        _txt("data_hora_depois", 24),     # 035-058  DH
        _num("cpf_responsavel", 11),      # 059-069
        _txt("crc16", 4),                 # 070-073
    ],
    # ── Tipo 5 — inclusão/alteração/exclusão de empregado ── 118 ──
    "5": [
        _num("nsr", 9),                   # 001-009
        _num("tipo", 1),                  # 010-010  "5"
        _txt("data_hora", 24),            # 011-034  DH
        _txt("operacao", 1),              # 035-035  I / A / E
        _num("cpf", 12),                  # 036-047
        _txt("nome", 52),                 # 048-099
        _txt("demais_dados", 4),          # 100-103
        _num("cpf_responsavel", 11),      # 104-114
        _txt("crc16", 4),                 # 115-118
    ],
    # ── Tipo 6 — eventos sensíveis do REP ── 36 ───────────────
    "6": [
        _num("nsr", 9),                   # 001-009
        _num("tipo", 1),                  # 010-010  "6"
        _txt("data_hora", 24),            # 011-034  DH
        _num("evento", 2),                # 035-036
    ],
    # ── Tipo 7 — MARCAÇÃO DE PONTO REP-P ── 137 ───────────────
    "7": [
        _num("nsr", 9),                   # 001-009
        _txt("tipo", 1),                  # 010-010  "7"
        _txt("data_hora_marcacao", 24),   # 011-034  DH
        _num("cpf", 12),                  # 035-046
        _txt("data_hora_gravacao", 24),   # 047-070  DH
        _num("coletor", 2),               # 071-072  01..05, ver COLETOR
        _num("offline", 1),               # 073-073  0=on-line, 1=off-line
        _txt("hash", 64),                 # 074-137  SHA-256, ver hash_afd()
    ],
    # ── Tipo 9 — trailer ── 64 ────────────────────────────────
    "9": [
        _num("nsr", 9),                   # 001-009  fixo "999999999"
        _num("qtd_tipo_2", 9),            # 010-018
        _num("qtd_tipo_3", 9),            # 019-027
        _num("qtd_tipo_4", 9),            # 028-036
        _num("qtd_tipo_5", 9),            # 037-045
        _num("qtd_tipo_6", 9),            # 046-054
        _num("qtd_tipo_7", 9),            # 055-063
        _num("tipo", 1),                  # 064-064  "9"  <- no fim, não no início
    ],
    # ── Assinatura digital ── 100 ─────────────────────────────
    #  Linha própria, depois do trailer. Não é um "registro tipo" e não
    #  entra em contagem alguma.
    "A": [
        _txt("assinatura", 100),          # 001-100
    ],
}

#: Campo 6 do registro tipo 7 — como a marcação foi coletada.
#: Os códigos são da própria Portaria; não são livres.
COLETOR = {
    "mobile": "01",     # aplicativo mobile
    "browser": "02",    # navegador de internet
    "desktop": "03",    # aplicativo desktop
    "dispositivo": "04",  # dispositivo eletrônico
    "outro": "05",      # outro dispositivo não especificado
}

#: De onde a marcação veio (MetodoRegistro) para o código do coletor.
COLETOR_POR_METODO = {
    "facial": COLETOR["dispositivo"],   # totem — dispositivo eletrônico
    "cpf": COLETOR["dispositivo"],      # fallback no mesmo totem
    "web": COLETOR["browser"],
    "api": COLETOR["outro"],
    "manual": COLETOR["browser"],       # ajuste do RH, feito no navegador
    "importacao": COLETOR["outro"],
}


def hash_afd(
    *, nsr, tipo, data_hora_marcacao, cpf, data_hora_gravacao,
    coletor, offline, hash_anterior="",
) -> str:
    """
    Código hash do registro tipo 7 (Anexo V, item 18).

    A Portaria especifica exatamente o que entra e em que ordem:

        1. NSR                              (campo 1)
        2. tipo do registro                 (campo 2)
        3. data e hora da marcação          (campo 3)
        4. CPF do empregado                 (campo 4)
        5. data e hora da gravação          (campo 5)
        6. identificador do coletor         (campo 6)
        7. indicador on-line/off-line       (campo 7)
        8. hash do registro anterior, se houver

    **Este hash não é o mesmo de `RegistroPonto.hash_registro`**, e a
    diferença é proposital. O hash interno leva um salt por empresa e um
    salt global: isso o torna impossível de forjar por quem tenha só o
    banco, e é o que sustenta a detecção de adulteração. Mas justamente
    por levar segredo, **um auditor não consegue recalculá-lo** a partir
    do arquivo.

    O hash do AFD é o oposto: sem segredo nenhum, reproduzível por
    qualquer um que tenha o TXT em mãos — que é exatamente o que a
    fiscalização precisa fazer. Os dois convivem: um prova integridade
    para nós, o outro prova integridade para o fiscal.

    Os valores entram **já formatados como vão para o arquivo**, com o
    preenchimento de cada campo. Concatenar os valores "crus" daria um
    hash que não confere com o que se recalcula lendo o arquivo.
    """
    import hashlib

    base = "".join([
        LAYOUT["7"][0].formatar(nsr),
        LAYOUT["7"][1].formatar(tipo),
        LAYOUT["7"][2].formatar(data_hora_marcacao),
        LAYOUT["7"][3].formatar(cpf),
        LAYOUT["7"][4].formatar(data_hora_gravacao),
        LAYOUT["7"][5].formatar(coletor),
        LAYOUT["7"][6].formatar(offline),
        hash_anterior or "",
    ])
    return hashlib.sha256(base.encode("iso-8859-1", errors="replace")).hexdigest()


def montar_linha(tipo: str, valores: dict) -> str:
    """Monta uma linha do AFD a partir do layout declarado."""
    campos = LAYOUT[tipo]
    linha = "".join(campo.formatar(valores.get(campo.nome, "")) for campo in campos)

    # Anexo V, item 17: registros de 1 a 5 levam o CRC-16 do proprio
    # registro. Calculado aqui, sobre a linha ja montada e com o campo
    # de CRC ainda em branco — ele e o resultado, nao entra no calculo.
    if tipo in ("1", "2", "3", "4", "5"):
        from apps.relatorios.crc16 import crc16_hex

        inicio, fim = posicao_do_campo(tipo, "crc16")
        sem_crc = linha[:inicio] + linha[fim:]
        linha = linha[:inicio] + crc16_hex(sem_crc) + linha[fim:]
    return linha


def tamanho_da_linha(tipo: str) -> int:
    return sum(campo.tamanho for campo in LAYOUT[tipo])


def posicao_do_campo(tipo: str, nome: str) -> tuple[int, int]:
    """
    Deslocamento (inicio, fim) de um campo dentro da linha.

    Derivar a posicao do layout — em vez de escrever `linha[46:55]` —
    e o que impede que uma mudanca de largura quebre silenciosamente
    quem le o arquivo. Ja custou um diagnostico errado durante o
    desenvolvimento.
    """
    inicio = 0
    for campo in LAYOUT[tipo]:
        if campo.nome == nome:
            return inicio, inicio + campo.tamanho
        inicio += campo.tamanho
    raise KeyError(f"campo {nome!r} nao existe no registro tipo {tipo}")


def ler_campo(linha: str, tipo: str, nome: str) -> str:
    inicio, fim = posicao_do_campo(tipo, nome)
    return linha[inicio:fim]


def tipo_da_linha(linha: str) -> str:
    """
    Descobre o tipo de um registro lido do arquivo.

    O tipo mora na posicao 10 em quase todos os registros — mas nao no
    trailer, que comeca com "999999999" e leva o "9" no fim, nem na
    linha de assinatura, que nao tem tipo nenhum. Centralizar a regra
    aqui evita que cada leitor a redescubra (e erre).
    """
    if linha.startswith("999999999"):
        return "9"
    if len(linha) == tamanho_da_linha("A") and not linha.strip():
        return "A"
    return linha[9:10]


def fatiar_linha(linha: str) -> dict:
    """Converte uma linha do AFD de volta em um dicionario de campos."""
    tipo = tipo_da_linha(linha)
    if tipo not in LAYOUT:
        return {"tipo": tipo, "erro": "tipo desconhecido"}
    valores, posicao = {}, 0
    for campo in LAYOUT[tipo]:
        valores[campo.nome] = linha[posicao : posicao + campo.tamanho].strip()
        posicao += campo.tamanho
    return valores


# ══════════════════════════════════════════════════════════════
# Gerador
# ══════════════════════════════════════════════════════════════
class AFDGenerator:
    """
    Monta o AFD de uma empresa em um intervalo de datas.

    Uso:
        gerador = AFDGenerator(empresa, inicio, fim)
        conteudo = gerador.gerar()            # str
        nome = gerador.nome_arquivo()
    """

    #: A Portaria determina codificação ASCII/ISO-8859-1 e quebra CRLF.
    CODIFICACAO = "iso-8859-1"
    QUEBRA = "\r\n"

    def __init__(self, empresa, data_inicio: date, data_fim: date):
        self.empresa = empresa
        self.data_inicio = data_inicio
        self.data_fim = data_fim
        self._contagem = {"2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0}
        self._hash_anterior = ""

    # -- utilitários de formato --------------------------------
    @staticmethod
    def _data(valor: date) -> str:
        """Campo tipo D: "AAAA-MM-dd" (Anexo V, item 6.3)."""
        return valor.strftime("%Y-%m-%d")

    @staticmethod
    def _iso(valor: datetime) -> str:
        """
        Campo tipo DH: "AAAA-MM-ddThh:mm:00ZZZZZ" (Anexo V, item 6.7).

        Dois detalhes que a norma fixa e que é fácil errar:

        * **os segundos são literalmente "00"**, não os segundos reais.
          O REP registra o minuto da marcação; gravar o segundo real
          produziria um campo fora do formato declarado.
        * o fuso é `ZZZZZ` — sinal e quatro dígitos, **sem dois-pontos**
          (`-0300`, não `-03:00`). O exemplo da própria Portaria é
          `2021-04-27T16:44:00-0300`.
        """
        local = timezone.localtime(valor)
        return local.strftime("%Y-%m-%dT%H:%M:00%z")

    @staticmethod
    def _cpf(valor: str) -> str:
        """
        CPF no campo de 12 posições.

        A norma reserva 12 para um dado de 11 dígitos. O material de
        Perguntas e Respostas do MTE aceita duas formas — zero à
        esquerda ou espaço à direita — e adotamos o **zero à esquerda**,
        que é o que `_num` faz e o que mantém o campo puramente
        numérico, como o layout declara (tipo N).
        """
        return apenas_digitos(valor)

    @property
    def identificador_rep(self) -> str:
        """
        Campo 7 do cabeçalho — **número de registro no INPI**, no REP-P.

        A Portaria é específica: para o REP-P este campo recebe o número
        do registro do programa no INPI, e o nome do arquivo também é
        formado com ele.

        Enquanto o registro do Kronus no INPI não sair, devolvemos o
        valor de `KRONUS["REGISTRO_INPI"]`, que nasce vazio. Um campo
        vazio é honesto: mostra à fiscalização que o registro está
        pendente. Inventar um número aqui seria declarar um registro que
        não existe — infração pior do que a ausência dele.
        """
        from django.conf import settings

        return apenas_digitos(settings.KRONUS.get("REGISTRO_INPI", ""))

    # -- registros ---------------------------------------------
    def cabecalho(self) -> str:
        from django.conf import settings

        agora = timezone.localtime()
        return montar_linha(
            "1",
            {
                "nsr": 0,                    # "000000000"
                "tipo": "1",
                "tipo_identificador": "1",   # CNPJ
                "identificador": apenas_digitos(self.empresa.cnpj),
                "cno_caepf": apenas_digitos(self.empresa.cei_caepf),
                "razao_social": self._ascii(self.empresa.razao_social),
                "identificador_rep": self.identificador_rep,
                "data_inicial": self._data(self.data_inicio),
                "data_final": self._data(self.data_fim),
                "data_hora_geracao": self._iso(agora),
                "versao_layout": VERSAO_LAYOUT,
                "tipo_id_desenvolvedor": "1",  # a KS TEC e pessoa juridica
                "id_desenvolvedor": apenas_digitos(
                    settings.KRONUS["DESENVOLVEDORA_CNPJ"]
                ),
                # Campo 14 e "Modelo, no caso de REP-C". Somos REP-P:
                # fica em branco, como manda o item 16 (preencher da
                # esquerda, sobras com espaco).
                "modelo": "",
            },
        )

    def registro_empregador(self, nsr: int) -> str:
        agora = timezone.localtime()
        self._contagem["2"] += 1
        return montar_linha(
            "2",
            {
                "nsr": nsr,
                "tipo": "2",
                "data_hora": self._iso(agora),
                # Campo 4 e o CPF de quem incluiu/alterou. O registro
                # e emitido pelo proprio sistema na geracao do arquivo,
                # sem pessoa responsavel: fica zerado.
                "cpf_responsavel": "",
                "tipo_identificador": "1",
                "identificador": apenas_digitos(self.empresa.cnpj),
                "cno_caepf": apenas_digitos(self.empresa.cei_caepf),
                "razao_social": self._ascii(self.empresa.razao_social),
                "local": self._ascii(self.empresa.endereco_completo),
            },
        )

    def registro_empregado(self, nsr: int, colaborador, operacao="I") -> str:
        agora = timezone.localtime()
        self._contagem["5"] += 1
        return montar_linha(
            "5",
            {
                "nsr": nsr,
                "tipo": "5",
                "data_hora": self._iso(agora),
                "operacao": operacao,
                "cpf": self._cpf(colaborador.cpf),
                "nome": self._ascii(colaborador.nome_completo),
                "demais_dados": "",
                # Campo 8 e o CPF de quem executou a operacao no REP.
                # Registros gerados pelo proprio sistema nao tem pessoa
                # responsavel: fica zerado.
                "cpf_responsavel": "",
            },
        )

    def registro_marcacao(self, registro) -> str:
        """
        Registro tipo 7 — a marcação de ponto propriamente dita.

        O hash é o **oficial do AFD** (`hash_afd`), encadeado com o do
        registro anterior *do próprio arquivo*, e não o
        `RegistroPonto.hash_registro` do banco. Ver a explicação em
        `hash_afd`: um leva salt e não é reproduzível pelo fiscal, o
        outro é calculado só com o que está no arquivo.
        """
        self._contagem["7"] += 1

        valores = {
            "nsr": registro.nsr,
            "tipo": "7",
            "data_hora_marcacao": self._iso(registro.data_hora),
            "cpf": self._cpf(registro.colaborador.cpf),
            "data_hora_gravacao": self._iso(registro.created_at),
            "coletor": COLETOR_POR_METODO.get(registro.metodo, COLETOR["outro"]),
            # O Kronus grava a marcação no servidor em tempo real; o
            # totem não acumula batidas offline (o registro exige NSR e
            # hash do servidor). Daí sempre "0".
            "offline": "0",
        }
        valores["hash"] = hash_afd(
            hash_anterior=self._hash_anterior, **valores
        )
        self._hash_anterior = valores["hash"]
        return montar_linha("7", valores)

    def trailer(self) -> str:
        """
        Registro tipo 9.

        O "9" do tipo fica na **última** posição da linha, não na
        décima: o trailer começa com "999999999" no lugar do NSR. É a
        única linha do arquivo em que o tipo não está na posição 10.
        """
        return montar_linha(
            "9",
            {
                "nsr": 999999999,
                "qtd_tipo_2": self._contagem["2"],
                "qtd_tipo_3": self._contagem["3"],
                "qtd_tipo_4": self._contagem["4"],
                "qtd_tipo_5": self._contagem["5"],
                "qtd_tipo_6": self._contagem["6"],
                "qtd_tipo_7": self._contagem["7"],
                "tipo": "9",
            },
        )

    def assinatura_digital(self) -> str:
        """
        Linha de assinatura digital, depois do trailer (Anexo V).

        São 100 posições reservadas. O Kronus ainda **não** assina o
        arquivo com certificado ICP-Brasil — a linha sai em branco, o
        que declara a ausência em vez de simulá-la. A integridade do
        conteúdo é sustentada pelo encadeamento SHA-256 dos registros
        tipo 7, que é o que a Portaria exige do REP-P; a assinatura do
        arquivo é uma camada adicional, ainda pendente.
        """
        return montar_linha("A", {"assinatura": ""})

    # -- montagem ----------------------------------------------
    def marcacoes(self):
        """
        Marcações do período, em ordem de NSR.

        Inclui os registros **cancelados**: um ajuste não apaga a
        marcação original do AFD — ela permanece, e o cancelamento é
        rastreável pelo par de registros. Omitir seria adulterar a
        sequência de NSR.
        """
        from apps.ponto.models import RegistroPonto

        return (
            RegistroPonto.objects.filter(
                empresa=self.empresa,
                data_hora__date__gte=self.data_inicio,
                data_hora__date__lte=self.data_fim,
            )
            .select_related("colaborador", "totem")
            .order_by("nsr")
        )

    def colaboradores_do_periodo(self):
        """Empregados que aparecem no período — vão nos registros tipo 5."""
        from apps.rh.models import Colaborador

        ids = self.marcacoes().values_list("colaborador_id", flat=True).distinct()
        return Colaborador.objects.filter(pk__in=ids).order_by("cpf")

    def gerar(self) -> str:
        """
        Monta o arquivo completo.

        Zera os contadores antes de comecar: sem isso, chamar `gerar()`
        duas vezes (o que `verificar()` faz internamente) somaria as
        contagens e produziria um trailer errado — arquivo invalido
        para a fiscalizacao.
        """
        self._contagem = {chave: 0 for chave in self._contagem}
        # A cadeia de hash do AFD e por arquivo: comeca vazia a cada
        # geracao, exatamente como o fiscal a recalculara ao ler o TXT.
        self._hash_anterior = ""
        linhas = [self.cabecalho()]

        # NSR próprio para os registros administrativos (2 e 5), que não
        # compartilham a sequência das marcações.
        nsr_admin = 1
        linhas.append(self.registro_empregador(nsr_admin))
        nsr_admin += 1

        for colaborador in self.colaboradores_do_periodo():
            linhas.append(self.registro_empregado(nsr_admin, colaborador))
            nsr_admin += 1

        for registro in self.marcacoes().iterator():
            linhas.append(self.registro_marcacao(registro))

        linhas.append(self.trailer())
        linhas.append(self.assinatura_digital())
        return self.QUEBRA.join(linhas) + self.QUEBRA

    def gerar_bytes(self) -> bytes:
        # `replace` evita estourar em acentos que escaparam do _ascii.
        return self.gerar().encode(self.CODIFICACAO, errors="replace")

    def nome_arquivo(self) -> str:
        """
        Nome do arquivo (Anexo V, item 19.3).

        Para o REP-P: "AFD" + numero de registro no INPI + CNPJ/CPF do
        empregador + "REP_P". O periodo nao faz parte da regra, mas fica
        no fim porque o RH baixa varios meses e precisa distingui-los na
        pasta de downloads.
        """
        inpi = self.identificador_rep or "SEM_INPI"
        return (
            f"AFD{inpi}{apenas_digitos(self.empresa.cnpj)}REP_P_"
            f"{self.data_inicio:%Y%m%d}_{self.data_fim:%Y%m%d}.txt"
        )

    # -- verificação -------------------------------------------
    @staticmethod
    def _conferir_hashes(linhas) -> list[str]:
        """
        Recalcula a cadeia SHA-256 dos registros tipo 7 lendo so o arquivo.

        E o teste que a fiscalizacao pode reproduzir: se o encadeamento
        fecha, nenhuma marcacao foi inserida, removida ou alterada
        depois da geracao.
        """
        problemas, anterior = [], ""
        for linha in linhas:
            if tipo_da_linha(linha) != "7":
                continue
            campos = fatiar_linha(linha)
            esperado = hash_afd(
                nsr=campos["nsr"],
                tipo=campos["tipo"],
                data_hora_marcacao=campos["data_hora_marcacao"],
                cpf=campos["cpf"],
                data_hora_gravacao=campos["data_hora_gravacao"],
                coletor=campos["coletor"],
                offline=campos["offline"],
                hash_anterior=anterior,
            )
            if esperado != campos["hash"]:
                problemas.append(
                    f"NSR {campos['nsr']}: hash nao confere com o conteudo do registro"
                )
            anterior = campos["hash"]
        return problemas

    @staticmethod
    def _conferir_crc(linhas) -> list[str]:
        """Recalcula o CRC-16 dos registros 1 a 5 (Anexo V, item 17)."""
        from apps.relatorios.crc16 import crc16_hex

        problemas = []
        for numero, linha in enumerate(linhas, 1):
            tipo = tipo_da_linha(linha)
            if tipo not in ("1", "2", "3", "4", "5"):
                continue
            inicio, fim = posicao_do_campo(tipo, "crc16")
            esperado = crc16_hex(linha[:inicio] + linha[fim:])
            if linha[inicio:fim] != esperado:
                problemas.append(
                    f"linha {numero} (tipo {tipo}): CRC-16 {linha[inicio:fim]!r}, "
                    f"esperado {esperado!r}"
                )
        return problemas

    def verificar(self) -> dict:
        """
        Confere o arquivo antes de entregá-lo.

        Checa o que a fiscalização checa: tamanho de linha por tipo,
        contagem do trailer e — o mais importante — **continuidade do
        NSR**, que é o que invalida o arquivo inteiro se falhar.
        """
        conteudo = self.gerar()
        linhas = [linha for linha in conteudo.split(self.QUEBRA) if linha]

        problemas = []
        nsrs = []

        for numero, linha in enumerate(linhas, 1):
            tipo = tipo_da_linha(linha)
            if tipo not in LAYOUT:
                problemas.append(f"linha {numero}: tipo de registro desconhecido {tipo!r}")
                continue
            esperado = tamanho_da_linha(tipo)
            if len(linha) != esperado:
                problemas.append(
                    f"linha {numero} (tipo {tipo}): {len(linha)} caracteres, "
                    f"esperado {esperado}"
                )
            if tipo == "7":
                nsrs.append(int(linha[:9]))

        # Continuidade do NSR — o critério que a fiscalização aplica.
        if nsrs:
            faltando = set(range(nsrs[0], nsrs[-1] + 1)) - set(nsrs)
            if faltando:
                amostra = sorted(faltando)[:10]
                problemas.append(
                    f"NSR com lacuna: {len(faltando)} ausente(s), ex.: {amostra}"
                )
            if len(nsrs) != len(set(nsrs)):
                problemas.append("NSR repetido no arquivo")
            if nsrs != sorted(nsrs):
                problemas.append("marcações fora da ordem de NSR")

        # O trailer precisa bater com o que foi de fato escrito. Ele nao
        # e a ultima linha: depois dele vem a linha de assinatura.
        trailer = next(
            (l for l in reversed(linhas) if tipo_da_linha(l) == "9"), None
        )
        if trailer is None:
            problemas.append("arquivo sem registro trailer (tipo 9)")
        else:
            declarado = int(ler_campo(trailer, "9", "qtd_tipo_7"))
            if declarado != len(nsrs):
                problemas.append(
                    f"trailer declara {declarado} marcacoes, arquivo tem {len(nsrs)}"
                )

        # Recalcula o hash e o CRC exatamente como um auditor faria:
        # lendo so o arquivo, sem acesso ao banco. E a checagem que
        # prova que o TXT entregue se sustenta sozinho.
        problemas.extend(self._conferir_hashes(linhas))
        problemas.extend(self._conferir_crc(linhas))

        return {
            "valido": not problemas,
            "problemas": problemas,
            "linhas": len(linhas),
            "marcacoes": len(nsrs),
            "nsr_inicial": nsrs[0] if nsrs else None,
            "nsr_final": nsrs[-1] if nsrs else None,
            "bytes": len(self.gerar_bytes()),
        }

    # -- helpers -----------------------------------------------
    @staticmethod
    def _ascii(texto: str) -> str:
        """
        Remove acentos.

        O AFD é lido por sistemas legados que assumem ASCII; um "ç" em
        ISO-8859-1 mal interpretado desloca a leitura de campo fixo.
        """
        import unicodedata

        if not texto:
            return ""
        normalizado = unicodedata.normalize("NFKD", texto)
        return "".join(c for c in normalizado if not unicodedata.combining(c))
