"""
Kronus — o master ve o ambiente com os olhos do cliente.

Ele ja tinha acesso a todas as empresas; o que faltava era a porta e,
sobretudo, o aviso. Navegar no ambiente de um cliente sem saber disso e
como se descobre, depois de meia hora, que a alteracao foi feita na
empresa errada.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.clientes.models import Cliente, Empresa
from apps.core.middleware import CHAVE_SESSAO_EMPRESA
from apps.master.models import LogAcessoMaster, Plano


class EntrarComoTests(TestCase):
    def setUp(self):
        plano = Plano.objects.create(nome="P", slug="p")
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.master = CustomUser.objects.create_superuser(
            email="m@x.test", password="Prova!12345", nome_completo="Master",
        )

    def test_o_master_entra_no_ambiente(self):
        self.client.force_login(self.master)
        self.client.get(reverse("master:entrar_como", args=[self.empresa.pk]))
        self.assertEqual(
            self.client.session.get(CHAVE_SESSAO_EMPRESA), self.empresa.pk
        )

    def test_a_faixa_avisa_em_que_ambiente_ele_esta(self):
        """
        Fixa e sem botao de fechar: o aviso existe para ser visto o tempo
        todo, e um aviso que se fecha e um aviso que se esquece.
        """
        self.client.force_login(self.master)
        self.client.get(reverse("master:entrar_como", args=[self.empresa.pk]))
        pagina = self.client.get(reverse("rh:dashboard")).content.decode()
        self.assertIn("Você está no ambiente de", pagina)
        self.assertIn(self.empresa.nome_exibicao, pagina)

    def test_sair_devolve_o_painel_da_ks_tec(self):
        self.client.force_login(self.master)
        self.client.get(reverse("master:entrar_como", args=[self.empresa.pk]))
        self.client.get(reverse("master:sair_do_ambiente"))
        self.assertIsNone(self.client.session.get(CHAVE_SESSAO_EMPRESA))

    def test_a_entrada_fica_na_auditoria(self):
        # Entrar no ambiente de um cliente e acesso a dado de terceiro, e
        # quem responde por LGPD precisa saber quando aconteceu.
        self.client.force_login(self.master)
        self.client.get(reverse("master:entrar_como", args=[self.empresa.pk]))
        self.assertTrue(
            LogAcessoMaster.objects.filter(
                cliente=self.cliente, detalhes__icontains="ambiente"
            ).exists()
        )

    def test_quem_nao_e_master_nao_entra(self):
        outro = CustomUser.objects.create_user(
            email="rh@x.test", password="Prova!12345",
            nome_completo="RH", tipo="rh", cliente=self.cliente,
        )
        self.client.force_login(outro)
        resposta = self.client.get(
            reverse("master:entrar_como", args=[self.empresa.pk])
        )
        self.assertIn(resposta.status_code, (403, 302))
