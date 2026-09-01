"""Kronus — URLconf de faturamento e assinaturas."""
from django.urls import path

from apps.faturamento import views

app_name = "faturamento"

urlpatterns = [
    # Publico: so o webhook, protegido por token no header.
    path("webhook/asaas/", views.webhook_asaas, name="webhook_asaas"),
    # Area do cliente
    path("minha-assinatura/", views.minha_assinatura, name="minha_assinatura"),
    path("planos/", views.planos_disponiveis, name="planos"),
    path("checkout/<slug:slug>/", views.checkout, name="checkout"),
    path("adicionais/totens/", views.contratar_totens, name="contratar_totens"),
    path("cancelar/", views.cancelar_assinatura, name="cancelar"),
    # A fatura no proprio dominio. Ver views.fatura.
    path("fatura/<uuid:uuid>/", views.fatura, name="fatura"),
]
