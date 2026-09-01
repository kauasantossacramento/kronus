"""
Kronus — o cadastro facial está melhorando?

O autoaprendizado promete que o cadastro acompanha a pessoa: cabelo que
muda, óculos novo, barba que cresceu. A promessa é fácil de fazer e
difícil de verificar — e um sistema que aprende sozinho sem ninguém
conseguir olhar é um sistema em que se acredita, não um que se sabe.

**O que esta tela responde.** Duas coisas, e as duas por pessoa:

  1. o reconhecimento dela está mais folgado do que estava?
  2. ela está mais distante das outras pessoas do que estava?

A primeira é conforto — distância menor significa reconhecer de
primeira, sem repetir. A segunda é segurança: aprender pode aproximar
alguém de um sósia, e a trava que impede isso precisa ser conferida, não
suposta.

**De onde vêm os dados.** Das tentativas já gravadas — nenhuma coleta
nova. Cada batida registra a distância, então a série existe desde
sempre; o que faltava era ler.

**Por que mediana, e não média.** Uma batida ruim isolada — quadro
tremido, alguém passando atrás — puxa a média e some na mediana. O que
interessa é como a pessoa é reconhecida no dia típico, não no pior.
"""
import statistics
from datetime import timedelta

#: Quantos dias formam cada lado da comparação.
#:
#: Sete de cada lado: menos que isso e um dia atípico decide o
#: resultado; muito mais e a comparação atrasa tanto que deixa de
#: apontar o efeito de um recadastro recente.
JANELA_EM_DIAS = 7

#: Mínimo de batidas em cada lado para a comparação valer.
#:
#: Com duas ou três, a mediana é a própria batida. Preferir dizer "ainda
#: não dá para saber" a apresentar um número que parece medição e não é.
MINIMO_DE_BATIDAS = 4

#: Variação abaixo disto é ruído, não tendência.
#:
#: A distância oscila naturalmente com luz e ângulo. Sem um piso,
#: qualquer flutuação viraria seta para cima ou para baixo, e a tela
#: passaria a mostrar movimento onde não houve nenhum.
VARIACAO_RELEVANTE = 0.02


def _mediana(valores):
    return statistics.median(valores) if valores else None


def evolucao_de(colaborador, *, ate=None) -> dict:
    """
    Como o reconhecimento desta pessoa mudou entre duas semanas.

    Compara a semana que terminou agora com a anterior. Devolve
    `situacao` já interpretada — quem lê a tela quer saber se melhorou,
    não calcular a diferença.
    """
    from django.utils import timezone

    from apps.facial.models import FaceRegistro, TentativaReconhecimento as T

    fim = ate or timezone.now()
    meio = fim - timedelta(days=JANELA_EM_DIAS)
    inicio = meio - timedelta(days=JANELA_EM_DIAS)

    def distancias(desde, ate_):
        return list(
            T.objects.filter(
                colaborador=colaborador,
                resultado=T.Resultado.IDENTIFICADO,
                distancia__isnull=False,
                created_at__gte=desde,
                created_at__lt=ate_,
            ).values_list("distancia", flat=True)
        )

    antes = distancias(inicio, meio)
    agora = distancias(meio, fim)

    aprendidas = FaceRegistro.objects.filter(
        colaborador=colaborador, ativo=True, aprendida=True
    ).count()
    supervisionadas = FaceRegistro.objects.filter(
        colaborador=colaborador, ativo=True, aprendida=False
    ).count()

    base = {
        "colaborador": colaborador,
        "batidas_antes": len(antes),
        "batidas_agora": len(agora),
        "amostras_aprendidas": aprendidas,
        "amostras_supervisionadas": supervisionadas,
        "mediana_antes": None,
        "mediana_agora": None,
        "variacao": None,
        "situacao": "sem_dados",
    }

    if len(antes) < MINIMO_DE_BATIDAS or len(agora) < MINIMO_DE_BATIDAS:
        # Dizer "ainda não dá para saber" e não um numero que parece
        # medicao e nao e.
        base["situacao"] = "poucas_batidas"
        base["mediana_agora"] = _mediana(agora)
        return base

    m_antes = _mediana(antes)
    m_agora = _mediana(agora)
    variacao = m_agora - m_antes

    if variacao <= -VARIACAO_RELEVANTE:
        situacao = "melhorou"
    elif variacao >= VARIACAO_RELEVANTE:
        situacao = "piorou"
    else:
        situacao = "estavel"

    base.update({
        "mediana_antes": round(m_antes, 4),
        "mediana_agora": round(m_agora, 4),
        "variacao": round(variacao, 4),
        "situacao": situacao,
    })
    return base


def panorama(empresa, *, ate=None) -> dict:
    """
    A evolução de todo mundo da empresa, do pior para o melhor.

    Ordenado pela distância atual, e não pela variação: quem está longe
    hoje é quem incomoda hoje, mesmo tendo melhorado desde a semana
    passada.
    """
    from apps.rh.models import Colaborador

    pessoas = Colaborador.objects.filter(
        empresa=empresa, ativo=True, face_registrada=True
    ).order_by("nome_completo")

    linhas = [evolucao_de(p, ate=ate) for p in pessoas]

    def chave(linha):
        # Sem dado vai para o fim: não é problema, é ausência de
        # informação, e misturar os dois esconde quem precisa de ação.
        atual = linha["mediana_agora"]
        return (atual is None, -(atual or 0))

    linhas.sort(key=chave)

    com_medida = [x for x in linhas if x["situacao"] in
                  ("melhorou", "piorou", "estavel")]
    return {
        "empresa": empresa,
        "linhas": linhas,
        "medidos": len(com_medida),
        "melhoraram": sum(1 for x in com_medida if x["situacao"] == "melhorou"),
        "pioraram": sum(1 for x in com_medida if x["situacao"] == "piorou"),
        "estaveis": sum(1 for x in com_medida if x["situacao"] == "estavel"),
        "aprendendo": sum(1 for x in linhas if x["amostras_aprendidas"]),
        "janela": JANELA_EM_DIAS,
    }
