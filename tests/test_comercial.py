"""
Kronus — demonstracao automatica de 24h.

O endpoint cria Cliente, Empresa e usuario a partir de um POST anonimo.
E o unico ponto do sistema em que um desconhecido escreve no banco sem
autenticacao, entao os testes aqui cobrem tanto o caminho feliz quanto os
limites que impedem que um laco simples encha o disco da VPS.
"""
from datetime import timedelta

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.clientes.models import Cliente, Empresa
from apps.comercial.models import ConfiguracaoComercial, SolicitacaoDemonstracao
from apps.comercial.services import expirar_demonstracoes, gerar_cnpj, gerar_cpf
from apps.core.constants import TipoUsuario


def dados(**extra):
    base = {
        "nome": "Joana Ribeiro",
        "empresa": "Padaria Aurora",
        "email": "joana@aurora.test",
        "whatsapp": "73988310101",
        "porte": "11-50",
    }
    base.update(extra)
    return base


class DocumentosTests(TestCase):
    def test_cpf_gerado_passa_no_validador_do_sistema(self):
        from apps.core.utils import validar_cpf

        for _ in range(30):
            validar_cpf(gerar_cpf())  # nao levanta

    def test_cnpj_gerado_tem_14_digitos(self):
        for _ in range(20):
            self.assertEqual(len(gerar_cnpj()), 14)


class SolicitacaoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("comercial:solicitar")

    def test_cria_ambiente_completo(self):
        resposta = self.client.post(self.url, dados())

        self.assertEqual(resposta.status_code, 200)
        solicitacao = SolicitacaoDemonstracao.objects.get()
        self.assertEqual(solicitacao.status, SolicitacaoDemonstracao.Status.ATIVA)

        cliente = solicitacao.cliente
        self.assertIsNotNone(cliente)
        self.assertTrue(cliente.eh_demonstracao)
        self.assertIsNotNone(cliente.demo_expira_em)

        empresa = Empresa.objects.get(cliente=cliente)
        self.assertTrue(empresa.slug)

        usuario = CustomUser.objects.get(email="joana@aurora.test")
        self.assertEqual(usuario.tipo, TipoUsuario.CLIENTE)
        self.assertEqual(usuario.cliente_id, cliente.pk)
        self.assertIn(empresa, usuario.empresas.all())

    def test_prazo_respeita_a_configuracao(self):
        config = ConfiguracaoComercial.carregar()
        config.demo_horas = 48
        config.save()

        antes = timezone.now()
        self.client.post(self.url, dados())
        solicitacao = SolicitacaoDemonstracao.objects.get()

        horas = (solicitacao.expira_em - antes).total_seconds() / 3600
        self.assertAlmostEqual(horas, 48, delta=1)

    def test_ambiente_nasce_com_colaboradores(self):
        from apps.rh.models import Colaborador

        self.client.post(self.url, dados())
        empresa = Empresa.objects.get()
        self.assertGreater(Colaborador.objects.filter(empresa=empresa).count(), 0)

    def test_envia_email_com_as_credenciais(self):
        self.client.post(self.url, dados())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("joana@aurora.test", mail.outbox[0].to)

    def test_a_senha_nao_e_persistida(self):
        resposta = self.client.post(self.url, dados())
        senha = resposta.context["senha"]

        solicitacao = SolicitacaoDemonstracao.objects.get()
        serializado = str(solicitacao.__dict__)
        self.assertNotIn(senha, serializado,
                         "a senha em texto claro nao pode ser guardada")

    def test_email_ja_cadastrado_e_recusado(self):
        CustomUser.objects.create_user(
            email="joana@aurora.test", password="x", nome_completo="Outra"
        )
        resposta = self.client.post(self.url, dados())
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(SolicitacaoDemonstracao.objects.count(), 0)

    def test_campo_armadilha_barra_robo(self):
        resposta = self.client.post(self.url, dados(site="http://spam.example"))
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Cliente.objects.count(), 0)

    def test_limite_por_ip(self):
        for i in range(3):
            self.client.post(self.url, dados(email=f"a{i}@x.test"))
        resposta = self.client.post(self.url, dados(email="quarta@x.test"))

        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(SolicitacaoDemonstracao.objects.count(), 3)

    def test_limite_diario(self):
        config = ConfiguracaoComercial.carregar()
        config.demo_limite_diario = 1
        config.save()

        self.client.post(self.url, dados(email="um@x.test"))
        cache.clear()  # isola o limite diario do limite por IP
        resposta = self.client.post(self.url, dados(email="dois@x.test"))

        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(SolicitacaoDemonstracao.objects.count(), 1)

    def test_demonstracao_desligada_nao_cria_nada(self):
        config = ConfiguracaoComercial.carregar()
        config.demo_ativa = False
        config.save()

        resposta = self.client.post(self.url, dados())
        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(Cliente.objects.count(), 0)

    def test_get_nao_e_aceito(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class ExpiracaoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.post(reverse("comercial:solicitar"), dados())
        self.solicitacao = SolicitacaoDemonstracao.objects.get()

    def _vencer(self):
        passado = timezone.now() - timedelta(hours=1)
        SolicitacaoDemonstracao.objects.filter(pk=self.solicitacao.pk).update(
            expira_em=passado
        )
        Cliente.objects.filter(pk=self.solicitacao.cliente_id).update(
            demo_expira_em=passado
        )

    def test_varredura_suspende_e_marca_expirada(self):
        self._vencer()
        self.assertEqual(expirar_demonstracoes(), 1)

        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.status,
                         SolicitacaoDemonstracao.Status.EXPIRADA)
        self.assertTrue(Cliente.objects.get(pk=self.solicitacao.cliente_id).suspenso)

    def test_varredura_e_idempotente(self):
        self._vencer()
        expirar_demonstracoes()
        self.assertEqual(expirar_demonstracoes(), 0)

    def test_ambiente_nao_e_apagado(self):
        self._vencer()
        expirar_demonstracoes()
        self.assertTrue(Cliente.objects.filter(pk=self.solicitacao.cliente_id).exists())
        self.assertTrue(
            Empresa.objects.filter(cliente=self.solicitacao.cliente).exists()
        )

    def test_acesso_apos_o_prazo_e_bloqueado_sem_esperar_a_varredura(self):
        """O corte vale no acesso: nao depende de o worker ter rodado."""
        usuario = CustomUser.objects.get(email="joana@aurora.test")
        self.client.force_login(usuario)

        self._vencer()
        resposta = self.client.get("/app/")
        self.assertRedirects(resposta, reverse("comercial:expirada"),
                             fetch_redirect_response=False)


class ConfiguracaoComercialTests(TestCase):
    def test_singleton(self):
        primeira = ConfiguracaoComercial.carregar()
        self.assertEqual(ConfiguracaoComercial.carregar().pk, primeira.pk)

    def test_link_whatsapp_vazio_quando_nao_ha_numero(self):
        config = ConfiguracaoComercial.carregar()
        config.whatsapp = ""
        self.assertEqual(config.link_whatsapp, "")

    def test_link_whatsapp_limpa_a_pontuacao(self):
        config = ConfiguracaoComercial.carregar()
        config.whatsapp = "+55 (73) 98831-0101"
        self.assertIn("wa.me/5573988310101", config.link_whatsapp)
