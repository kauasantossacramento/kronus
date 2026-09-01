"""
Kronus — quantas tentativas custa uma batida.

O painel de semelhancas media a galeria, que e um dado teorico: 13 de 17
pessoas apareciam em algum par proximo, e isso se leu como "quase todo
mundo precisa recadastrar". Um par proximo so custa alguma coisa quando
custa — medir o custo direto dispensa a inferencia.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.facial.repeticao import CORTE_DE_SESSAO, medir


class BaseTentativas(TestCase):
    def setUp(self):
        from decimal import Decimal

        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.totem.models import Totem

        plano = Plano.objects.create(
            nome="P", slug="p", max_empresas=3, max_colaboradores=50,
            preco_mensal=Decimal("100"),
        )
        cliente = Cliente.objects.create(
            razao_social="C LTDA", cnpj="11222333000181",
            email_contato="c@t.com", plano=plano,
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="E LTDA", cnpj="60746948000112",
        )
        self.totem = Totem.objects.create(
            empresa=self.empresa, apelido="T1",
        )
        self.base = timezone.now()

    def _tentativa(self, segundos, desfecho, colaborador=None, totem=None):
        from apps.facial.models import TentativaReconhecimento as T

        t = T.objects.create(
            empresa=self.empresa,
            totem=totem or self.totem,
            colaborador=colaborador,
            resultado=(
                T.Resultado.IDENTIFICADO if colaborador
                else T.Resultado.NAO_IDENTIFICADO
            ),
            desfecho=desfecho,
        )
        # `created_at` e auto_now_add: so um update escapa dele.
        T.objects.filter(pk=t.pk).update(
            created_at=self.base + timedelta(seconds=segundos)
        )
        t.refresh_from_db()
        return t

    def _pessoa(self, nome="Fulano de Tal", cpf="52998224725"):
        from datetime import date

        from apps.rh.models import Colaborador

        return Colaborador.objects.create(
            empresa=self.empresa, nome_completo=nome, cpf=cpf,
            data_nascimento=date(1990, 1, 1), data_admissao=date(2020, 1, 1),
        )


class ContagemTests(BaseTentativas):
    def test_batida_de_primeira_custa_uma_tentativa(self):
        from apps.facial.models import TentativaReconhecimento as T

        p = self._pessoa()
        self._tentativa(0, T.Desfecho.PONTO, p)
        r = medir(empresa=self.empresa)
        self.assertEqual(r["batidas"], 1)
        self.assertEqual(r["media"], 1.0)
        self.assertEqual(r["de_primeira"], 1)

    def test_conta_as_recusas_antes_da_batida(self):
        from apps.facial.models import TentativaReconhecimento as T

        p = self._pessoa()
        self._tentativa(0, T.Desfecho.RECUSADO)
        self._tentativa(3, T.Desfecho.RECUSADO)
        self._tentativa(6, T.Desfecho.PONTO, p)
        r = medir(empresa=self.empresa)
        self.assertEqual(r["media"], 3.0)
        self.assertEqual(r["pior"], 3)
        self.assertEqual(r["de_primeira"], 0)

    def test_sessoes_distantes_nao_se_misturam(self):
        """
        Duas tentativas separadas por minutos sao de pessoas diferentes,
        ou da mesma em outro momento. Juntar infla a conta com tempo em
        que ninguem estava tentando.
        """
        from apps.facial.models import TentativaReconhecimento as T

        p = self._pessoa()
        self._tentativa(0, T.Desfecho.PONTO, p)
        depois = CORTE_DE_SESSAO.total_seconds() + 60
        self._tentativa(depois, T.Desfecho.PONTO, p)
        r = medir(empresa=self.empresa)
        self.assertEqual(r["batidas"], 2)
        self.assertEqual(r["media"], 1.0)

    def test_totens_diferentes_nunca_entram_na_mesma_sessao(self):
        from apps.facial.models import TentativaReconhecimento as T
        from apps.totem.models import Totem

        outro = Totem.objects.create(empresa=self.empresa, apelido="T2")
        p = self._pessoa()
        self._tentativa(0, T.Desfecho.RECUSADO)
        self._tentativa(2, T.Desfecho.PONTO, p, totem=outro)
        r = medir(empresa=self.empresa)
        # A recusa do T1 nao pode ser cobrada da batida do T2.
        self.assertEqual(r["media"], 1.0)


class AbandonoTests(BaseTentativas):
    def test_quem_tentou_e_desistiu_conta_como_abandono(self):
        from apps.facial.models import TentativaReconhecimento as T

        p = self._pessoa()
        self._tentativa(0, T.Desfecho.RECUSADO, p)
        self._tentativa(3, T.Desfecho.RECUSADO, p)
        r = medir(empresa=self.empresa)
        self.assertEqual(r["abandonadas"], 1)
        self.assertEqual(r["batidas"], 0)

    def test_camera_vendo_a_parede_nao_e_abandono(self):
        """
        Sessao inteira sem identificar ninguem e o totem olhando para o
        corredor vazio — contar como desistencia inventaria um problema
        que nao existe.
        """
        from apps.facial.models import TentativaReconhecimento as T

        self._tentativa(0, T.Desfecho.RECUSADO)
        self._tentativa(3, T.Desfecho.RECUSADO)
        self.assertEqual(medir(empresa=self.empresa)["abandonadas"], 0)


class QuemMaisRepeteTests(BaseTentativas):
    def test_aponta_quem_gasta_mais_tentativas(self):
        """
        A media esconde a pessoa que tenta oito vezes atras de nove que
        acertam de primeira. E a pessoa e que precisa recadastrar.
        """
        from apps.facial.models import TentativaReconhecimento as T

        facil = self._pessoa("Ana Facil", "52998224725")
        dificil = self._pessoa("Bruno Dificil", "11144477735")

        self._tentativa(0, T.Desfecho.PONTO, facil)
        self._tentativa(300, T.Desfecho.RECUSADO)
        self._tentativa(303, T.Desfecho.RECUSADO)
        self._tentativa(306, T.Desfecho.RECUSADO)
        self._tentativa(309, T.Desfecho.PONTO, dificil)

        r = medir(empresa=self.empresa)
        self.assertEqual(r["por_pessoa"][0]["colaborador"], dificil)
        self.assertEqual(r["por_pessoa"][0]["media"], 4.0)

    def test_sem_dados_nao_inventa_numero(self):
        r = medir(empresa=self.empresa)
        self.assertIsNone(r["media"])
        self.assertEqual(r["batidas"], 0)
