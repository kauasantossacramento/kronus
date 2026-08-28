"""
Kronus — landing page publica.

A versao completa (secoes de funcionalidades, planos, depoimentos e
formulario de contato) e entregue na Fase 6. Nesta fase existe apenas
o esqueleto navegavel com a identidade visual aplicada.
"""
from django.shortcuts import render

from apps.master.models import Plano


def index(request):
    contexto = {
        "titulo": "Kronus — O tempo sob controle",
        "planos": Plano.objects.filter(ativo=True).order_by("ordem", "preco_mensal"),
    }
    return render(request, "landing/index.html", contexto)
