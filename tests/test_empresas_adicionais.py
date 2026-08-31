"""
Kronus — empresa adicional contratada a parte.

Um grupo com varios CNPJs e uma negociacao caso a caso. Ler
`plano.max_empresas` direto obrigava a escolher entre barrar uma
empresa ja acordada ou inventar um plano novo por cliente — e a tabela
de planos viraria uma lista de excecoes.

Mesma forma do adicional de totens, que ja existia.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.clientes.models import Cliente, Empresa
from apps.faturamento.models import Assinatura
from apps.master.models import Plano


class LimiteDeEmpresasTests(TestCase):
    def setUp(self):
        self.plano = Plano.objects.create(
            nome="Profissional teste", slug="profissional-teste",
            max_empresas=3, max_colaboradores=100, max_totems=2,
            preco_mensal=Decimal("300"), preco_por_empresa=Decimal("50"),
        )
        self.cliente = Cliente.objects.create(
            razao_social="Grupo Teste LTDA", nome_fantasia="Grupo Teste",
            cnpj="11222333000181", email_contato="grupo@teste.com", plano=self.plano,
        )

    def _assinatura(self, empresas=0):
        return Assinatura.objects.create(
            cliente=self.cliente, plano=self.plano,
            valor=Decimal("300"), data_inicio=date.today(),
            empresas_contratadas=empresas,
        )

    def _criar_empresas(self, quantidade):
        for _ in range(quantidade):
            indice = Empresa.objects.count()
            Empresa.objects.create(
                cliente=self.cliente,
                razao_social=f"Empresa {indice}",
                cnpj=f"1122233300{indice:04d}",
            )

    def test_sem_assinatura_vale_o_limite_do_plano(self):
        self.assertEqual(self.cliente.limite_de_empresas, 3)

    def test_o_adicional_soma_ao_plano(self):
        self._assinatura(empresas=1)
        self.assertEqual(self.cliente.limite_de_empresas, 4)

    def test_barra_ao_atingir_o_limite_do_plano(self):
        self._criar_empresas(3)
        self.assertFalse(self.cliente.pode_adicionar_empresa())

    def test_o_adicional_libera_a_empresa_seguinte(self):
        self._assinatura(empresas=1)
        self._criar_empresas(3)
        self.assertTrue(self.cliente.pode_adicionar_empresa())
        self._criar_empresas(1)
        self.assertFalse(self.cliente.pode_adicionar_empresa())

    def test_a_empresa_adicional_entra_no_valor(self):
        a = self._assinatura(empresas=2)
        self.assertEqual(a.valor_dos_adicionais(), Decimal("100"))

    def test_plano_sem_preco_de_empresa_nao_cobra_nada(self):
        self.plano.preco_por_empresa = Decimal("0")
        self.plano.save(update_fields=["preco_por_empresa"])
        a = self._assinatura(empresas=2)
        self.assertEqual(a.valor_dos_adicionais(), Decimal("0"))

    def test_empresas_permitidas_na_assinatura(self):
        a = self._assinatura(empresas=1)
        self.assertEqual(a.empresas_permitidas, 4)


class TrocaDePlanoTests(TestCase):
    """
    Quem pagou por uma empresa adicional nao a perde ao mudar de plano.

    A checagem antiga comparava com `plano.max_empresas` puro, entao um
    cliente com 4 empresas (3 do plano + 1 contratada) era barrado ao
    trocar para um plano de mesmo tamanho — o adicional sumia da conta.
    """

    def setUp(self):
        self.plano = Plano.objects.create(
            nome="Base", slug="base", max_empresas=3,
            max_colaboradores=50, preco_mensal=Decimal("200"),
        )
        self.destino = Plano.objects.create(
            nome="Destino", slug="destino", max_empresas=3,
            max_colaboradores=80, preco_mensal=Decimal("260"),
        )
        self.cliente = Cliente.objects.create(
            razao_social="Grupo X LTDA", nome_fantasia="Grupo X",
            cnpj="60746948000112", email_contato="x@teste.com", plano=self.plano,
        )
        for i in range(4):
            Empresa.objects.create(
                cliente=self.cliente, razao_social=f"E{i}",
                cnpj=f"6074694800{i:04d}",
            )
        self.assinatura = Assinatura.objects.create(
            cliente=self.cliente, plano=self.plano, valor=Decimal("200"),
            data_inicio=date.today(), empresas_contratadas=1,
        )

    def test_troca_de_plano_respeita_o_adicional_contratado(self):
        from apps.faturamento.services import AssinaturaService

        AssinaturaService.trocar_plano(assinatura=self.assinatura, plano=self.destino)
        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.plano_id, self.destino.pk)

    def test_sem_o_adicional_a_troca_e_barrada(self):
        from apps.faturamento.services import AssinaturaService

        self.assinatura.empresas_contratadas = 0
        self.assinatura.save(update_fields=["empresas_contratadas"])
        with self.assertRaises(ValueError):
            AssinaturaService.trocar_plano(assinatura=self.assinatura, plano=self.destino)
