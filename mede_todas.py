import functools, http.server, json, os, socketserver, threading
from playwright.sync_api import sync_playwright

PASTA = r"C:\Users\KSTEC~1\AppData\Local\Temp\claude\c--Users-KS-TEC-kronus\e2567f89-1ee7-49dd-b019-d146e5d8e48f\scratchpad\telas"
ALVO = 390

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 8820), functools.partial(H, directory=PASTA))
threading.Thread(target=srv.serve_forever, daemon=True).start()

indice = json.load(open(os.path.join(PASTA, "indice.json"), encoding="utf-8"))
DETECTAR = """() => {
    const vw = %d;
    return [...document.querySelectorAll('*')]
      .filter(e => { const r = e.getBoundingClientRect();
                     return r.width > 0 && r.right > vw + 2; })
      .slice(0, 4)
      .map(e => {
        const r = e.getBoundingClientRect();
        const cls = (typeof e.className === 'string' ? e.className : '')
                      .split(' ').filter(Boolean).slice(0, 4).join('.');
        return e.tagName.toLowerCase() + (cls ? '.' + cls : '')
          + ' w=' + Math.round(r.width)
          + ' "' + (e.innerText || '').trim().slice(0, 24).replace(/\n/g,' ') + '"';
      });
}""" % ALVO

with sync_playwright() as p:
    nav = p.chromium.launch()
    pag = nav.new_page(viewport={"width": ALVO, "height": 844}, is_mobile=True, has_touch=True)
    ruins = 0
    for papel, nome, arq in indice:
        pag.goto(f"http://127.0.0.1:8820/{arq}")
        pag.wait_for_timeout(900)
        doc = pag.evaluate("document.documentElement.scrollWidth")
        if doc > ALVO + 1:
            ruins += 1
            print(f"\nVAZA {doc - ALVO:>3}px  {papel}/{nome}")
            for e in pag.evaluate(DETECTAR):
                print("     ", e)
    print(f"\n{len(indice)} telas | {ruins} com vazamento horizontal")
    nav.close()
srv.shutdown()
