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


class DemonstracaoContrataTests(TestCase):
    """
    Contratar durante a demonstracao.

    Com a cobranca automatica desligada, ninguem cria a fatura sozinho —
    se o Master nao souber que houve contratacao, o cliente usa de graca
    ate alguem reparar. E manter a marca de demonstracao faria a
    varredura suspender, dias depois, quem acabou de dizer sim.
    """

    def setUp(self):
        cache.clear()
        self.client.post(reverse("comercial:solicitar"), dados())
        self.solicitacao = SolicitacaoDemonstracao.objects.get()
        self.cliente = self.solicitacao.cliente
        self.usuario = CustomUser.objects.get(email="joana@aurora.test")

        from apps.master.models import Plano

        self.plano = Plano.objects.create(
            nome="Profissional", slug="profissional",
            preco_mensal=199, max_empresas=3, max_colaboradores=50, ativo=True,
        )
        self.client.force_login(self.usuario)

    def _contratar(self):
        return self.client.post(
            reverse("faturamento:checkout", args=[self.plano.slug]),
            {"acao": "confirmar", "ciclo": "mensal"},
            follow=True,
        )

    def test_contratar_tira_a_marca_de_demonstracao(self):
        self._contratar()

        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.eh_demonstracao)
        self.assertIsNone(self.cliente.demo_expira_em)

    def test_a_solicitacao_fica_como_convertida(self):
        self._contratar()

        self.solicitacao.refresh_from_db()
        self.assertEqual(
            self.solicitacao.status, SolicitacaoDemonstracao.Status.CONVERTIDA
        )
        self.assertIsNotNone(self.solicitacao.convertida_em)

    def test_a_varredura_nao_suspende_quem_contratou(self):
        from datetime import timedelta

        self._contratar()
        Cliente.objects.filter(pk=self.cliente.pk).update(
            demo_expira_em=timezone.now() - timedelta(hours=1)
        )

        expirar_demonstracoes()

        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.suspenso)

    def test_o_master_e_avisado(self):
        from apps.core.constants import TipoUsuario
        from apps.notificacoes.models import Notificacao

        master = CustomUser.objects.create_user(
            email="master@kstec.online", password="x", nome_completo="Master",
            tipo=TipoUsuario.MASTER, is_staff=True, is_superuser=True,
        )
        self._contratar()

        self.assertTrue(
            Notificacao.objects.filter(
                destinatario=master, titulo__contains="contratou"
            ).exists(),
            "sem aviso, ninguem emite a fatura e o cliente usa de graca",
        )

    def test_nao_conta_a_configuracao_interna_ao_cliente(self):
        """
        "Cobrança automática desativada" e informacao nossa. O que muda
        para o cliente e so como a fatura chega.
        """
        resposta = self.client.get(
            reverse("faturamento:checkout", args=[self.plano.slug])
        )
        corpo = resposta.content.decode()

        self.assertNotIn("desativada nesta instalação", corpo)
        self.assertIn("KS TEC", corpo)


class LogoutPersonalizadoTests(TestCase):
    """
    Sair devolve o usuario a porta por onde ele entrou.

    Quem usa o app de uma empresa entra por `kronus.online/<empresa>`,
    com a logo e as cores dela. Jogar essa pessoa na capa comercial do
    Kronus troca a marca do empregador pela nossa no unico momento em que
    ela nao pediu nada — e ela perde o endereco de volta.
    """

    def setUp(self):
        from apps.core.constants import TipoUsuario
        from apps.master.models import Plano

        plano = Plano.objects.create(nome="P", slug="p", max_empresas=3)
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa",
            cnpj="45997418000234", slug="alfa",
        )
        self.usuario = CustomUser.objects.create_user(
            email="rh@alfa.com", password="x", nome_completo="RH",
            tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        self.usuario.empresas.add(self.empresa)

    def test_volta_para_a_pagina_da_empresa(self):
        self.client.force_login(self.usuario)
        resposta = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(resposta, "/alfa/", fetch_redirect_response=False)

    def test_master_volta_para_a_capa(self):
        from apps.core.constants import TipoUsuario

        master = CustomUser.objects.create_user(
            email="m@kstec.online", password="x", nome_completo="M",
            tipo=TipoUsuario.MASTER, is_staff=True, is_superuser=True,
        )
        self.client.force_login(master)
        resposta = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(resposta, "/", fetch_redirect_response=False)

    def test_com_duas_empresas_volta_para_a_que_estava_em_uso(self):
        """
        O middleware ja resolve uma empresa ativa mesmo quando ha varias.
        Voltar para a pagina dela e coerente: e o contexto em que a pessoa
        estava operando quando clicou em sair.
        """
        outra = Empresa.objects.create(
            cliente=self.cliente, razao_social="Beta",
            cnpj="11444777000161", slug="beta",
        )
        self.usuario.empresas.add(outra)

        self.client.force_login(self.usuario)
        sessao = self.client.session
        sessao["empresa_ativa_id"] = outra.pk
        sessao.save()

        resposta = self.client.post(reverse("accounts:logout"))
        self.assertIn(resposta["Location"], ("/alfa/", "/beta/"))

    def test_empresa_sem_endereco_proprio_volta_para_a_capa(self):
        Empresa.objects.filter(pk=self.empresa.pk).update(slug=None)

        self.client.force_login(self.usuario)
        resposta = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(resposta, "/", fetch_redirect_response=False)
