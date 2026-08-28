"""
Kronus — captura das telas do sistema para o manual.

Gera um par de imagens por tela (computador e celular) em `docs/prints/`,
a partir do HTML realmente renderizado pelo Django. Capturar do sistema
rodando, e nao montar mockups, garante que o manual envelhece junto com o
produto: quando a tela muda, basta rodar isto de novo.

    python ferramentas/capturar_telas.py

Precisa de `playwright` e do Chromium instalado:

    pip install playwright && playwright install chromium

A execucao tem duas fases em processos separados, de proposito: o
Playwright sincrono e o Django nao convivem no mesmo laco de eventos no
Windows. A primeira fase grava o HTML em disco; a segunda o serve e
fotografa.
"""
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
TRABALHO = os.path.join(RAIZ, ".telas")
DESTINO = os.path.join(RAIZ, "docs", "prints")

#: Telas do manual, por papel. A ordem e a da narrativa do manual, nao a
#: do menu — o leitor comeca pelo que faz primeiro.
ROTEIRO = {
    "master": [
        ("master:dashboard", "Painel da KS TEC"),
        ("master:cliente_lista", "Clientes"),
        ("master:cliente_criar", "Novo cliente"),
        ("master:empresa_lista", "Empresas"),
        ("master:plano_lista", "Planos"),
        ("master:totem_lista", "Totens"),
        ("master:comercial_config", "Configuração comercial"),
        ("master:comercial_demos", "Demonstrações"),
        ("master:assinaturas", "Assinaturas"),
        ("master:custos", "Custos e margem"),
        ("master:gateway", "Gateway de pagamento"),
        ("master:usuarios", "Usuários"),
        ("master:usuario_criar", "Novo usuário"),
        ("master:auditoria", "Auditoria"),
        ("master:log_lista", "Logs de acesso"),
    ],
    "rh": [
        ("rh:dashboard", "Painel do RH"),
        ("rh:colaborador_lista", "Colaboradores"),
        ("rh:colaborador_criar", "Novo colaborador"),
        ("rh:qualidade_facial", "Qualidade do reconhecimento"),
        ("rh:equipamentos", "Equipamentos"),
        ("rh:personalizacao", "Personalização"),
        ("rh:slides_totem", "Slides do totem"),
        ("rh:empresa", "Configurações da empresa"),
        ("rh:webhooks", "Webhooks"),
        ("rh:integracao", "Integração"),
    ],
    "colaborador": [
        ("ponto:registrar", "Registrar ponto"),
        ("ponto:meus_pontos", "Meus pontos"),
        ("ponto:meus_espelhos", "Meus espelhos"),
    ],
    "publico": [
        ("landing:index", "Página inicial"),
        ("accounts:login", "Entrar"),
    ],
}


# ══════════════════════════════════════════════════════════════
# Fase 1 — renderizar o HTML
# ══════════════════════════════════════════════════════════════
FASE_1 = r'''
import json, os, sys, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from django.test import Client
from django.urls import reverse, NoReverseMatch
from apps.accounts.models import CustomUser
from apps.core.constants import TipoUsuario

TRABALHO = r"{trabalho}"
os.makedirs(TRABALHO, exist_ok=True)
ROTEIRO = json.loads(r"""{roteiro}""")

TIPOS = {{
    "master": TipoUsuario.MASTER,
    "rh": TipoUsuario.RH,
    "colaborador": TipoUsuario.COLABORADOR,
}}

indice = []
for papel, telas in ROTEIRO.items():
    cliente = Client()
    if papel != "publico":
        usuario = CustomUser.objects.filter(
            tipo=TIPOS[papel], is_active=True
        ).first()
        if usuario is None:
            print("!! sem usuario de exemplo para", papel)
            continue
        cliente.force_login(usuario)

    for rota, titulo in telas:
        try:
            url = reverse(rota)
        except NoReverseMatch:
            print("   rota inexistente:", rota)
            continue
        try:
            resposta = cliente.get(url, follow=True)
        except Exception as erro:
            print("   erro em", rota, "->", type(erro).__name__)
            continue
        if resposta.status_code != 200:
            print("   ", rota, "HTTP", resposta.status_code)
            continue
        arquivo = papel + "__" + rota.replace(":", "_") + ".html"
        with open(os.path.join(TRABALHO, arquivo), "w", encoding="utf-8") as f:
            f.write(resposta.content.decode())
        indice.append({{"papel": papel, "rota": rota, "titulo": titulo,
                        "arquivo": arquivo}})

with open(os.path.join(TRABALHO, "indice.json"), "w", encoding="utf-8") as f:
    json.dump(indice, f, ensure_ascii=False, indent=1)
print(len(indice), "telas renderizadas")
'''


