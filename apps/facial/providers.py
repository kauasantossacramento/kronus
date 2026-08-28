"""
Kronus — provedores de reconhecimento facial.

A Seção 2.1 do plano define **DeepFace com backend ArcFace** e detecção
por **RetinaFace**. Essa stack pesa centenas de megabytes e depende de
TensorFlow/ONNX — o que a torna inviável em algumas máquinas de
desenvolvimento e em CI.

A solução é uma interface fina: todo o resto do sistema (endpoints do
totem, cadastro facial, tarefas assíncronas, testes) conversa apenas com
`ProvedorFacial`. Em produção o `DeepFaceProvider` faz o trabalho real;
onde a stack não existe, o `ProvedorIndisponivel` responde com um erro
explícito, e o `ProvedorDeterministico` permite exercitar toda a lógica
de negócio em testes sem carregar um modelo de 120 MB.

Trocar de motor (InsightFace, um serviço externo, uma GPU dedicada) passa
a ser escrever uma classe nova — nenhuma view muda.
"""
import hashlib
import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path  # noqa: F401  (usado nas anotações de tipo)

import numpy as np
from django.conf import settings

logger = logging.getLogger("kronus.facial")

#: Dimensão do vetor ArcFace (Seção 4.2 do plano).
DIMENSOES_ARCFACE = 512


class ErroReconhecimento(Exception):
    """Falha ao processar uma imagem facial."""

    def __init__(self, mensagem: str, codigo: str = "erro"):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


class NenhumRostoDetectado(ErroReconhecimento):
    def __init__(self, mensagem="Nenhum rosto detectado na imagem."):
        super().__init__(mensagem, codigo="sem_rosto")


class MultiplosRostosDetectados(ErroReconhecimento):
    def __init__(self, mensagem="Mais de um rosto na imagem."):
        super().__init__(mensagem, codigo="multiplos_rostos")


class MotorIndisponivel(ErroReconhecimento):
    def __init__(self, mensagem="Motor de reconhecimento facial indisponível."):
        super().__init__(mensagem, codigo="motor_indisponivel")


# ══════════════════════════════════════════════════════════════
# Interface
# ══════════════════════════════════════════════════════════════
class ProvedorFacial(ABC):
    """Contrato mínimo que qualquer motor de reconhecimento deve cumprir."""

    nome = "abstrato"
    dimensoes = DIMENSOES_ARCFACE

    @abstractmethod
    def gerar_embedding(self, imagem_bytes: bytes) -> np.ndarray:
        """
        Extrai o vetor facial de uma imagem.

        Levanta `NenhumRostoDetectado` ou `MultiplosRostosDetectados`
        quando o enquadramento inviabiliza o cadastro.
        """

    @property
    def disponivel(self) -> bool:
        return True

    # -- comparação (comum a todos os provedores) --------------
    @staticmethod
    def distancia_cosseno(a: np.ndarray, b: np.ndarray) -> float:
        """
        Distância cosseno entre dois embeddings: 0 = idênticos.

        É a métrica que o plano adota para o ArcFace (Seção 8.2), com
        threshold de 0,68.
        """
        a = np.asarray(a, dtype=np.float32)
        b = np.asarray(b, dtype=np.float32)
        norma = np.linalg.norm(a) * np.linalg.norm(b)
        if norma == 0:
            return 1.0
        return float(1.0 - np.dot(a, b) / norma)

    @classmethod
    def confianca(cls, distancia: float, threshold: float) -> float:
        """
        Converte a distância em um percentual legível para a interface.

        Na distância zero a confiança é 100%; no threshold, 0%. Serve
        para exibição e auditoria — a decisão de match continua sendo
        a comparação crua com o threshold.
        """
        if threshold <= 0:
            return 0.0
        return round(max(0.0, min(1.0, 1.0 - distancia / threshold)) * 100, 2)

    @staticmethod
    def media_normalizada(embeddings: list) -> np.ndarray:
        """
        Embedding médio de várias amostras, normalizado.

        O cadastro captura de 3 a 5 ângulos (Seção 8.2); a média dos
        vetores é mais robusta a variação de pose e iluminação do que
        qualquer amostra isolada.
        """
        matriz = np.asarray(embeddings, dtype=np.float32)
        media = matriz.mean(axis=0)
        norma = np.linalg.norm(media)
        return (media / norma).astype(np.float32) if norma else media.astype(np.float32)


