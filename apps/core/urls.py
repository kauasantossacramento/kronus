from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("selecionar-empresa/", views.selecionar_empresa, name="selecionar_empresa"),
    path("suspenso/", views.cliente_suspenso, name="cliente_suspenso"),
]
