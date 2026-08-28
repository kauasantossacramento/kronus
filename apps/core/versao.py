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

# Arquivos que definem "a aparencia do sistema". Basta um deles mudar
# para o carimbo mudar — nao ha necessidade de varrer todo o static/.
_REFERENCIAS = (
    "css/main.css",
    "css/kronus-design-system.css",
)


def _origens() -> list[Path]:
    raizes = [Path(settings.STATIC_ROOT)] if getattr(settings, "STATIC_ROOT", None) else []
    raizes += [Path(d) for d in getattr(settings, "STATICFILES_DIRS", [])]
    return [raiz / rel for raiz in raizes for rel in _REFERENCIAS]


def versao_dos_estaticos() -> str:
    """
    Identificador curto e estavel do conjunto de estaticos publicado.

    Se nenhum arquivo de referencia existir (checkout sem build de CSS,
    por exemplo), devolve um valor fixo em vez de estourar: uma pagina
    sem cache-busting e um problema menor do que uma pagina que nao
    renderiza.
    """
    global _carimbo
    if _carimbo is not None:
        return _carimbo

    digestor = hashlib.sha256()
    encontrou = False
    for caminho in _origens():
        try:
            info = caminho.stat()
        except OSError:
            continue
        encontrou = True
        digestor.update(f"{caminho.name}:{info.st_mtime_ns}:{info.st_size}".encode())

    _carimbo = digestor.hexdigest()[:10] if encontrou else "dev"
    return _carimbo
