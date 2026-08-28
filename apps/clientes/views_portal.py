"""
Kronus — porta de entrada personalizada por empresa.

    kronus.online/<slug>/            login com a marca da empresa

**Por que por caminho e não por subdomínio.** `empresa.kronus.online`
exige DNS curinga (`*.kronus.online`) e um certificado curinga, que a
Let's Encrypt só emite pelo desafio DNS-01 — o que amarra a renovação a
uma API do provedor de DNS. O caminho funciona hoje, com o certificado
que já existe, e não cria uma dependência de renovação que pode falhar
de madrugada e derrubar todos os clientes de uma vez.

O código já resolve a empresa por slug independentemente da origem;
migrar para subdomínio depois é acrescentar a leitura do `Host`, não
reescrever a autenticação.

**O que a página personaliza:** logo, cores, nome e uma saudação. O que
ela *não* faz é revelar quem trabalha ali — o formulário é o mesmo, e um
login errado responde igual em qualquer empresa.
"""
import logging

from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.clientes.models import Empresa

logger = logging.getLogger("kronus.clientes")


class LoginDaEmpresa(auth_views.LoginView):
    """
    Login com a identidade visual da empresa.

    Herda de `LoginView` de propósito: autenticação, limitação de
    tentativas e mensagens de erro continuam sendo as do Django e as do
    projeto. A personalização é só a moldura.
    """

    template_name = "clientes/portal_login.html"
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        self.empresa = get_object_or_404(
            Empresa.objects.select_related("cliente"),
            slug=kwargs.get("slug"),
            ativo=True,
        )
        # Conta suspensa não mostra porta personalizada: seria convidar
        # a pessoa a tentar entrar num sistema que vai recusá-la.
        if self.empresa.cliente.suspenso:
            return redirect("accounts:login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update({
            "empresa_portal": self.empresa,
            "titulo": self.empresa.nome_exibicao,
        })
        return contexto

    def get_success_url(self):
        # Depois de entrar, o destino é o de sempre — quem decide para
        # onde ir é o papel do usuário, não a porta por onde entrou.
        return self.get_redirect_url() or reverse("core:home")


def manifesto_da_empresa(request, slug):
    """
    Manifesto PWA por empresa.

    Cada empresa instala **o seu próprio** app: nome, ícone e cor da
    barra são os dela. Um manifesto único faria todos os clientes
    instalarem um ícone "Kronus" idêntico na tela inicial, e num celular
    com dois empregos isso vira confusão.
    """
    from django.http import JsonResponse

    empresa = get_object_or_404(Empresa, slug=slug, ativo=True)
    icone = empresa.logo.url if empresa.logo else "/static/img/favicon.svg"

    return JsonResponse({
        "name": f"Ponto — {empresa.nome_exibicao}",
        "short_name": empresa.nome_exibicao[:12],
        "description": f"Registro de ponto de {empresa.nome_exibicao}",
        "start_url": f"/{empresa.slug}/",
        "scope": "/",
        # `standalone` e não `fullscreen`: o colaborador precisa da barra
        # de status para ver a hora do aparelho e o sinal — num app de
        # ponto, a hora é a informação central.
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#FFFFFF",
        "theme_color": empresa.cor_primaria,
        "lang": "pt-BR",
        "icons": [
            {"src": icone, "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icone, "sizes": "512x512", "type": "image/png", "purpose": "any"},
        ],
        "shortcuts": [
            {
                "name": "Registrar ponto",
                "url": "/ponto/registrar/",
                "description": "Bater o ponto agora",
            },
            {
                "name": "Meus pontos",
                "url": "/ponto/meus-pontos/",
                "description": "Consultar as marcações do mês",
            },
        ],
    })
