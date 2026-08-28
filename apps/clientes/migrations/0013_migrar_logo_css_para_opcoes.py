"""
Converte o CSS livre da logo nas opcoes por tela.

Antes existia so `logo_css`, aplicado ao sistema inteiro. Quem escreveu
ali a regra de deixar a logo branca esperava que ela continuasse valendo
— entao a conversao marca as duas telas e remove a regra do campo livre,
para que ela nao seja aplicada duas vezes.
"""
import re

from django.db import migrations

# `filter: brightness(0) invert(1)` em qualquer espacamento ou ordem de
# escrita. Nao tenta interpretar CSS de verdade: procura a receita que a
# ajuda antiga sugeria, que e o que as pessoas copiaram.
PADRAO = re.compile(
    r"filter\s*:\s*brightness\(\s*0\s*\)\s+invert\(\s*1\s*\)\s*;?",
    re.IGNORECASE,
)


def converter(apps, schema_editor):
    Empresa = apps.get_model("clientes", "Empresa")
    for empresa in Empresa.objects.exclude(logo_css="").exclude(logo_css=None):
        if not PADRAO.search(empresa.logo_css or ""):
            continue
        empresa.logo_branca_totem = True
        empresa.logo_branca_login = True
        empresa.logo_css = PADRAO.sub("", empresa.logo_css).strip()
        empresa.save(update_fields=[
            "logo_branca_totem", "logo_branca_login", "logo_css",
        ])


def reverter(apps, schema_editor):
    """Devolve a regra ao campo livre, para nao perder a configuracao."""
    Empresa = apps.get_model("clientes", "Empresa")
    for empresa in Empresa.objects.filter(logo_branca_totem=True):
        regra = "filter: brightness(0) invert(1);"
        if regra not in (empresa.logo_css or ""):
            empresa.logo_css = f"{regra} {empresa.logo_css or ''}".strip()
            empresa.save(update_fields=["logo_css"])


class Migration(migrations.Migration):
    dependencies = [
        ("clientes", "0012_empresa_cor_fundo_login_empresa_logo_branca_login_and_more"),
    ]
    operations = [migrations.RunPython(converter, reverter)]
