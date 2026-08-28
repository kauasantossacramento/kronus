from django.urls import path

from apps.comercial import views

app_name = "comercial"

urlpatterns = [
    path("demonstracao/", views.solicitar, name="solicitar"),
    path("demonstracao/encerrada/", views.expirada, name="expirada"),
]
