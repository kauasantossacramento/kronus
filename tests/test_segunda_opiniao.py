"""
Kronus — segunda opiniao na faixa de duvida.

O reconhecimento com um modelo so decide no escuro justamente na faixa
onde moram os dois erros que importam: o acerto dificil, que ele recusa,
e o rosto parecido, que ele aceita. Foi ali que os falsos positivos de
producao cairam — 0,505 a 0,516, com o limiar em 0,52.

A ideia: abaixo de FACE_ACEITE_DIRETO aceita direto, acima do limiar
recusa direto, e no meio pergunta a um segundo modelo. Arquitetura
diferente de proposito — dois modelos parecidos erram junto.

O custo em tempo aparece so na faixa estreita do meio, e nao no caso
comum, que e o que mantem o totem rapido.
"""
import numpy as np
from django.test import TestCase, override_settings

from apps.facial.services import FaceRecognitionService


def vetor(semente, dim=512):
    estado = np.random.RandomState(semente)
    v = estado.normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


class FaixaDeDuvidaTests(TestCase):
    """Onde a segunda opiniao entra, e onde ela nao deve custar nada."""

    def setUp(self):
        self.servico = FaceRecognitionService.__new__(FaceRecognitionService)
        self.servico.threshold = 0.45
        self.servico.margem_minima = 0.10
        self.chamadas = []

        def espiar(frame, escolhido, candidatos):
            self.chamadas.append(escolhido)
            return None

        self.servico._segunda_opiniao = espiar

    def test_a_faixa_fica_entre_o_aceite_direto_e_o_limiar(self):
        from django.conf import settings

        self.assertLess(settings.FACE_ACEITE_DIRETO, settings.FACE_RECOGNITION_THRESHOLD)
        self.assertGreater(settings.FACE_ACEITE_DIRETO, 0)

    def test_o_segundo_modelo_e_de_outra_arquitetura(self):
        # Dois modelos parecidos erram junto; o valor da conferencia
        # esta em o erro nao ser correlacionado.
        from django.conf import settings

        self.assertNotEqual(
            settings.FACE_MODELO_CONFIRMACAO, settings.DEEPFACE_MODEL
        )


class DecisaoTests(TestCase):
    """A conferencia decide, mas nunca por conta propria."""

    def setUp(self):
        self.servico = FaceRecognitionService.__new__(FaceRecognitionService)

    def test_concorda_quando_aponta_a_mesma_pessoa_com_folga(self):
        alvo = vetor(1)
        galeria = {1: [alvo], 2: [vetor(2)]}
        self.servico._galeria_de_confirmacao = lambda ids: galeria

        class Provedor:
            disponivel = True

            def gerar_embedding(self, _):
                return alvo

        with override_settings(FACE_MARGEM_CONFIRMACAO=0.06):
            import apps.facial.providers as provedores

            original = provedores.obter_provedor_confirmacao
            provedores.obter_provedor_confirmacao = lambda: Provedor()
            try:
                self.assertIs(
                    self.servico._segunda_opiniao(b"quadro", 1, galeria), True
                )
            finally:
                provedores.obter_provedor_confirmacao = original

    def test_discorda_quando_aponta_outra_pessoa(self):
        outro = vetor(2)
        galeria = {1: [vetor(1)], 2: [outro]}
        self.servico._galeria_de_confirmacao = lambda ids: galeria

        class Provedor:
            disponivel = True

            def gerar_embedding(self, _):
                return outro

        import apps.facial.providers as provedores

        original = provedores.obter_provedor_confirmacao
        provedores.obter_provedor_confirmacao = lambda: Provedor()
        try:
            # `is False`, e nao `assertFalse`: `None` tambem e falsy, e
            # `None` aqui significaria "nao conferiu" — o oposto de
            # "conferiu e discordou".
            self.assertIs(
                self.servico._segunda_opiniao(b"quadro", 1, galeria), False
            )
        finally:
            provedores.obter_provedor_confirmacao = original

    def test_sem_galeria_do_segundo_modelo_nao_bloqueia(self):
        """
        `None`, e nao `False`. A conferencia e uma camada a mais;
        derrubar o ponto porque ela nao pode rodar trocaria uma melhora
        por uma falha.
        """
        self.servico._galeria_de_confirmacao = lambda ids: {}
        self.assertIsNone(self.servico._segunda_opiniao(b"", 1, {1: []}))

    def test_falha_do_motor_nao_bloqueia(self):
        def explodir(ids):
            raise RuntimeError("motor fora do ar")

        self.servico._galeria_de_confirmacao = explodir
        self.assertIsNone(self.servico._segunda_opiniao(b"", 1, {1: [], 2: []}))

    def test_uma_pessoa_so_dispensa_a_conferencia(self):
        # Sem segundo colocado nao ha o que confirmar por comparacao.
        self.servico._galeria_de_confirmacao = lambda ids: {1: [vetor(1)]}
        self.assertIsNone(self.servico._segunda_opiniao(b"", 1, {1: []}))