# ══════════════════════════════════════════════════════════════
# Produção — DeepFace / ArcFace
# ══════════════════════════════════════════════════════════════
class DeepFaceProvider(ProvedorFacial):
    """
    Motor de produção: DeepFace com ArcFace e detector RetinaFace.

    O import do DeepFace é tardio de propósito — ele carrega TensorFlow,
    o que leva segundos e ocupa memória. Só acontece na primeira chamada
    real, não na importação do módulo.
    """

    nome = "deepface"

    def __init__(self, modelo: str = None, detector: str = None):
        self.modelo = modelo or settings.DEEPFACE_MODEL
        self.detector = detector or settings.DEEPFACE_DETECTOR

    @property
    def disponivel(self) -> bool:
        """
        A biblioteca importa **e** os pesos do modelo estão em disco.

        Checar só o import seria enganoso: o DeepFace instala sem os
        pesos e tenta baixá-los na primeira chamada. Em servidor sem
        saída para a internet — situação comum em produção — isso
        transformaria a primeira batida do dia em erro. Melhor recusar
        antes, com instrução de como resolver.
        """
        return _deepface_importavel() and self.pesos_presentes()

    def pesos_presentes(self) -> bool:
        return caminho_pesos(self.modelo).exists()

    def verificar_saude(self) -> dict:
        """
        Diagnóstico para o deploy: o que está pronto e o que falta.

        Usado por `manage.py facial_check`.
        """
        pesos = caminho_pesos(self.modelo)
        return {
            "provedor": self.nome,
            "modelo": self.modelo,
            "detector": self.detector,
            "biblioteca_importavel": _deepface_importavel(),
            "pesos_esperados_em": str(pesos),
            "pesos_presentes": pesos.exists(),
            "pesos_bytes": pesos.stat().st_size if pesos.exists() else 0,
            "disponivel": self.disponivel,
        }

    def gerar_embedding(self, imagem_bytes: bytes) -> np.ndarray:
        import cv2

        deepface = _carregar_deepface()
        if deepface is None:
            raise MotorIndisponivel(
                "DeepFace não está instalado neste ambiente. "
                "Execute: pip install -r requirements.txt"
            )
        if not self.pesos_presentes():
            raise MotorIndisponivel(
                f"Pesos do modelo {self.modelo} ausentes em "
                f"{caminho_pesos(self.modelo)}. Rode `manage.py facial_check "
                "--baixar` em uma máquina com acesso à internet ou copie o "
                "arquivo manualmente."
            )

        matriz = cv2.imdecode(
            np.frombuffer(imagem_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if matriz is None:
            raise ErroReconhecimento("Imagem inválida ou corrompida.", codigo="imagem_invalida")

        try:
            resultados = deepface.represent(
                img_path=matriz,
                model_name=self.modelo,
                detector_backend=self.detector,
                enforce_detection=True,
                align=True,
            )
        except ValueError as erro:
            # O DeepFace sinaliza ausência de rosto com ValueError.
            raise NenhumRostoDetectado(str(erro)) from erro
        except Exception as erro:  # falha do motor, não do enquadramento
            logger.exception("Falha no DeepFace")
            raise ErroReconhecimento(
                f"Falha ao processar a imagem: {erro}", codigo="erro_motor"
            ) from erro

        if not resultados:
            raise NenhumRostoDetectado()
        if len(resultados) > 1:
            raise MultiplosRostosDetectados(
                f"{len(resultados)} rostos detectados. Enquadre apenas uma pessoa."
            )

        vetor = np.asarray(resultados[0]["embedding"], dtype=np.float32)
        norma = np.linalg.norm(vetor)
        return (vetor / norma).astype(np.float32) if norma else vetor


#: Nome do arquivo de pesos por modelo do DeepFace.
ARQUIVOS_DE_PESO = {
    "ArcFace": "arcface_weights.h5",
    "Facenet": "facenet_weights.h5",
    "Facenet512": "facenet512_weights.h5",
    "VGG-Face": "vgg_face_weights.h5",
    "SFace": "face_recognition_sface_2021dec.onnx",
}


def diretorio_pesos() -> "Path":
    """Diretório onde o DeepFace guarda os modelos baixados."""
    from pathlib import Path

    base = os.environ.get("DEEPFACE_HOME") or os.path.expanduser("~")
    return Path(base) / ".deepface" / "weights"


def caminho_pesos(modelo: str) -> "Path":
    arquivo = ARQUIVOS_DE_PESO.get(modelo, f"{modelo.lower()}_weights.h5")
    return diretorio_pesos() / arquivo


@lru_cache(maxsize=1)
def _deepface_importavel() -> bool:
    try:
        import cv2  # noqa: F401
        from deepface import DeepFace  # noqa: F401

        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _carregar_deepface():
    """Importa o DeepFace uma única vez por processo."""
    try:
        from deepface import DeepFace

        return DeepFace
    except Exception:
        logger.warning(
            "DeepFace indisponível neste ambiente — o reconhecimento facial "
            "responderá com erro explícito até a stack ser instalada."
        )
        return None


# ══════════════════════════════════════════════════════════════
# Desenvolvimento e testes
# ══════════════════════════════════════════════════════════════
class ProvedorDeterministico(ProvedorFacial):
    """
    Motor de teste: deriva o embedding do **conteúdo** da imagem.

    A mesma imagem sempre produz o mesmo vetor, e imagens diferentes
    produzem vetores distantes. Isso permite testar todo o fluxo de
    cadastro, comparação, threshold e registro de ponto sem depender de
    modelo treinado — o que mantém a suíte rápida e determinística.

    **Nunca deve ser usado em produção**: não reconhece rostos, apenas
    compara bytes.
    """

    nome = "deterministico"

    #: Marcadores que simulam falhas de enquadramento nos testes.
    MARCA_SEM_ROSTO = b"__SEM_ROSTO__"
    MARCA_MULTIPLOS = b"__MULTIPLOS_ROSTOS__"

    def gerar_embedding(self, imagem_bytes: bytes) -> np.ndarray:
        if not imagem_bytes:
            raise ErroReconhecimento("Imagem vazia.", codigo="imagem_invalida")
        if self.MARCA_SEM_ROSTO in imagem_bytes:
            raise NenhumRostoDetectado()
        if self.MARCA_MULTIPLOS in imagem_bytes:
            raise MultiplosRostosDetectados()

        # SHA-512 dá 64 bytes; repetimos até preencher as 512 dimensões
        # e normalizamos para que a distância cosseno se comporte.
        semente = hashlib.sha512(imagem_bytes).digest()
        gerador = np.random.default_rng(int.from_bytes(semente[:8], "big"))
        vetor = gerador.standard_normal(self.dimensoes).astype(np.float32)
        return (vetor / np.linalg.norm(vetor)).astype(np.float32)


class ProvedorIndisponivel(ProvedorFacial):
    """Recusa toda operação com uma mensagem acionável."""

    nome = "indisponivel"

    @property
    def disponivel(self) -> bool:
        return False

    def gerar_embedding(self, imagem_bytes: bytes) -> np.ndarray:
        raise MotorIndisponivel(
            "O reconhecimento facial não está habilitado neste ambiente. "
            "Instale a stack de visão computacional com "
            "`pip install -r requirements.txt`."
        )


# ══════════════════════════════════════════════════════════════
# Seleção do provedor
# ══════════════════════════════════════════════════════════════
def obter_provedor(nome: str = None) -> ProvedorFacial:
    """
    Devolve o provedor configurado.

    `settings.FACE_PROVIDER` aceita:
        "auto"           DeepFace se disponível, senão indisponível (padrão)
        "deepface"       força o motor de produção
        "deterministico" motor de teste
        "indisponivel"   desliga o reconhecimento
    """
    nome = nome or getattr(settings, "FACE_PROVIDER", "auto")

    if nome == "deterministico":
        return ProvedorDeterministico()
    if nome == "indisponivel":
        return ProvedorIndisponivel()
    if nome == "deepface":
        return DeepFaceProvider()

    # auto
    provedor = DeepFaceProvider()
    return provedor if provedor.disponivel else ProvedorIndisponivel()
