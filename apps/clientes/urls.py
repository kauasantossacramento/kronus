"""
Kronus — porta de entrada personalizada por empresa.

O `<slug>` fica no fim do `config/urls.py`, depois de todas as rotas
nomeadas: assim uma empresa chamada "relatorios" nao sequestra
`/relatorios/`.
"""
from django.urls import path
from django.views.generic import TemplateView

from apps.clientes import views_portal

app_name = "clientes"

urlpatterns = [
    path(
        "sw.js",
        TemplateView.as_view(
            template_name="clientes/sw.js",
            content_type="application/javascript",
        ),
        name="service_worker",
    ),
    path("<slug:slug>/manifest.json", views_portal.manifesto_da_empresa, name="manifesto"),
    path("<slug:slug>/", views_portal.LoginDaEmpresa.as_view(), name="portal"),
]
