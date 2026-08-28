"""
Kronus — etiqueta de patrimonio do totem.

Imagem retangular para imprimir e colar no equipamento. Responde a tres
perguntas de quem chega perto dele:

  · de quem e este aparelho          -> KS TEC, com contato
  · qual e o numero de patrimonio    -> KST-AAAA-NNNN
  · isto e mesmo um totem legitimo   -> QR Code para a pagina publica

O QR aponta para a pagina de autenticidade, **nao** para o totem em si.
A etiqueta fica visivel numa recepcao: quem a fotografa nao pode sair
com a credencial que abre o registro de ponto.
"""
import io

from PIL import Image, ImageDraw, ImageFont

# Proporcao de etiqueta adesiva comum (90 x 50 mm). Em 300 dpi.
LARGURA = 1063
ALTURA = 591
SUPER = 2  # desenha em dobro e reduz, para o texto nao sair serrilhado

AZUL = (30, 58, 95)
OURO = (212, 160, 23)
BRANCO = (255, 255, 255)
CINZA = (148, 163, 184)


def _fonte(tamanho: int, negrito: bool = False):
    """
    Fonte do sistema, com reserva.

    A etiqueta e impressa uma vez e colada por anos; se a fonte preferida
    nao existir na maquina que gerou, cair na bitmap padrao e melhor do
    que nao gerar etiqueta nenhuma.
    """
    candidatas = (
        ["arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial_Bold.ttf"]
        if negrito
        else ["arial.ttf", "DejaVuSans.ttf", "Arial.ttf"]
    )
    for nome in candidatas:
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def _qrcode(dados: str, lado: int) -> Image.Image:
    import qrcode

    codigo = qrcode.QRCode(
        version=None,
        # Alta correcao de erro: a etiqueta vai para um equipamento que
        # acumula poeira e risco. Um QR que so le limpo e um QR que para
        # de funcionar no segundo mes.
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    codigo.add_data(dados)
    codigo.make(fit=True)
    img = codigo.make_image(fill_color=(15, 23, 42), back_color=BRANCO)
    return img.convert("RGB").resize((lado, lado), Image.NEAREST)


def gerar(totem, url_base: str = "https://kronus.online") -> bytes:
    """
    Devolve o PNG da etiqueta do totem.

    `url_base` entra por parametro para que a etiqueta gerada em
    homologacao nao aponte para producao.
    """
    largura, altura = LARGURA * SUPER, ALTURA * SUPER
    img = Image.new("RGB", (largura, altura), BRANCO)
    d = ImageDraw.Draw(img)

    margem = 34 * SUPER

    # Faixa superior: a quem pertence o equipamento.
    faixa = 132 * SUPER
    d.rectangle([0, 0, largura, faixa], fill=AZUL)
    d.text((margem, 30 * SUPER), "KS TEC", font=_fonte(52 * SUPER, True), fill=BRANCO)
    d.text((margem, 88 * SUPER), "PROPRIEDADE DA KS TEC — NÃO REMOVER",
           font=_fonte(22 * SUPER), fill=OURO)

    # Patrimonio, em destaque: e o que alguem anota ao telefone.
    topo = faixa + 34 * SUPER
    d.text((margem, topo), "PATRIMÔNIO", font=_fonte(20 * SUPER), fill=CINZA)
    d.text((margem, topo + 26 * SUPER), totem.identificador,
           font=_fonte(56 * SUPER, True), fill=AZUL)

    d.text((margem, topo + 108 * SUPER), "CÓDIGO DE VERIFICAÇÃO",
           font=_fonte(20 * SUPER), fill=CINZA)
    d.text((margem, topo + 134 * SUPER), totem.codigo_autenticidade,
           font=_fonte(38 * SUPER, True), fill=(15, 23, 42))

    d.text((margem, topo + 196 * SUPER), "Registrador Eletrônico de Ponto — REP-P",
           font=_fonte(20 * SUPER), fill=CINZA)
    d.text((margem, topo + 222 * SUPER), "Aponte a câmera para conferir a autenticidade",
           font=_fonte(20 * SUPER), fill=CINZA)

    # QR na direita, com folga para o recorte da etiqueta.
    lado_qr = 232 * SUPER
    qr = _qrcode(f"{url_base.rstrip('/')}{totem.url_autenticidade}", lado_qr)
    img.paste(qr, (largura - lado_qr - margem, faixa + 46 * SUPER))

    # Rodape: contato, para quem achar o aparelho fora do lugar.
    rodape = altura - 52 * SUPER
    d.rectangle([0, rodape, largura, altura], fill=(241, 245, 249))
    d.text((margem, rodape + 14 * SUPER), "kronus.online  ·  contato@kstec.online",
           font=_fonte(22 * SUPER), fill=(71, 85, 105))

    img = img.resize((LARGURA, ALTURA), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, "PNG", optimize=True, dpi=(300, 300))
    return buffer.getvalue()
