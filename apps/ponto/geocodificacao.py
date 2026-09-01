"""
Kronus — de coordenada para endereço.

"-12.2664, -38.9663" não diz a quem confere ponto se a pessoa estava na
empresa ou em casa. "Rua Marechal Deodoro, Centro, Feira de Santana"
diz.

**Fora do caminho da batida.** A consulta ao serviço de mapas leva de
centésimos a segundos, e depende de uma rede que não é nossa. Ninguém
espera por isso para registrar ponto: a batida grava com a coordenada, e
o endereço chega depois. Se nunca chegar, a coordenada continua lá e a
tela mostra o mapa do mesmo jeito.

**Nominatim, do OpenStreetMap.** Sem chave, sem conta, sem custo — e
sem mandar a localização dos colaboradores para uma empresa que vive de
perfilar gente. A contrapartida é a política de uso: no máximo uma
consulta por segundo, e um User-Agent que identifique quem chama. As
duas coisas estão respeitadas aqui.

**Cache por coordenada arredondada.** Quem bate ponto no mesmo lugar
todo dia geraria uma consulta por batida. Arredondando a quatro casas
— cerca de onze metros —, o segundo da mesma pessoa no mesmo local já
sai do cache.
"""
import logging
import time

from django.core.cache import cache

logger = logging.getLogger("kronus.ponto")

ENDERECO_API = "https://nominatim.openstreetmap.org/reverse"

#: Identificação exigida pela política de uso do Nominatim.
#:
#: Chamada anônima é bloqueada, e com razão: sem identificar quem chama,
#: não há como avisar antes de barrar.
AGENTE = "Kronus/1.0 (ponto eletronico; suporte@kstec.online)"

#: Teto de espera. Curto: isto roda em segundo plano, mas um worker
#: preso numa conexão morta é um worker a menos para o resto.
TIMEOUT = 10

#: Casas decimais do cache. Quatro ≈ 11 metros.
CASAS = 4

#: Quanto o endereço de uma coordenada vale em cache.
#:
#: Uma semana. Rua não muda de nome com frequência, e a alternativa —
#: consultar de novo a cada batida — gastaria a cota de um serviço
#: gratuito por nada.
SEGUNDOS_EM_CACHE = 7 * 24 * 3600

#: Intervalo mínimo entre consultas, exigido pelo Nominatim.
INTERVALO_MINIMO = 1.1
_ultima_consulta = [0.0]


def _chave(latitude, longitude) -> str:
    return f"kronus:endereco:{round(float(latitude), CASAS)}:{round(float(longitude), CASAS)}"


def _resumir(dados: dict) -> str:
    """
    Monta o endereço curto, do específico para o geral.

    O `display_name` do Nominatim traz o país, o CEP e o estado inteiro
    — quinze palavras onde três bastam. Quem confere quer saber a rua e
    o bairro; o país ele já sabe.
    """
    e = dados.get("address") or {}
    partes = [
        e.get("road") or e.get("pedestrian") or e.get("suburb"),
        e.get("suburb") if e.get("road") else None,
        e.get("city") or e.get("town") or e.get("village") or e.get("municipality"),
        e.get("state"),
    ]
    vistos, limpas = set(), []
    for parte in partes:
        if parte and parte not in vistos:
            vistos.add(parte)
            limpas.append(parte)
    return ", ".join(limpas)[:255] or (dados.get("display_name") or "")[:255]


def endereco_de(latitude, longitude) -> str:
    """
    O endereço aproximado. String vazia quando não deu.

    Nunca levanta: falha aqui deixa o registro sem endereço, e o
    registro sem endereço continua sendo um registro válido.
    """
    if latitude is None or longitude is None:
        return ""

    chave = _chave(latitude, longitude)
    guardado = cache.get(chave)
    if guardado is not None:
        return guardado

    try:
        import requests

        # A política do Nominatim pede no máximo uma consulta por
        # segundo. Respeitar é o que mantém o acesso.
        espera = INTERVALO_MINIMO - (time.monotonic() - _ultima_consulta[0])
        if espera > 0:
            time.sleep(espera)
        _ultima_consulta[0] = time.monotonic()

        resposta = requests.get(
            ENDERECO_API,
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "jsonv2",
                "zoom": 18,
                "addressdetails": 1,
                "accept-language": "pt-BR",
            },
            headers={"User-Agent": AGENTE},
            timeout=TIMEOUT,
        )
        resposta.raise_for_status()
        endereco = _resumir(resposta.json())
    except Exception:
        logger.info("Não foi possível resolver o endereço de %s,%s", latitude, longitude)
        return ""

    if endereco:
        cache.set(chave, endereco, SEGUNDOS_EM_CACHE)
    return endereco
