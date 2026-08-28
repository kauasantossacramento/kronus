import os, sys, django
sys.path.insert(0, os.getcwd())
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.development"
django.setup()
from django.test import Client
from django.urls import reverse, NoReverseMatch
from apps.accounts.models import CustomUser
from apps.core.constants import TipoUsuario
from apps.clientes.models import Empresa

PASTA = r"C:\Users\KSTEC~1\AppData\Local\Temp\claude\c--Users-KS-TEC-kronus\e2567f89-1ee7-49dd-b019-d146e5d8e48f\scratchpad\telas"
os.makedirs(PASTA, exist_ok=True)

ROTAS = {
    "master": [
        "master:dashboard", "master:cliente_lista", "master:empresa_lista",
        "master:plano_lista", "master:totem_lista", "master:assinaturas",
        "master:custos", "master:usuarios", "master:auditoria",
        "master:gateway", "master:comercial_config", "master:comercial_demos",
        "master:log_lista",
    ],
    "rh": [
        "rh:dashboard", "rh:colaborador_lista", "rh:equipamentos",
        "rh:qualidade_facial", "rh:personalizacao", "rh:slides_totem",
        "rh:webhooks", "rh:integracao",
    ],
}

def usuario(tipo):
    u = CustomUser.objects.filter(tipo=tipo, is_active=True).first()
    return u

registro = []
for papel, rotas in ROTAS.items():
    tipo = TipoUsuario.MASTER if papel == "master" else TipoUsuario.RH
    u = usuario(tipo)
    if u is None:
        print(f"!! sem usuario {papel}"); continue
    c = Client(); c.force_login(u)
    for nome in rotas:
        try:
            url = reverse(nome)
        except NoReverseMatch:
            print(f"   rota inexistente: {nome}"); continue
        r = c.get(url, follow=True)
        if r.status_code != 200:
            print(f"   {nome}: HTTP {r.status_code}"); continue
        arq = f"{papel}__{nome.replace(':','_')}.html"
        open(os.path.join(PASTA, arq), "w", encoding="utf-8").write(r.content.decode())
        registro.append((papel, nome, arq))

import json
json.dump(registro, open(os.path.join(PASTA, "indice.json"), "w"), ensure_ascii=False)
print(f"{len(registro)} telas salvas")
