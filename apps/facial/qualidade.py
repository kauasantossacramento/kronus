"""
Kronus — qualidade do reconhecimento facial ao longo do tempo.

O cadastro facial nao envelhece de uma vez: a pessoa deixa a barba
crescer, troca de armacao, muda de cor de cabelo, e a distancia entre o
rosto do dia e o vetor guardado sobe devagar. Enquanto ela fica abaixo do
limiar, o ponto e registrado normalmente e ninguem percebe nada — ate o
dia em que passa do limiar e a pessoa comeca a bater o ponto pelo CPF.

O que este modulo faz e enxergar essa subida **antes** dela virar
reclamacao, olhando a distancia media das ultimas identificacoes bem
sucedidas de cada colaborador.

Nao ha modelo novo: `TentativaReconhecimento.distancia` ja e gravada a
cada reconhecimento desde o inicio.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count, Max, Min
from django.utils import timezone

logger = logging.getLogger("kronus.facial")

#: Quanto da folga ate o limiar ja foi consumida.
#:
#: Com limiar 0,68, "atencao" comeca em 0,54 e "critico" em 0,61. Os
#: cortes sao proporcionais ao limiar configurado, e nao numeros fixos,
#: para que mexer no limiar nao invalide silenciosamente o alerta.
FRACAO_ATENCAO = 0.80
FRACAO_CRITICO = 0.90

#: Amostra minima para opinar. Duas ou tres identificacoes dizem mais
#: sobre a iluminacao do dia do que sobre o cadastro.
MINIMO_DE_AMOSTRAS = 8

#: Janela observada. Curta demais capta ruido; longa demais dilui a
#: mudanca recente, que e justamente o que interessa detectar.
DIAS_OBSERVADOS = 45


class Situacao:
    BOA = "boa"
    ATENCAO = "atencao"
    CRITICA = "critica"

    ROTULOS = {
        BOA: "Boa",
        ATENCAO: "Atenção",
        CRITICA: "Crítica",
    }


def limiar() -> float:
    """
    Limiar de correspondencia em uso.

    Lido do settings, e nao instanciando o servico: instanciar carrega o
    provedor facial, que no worker dedicado significa subir o modelo —
    caro demais para responder uma pergunta que e um numero.
    """
    return settings.FACE_RECOGNITION_THRESHOLD


def classificar(distancia_media: float, corte: float = None) -> str:
    corte = corte or limiar()
    if distancia_media >= corte * FRACAO_CRITICO:
        return Situacao.CRITICA
    if distancia_media >= corte * FRACAO_ATENCAO:
        return Situacao.ATENCAO
    return Situacao.BOA


def avaliar(empresa=None, dias: int = DIAS_OBSERVADOS) -> list[dict]:
    """
    Distancia media por colaborador nas identificacoes recentes.

    Devolve a lista ordenada da pior para a melhor, para que a tela e o
    alerta comecem por quem esta mais perto de parar de ser reconhecido.
    """
    from apps.facial.models import TentativaReconhecimento

    corte = limiar()
    desde = timezone.now() - timedelta(days=dias)

    consulta = TentativaReconhecimento.objects.filter(
        resultado=TentativaReconhecimento.Resultado.IDENTIFICADO,
        colaborador__isnull=False,
        distancia__isnull=False,
        created_at__gte=desde,
    )
    if empresa is not None:
        consulta = consulta.filter(empresa=empresa)

    agrupado = (
        consulta.values(
            "colaborador_id",
            "colaborador__nome_completo",
            "colaborador__empresa__razao_social",
        )
        .annotate(
            amostras=Count("id"),
            media=Avg("distancia"),
            pior=Max("distancia"),
            melhor=Min("distancia"),
            ultima=Max("created_at"),
        )
        .filter(amostras__gte=MINIMO_DE_AMOSTRAS)
    )

    resultado = []
    for linha in agrupado:
        situacao = classificar(linha["media"], corte)
        resultado.append({
            "colaborador_id": linha["colaborador_id"],
            "nome": linha["colaborador__nome_completo"],
            "empresa": linha["colaborador__empresa__razao_social"],
            "amostras": linha["amostras"],
            "media": round(linha["media"], 3),
            "pior": round(linha["pior"], 3),
            "melhor": round(linha["melhor"], 3),
            "ultima": linha["ultima"],
            "situacao": situacao,
            "rotulo": Situacao.ROTULOS[situacao],
            # Quanto da folga ate o limiar ja foi consumida, em %. E o
            # numero que responde "quanto falta para parar de funcionar".
            "folga_consumida": round(100 * linha["media"] / corte),
        })

    resultado.sort(key=lambda item: item["media"], reverse=True)
    return resultado


def em_risco(empresa=None) -> list[dict]:
    """Somente quem precisa de acao — atencao ou pior."""
    return [
        item for item in avaliar(empresa)
        if item["situacao"] in (Situacao.ATENCAO, Situacao.CRITICA)
    ]


def resumo(empresa=None) -> dict:
    """Contagem por situacao, para o cabecalho da tela."""
    avaliados = avaliar(empresa)
    contagem = {Situacao.BOA: 0, Situacao.ATENCAO: 0, Situacao.CRITICA: 0}
    for item in avaliados:
        contagem[item["situacao"]] += 1
    return {
        "total": len(avaliados),
        "boa": contagem[Situacao.BOA],
        "atencao": contagem[Situacao.ATENCAO],
        "critica": contagem[Situacao.CRITICA],
        "limiar": limiar(),
        "dias": DIAS_OBSERVADOS,
        "minimo_amostras": MINIMO_DE_AMOSTRAS,
        "itens": avaliados,
    }
