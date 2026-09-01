"""
Kronus — o que a tela ociosa mostra agora.

Monta o conteudo do periodo corrente para um totem. Fica separado dos
modelos porque a regra e de apresentacao, nao de dado: o que muda com o
tempo aqui e o gosto, e o modelo nao deve mudar junto.
"""
import random

from django.core.cache import cache

#: Quanto tempo o conjunto montado vale.
#:
#: Curto de proposito. Uma frase adicionada pelo master, ou uma imagem
#: que o cliente escondeu, precisa sumir da tela em minutos — nao no
#: proximo turno. E a consulta e pequena: dezenas de linhas, indexadas.
SEGUNDOS_EM_CACHE = 300

#: Quantas frases e imagens vao para o totem de uma vez.
#:
#: O totem alterna entre elas sozinho, sem voltar ao servidor. Mandar o
#: acervo inteiro gastaria banda de um equipamento que costuma estar em
#: rede fraca; mandar duas faria o rodizio ficar obvio.
QUANTAS_FRASES = 8
QUANTAS_IMAGENS = 6


def conteudo_para(empresa, *, hora: int) -> dict:
    """
    Frases e imagens do periodo, ja filtradas para esta empresa.

    Devolve `{}` quando a empresa desligou o recurso — e o totem, ao
    receber vazio, simplesmente nao mostra nada a mais. Nao ha estado
    intermediario para o cliente lidar.
    """
    from apps.clientes.ambiente import FraseAmbiente, ImagemAmbiente, periodo_de

    if not getattr(empresa, "telas_ambiente", False):
        return {}
    if empresa.modo_slides == empresa.ModoDosSlides.SOMENTE_MEUS:
        return {}

    periodo = periodo_de(hora)
    chave = f"kronus:ambiente:{empresa.pk}:{periodo}"
    guardado = cache.get(chave)
    if guardado is not None:
        return guardado

    # A dica de saude entra em qualquer periodo: beber agua e
    # alimentar-se bem nao tem hora. Ela alterna com a saudacao do
    # periodo em vez de virar categoria propria — uma tela que so da
    # conselho de saude cansa.
    frases = list(
        FraseAmbiente.objects.filter(ativo=True, periodo=periodo)
        .exclude(tipo=FraseAmbiente.Tipo.SAUDE)
        .values_list("texto", flat=True)
    )
    # Filtrada pelo periodo tambem.
    #
    # Sem o filtro, um periodo sem nenhuma frase ainda recebia dicas de
    # outro — e "bom dia" as 22h nasce assim. A dica de saude vale em
    # qualquer hora, e por isso o acervo a cadastra em todos os
    # periodos; puxar sem filtrar era resolver duas vezes a mesma coisa,
    # e errado na segunda.
    saude = list(
        FraseAmbiente.objects.filter(
            ativo=True, periodo=periodo, tipo=FraseAmbiente.Tipo.SAUDE
        ).values_list("texto", flat=True)
    )

    escolhidas = random.sample(frases, min(len(frases), QUANTAS_FRASES - 2))
    escolhidas += random.sample(saude, min(len(saude), 2))
    random.shuffle(escolhidas)

    ocultas = set(
        empresa.imagens_ambiente_ocultas.values_list("imagem_id", flat=True)
    )
    disponiveis = [
        img for img in ImagemAmbiente.objects.filter(ativo=True, periodo=periodo)
        if img.pk not in ocultas and img.imagem
    ]
    sorteadas = random.sample(
        disponiveis, min(len(disponiveis), QUANTAS_IMAGENS)
    )

    conteudo = {
        "periodo": periodo,
        "frases": escolhidas,
        # Sem credito na tela: a licenca do Pexels dispensa atribuicao,
        # e um rodape de credito numa tela vista de longe so tira espaco
        # do que a pessoa precisa ler. A procedencia continua guardada no
        # acervo, para quem precisar conferir.
        "imagens": [
            {"url": img.imagem.url, "clara": img.clara} for img in sorteadas
        ],
        # O totem precisa saber se pode misturar com os slides da
        # empresa ou se o acervo e o unico conteudo.
        "exclusivo": empresa.modo_slides == empresa.ModoDosSlides.SOMENTE_ACERVO,
    }
    cache.set(chave, conteudo, SEGUNDOS_EM_CACHE)
    return conteudo


def esquecer(empresa_id=None) -> None:
    """Descarta o conjunto montado — chamado quando o acervo muda."""
    from apps.clientes.ambiente import Periodo

    if empresa_id is None:
        from apps.clientes.models import Empresa

        alvos = Empresa.objects.values_list("pk", flat=True)
    else:
        alvos = [empresa_id]
    for pk in alvos:
        for periodo in Periodo.values:
            cache.delete(f"kronus:ambiente:{pk}:{periodo}")
