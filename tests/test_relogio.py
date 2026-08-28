"""
Kronus — verificacao do sincronismo com a Hora Legal Brasileira.

Anexo IX, requisito 2. Configurar o NTP atende metade do requisito; a
outra metade e perceber quando ele para. Sem isto, o relogio pode derivar
por semanas com as batidas sendo gravadas normalmente — com hora errada.
"""
from unittest import mock

from django.test import TestCase

from apps.ponto import relogio

SAIDA_REAL = """LinkNTPServers=
SystemNTPServers=a.st1.ntp.br b.st1.ntp.br c.st1.ntp.br d.st1.ntp.br
ServerName=a.st1.ntp.br
ServerAddress=2001:12ff:0:7::186
NTPMessage={ Leap=0, Version=4, Mode=4, Stratum=1, Precision=-22, RootDelay=0, RootDispersion=1.144ms, Reference=ONBR, Ignored=no, PacketCount=14, Jitter=756us }
Frequency=24350
"""


class FonteTests(TestCase):
    """
    A saida usada aqui foi copiada da VPS em producao — nao inventada.
    Um formato suposto passaria no teste e falharia no servidor.
    """

    def _com_saida(self, saida=SAIDA_REAL):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=saida)
            return relogio.fonte_configurada()

    def test_le_o_servidor(self):
        self.assertEqual(self._com_saida()["servidor"], "a.st1.ntp.br")

    def test_le_o_estrato_e_a_referencia(self):
        info = self._com_saida()
        self.assertEqual(info["estrato"], 1)
        self.assertEqual(info["referencia"], "ONBR")

    def test_reconhece_que_a_fonte_e_o_observatorio_nacional(self):
        """`ONBR` e estrato 1 sao a prova documental exigida pelo Anexo IX."""
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=SAIDA_REAL)
            with mock.patch.object(relogio, "medir_desvio", return_value=0.003):
                estado = relogio.estado_do_relogio()
        self.assertTrue(estado["fonte_e_o_on"])

    def test_fonte_qualquer_nao_passa_por_observatorio(self):
        saida = SAIDA_REAL.replace("Stratum=1", "Stratum=3").replace(
            "Reference=ONBR", "Reference=10.0.0.1"
        ).replace("ServerName=a.st1.ntp.br", "ServerName=ntp.ubuntu.com")
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=saida)
            with mock.patch.object(relogio, "medir_desvio", return_value=0.003):
                estado = relogio.estado_do_relogio()
        self.assertFalse(estado["fonte_e_o_on"])

    def test_sem_systemd_nao_estoura(self):
        with mock.patch("subprocess.run", side_effect=OSError("sem timedatectl")):
            info = relogio.fonte_configurada()
        self.assertEqual(info["servidor"], "")


class DesvioTests(TestCase):
    def _estado(self, desvio):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=SAIDA_REAL)
            with mock.patch.object(relogio, "medir_desvio", return_value=desvio):
                return relogio.estado_do_relogio()

    def test_desvio_pequeno_fica_dentro_do_limite(self):
        estado = self._estado(0.004)
        self.assertTrue(estado["dentro_do_limite"])

    def test_desvio_grande_estoura(self):
        estado = self._estado(12.4)
        self.assertFalse(estado["dentro_do_limite"])
        self.assertAlmostEqual(estado["desvio_segundos"], 12.4, places=1)

    def test_atrasado_ou_adiantado_conta_pelo_modulo(self):
        self.assertAlmostEqual(self._estado(-9.0)["desvio_segundos"], 9.0, places=1)

    def test_alerta_bem_antes_do_limite_legal(self):
        self.assertLess(
            relogio.DESVIO_ALERTA_SEGUNDOS, relogio.DESVIO_LEGAL_SEGUNDOS
        )

    def test_servidor_mudo_e_informacao_e_nao_erro(self):
        """Rede fora tambem impede manter o sincronismo."""
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=SAIDA_REAL)
            with mock.patch.object(relogio, "medir_desvio", return_value=None):
                estado = relogio.estado_do_relogio()

        self.assertIsNone(estado["desvio_segundos"])
        self.assertIn("respondeu", estado["erro"])


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
        self.assertIn("18", aviso.mensagem)
