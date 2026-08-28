"""
Kronus — prova do ciclo offline ponta a ponta.

Nao e um teste unitario: sobe o servidor Django de verdade, abre o
navegador, derruba a rede dele, registra a marcacao na fila, restaura a
rede e confere que a batida chegou **ao banco**.

Existe porque a promessa do modo offline e forte demais para ser
verificada so por mock — "a batida feita sem conexao chega ao servidor
quando a conexao voltar". Um teste que simula o `fetch` prova que o
codigo chama o `fetch`; nao prova que a batida sobrevive a uma recarga
da pagina e chega ao banco.

    python ferramentas/prova_offline.py
"""
import json
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
PORTA = 8899

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
from apps.ponto.models import RegistroPonto

plano, _ = Plano.objects.get_or_create(
    slug="prova-offline",
    defaults=dict(nome="Prova offline", max_empresas=2,
                  max_colaboradores=20, max_totems=2, tem_offline=True),
)
cliente, _ = Cliente.objects.get_or_create(
    cnpj="11444777000161",
    defaults=dict(razao_social="Prova Offline LTDA", plano=plano,
                  email_contato="prova@x.test"),
)
empresa, _ = Empresa.objects.get_or_create(
    cnpj="34028316000103",
    defaults=dict(cliente=cliente, razao_social="Prova Offline"),
)
totem, _ = Totem.objects.get_or_create(
    empresa=empresa, apelido="Prova offline", defaults=dict(ativo=True)
)
colaborador, _ = Colaborador.objects.get_or_create(
    cpf="52998224725", empresa=empresa,
    defaults=dict(nome_completo="Ana da Prova",
                  data_nascimento=date(1990, 5, 12),
                  data_admissao=date(2024, 1, 1)),
)
print(json.dumps({{
    "token": totem.token_acesso,
    "colaborador_id": colaborador.pk,
    "antes": RegistroPonto.objects.filter(colaborador=colaborador).count(),
}}))
'''

CONFERENCIA = '''
import os, sys, json, django
sys.path.insert(0, r"{raiz}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.ponto.models import RegistroPonto

registro = RegistroPonto.objects.filter(uuid_offline="{uuid}").first()
iguais = RegistroPonto.objects.filter(uuid_offline="{uuid}").count()
print(json.dumps({{
    "encontrado": registro is not None,
    "marcado_offline": bool(registro and registro.registrado_offline),
    "duplicatas": iguais,
    "nsr": registro.nsr if registro else None,
    "hora_da_marcacao": registro.data_hora.isoformat() if registro else None,
    "hora_da_gravacao": registro.created_at.isoformat() if registro else None,
}}))
'''


def python(codigo: str, rotulo: str) -> dict:
    saida = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True
    )
    linhas = [l for l in saida.stdout.splitlines() if l.startswith("{")]
    if not linhas:
        print(saida.stdout)
        print(saida.stderr)
        raise SystemExit(f"falha em {rotulo}")
    return json.loads(linhas[-1])


def exercitar(dados: dict) -> dict:
    from playwright.sync_api import sync_playwright

    base = f"http://127.0.0.1:{PORTA}"
    configurar = """(cfg) => {
        KronusFilaOffline.configurar({
            urlSincronizar: cfg.base + '/api/v1/totem/sincronizar/',
            urlColaboradores: cfg.base + '/api/v1/totem/colaboradores-offline/',
            token: cfg.token
        });
        return KronusFilaOffline.pendentes().length;
    }"""
    cfg = {"base": base, "token": dados["token"]}

    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context()
        pag = ctx.new_page()
        pag.goto(f"{base}/totem/{dados['token']}/")
        pag.wait_for_timeout(1500)
        pag.evaluate(configurar, cfg)

        print("\n1. Com conexao: baixando a lista de colaboradores")
        baixou = pag.evaluate("() => KronusFilaOffline.atualizarColaboradores()")
        total = pag.evaluate("() => KronusFilaOffline.colaboradores().length")
        print(f"   baixada: {baixou} | {total} colaborador(es) em cache")
        vazou = pag.evaluate(
            "() => JSON.stringify(KronusFilaOffline.colaboradores())"
            ".indexOf('52998224725') >= 0"
        )
        print(f"   CPF em claro no aparelho: {vazou}")

        print("\n2. Derrubando a rede do navegador")
        ctx.set_offline(True)

        print("\n3. Identificando pela lista local, sem conexao")
        achado = pag.evaluate(
            "async () => { const c = await KronusFilaOffline"
            ".identificar('529.982.247-25', '1990-05-12'); return c ? c.nome : null; }"
        )
        print(f"   identificado: {achado}")

        print("\n4. Registrando a marcacao na fila")
        marcacao = pag.evaluate(
            "(id) => KronusFilaOffline.registrar(id, 'entrada')",
            dados["colaborador_id"],
        )
        print(f"   uuid: {marcacao['uuid']}")
        print(f"   na fila: {pag.evaluate('() => KronusFilaOffline.pendentes().length')}")

        print("\n5. Tentando enviar ainda sem conexao")
        tentativa = pag.evaluate("() => KronusFilaOffline.sincronizar()")
        print(f"   enviadas: {tentativa['enviadas']} | erro de rede: {tentativa.get('erro')}")
        print(f"   continua na fila: {pag.evaluate('() => KronusFilaOffline.pendentes().length')}")

        print("\n6. Recarregando a pagina (o aparelho podia ter reiniciado)")
        ctx.set_offline(False)
        pag.goto(f"{base}/totem/{dados['token']}/")
        pag.wait_for_timeout(1200)
        sobreviveu = pag.evaluate(configurar, cfg)
        print(f"   fila sobreviveu: {sobreviveu} pendente(s)")

        print("\n7. Conexao de volta: sincronizando")
        envio = pag.evaluate("() => KronusFilaOffline.sincronizar()")
        recusadas = pag.evaluate(
            "() => KronusFilaOffline.recusadas().map(m => m.motivo)"
        )
        print(f"   enviadas: {envio['enviadas']} | restante: "
              f"{pag.evaluate('() => KronusFilaOffline.pendentes().length')}")
        if recusadas:
            print(f"   RECUSADAS: {recusadas}")

        print("\n8. Reenviando a mesma marcacao (a resposta podia ter se perdido)")
        pag.evaluate(
            "(m) => { const f = JSON.parse("
            "localStorage.getItem('kronus-fila-offline') || '[]');"
            " f.push(m); localStorage.setItem("
            "'kronus-fila-offline', JSON.stringify(f)); }",
            marcacao,
        )
        reenvio = pag.evaluate("() => KronusFilaOffline.sincronizar()")
        print(f"   reenvio aceito sem duplicar: {reenvio['enviadas']} confirmada(s)")

        nav.close()
    return marcacao


def main() -> int:
    print("== preparando dados ==")
    dados = python(PREPARO.format(raiz=RAIZ), "preparo")
    print(f"   totem e colaborador prontos ({dados['antes']} marcacao(oes) antes)")

    print("\n== subindo o servidor ==")
    servidor = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", f"127.0.0.1:{PORTA}",
         "--noreload", "--settings=config.settings.development"],
        cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(5)
    try:
        marcacao = exercitar(dados)
    finally:
        servidor.terminate()
        servidor.wait(timeout=10)

    print("\n== conferindo no banco ==")
    conferido = python(
        CONFERENCIA.format(raiz=RAIZ, uuid=marcacao["uuid"]), "conferencia"
    )
    for chave, valor in conferido.items():
        print(f"   {chave:18s}: {valor}")

    certo = (
        conferido["encontrado"]
        and conferido["marcado_offline"]
        and conferido["duplicatas"] == 1
    )
    print(
        "\nA batida feita sem conexao chegou ao banco, marcada como offline "
        "e sem duplicar."
        if certo else
        "\nA prova FALHOU — a batida nao chegou como deveria."
    )
    return 0 if certo else 1


if __name__ == "__main__":
    raise SystemExit(main())
