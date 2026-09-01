"""
Kronus — lembretes de vencimento.

Dois avisos com tons deliberadamente diferentes: um lembrete antes, um
pedido de atencao depois. Nenhum dos dois cobra.

Quem paga em dia nao precisa de cobranca — precisa de aviso. E quem
atrasou quase sempre esqueceu: o texto duro ofende essa maioria e nao
convence a minoria que decidiu nao pagar.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.clientes.models import Cliente
from apps.faturamento.models import Assinatura, Cobranca
from apps.master.models import Plano
from apps.notificacoes.models import Notificacao


class BaseCobranca(TestCase):
    def setUp(self):
        from apps.accounts.models import CustomUser as Usuario

        self.plano = Plano.objects.create(
            nome="Pro", slug="pro", max_empresas=3, max_colaboradores=50,
            preco_mensal=Decimal("300"),
        )
        self.cliente = Cliente.objects.create(
            razao_social="Cliente LTDA", nome_fantasia="Cliente",
            cnpj="11222333000181", email_contato="c@t.com", plano=self.plano,
        )
        self.dono = Usuario.objects.create_user(
            email="dono@t.com", password="x", nome_completo="Dono da Conta",
            tipo="cliente", cliente=self.cliente,
        )
        self.assinatura = Assinatura.objects.create(
            cliente=self.cliente, plano=self.plano, valor=Decimal("300"),
            data_inicio=date.today(),
        )

    def _cobranca(self, vencimento, status=Cobranca.Status.PENDENTE):
        return Cobranca.objects.create(
            assinatura=self.assinatura, valor=Decimal("300"),
            vencimento=vencimento, status=status,
        )

    def _rodar(self):
        from apps.faturamento.tasks import lembrar_vencimentos

        return lembrar_vencimentos()


class LembreteAntesTests(BaseCobranca):
    def test_avisa_tres_dias_antes(self):
        from apps.faturamento.tasks import DIAS_DE_ANTECEDENCIA

        self._cobranca(date.today() + timedelta(days=DIAS_DE_ANTECEDENCIA))
        self.assertEqual(self._rodar()["lembrados"], 1)
        self.assertEqual(Notificacao.objects.count(), 1)

    def test_nao_avisa_antes_da_hora(self):
        self._cobranca(date.today() + timedelta(days=10))
        self.assertEqual(self._rodar()["lembrados"], 0)

    def test_nao_repete_o_mesmo_aviso(self):
        """
        Dois e-mails iguais sobre a mesma fatura fazem o cliente parar de
        ler os proximos.
        """
        from apps.faturamento.tasks import DIAS_DE_ANTECEDENCIA

        self._cobranca(date.today() + timedelta(days=DIAS_DE_ANTECEDENCIA))
        self._rodar()
        self.assertEqual(self._rodar()["lembrados"], 0)
        self.assertEqual(Notificacao.objects.count(), 1)

    def test_fatura_paga_nao_gera_lembrete(self):
        from apps.faturamento.tasks import DIAS_DE_ANTECEDENCIA

        self._cobranca(
            date.today() + timedelta(days=DIAS_DE_ANTECEDENCIA),
            status=Cobranca.Status.RECEBIDA,
        )
        self.assertEqual(self._rodar()["lembrados"], 0)

    def test_o_lembrete_nao_e_alarme(self):
        """Antes do vencimento nao ha nada de errado acontecendo."""
        from apps.faturamento.tasks import DIAS_DE_ANTECEDENCIA

        self._cobranca(date.today() + timedelta(days=DIAS_DE_ANTECEDENCIA))
        self._rodar()
        self.assertEqual(Notificacao.objects.first().nivel, Notificacao.Nivel.INFO)


class AvisoDeAtrasoTests(BaseCobranca):
    def test_avisa_depois_do_vencimento(self):
        self._cobranca(date.today() - timedelta(days=1))
        self.assertEqual(self._rodar()["atrasados"], 1)

    def test_repete_com_intervalo_e_nao_todo_dia(self):
        """Diario vira assedio; uma vez so se perde."""
        self._cobranca(date.today() - timedelta(days=5))
        self.assertEqual(self._rodar()["atrasados"], 1)
        self.assertEqual(self._rodar()["atrasados"], 0)

    def test_para_de_avisar_depois_de_um_mes(self):
        """
        Passado um mes o caso virou conversa comercial, e insistir por
        robo atrapalha quem for negociar.
        """
        from apps.faturamento.tasks import LIMITE_DE_AVISOS

        self._cobranca(date.today() - timedelta(days=LIMITE_DE_AVISOS + 1))
        self.assertEqual(self._rodar()["atrasados"], 0)

    def test_o_texto_nao_ameaca(self):
        self._cobranca(date.today() - timedelta(days=2))
        self._rodar()
        texto = (Notificacao.objects.first().mensagem or "").lower()
        for palavra in ("suspens", "bloque", "cortad", "juros", "multa", "negativ"):
            self.assertNotIn(palavra, texto)

    def test_reconhece_que_o_pagamento_pode_estar_a_caminho(self):
        """
        A confirmacao demora. Sem esta ressalva, o aviso acusa quem ja
        pagou ontem.
        """
        self._cobranca(date.today() - timedelta(days=1))
        self._rodar()
        self.assertIn("já pagou", Notificacao.objects.first().mensagem)


class DestinatariosTests(BaseCobranca):
    def test_so_quem_administra_a_conta_recebe(self):
        """
        Fatura e assunto de quem assina o contrato. Mandar o valor da
        mensalidade para a operacao inteira vaza informacao comercial
        dentro do proprio cliente.
        """
        from apps.accounts.models import CustomUser as Usuario

        Usuario.objects.create_user(
            email="rh@t.com", password="x", nome_completo="Pessoa do RH",
            tipo="rh", cliente=self.cliente,
        )
        self._cobranca(date.today() - timedelta(days=1))
        self._rodar()
        self.assertEqual(Notificacao.objects.count(), 1)
        self.assertEqual(Notificacao.objects.first().destinatario, self.dono)


class LinkDaFaturaTests(BaseCobranca):
    def test_o_link_aponta_para_o_dominio_do_kronus(self):
        """
        Um e-mail sobre dinheiro que manda para outro dominio e
        indistinguivel de golpe para quem foi treinado a desconfiar.
        """
        from apps.faturamento.tasks import _url_da_fatura

        cobranca = self._cobranca(date.today())
        url = _url_da_fatura(cobranca)
        self.assertIn(str(cobranca.uuid), url)
        self.assertIn("/fatura/", url)

    def test_a_pagina_recusa_quem_nao_e_dono(self):
        from apps.accounts.models import CustomUser as Usuario

        outro_cliente = Cliente.objects.create(
            razao_social="Outro LTDA", cnpj="60746948000112",
            email_contato="o@t.com", plano=self.plano,
        )
        intruso = Usuario.objects.create_user(
            email="i@t.com", password="x", nome_completo="Outro Dono",
            tipo="cliente", cliente=outro_cliente,
        )
        cobranca = self._cobranca(date.today())
        self.client.force_login(intruso)
        resposta = self.client.get(f"/faturamento/fatura/{cobranca.uuid}/")
        self.assertEqual(resposta.status_code, 404)

    def test_o_dono_abre_a_propria_fatura(self):
        cobranca = self._cobranca(date.today())
        self.client.force_login(self.dono)
        resposta = self.client.get(f"/faturamento/fatura/{cobranca.uuid}/")
        self.assertEqual(resposta.status_code, 200)
