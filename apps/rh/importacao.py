"""
Kronus — importação de colaboradores por planilha (Fase 6).

Cadastrar 200 colaboradores um a um na tela é o que faz um cliente
desistir da migração. Este módulo lê um CSV e cria o quadro inteiro.

**Duas passadas, sempre.** A primeira valida tudo e não grava nada; a
segunda grava. O RH vê o laudo completo — linha por linha, com o motivo
de cada recusa — *antes* de qualquer escrita. Importar direto e parar no
erro da linha 137 deixaria 136 colaboradores criados e o arquivo pela
metade, e a segunda tentativa esbarraria em duplicidade.

**Nada é sobrescrito por engano.** Um CPF já cadastrado é reportado como
duplicado e ignorado. Atualizar em massa é outra operação, com outro
risco — trocar a data de admissão de alguém por um erro de planilha
altera o cálculo de férias e de rescisão.

Formato aceito (cabeçalho obrigatório, ordem livre, acentos opcionais):

    cpf;nome;data_nascimento;data_admissao;matricula;email;
    telefone;cargo;departamento;escala;pis;ctps;ctps_serie

Só `cpf`, `nome` e `data_admissao` são obrigatórios.
"""
import csv
import io
import logging
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

from django.db import transaction

from apps.core.utils import apenas_digitos, cpf_valido, pis_valido

logger = logging.getLogger("kronus.rh")

#: Sinônimos aceitos para cada coluna. O RH exporta do sistema antigo e
#: raramente os nomes batem — aceitar variações evita uma rodada de
#: "renomeie a coluna e tente de novo".
ALIASES = {
    "cpf": {"cpf", "cpfcolaborador", "documento", "nrcpf"},
    "nome": {"nome", "nomecompleto", "colaborador", "funcionario", "empregado"},
    "data_nascimento": {"datanascimento", "nascimento", "dtnascimento", "datadenascimento"},
    "data_admissao": {"dataadmissao", "admissao", "dtadmissao", "datadeadmissao"},
    "matricula": {"matricula", "chapa", "codigo", "registro"},
    "email": {"email", "emails", "correioeletronico"},
    "telefone": {"telefone", "celular", "fone", "contato"},
    "cargo": {"cargo", "funcao", "ocupacao"},
    "departamento": {"departamento", "setor", "area", "centrodecusto"},
    "escala": {"escala", "jornada", "horario", "turno"},
    "pis": {"pis", "pispasep", "nis", "pisPasep".lower()},
    "ctps": {"ctps", "carteira", "numeroctps"},
    "ctps_serie": {"ctpsserie", "serie", "seriectps"},
}

OBRIGATORIAS = ("cpf", "nome", "data_admissao")

FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y")


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem separador — para casar cabeçalhos."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return "".join(c for c in sem_acento.lower() if c.isalnum())


def _ler_data(valor: str):
    """Aceita os formatos que aparecem numa planilha brasileira de RH."""
    texto = (valor or "").strip()
    if not texto:
        return None
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {texto!r} (use DD/MM/AAAA)")


@dataclass
class LinhaImportacao:
    numero: int
    dados: dict
    erros: list = field(default_factory=list)
    aviso: str = ""

    @property
    def valida(self) -> bool:
        return not self.erros


@dataclass
class Laudo:
    """Resultado da conferência ou da importação."""

    colunas_reconhecidas: dict = field(default_factory=dict)
    colunas_ignoradas: list = field(default_factory=list)
    linhas: list = field(default_factory=list)
    criados: int = 0
    aplicado: bool = False

    @property
    def validas(self):
        return [l for l in self.linhas if l.valida]

    @property
    def invalidas(self):
        return [l for l in self.linhas if not l.valida]

    @property
    def total(self):
        return len(self.linhas)

    @property
    def pode_importar(self) -> bool:
        return bool(self.validas)


