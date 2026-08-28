from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("manifest.json", views.manifesto_do_painel, name="manifesto"),
    path("", views.home, name="home"),
    path("selecionar-empresa/", views.selecionar_empresa, name="selecionar_empresa"),
    path("suspenso/", views.cliente_suspenso, name="cliente_suspenso"),
]
