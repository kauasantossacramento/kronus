"""
Kronus — testes de isolamento multi-tenant e permissoes (Fase 1).

Estes testes protegem a garantia central do produto: um cliente jamais
enxerga dados de outro, e cada papel so alcanca o seu escopo.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.clientes.models import Cliente, ConfiguracaoEmpresa, Empresa
from apps.core.constants import TipoUsuario
from apps.core.mixins import escopo_empresas
from apps.core.permissions import pode_gerenciar_empresa
from apps.master.models import Plano
from apps.rh.models import Colaborador

User = get_user_model()
SENHA = "senha-forte-123"


class BaseTenantTestCase(TestCase):
    """Monta dois clientes independentes com uma empresa e um colaborador cada."""

    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Teste", slug="teste", max_empresas=5, max_colaboradores=100
        )

        cls.cliente_a = Cliente.objects.create(
            razao_social="Cliente A Ltda",
            cnpj="11222333000181",
            plano=cls.plano,
            email_contato="a@a.com",
        )
        cls.cliente_b = Cliente.objects.create(
            razao_social="Cliente B Ltda",
            cnpj="11444777000161",
            plano=cls.plano,
            email_contato="b@b.com",
        )

        cls.empresa_a = Empresa.objects.create(
            cliente=cls.cliente_a, razao_social="Empresa A1", cnpj="11222333000262"
        )
        cls.empresa_a2 = Empresa.objects.create(
            cliente=cls.cliente_a, razao_social="Empresa A2", cnpj="11222333000343"
        )
        cls.empresa_b = Empresa.objects.create(
            cliente=cls.cliente_b, razao_social="Empresa B1", cnpj="11444777000242"
        )

        cls.master = User.objects.create_superuser(
            email="master@kstec.online", password=SENHA, nome_completo="Master"
        )
        cls.admin_a = User.objects.create_user(
            email="admin@a.com",
            password=SENHA,
            nome_completo="Admin A",
            tipo=TipoUsuario.CLIENTE,
            cliente=cls.cliente_a,
        )
        cls.rh_a = User.objects.create_user(
            email="rh@a.com",
            password=SENHA,
            nome_completo="RH A",
            tipo=TipoUsuario.RH,
            cliente=cls.cliente_a,
        )
        cls.rh_a.empresas.set([cls.empresa_a])

        cls.rh_b = User.objects.create_user(
            email="rh@b.com",
            password=SENHA,
            nome_completo="RH B",
            tipo=TipoUsuario.RH,
            cliente=cls.cliente_b,
        )
        cls.rh_b.empresas.set([cls.empresa_b])

        cls.colab_a = Colaborador.objects.create(
            empresa=cls.empresa_a,
            cpf="52998224725",
            nome_completo="Colaborador A",
            data_nascimento=date(1990, 1, 1),
            data_admissao=date(2024, 1, 1),
        )
        cls.colab_b = Colaborador.objects.create(
            empresa=cls.empresa_b,
            cpf="15350946056",
            nome_completo="Colaborador B",
            data_nascimento=date(1990, 1, 1),
            data_admissao=date(2024, 1, 1),
        )


class EscopoDeEmpresasTests(BaseTenantTestCase):
    def test_master_enxerga_todas(self):
        self.assertEqual(escopo_empresas(self.master).count(), 3)

    def test_admin_do_cliente_enxerga_apenas_as_suas(self):
        empresas = escopo_empresas(self.admin_a)
        self.assertEqual(empresas.count(), 2)
        self.assertNotIn(self.empresa_b, empresas)

    def test_rh_enxerga_apenas_as_empresas_vinculadas(self):
        empresas = escopo_empresas(self.rh_a)
        self.assertEqual(list(empresas), [self.empresa_a])

    def test_anonimo_nao_enxerga_nada(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(escopo_empresas(AnonymousUser()).count(), 0)


class PermissoesDeEmpresaTests(BaseTenantTestCase):
    def test_master_gerencia_qualquer_empresa(self):
        self.assertTrue(pode_gerenciar_empresa(self.master, self.empresa_b))

    def test_admin_do_cliente_gerencia_suas_empresas(self):
        self.assertTrue(pode_gerenciar_empresa(self.admin_a, self.empresa_a2))

    def test_admin_do_cliente_nao_gerencia_empresa_de_outro(self):
        self.assertFalse(pode_gerenciar_empresa(self.admin_a, self.empresa_b))

    def test_rh_nao_gerencia_empresa_nao_vinculada(self):
        self.assertFalse(pode_gerenciar_empresa(self.rh_a, self.empresa_a2))


class IsolamentoNasViewsTests(BaseTenantTestCase):
    """O vazamento entre tenants tem que ser impossível pela interface."""

    def test_rh_so_lista_colaboradores_da_propria_empresa(self):
        self.client.login(username="rh@a.com", password=SENHA)
        resposta = self.client.get(reverse("rh:colaborador_lista"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Colaborador A")
        self.assertNotContains(resposta, "Colaborador B")

    def test_rh_recebe_404_ao_acessar_colaborador_de_outro_tenant(self):
        self.client.login(username="rh@a.com", password=SENHA)
        resposta = self.client.get(
            reverse("rh:colaborador_detalhe", args=[self.colab_b.pk])
        )
        self.assertEqual(resposta.status_code, 404)

    def test_rh_nao_acessa_painel_master(self):
        self.client.login(username="rh@a.com", password=SENHA)
        resposta = self.client.get(reverse("master:dashboard"))
        self.assertEqual(resposta.status_code, 403)

    def test_master_acessa_painel_master(self):
        self.client.login(username="master@kstec.online", password=SENHA)
        resposta = self.client.get(reverse("master:dashboard"))
        self.assertEqual(resposta.status_code, 200)

    def test_visitante_e_redirecionado_para_o_login(self):
        resposta = self.client.get(reverse("rh:colaborador_lista"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/accounts/login/", resposta.url)


class ClienteSuspensoTests(BaseTenantTestCase):
    def test_usuario_de_cliente_suspenso_e_barrado(self):
        self.cliente_a.suspender("Inadimplência")
        self.client.login(username="rh@a.com", password=SENHA)
        resposta = self.client.get(reverse("rh:colaborador_lista"))
        self.assertRedirects(
            resposta, reverse("core:cliente_suspenso"), target_status_code=403
        )

    def test_master_nao_e_barrado_por_suspensao(self):
        self.cliente_a.suspender("Inadimplência")
        self.client.login(username="master@kstec.online", password=SENHA)
        self.assertEqual(self.client.get(reverse("master:dashboard")).status_code, 200)


class ModeloEmpresaTests(BaseTenantTestCase):
    def test_configuracao_e_criada_automaticamente(self):
        self.assertTrue(
            ConfiguracaoEmpresa.objects.filter(empresa=self.empresa_a).exists()
        )

    def test_salt_de_integridade_e_gerado(self):
        self.assertTrue(self.empresa_a.salt_registro)

    def test_nsr_incrementa_sem_lacunas(self):
        for esperado in range(1, 6):
            self.assertEqual(self.empresa_a.proximo_nsr(), esperado)

    def test_nsr_e_independente_por_empresa(self):
        self.empresa_a.proximo_nsr()
        self.empresa_a.proximo_nsr()
        self.assertEqual(self.empresa_b.proximo_nsr(), 1)


class LimitesDoPlanoTests(BaseTenantTestCase):
    def test_bloqueia_empresa_acima_do_limite(self):
        self.plano.max_empresas = 2
        self.plano.save()
        self.assertFalse(self.cliente_a.pode_adicionar_empresa())

    def test_permite_dentro_do_limite(self):
        self.assertTrue(self.cliente_b.pode_adicionar_empresa())


class ApiKeyTests(BaseTenantTestCase):
    def test_chave_em_texto_plano_nao_e_persistida(self):
        chave = self.cliente_a.gerar_api_key()
        self.cliente_a.refresh_from_db()
        self.assertTrue(self.cliente_a.api_key_ativa)
        self.assertNotIn(chave, self.cliente_a.api_key_hash)
        self.assertEqual(len(self.cliente_a.api_key_hash), 64)
        self.assertTrue(chave.startswith(self.cliente_a.api_key_prefixo))

    def test_revogacao(self):
        self.cliente_a.gerar_api_key()
        self.cliente_a.revogar_api_key()
        self.assertFalse(self.cliente_a.api_key_ativa)
