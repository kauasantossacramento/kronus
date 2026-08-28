"""
Kronus — pré-processamento das imagens faciais.

O totem envia frames JPEG em base64 (Seção 6.5.1). Antes de chegar ao
motor de reconhecimento a imagem passa por aqui: decodificação segura,
limite de tamanho, redimensionamento e um score de qualidade que evita
gravar amostras ruins no cadastro.

Tudo funciona sem OpenCV; quando ele está disponível, o score de
qualidade fica mais preciso (nitidez por variância do laplaciano).
"""
import base64
import binascii
import io
import logging

from django.core.files.base import ContentFile

logger = logging.getLogger("kronus.facial")

#: Frame do totem comprimido chega com ~50 KB (Seção 6.5.2, item 5).
#: 4 MB cobre com folga um upload de webcam em alta resolução.
TAMANHO_MAXIMO_BYTES = 4 * 1024 * 1024

#: Lado maior após o redimensionamento enviado ao motor.
LADO_MAXIMO = 640

#: Abaixo disso a imagem não tem informação suficiente para um embedding.
LADO_MINIMO = 120


class ImagemInvalida(ValueError):
    """A imagem recebida não pode ser processada."""

    def __init__(self, mensagem: str, codigo: str = "imagem_invalida"):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


# ══════════════════════════════════════════════════════════════
# Entrada
# ══════════════════════════════════════════════════════════════
def decodificar_base64(dados: str) -> bytes:
    """
    Converte o payload do totem em bytes.

    Aceita tanto o base64 puro quanto o data URI completo
    (`data:image/jpeg;base64,...`) que o `canvas.toDataURL()` produz.
    """
    if not dados:
        raise ImagemInvalida("Nenhuma imagem recebida.", codigo="imagem_ausente")

    if isinstance(dados, bytes):
        return dados

    conteudo = dados.strip()
    if conteudo.startswith("data:"):
        _, _, conteudo = conteudo.partition(",")

    try:
        imagem = base64.b64decode(conteudo, validate=True)
    except (binascii.Error, ValueError) as erro:
        raise ImagemInvalida("Imagem em base64 inválida.") from erro

    if not imagem:
        raise ImagemInvalida("Imagem vazia.", codigo="imagem_ausente")
    if len(imagem) > TAMANHO_MAXIMO_BYTES:
        raise ImagemInvalida(
            f"Imagem acima do limite de {TAMANHO_MAXIMO_BYTES // (1024 * 1024)} MB.",
            codigo="imagem_grande",
        )
    return imagem


