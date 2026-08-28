"""Confere que tudo o que o Service Worker promete guardar existe de fato."""
import json, re, subprocess, sys, time
RAIZ = r"C:\Users\KS TEC\kronus"
PORTA = 8903

PREPARO = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()
from apps.totem.models import Totem
print(json.dumps({{"token": Totem.objects.filter(ativo=True).first().token_acesso}}))
'''

s = subprocess.run([sys.executable, "-c", PREPARO.format(raiz=RAIZ)],
                   cwd=RAIZ, capture_output=True, text=True)
token = json.loads([l for l in s.stdout.splitlines() if l.startswith("{")][-1])["token"]

srv = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{PORTA}",
                        "--noreload", "--settings=config.settings.development"],
                       cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(5)
import urllib.request
try:
    base = f"http://127.0.0.1:{PORTA}"
    sw = urllib.request.urlopen(f"{base}/totem/sw.js").read().decode()
    urls = re.findall(r"'(/[^']+)'", sw)
    # `/totem/offline/` aparece duas vezes: na lista e no fallback de
    # navegacao. E a mesma pagina, e conta uma vez.
    urls = sorted({u for u in urls
                   if u.startswith("/static/") or u.startswith("/totem/")})
    ruins = []
    print(f"   {len(urls)} arquivos na lista do Service Worker")
    for u in urls:
        try:
            r = urllib.request.urlopen(base + u)
            if r.status != 200 or not r.length:
                ruins.append(f"{u} -> {r.status}")
        except Exception as e:
            ruins.append(f"{u} -> {e}")
    sem_carimbo = [u for u in urls if "?v=" not in u]
    print(f"   sem carimbo: {sem_carimbo}")
    carimbados = [u for u in urls if "?v=" in u]
    print(f"   com carimbo de versao: {len(carimbados)}/{len(urls)}")
    print(f"   inacessiveis: {ruins or 'nenhum'}")
    # A pagina offline e servida por rota, e nao por arquivo estatico:
    # e a unica sem carimbo, por natureza.
    ok = not ruins and sem_carimbo == ["/totem/offline/"]
    print("\nO Service Worker guarda o que promete." if ok else "\nFALHOU.")
finally:
    srv.terminate(); srv.wait(timeout=10)
raise SystemExit(0 if ok else 1)
