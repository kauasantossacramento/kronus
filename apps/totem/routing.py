"""Kronus — rotas WebSocket (Django Channels)."""
from django.urls import re_path

from apps.totem import consumers

websocket_urlpatterns = [
    # Canal do equipamento — autenticado pelo token opaco.
    re_path(r"^ws/totem/(?P<token>[\w\-]+)/$", consumers.TotemConsumer.as_asgi()),
    # Canal do dashboard do RH — autenticado pela sessão.
    re_path(
        r"^ws/painel/(?P<empresa>[0-9a-f\-]{36})/$", consumers.PainelConsumer.as_asgi()
    ),
]
