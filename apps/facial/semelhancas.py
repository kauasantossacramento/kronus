"""
Kronus — quem se parece com quem, e o que fazer a respeito.

Semelhanca entre cadastros nao e defeito do sistema: irmaos existem, e
duas pessoas parecidas continuam sendo duas pessoas. O que o painel
precisa responder nao e "ha semelhanca?", e sim **"esta semelhanca ja
esta atrapalhando, e o que resolve?"**.

Por isso cada par vem com uma acao concreta. Um painel que mostra o
problema e nao diz o que fazer transfere para quem le um trabalho que o
sistema tem como fazer sozinho — e, na pratica, ninguem faz.

O calculo e caro (todos contra todos) e o resultado muda pouco: fica em
cache, e a tela oferece recalcular.
"""
import itertools
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("kronus.facial")

#: Quanto tempo o levantamento vale.
#:
#: Um cadastro novo muda o quadro, e o cache e invalidado junto com o do
#: reconhecimento. Fora disso, meia hora e mais que suficiente: ninguem
#: acompanha semelhanca de minuto em minuto.
SEGUNDOS_EM_CACHE = 1800


class Gravidade:
    """Quao perto e perto demais."""

    CRITICA = "critica"
    ATENCAO = "atencao"
    OBSERVAR = "observar"

    ROTULOS = {
        CRITICA: "Crítica",
        ATENCAO: "Atenção",
        OBSERVAR: "Observar",
    }


def _gravidade(distancia: float, limiar: float, margem: float) -> str | None:
    """
    Traduz a distancia em quanto isto importa.

    Os cortes saem das regras que ja decidem no reconhecimento, e nao de
    numeros escolhidos para o painel: abaixo do limiar as duas pessoas
    disputam a mesma batida; abaixo de `limiar - margem` a disputa vira
    recusa frequente. Um painel com escala propria diria uma coisa e o
    totem faria outra.
    """
    if distancia < limiar:
        return Gravidade.CRITICA
    if distancia < limiar + margem:
        return Gravidade.ATENCAO
    if distancia < limiar + margem * 2:
        return Gravidade.OBSERVAR
    return None


def _acoes(gravidade: str, a: dict, b: dict) -> list[str]:
    """
    O que resolve **este** par.

    Ordenado do que resolve mais para o que resolve menos, e citando o
    lado mais fraco primeiro: refazer o cadastro pior e o que muda o
    quadro com menos trabalho.
    """
    pior = a if a["amostras"] <= b["amostras"] else b
    outro = b if pior is a else a
    acoes = []

    if gravidade == Gravidade.CRITICA:
        acoes.append(
            f"Refazer a biometria de {pior['nome']} no totem, de frente e "
            "com luz uniforme — é o que mais separa os dois."
        )
        acoes.append(
            f"Se continuar perto, refazer também a de {outro['nome']}."
        )
    else:
        acoes.append(
            f"Refazer a biometria de {pior['nome']} quando for conveniente."
        )

    if pior["amostras"] < settings.FACE_AMOSTRAS_MAXIMAS:
        acoes.append(
            f"{pior['nome']} tem {pior['amostras']} amostra(s); completar as "
            f"{settings.FACE_AMOSTRAS_MAXIMAS} poses dá mais material para distinguir."
        )

    if gravidade == Gravidade.CRITICA:
        acoes.append(
            "Enquanto isso o ponto continua seguro: a regra de margem "
            "recusa e pede nova tentativa em vez de escolher entre os dois."
        )
    return acoes


def levantar(empresa, *, usar_cache: bool = True) -> dict:
    """
    Pares de colaboradores perigosamente proximos, com o que fazer.

    Compara a **menor** distancia entre as amostras de cada dupla, que e
    exatamente o que o reconhecimento usa para decidir: comparar medias
    daria um numero mais bonito e menos verdadeiro.
    """
    chave = f"kronus:semelhancas:{empresa.pk}"
    if usar_cache:
        guardado = cache.get(chave)
        if guardado is not None:
            return guardado

    from apps.facial.services import FaceRecognitionService
    from apps.rh.models import Colaborador

    servico = FaceRecognitionService()
    galeria = servico.candidatos([empresa])

    pessoas = {
        c.pk: {
            "id": c.pk,
            "nome": c.nome_exibicao,
            "amostras": len(galeria.get(c.pk) or []),
        }
        for c in Colaborador.objects.filter(
            pk__in=list(galeria), ativo=True
        )
    }

    limiar = settings.FACE_RECOGNITION_THRESHOLD
    margem = settings.FACE_MARGEM_MINIMA

    pares = []
    for (pk1, v1), (pk2, v2) in itertools.combinations(galeria.items(), 2):
        if pk1 not in pessoas or pk2 not in pessoas:
            continue
        try:
            distancia = min(
                servico._distancia(a, b) for a in v1 for b in v2
            )
        except Exception:
            logger.exception("Falha ao comparar %s com %s", pk1, pk2)
            continue

        gravidade = _gravidade(distancia, limiar, margem)
        if gravidade is None:
            continue

        a, b = pessoas[pk1], pessoas[pk2]
        pares.append({
            "a": a,
            "b": b,
            "distancia": round(distancia, 4),
            "gravidade": gravidade,
            "rotulo": Gravidade.ROTULOS[gravidade],
            "acoes": _acoes(gravidade, a, b),
        })

    pares.sort(key=lambda p: p["distancia"])

    resultado = {
        "empresa_id": empresa.pk,
        "empresa": empresa.nome_exibicao,
        "cadastrados": len(pessoas),
        "comparacoes": len(pessoas) * (len(pessoas) - 1) // 2,
        "pares": pares,
        "criticos": sum(1 for p in pares if p["gravidade"] == Gravidade.CRITICA),
        "limiar": limiar,
        "margem": margem,
    }
    cache.set(chave, resultado, SEGUNDOS_EM_CACHE)
    return resultado


def esquecer(empresa_id) -> None:
    """Descarta o levantamento — chamado quando a galeria muda."""
    cache.delete(f"kronus:semelhancas:{empresa_id}")
