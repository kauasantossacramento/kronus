"""Kronus — landing page publica."""
from django.shortcuts import render

from apps.master.models import Plano


def contexto_da_capa() -> dict:
    """
    Contexto comum da capa.

    Extraido para funcao porque a view de demonstracao precisa
    re-renderizar a mesma pagina quando o formulario falha — e uma capa
    que volta sem os planos, so porque o e-mail estava invalido, parece
    quebrada.
    """
    from apps.comercial.forms import FormularioDemonstracao
    from apps.comercial.models import ConfiguracaoComercial

    return {
        "titulo": "Kronus — O tempo sob controle",
        "planos": Plano.objects.filter(ativo=True).order_by("ordem", "preco_mensal"),
        "config_comercial": ConfiguracaoComercial.carregar(),
        "formulario_demo": FormularioDemonstracao(),
    }


def index(request):
    return render(request, "landing/index.html", contexto_da_capa())
