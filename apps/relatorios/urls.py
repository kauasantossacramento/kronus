from django.urls import path

from apps.relatorios import views

app_name = "relatorios"

urlpatterns = [
    # -- Arquivos fiscais (Portaria 671) -----------------------
    path("fiscais/", views.fiscais, name="fiscais"),
    path("afd/", views.baixar_afd, name="afd"),
    path("aej/", views.baixar_aej, name="aej"),

    # -- Gerenciais --------------------------------------------
    path("gerenciais/", views.gerenciais, name="gerenciais"),
    path("gerenciais/csv/", views.exportar_csv, name="gerenciais_csv"),

    # -- Portal do contador ------------------------------------
    path("contador/", views.portal_contador, name="portal_contador"),
]
