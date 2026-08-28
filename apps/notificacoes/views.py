"""Kronus — central de notificacoes in-app."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.notificacoes.models import Notificacao


@login_required
def lista(request):
    notificacoes = request.user.notificacoes.all()[:100]
    return render(
        request,
        "notificacoes/lista.html",
        {"titulo": "Notificações", "notificacoes": notificacoes},
    )


@login_required
def marcar_lida(request, pk):
    notificacao = get_object_or_404(Notificacao, pk=pk, destinatario=request.user)
    notificacao.marcar_lida()
    return redirect(notificacao.url_acao or "notificacoes:lista")
