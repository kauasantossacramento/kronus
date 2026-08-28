"""
Kronus — identificacao do colaborador sem conexao.

O totem precisa reconhecer quem digitou CPF e data de nascimento com o
link caido, e para isso guarda uma lista local. Guardar CPF em claro
nessa lista seria despejar a base de documentos da empresa num tablet de
portaria — aparelho compartilhado, roubavel e sem custodia.

**O problema real.** Para conferir sem conexao, o aparelho precisa
guardar algo que ele mesmo saiba recalcular. Qualquer coisa assim pode
ser atacada por quem tiver o aparelho, porque o espaco de CPFs validos e
pequeno o bastante para ser varrido — cerca de um bilhao, e menos ainda
com a data de nascimento restringindo.

**A saida nao e esconder, e encarecer.** Guardamos uma derivacao lenta
(PBKDF2-SHA256, muitas iteracoes) com sal por equipamento. Conferir uma
digitacao custa **uma** derivacao — cerca de um decimo de segundo, que
ninguem percebe. Varrer o espaco inteiro custa esse decimo vezes um
bilhao: inviavel com o aparelho na mao.

O sal nao e segredo; ele viaja junto com a lista. Quem protege e a
quantidade de iteracoes. O sal existe para que a lista de um totem nao
sirva a outro, e para que rotacionar o token invalide a lista inteira —
que e o comportamento desejado quando um equipamento e perdido.
"""
import hashlib

from django.conf import settings

#: Iteracoes do PBKDF2.
#:
#: Alto o bastante para tornar a varredura do espaco de CPFs inviavel, e
#: baixo o bastante para uma conferencia nao travar a fila da portaria.
#: Em tablet de baixo custo, ~150 mil iteracoes ficam abaixo de 300 ms.
ITERACOES = 150_000


def sal_do_totem(totem) -> str:
    """
    Sal por equipamento, derivado do token e do segredo do servidor.

    Nao e segredo — viaja com a lista. Serve para isolar equipamentos e
    para que a rotacao do token invalide o que ficou no aparelho.
    """
    material = f"{totem.token_acesso}|{settings.SECRET_KEY}".encode()
    return hashlib.sha256(material).hexdigest()[:32]


def resumo_de_identificacao(totem, cpf: str, data_nascimento) -> str:
    """
    Derivacao de CPF + data de nascimento, para conferencia local.

    A data entra junto porque ela ja e o segundo fator do registro por
    CPF: sem ela, conhecer o CPF de um colega bastaria para bater o ponto
    no lugar dele.
    """
    from apps.core.utils import apenas_digitos

    digitos = apenas_digitos(cpf or "")
    nascimento = data_nascimento.isoformat() if data_nascimento else ""
    entrada = f"{digitos}|{nascimento}".encode()

    derivado = hashlib.pbkdf2_hmac(
        "sha256", entrada, sal_do_totem(totem).encode(), ITERACOES, dklen=32
    )
    return derivado.hex()
