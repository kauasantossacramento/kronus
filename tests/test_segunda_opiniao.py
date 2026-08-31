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


class CustoDaConferenciaTests(TestCase):
    """
    A conferencia nao pode perguntar se pode conferir.

    `ProvedorDelegado.disponivel` faz um ping a todos os workers do
    Celery: medido em producao, 2065 ms contra 713 ms da inferencia —
    o triplo do trabalho util, so para decidir se vale trabalhar. Como
    a indisponibilidade ja chega como excecao, o guard so somava espera.

    Este teste existe porque a regressao e invisivel: o resultado
    continua certo, so fica tres vezes mais lento — e quem esta parado
    na frente do totem e quem paga.
    """

    def test_a_conferencia_nao_faz_ping_no_worker(self):
        alvo = np.array([1.0, 0.0], dtype=np.float32)
        galeria = {1: [alvo], 2: [np.array([0.0, 1.0], dtype=np.float32)]}

        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        servico._galeria_de_confirmacao = lambda ids: galeria

        perguntou = []

        class ProvedorEspiao:
            @property
            def disponivel(self):
                perguntou.append(True)
                return True

            def gerar_embedding(self, _):
                return alvo

        import apps.facial.providers as provedores

        original = provedores.obter_provedor_confirmacao
        provedores.obter_provedor_confirmacao = lambda: ProvedorEspiao()
        try:
            servico._segunda_opiniao(b"quadro", 1, galeria)
        finally:
            provedores.obter_provedor_confirmacao = original

        self.assertEqual(
            perguntou, [], "a conferencia perguntou `disponivel` — 2 s por batida"
        )

    def test_sem_worker_a_conferencia_se_abstem_sem_derrubar(self):
        """A excecao ja e a resposta: abstem-se, e o ponto segue."""
        from apps.facial.providers import MotorIndisponivel

        galeria = {1: [np.array([1.0, 0.0], dtype=np.float32)],
                   2: [np.array([0.0, 1.0], dtype=np.float32)]}
        servico = FaceRecognitionService.__new__(FaceRecognitionService)
        servico._galeria_de_confirmacao = lambda ids: galeria

        class ProvedorMorto:
            def gerar_embedding(self, _):
                raise MotorIndisponivel("worker fora do ar")

        import apps.facial.providers as provedores

        original = provedores.obter_provedor_confirmacao
        provedores.obter_provedor_confirmacao = lambda: ProvedorMorto()
        try:
            self.assertIsNone(servico._segunda_opiniao(b"quadro", 1, galeria))
        finally:
            provedores.obter_provedor_confirmacao = original


class MargemEscalonadaTests(TestCase):
    """
    Reconhecimento fraco cobra folga extra.

    Medido na base real: a mesma pessoa fica em media a 0,2254 e pessoas
    diferentes chegam a 0,2630. As faixas se sobrepoem — nao existe
    limiar unico que aceite todo titular e recuse todo sosia.

    Simulado contra a galeria de producao (90 amostras, 17 pessoas):
    87 acertos e **zero** confusoes, contra 87 acertos e uma confusao
    antes — Samira era aceita como Adriana a 0,3667. O custo foi uma
    recusa a mais, que vira nova tentativa.

    Piso e fator sairam da calibracao, nao da intuicao: valores abaixo
    de 0,32 recusavam o caso legitimo de 0,30 com segundo a 0,38, que
    tem teste proprio em `tests/test_falso_positivo.py`.
    """

    def _exigida(self, melhor):
        from django.conf import settings

        if melhor < settings.FACE_PISO_DE_RISCO:
            return None  # abaixo do piso esta regra nao opina
        return 0.10 + (
            melhor - settings.FACE_PISO_DE_RISCO
        ) * settings.FACE_FATOR_DE_RISCO

    def test_abaixo_do_piso_a_regra_nao_opina(self):
        self.assertIsNone(self._exigida(0.20))
        self.assertIsNone(self._exigida(0.30))

    def test_reconhecimento_fraco_exige_muito_mais(self):
        # 0,44 esta na sobreposicao entre titular e sosia. Aceitar sem
        # folga grande e onde nasce a batida pela outra pessoa.
        self.assertAlmostEqual(self._exigida(0.44), 0.10 + 0.20, places=4)

    def test_a_exigencia_cresce_com_a_fraqueza(self):
        anterior = 0
        for d in (0.34, 0.36, 0.40, 0.44):
            atual = self._exigida(d)
            self.assertGreaterEqual(atual, anterior)
            anterior = atual

    def test_o_caso_real_da_samira_seria_recusado(self):
        """
        O par que a simulacao pegou: aceita como outra pessoa a 0,3667,
        com a segunda colocada a 0,45. A folga era 0,0833.

        Passava porque a segunda estava FORA do limiar e a regra antiga
        nem chegava a olhar. Agora olha.
        """
        melhor, segunda = 0.3667, 0.45
        self.assertLess(segunda - melhor, self._exigida(melhor))

    def test_o_caso_legitimo_protegido_continua_passando(self):
        """0,30 com segundo a 0,38 nao pode ser recusado."""
        self.assertIsNone(self._exigida(0.30))
