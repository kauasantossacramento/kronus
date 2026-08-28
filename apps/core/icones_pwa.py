"""
Kronus — lista de icones dos manifestos PWA.

Centralizado porque o erro que motivou este modulo se repetia nos tres
manifestos: todos declaravam `"type": "image/png"` apontando para um
`.svg`. O Chrome valida o icone antes de considerar o site instalavel;
com o tipo mentindo sobre o arquivo, o icone e descartado, o app deixa de
ser instalavel e o `beforeinstallprompt` nunca dispara — nenhum convite
de instalacao aparecia, em aparelho nenhum.
"""
import mimetypes

PADRAO = [
    {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png",
     "purpose": "any"},
    {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png",
     "purpose": "any"},
    # O Android recorta o icone; a versao `maskable` tem margem para
    # sobreviver ao recorte sem perder o simbolo.
    {"src": "/static/img/icon-512-maskable.png", "sizes": "512x512",
     "type": "image/png", "purpose": "maskable"},
]


def para_logo(url: str | None) -> list[dict]:
    """
    Icones do manifesto de uma empresa.

    A logo enviada pelo cliente pode ser PNG, JPG, WEBP ou SVG — o tipo
    sai do proprio nome do arquivo, nunca de um palpite. Quando nao ha
    logo, cai nos icones do Kronus, que sabidamente atendem aos
    requisitos de instalacao.
    """
    if not url:
        return list(PADRAO)

    tipo = mimetypes.guess_type(url)[0] or "image/png"
    if tipo == "image/svg+xml":
        # SVG nao tem tamanho fixo; declarar um numero seria mentir de
        # novo, e `any` e o valor previsto para vetor.
        icones = [{"src": url, "sizes": "any", "type": tipo, "purpose": "any"}]
    else:
        icones = [
            {"src": url, "sizes": "192x192", "type": tipo, "purpose": "any"},
            {"src": url, "sizes": "512x512", "type": tipo, "purpose": "any"},
        ]
    # Mantem os icones do Kronus como reserva: se a logo do cliente nao
    # atender ao tamanho minimo, o app continua instalavel.
    return icones + list(PADRAO)
