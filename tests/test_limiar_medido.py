"""
Kronus — o limiar vem da medicao, e nao de estimativa.

Vinte e cinco tentativas num dia de uso real, com seis pessoas
cadastradas, separaram-se assim:

    reconhecimentos legitimos    0,11 a 0,40
    falsos positivos             0,505 · 0,512 · 0,516
    recusas corretas             0,52 a 0,65

Ha um vao limpo entre 0,40 e 0,50. O limiar precisa cair dentro dele.
"""
from django.conf import settings
from django.test import TestCase

#: Extremos observados em producao, 31/08.
PIOR_LEGITIMO = 0.3955
MELHOR_FALSO_POSITIVO = 0.5047


class LimiarTests(TestCase):
    def test_o_limiar_cai_dentro_do_vao_medido(self):
        limiar = settings.FACE_RECOGNITION_THRESHOLD
        self.assertGreater(
            limiar, PIOR_LEGITIMO,
            "abaixo disto, quem foi reconhecido de verdade passa a falhar",
        )
        self.assertLess(
            limiar, MELHOR_FALSO_POSITIVO,
            "acima disto, os falsos positivos medidos voltam a passar",
        )

    def test_ha_folga_para_os_dois_lados(self):
        """
        Encostar num dos extremos deixaria o sistema a um centesimo de
        errar — que foi exatamente o caso do limiar anterior.
        """
        limiar = settings.FACE_RECOGNITION_THRESHOLD
        self.assertGreaterEqual(limiar - PIOR_LEGITIMO, 0.03)
        self.assertGreaterEqual(MELHOR_FALSO_POSITIVO - limiar, 0.03)

    def test_os_falsos_positivos_do_dia_seriam_recusados(self):
        for distancia in (0.5047, 0.5117, 0.5162):
            self.assertGreaterEqual(
                distancia, settings.FACE_RECOGNITION_THRESHOLD,
                f"{distancia} voltaria a registrar ponto no nome errado",
            )

    def test_os_acertos_do_dia_continuam_passando(self):
        for distancia in (0.1127, 0.1622, 0.3124, 0.3666, 0.3955):
            self.assertLess(
                distancia, settings.FACE_RECOGNITION_THRESHOLD,
                f"{distancia} era um reconhecimento correto e passaria a falhar",
            )
