"""
Kronus — o cadastro facial está melhorando?

O autoaprendizado promete acompanhar a pessoa: cabelo que muda, óculos
novo. Promessa fácil de fazer e difícil de verificar — e um sistema que
aprende sozinho sem ninguém conseguir olhar é um sistema em que se
acredita, não um que se sabe.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.facial.evolucao import (
    JANELA_EM_DIAS,
    MINIMO_DE_BATIDAS,
    VARIACAO_RELEVANTE,
    evolucao_de,
    panorama,
)


class BaseEvolucao(TestCase):
    def setUp(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.rh.models import Colaborador

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
        self.pessoa = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Fulano de Tal",
            cpf="52998224725", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2020, 1, 1), face_registrada=True,
        )
        self.agora = timezone.now()

    def _batida(self, distancia, dias_atras):
        from apps.facial.models import TentativaReconhecimento as T

        t = T.objects.create(
            empresa=self.empresa, colaborador=self.pessoa,
            resultado=T.Resultado.IDENTIFICADO, distancia=distancia,
        )
        T.objects.filter(pk=t.pk).update(
            created_at=self.agora - timedelta(days=dias_atras)
        )
        return t

    def _semana_passada(self, distancia, quantas=MINIMO_DE_BATIDAS):
        for i in range(quantas):
            self._batida(distancia, JANELA_EM_DIAS + 1 + i * 0.1)

    def _esta_semana(self, distancia, quantas=MINIMO_DE_BATIDAS):
        for i in range(quantas):
            self._batida(distancia, 1 + i * 0.1)


class ComparacaoTests(BaseEvolucao):
    def test_distancia_menor_e_melhora(self):
        self._semana_passada(0.32)
        self._esta_semana(0.18)
        r = evolucao_de(self.pessoa, ate=self.agora)
        self.assertEqual(r["situacao"], "melhorou")
        self.assertLess(r["variacao"], 0)

    def test_distancia_maior_e_piora(self):
        self._semana_passada(0.18)
        self._esta_semana(0.34)
        r = evolucao_de(self.pessoa, ate=self.agora)
        self.assertEqual(r["situacao"], "piorou")
        self.assertGreater(r["variacao"], 0)

    def test_variacao_pequena_e_ruido_e_nao_tendencia(self):
        """
        A distancia oscila com luz e angulo. Sem um piso, qualquer
        flutuacao viraria seta, e a tela mostraria movimento onde nao
        houve nenhum.
        """
        self._semana_passada(0.20)
        self._esta_semana(0.20 + VARIACAO_RELEVANTE / 2)
        self.assertEqual(
            evolucao_de(self.pessoa, ate=self.agora)["situacao"], "estavel"
        )

    def test_usa_mediana_e_nao_media(self):
        """
        Uma batida ruim isolada — quadro tremido, alguem passando atras —
        puxa a media e some na mediana. Interessa o dia tipico, nao o
        pior.
        """
        self._semana_passada(0.20)
        for _ in range(MINIMO_DE_BATIDAS):
            self._batida(0.20, 1)
        self._batida(0.95, 1)   # o quadro ruim

        r = evolucao_de(self.pessoa, ate=self.agora)
        self.assertEqual(r["mediana_agora"], 0.20)
        self.assertEqual(r["situacao"], "estavel")


class HonestidadeDosDadosTests(BaseEvolucao):
    def test_poucas_batidas_nao_viram_tendencia(self):
        """
        Com duas ou tres, a mediana e a propria batida. Dizer "ainda nao
        da para saber" e melhor que um numero que parece medicao.
        """
        self._semana_passada(0.30, quantas=2)
        self._esta_semana(0.10, quantas=2)
        r = evolucao_de(self.pessoa, ate=self.agora)
        self.assertEqual(r["situacao"], "poucas_batidas")
        self.assertIsNone(r["variacao"])

    def test_sem_batida_nenhuma_nao_inventa_numero(self):
        r = evolucao_de(self.pessoa, ate=self.agora)
        self.assertEqual(r["situacao"], "poucas_batidas")
        self.assertIsNone(r["mediana_antes"])

    def test_so_conta_batida_identificada(self):
        """
        Tentativa recusada nao tem distancia que descreva a pessoa —
        descreve o quadro. Misturar as duas mediria outra coisa.
        """
        from apps.facial.models import TentativaReconhecimento as T

        self._semana_passada(0.20)
        self._esta_semana(0.20)
        for _ in range(6):
            t = T.objects.create(
                empresa=self.empresa, colaborador=self.pessoa,
                resultado=T.Resultado.NAO_IDENTIFICADO, distancia=0.90,
            )
            T.objects.filter(pk=t.pk).update(
                created_at=self.agora - timedelta(days=1)
            )

        self.assertEqual(evolucao_de(self.pessoa, ate=self.agora)["mediana_agora"], 0.20)

    def test_batida_antiga_nao_entra_na_janela(self):
        self._batida(0.05, JANELA_EM_DIAS * 4)
        self._semana_passada(0.20)
        self._esta_semana(0.20)
        r = evolucao_de(self.pessoa, ate=self.agora)
        self.assertEqual(r["batidas_antes"], MINIMO_DE_BATIDAS)


class AmostrasTests(BaseEvolucao):
    def test_separa_o_que_veio_do_aprendizado(self):
        """
        A maioria tem de continuar sendo o cadastro supervisionado —
        alguem viu quem estava na frente da camera. Ver a proporcao e o
        que permite perceber se isso deixou de valer.
        """
        from apps.facial.models import FaceRegistro

        for i in range(5):
            FaceRegistro.objects.create(
                colaborador=self.pessoa, angulo="frontal", aprendida=False,
            )
        for i in range(2):
            FaceRegistro.objects.create(
                colaborador=self.pessoa, angulo="frontal", aprendida=True,
            )

        r = evolucao_de(self.pessoa, ate=self.agora)
        self.assertEqual(r["amostras_supervisionadas"], 5)
        self.assertEqual(r["amostras_aprendidas"], 2)


class PanoramaTests(BaseEvolucao):
    def test_quem_esta_pior_hoje_aparece_primeiro(self):
        """
        Ordenado pela distancia atual, e nao pela variacao: quem esta
        longe hoje incomoda hoje, mesmo tendo melhorado desde a semana
        passada.
        """
        from apps.rh.models import Colaborador

        outro = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Sicrano de Tal",
            cpf="11144477735", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2020, 1, 1), face_registrada=True,
        )
        self._semana_passada(0.20)
        self._esta_semana(0.15)

        from apps.facial.models import TentativaReconhecimento as T

        for i in range(MINIMO_DE_BATIDAS * 2):
            t = T.objects.create(
                empresa=self.empresa, colaborador=outro,
                resultado=T.Resultado.IDENTIFICADO, distancia=0.40,
            )
            T.objects.filter(pk=t.pk).update(
                created_at=self.agora - timedelta(days=1 if i % 2 else JANELA_EM_DIAS + 1)
            )

        linhas = panorama(self.empresa, ate=self.agora)["linhas"]
        self.assertEqual(linhas[0]["colaborador"], outro)

    def test_quem_nao_tem_medida_vai_para_o_fim(self):
        """
        Ausencia de informacao nao e problema. Misturar as duas esconde
        quem precisa de acao.
        """
        from apps.rh.models import Colaborador

        Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Sem Dados",
            cpf="11144477735", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2020, 1, 1), face_registrada=True,
        )
        self._semana_passada(0.30)
        self._esta_semana(0.30)

        linhas = panorama(self.empresa, ate=self.agora)["linhas"]
        self.assertEqual(linhas[-1]["colaborador"].nome_completo, "Sem Dados")

    def test_conta_quem_melhorou_e_quem_piorou(self):
        self._semana_passada(0.32)
        self._esta_semana(0.18)
        r = panorama(self.empresa, ate=self.agora)
        self.assertEqual(r["melhoraram"], 1)
        self.assertEqual(r["pioraram"], 0)
