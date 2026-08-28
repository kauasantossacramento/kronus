from django.contrib import admin

from apps.core.models import Feriado, LogAcesso


@admin.register(LogAcesso)
class LogAcessoAdmin(admin.ModelAdmin):
    list_display = ("created_at", "usuario", "acao", "descricao", "cliente", "empresa", "ip")
    list_filter = ("acao", "created_at")
    search_fields = ("descricao", "objeto_id", "ip")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in LogAcesso._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ("nome", "data", "abrangencia", "uf", "municipio", "empresa")
    list_filter = ("abrangencia", "recorrente")
    search_fields = ("nome",)
    date_hierarchy = "data"
