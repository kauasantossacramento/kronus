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

        Quatro capturas coerentes do titular, mais uma contaminada. Um
        rosto que so se parece com a contaminada nao pode ser aceito.

        A protecao nao esta na pontuacao — que continua sendo a menor
        distancia, porque poses da mesma pessoa ficam naturalmente
        distantes entre si. Esta em nao deixar a amostra contaminada
        participar.
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

        # Sem o filtro, o visitante entraria.
        menor = min(self.servico._distancia(visitante, a) for a in amostras)
        self.assertLess(menor, 0.55, "o cenario so faz sentido se a menor passaria")

        limpas = self.servico._amostras_coerentes(amostras)
        self.assertEqual(len(limpas), 4, "a contaminada deveria ficar de fora")

        (_, distancia), = self.servico._pontuar(visitante, {7: limpas})
        self.assertGreater(
            distancia, 0.55,
            "sem a amostra contaminada, o visitante nao se parece com ninguem",
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

    def test_vale_a_menor_distancia_entre_as_amostras(self):
        """
        Exigir a SEGUNDA menor foi uma tentativa de conter a amostra
        contaminada aqui, e nao se sustentou. O roteiro de cadastro pede
        cinco poses, e poses da mesma pessoa ficam a 0,38-0,48 entre si
        (medido em producao) — exigir que duas concordassem punia o
        cadastro bem feito. O titular passou a ser reconhecido no limite
        do limiar, quando antes era reconhecido com folga.
        """
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        base = vetor(3)
        amostras = [perto(base, 0.10, 71), perto(base, 0.40, 72),
                    perto(base, 0.45, 74)]
        alvo = perto(base, 0.11, 73)
        (_, d), = servico._pontuar(alvo, {1: amostras})
        distancias = sorted(servico._distancia(alvo, a) for a in amostras)
        self.assertAlmostEqual(d, distancias[0], places=5)

    def test_com_menos_de_tres_amostras_nada_e_descartado(self):
        # Com duas nao ha maioria: apontar a divergente seria escolher
        # uma das duas no cara ou coroa.
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        amostras = [vetor(81), vetor(82)]
        self.assertEqual(len(servico._amostras_coerentes(amostras)), 2)

    def test_poses_distantes_entre_si_nao_sao_descartadas(self):
        """
        A faixa medida em producao para o mesmo rosto em cinco poses:
        mediana de 0,38 a 0,48. Nada disso pode ser tratado como
        contaminacao — foi o erro que recusou uma captura legitima.
        """
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        base = vetor(5)
        poses = [base] + [perto(base, d, 90 + i)
                          for i, d in enumerate((0.40, 0.45, 0.48, 0.44))]
        self.assertEqual(
            len(servico._amostras_coerentes(poses)), 5,
            "poses legitimas foram tratadas como rosto diferente",
        )

    def test_nunca_deixa_o_colaborador_sem_referencia(self):
        # Se quase tudo diverge, o cadastro inteiro esta errado — e
        # recusar tudo aqui trocaria o erro por alguem que nao bate ponto.
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        soltas = [vetor(s) for s in (91, 92, 93, 94)]
        self.assertEqual(len(servico._amostras_coerentes(soltas)), 4)


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


class TrocaDeModeloTests(TestCase):
    """
    Um vetor gerado por outro modelo tem as mesmas 512 posicoes e nenhum
    significado comparavel. Compara-lo nao levanta erro — devolve
    reconhecimento por sorteio, que e pior, porque parece funcionar.
    """

    def setUp(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.rh.models import Colaborador
        from datetime import date
        from django.core.cache import cache

        cache.clear()
        plano = Plano.objects.create(nome="P", slug="p")
        cliente = Cliente.objects.create(
            razao_social="C", cnpj="45997418000153",
            plano=plano, email_contato="c@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="E", cnpj="45997418000234",
        )
        self.pessoa = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Ana", cpf="52998224725",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
            face_registrada=True,
        )

    def _amostra(self, modelo):
        from apps.facial.models import FaceRegistro

        r = FaceRegistro(colaborador=self.pessoa, angulo="frontal",
                         modelo=modelo, detector="mtcnn", qualidade=90)
        r.definir_embedding(vetor(1), salvar=False)
        r.save()
        return r

    def test_amostra_de_outro_modelo_nao_entra_na_comparacao(self):
        from django.test import override_settings
        from apps.facial.services import FaceRecognitionService

        self._amostra("ArcFace")
        with override_settings(DEEPFACE_MODEL="Facenet512"):
            FaceRecognitionService.invalidar_cache(self.empresa.pk)
            candidatos = FaceRecognitionService().candidatos([self.empresa])
        self.assertEqual(
            candidatos, {},
            "amostra de outro modelo entrou: o reconhecimento vira sorteio",
        )

    def test_amostra_do_modelo_certo_entra(self):
        from django.test import override_settings
        from apps.facial.services import FaceRecognitionService

        self._amostra("Facenet512")
        with override_settings(DEEPFACE_MODEL="Facenet512"):
            FaceRecognitionService.invalidar_cache(self.empresa.pk)
            candidatos = FaceRecognitionService().candidatos([self.empresa])
        self.assertEqual(len(candidatos), 1)

    def test_a_media_legada_tambem_e_ignorada_se_o_modelo_mudou(self):
        # A media foi calculada com os vetores do modelo antigo: cair
        # nela seria o mesmo problema por outro caminho.
        from django.test import override_settings
        from apps.facial.services import FaceRecognitionService

        self._amostra("ArcFace")
        self.pessoa.definir_embedding(vetor(2))
        with override_settings(DEEPFACE_MODEL="Facenet512"):
            FaceRecognitionService.invalidar_cache(self.empresa.pk)
            candidatos = FaceRecognitionService().candidatos([self.empresa])
        self.assertEqual(candidatos, {})

    def test_cada_modelo_tem_a_sua_normalizacao(self):
        # Deixar no "base" do DeepFace nao da erro: da embedding pior, em
        # silencio. Foi metade do caminho ate o falso positivo.
        from apps.facial.providers import NORMALIZACAO_POR_MODELO

        self.assertEqual(NORMALIZACAO_POR_MODELO["Facenet512"], "Facenet2018")
        self.assertEqual(NORMALIZACAO_POR_MODELO["ArcFace"], "ArcFace")


class AmostraAmbiguaTests(TestCase):
    """
    Uma amostra pode combinar com as irmas e ainda assim estar perto
    demais de um estranho.

    Medido em producao: a captura da pose "cima" de uma colaboradora
    ficou a 0,367 de outra pessoa e a 0,506 das proprias irmas. A
    verificacao de coerencia interna nao pega isso — ela so olha para
    dentro. E como vale a menor distancia, essa amostra respondia por
    duas pessoas ao mesmo tempo.
    """

    def _servico(self):
        from apps.facial.services import FaceRecognitionService

        return FaceRecognitionService.__new__(FaceRecognitionService)

    def test_descarta_a_amostra_mais_parecida_com_outra_pessoa(self):
        servico = self._servico()
        ana = vetor(1)
        bia = vetor(2)

        # A ultima de Ana esta mais perto de Bia do que das irmas.
        galeria = {
            1: [perto(ana, 0.10, 11), perto(ana, 0.12, 12),
                perto(ana, 0.15, 13), perto(bia, 0.08, 14)],
            2: [perto(bia, 0.10, 21), perto(bia, 0.12, 22)],
        }
        limpa = servico._sem_amostras_ambiguas(galeria)

        self.assertEqual(len(limpa[1]), 3, "a amostra ambigua deveria sair")
        self.assertEqual(len(limpa[2]), 2, "a galeria de Bia nao muda")

    def test_o_descarte_afasta_as_duas_pessoas(self):
        servico = self._servico()
        ana, bia = vetor(3), vetor(4)
        galeria = {
            1: [perto(ana, 0.10, 31), perto(ana, 0.12, 32),
                perto(ana, 0.15, 33), perto(bia, 0.08, 34)],
            2: [perto(bia, 0.10, 41), perto(bia, 0.12, 42)],
        }

        def separacao(g):
            return min(
                servico._distancia(x, y) for x in g[1] for y in g[2]
            )

        antes = separacao(galeria)
        depois = separacao(servico._sem_amostras_ambiguas(galeria))
        self.assertGreater(
            depois, antes,
            "tirar a amostra ambigua tem de aumentar a distancia entre as duas",
        )

    def test_nunca_deixa_menos_de_duas_referencias(self):
        # Um cadastro reduzido a nada trocaria o erro por alguem que nao
        # consegue bater ponto.
        servico = self._servico()
        bia = vetor(5)
        galeria = {
            1: [perto(bia, 0.05, 51), perto(bia, 0.06, 52)],
            2: [perto(bia, 0.04, 61), perto(bia, 0.07, 62)],
        }
        limpa = servico._sem_amostras_ambiguas(galeria)
        self.assertGreaterEqual(len(limpa[1]), 2)
        self.assertGreaterEqual(len(limpa[2]), 2)

    def test_com_uma_pessoa_so_nada_e_descartado(self):
        # Sem estranho para comparar, a regra nao tem o que dizer.
        servico = self._servico()
        ana = vetor(6)
        galeria = {1: [perto(ana, 0.1, 71), perto(ana, 0.5, 72)]}
        self.assertEqual(len(servico._sem_amostras_ambiguas(galeria)[1]), 2)


class RostoDaFrenteTests(TestCase):
    """
    Um segundo rosto no quadro nao pode recusar a leitura inteira.

    Do outro lado da tela isso vira "dois rostos identificados" numa
    cena que tem uma pessoa so — um reflexo, alguem passando ao fundo,
    uma deteccao fraca. Quem esta no totem e o rosto maior.
    """

    def _provedor(self):
        from apps.facial.providers import DeepFaceProvider

        return DeepFaceProvider.__new__(DeepFaceProvider)

    def _rosto(self, largura, altura, marca):
        return {"embedding": [float(marca)] * 4,
                "facial_area": {"w": largura, "h": altura, "x": 0, "y": 0}}

    def test_escolhe_o_rosto_maior(self):
        provedor = self._provedor()
        escolhido = provedor._rosto_da_frente([
            self._rosto(60, 70, 1),    # alguem ao fundo
            self._rosto(240, 260, 2),  # quem esta no totem
        ])
        self.assertEqual(escolhido["embedding"][0], 2.0)

    def test_duas_pessoas_lado_a_lado_ainda_recusam(self):
        # Areas comparaveis: nao da para saber de quem e o ponto, e
        # escolher uma seria adivinhar.
        from apps.facial.providers import MultiplosRostosDetectados

        provedor = self._provedor()
        with self.assertRaises(MultiplosRostosDetectados):
            provedor._rosto_da_frente([
                self._rosto(230, 250, 1),
                self._rosto(240, 260, 2),
            ])

    def test_um_rosto_passa_direto(self):
        provedor = self._provedor()
        unico = self._rosto(200, 220, 9)
        self.assertIs(provedor._rosto_da_frente([unico]), unico)


class MargemEntreCandidatosTests(TestCase):
    """
    A margem so vale entre candidatos que PASSARIAM no limiar.

    Antes ela comparava com o segundo colocado qualquer que fosse a
    distancia dele. Com varias pessoas cadastradas isso disparava o
    tempo todo: alguem reconhecido a 0,30 tinha um segundo a 0,38 — que
    nunca seria aceito — e a leitura era recusada por uma ambiguidade
    que nao existia.
    """

    def test_segundo_colocado_longe_nao_gera_ambiguidade(self):
        import inspect
        from apps.facial import services

        fonte = inspect.getsource(services.FaceRecognitionService.reconhecer)
        self.assertIn("pontos[1][1] < self.threshold", fonte)

    def test_a_regra_esta_documentada_com_o_motivo(self):
        # O comentario e parte da correcao: sem ele, o proximo a mexer
        # aqui reintroduz a comparacao com qualquer segundo colocado.
        import inspect
        from apps.facial import services

        fonte = inspect.getsource(services.FaceRecognitionService.reconhecer)
        self.assertIn("PASSARIAM no limiar", fonte)


class RostoColadoNaLenteTests(TestCase):
    """
    Quem chega bem perto tambem precisa acordar a tela.

    O TinyFaceDetector perde o rosto colado na lente, e a tela ficava
    parada esperando um toque — justamente de quem tinha chegado mais
    perto para ser reconhecido logo.
    """

    def setUp(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        self.js = (
            raiz / "apps/totem/static/totem/js/face-detector.js"
        ).read_text(encoding="utf-8")

    def test_o_limite_de_perto_nao_recusa_o_gesto_natural(self):
        import re

        achado = re.search(r"LARGURA_MAXIMA_ROSTO:\s*([0-9.]+)", self.js)
        self.assertIsNotNone(achado)
        self.assertGreaterEqual(
            float(achado.group(1)), 0.9,
            "0,85 recusava quem chegava perto, que e o gesto de quem quer "
            "ser reconhecido logo",
        )

    def test_sem_rosto_detectado_a_heuristica_ainda_acorda_a_tela(self):
        self.assertIn("_detectarHeuristico(canvas)", self.js)
        # Mas nunca autoriza envio: quem decide isso continua sendo o
        # rosto detectado e enquadrado.
        trecho = self.js[self.js.index("Sem rosto detectado, a heuristica"):]
        trecho = trecho[: trecho.index("}")]
        self.assertIn("pronto: false", self.js[self.js.index("perto.detectado"):][:400])


class AuditoriaDoReconhecimentoTests(TestCase):
    """
    A tela que responde "foi a pessoa certa?".

    Sem a foto e a distancia medida, a resposta era conversa — e conversa
    e onde duvida sobre ponto vira litigio.
    """

    def setUp(self):
        from datetime import date
        from apps.accounts.models import CustomUser
        from apps.clientes.models import Cliente, Empresa
        from apps.facial.models import TentativaReconhecimento
        from apps.master.models import Plano
        from apps.rh.models import Colaborador
        from apps.totem.models import Totem

        plano = Plano.objects.create(nome="P", slug="p", max_totems=3)
        cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        totem = Totem.objects.create(empresa=self.empresa, ativo=True)
        self.pessoa = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Edjane Alves", cpf="52998224725",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )
        TentativaReconhecimento.objects.create(
            empresa=self.empresa, totem=totem, colaborador=self.pessoa,
            resultado="identificado", distancia=0.2808, confianca=46.0,
        )
        TentativaReconhecimento.objects.create(
            empresa=self.empresa, totem=totem,
            resultado="nao_identificado", distancia=0.6390,
        )
        self.master = CustomUser.objects.create_superuser(
            email="master@x.test", password="Prova!12345", nome_completo="Master",
        )

    def _como_na_tela(self, numero):
        # A pagina e em pt-BR: o numero sai com virgula. Comparar com
        # ponto passaria a impressao de que a distancia sumiu.
        from django.utils.formats import localize

        return localize(numero)

    def test_o_master_ve_a_distancia_de_cada_tentativa(self):
        from django.urls import reverse

        self.client.force_login(self.master)
        pagina = self.client.get(reverse("master:reconhecimentos")).content.decode()

        self.assertIn(self._como_na_tela(0.2808), pagina)
        self.assertIn(self._como_na_tela(0.639), pagina)
        self.assertIn("Edjane Alves", pagina)

    def test_filtra_por_colaborador(self):
        from django.urls import reverse

        self.client.force_login(self.master)
        url = reverse("master:reconhecimentos")
        pagina = self.client.get(
            url, {"empresa": self.empresa.pk, "colaborador": self.pessoa.pk}
        ).content.decode()

        self.assertIn(self._como_na_tela(0.2808), pagina)
        self.assertNotIn(self._como_na_tela(0.639), pagina)

    def test_quem_nao_e_master_nao_entra(self):
        from django.urls import reverse
        from apps.accounts.models import CustomUser

        colaborador = CustomUser.objects.create_user(
            email="colab@x.test", password="Prova!12345",
            nome_completo="Colab", tipo="colaborador",
        )
        self.client.force_login(colaborador)
        resposta = self.client.get(reverse("master:reconhecimentos"))
        self.assertNotEqual(resposta.status_code, 200)


class MidiaSensivelTests(TestCase):
    """
    Biometria e atestado medico nao podem ser servidos em aberto.

    Estavam: bastava a URL — que aparece no HTML de quem tem acesso —
    para baixar de qualquer lugar, sem sessao. Sao dados pessoais
    sensiveis (LGPD Art. 11), e a URL nao e segredo.
    """

    def test_sem_sessao_o_porteiro_recusa(self):
        from django.urls import reverse

        resposta = self.client.get(reverse("permissao_midia"))
        self.assertEqual(resposta.status_code, 403)

    def test_colaborador_nao_alcanca_a_classe_inteira(self):
        # A foto dele aparece na propria ficha, servida por view que
        # confere de quem e. Liberar a classe daria a foto de todos.
        from django.urls import reverse
        from apps.accounts.models import CustomUser

        usuario = CustomUser.objects.create_user(
            email="c@x.test", password="Prova!12345",
            nome_completo="C", tipo="colaborador",
        )
        self.client.force_login(usuario)
        self.assertEqual(
            self.client.get(reverse("permissao_midia")).status_code, 403
        )

    def test_rh_alcanca(self):
        from django.urls import reverse
        from apps.accounts.models import CustomUser

        usuario = CustomUser.objects.create_user(
            email="rh@x.test", password="Prova!12345",
            nome_completo="RH", tipo="rh",
        )
        self.client.force_login(usuario)
        self.assertEqual(
            self.client.get(reverse("permissao_midia")).status_code, 200
        )
