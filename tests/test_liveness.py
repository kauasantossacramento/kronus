"""
Kronus — testes da prova de vida.

O ataque que importa: alguém aponta uma foto impressa ou a tela de um
celular para a câmera do totem e bate o ponto do colega. Estes testes
verificam que a sequência de quadros distingue isso de uma pessoa.

Também travam o que a implementação **não** promete: vídeo gravado
passa, e o teste diz isso em voz alta para ninguém confundir esta camada
com prova de vida forte.
"""
import io

import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from apps.facial.liveness import DESAFIOS, LivenessRecusado, LivenessService


def quadro(brilho=128, deslocamento=0, ruido=0, tamanho=(320, 240)):
    """
    Gera um quadro sintético.

    `deslocamento` move um retângulo — simula o rosto mudando de posição.
    `ruido` adiciona granulação, como a de um sensor barato.
    """
    imagem = Image.new("RGB", tamanho, (brilho, brilho, brilho))
    pixels = imagem.load()
    x0 = 80 + deslocamento
    for x in range(max(0, x0), min(tamanho[0], x0 + 120)):
        for y in range(60, 180):
            pixels[x, y] = (brilho // 2, brilho // 3, brilho // 4)

    if ruido:
        gerador = np.random.default_rng(ruido)
        for _ in range(600):
            x = int(gerador.integers(0, tamanho[0]))
            y = int(gerador.integers(0, tamanho[1]))
            pixels[x, y] = tuple(int(v) for v in gerador.integers(0, 255, 3))

    saida = io.BytesIO()
    imagem.save(saida, format="JPEG", quality=88)
    return saida.getvalue()


class ProvedorAusente:
    """Motor indisponível: a prova de vida cai só no sinal de movimento."""

    disponivel = False

    def gerar_embedding(self, dados):
        raise AssertionError("nao deveria ser chamado")

    @staticmethod
    def distancia_cosseno(a, b):
        return 0.0


class ProvedorFalso:
    """Motor que devolve um vetor derivado dos bytes, para testar continuidade."""

    def __init__(self, distancia=0.1):
        self.disponivel = True
        self._distancia = distancia

    def gerar_embedding(self, dados):
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)

    def distancia_cosseno(self, a, b):
        return self._distancia


class MovimentoTests(SimpleTestCase):
    def servico(self):
        return LivenessService(provedor=ProvedorAusente())

    def test_foto_parada_e_recusada(self):
        """
        O ataque principal: uma foto impressa ou uma tela parada geram
        quadros praticamente idênticos.
        """
        identicos = [quadro() for _ in range(4)]
        with self.assertRaises(LivenessRecusado) as contexto:
            self.servico().verificar(identicos)
        self.assertEqual(contexto.exception.codigo, "sem_movimento")

    def test_pessoa_que_se_move_e_aprovada(self):
        movendo = [quadro(deslocamento=d) for d in (0, 14, 28, 42)]
        laudo = self.servico().verificar(movendo)
        self.assertTrue(laudo["aprovado"])
        self.assertGreater(laudo["movimento"], 0)

    def test_ruido_de_sensor_nao_conta_como_vida(self):
        """
        Sem reduzir a resolução antes de comparar, a granulação de uma
        câmera barata sozinha passaria por movimento.
        """
        so_ruido = [quadro(ruido=semente) for semente in (1, 2, 3, 4)]
        with self.assertRaises(LivenessRecusado) as contexto:
            self.servico().verificar(so_ruido)
        self.assertEqual(contexto.exception.codigo, "sem_movimento")

    def test_cena_trocada_por_completo_e_recusada(self):
        """Câmera coberta ou trocada no meio da sequência."""
        caotico = [
            quadro(brilho=20), quadro(brilho=240),
            quadro(brilho=15), quadro(brilho=250),
        ]
        with self.assertRaises(LivenessRecusado) as contexto:
            self.servico().verificar(caotico)
        self.assertEqual(contexto.exception.codigo, "movimento_excessivo")

    def test_sequencia_curta_e_recusada(self):
        with self.assertRaises(LivenessRecusado) as contexto:
            self.servico().verificar([quadro(), quadro(deslocamento=20)])
        self.assertEqual(contexto.exception.codigo, "quadros_insuficientes")


class ContinuidadeTests(SimpleTestCase):
    def quadros(self):
        return [quadro(deslocamento=d) for d in (0, 14, 28, 42)]

    def test_mesma_pessoa_atravessa(self):
        servico = LivenessService(provedor=ProvedorFalso(distancia=0.12))
        laudo = servico.verificar(self.quadros())
        self.assertTrue(laudo["aprovado"])
        self.assertEqual(laudo["distancia_entre_quadros"], 0.12)

    def test_troca_de_pessoa_no_meio_e_recusada(self):
        """Mostra o próprio rosto, depois troca por uma foto."""
        servico = LivenessService(provedor=ProvedorFalso(distancia=0.9))
        with self.assertRaises(LivenessRecusado) as contexto:
            servico.verificar(self.quadros())
        self.assertEqual(contexto.exception.codigo, "pessoa_trocou")

    def test_sem_motor_a_continuidade_e_omitida(self):
        """
        Com o motor fora, a prova de vida se apoia só no movimento e diz
        isso no laudo — em vez de fingir que verificou.
        """
        laudo = LivenessService(provedor=ProvedorAusente()).verificar(self.quadros())
        self.assertIsNone(laudo["distancia_entre_quadros"])


class DesafioTests(SimpleTestCase):
    def test_ha_mais_de_um_desafio(self):
        """
        Um gesto fixo seria gravado uma vez e reproduzido para sempre.
        """
        self.assertGreater(len(DESAFIOS), 1)

    def test_desafio_vai_para_o_laudo(self):
        quadros = [quadro(deslocamento=d) for d in (0, 14, 28)]
        laudo = LivenessService(provedor=ProvedorAusente()).verificar(
            quadros, desafio="virar_esquerda"
        )
        self.assertEqual(laudo["desafio"], "virar_esquerda")


class LimitacoesConhecidasTests(SimpleTestCase):
    """
    O que esta camada NÃO impede — documentado como teste para que a
    limitação não se perca e ninguém a confunda com prova de vida forte.
    """

    def test_video_gravado_passaria(self):
        """
        Um vídeo do colega virando a cabeça produz movimento real e
        continuidade real: passa nos dois sinais.

        Deter isso exige análise de textura (moiré, reflexo de tela) ou
        sensor de profundidade. Está fora do escopo desta camada, e o
        texto da tela de configuração diz isso ao administrador.
        """
        como_video = [quadro(deslocamento=d) for d in (0, 14, 28, 42)]
        laudo = LivenessService(provedor=ProvedorFalso(distancia=0.1)).verificar(
            como_video
        )
        self.assertTrue(
            laudo["aprovado"],
            "confirma a limitacao conhecida: video gravado atravessa",
        )
