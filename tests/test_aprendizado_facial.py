"""
Kronus — o cadastro facial aprende com as batidas.

Aprender com o proprio resultado e realimentacao: se uma identificacao
errada virar referencia, o erro deixa de ser um episodio e passa a ser o
cadastro. O que estes testes guardam sao as travas — nao o "aprendeu?",
mas o "recusou aprender quando devia recusar?".
"""
from django.test import TestCase

from apps.facial.aprendizado import (
    FRACAO_PARA_APRENDER,
    MARGEM_PARA_APRENDER,
    MAXIMO_APRENDIDAS,
    pode_aprender,
)
from apps.facial.services import ResultadoReconhecimento


def resultado(distancia, segunda=None, identificado=True):
    r = ResultadoReconhecimento(identificado=identificado, distancia=distancia)
    r.segunda_distancia = segunda
    return r


class TravasTests(TestCase):
    LIMIAR = 0.52

    def test_aprende_com_folga_larga(self):
        # 0,15 esta bem abaixo da metade do limiar, e o segundo colocado
        # a 0,60 nao deixa duvida.
        self.assertTrue(pode_aprender(resultado(0.15, 0.60), self.LIMIAR))

    def test_nao_aprende_com_acerto_no_fio(self):
        """
        0,45 passa no limiar e registra o ponto. Nao vira referencia:
        um acerto apertado gravado como cadastro empurra a pessoa para
        mais perto de quem ela ja quase se confundiu.
        """
        self.assertFalse(pode_aprender(resultado(0.45, 0.90), self.LIMIAR))

    def test_nao_aprende_com_segundo_colocado_perto(self):
        # Passou, mas podia ter sido sorte — e sorte nao se grava.
        self.assertFalse(pode_aprender(resultado(0.15, 0.25), self.LIMIAR))

    def test_nao_aprende_com_quem_nao_foi_identificado(self):
        self.assertFalse(
            pode_aprender(resultado(0.15, 0.90, identificado=False), self.LIMIAR)
        )

    def test_sozinho_na_galeria_ainda_aprende(self):
        # Sem segundo colocado nao ha de quem se afastar; o que decide e
        # a folga ate o limiar.
        self.assertTrue(pode_aprender(resultado(0.12, None), self.LIMIAR))

    def test_a_faixa_de_aprendizado_e_metade_do_limiar(self):
        # Fixado porque e o numero que separa "acerto folgado" de
        # "acerto qualquer": medido em producao, as identificacoes
        # legitimas ficam entre 0,08 e 0,29.
        self.assertLessEqual(FRACAO_PARA_APRENDER, 0.5)

    def test_a_margem_para_aprender_e_maior_que_a_do_ponto(self):
        from django.conf import settings

        self.assertGreater(MARGEM_PARA_APRENDER, settings.FACE_MARGEM_MINIMA)


class MaioriaSupervisionadaTests(TestCase):
    """
    O cadastro original e supervisionado: alguem viu quem estava na
    frente da camera. As aprendidas nao. A maioria precisa continuar
    sendo a que foi conferida.
    """

    def test_o_limite_deixa_a_maioria_supervisionada(self):
        from django.conf import settings

        maximo = settings.FACE_AMOSTRAS_MAXIMAS
        self.assertLess(
            MAXIMO_APRENDIDAS, maximo - MAXIMO_APRENDIDAS,
            "com este limite, as aprendidas passariam a ser maioria",
        )


class LigadoPorPadraoTests(TestCase):
    """
    O aprendizado passou a nascer ligado.

    Ficou desligado enquanto aprender com o proprio resultado era
    realimentacao sem freio. As travas mudaram isso: so aprende com
    batida folgada, so o que traz condicao nova, e nunca o que encosta
    em outra pessoa — esta ultima e a que impede o rosto de uma irma de
    entrar na galeria da outra.

    Com elas, o risco de NAO aprender ficou maior: sem aprender, a
    pessoa se afasta da propria referencia e o totem passa a pedir CPF
    de quem sempre reconheceu.
    """

    def test_a_empresa_ja_nasce_aprendendo(self):
        from apps.clientes.models import Empresa

        campo = Empresa._meta.get_field("aprendizado_facial")
        self.assertTrue(
            campo.default,
            "sem aprender, a pessoa se afasta da propria referencia",
        )

    def test_as_travas_que_permitem_ligar_continuam_de_pe(self):
        """
        O padrao novo se apoia nelas: se alguma sumir, ligar por padrao
        deixa de ser seguro e este teste tem de doer.
        """
        from apps.facial import aprendizado

        self.assertTrue(hasattr(aprendizado, "_nao_aproxima_de_outro"))
        self.assertTrue(hasattr(aprendizado, "_traz_algo_novo"))
        self.assertGreater(aprendizado.MARGEM_PARA_APRENDER, 0.1)
        self.assertLessEqual(aprendizado.FRACAO_PARA_APRENDER, 0.5)

    def test_a_amostra_registra_de_onde_veio(self):
        from apps.facial.models import FaceRegistro

        campo = FaceRegistro._meta.get_field("aprendida")
        self.assertFalse(campo.default)