class ImportadorColaboradores:
    """
    Lê o CSV, valida linha a linha e — só quando mandado — grava.

        importador = ImportadorColaboradores(empresa, arquivo)
        laudo = importador.conferir()      # nada é gravado
        if laudo.pode_importar:
            laudo = importador.importar()  # grava só as linhas válidas
    """

    def __init__(self, empresa, arquivo, usuario=None):
        self.empresa = empresa
        self.usuario = usuario
        self._bruto = arquivo.read() if hasattr(arquivo, "read") else arquivo
        self._laudo = None

    # -- leitura -------------------------------------------------
    def _texto(self) -> str:
        """
        Decodifica tentando UTF-8 e caindo para Latin-1.

        Planilha exportada de sistema antigo quase sempre vem em
        Latin-1; recusar o arquivo por causa de um "ç" seria trocar um
        problema de codificação por um problema de suporte.
        """
        if isinstance(self._bruto, str):
            return self._bruto
        for codec in ("utf-8-sig", "utf-8", "iso-8859-1"):
            try:
                return self._bruto.decode(codec)
            except UnicodeDecodeError:
                continue
        return self._bruto.decode("iso-8859-1", errors="replace")

    @staticmethod
    def _dialeto(amostra: str):
        """Descobre se o separador é `;` ou `,`."""
        try:
            return csv.Sniffer().sniff(amostra, delimiters=";,\t")
        except csv.Error:
            # O padrão brasileiro é `;` — o Excel pt-BR usa ponto e
            # vírgula porque a vírgula é separador decimal.
            class Padrao(csv.Dialect):
                delimiter = ";"
                quotechar = '"'
                doublequote = True
                skipinitialspace = True
                lineterminator = "\r\n"
                quoting = csv.QUOTE_MINIMAL

            return Padrao

    def _mapear_colunas(self, cabecalho):
        """Casa cada coluna do arquivo com um campo conhecido."""
        reconhecidas, ignoradas = {}, []
        for indice, bruto in enumerate(cabecalho or []):
            chave = _normalizar(bruto)
            destino = next(
                (campo for campo, nomes in ALIASES.items() if chave in nomes), None
            )
            if destino and destino not in reconhecidas:
                reconhecidas[destino] = indice
            else:
                ignoradas.append(bruto)
        return reconhecidas, ignoradas

    # -- conferência ---------------------------------------------
    def conferir(self) -> Laudo:
        """Valida tudo sem gravar nada."""
        if self._laudo is not None:
            return self._laudo

        texto = self._texto()
        leitor = csv.reader(io.StringIO(texto), dialect=self._dialeto(texto[:4096]))

        try:
            cabecalho = next(leitor)
        except StopIteration:
            laudo = Laudo()
            laudo.linhas.append(
                LinhaImportacao(0, {}, ["arquivo vazio"])
            )
            self._laudo = laudo
            return laudo

        colunas, ignoradas = self._mapear_colunas(cabecalho)
        laudo = Laudo(colunas_reconhecidas=colunas, colunas_ignoradas=ignoradas)

        faltando = [c for c in OBRIGATORIAS if c not in colunas]
        if faltando:
            laudo.linhas.append(
                LinhaImportacao(
                    0, {},
                    [f"colunas obrigatórias ausentes: {', '.join(faltando)}"],
                )
            )
            self._laudo = laudo
            return laudo

        from apps.rh.models import Colaborador

        ja_cadastrados = set(
            Colaborador.objects.filter(empresa=self.empresa).values_list("cpf", flat=True)
        )
        vistos_no_arquivo = set()

        for numero, bruta in enumerate(leitor, start=2):
            if not any((celula or "").strip() for celula in bruta):
                continue
            linha = self._validar(bruta, numero, colunas, ja_cadastrados, vistos_no_arquivo)
            laudo.linhas.append(linha)
            if linha.valida:
                vistos_no_arquivo.add(linha.dados["cpf"])

        self._laudo = laudo
        return laudo

    def _validar(self, bruta, numero, colunas, ja_cadastrados, vistos):
        def celula(campo):
            indice = colunas.get(campo)
            if indice is None or indice >= len(bruta):
                return ""
            return (bruta[indice] or "").strip()

        erros, dados = [], {}

        cpf = apenas_digitos(celula("cpf"))
        if not cpf:
            erros.append("CPF vazio")
        elif not cpf_valido(cpf):
            erros.append(f"CPF inválido: {celula('cpf')}")
        elif cpf in ja_cadastrados:
            erros.append("CPF já cadastrado nesta empresa")
        elif cpf in vistos:
            erros.append("CPF repetido dentro do arquivo")
        dados["cpf"] = cpf

        nome = celula("nome")
        if len(nome) < 3:
            erros.append("nome ausente ou muito curto")
        dados["nome_completo"] = nome[:150]

        for campo, destino, obrigatorio in (
            ("data_admissao", "data_admissao", True),
            ("data_nascimento", "data_nascimento", False),
        ):
            try:
                valor = _ler_data(celula(campo))
            except ValueError as erro:
                erros.append(f"{campo}: {erro}")
                valor = None
            if obrigatorio and valor is None:
                erros.append(f"{campo} é obrigatória")
            dados[destino] = valor

        admissao = dados.get("data_admissao")
        if admissao and admissao > date.today():
            erros.append("data de admissão no futuro")

        nascimento = dados.get("data_nascimento")
        if nascimento and admissao and nascimento >= admissao:
            erros.append("nascimento posterior à admissão")

        pis = apenas_digitos(celula("pis"))
        if pis and not pis_valido(pis):
            erros.append(f"PIS inválido: {celula('pis')}")
        dados["pis_pasep"] = pis

        dados["matricula"] = celula("matricula")[:20]
        dados["email"] = celula("email")[:254]
        dados["telefone"] = celula("telefone")[:20]
        dados["cargo"] = celula("cargo")[:100]
        dados["ctps"] = celula("ctps")[:20]
        dados["ctps_serie"] = celula("ctps_serie")[:10]
        dados["_departamento"] = celula("departamento")
        dados["_escala"] = celula("escala")

        return LinhaImportacao(numero, dados, erros)

    # -- gravação ------------------------------------------------
    @transaction.atomic
    def importar(self) -> Laudo:
        """
        Grava as linhas válidas. As inválidas são apenas relatadas.

        Roda numa transação: se algo inesperado explodir no meio, nada
        fica gravado e o RH pode corrigir o arquivo e repetir sem
        precisar limpar cadastros parciais.
        """
        laudo = self.conferir()
        if not laudo.pode_importar:
            return laudo

        from apps.ponto.models import EscalaTrabalho
        from apps.rh.models import Colaborador, Departamento

        departamentos = {
            _normalizar(d.nome): d
            for d in Departamento.objects.filter(empresa=self.empresa)
        }
        escalas = {
            _normalizar(e.nome): e
            for e in EscalaTrabalho.objects.filter(empresa=self.empresa)
        }

        criados = 0
        for linha in laudo.validas:
            dados = dict(linha.dados)
            nome_depto = dados.pop("_departamento", "")
            nome_escala = dados.pop("_escala", "")

            departamento = departamentos.get(_normalizar(nome_depto))
            escala = escalas.get(_normalizar(nome_escala))

            avisos = []
            if nome_depto and departamento is None:
                # Não criamos departamento por conta própria: a estrutura
                # organizacional é decisão do RH, e um erro de digitação
                # viraria um departamento fantasma no relatório.
                avisos.append(f"departamento '{nome_depto}' não existe — deixado em branco")
            if nome_escala and escala is None:
                avisos.append(f"escala '{nome_escala}' não existe — deixada em branco")

            Colaborador.objects.create(
                empresa=self.empresa,
                departamento=departamento,
                escala=escala,
                **dados,
            )
            linha.aviso = "; ".join(avisos)
            criados += 1

        laudo.criados = criados
        laudo.aplicado = True
        logger.info(
            "Importação de colaboradores em %s: %s criados, %s recusados.",
            self.empresa.cnpj, criados, len(laudo.invalidas),
        )
        return laudo


def modelo_csv() -> str:
    """Planilha-modelo para download, já com uma linha de exemplo."""
    return (
        "cpf;nome;data_nascimento;data_admissao;matricula;email;telefone;"
        "cargo;departamento;escala;pis;ctps;ctps_serie\r\n"
        "529.982.247-25;João da Silva Souza;12/03/1990;01/02/2024;0001;"
        "joao@empresa.com.br;(73) 99999-0000;Analista;Administrativo;"
        "Comercial;120.4567.890-5;1234567;001\r\n"
    )
