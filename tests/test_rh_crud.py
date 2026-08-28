"""Kronus — testes do CRUD do painel RH (Fase 1)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoUsuario
from apps.master.models import Plano
from apps.rh.models import Cargo, Colaborador, Departamento

User = get_user_model()
SENHA = "senha-forte-123"


class BaseRHTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Teste", slug="teste", max_empresas=2, max_colaboradores=3
        )
        cls.cliente = Cliente.objects.create(
            razao_social="Cliente Teste",
            cnpj="11222333000181",
            plano=cls.plano,
            email_contato="c@c.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Empresa Teste", cnpj="11222333000262"
        )
        cls.outra_empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Outra Empresa", cnpj="11222333000343"
        )
        cls.rh = User.objects.create_user(
            email="rh@teste.com",
            password=SENHA,
            nome_completo="RH Teste",
            tipo=TipoUsuario.RH,
            cliente=cls.cliente,
        )
        cls.rh.empresas.set([cls.empresa])

    def setUp(self):
        self.client.login(username="rh@teste.com", password=SENHA)


class CadastroDeColaboradorTests(BaseRHTestCase):
    def _dados(self, **overrides):
        base = {
            "nome_completo": "João da Silva Souza",
            "nome_social": "",
            "cpf": "529.982.247-25",
            "data_nascimento": "1990-03-12",
            "email": "joao@teste.com",
            "telefone": "",
            "matricula": "0001",
            "cargo": "Operador de Caixa",
            "cargo_ref": "",
            "departamento": "",
            "escala": "",
            "data_admissao": "2024-01-15",
            "data_demissao": "",
            "pis_pasep": "",
            "ctps": "",
            "ctps_serie": "",
            "observacoes": "",
            "permite_ponto_web": "on",
            "ativo": "on",
        }
        base.update(overrides)
        return base

    def test_cadastra_colaborador_na_empresa_ativa(self):
        resposta = self.client.post(reverse("rh:colaborador_criar"), self._dados())
        self.assertEqual(resposta.status_code, 302)
        colaborador = Colaborador.objects.get(cpf="52998224725")
        self.assertEqual(colaborador.empresa, self.empresa)
        self.assertEqual(colaborador.nome_completo, "João da Silva Souza")

    def test_recusa_cpf_invalido(self):
        resposta = self.client.post(
            reverse("rh:colaborador_criar"), self._dados(cpf="111.111.111-11")
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertFormError(
            resposta.context["form"], "cpf", "CPF inválido."
        )

    def test_recusa_cpf_duplicado_na_mesma_empresa(self):
        self.client.post(reverse("rh:colaborador_criar"), self._dados())
        resposta = self.client.post(
            reverse("rh:colaborador_criar"), self._dados(matricula="0002")
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertFormError(
            resposta.context["form"],
            "cpf",
            "Já existe um colaborador com este CPF na empresa.",
        )

    def test_recusa_demissao_anterior_a_admissao(self):
        resposta = self.client.post(
            reverse("rh:colaborador_criar"),
            self._dados(data_demissao="2023-01-01"),
        )
        self.assertFormError(
            resposta.context["form"],
            "data_demissao",
            "A demissão não pode ser anterior à admissão.",
        )

    def test_respeita_limite_de_colaboradores_do_plano(self):
        for indice in range(3):
            Colaborador.objects.create(
                empresa=self.empresa,
                cpf=["15350946056", "71428793860", "40442820135"][indice],
                nome_completo=f"Colaborador {indice}",
                data_nascimento=date(1990, 1, 1),
                data_admissao=date(2024, 1, 1),
            )
        resposta = self.client.post(reverse("rh:colaborador_criar"), self._dados())
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(
            "no máximo", " ".join(resposta.context["form"].non_field_errors())
        )

    def test_cria_credenciais_quando_solicitado(self):
        self.client.post(
            reverse("rh:colaborador_criar"), self._dados(criar_acesso="on")
        )
        colaborador = Colaborador.objects.get(cpf="52998224725")
        self.assertIsNotNone(colaborador.user)
        self.assertTrue(colaborador.user.trocar_senha_no_proximo_login)
        self.assertEqual(colaborador.user.tipo, TipoUsuario.COLABORADOR)

    def test_desligamento_preserva_o_registro(self):
        self.client.post(reverse("rh:colaborador_criar"), self._dados())
        colaborador = Colaborador.objects.get(cpf="52998224725")
        self.client.post(reverse("rh:colaborador_desligar", args=[colaborador.pk]))
        colaborador.refresh_from_db()
        self.assertFalse(colaborador.ativo)
        self.assertIsNotNone(colaborador.data_demissao)


class EscopoDosFormulariosTests(BaseRHTestCase):
    """Os selects relacionados nunca podem oferecer dados de outra empresa."""

    def test_departamentos_de_outra_empresa_nao_aparecem(self):
        Departamento.objects.create(empresa=self.empresa, nome="Interno")
        Departamento.objects.create(empresa=self.outra_empresa, nome="Externo")

        resposta = self.client.get(reverse("rh:colaborador_criar"))
        opcoes = resposta.context["form"].fields["departamento"].queryset
        self.assertEqual([d.nome for d in opcoes], ["Interno"])

    def test_post_forjado_para_outra_empresa_e_recusado(self):
        alheio = Departamento.objects.create(empresa=self.outra_empresa, nome="Externo")
        resposta = self.client.post(
            reverse("rh:colaborador_criar"),
            {
                "nome_completo": "Teste",
                "cpf": "52998224725",
                "data_nascimento": "1990-01-01",
                "data_admissao": "2024-01-01",
                "departamento": alheio.pk,
                "ativo": "on",
            },
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("departamento", resposta.context["form"].errors)


class CadastroDeEstruturaTests(BaseRHTestCase):
    def test_cria_departamento_na_empresa_ativa(self):
        resposta = self.client.post(
            reverse("rh:departamento_criar"),
            {"nome": "Logística", "descricao": "", "centro_custo": "", "ativo": "on"},
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(
            Departamento.objects.get(nome="Logística").empresa, self.empresa
        )

    def test_cria_cargo_na_empresa_ativa(self):
        resposta = self.client.post(
            reverse("rh:cargo_criar"),
            {"nome": "Motorista", "cbo": "7823-05", "descricao": "", "ativo": "on"},
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Cargo.objects.get(nome="Motorista").empresa, self.empresa)

    def test_dashboard_do_rh_responde(self):
        resposta = self.client.get(reverse("rh:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Empresa Teste")
