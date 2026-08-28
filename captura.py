import functools, http.server, json, os, socketserver, threading
from playwright.sync_api import sync_playwright

PASTA = r"C:\Users\KSTEC~1\AppData\Local\Temp\claude\c--Users-KS-TEC-kronus\e2567f89-1ee7-49dd-b019-d146e5d8e48f\scratchpad\telas"
SAIDA = os.path.join(PASTA, "prints")
os.makedirs(SAIDA, exist_ok=True)

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 8821), functools.partial(H, directory=PASTA))
threading.Thread(target=srv.serve_forever, daemon=True).start()

indice = json.load(open(os.path.join(PASTA, "indice.json"), encoding="utf-8"))
ALVOS = ["master__master_dashboard", "master__master_cliente_lista",
         "rh__rh_dashboard", "master__master_auditoria"]

with sync_playwright() as p:
    nav = p.chromium.launch()
    cel = nav.new_page(viewport={"width": 390, "height": 900}, is_mobile=True, has_touch=True)
    desk = nav.new_page(viewport={"width": 1440, "height": 900})
    for papel, nome, arq in indice:
        chave = arq.replace(".html", "")
        if chave not in ALVOS:
            continue
        cel.goto(f"http://127.0.0.1:8821/{arq}")
        cel.wait_for_timeout(1000)
        cel.screenshot(path=os.path.join(SAIDA, chave + "_cel.png"), full_page=False)
        desk.goto(f"http://127.0.0.1:8821/{arq}")
        desk.wait_for_timeout(900)
        desk.screenshot(path=os.path.join(SAIDA, chave + "_desk.png"), full_page=False)
        print("capturado:", chave)
    nav.close()
srv.shutdown()
