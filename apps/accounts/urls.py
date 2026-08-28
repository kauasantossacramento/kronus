from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.KronusLoginView.as_view(), name="login"),
    path("colaborador/", views.LoginColaboradorView.as_view(), name="login_colaborador"),
    path("logout/", views.logout_view, name="logout"),
    path("perfil/", views.perfil, name="perfil"),
    path(
        "definir-senha/",
        views.trocar_senha_primeiro_acesso,
        name="trocar_senha_primeiro_acesso",
    ),
    # -- Recuperacao de senha ---------------------------------
    path(
        "recuperar-senha/",
        views.KronusPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "recuperar-senha/enviado/",
        views.KronusPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "recuperar-senha/<uidb64>/<token>/",
        views.KronusPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "recuperar-senha/concluido/",
        views.KronusPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
