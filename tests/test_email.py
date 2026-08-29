"""
Kronus — o remetente e a configuracao de saida de e-mail.

Escrito depois de descobrir que producao rodava com o backend de
console: nenhum e-mail saia do servidor. Redefinicao de senha, senha
provisoria e espelho fechado eram impressos no log e perdidos — e o
sintoma, para quem esperava, era "o sistema nao mandou nada".
"""
from django.test import TestCase, override_settings


class ConfiguracaoDeSaidaTests(TestCase):
    def test_ssl_e_tls_nunca_ficam_os_dois_ligados(self):
        """
        O Django recusa a inicializacao com os dois marcados, e a porta
        465 fala SSL desde o primeiro byte enquanto a 587 sobe para TLS
        depois. Derivar da porta evita duas chaves que discordam.
        """
        from django.conf import settings

        self.assertFalse(settings.EMAIL_USE_SSL and settings.EMAIL_USE_TLS)

    def test_o_remetente_padrao_existe(self):
        # Sem remetente, o envio falha na hora — e falha depois de a
        # senha ja ter sido trocada, deixando a pessoa sem como entrar.
        from django.conf import settings

        self.assertTrue(settings.DEFAULT_FROM_EMAIL)
        self.assertIn("@", settings.DEFAULT_FROM_EMAIL)

    def test_a_senha_nao_esta_no_repositorio(self):
        """
        Senha de e-mail no git vaza para todo clone, para sempre, e
        continua valida depois de o arquivo ser removido.
        """
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        base = (raiz / "config/settings/base.py").read_text(encoding="utf-8")
        self.assertIn('config("EMAIL_HOST_PASSWORD", default="")', base)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Kronus <dpo@kstec.online>",
    )
    def test_a_notificacao_sai_do_remetente_configurado(self):
        from django.core import mail

        mail.send_mail("Assunto", "Corpo", None, ["alguem@x.test"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, "Kronus <dpo@kstec.online>")
