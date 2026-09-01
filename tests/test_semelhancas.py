"""
Kronus — painel de semelhancas entre cadastros.

Semelhanca nao e defeito: irmaos existem, e duas pessoas parecidas
continuam sendo duas pessoas. O painel nao existe para denunciar
semelhanca, e sim para responder se ela ja atrapalha e o que resolve.

O caso que motivou: Elisangela e Edjane, irmas, a 0,2630 uma da outra.
"""
import numpy as np
from django.test import TestCase, override_settings

from apps.facial.semelhancas import Gravidade, _acoes, _gravidade


class GravidadeTests(TestCase):
    """
    Os cortes saem das regras que ja decidem no reconhecimento.

    Um painel com escala propria diria uma coisa e o totem faria outra.
    """

    def test_abaixo_do_limiar_e_critico(self):
        # Aqui as duas pessoas disputam a mesma batida.
        self.assertEqual(_gravidade(0.2630, 0.45, 0.10), Gravidade.CRITICA)
        self.assertEqual(_gravidade(0.4499, 0.45, 0.10), Gravidade.CRITICA)

    def test_dentro_da_margem_e_atencao(self):
        self.assertEqual(_gravidade(0.50, 0.45, 0.10), Gravidade.ATENCAO)

    def test_acima_da_margem_nao_entra_no_painel(self):
        """
        A terceira faixa saiu.

        Ia ate duas margens acima do limiar e sinalizava 62 dos 120 pares
        de uma empresa real — mais da metade. Um aviso que aparece em 52%
        dos casos deixa de ser aviso, e o efeito medido foi o oposto do
        pretendido: quem abriu a tela concluiu que havia gente batendo
        ponto pelos outros.
        """
        self.assertIsNone(_gravidade(0.60, 0.45, 0.10))
        self.assertIsNone(_gravidade(0.90, 0.45, 0.10))

    def test_o_rotulo_fala_da_consequencia_e_nao_do_susto(self):
        """
        "Crítica" foi lido como "alguem bate pelo outro" — o oposto do
        que acontece: nessa faixa o totem recusa e pede de novo.
        """
        rotulo = Gravidade.ROTULOS[Gravidade.CRITICA]
        self.assertNotIn("rítica", rotulo)
        self.assertIn("repetição", rotulo)
        explicacao = Gravidade.EXPLICACOES[Gravidade.CRITICA]
        self.assertIn("Ninguém bate pelo outro", explicacao)


class AcoesTests(TestCase):
    """Cada par vem com o que fazer, e nao so com o problema."""

    def setUp(self):
        self.magro = {"id": 1, "nome": "Edjane", "amostras": 2}
        self.cheio = {"id": 2, "nome": "Elisangela", "amostras": 5}

    def test_manda_refazer_primeiro_o_cadastro_mais_fraco(self):
        # Refazer o pior e o que muda o quadro com menos trabalho.
        acoes = _acoes(Gravidade.CRITICA, self.magro, self.cheio)
        self.assertIn("Edjane", acoes[0])

    def test_a_ordem_dos_argumentos_nao_muda_a_recomendacao(self):
        a = _acoes(Gravidade.CRITICA, self.magro, self.cheio)
        b = _acoes(Gravidade.CRITICA, self.cheio, self.magro)
        self.assertEqual(a, b)

    def test_avisa_quando_faltam_poses(self):
        acoes = " ".join(_acoes(Gravidade.CRITICA, self.magro, self.cheio))
        self.assertIn("amostra", acoes)

    def test_no_caso_critico_diz_que_o_ponto_segue_seguro(self):
        """
        Sem isto, quem le o painel conclui que ha fraude acontecendo.

        A regra de margem recusa e pede nova tentativa em vez de
        escolher entre os dois — e quem esta olhando precisa saber.
        """
        acoes = " ".join(_acoes(Gravidade.CRITICA, self.magro, self.cheio))
        self.assertIn("recusa", acoes.lower())

    def test_par_menos_grave_nao_alarma(self):
        acoes = " ".join(_acoes(Gravidade.ATENCAO, self.magro, self.cheio))
        self.assertIn("conveniente", acoes)
