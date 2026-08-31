"""
Kronus — o autoaprendizado nao pode contaminar o cadastro do vizinho.

Caso real: Elisangela e Edjane, irmas, ficam a 0,2630 uma da outra no
cadastro supervisionado. Sem trava, bastava uma batida em que a
semelhanca ajudasse para o rosto de uma entrar na galeria da outra.

O estrago do aprendizado errado nao e uma batida errada — e um cadastro
que passa a aceitar duas pessoas para sempre, sem que ninguem tenha
conferido. Por isso a duvida aqui bloqueia, em vez de liberar.
"""
import numpy as np
from django.test import TestCase

from apps.facial.aprendizado import (
    DISTANCIA_MINIMA_DE_OUTROS,
    _nao_aproxima_de_outro,
)


def vetor(semente, dim=512):
    v = np.random.RandomState(semente).normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def mistura(a, b, peso):
    """Vetor entre `a` e `b`: peso 0 e `a`, peso 1 e `b`."""
    v = (1 - peso) * a + peso * b
    return (v / np.linalg.norm(v)).astype(np.float32)


class ServicoFalso:
    def __init__(self, galeria, captura, falhar=False):
        self._galeria = galeria
        self._captura = captura
        self._falhar = falhar

        class Provedor:
            def gerar_embedding(_self, _bytes):
                if falhar:
                    raise RuntimeError("motor fora do ar")
                return captura

        self.provedor = Provedor()

    def candidatos(self, _empresas):
        return self._galeria

    @staticmethod
    def _distancia(a, b):
        return float(1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class Colaborador:
    def __init__(self, pk):
        self.pk = pk
        self.empresa = object()


class VizinhancaTests(TestCase):
    def setUp(self):
        self.titular = Colaborador(1)
        self.eu = vetor(1)
        self.vizinho = vetor(2)

    def test_captura_longe_de_todos_pode_ser_aprendida(self):
        galeria = {1: [self.eu], 2: [self.vizinho]}
        # Uma variacao do proprio rosto, ainda longe do vizinho.
        captura = mistura(self.eu, vetor(9), 0.25)
        servico = ServicoFalso(galeria, captura)
        self.assertTrue(_nao_aproxima_de_outro(servico, self.titular, b"x"))

    def test_captura_encostada_em_outra_pessoa_nao_entra(self):
        galeria = {1: [self.eu], 2: [self.vizinho]}
        # Quase o rosto do vizinho: e este o caso das irmas.
        captura = mistura(self.vizinho, self.eu, 0.05)
        servico = ServicoFalso(galeria, captura)
        self.assertFalse(_nao_aproxima_de_outro(servico, self.titular, b"x"))

    def test_nao_pode_estreitar_a_distancia_ja_existente(self):
        """
        Mesmo passando no minimo, a amostra nao pode empurrar os dois
        cadastros um para o outro — e assim que a confusao se instala.
        """
        eu = vetor(3)
        vizinho = mistura(eu, vetor(4), 0.55)   # ja e um vizinho proximo
        galeria = {1: [eu], 2: [vizinho]}
        captura = mistura(eu, vizinho, 0.35)    # mais perto dele que eu estava
        servico = ServicoFalso(galeria, captura)

        antes = servico._distancia(eu, vizinho)
        agora = servico._distancia(captura, vizinho)
        self.assertLess(agora, antes)   # confirma o cenario
        self.assertFalse(_nao_aproxima_de_outro(servico, self.titular, b"x"))

    def test_sozinho_na_empresa_nao_ha_de_quem_se_confundir(self):
        servico = ServicoFalso({1: [self.eu]}, mistura(self.eu, vetor(7), 0.2))
        self.assertTrue(_nao_aproxima_de_outro(servico, self.titular, b"x"))

    def test_falha_ao_medir_bloqueia_o_aprendizado(self):
        """
        Ao contrario da regra de novidade, aqui a duvida pesa contra.

        La o risco e guardar uma foto redundante; aqui e contaminar um
        cadastro de forma permanente.
        """
        galeria = {1: [self.eu], 2: [self.vizinho]}
        servico = ServicoFalso(galeria, self.eu, falhar=True)
        self.assertFalse(_nao_aproxima_de_outro(servico, self.titular, b"x"))

    def test_o_minimo_e_mais_duro_que_o_limiar_de_batida(self):
        from django.conf import settings

        self.assertGreater(
            DISTANCIA_MINIMA_DE_OUTROS, settings.FACE_RECOGNITION_THRESHOLD - 0.01
        )
