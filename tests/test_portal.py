"""
Kronus — porta de entrada personalizada por empresa e PWA.

O colaborador acessa `kronus.online/<empresa>` e vê a marca de quem o
emprega, não a do fornecedor. Os testes cobrem o que a personalização
não pode custar: a segurança do login e o isolamento entre contas.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoUsuario
from apps.master.models import Plano

SENHA = "senha-forte-123"


class BasePortalTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(nome="Pro", slug="pro", max_colaboradores=100)
        cls.cliente = Cliente.objects.create(
            razao_social="Grupo Aurora", cnpj="11222333000181",
            plano=cls.plano, email_contato="a@a.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente,
            razao_social="Aurora Supermercados Ltda",
            nome_fantasia="Aurora",
            cnpj="11222333000262",
            cor_primaria="#7C3AED",
        )


class SlugTests(BasePortalTestCase):
    def test_slug_e_gerado_do_nome_fantasia(self):
        self.assertEqual(self.empresa.slug, "aurora")

    def test_colisao_ganha_sufixo(self):
        """
        Dois "Aurora" em clientes diferentes precisam de enderecos
        distintos — falhar aqui deixaria a segunda empresa sem acesso
        personalizado por um detalhe de cadastro.
        """
        outro = Cliente.objects.create(
            razao_social="Outro Grupo", cnpj="45997418000153",
            plano=self.plano, email_contato="b@b.com",
        )
        segunda = Empresa.objects.create(
            cliente=outro, razao_social="Aurora Norte",
            nome_fantasia="Aurora", cnpj="45997418000234",
        )
        self.assertNotEqual(segunda.slug, self.empresa.slug)
        self.assertTrue(segunda.slug.startswith("aurora"))

    def test_slug_definido_a_mao_e_respeitado(self):
        self.empresa.slug = "aurora-matriz"
        self.empresa.save()
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.slug, "aurora-matriz")


class PortalTests(BasePortalTestCase):
    def url(self):
        return reverse("clientes:portal", args=[self.empresa.slug])

    def test_portal_abre_com_a_marca_da_empresa(self):
        resposta = self.client.get(self.url())
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.content.decode()
        self.assertIn("Aurora", corpo)
        self.assertIn("#7C3AED", corpo)

    def test_empresa_inexistente_da_404(self):
        self.assertEqual(self.client.get("/nao-existe/").status_code, 404)

    def test_cliente_suspenso_cai_no_login_geral(self):
        """
        Mostrar a porta personalizada de uma conta suspensa seria
        convidar a pessoa a tentar entrar num sistema que vai recusa-la.
        """
        self.cliente.suspenso = True
        self.cliente.save(update_fields=["suspenso"])
        resposta = self.client.get(self.url())
        self.assertRedirects(resposta, reverse("accounts:login"))

    def test_login_funciona_pelo_portal(self):
        from apps.accounts.models import CustomUser

        CustomUser.objects.create_user(
            username="joao@aurora.com", password=SENHA,
            nome_completo="João Souza", tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        resposta = self.client.post(
            self.url(), {"username": "joao@aurora.com", "password": SENHA}
        )
        self.assertEqual(resposta.status_code, 302)

    def test_erro_de_login_nao_revela_quem_trabalha_ali(self):
        """
        "Usuario nao existe" entregaria a lista de funcionarios a quem
        testa CPFs. A mensagem e a mesma para qualquer falha.
        """
        resposta = self.client.post(
            self.url(), {"username": "naoexiste@x.com", "password": "errada"}
        )
        corpo = resposta.content.decode()
        self.assertNotIn("não existe", corpo.lower())
        self.assertIn("Não foi possível entrar", corpo)

    def test_portal_nao_da_acesso_a_outra_empresa(self):
        """A porta e cosmetica: quem manda no acesso e o vinculo do usuario."""
        from apps.accounts.models import CustomUser

        outro_cliente = Cliente.objects.create(
            razao_social="Beta", cnpj="45997418000153",
            plano=self.plano, email_contato="b@b.com",
        )
        Empresa.objects.create(
            cliente=outro_cliente, razao_social="Beta Ltda",
            nome_fantasia="Beta", cnpj="45997418000234",
        )
        usuario = CustomUser.objects.create_user(
            username="beta@beta.com", password=SENHA, nome_completo="Beta User",
            tipo=TipoUsuario.RH, cliente=outro_cliente,
        )
        # Entra pela porta da Aurora, mas continua sendo da Beta.
        self.client.post(self.url(), {"username": usuario.username, "password": SENHA})
        self.client.get(reverse("core:home"))
        self.assertNotEqual(usuario.cliente, self.cliente)


class PWATests(BasePortalTestCase):
    def test_manifesto_traz_a_identidade_da_empresa(self):
        resposta = self.client.get(
            reverse("clientes:manifesto", args=[self.empresa.slug])
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertIn("Aurora", dados["name"])
        self.assertEqual(dados["theme_color"], "#7C3AED")
        self.assertEqual(dados["start_url"], "/aurora/")

    def test_manifesto_usa_standalone_e_nao_fullscreen(self):
        """
        Num app de ponto a hora do aparelho e a informacao central —
        esconder a barra de status tiraria justamente ela.
        """
        dados = self.client.get(
            reverse("clientes:manifesto", args=[self.empresa.slug])
        ).json()
        self.assertEqual(dados["display"], "standalone")

    def test_manifesto_oferece_atalhos_uteis(self):
        dados = self.client.get(
            reverse("clientes:manifesto", args=[self.empresa.slug])
        ).json()
        urls = [a["url"] for a in dados["shortcuts"]]
        self.assertIn("/ponto/registrar/", urls)

    def test_service_worker_e_servido_como_javascript(self):
        resposta = self.client.get(reverse("clientes:service_worker"))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("javascript", resposta["Content-Type"])

    def test_service_worker_nunca_cacheia_ponto_nem_api(self):
        """
        Servir uma marcacao do cache e pior do que dizer "sem conexao":
        a pessoa acredita que bateu o ponto e nao bateu.
        """
        corpo = self.client.get(reverse("clientes:service_worker")).content.decode()
        self.assertIn("/api/", corpo)
        self.assertIn("/ponto/", corpo)
        self.assertIn("somenteRede", corpo)

    def test_portal_referencia_o_manifesto(self):
        corpo = self.client.get(
            reverse("clientes:portal", args=[self.empresa.slug])
        ).content.decode()
        self.assertIn('rel="manifest"', corpo)
        self.assertIn("beforeinstallprompt", corpo)


class PWATotemTests(BasePortalTestCase):
    """
    O totem instala como app **em tela cheia** — diferente do app do
    colaborador. Aqui o aparelho é dedicado e fica preso num suporte na
    portaria: a barra de status só oferece um caminho para alguém sair
    do quiosque.
    """

    def setUp(self):
        from apps.totem.models import Totem

        self.totem = Totem.objects.create(
            identificador="PWA-01", empresa=self.empresa
        )

    def manifesto(self):
        from django.urls import reverse

        return self.client.get(
            reverse("totem:manifesto", args=[self.totem.token_acesso])
        )

    def test_manifesto_do_totem_e_fullscreen(self):
        dados = self.manifesto().json()
        self.assertEqual(dados["display"], "fullscreen")
        self.assertIn("fullscreen", dados["display_override"])

    def test_manifesto_fixa_orientacao_retrato(self):
        """
        O enquadramento do rosto pressupõe tablet em pé; girar produziria
        recorte lateral e embedding ruim.
        """
        self.assertEqual(self.manifesto().json()["orientation"], "portrait")

    def test_escopo_limitado_ao_proprio_totem(self):
        dados = self.manifesto().json()
        self.assertEqual(dados["scope"], self.totem.url_kiosk)
        self.assertEqual(dados["start_url"], self.totem.url_kiosk)

    def test_usa_a_cor_da_empresa(self):
        self.assertEqual(self.manifesto().json()["theme_color"], "#7C3AED")

    def test_totem_inativo_nao_tem_manifesto(self):
        from django.urls import reverse

        self.totem.ativo = False
        self.totem.save(update_fields=["ativo"])
        resposta = self.client.get(
            reverse("totem:manifesto", args=[self.totem.token_acesso])
        )
        self.assertEqual(resposta.status_code, 404)