class NovidadeTests(TestCase):
    """
    O que decide o aprendizado e a foto trazer algo novo, e nao o
    calendario.

    Guardar uma captura quase igual a uma que ja esta la ocupa um lugar
    da cota e nao melhora nada: o cadastro fica mais estreito, e nao mais
    largo. O que faz o reconhecimento melhorar e cobrir condicao que
    ainda nao estava coberta.
    """

    def test_a_regra_de_novidade_existe_e_e_o_criterio(self):
        from apps.facial import aprendizado

        self.assertGreater(aprendizado.NOVIDADE_MINIMA, 0)
        # E o calendario deixa de ser a trava principal.
        self.assertLessEqual(aprendizado.DIAS_ENTRE_APRENDIZADOS, 1)

    def test_a_novidade_fica_dentro_da_faixa_da_mesma_pessoa(self):
        """
        Alta demais e o sistema so aprenderia com fotos que quase nao
        parecem a pessoa; baixa demais aprenderia repeticao. As poses do
        cadastro ficam entre 0,05 e 0,48 entre si — a faixa util esta
        dentro disso.
        """
        from django.conf import settings
        from apps.facial import aprendizado

        self.assertLess(aprendizado.NOVIDADE_MINIMA, settings.FACE_RECOGNITION_THRESHOLD)

    def test_na_duvida_aprende(self):
        # Falha ao medir (motor fora do ar) nao pode virar motivo para
        # nunca mais aprender: foto redundante custa menos do que
        # cadastro parado no tempo.
        from apps.facial.aprendizado import _traz_algo_novo

        class ServicoQuebrado:
            provedor = None

            def candidatos(self, _):
                raise RuntimeError("motor fora do ar")

        self.assertTrue(_traz_algo_novo(ServicoQuebrado(), None, b""))


class AposentadoriaTests(TestCase):
    """
    A aprendida sai antes da supervisionada.

    So por recencia, cada foto aprendida aposentava uma do cadastro
    original — e o cadastro original e o que alguem conferiu, com a
    pessoa na frente da camera. Em poucos meses a referencia inteira
    teria virado material coletado sem supervisao.
    """

    def _pessoa(self):
        from datetime import date
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.rh.models import Colaborador

        plano = Plano.objects.create(nome="P", slug="p")
        cliente = Cliente.objects.create(
            razao_social="C", cnpj="45997418000153",
            plano=plano, email_contato="c@x.com",
        )
        empresa = Empresa.objects.create(
            cliente=cliente, razao_social="E", cnpj="45997418000234",
        )
        return Colaborador.objects.create(
            empresa=empresa, nome_completo="Ana", cpf="52998224725",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )

    def _amostra(self, pessoa, aprendida, quando):
        import numpy as np
        from apps.facial.models import FaceRegistro

        r = FaceRegistro(colaborador=pessoa, angulo="frontal", modelo="Facenet512",
                         detector="mtcnn", qualidade=90, aprendida=aprendida)
        r.definir_embedding(np.ones(512, dtype=np.float32), salvar=False)
        r.save()
        FaceRegistro.objects.filter(pk=r.pk).update(created_at=quando)
        return r

    def test_a_supervisionada_antiga_sobrevive_a_aprendida(self):
        from datetime import timedelta

        from django.conf import settings
        from django.utils import timezone

        from apps.facial.models import FaceRegistro
        from apps.facial.services import FaceRecognitionService

        pessoa = self._pessoa()
        agora = timezone.now()
        maximo = settings.FACE_AMOSTRAS_MAXIMAS

        # Cadastro supervisionado, o mais antigo de todos.
        supervisionadas = [
            self._amostra(pessoa, False, agora - timedelta(days=100 - i))
            for i in range(maximo)
        ]
        # E uma aprendida recente, que estoura o limite.
        aprendida = self._amostra(pessoa, True, agora)

        FaceRecognitionService._aposentar_excedentes(pessoa)

        aprendida.refresh_from_db()
        self.assertFalse(
            aprendida.ativo,
            "a aprendida deveria sair antes de qualquer supervisionada",
        )
        self.assertEqual(
            FaceRegistro.objects.filter(
                colaborador=pessoa, ativo=True, aprendida=False
            ).count(),
            maximo,
        )
