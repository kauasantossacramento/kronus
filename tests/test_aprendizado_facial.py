"""
Kronus — o cadastro facial aprende com as batidas.

Aprender com o proprio resultado e realimentacao: se uma identificacao
errada virar referencia, o erro deixa de ser um episodio e passa a ser o
cadastro. O que estes testes guardam sao as travas — nao o "aprendeu?",
mas o "recusou aprender quando devia recusar?".
"""
from django.test import TestCase

from apps.facial.aprendizado import (
    FRACAO_PARA_APRENDER,
    MARGEM_PARA_APRENDER,
    MAXIMO_APRENDIDAS,
    pode_aprender,
)
from apps.facial.services import ResultadoReconhecimento


def resultado(distancia, segunda=None, identificado=True):
    r = ResultadoReconhecimento(identificado=identificado, distancia=distancia)
    r.segunda_distancia = segunda
    return r


class TravasTests(TestCase):
    LIMIAR = 0.52

    def test_aprende_com_folga_larga(self):
        # 0,15 esta bem abaixo da metade do limiar, e o segundo colocado
        # a 0,60 nao deixa duvida.
        self.assertTrue(pode_aprender(resultado(0.15, 0.60), self.LIMIAR))

    def test_nao_aprende_com_acerto_no_fio(self):
        """
        0,45 passa no limiar e registra o ponto. Nao vira referencia:
        um acerto apertado gravado como cadastro empurra a pessoa para
        mais perto de quem ela ja quase se confundiu.
        """
        self.assertFalse(pode_aprender(resultado(0.45, 0.90), self.LIMIAR))

    def test_nao_aprende_com_segundo_colocado_perto(self):
        # Passou, mas podia ter sido sorte — e sorte nao se grava.
        self.assertFalse(pode_aprender(resultado(0.15, 0.25), self.LIMIAR))

    def test_nao_aprende_com_quem_nao_foi_identificado(self):
        self.assertFalse(
            pode_aprender(resultado(0.15, 0.90, identificado=False), self.LIMIAR)
        )

    def test_sozinho_na_galeria_ainda_aprende(self):
        # Sem segundo colocado nao ha de quem se afastar; o que decide e
        # a folga ate o limiar.
        self.assertTrue(pode_aprender(resultado(0.12, None), self.LIMIAR))

    def test_a_faixa_de_aprendizado_e_metade_do_limiar(self):
        # Fixado porque e o numero que separa "acerto folgado" de
        # "acerto qualquer": medido em producao, as identificacoes
        # legitimas ficam entre 0,08 e 0,29.
        self.assertLessEqual(FRACAO_PARA_APRENDER, 0.5)

    def test_a_margem_para_aprender_e_maior_que_a_do_ponto(self):
        from django.conf import settings

        self.assertGreater(MARGEM_PARA_APRENDER, settings.FACE_MARGEM_MINIMA)


class MaioriaSupervisionadaTests(TestCase):
    """
    O cadastro original e supervisionado: alguem viu quem estava na
    frente da camera. As aprendidas nao. A maioria precisa continuar
    sendo a que foi conferida.
    """

    def test_o_limite_deixa_a_maioria_supervisionada(self):
        from django.conf import settings

        maximo = settings.FACE_AMOSTRAS_MAXIMAS
        self.assertLess(
            MAXIMO_APRENDIDAS, maximo - MAXIMO_APRENDIDAS,
            "com este limite, as aprendidas passariam a ser maioria",
        )


class DesligadoPorPadraoTests(TestCase):
    def test_a_empresa_precisa_ligar(self):
        from apps.clientes.models import Empresa

        campo = Empresa._meta.get_field("aprendizado_facial")
        self.assertFalse(
            campo.default,
            "aprender com o proprio resultado e realimentacao: quem liga "
            "precisa saber que ligou",
        )

    def test_a_amostra_registra_de_onde_veio(self):
        from apps.facial.models import FaceRegistro

        campo = FaceRegistro._meta.get_field("aprendida")
        self.assertFalse(campo.default)
