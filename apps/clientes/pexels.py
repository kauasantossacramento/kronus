"""
Kronus — busca imagens da tela ociosa no Pexels.

**Por que os termos sao curados, e nao genericos.** Buscar "manha"
devolve despertador, transito e gente correndo — o oposto do que uma
tela de recepcao deve transmitir as 7h. O que serve e luz, calma e
comeco; o que atrapalha e pressa. Cada periodo tem uma lista escrita
para isso, e nao um termo unico.

**Por que a paisagem importa.** A imagem fica atras da logo da empresa,
do relogio e do aviso de toque. Foto com rosto grande, texto embutido ou
muito contraste no centro briga com tudo isso. Por isso a busca pede
paisagem, e a escolha prefere o que tem area livre.

**Sobre credito.** A licenca do Pexels dispensa atribuicao, entao o
totem nao mostra nada. O registro de onde veio fica guardado assim
mesmo: um ano depois, "de onde e esta foto?" precisa ter resposta.
"""
import logging

logger = logging.getLogger("kronus.ambiente")

ENDERECO = "https://api.pexels.com/v1/search"

#: Quanto esperar pela API.
#:
#: Curto: isto roda numa tarefa de fundo, e uma busca que trava segura o
#: worker que tambem cuida de outras coisas.
TIMEOUT = 20

#: Termos por periodo, escritos para o que a tela precisa transmitir.
#:
#: Em ingles porque o acervo do Pexels e indexado assim — busca em
#: portugues devolve uma fracao do catalogo, e pior.
TERMOS = {
    # Sol, jardim, arvore, natureza.
    #
    # A primeira lista trouxe muita nevoa e campo aberto — bonito, mas
    # cinzento e sem vida, o oposto do que uma tela de recepcao deve
    # transmitir as 7h. Verde e luz direta dizem "comeco"; neblina diz
    # "ainda nao acordei".
    "manha": [
        "morning sunlight through trees",
        "garden morning sunlight flowers",
        "green trees sunny morning",
        "sunlight forest path green",
        "morning garden nature fresh",
        "sunrise over green field",
        "sunny park trees morning",
    ],
    "tarde": [
        "afternoon light nature",
        "calm blue sky clouds",
        "green field afternoon",
        "soft daylight landscape",
        "peaceful lake day",
        "warm afternoon nature",
    ],
    "noite": [
        "night sky stars",
        "calm night landscape",
        "moonlight nature",
        "dark blue night sky",
        "quiet night city lights",
        "starry night mountains",
    ],
}

#: O que nao serve, mesmo vindo na busca.
#:
#: Rosto grande compete com a logo; texto embutido conflita com o aviso
#: de toque; e imagem muito clara na noite quebra a intencao do periodo.
#: Filtrar pelo que a API ja informa evita baixar para depois descartar.
LARGURA_MINIMA = 1600


def _requests():
    """Import tardio: o modulo e usado so na importacao, nao no request."""
    import requests

    return requests


def buscar(periodo: str, *, por_termo: int = 3, chave: str = None) -> list[dict]:
    """
    Devolve candidatas do periodo, ja filtradas.

    Uma lista de dicionarios com o que interessa: id na origem, endereco
    do arquivo, autor e pagina. Nao baixa nada — quem decide o que
    guardar e o comando, que tambem sabe o que ja existe.
    """
    from django.conf import settings

    chave = chave or getattr(settings, "PEXELS_API_KEY", "")
    if not chave:
        logger.info("Sem PEXELS_API_KEY: busca automática desligada.")
        return []

    termos = TERMOS.get(periodo, [])
    if not termos:
        return []

    requests = _requests()
    achadas = []
    vistos = set()

    for termo in termos:
        try:
            resposta = requests.get(
                ENDERECO,
                headers={"Authorization": chave},
                params={
                    "query": termo,
                    "orientation": "landscape",
                    "size": "large",
                    "per_page": por_termo,
                },
                timeout=TIMEOUT,
            )
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception:
            # Um termo que falha nao pode derrubar a importacao inteira:
            # os outros cinco ainda trazem material.
            logger.exception("Falha ao buscar '%s' no Pexels.", termo)
            continue

        for foto in dados.get("photos", []):
            identificador = str(foto.get("id", ""))
            if not identificador or identificador in vistos:
                continue
            if (foto.get("width") or 0) < LARGURA_MINIMA:
                continue
            arquivo = (foto.get("src") or {}).get("large2x") or (
                foto.get("src") or {}
            ).get("large")
            if not arquivo:
                continue
            vistos.add(identificador)
            achadas.append({
                "id_externo": identificador,
                "url_arquivo": arquivo,
                "autor": (foto.get("photographer") or "")[:120],
                "fonte": (foto.get("url") or "")[:500],
                "titulo": (foto.get("alt") or "")[:120],
                "termo": termo,
            })

    return achadas


def baixar(url: str) -> bytes | None:
    """O arquivo em si. `None` quando nao deu — sem levantar."""
    try:
        requests = _requests()
        resposta = requests.get(url, timeout=TIMEOUT)
        resposta.raise_for_status()
        return resposta.content
    except Exception:
        logger.exception("Falha ao baixar %s", url)
        return None
