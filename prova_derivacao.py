"""Prova que a derivacao do navegador bate com a do servidor."""
import json, os, shutil
from playwright.sync_api import sync_playwright

SC = r"C:\Users\KSTEC~1\AppData\Local\Temp\claude\c--Users-KS-TEC-kronus\e2567f89-1ee7-49dd-b019-d146e5d8e48f\scratchpad"
vetor = json.load(open(os.path.join(SC, "vetor.json")))
shutil.copy("apps/totem/static/totem/js/fila-offline.js", os.path.join(SC, "fila-offline.js"))

with open(os.path.join(SC, "prova.html"), "w", encoding="utf-8") as f:
    f.write("<!doctype html><meta charset=utf-8><script src=fila-offline.js></script>")

import functools, http.server, socketserver, threading
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 8840), functools.partial(H, directory=SC))
threading.Thread(target=srv.serve_forever, daemon=True).start()

with sync_playwright() as p:
    nav = p.chromium.launch()
    pag = nav.new_page()
    pag.goto("http://127.0.0.1:8840/prova.html")
    obtido = pag.evaluate("""async (v) => {
        localStorage.setItem('kronus-offline-sal', JSON.stringify(v.sal));
        localStorage.setItem('kronus-offline-iteracoes', JSON.stringify(v.iteracoes));
        return await KronusFilaOffline._resumo(v.cpf, v.nascimento);
    }""", vetor)
    print("servidor  :", vetor["esperado"])
    print("navegador :", obtido)
    print("CONFEREM  :", obtido == vetor["esperado"])
    nav.close()
srv.shutdown()
