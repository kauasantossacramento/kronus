"""A logica do disparo automatico, exercitada no navegador.

Nao ha rosto de verdade numa camera falsa, entao o detector e
substituido por um dublê: assim da para provar a DECISAO — quando
dispara, quando espera pela luz, quando desiste de esperar — que e o que
foi escrito agora.
"""
import json, subprocess, sys, time
RAIZ = r"C:\Users\KS TEC\kronus"
PORTA = 8913

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
plano,_ = Plano.objects.get_or_create(slug="pauto", defaults=dict(nome="PAuto", max_totems=5, max_colaboradores=50))
cli,_ = Cliente.objects.get_or_create(cnpj="27865757000102",
    defaults=dict(razao_social="Prova Auto", plano=plano, email_contato="pa@x.test"))
emp,_ = Empresa.objects.get_or_create(cnpj="33000167000101",
    defaults=dict(cliente=cli, razao_social="Prova Auto"))
tot,_ = Totem.objects.get_or_create(empresa=emp, apelido="Prova auto", defaults=dict(ativo=True))
Colaborador.objects.get_or_create(cpf="39053344705", empresa=emp, defaults=dict(
    nome_completo="Ana Auto", data_nascimento=date(1990,1,1), data_admissao=date(2024,1,1),
    consentimento_biometrico=True))
cli.cadastro_facial_no_totem = True
cli.save(update_fields=["cadastro_facial_no_totem"])
cli.definir_senha_totem("segredo123")
print(json.dumps({{"token": tot.token_acesso}}))
'''

s = subprocess.run([sys.executable, "-c", PREPARO.format(raiz=RAIZ)], cwd=RAIZ,
                   capture_output=True, text=True)
linhas = [l for l in s.stdout.splitlines() if l.startswith("{")]
if not linhas:
    print(s.stdout); print(s.stderr); raise SystemExit(1)
token = json.loads(linhas[-1])["token"]

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
        import time as _t
        _inicio = _t.time()
        navegou = []
        pag.on("framenavigated",
               lambda f: navegou.append(f"{_t.time()-_inicio:.1f}s {f.url[-40:]}"))
        pag.on("console", lambda m: print("   console:", m.text[:110])
               if "Kronus" in m.text else None)
        pag.goto(f"{base}/totem/{token}/", wait_until="networkidle")
        pag.wait_for_timeout(3000)

        # Dublê do detector: sempre pronto. E contamos as capturas
        # interceptando a chamada, sem gravar nada.
        pag.evaluate("""() => {
          window.__capturas = 0;
          window.__momentos = [];
          window.KronusFaceDetector.modo = 'faceapi';
          window.KronusFaceDetector.detectar = () => Promise.resolve({
            presenca: true, pronto: true, confianca: .9,
            proporcao: .48, motivo: 'ok'
          });
          const M = window.KronusManutencao;
          M._capturarOriginal = M._capturar;
          M._capturar = function () {
            window.__capturas += 1;
            window.__momentos.push(Date.now());
            this._capturando = true;
            // Simula a resposta do servidor, com a pausa entre poses.
            setTimeout(() => {
              this._capturando = false;
              this.pose += 1;
              this._estaveis = 0;
              this._prontoDesde = 0;
              this._liberadoEm = Date.now() + 1200;
            }, 120);
          };
        }""")

        M = "window.KronusManutencao"
        pag.evaluate(f"""() => {{
          const M = {M};
          M.pessoa = {{ id: 1, nome: 'Ana Auto', consentimento: true }};
          M._abrirCaptura();
        }}""")

        pag.wait_for_timeout(2500)
        print("   navegacoes:", navegou)
        r["1. dispara sozinho"] = pag.evaluate("() => window.__capturas >= 1")
        uma = pag.evaluate("() => window.__capturas")

        pag.wait_for_timeout(3500)
        total = pag.evaluate("() => window.__capturas")
        r["2. avanca as poses"] = total > uma

        # Rajada e disparo sem pausa entre poses. O que se mede e o
        # intervalo minimo, e nao a contagem: com a pausa menor, mais
        # fotos em menos tempo e o objetivo, nao o defeito.
        intervalos = pag.evaluate(
            "() => window.__momentos.slice(1).map((m, i) => m - window.__momentos[i])"
        )
        menor = min(intervalos) if intervalos else 9999
        r["3. respeita a pausa entre poses"] = menor >= 1100
        print(f"   capturas: {uma} apos 2,5s · {total} apos 6s")
        print(f"   intervalos entre disparos (ms): {intervalos} · menor {menor}")

        # Luz ruim: espera antes de fotografar assim mesmo.
        pag.evaluate(f"""() => {{
          const M = {M};
          window.__capturas = 0;
          M._medirLuz = () => ({{ boa: false, media: 20, contraste: 5 }});
          M._estaveis = 0; M._prontoDesde = 0; M._liberadoEm = 0;
          M._capturando = false;
        }}""")
        pag.wait_for_timeout(1500)
        r["4. espera por luz melhor"] = pag.evaluate("() => window.__capturas") == 0
        instrucao = pag.locator("#manut-instrucao").inner_text()
        r["5. orienta sobre a luz"] = "luz" in instrucao.lower()
        print(f"   instrucao com pouca luz: {instrucao!r}")

        pag.wait_for_timeout(3000)
        r["6. fotografa assim mesmo"] = pag.evaluate("() => window.__capturas") >= 1
        print(f"   capturas com luz ruim, apos a espera: "
              f"{pag.evaluate('() => window.__capturas')}")

        r["7. sem erro de JS"] = not erros
        if erros: print("   ERROS:", erros[:3])
        nav.close()
finally:
    srv.terminate(); srv.wait(timeout=10)

for k, v in r.items():
    print(f"   {k:28s}: {v}")
raise SystemExit(0 if all(r.values()) else 1)
