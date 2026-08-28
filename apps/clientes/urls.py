"""
Kronus — porta de entrada personalizada por empresa.

O `<slug>` fica no fim do `config/urls.py`, depois de todas as rotas
nomeadas: assim uma empresa chamada "relatorios" nao sequestra
`/relatorios/`.
"""
from django.urls import path

from apps.clientes import views_portal

app_name = "clientes"

urlpatterns = [
    path("sw.js", views_portal.service_worker, name="service_worker"),
    path("<slug:slug>/manifest.json", views_portal.manifesto_da_empresa, name="manifesto"),
    path("<slug:slug>/", views_portal.LoginDaEmpresa.as_view(), name="portal"),
]
