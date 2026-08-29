"""A previa do totem existe, mostra as duas marcas e reage ao formulario."""
import json, subprocess, sys, time
RAIZ = r"C:\Users\KS TEC\kronus"
PORTA = 8911

PREPARO = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()
from apps.master.models import Plano
from apps.clientes.models import Cliente, Empresa
from apps.accounts.models import CustomUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, HASH_SESSION_KEY

plano,_ = Plano.objects.get_or_create(slug="pprev", defaults=dict(nome="PPrev"))
cli,_ = Cliente.objects.get_or_create(cnpj="27865757000102",
    defaults=dict(razao_social="Prova Previa", plano=plano, email_contato="pp@x.test"))
emp,_ = Empresa.objects.get_or_create(cnpj="33000167000101",
    defaults=dict(cliente=cli, razao_social="Prova Previa"))
u = CustomUser.objects.filter(email="master@x.test").first()
if not u:
    u = CustomUser.objects.create_superuser(email="master@x.test", password="Prova!12345",
                                            nome_completo="Master")
s = SessionStore()
s[SESSION_KEY] = str(u.pk)
s[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
s[HASH_SESSION_KEY] = u.get_session_auth_hash()
s.create()
print(json.dumps({{"sessao": s.session_key, "empresa": emp.pk}}))
'''

s = subprocess.run([sys.executable, "-c", PREPARO.format(raiz=RAIZ)], cwd=RAIZ,
                   capture_output=True, text=True)
linhas = [l for l in s.stdout.splitlines() if l.startswith("{")]
if not linhas:
    print(s.stdout); print(s.stderr); raise SystemExit(1)
d = json.loads(linhas[-1])

srv = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{PORTA}",
                        "--noreload", "--settings=config.settings.development"],
                       cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(5)
from playwright.sync_api import sync_playwright
base = f"http://127.0.0.1:{PORTA}"
r = {}
try:
    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context()
        ctx.add_cookies([{"name": "sessionid", "value": d["sessao"],
                          "domain": "127.0.0.1", "path": "/"}])
        pag = ctx.new_page()
        erros = []
        pag.on("pageerror", lambda e: erros.append(str(e)))
        pag.goto(f"{base}/master/empresas/{d['empresa']}/personalizacao/",
                 wait_until="networkidle")
        pag.wait_for_timeout(1200)

        r["1. previa existe"] = pag.locator("#previa-totem").count() == 1
        r["2. proporcao 7 pol"] = pag.evaluate(
            "() => { const e = document.getElementById('previa-totem');"
            " const s = getComputedStyle(e);"
            " return Math.abs(e.clientHeight / e.clientWidth - 1024/600) < 0.05; }")
        r["3. as duas marcas"] = (
            pag.locator("#previa-totem-kronus").count() == 1
            and pag.locator("#previa-totem-kstec").count() == 1
        )

        antes = pag.evaluate(
            "() => getComputedStyle(document.getElementById("
            "'previa-totem-kronus')).fontSize")
        pag.fill("#id_marca_kronus_px", "40")
        pag.dispatch_event("#id_marca_kronus_px", "input")
        pag.wait_for_timeout(300)
        depois = pag.evaluate(
            "() => getComputedStyle(document.getElementById("
            "'previa-totem-kronus')).fontSize")
        r["4. Kronus reage"] = antes != depois
        print(f"   marca Kronus: {antes} -> {depois}")

        alt_antes = pag.evaluate(
            "() => document.getElementById('previa-totem-kstec').style.height")
        pag.fill("#id_assinatura_altura_px", "60")
        pag.dispatch_event("#id_assinatura_altura_px", "input")
        pag.wait_for_timeout(300)
        alt_depois = pag.evaluate(
            "() => document.getElementById('previa-totem-kstec').style.height")
        r["5. KS TEC reage"] = alt_antes != alt_depois
        print(f"   assinatura KS TEC: {alt_antes} -> {alt_depois}")

        pag.fill("#id_msg_boas_vindas", "Bata seu ponto aqui")
        pag.dispatch_event("#id_msg_boas_vindas", "input")
        pag.wait_for_timeout(300)
        r["6. texto reage"] = pag.locator("#previa-totem-boas").inner_text().strip() == "Bata seu ponto aqui"

        r["7. sem erro de JS"] = not erros
        if erros: print("   ERROS:", erros[:3])
        nav.close()
finally:
    srv.terminate(); srv.wait(timeout=10)

for k, v in r.items():
    print(f"   {k:24s}: {v}")
raise SystemExit(0 if all(r.values()) else 1)
