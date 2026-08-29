"""
Kronus — porteiro dos arquivos sensiveis em `media/`.

O Nginx servia `media/` inteiro em aberto. Bastava ter a URL — e ela
aparece no HTML de quem tem acesso — para baixar de qualquer lugar, sem
sessao. Nesse diretorio vivem:

    faces/amostras/      fotos do cadastro facial
    faces/tentativas/    quadros das batidas no totem
    faces/perfil/        foto do colaborador
    atestados/           atestado medico
    justificativas/      comprovantes
    afastamentos/        documentos

Biometria e saude sao dados pessoais **sensiveis** (LGPD Art. 11). Deixar
a URL como unica protecao e seguranca por obscuridade, e a URL nao e
segredo: ela e impressa na propria pagina que a exibe.

Como funciona. O Nginx continua entregando os bytes — e o que ele faz
bem —, mas antes pergunta a este endpoint se pode. Assim nenhuma pagina
precisou mudar: as URLs continuam as mesmas, e quem nao tem sessao passa
a receber 403 em vez do arquivo.

O que este porteiro decide e o **acesso a classe de arquivo**, e nao a um
objeto especifico. E a primeira camada: separa "qualquer um na internet"
de "alguem autenticado com papel compativel". A checagem por objeto
continua onde ela pode ser feita — nas telas que listam e nas views que
entregam um registro por vez.
"""
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.core.constants import TipoUsuario

#: Papeis que podem ver arquivo sensivel.
#:
#: Colaborador fica de fora de proposito: a foto dele aparece na propria
#: ficha, servida por view que ja confere de quem e. Liberar a classe
#: inteira daria a ele a foto de todo mundo.
PAPEIS_COM_ACESSO = frozenset({
    TipoUsuario.MASTER,
    TipoUsuario.CLIENTE,
    TipoUsuario.RH,
})


@require_GET
@never_cache
def permissao_midia(request):
    """
    Consultado pelo Nginx (`auth_request`) antes de entregar o arquivo.

    Responde apenas com o codigo: 200 libera, 403 recusa. O corpo e
    descartado pelo Nginx, entao nao ha o que escrever nele.
    """
    usuario = getattr(request, "user", None)
    if not usuario or not usuario.is_authenticated:
        return HttpResponseForbidden()

    if usuario.is_superuser or getattr(usuario, "tipo", None) in PAPEIS_COM_ACESSO:
        return HttpResponse(status=200)

    return HttpResponseForbidden()
