"""Reproduz o wizard de colaborador: o botao salvar devolve resultado?"""
import json
import subprocess
import sys
import time

RAIZ = r"C:\Users\KS TEC\kronus"
PORTA = 8909

PREPARO = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()
from apps.master.models import Plano
from apps.clientes.models import Cliente, Empresa
from apps.accounts.models import CustomUser
from apps.rh.models import Colaborador
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, HASH_SESSION_KEY

plano,_ = Plano.objects.get_or_create(slug="pwiz", defaults=dict(nome="PWiz", max_colaboradores=99))
cli,_ = Cliente.objects.get_or_create(cnpj="27865757000102",
    defaults=dict(razao_social="Prova Wizard", plano=plano, email_contato="pw@x.test"))
cli.plano = plano; cli.save(update_fields=["plano"])
emp,_ = Empresa.objects.get_or_create(cnpj="33000167000101",
    defaults=dict(cliente=cli, razao_social="Prova Wizard"))
u = CustomUser.objects.filter(email="wizard@x.test").first()
if not u:
    u = CustomUser.objects.create_user(email="wizard@x.test", password="Prova!12345",
                                       nome_completo="RH", tipo="rh", cliente=cli)
u.empresas.add(emp); u.save()
Colaborador.objects.filter(cpf="39053344705").delete()
s = SessionStore()
s[SESSION_KEY] = str(u.pk)
s[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
s[HASH_SESSION_KEY] = u.get_session_auth_hash()
s["empresa_ativa_id"] = emp.pk
s.create()
print(json.dumps({{"sessao": s.session_key, "empresa": emp.pk}}))
'''

CONFERIR = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()
from apps.rh.models import Colaborador
c = Colaborador.objects.filter(cpf="39053344705").first()
print(json.dumps({{"salvou": c is not None, "nome": c.nome_completo if c else None}}))
'''


def rodar(codigo):
    s = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ,
                       capture_output=True, text=True)
    linhas = [l for l in s.stdout.splitlines() if l.startswith("{")]
    if not linhas:
        print(s.stdout)
        print(s.stderr)
        raise SystemExit(1)
    return json.loads(linhas[-1])


dados = rodar(PREPARO.format(raiz=RAIZ))
srv = subprocess.Popen(
    [sys.executable, "manage.py", "runserver", f"127.0.0.1:{PORTA}",
     "--noreload", "--settings=config.settings.development"],
    cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(5)

from playwright.sync_api import sync_playwright

base = f"http://127.0.0.1:{PORTA}"
r = {}
try:
    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context()
        ctx.add_cookies([{"name": "sessionid", "value": dados["sessao"],
                          "domain": "127.0.0.1", "path": "/"}])
        pag = ctx.new_page()
        erros = []
        pag.on("pageerror", lambda e: erros.append("pageerror: " + str(e)))
        pag.on("console", lambda m: erros.append(m.type + ": " + m.text)
               if m.type == "error" else None)

        pag.goto(f"{base}/rh/colaboradores/novo/", wait_until="networkidle")
        pag.wait_for_timeout(1200)
        r["1. abriu o wizard"] = pag.locator("form").count() > 0

        # -- a) faltando um obrigatorio: o erro precisa APARECER --
        pag.fill("#id_nome_completo", "Teste Wizard")
        pag.fill("#id_cpf", "390.533.447-05")
        pag.locator("button[type=submit]:visible").first.click(no_wait_after=True)
        pag.wait_for_timeout(2000)
        r["2. erro aparece na tela"] = pag.locator("[data-campo-erro]").count() > 0
        r["3. o erro fica visivel"] = (
            pag.locator("[data-campo-erro]:visible").count() > 0
        )

        # -- b) primeiro passo completo: salva --
        pag.fill("#id_nome_completo", "Teste Wizard")
        pag.fill("#id_cpf", "390.533.447-05")
        pag.fill("#id_data_nascimento", "1990-05-12")
        pag.fill("#id_data_admissao", "2024-01-15")
        pag.locator("button[type=submit]:visible").first.click(no_wait_after=True)
        pag.wait_for_load_state("networkidle")
        pag.wait_for_timeout(1500)

        conferido = rodar(CONFERIR.format(raiz=RAIZ))
        r["4. salvou no banco"] = conferido["salvou"]
        # Salvando do primeiro passo, vai para a ficha — e nao para uma
        # captura de rosto que a pessoa nao pediu.
        r["5. levou a ficha, nao a camera"] = (
            "/rh/colaboradores/" in pag.url and "novo" not in pag.url
            and "/facial/" not in pag.url
        )
        print("   url final:", pag.url.replace(base, ""))

        if not conferido["salvou"]:
            visiveis = pag.locator(".text-red-600, .text-red-700").all_inner_texts()
            print("   url depois:", pag.url.replace(base, "") or "/")
            print("   erros na tela:", visiveis[:6] or "nenhum")
            print("   campos required invisiveis:", pag.evaluate(
                "() => Array.from(document.querySelectorAll('[required]'))"
                ".filter(e => e.offsetParent === null)"
                ".map(e => e.name)"))
        print("   erros de JS:", erros[:4] or "nenhum")
        nav.close()
finally:
    srv.terminate()
    srv.wait(timeout=10)

for k, v in r.items():
    print(f"   {k:26s}: {v}")
raise SystemExit(0 if all(r.values()) else 1)
