"""
Kronus — desconto comercial na assinatura.

Concedido pelo master, e nao pelo cliente. Fica na assinatura porque e o
contrato: muda com a renegociacao, e nao com o cadastro da empresa.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.faturamento.models import Assinatura
from apps.master.models import Plano


class BaseDesconto(TestCase):
    def setUp(self):
        self.plano = Plano.objects.create(
            nome="Pro", slug="pro", preco_mensal=Decimal("300.00"),
            preco_por_totem=Decimal("50.00"), max_colaboradores=50,
        )
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=self.plano, email_contato="a@x.com",
        )
        self.assinatura = Assinatura.objects.create(
            cliente=self.cliente, plano=self.plano,
            valor=Decimal("300.00"), totens_contratados=2,
        )


class CalculoTests(BaseDesconto):
    def test_sem_desconto_o_total_nao_muda(self):
        self.assertEqual(self.assinatura.valor_total(), Decimal("400.00"))
        self.assertFalse(self.assinatura.tem_desconto)

    def test_percentual_incide_sobre_o_total_com_adicionais(self):
        """
        Aplicar so no plano e deixar os adicionais cheios daria um numero
        que nem o comercial nem o cliente reconhecem como o combinado.
        """
        self.assinatura.desconto_percentual = Decimal("10")
        self.assertEqual(self.assinatura.desconto_aplicado(), Decimal("40.00"))
        self.assertEqual(self.assinatura.valor_total(), Decimal("360.00"))

    def test_valor_fixo_desconta_o_valor(self):
        self.assinatura.desconto_valor = Decimal("50.00")
        self.assertEqual(self.assinatura.valor_total(), Decimal("350.00"))

    def test_os_dois_somam(self):
        # Um acordo pode ser "10% e mais R$ 50", e obrigar a escolher um
        # so faria alguem converter na mao e errar.
        self.assinatura.desconto_percentual = Decimal("10")
        self.assinatura.desconto_valor = Decimal("50.00")
        self.assertEqual(self.assinatura.valor_total(), Decimal("310.00"))

    def test_o_desconto_nunca_deixa_o_total_negativo(self):
        self.assinatura.desconto_valor = Decimal("9999.00")
        self.assertEqual(self.assinatura.valor_total(), Decimal("0.00"))

    def test_desconto_vencido_nao_desconta(self):
        self.assinatura.desconto_percentual = Decimal("50")
        self.assinatura.desconto_ate = timezone.localdate() - timedelta(days=1)
        self.assertEqual(self.assinatura.valor_total(), Decimal("400.00"))

    def test_desconto_vencido_continua_gravado(self):
        # "Por que o valor mudou?" precisa de resposta: apagar o desconto
        # ao vencer deixaria a pergunta sem historico.
        self.assinatura.desconto_percentual = Decimal("50")
        self.assinatura.desconto_motivo = "Campanha de lançamento"
        self.assinatura.desconto_ate = date(2020, 1, 1)
        self.assertTrue(self.assinatura.tem_desconto)
        self.assertEqual(self.assinatura.desconto_motivo, "Campanha de lançamento")

    def test_o_ultimo_dia_ainda_vale(self):
        self.assinatura.desconto_percentual = Decimal("10")
        self.assinatura.desconto_ate = timezone.localdate()
        self.assertEqual(self.assinatura.valor_total(), Decimal("360.00"))


class TelaDoMasterTests(BaseDesconto):
    def _master(self):
        from apps.accounts.models import CustomUser

        usuario = CustomUser.objects.create_superuser(
            email="m@x.test", password="Prova!12345", nome_completo="M",
        )
        self.client.force_login(usuario)
        return usuario

    def _aplicar(self, **dados):
        from django.urls import reverse

        corpo = {"acao": "desconto", "desconto_percentual": "0",
                 "desconto_valor": "0", "desconto_motivo": "", **dados}
        return self.client.post(
            reverse("master:assinatura_detalhe", args=[self.assinatura.pk]),
            corpo, follow=True,
        )

    def test_o_master_concede_o_desconto(self):
        self._master()
        self._aplicar(desconto_percentual="15", desconto_motivo="Fidelidade")

        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.desconto_percentual, Decimal("15.00"))
        self.assertEqual(self.assinatura.valor_total(), Decimal("340.00"))

    def test_desconto_sem_motivo_e_recusado(self):
        """
        Um numero sem explicacao vira, um ano depois, uma pergunta que
        ninguem sabe responder na hora de renovar.
        """
        self._master()
        resposta = self._aplicar(desconto_percentual="15")

        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.desconto_percentual, Decimal("0.00"))
        self.assertContains(resposta, "motivo")

    def test_aceita_virgula_do_teclado_brasileiro(self):
        # "10,00" chega assim do teclado, e `Decimal("10,00")` estoura.
        self._master()
        self._aplicar(desconto_percentual="12,5", desconto_motivo="Acordo")

        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.desconto_percentual, Decimal("12.50"))

    def test_percentual_acima_de_cem_e_recusado(self):
        self._master()
        self._aplicar(desconto_percentual="150", desconto_motivo="x")

        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.desconto_percentual, Decimal("0.00"))

    def test_zerar_os_dois_remove_o_desconto(self):
        self._master()
        self.assinatura.desconto_percentual = Decimal("20")
        self.assinatura.desconto_motivo = "antigo"
        self.assinatura.save()

        self._aplicar()
        self.assinatura.refresh_from_db()
        self.assertFalse(self.assinatura.tem_desconto)

    def test_a_concessao_fica_na_auditoria(self):
        # Desconto e dinheiro: quem concedeu e quando precisa ficar
        # registrado.
        from apps.master.models import LogAcessoMaster

        self._master()
        self._aplicar(desconto_percentual="10", desconto_motivo="Campanha")

        self.assertTrue(
            LogAcessoMaster.objects.filter(detalhes__icontains="Desconto").exists()
        )
