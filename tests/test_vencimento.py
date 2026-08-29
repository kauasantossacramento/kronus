"""
Kronus — a cobranca cai no dia combinado com o cliente.

O cadastro guarda `dia_vencimento` desde sempre, e a assinatura o
ignorava: a cobranca caia N dias depois da contratacao, no dia que
desse. Para quem fecha o financeiro no dia 10, uma fatura no dia 23 e
uma conversa por mes.
"""
from datetime import date

from django.test import TestCase

from apps.faturamento.services import AssinaturaService


class Cliente:
    """Dublê: o que importa aqui é um número, não o modelo inteiro."""

    def __init__(self, dia):
        self.dia_vencimento = dia


class DiaDoClienteTests(TestCase):
    def test_move_para_o_dia_combinado(self):
        self.assertEqual(
            AssinaturaService.no_dia_do_cliente(Cliente(10), date(2026, 3, 4)),
            date(2026, 3, 10),
        )

    def test_nunca_puxa_para_tras(self):
        # O dia 10 de marco ja passou: vai para o de abril, e nao para
        # uma data anterior a referencia.
        self.assertEqual(
            AssinaturaService.no_dia_do_cliente(Cliente(10), date(2026, 3, 23)),
            date(2026, 4, 10),
        )

    def test_o_proprio_dia_serve(self):
        self.assertEqual(
            AssinaturaService.no_dia_do_cliente(Cliente(10), date(2026, 3, 10)),
            date(2026, 3, 10),
        )

    def test_vira_o_ano(self):
        self.assertEqual(
            AssinaturaService.no_dia_do_cliente(Cliente(5), date(2026, 12, 20)),
            date(2027, 1, 5),
        )

    def test_mes_curto_cai_no_ultimo_dia(self):
        """
        Dia 31 em fevereiro nao existe. Adiar para marco atrasaria a
        cobranca um mes inteiro; o ultimo dia do mes e o mais proximo do
        combinado.
        """
        self.assertEqual(
            AssinaturaService.no_dia_do_cliente(Cliente(31), date(2026, 2, 1)),
            date(2026, 2, 28),
        )

    def test_fevereiro_bissexto(self):
        self.assertEqual(
            AssinaturaService.no_dia_do_cliente(Cliente(30), date(2028, 2, 1)),
            date(2028, 2, 29),
        )

    def test_sem_dia_definido_nada_muda(self):
        # Cliente sem preferencia mantem a data calculada pelo ciclo.
        self.assertEqual(
            AssinaturaService.no_dia_do_cliente(Cliente(None), date(2026, 3, 4)),
            date(2026, 3, 4),
        )


class ContratacaoTests(TestCase):
    def test_a_assinatura_nasce_no_dia_do_cliente(self):
        from apps.clientes.models import Cliente as ClienteReal
        from apps.faturamento.models import Assinatura
        from apps.master.models import Plano

        plano = Plano.objects.create(
            nome="Pro", slug="pro", preco_mensal=100, max_colaboradores=50
        )
        cliente = ClienteReal.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com", dia_vencimento=10,
        )

        assinatura = AssinaturaService.contratar(cliente=cliente, plano=plano)

        self.assertIsNotNone(assinatura.proxima_cobranca)
        self.assertEqual(
            assinatura.proxima_cobranca.day, 10,
            "a assinatura nasceu ignorando o dia combinado com o cliente",
        )
        self.assertEqual(assinatura.status, Assinatura.Status.TESTE)

    def test_a_assinatura_vale_mesmo_sem_o_gateway(self):
        """
        A chave do ASAAS pode nao estar configurada ainda. A assinatura
        local precisa existir assim mesmo: cobrar depois e possivel,
        descobrir que nao havia assinatura nao e.
        """
        from apps.clientes.models import Cliente as ClienteReal
        from apps.master.models import Plano

        plano = Plano.objects.create(nome="P", slug="p", preco_mensal=50)
        cliente = ClienteReal.objects.create(
            razao_social="Beta", cnpj="11444777000161",
            plano=plano, email_contato="b@x.com", dia_vencimento=10,
        )

        assinatura = AssinaturaService.contratar(cliente=cliente, plano=plano)
        self.assertIsNotNone(assinatura.pk)
        self.assertEqual(assinatura.asaas_subscription_id, "")
