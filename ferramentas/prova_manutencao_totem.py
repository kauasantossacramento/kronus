"""Prova em navegador: o gesto de tres toques abre o modo, e so quando ligado."""
import json, subprocess, sys, time
RAIZ = r"C:\Users\KS TEC\kronus"
PORTA = 8907

PREPARO = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()
from datetime import date
from apps.master.models import Plano
from apps.clientes.models import Cliente, Empresa
from apps.totem.models import Totem
from apps.rh.models import Colaborador

plano,_ = Plano.objects.get_or_create(slug="pmanut", defaults=dict(nome="PManut", max_totems=5, max_colaboradores=50))
cli,_ = Cliente.objects.get_or_create(cnpj="27865757000102",
    defaults=dict(razao_social="Prova Manut", plano=plano, email_contato="pm@x.test"))
emp,_ = Empresa.objects.get_or_create(cnpj="33000167000101",
    defaults=dict(cliente=cli, razao_social="Prova Manut"))
tot,_ = Totem.objects.get_or_create(empresa=emp, apelido="Prova manut", defaults=dict(ativo=True))
for nome, cpf in (("Ana Souza","39053344705"), ("Bruno Lima","12345678909")):
    Colaborador.objects.get_or_create(cpf=cpf, empresa=emp, defaults=dict(
        nome_completo=nome, data_nascimento=date(1990,1,1), data_admissao=date(2024,1,1)))
cli.cadastro_facial_no_totem = {ligado}
cli.save(update_fields=["cadastro_facial_no_totem"])
if {ligado}:
    cli.definir_senha_totem("segredo123")
print(json.dumps({{"token": tot.token_acesso}}))
'''

def preparar(ligado):
    s = subprocess.run([sys.executable, "-c", PREPARO.format(raiz=RAIZ, ligado=ligado)],
                       cwd=RAIZ, capture_output=True, text=True)
    linhas = [l for l in s.stdout.splitlines() if l.startswith("{")]
    if not linhas:
        print(s.stdout); print(s.stderr); raise SystemExit(1)
    return json.loads(linhas[-1])["token"]

token = preparar("False")
srv = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{PORTA}",
                        "--noreload", "--settings=config.settings.development"],
                       cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(5)
from playwright.sync_api import sync_playwright
base = f"http://127.0.0.1:{PORTA}"
r = {}
try:
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--use-fake-ui-for-media-stream",
                                      "--use-fake-device-for-media-stream"])
        ctx = nav.new_context(permissions=["camera"])
        pag = ctx.new_page()
        erros = []
        pag.on("pageerror", lambda e: erros.append(str(e)))

        def tres_toques():
            # O relogio visivel: os outros vivem em telas ocultas.
            alvo = pag.locator(".totem-relogio:visible").first
            for _ in range(3):
                alvo.click()
                pag.wait_for_timeout(120)
            pag.wait_for_timeout(500)

        pag.goto(f"{base}/totem/{token}/", wait_until="networkidle")
        pag.wait_for_timeout(2500)
        tres_toques()
        r["1. desligado: nao abre"] = not pag.is_visible("#tela-manut-senha")

        # liga e recarrega
        preparar("True")
        pag.reload(wait_until="networkidle")
        pag.wait_for_timeout(2500)
        tres_toques()
        r["2. ligado: abre a senha"] = pag.is_visible("#tela-manut-senha")

        pag.fill("#campo-manut-senha", "errada")
        pag.click("#form-manut-senha button[type=submit]")
        pag.wait_for_timeout(1200)
        r["3. senha errada avisa"] = pag.is_visible("#erro-manut-senha")

        pag.fill("#campo-manut-senha", "segredo123")
        pag.click("#form-manut-senha button[type=submit]")
        pag.wait_for_timeout(1500)
        r["4. senha certa lista"] = pag.is_visible("#tela-manut-lista")
        r["5. dois colaboradores"] = pag.locator(".totem-manut-item").count() == 2

        pag.fill("#campo-manut-busca", "Bruno")
        pag.wait_for_timeout(400)
        r["6. busca filtra"] = pag.locator(".totem-manut-item").count() == 1

        pag.fill("#campo-manut-busca", "")
        pag.wait_for_timeout(300)
        pag.locator(".totem-manut-item__botao").first.click()
        pag.wait_for_timeout(600)
        r["7. pede consentimento"] = pag.is_visible("#tela-manut-lgpd")
        r["8. continuar bloqueado"] = pag.locator("#manut-lgpd-continuar").is_disabled()

        pag.check("#manut-lgpd-aceite")
        pag.wait_for_timeout(200)
        r["9. aceite libera"] = not pag.locator("#manut-lgpd-continuar").is_disabled()

        pag.click("#manut-lgpd-continuar")
        pag.wait_for_timeout(2500)
        r["10. abre a captura"] = pag.is_visible("#tela-manut-captura")
        r["11. camera ligada"] = pag.evaluate(
            "() => { const v = document.getElementById('manut-video');"
            " return !!(v && v.srcObject); }")
        r["12. ponto certo tem 5 poses"] = pag.locator(".totem-manut-ponto").count() == 5
        r["13. ponto de ponto parado"] = not pag.is_visible("#tela-idle")
        r["14. sem erro de JS"] = not erros
        if erros: print("   ERROS:", erros[:3])
        nav.close()
finally:
    srv.terminate(); srv.wait(timeout=10)

for k, v in r.items():
    print(f"   {k:30s}: {v}")
ok = all(r.values())
print("\nO modo de manutencao abre so quando ligado, e segue o roteiro."
      if ok else "\nFALHOU.")
raise SystemExit(0 if ok else 1)