# ══════════════════════════════════════════════════════════════
# Fase 2 — fotografar
# ══════════════════════════════════════════════════════════════
FASE_2 = r'''
import functools, http.server, json, os, socketserver, threading
from playwright.sync_api import sync_playwright

TRABALHO = r"{trabalho}"
DESTINO = r"{destino}"
os.makedirs(DESTINO, exist_ok=True)

class Servidor(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

srv = socketserver.TCPServer(
    ("127.0.0.1", 8830), functools.partial(Servidor, directory=TRABALHO)
)
threading.Thread(target=srv.serve_forever, daemon=True).start()

indice = json.load(open(os.path.join(TRABALHO, "indice.json"), encoding="utf-8"))

with sync_playwright() as p:
    nav = p.chromium.launch()
    # A ajuda abre sozinha na primeira visita e cobriria a tela na foto.
    # Marcar como vista antes de navegar mantem a captura limpa.
    contexto_pc = nav.new_context(viewport={{"width": 1440, "height": 900}})
    contexto_cel = nav.new_context(
        viewport={{"width": 390, "height": 844}}, is_mobile=True, has_touch=True
    )
    for ctx in (contexto_pc, contexto_cel):
        ctx.add_init_script(
            # Marca a ajuda como ja vista: ela abre sozinha na primeira
            # visita e tamparia justamente a tela que se quer fotografar.
            "try {{ localStorage.setItem('kronus-ajuda-vista-todas', '1'); "
            "const p = localStorage.setItem.bind(localStorage); }} catch (e) {{}}"
        )

    pc = contexto_pc.new_page()
    cel = contexto_cel.new_page()

    for item in indice:
        base = item["papel"] + "__" + item["rota"].replace(":", "_")
        url = "http://127.0.0.1:8830/" + item["arquivo"]
        for pagina, sufixo in ((pc, "pc"), (cel, "cel")):
            pagina.goto(url)
            pagina.wait_for_timeout(1100)
            # Fecha a ajuda, caso tenha aberto, para nao tampar a tela.
            pagina.evaluate(
                "() => {{ const m = document.getElementById('ajuda-modal');"
                " if (m) m.hidden = true;"
                " const t = document.getElementById('ajuda-tour-camada');"
                " if (t) t.hidden = true; }}"
            )
            pagina.wait_for_timeout(150)
            pagina.screenshot(
                path=os.path.join(DESTINO, base + "_" + sufixo + ".png"),
                full_page=True,
            )
        print("  ", base)
    nav.close()
srv.shutdown()
print(len(indice) * 2, "imagens geradas em docs/prints/")
'''


def copiar_estaticos() -> None:
    """
    Leva CSS, imagens e uploads para junto do HTML.

    O HTML capturado aponta para `/static/` e `/media/`. Sem esses
    arquivos ao lado, o servidor de captura devolve 404 e a foto sai sem
    estilo nenhum — uma tela desmontada, que num manual e pior do que
    nenhuma imagem.
    """
    import shutil

    for pasta in ("static", "media"):
        origem = os.path.join(RAIZ, pasta)
        if not os.path.isdir(origem):
            continue
        destino = os.path.join(TRABALHO, pasta)
        shutil.rmtree(destino, ignore_errors=True)
        shutil.copytree(origem, destino)
    print("   estáticos copiados")


def rodar(codigo: str, rotulo: str) -> None:
    print(f"\n== {rotulo} ==")
    processo = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, text=True
    )
    if processo.returncode != 0:
        raise SystemExit(f"falha em {rotulo}")


def otimizar() -> None:
    """
    Reduz o tamanho das imagens sem perder legibilidade.

    Captura de pagina inteira gera arquivos grandes, e eles vao para o
    repositorio. Captura de interface tem poucas cores e grandes areas
    chapadas: quantizar para uma paleta de 256 corta o peso a uma fracao
    sem diferenca visivel no texto — o que uma conversao para RGB, ao
    contrario, chega a **aumentar**.
    """
    from PIL import Image

    total_antes = total_depois = 0
    for nome in sorted(os.listdir(DESTINO)):
        if not nome.endswith(".png"):
            continue
        caminho = os.path.join(DESTINO, nome)
        total_antes += os.path.getsize(caminho)
        with Image.open(caminho) as img:
            img = img.convert("RGB")
            largura = 1200 if nome.endswith("_pc.png") else 400
            if img.width > largura:
                altura = round(img.height * largura / img.width)
                img = img.resize((largura, altura), Image.LANCZOS)
            img.quantize(colors=256, method=Image.MEDIANCUT).save(
                caminho, "PNG", optimize=True
            )
        total_depois += os.path.getsize(caminho)

    print(f"\npeso: {total_antes/1e6:.1f} MB -> {total_depois/1e6:.1f} MB")


if __name__ == "__main__":
    roteiro = json.dumps(ROTEIRO, ensure_ascii=False)
    rodar(
        FASE_1.format(raiz=RAIZ, trabalho=TRABALHO, roteiro=roteiro),
        "renderizando as telas",
    )
    copiar_estaticos()
    rodar(FASE_2.format(trabalho=TRABALHO, destino=DESTINO), "fotografando")
    otimizar()
