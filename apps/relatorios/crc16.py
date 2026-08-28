"""
Kronus — CRC-16 dos registros do AFD (Portaria 671/2021, Anexo V, item 17).

    "Para os registros dos tipos '1' a '5' deve ser gravado o Código de
     Verificação de Redundância, utilizando o CRC-16 (Cyclic Redundancy
     Check) do registro."

A variante é a **CRC-16/KERMIT** (também chamada CCITT-TRUE), confirmada
no material de Perguntas e Respostas do próprio Ministério do Trabalho:

    polinômio  0x1021, refletido como 0x8408
    inicial    0x0000
    refletido  entrada e saída
    xor final  0x0000

Não confundir com a "CRC-16/CCITT-FALSE", que usa inicial 0xFFFF e não
reflete — é a confusão mais comum, e produz um valor completamente
diferente para o mesmo registro.

O resultado vai no arquivo como **4 dígitos hexadecimais maiúsculos**,
que é o tamanho reservado ao campo em todos os registros de 1 a 5.
"""
#: Tabela pré-calculada do polinômio refletido 0x8408. Calcular bit a
#: bit funcionaria, mas o AFD de uma empresa grande tem dezenas de
#: milhares de linhas e cada uma passa por aqui.
_TABELA: list[int] = []
for _byte in range(256):
    _valor = _byte
    for _ in range(8):
        _valor = (_valor >> 1) ^ 0x8408 if _valor & 1 else _valor >> 1
    _TABELA.append(_valor)


def crc16(dados: bytes | str, codificacao: str = "iso-8859-1") -> int:
    """CRC-16/KERMIT dos bytes informados."""
    if isinstance(dados, str):
        dados = dados.encode(codificacao, errors="replace")

    registrador = 0x0000
    for octeto in dados:
        registrador = (registrador >> 8) ^ _TABELA[(registrador ^ octeto) & 0xFF]
    return registrador & 0xFFFF


def crc16_hex(dados: bytes | str, codificacao: str = "iso-8859-1") -> str:
    """
    CRC-16 formatado para o arquivo: 4 hexadecimais maiúsculos.

    O cálculo é feito sobre o registro **sem o campo de CRC** — o campo
    é o resultado, não entra no próprio cálculo.
    """
    return f"{crc16(dados, codificacao):04X}"
