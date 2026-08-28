"""
Kronus — carimbo de versao dos arquivos estaticos.

O problema que isto resolve: o Nginx serve `/static/css/main.css` com
`Cache-Control: public, immutable, max-age=2592000`. "Immutable" diz ao
navegador para **nao revalidar** — e o nome do arquivo nunca muda entre
deploys. O resultado e que quem abriu o site uma vez fica trinta dias
presos ao CSS antigo, vendo HTML novo com estilo velho, sem nenhuma
forma de descobrir que existe versao nova. Foi o que produziu o relato
de "html basico, sem estilo", a tela do celular quebrada e o PWA que
nao atualiza.

A correcao e dar a cada deploy uma URL propria: `main.css?v=<carimbo>`.
Uma URL nova e uma chave de cache nova, entao o navegador busca o
arquivo na hora — inclusive aquele que ja tem a copia "immutable"
guardada, sem exigir Ctrl+Shift+R do usuario.

O carimbo sai do proprio arquivo compilado (mtime + tamanho), e nao de
uma constante que alguem precise lembrar de incrementar: um carimbo que
depende de disciplina humana e um carimbo que um dia fica para tras.
"""
import hashlib
from pathlib import Path

from django.conf import settings

# Calculado uma vez por processo. O deploy reinicia os servicos, entao
# o valor acompanha o deploy sem custo de I/O por requisicao.
_carimbo: str | None = None

# Extensoes que o carimbo acompanha.
#
# A primeira versao listava dois arquivos a mao — `main.css` e o design
# system. Funcionou ate mexermos no CSS do totem: ele nao estava na
# lista, o carimbo nao mudou, e o navegador seguiu servindo a folha
# antiga. O sintoma foi um ajuste de tamanho de fonte que "nao fazia
# efeito", sem nada errado no codigo.
#
# Varrer tudo custa alguns milissegundos, uma vez por processo, e nao
# depende de alguem lembrar de acrescentar o arquivo novo.
_EXTENSOES = (".css", ".js")


def _origens() -> list[Path]:
    raizes = []
    if getattr(settings, "STATIC_ROOT", None):
        raizes.append(Path(settings.STATIC_ROOT))
    raizes += [Path(d) for d in getattr(settings, "STATICFILES_DIRS", [])]

    arquivos = []
    for raiz in raizes:
        if not raiz.is_dir():
            continue
        for caminho in raiz.rglob("*"):
            if caminho.suffix.lower() in _EXTENSOES and caminho.is_file():
                arquivos.append(caminho)
    return arquivos


def versao_dos_estaticos() -> str:
    """
    Identificador curto e estavel do conjunto de estaticos publicado.

    Se nenhum arquivo for encontrado (checkout sem build de CSS, por
    exemplo), devolve um valor fixo em vez de estourar: uma pagina sem
    cache-busting e um problema menor do que uma pagina que nao
    renderiza.
    """
    global _carimbo
    if _carimbo is not None:
        return _carimbo

    digestor = hashlib.sha256()
    encontrou = False
    # Ordenado: a ordem do sistema de arquivos varia entre maquinas, e um
    # carimbo diferente por servidor invalidaria o cache sem motivo.
    for caminho in sorted(_origens()):
        try:
            info = caminho.stat()
        except OSError:
            continue
        encontrou = True
        digestor.update(f"{caminho.name}:{info.st_mtime_ns}:{info.st_size}".encode())

    _carimbo = digestor.hexdigest()[:10] if encontrou else "dev"
    return _carimbo
