"""
Kronus — o totem nao pode registrar ponto no nome de outra pessoa.

Escrito a partir de um caso real. Em producao, um colaborador tinha
cinco amostras faciais; a quinta, capturada tres minutos depois das
outras, estava a 0,70 delas — distancia de pessoa diferente. Como o
reconhecimento passara a ficar com a MENOR distancia entre as amostras,
aquela captura virou uma porta: um visitante foi identificado como o
titular, a 0,41.

A assimetria e o que decide o desenho: um falso NEGATIVO custa uma
digitacao de CPF; um falso POSITIVO custa ponto batido no nome de outro,
com consequencia trabalhista. As tres protecoes abaixo escolhem sempre o
lado do incomodo.
"""
import numpy as np
from django.test import TestCase, override_settings

from apps.facial.services import FaceRecognitionService


def vetor(semente: int, dim: int = 512) -> np.ndarray:
    """Vetor unitario reprodutivel — faz o papel de um embedding."""
    estado = np.random.RandomState(semente)
    v = estado.normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def perto(base: np.ndarray, distancia: float, semente: int) -> np.ndarray:
    """Vetor a uma distancia de cosseno aproximada de `base`."""
    estado = np.random.RandomState(semente)
    ruido = estado.normal(size=base.shape).astype(np.float32)
    ruido -= base * float(ruido @ base)
    ruido /= np.linalg.norm(ruido)
    alvo = 1.0 - distancia            # similaridade desejada
    v = base * alvo + ruido * np.sqrt(max(1.0 - alvo ** 2, 0.0))
    return (v / np.linalg.norm(v)).astype(np.float32)


class PontuacaoTests(TestCase):
    def setUp(self):
        self.servico = FaceRecognitionService.__new__(FaceRecognitionService)
        self.servico.margem_minima = 0.06

    def test_uma_amostra_fora_do_lugar_nao_autoriza_sozinha(self):
        """
        O defeito de producao, reproduzido.

        Quatro amostras coerentes do titular, mais uma contaminada. Um
        rosto que so se parece com a contaminada nao pode ser aceito.
        """
        titular = vetor(1)
        contaminada = vetor(99)          # longe do titular
        amostras = [
            perto(titular, 0.10, 11),
            perto(titular, 0.15, 12),
            perto(titular, 0.20, 13),
            perto(titular, 0.25, 14),
            contaminada,
        ]
        visitante = perto(contaminada, 0.20, 21)

        (_, distancia), = self.servico._pontuar(visitante, {7: amostras})

        menor = min(self.servico._distancia(visitante, a) for a in amostras)
        self.assertLess(menor, 0.55, "o cenario so faz sentido se a menor passaria")
        self.assertGreater(
            distancia, 0.55,
            "uma unica amostra ruim voltou a abrir a porta sozinha",
        )

    def test_o_titular_continua_sendo_reconhecido(self):
        """A protecao nao pode custar o reconhecimento de quem e real."""
        titular = vetor(1)
        amostras = [perto(titular, d, s) for d, s in
                    ((0.10, 11), (0.15, 12), (0.20, 13), (0.25, 14))]
        ele_mesmo = perto(titular, 0.18, 31)

        (_, distancia), = self.servico._pontuar(ele_mesmo, {7: amostras})
        self.assertLess(distancia, 0.55)

    def test_duas_amostras_de_cameras_diferentes_ainda_bastam(self):
        """
        A tolerancia entre cameras nao pode ser perdida: cadastrar no
        computador e bater o ponto no tablet precisa continuar valendo.
        """
        webcam = vetor(2)
        tablet = perto(webcam, 0.45, 41)      # mesma pessoa, outra camera
        amostras = [
            perto(webcam, 0.05, 51), perto(webcam, 0.08, 52),
            perto(tablet, 0.05, 53), perto(tablet, 0.08, 54),
        ]
        no_tablet = perto(tablet, 0.12, 61)

        (_, distancia), = self.servico._pontuar(no_tablet, {7: amostras})
        self.assertLess(
            distancia, 0.55,
            "duas capturas da camera de uso deveriam bastar",
        )


class MargemTests(TestCase):
    """
    Aceitar o mais proximo sem olhar o segundo transforma dois parecidos
    num sorteio: quem estiver um milesimo mais perto leva o ponto.
    """

    def test_a_segunda_menor_distancia_e_a_que_conta(self):
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        base = vetor(3)
        # tres amostras: duas coerentes, uma solta
        amostras = [perto(base, 0.10, 71), perto(base, 0.12, 72), vetor(77)]
        alvo = perto(base, 0.11, 73)
        (_, d), = servico._pontuar(alvo, {1: amostras})
        distancias = sorted(servico._distancia(alvo, a) for a in amostras)
        self.assertAlmostEqual(d, distancias[1], places=5)

    def test_com_menos_de_tres_amostras_usa_a_menor(self):
        # Exigir a segunda com duas amostras puniria quem cadastrou o
        # minimo, sem ganho: nao ha maioria a formar.
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        base = vetor(4)
        amostras = [perto(base, 0.10, 81), perto(base, 0.30, 82)]
        alvo = perto(base, 0.11, 83)
        (_, d), = servico._pontuar(alvo, {1: amostras})
        distancias = sorted(servico._distancia(alvo, a) for a in amostras)
        self.assertAlmostEqual(d, distancias[0], places=5)


