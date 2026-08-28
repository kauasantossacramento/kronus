"""
Prova: o totem detecta rosto sem depender de CDN, e avisa quando nao da.

A causa do "nao reconhece ninguem" era silenciosa por construcao: o
face-api.js vinha de um CDN, e a sua ausencia levava a um modo que nunca
declara um rosto pronto — logo, nunca envia imagem ao servidor. Nada na
tela dizia isso.

    python ferramentas/prova_detector.py
"""
import json, subprocess, sys, time
RAIZ = r"C:\Users\KS TEC\kronus"
PORTA = 8902

PREPARO = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()
from apps.totem.models import Totem
print(json.dumps({{"token": Totem.objects.filter(ativo=True).first().token_acesso}}))
'''

def main():
    s = subprocess.run([sys.executable, "-c", PREPARO.format(raiz=RAIZ)],
                       cwd=RAIZ, capture_output=True, text=True)
    linhas = [l for l in s.stdout.splitlines() if l.startswith("{")]
    if not linhas:
        print(s.stdout, s.stderr); return 1
    token = json.loads(linhas[-1])["token"]
    url = f"http://127.0.0.1:{PORTA}/totem/{token}/"

    srv = subprocess.Popen([sys.executable, "manage.py", "runserver",
                            f"127.0.0.1:{PORTA}", "--noreload",
                            "--settings=config.settings.development"],
                           cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    from playwright.sync_api import sync_playwright
    r = {}
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch(args=["--use-fake-ui-for-media-stream",
                                          "--use-fake-device-for-media-stream"])

            # -- 1. caminho normal --------------------------------
            ctx = nav.new_context(permissions=["camera"])
            pag = ctx.new_page()
            externos = []
            # So script: fonte e imagem externas degradam sozinhas
            # (texto cai na fonte do sistema), enquanto um script que nao
            # chega leva junto a funcao que ele implementa.
            pag.on("request", lambda req: externos.append(req.url)
                   if req.resource_type == "script"
                   and "127.0.0.1" not in req.url
                   and req.url.startswith("http") else None)
            pag.goto(url, wait_until="networkidle")
            pag.wait_for_timeout(4000)
            r["1. face-api presente"] = pag.evaluate("() => typeof faceapi !== 'undefined'")
            r["2. modo do detector"] = pag.evaluate(
                "() => window.KronusFaceDetector && window.KronusFaceDetector.modo")
            r["3. nenhum script externo"] = not externos
            if externos:
                print("   EXTERNOS:", externos[:5])
            r["4. faixa de aviso oculta"] = not pag.is_visible("#totem-degradado")
            ctx.close()

            # -- 2. com o face-api bloqueado ----------------------
            ctx2 = nav.new_context(permissions=["camera"])
            pag2 = ctx2.new_page()
            pag2.route("**/face-api.min.js*", lambda rota: rota.abort())
            hb = []
            def espiar(rota):
                dados = rota.request.post_data
                if dados:
                    hb.append(dados)
                rota.continue_()
            pag2.route("**/heartbeat/", espiar)
            pag2.goto(url, wait_until="networkidle")
            # o detector espera ate 15s antes de desistir
            pag2.wait_for_timeout(19000)
            r["5. faixa aparece"] = pag2.is_visible("#totem-degradado")
            r["6. heartbeat leva o motivo"] = any("degradado" in d for d in hb)
            r["7. totem segue de pe"] = pag2.is_visible("#tela-idle") or pag2.is_visible("#tela-camera")
            ctx2.close()
            nav.close()
    finally:
        srv.terminate(); srv.wait(timeout=10)

    for k, v in r.items():
        print(f"   {k:28s}: {v}")
    esperado = {"2. modo do detector": "faceapi"}
    ok = all(v is True for k, v in r.items() if k not in esperado) \
         and r.get("2. modo do detector") == "faceapi"
    print("\nO totem detecta rosto sem CDN, e avisa quando nao consegue."
          if ok else "\nFALHOU.")
    return 0 if ok else 1

raise SystemExit(main())