class DesfechoRegistradoTests(TestCase):
    """
    O painel precisa dizer o que aconteceu de verdade.

    "Identificado" nao quer dizer ponto batido: o primeiro quadro da
    dupla confirmacao identifica e nao grava nada, uma consulta
    identifica e nao grava nada, e uma batida repetida identifica e e
    recusada. Tres linhas iguais para tres desfechos diferentes foi o
    que gerou a pergunta "estes retornaram sucesso?".
    """

    def test_o_modelo_tem_os_desfechos_que_importam(self):
        from apps.facial.models import TentativaReconhecimento as T

        valores = {v for v, _ in T.Desfecho.choices}
        self.assertEqual(
            valores,
            {"pendente", "aguardando", "ponto", "so_consulta",
             "recusado", "duplicado"},
        )

    def test_a_view_anota_cada_caminho(self):
        # Recusa, consulta, aguardando, duplicado e ponto: cinco saidas,
        # e nenhuma pode ficar sem desfecho.
        # Lido do arquivo: o decorador do DRF embrulha a view, e
        # `getsource` devolveria o embrulho em vez do corpo.
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        fonte = (raiz / "apps/api/views_totem.py").read_text(encoding="utf-8")
        for desfecho in ("RECUSADO", "SO_CONSULTA", "AGUARDANDO",
                         "DUPLICADO", "PONTO"):
            self.assertIn(desfecho, fonte, f"{desfecho} nao e anotado")

    def test_a_tentativa_guarda_o_modelo_que_decidiu(self):
        # Depois de uma troca de modelo, uma distancia sem o nome do
        # modelo nao significa mais a mesma coisa.
        import inspect

        from apps.facial import services

        fonte = inspect.getsource(
            services.FaceRecognitionService._registrar_tentativa
        )
        self.assertIn("modelo=settings.DEEPFACE_MODEL", fonte)
        self.assertIn("confirmacao=", fonte)


class ArquiteturaDaConfirmacaoTests(TestCase):
    """
    A segunda opiniao nao pode carregar modelo no processo web.

    O `ProvedorDelegado` existe porque cada modelo custa ~1,1 GB *por
    processo*: dois workers web com copia propria estouram um servidor
    de 3,9 GB e empurram o Postgres para o swap. A conferencia dobraria
    esse custo se pedisse o DeepFace direto — por isso ela passa pelo
    mesmo seletor, e a inferencia vai para o worker dedicado, que e de
    concorrencia 1 e guarda os dois modelos numa copia so.

    Este teste existe para que a regressao apareca aqui, e nao como
    memoria estourada em producao.
    """

    def test_em_producao_a_confirmacao_e_delegada(self):
        from apps.facial.providers import ProvedorDelegado, obter_provedor_confirmacao

        with override_settings(
            FACE_PROVIDER="delegado", FACE_MODELO_CONFIRMACAO="ArcFace"
        ):
            provedor = obter_provedor_confirmacao()

        self.assertIsInstance(provedor, ProvedorDelegado)
        self.assertEqual(provedor.modelo, "ArcFace")

    def test_o_worker_recebe_qual_modelo_usar(self):
        """
        Sem o modelo no argumento, o worker responderia com o modelo
        principal — e a "segunda opiniao" seria a primeira de novo,
        concordando sempre e nao filtrando nada.
        """
        from apps.facial.providers import ProvedorDelegado

        enviados = {}

        class TarefaFalsa:
            def apply_async(self, args, queue):
                enviados["args"] = args

                class Resultado:
                    def get(self, timeout, propagate):
                        return {"embedding": [1.0, 0.0]}

                return Resultado()

        import apps.facial.tasks as tarefas

        original = tarefas.gerar_embedding_remoto
        tarefas.gerar_embedding_remoto = TarefaFalsa()
        try:
            ProvedorDelegado(modelo="ArcFace").gerar_embedding(b"imagem")
        finally:
            tarefas.gerar_embedding_remoto = original

        self.assertEqual(enviados["args"][1], "ArcFace")

    def test_sem_modelo_de_confirmacao_a_conferencia_se_abstem(self):
        from apps.facial.providers import ProvedorIndisponivel, obter_provedor_confirmacao

        with override_settings(FACE_MODELO_CONFIRMACAO=""):
            self.assertIsInstance(
                obter_provedor_confirmacao(), ProvedorIndisponivel
            )