@override_settings(FACE_MARGEM_MINIMA=0.06, FACE_RECOGNITION_THRESHOLD=0.55)
class LimiarTests(TestCase):
    def test_o_limiar_escolhe_o_lado_do_incomodo(self):
        from django.conf import settings
        self.assertLessEqual(
            settings.FACE_RECOGNITION_THRESHOLD, 0.55,
            "0,60 foi calibrado para a comparacao contra a media; a "
            "comparacao por amostra baixa toda distancia e exige limiar menor",
        )


class OrdemDasVerificacoesTests(TestCase):
    """
    A margem so vale entre candidatos que ja passariam no limiar.

    Conferi-la antes era um erro com consequencia visivel: um rosto
    desconhecido fica longe de todo mundo, e duas distancias grandes
    parecidas entre si — 0,90 e 0,92 — viravam "ambiguo". O totem
    passava a culpar a semelhanca entre cadastrados por um rosto que nao
    era de nenhum deles.
    """

    def test_desconhecido_e_nao_identificado_e_nao_ambiguo(self):
        from apps.facial.services import FaceRecognitionService
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        servico.threshold = 0.55
        servico.margem_minima = 0.06

        # Os dois cadastrados a distancias grandes e proximas entre si:
        # e assim que um rosto de fora se apresenta ao sistema.
        desconhecido = vetor(1000)
        candidatos = {
            1: [perto(desconhecido, 0.88, 201), perto(desconhecido, 0.90, 202)],
            2: [perto(desconhecido, 0.89, 203), perto(desconhecido, 0.91, 204)],
        }
        pontos = servico._pontuar(desconhecido, candidatos)

        self.assertGreater(
            pontos[0][1], servico.threshold,
            "o cenario exige que ninguem passe no limiar",
        )
        # As duas distancias sao grandes e parecidas: sem a ordem certa,
        # isso seria lido como ambiguidade.
        self.assertLess(abs(pontos[0][1] - pontos[1][1]), servico.margem_minima)

    def test_o_codigo_ambiguo_conta_como_nao_identificado(self):
        # Nao pode virar "erro": o equipamento esta funcionando, e a
        # recusa e deliberada. Contar como erro sujaria a metrica que o
        # suporte usa para achar totem com defeito.
        from apps.facial.models import TentativaReconhecimento as T
        from apps.facial import services
        import inspect
        fonte = inspect.getsource(services.FaceRecognitionService._registrar_tentativa)
        self.assertIn('"ambiguo"', fonte)
        self.assertTrue(hasattr(T.Resultado, "NAO_IDENTIFICADO"))


class AuditoriaTests(TestCase):
    """
    O comando que limpa o que ja estava gravado antes da validacao de
    entrada. Precisa achar a amostra contaminada — e precisa se recusar a
    deixar alguem sem cadastro.
    """

    def _colaborador(self, nome, cpf):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.rh.models import Colaborador
        from datetime import date

        plano, _ = Plano.objects.get_or_create(nome="P", slug="p")
        cliente, _ = Cliente.objects.get_or_create(
            cnpj="45997418000153",
            defaults=dict(razao_social="C", plano=plano, email_contato="c@x.com"),
        )
        empresa, _ = Empresa.objects.get_or_create(
            cnpj="45997418000234",
            defaults=dict(cliente=cliente, razao_social="E"),
        )
        return Colaborador.objects.create(
            empresa=empresa, nome_completo=nome, cpf=cpf,
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )

    def _amostra(self, colaborador, v, angulo="frontal"):
        from apps.facial.models import FaceRegistro
        r = FaceRegistro(colaborador=colaborador, angulo=angulo,
                         modelo="ArcFace", detector="mtcnn", qualidade=90)
        r.definir_embedding(np.asarray(v, dtype=np.float32), salvar=False)
        r.save()
        return r

    def test_acha_e_desativa_a_amostra_divergente(self):
        from django.core.management import call_command
        from apps.facial.models import FaceRegistro
        from io import StringIO

        pessoa = self._colaborador("Ana", "52998224725")
        base = vetor(1)
        for i, d in enumerate((0.10, 0.15, 0.20, 0.25)):
            self._amostra(pessoa, perto(base, d, 300 + i))
        ruim = self._amostra(pessoa, vetor(900))

        saida = StringIO()
        call_command("auditar_amostras", "--desativar", stdout=saida)

        ruim.refresh_from_db()
        self.assertFalse(ruim.ativo, "a amostra contaminada deveria sair")
        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=pessoa, ativo=True).count(), 4
        )

    def test_nao_deixa_o_colaborador_sem_cadastro(self):
        from django.core.management import call_command
        from apps.facial.models import FaceRegistro
        from io import StringIO

        pessoa = self._colaborador("Bia", "11144477735")
        # Todas soltas entre si: o cadastro inteiro e que esta errado.
        for s in (901, 902, 903, 904):
            self._amostra(pessoa, vetor(s))

        saida = StringIO()
        call_command("auditar_amostras", "--desativar", stdout=saida)

        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=pessoa, ativo=True).count(), 4,
            "com quase tudo divergente, refazer o cadastro e decisao de quem opera",
        )
        self.assertIn("precisa ser refeito", saida.getvalue())

    def test_sem_o_sinalizador_nada_e_alterado(self):
        from django.core.management import call_command
        from apps.facial.models import FaceRegistro
        from io import StringIO

        pessoa = self._colaborador("Caio", "12345678909")
        base = vetor(2)
        for i, d in enumerate((0.10, 0.15, 0.20)):
            self._amostra(pessoa, perto(base, d, 400 + i))
        ruim = self._amostra(pessoa, vetor(950))

        call_command("auditar_amostras", stdout=StringIO())
        ruim.refresh_from_db()
        self.assertTrue(ruim.ativo)
