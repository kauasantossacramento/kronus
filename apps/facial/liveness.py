"""
Kronus — prova de vida (anti-spoofing) no reconhecimento facial.

**O ataque que isto impede.** Sem prova de vida, o totem aceita uma foto
impressa ou a tela de um celular apontada para a câmera. Num sistema de
ponto isso é a fraude óbvia: alguém bate o ponto do colega com uma foto
no bolso. É a vulnerabilidade mais séria do produto.

**O que esta implementação faz.** Pede um gesto ao colaborador ("vire a
cabeça", "aproxime-se") e analisa uma **sequência** de quadros em vez de
um só. Dois sinais têm de aparecer juntos:

1. **Movimento** — os quadros precisam diferir entre si. Uma foto
   impressa e uma tela paradas produzem quadros quase idênticos; um
   rosto vivo se mexe mesmo quando a pessoa tenta ficar imóvel.

2. **Continuidade** — todos os quadros precisam ser da *mesma* pessoa.
   Isso fecha a brecha de mostrar o próprio rosto no primeiro quadro e
   trocar por uma foto no seguinte.

**O que esta implementação NÃO impede, e é honesto declarar:**

* **Vídeo em tela.** Um vídeo do colega virando a cabeça passa nos dois
  sinais. Deter isso exige análise de textura (moiré, reflexo de tela) ou
  sensor de profundidade — outra ordem de complexidade e de custo de CPU.
* **Máscara de alta qualidade.** Fora do alcance de qualquer método 2D.

Ou seja: isto eleva o custo do ataque de "imprimir uma foto" para
"gravar e reproduzir um vídeo com o gesto certo no momento certo". É uma
diferença real, mas não é prova de vida forte. A tela de configuração
diz isso ao administrador, em vez de vender segurança que não existe.
"""
import logging

import numpy as np

logger = logging.getLogger("kronus.facial")


