from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ("nome_completo", "email", "cpf", "tipo", "cliente", "is_active")
    list_filter = ("tipo", "is_active", "is_staff")
    search_fields = ("nome_completo", "email", "cpf", "username")
    ordering = ("nome_completo",)
    filter_horizontal = ("empresas", "groups", "user_permissions")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identificacao", {"fields": ("nome_completo", "email", "cpf", "telefone", "avatar")}),
        ("Papel e escopo", {"fields": ("tipo", "cliente", "empresas")}),
        ("Seguranca", {"fields": ("trocar_senha_no_proximo_login", "bloqueado_ate",
                                  "tentativas_login_falhas", "ultimo_acesso_ip")}),
        ("LGPD", {"fields": ("aceite_termos_em", "aceite_biometria_em")}),
        ("Permissoes", {"fields": ("is_active", "is_staff", "is_superuser",
                                   "groups", "user_permissions")}),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "nome_completo", "email", "cpf",
                       "tipo", "cliente", "password1", "password2"),
        }),
    )
