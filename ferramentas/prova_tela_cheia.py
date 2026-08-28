"""Prova: o atalho de tela cheia sobrevive a recusa do convite de instalacao."""
import json, os, subprocess, sys, time
RAIZ = r"C:\Users\KS TEC\kronus"
PORTA = 8901

PREPARO = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()
from apps.totem.models import Totem
print(json.dumps({{"token": Totem.objects.filter(ativo=True).first().token_acesso}}))
'''

def main():
    saida = subprocess.run([sys.executable, "-c", PREPARO.format(raiz=RAIZ)],
                           cwd=RAIZ, capture_output=True, text=True)
    linha = [l for l in saida.stdout.splitlines() if l.startswith("{")]
    if not linha:
        print(saida.stdout, saida.stderr); return 1
    token = json.loads(linha[-1])["token"]

    srv = subprocess.Popen([sys.executable, "manage.py", "runserver",
                            f"127.0.0.1:{PORTA}", "--noreload",
                            "--settings=config.settings.development"],
                           cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    from playwright.sync_api import sync_playwright
    url = f"http://127.0.0.1:{PORTA}/totem/{token}/"
    resultados = {}
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            ctx = nav.new_context()
            pag = ctx.new_page()
            erros = []
            pag.on("pageerror", lambda e: erros.append(str(e)))

            pag.goto(url); pag.wait_for_timeout(1800)
            resultados["1. primeira visita"] = pag.is_visible("#totem-fs-atalho")

            # O usuario recusa o convite de instalacao, como aconteceu.
            pag.evaluate("() => localStorage.setItem("
                         "'kronus-totem-instalar-recusado', '1')")
            pag.goto(url); pag.wait_for_timeout(1800)
            resultados["2. apos recusar o convite"] = pag.is_visible("#totem-fs-atalho")

            # E recarrega de novo, que foi o relato.
            pag.reload(); pag.wait_for_timeout(1800)
            resultados["3. apos recarregar"] = pag.is_visible("#totem-fs-atalho")

            resultados["4. objeto exposto"] = pag.evaluate(
                "() => typeof window.KronusTelaCheia === 'object'")
            resultados["5. sem erro de JS"] = not erros
            if erros:
                print("ERROS:", erros)
            nav.close()
    finally:
        srv.terminate(); srv.wait(timeout=10)

    for k, v in resultados.items():
        print(f"   {k:28s}: {v}")
    ok = all(resultados.values())
    print("\nO atalho de tela cheia continua disponivel." if ok
          else "\nFALHOU — o atalho ainda some.")
    return 0 if ok else 1

raise SystemExit(main())