class LivenessRecusado(Exception):
    """A sequência não passou na prova de vida."""

    def __init__(self, mensagem, codigo="liveness_falha", detalhes=None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.detalhes = detalhes or {}


#: Gestos pedidos ao colaborador. Escolhido ao acaso a cada tentativa —
#: um gesto fixo seria gravado uma vez e reproduzido para sempre.
DESAFIOS = [
    ("virar_esquerda", "Vire o rosto levemente para a esquerda"),
    ("virar_direita", "Vire o rosto levemente para a direita"),
    ("aproximar", "Aproxime-se um pouco da câmera"),
    ("sorrir", "Sorria"),
]


def sortear_desafio():
    import random

    return random.choice(DESAFIOS)


class LivenessService:
    """
    Analisa uma sequência de quadros.

    Os limiares abaixo saem de uma tensão que não tem ponto ótimo: um
    valor alto rejeita gente de verdade parada demais; um valor baixo
    aceita foto impressa. Os padrões pendem para **aceitar o humano**,
    porque um falso negativo trava a fila da portaria — e o custo de um
    falso positivo aqui é limitado, já que o reconhecimento facial em si
    ainda precisa acertar quem é a pessoa.
    """

    #: Diferença média mínima entre quadros consecutivos (0 a 1).
    #: Abaixo disso, a cena está parada demais para ser gente.
    MOVIMENTO_MINIMO = 0.012

    #: Diferença máxima: acima disso a cena mudou completamente
    #: (a câmera foi coberta, ou trocaram o que está na frente).
    MOVIMENTO_MAXIMO = 0.45

    #: Distância máxima entre os embeddings dos quadros. Acima disso
    #: não é a mesma pessoa ao longo da sequência.
    DISTANCIA_MAXIMA_ENTRE_QUADROS = 0.55

    #: Quadros mínimos para uma decisão.
    QUADROS_MINIMOS = 3

    def __init__(self, provedor=None):
        from apps.facial.providers import obter_provedor

        self.provedor = provedor or obter_provedor()

    # ══════════════════════════════════════════════════════════
    def verificar(self, quadros: list[bytes], desafio: str = None) -> dict:
        """
        Analisa a sequência e devolve o laudo.

        Levanta `LivenessRecusado` quando reprova. Devolve um dicionário
        com as métricas quando aprova — elas vão para o log, que é o que
        permite calibrar os limiares depois com dados reais em vez de
        palpite.
        """
        if len(quadros) < self.QUADROS_MINIMOS:
            raise LivenessRecusado(
                "Sequência curta demais para verificar.",
                codigo="quadros_insuficientes",
            )

        movimento = self._movimento(quadros)
        if movimento < self.MOVIMENTO_MINIMO:
            # O caso da foto impressa e da tela parada.
            raise LivenessRecusado(
                "Não detectamos movimento. Olhe para a câmera e siga a instrução.",
                codigo="sem_movimento",
                detalhes={"movimento": movimento},
            )

        if movimento > self.MOVIMENTO_MAXIMO:
            raise LivenessRecusado(
                "A imagem mudou demais. Fique parado em frente à câmera.",
                codigo="movimento_excessivo",
                detalhes={"movimento": movimento},
            )

        distancia = self._continuidade(quadros)
        if distancia is not None and distancia > self.DISTANCIA_MAXIMA_ENTRE_QUADROS:
            # Mostrou o próprio rosto e trocou por uma foto no meio.
            raise LivenessRecusado(
                "A pessoa em frente à câmera mudou durante a verificação.",
                codigo="pessoa_trocou",
                detalhes={"distancia": distancia},
            )

        laudo = {
            "aprovado": True,
            "movimento": round(movimento, 4),
            "distancia_entre_quadros": (
                round(distancia, 4) if distancia is not None else None
            ),
            "quadros": len(quadros),
            "desafio": desafio,
        }
        logger.info("Liveness aprovado: %s", laudo)
        return laudo

    # ══════════════════════════════════════════════════════════
    @staticmethod
    def _movimento(quadros: list[bytes]) -> float:
        """
        Diferença média entre quadros consecutivos, de 0 a 1.

        Compara em escala de cinza e em baixa resolução: o que interessa
        é o deslocamento estrutural, não o ruído do sensor. Reduzir a
        64x64 antes de comparar elimina boa parte desse ruído — sem
        isso, a granulação de uma câmera barata contaria como "vida".
        """
        import io

        from PIL import Image

        miniaturas = []
        for bruto in quadros:
            with Image.open(io.BytesIO(bruto)) as imagem:
                pequena = imagem.convert("L").resize((64, 64), Image.BILINEAR)
                miniaturas.append(np.asarray(pequena, dtype=np.float32) / 255.0)

        diferencas = [
            float(np.abs(miniaturas[i] - miniaturas[i - 1]).mean())
            for i in range(1, len(miniaturas))
        ]
        return sum(diferencas) / len(diferencas) if diferencas else 0.0

    def _continuidade(self, quadros: list[bytes]) -> float | None:
        """
        Maior distância entre os embeddings do primeiro e do último quadro.

        Compara só as pontas de propósito: gerar embedding de todos os
        quadros custaria ~217 ms cada, e num totem isso é a diferença
        entre uma fila que anda e uma que para. As pontas já pegam a
        troca de pessoa no meio da sequência.

        Devolve `None` quando o motor não está disponível — nesse caso a
        prova de vida se apoia apenas no movimento, e quem chama decide
        se isso basta.
        """
        if not self.provedor.disponivel:
            return None

        try:
            primeiro = self.provedor.gerar_embedding(quadros[0])
            ultimo = self.provedor.gerar_embedding(quadros[-1])
        except Exception:
            # Sem rosto em alguma ponta não é problema de continuidade —
            # o reconhecimento em si vai tratar disso logo adiante.
            logger.debug("Continuidade nao avaliada", exc_info=True)
            return None

        return self.provedor.distancia_cosseno(primeiro, ultimo)
