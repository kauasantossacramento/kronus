from django.urls import path

from apps.notificacoes import views

app_name = "notificacoes"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("<int:pk>/lida/", views.marcar_lida, name="marcar_lida"),
]