def validar_dimensoes(imagem_bytes: bytes) -> tuple[int, int]:
    """Confere que a imagem abre e tem tamanho mínimo utilizável."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(imagem_bytes)) as imagem:
            largura, altura = imagem.size
    except UnidentifiedImageError as erro:
        raise ImagemInvalida("Formato de imagem não reconhecido.") from erro
    except Exception as erro:
        raise ImagemInvalida("Não foi possível ler a imagem.") from erro

    if min(largura, altura) < LADO_MINIMO:
        raise ImagemInvalida(
            f"Imagem pequena demais ({largura}x{altura}). "
            f"O lado menor precisa ter ao menos {LADO_MINIMO} px.",
            codigo="imagem_pequena",
        )
    return largura, altura


def normalizar(imagem_bytes: bytes, lado_maximo: int = LADO_MAXIMO) -> bytes:
    """
    Redimensiona e reencoda como JPEG.

    Uniformizar a entrada antes do motor reduz o custo do reconhecimento
    e elimina surpresas com PNG com transparência ou EXIF rotacionado.
    """
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(imagem_bytes)) as imagem:
        # `exif_transpose` corrige fotos de celular deitadas.
        imagem = ImageOps.exif_transpose(imagem)
        if imagem.mode != "RGB":
            imagem = imagem.convert("RGB")
        if max(imagem.size) > lado_maximo:
            imagem.thumbnail((lado_maximo, lado_maximo), Image.LANCZOS)

        saida = io.BytesIO()
        imagem.save(saida, format="JPEG", quality=85, optimize=True)
        return saida.getvalue()


def preparar(dados) -> bytes:
    """Pipeline completo: decodifica, valida e normaliza."""
    imagem = decodificar_base64(dados) if isinstance(dados, str) else dados
    if len(imagem) > TAMANHO_MAXIMO_BYTES:
        raise ImagemInvalida("Imagem acima do limite de tamanho.", codigo="imagem_grande")
    validar_dimensoes(imagem)
    return normalizar(imagem)


# ══════════════════════════════════════════════════════════════
# Qualidade da amostra
# ══════════════════════════════════════════════════════════════
def calcular_qualidade(imagem_bytes: bytes) -> float:
    """
    Score de 0 a 100 combinando nitidez, brilho e contraste.

    Serve para recusar amostras ruins **no cadastro**, onde há tempo de
    pedir uma nova foto. No reconhecimento do totem o score é apenas
    registrado — bloquear ali penalizaria o colaborador por uma condição
    de luz que ele não controla.
    """
    try:
        nitidez = _nitidez(imagem_bytes)
        brilho, contraste = _brilho_e_contraste(imagem_bytes)
    except Exception:
        logger.debug("Não foi possível calcular a qualidade da amostra", exc_info=True)
        return 0.0

    # Nitidez: variância do laplaciano acima de ~150 já é uma foto boa.
    score_nitidez = min(nitidez / 150.0, 1.0)
    # Brilho ideal ao redor de 128; penaliza sub e superexposição.
    score_brilho = max(0.0, 1.0 - abs(brilho - 128) / 128.0)
    # Contraste: desvio padrão acima de ~50 indica boa separação.
    score_contraste = min(contraste / 50.0, 1.0)

    total = 0.5 * score_nitidez + 0.25 * score_brilho + 0.25 * score_contraste
    return round(total * 100, 2)


def _nitidez(imagem_bytes: bytes) -> float:
    """Variância do laplaciano — quanto maior, mais nítida a imagem."""
    try:
        import cv2
        import numpy as np

        matriz = cv2.imdecode(
            np.frombuffer(imagem_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
        )
        if matriz is None:
            return 0.0
        return float(cv2.Laplacian(matriz, cv2.CV_64F).var())
    except ImportError:
        # Sem OpenCV, aproximamos pela variância do gradiente com Pillow.
        return _nitidez_pillow(imagem_bytes)


def _nitidez_pillow(imagem_bytes: bytes) -> float:
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(io.BytesIO(imagem_bytes)) as imagem:
        cinza = imagem.convert("L")
        bordas = cinza.filter(ImageFilter.FIND_EDGES)
        return float(ImageStat.Stat(bordas).stddev[0] ** 2)


def _brilho_e_contraste(imagem_bytes: bytes) -> tuple[float, float]:
    from PIL import Image, ImageStat

    with Image.open(io.BytesIO(imagem_bytes)) as imagem:
        estatisticas = ImageStat.Stat(imagem.convert("L"))
        return float(estatisticas.mean[0]), float(estatisticas.stddev[0])


def qualidade_aceitavel(score: float, minimo: float = 25.0) -> bool:
    """
    Limiar de aceite no cadastro.

    Deliberadamente permissivo: webcams de escritório produzem imagens
    medianas, e recusar demais tornaria o cadastro impraticável. O papel
    do score é barrar foto borrada ou no escuro, não exigir estúdio.
    """
    return score >= minimo


# ══════════════════════════════════════════════════════════════
# Persistência
# ══════════════════════════════════════════════════════════════
def como_arquivo(imagem_bytes: bytes, nome: str) -> ContentFile:
    """Empacota os bytes para gravar em um ImageField."""
    return ContentFile(imagem_bytes, name=nome)
