"""
Kronus — mede a acuracia do reconhecimento facial com dados reais.

Nao e teste unitario e nao usa vetor sintetico: le as fotos de cadastro
gravadas, gera embeddings pelo motor de producao e mede as distancias
que o totem realmente enfrenta.

Responde tres perguntas.

1. As amostras de cada pessoa combinam entre si? Uma captura solta no
   meio das outras e contaminacao, e como vale a menor distancia ela
   vira porta aberta para quem se pareca com ela.

2. Pessoas diferentes ficam longe? E a margem que separa reconhecer de
   trocar um pelo outro. Exige duas ou mais pessoas cadastradas.

3. **Proximidade**: ate onde o rosto pode estar da camera e ainda ser
   reconhecido? Distancia maior significa menos pixels no rosto, e
   menos pixels significa embedding mais pobre. O ensaio reduz a
   resolucao da foto para emular o afastamento e mede quanto a
   distancia sobe.

    python manage.py shell -c "exec(open('ferramentas/mede_acuracia.py').read())"

ou, direto:

    python ferramentas/mede_acuracia.py
"""
import io
import itertools
import os
import sys

if __name__ == "__main__" and not os.environ.get("DJANGO_SETTINGS_MODULE"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.development"
    import django

    django.setup()

import numpy as np
from django.conf import settings
from PIL import Image

from apps.facial.models import FaceRegistro
from apps.facial.services import FaceRecognitionService

#: Larguras de rosto no quadro, em fracao da largura total, e a distancia
#: aproximada correspondente. Os dois extremos sao os limites que o
#: proprio totem aplica antes de enviar (LARGURA_MINIMA/MAXIMA_ROSTO em
#: face-detector.js): fora deles a imagem nem chega ao servidor, entao
#: medir alem disso descreveria uma situacao que nao acontece.
PROXIMIDADES = [
    (0.60, "~20 cm — bem perto"),
    (0.45, "~30 cm"),
    (0.32, "~40 cm"),
    (0.24, "~50 cm"),
    (0.18, "~60 cm — limite que o totem aceita"),
]

#: Referencia: com que largura de rosto a foto de cadastro foi feita.
#: As capturas do roteiro pedem o rosto preenchendo boa parte da moldura.
LARGURA_DE_CADASTRO = 0.60


def distancia(a, b) -> float:
    na = float(np.linalg.norm(a)) or 1e-9
    nb = float(np.linalg.norm(b)) or 1e-9
    return 1.0 - float(a @ b) / (na * nb)


def reduzir(dados: bytes, fracao: float) -> bytes:
    """
    Emula o afastamento da camera.

    Afastar-se nao borra a imagem: reduz quantos pixels sobram sobre o
    rosto. Reduzir e voltar ao tamanho original reproduz exatamente essa
    perda — o quadro continua do mesmo tamanho, e o rosto dentro dele
    passa a ter menos informacao.
    """
    imagem = Image.open(io.BytesIO(dados)).convert("RGB")
    largura, altura = imagem.size
    menor = imagem.resize(
        (max(int(largura * fracao), 16), max(int(altura * fracao), 16)),
        Image.LANCZOS,
    )
    de_volta = menor.resize((largura, altura), Image.LANCZOS)
    buffer = io.BytesIO()
    de_volta.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _linha(titulo):
    print()
    print(titulo)
    print("-" * len(titulo))


def main() -> int:
    servico = FaceRecognitionService()
    limiar = settings.FACE_RECOGNITION_THRESHOLD
    print(f"motor: {type(servico.provedor).__name__} · modelo: "
          f"{settings.DEEPFACE_MODEL} · limiar: {limiar} · "
          f"margem: {settings.FACE_MARGEM_MINIMA}")

    registros = list(
        FaceRegistro.objects.filter(ativo=True).select_related("colaborador")
    )
    if not registros:
        print("Nenhuma amostra ativa. Cadastre pelo menos uma pessoa.")
        return 1

    por_pessoa = {}
    for registro in registros:
        por_pessoa.setdefault(registro.colaborador, []).append(registro)

    # ── 1. Coerencia interna ──────────────────────────────────
    _linha("1. As amostras de cada pessoa combinam entre si?")
    vetores_por_pessoa = {}
    for pessoa, amostras in por_pessoa.items():
        vetores = [r.obter_embedding() for r in amostras]
        vetores_por_pessoa[pessoa] = vetores
        if len(vetores) < 2:
            print(f"  {pessoa.nome_exibicao}: 1 amostra — nada a comparar")
            continue
        pares = [distancia(a, b) for a, b in itertools.combinations(vetores, 2)]
        aceitas = servico._amostras_coerentes(vetores)
        descartadas = len(vetores) - len(aceitas)
        print(
            f"  {pessoa.nome_exibicao}: {len(vetores)} amostras · "
            f"entre si {min(pares):.3f} a {max(pares):.3f}"
            + (f" · {descartadas} descartada(s) por divergencia" if descartadas
               else " · todas coerentes")
        )

    # ── 2. Separacao entre pessoas ────────────────────────────
    _linha("2. Pessoas diferentes ficam longe umas das outras?")
    pessoas = list(vetores_por_pessoa)
    if len(pessoas) < 2:
        print("  So ha uma pessoa cadastrada.")
        print("  Sem uma segunda, NAO da para medir falso positivo — que e")
        print("  o erro caro. Cadastre outra pessoa e rode de novo.")
    else:
        pior = None
        for a, b in itertools.combinations(pessoas, 2):
            entre = min(
                distancia(x, y)
                for x in vetores_por_pessoa[a] for y in vetores_por_pessoa[b]
            )
            marca = "  <-- ABAIXO DO LIMIAR" if entre < limiar else ""
            print(f"  {a.nome_exibicao} x {b.nome_exibicao}: {entre:.3f}{marca}")
            if pior is None or entre < pior:
                pior = entre
        folga = pior - limiar
        print(f"\n  Par mais proximo: {pior:.3f} · folga sobre o limiar: {folga:+.3f}")
        if folga <= 0:
            print("  RISCO: duas pessoas cadastradas se confundem.")

    # ── 3. Proximidade ────────────────────────────────────────
    _linha("3. Ate que distancia o rosto ainda e reconhecido?")
    print("  Reduzindo a resolucao do rosto para emular o afastamento.")
    print("  A distancia mostrada e ate a propria galeria da pessoa —")
    print("  acima do limiar, a pessoa deixaria de ser reconhecida.\n")

    com_foto = [r for r in registros if r.imagem]
    if not com_foto:
        print("  As fotos nao foram guardadas (a empresa apaga apos o encoding).")
        print("  Sem elas nao da para reamostrar; o ensaio precisa da imagem.")
        return 0

    referencia = com_foto[0]
    pessoa = referencia.colaborador
    galeria = servico._amostras_coerentes(vetores_por_pessoa[pessoa])
    print(f"  Pessoa: {pessoa.nome_exibicao} · foto: {os.path.basename(referencia.imagem.name)}")

    try:
        referencia.imagem.open("rb")
        original = referencia.imagem.read()
        referencia.imagem.close()
    except Exception as erro:  # pragma: no cover
        print(f"  Nao foi possivel ler a foto: {erro}")
        return 1

    print()
    print(f"  {'situacao':<34} {'dist. a galeria':>16}   veredito")
    for largura, rotulo in PROXIMIDADES:
        fracao = min(largura / LARGURA_DE_CADASTRO, 1.0)
        try:
            vetor = servico.provedor.gerar_embedding(reduzir(original, fracao))
        except Exception as erro:
            print(f"  {rotulo:<34} {'—':>16}   rosto nao detectado ({erro})")
            continue
        perto = min(distancia(vetor, v) for v in galeria)
        veredito = "reconhece" if perto < limiar else "NAO reconhece"
        print(f"  {rotulo:<34} {perto:>16.3f}   {veredito}")

    print()
    print("  Leitura: a foto de cadastro comparada consigo mesma da ~0, e o")
    print("  numero cresce conforme o rosto perde pixels. O ponto em que")
    print("  passa do limiar e a distancia maxima util deste cadastro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
