"""
Kronus — verificacao do sincronismo com a Hora Legal Brasileira.

Anexo IX, requisito 2. Configurar o NTP atende metade do requisito; a
outra metade e perceber quando ele para. Sem isto, o relogio pode derivar
por semanas com as batidas sendo gravadas normalmente — com hora errada.
"""
from unittest import mock

from django.test import TestCase

from apps.ponto import relogio


class ConversaoTests(TestCase):
    def test_le_as_unidades_do_systemd(self):
        self.assertAlmostEqual(relogio._para_segundos("+1.5ms"), 0.0015)
        self.assertAlmostEqual(relogio._para_segundos("-250us"), -0.00025)
        self.assertAlmostEqual(relogio._para_segundos("2.5s"), 2.5)
        self.assertAlmostEqual(relogio._para_segundos("100ns"), 1e-7)


class EstadoDoRelogioTests(TestCase):
    def _saida(self, offset):
        return (
            "ServerName=a.st1.ntp.br\n"
            "ServerAddress=200.160.7.186\n"
            f"NTPMessage={{ Leap=0, offset={offset}, delay=20ms }}\n"
        )

    def _rodar(self, offset):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=self._saida(offset))
            return relogio.estado_do_relogio()

    def test_desvio_pequeno_fica_dentro_do_limite(self):
        estado = self._rodar("+3.2ms")

        self.assertTrue(estado["dentro_do_limite"])
        self.assertEqual(estado["servidor"], "a.st1.ntp.br")
        self.assertLess(estado["desvio_segundos"], 0.01)

    def test_desvio_grande_estoura_o_limite(self):
        estado = self._rodar("+12.4s")

        self.assertFalse(estado["dentro_do_limite"])
        self.assertAlmostEqual(estado["desvio_segundos"], 12.4, places=1)

    def test_desvio_negativo_conta_pelo_modulo(self):
        """Adiantado ou atrasado, o que importa e a distancia."""
        estado = self._rodar("-9.0s")

        self.assertFalse(estado["dentro_do_limite"])
        self.assertAlmostEqual(estado["desvio_segundos"], 9.0, places=1)

    def test_alerta_bem_antes_do_limite_legal(self):
        """
        Alertar so aos 30s seria alertar quando ja se esta em
        descumprimento. O objetivo e agir antes.
        """
        self.assertLess(
            relogio.DESVIO_ALERTA_SEGUNDOS, relogio.DESVIO_LEGAL_SEGUNDOS
        )

    def test_sem_a_ferramenta_nao_estoura(self):
        """Falha ao medir nao pode derrubar nada — ela e o proprio alerta."""
        with mock.patch("subprocess.run", side_effect=OSError("sem timedatectl")):
            estado = relogio.estado_do_relogio()

        self.assertIsNone(estado["desvio_segundos"])
        self.assertIn("não foi possível", estado["erro"])


class TarefaTests(TestCase):
    def _master(self):
        from apps.accounts.models import CustomUser
        from apps.core.constants import TipoUsuario

        return CustomUser.objects.create_user(
            email="m@kstec.online", password="x", nome_completo="Master",
            tipo=TipoUsuario.MASTER, is_staff=True, is_superuser=True,
        )

    def test_relogio_certo_nao_gera_alerta(self):
        from apps.notificacoes.models import Notificacao
        from apps.ponto.tasks import verificar_relogio

        self._master()
        with mock.patch(
            "apps.ponto.relogio.estado_do_relogio",
            return_value={"dentro_do_limite": True, "desvio_segundos": 0.004,
                          "servidor": "a.st1.ntp.br", "erro": ""},
        ):
            verificar_relogio()

        self.assertFalse(Notificacao.objects.exists())

    def test_deriva_avisa_o_master(self):
        from apps.notificacoes.models import Notificacao
        from apps.ponto.tasks import verificar_relogio

        master = self._master()
        with mock.patch(
            "apps.ponto.relogio.estado_do_relogio",
            return_value={"dentro_do_limite": False, "desvio_segundos": 18.0,
                          "servidor": "a.st1.ntp.br", "erro": ""},
        ):
            verificar_relogio()

        aviso = Notificacao.objects.filter(destinatario=master).first()
        self.assertIsNotNone(aviso)
        self.assertIn("sincronismo", aviso.titulo.lower())
        self.assertIn("18", aviso.mensagem)
