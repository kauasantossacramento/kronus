"""
Kronus — verificacoes estruturais dos templates.

Coisas que quebram em producao e nenhum teste de view pega, porque a
pagina responde 200 do mesmo jeito — o defeito e o que aparece nela.
"""
import pathlib
import re

from django.test import SimpleTestCase

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def templates():
    """Todos os .html do projeto, fora de dependencias."""
    encontrados = list((RAIZ / "templates").rglob("*.html"))
    encontrados += list((RAIZ / "apps").rglob("templates/**/*.html"))
    return encontrados


class ComentariosTests(SimpleTestCase):
    """
    O `{# #}` do Django e **de uma linha so**.

    Aberto numa linha e fechado em outra, ele nao e comentario: o Django
    renderiza o texto inteiro na pagina. Ja aconteceu duas vezes neste
    projeto — uma delas foi parar na tela do usuario, explicando um bug
    do dropdown para quem so queria abrir o menu.

    Para comentario de varias linhas existe `{% comment %}`.
    """

    def test_nenhum_comentario_de_uma_linha_atravessa_linhas(self):
        vazando = []
        for caminho in templates():
            for numero, linha in enumerate(
                caminho.read_text(encoding="utf-8").split("\n"), 1
            ):
                if "{#" in linha and "#}" not in linha:
                    relativo = caminho.relative_to(RAIZ)
                    vazando.append(f"{relativo}:{numero}")

        self.assertEqual(
            vazando, [],
            "Comentario {# #} aberto e nao fechado na mesma linha — o texto "
            "vai renderizado para a tela. Use {% comment %}...{% endcomment %} "
            "para varias linhas. Ocorrencias:\n  " + "\n  ".join(vazando),
        )


class VocabularioTests(SimpleTestCase):
    """
    O cliente nao le o nosso plano de desenvolvimento.

    Referencias a "Secao 8.4", "Fase 3" e afins sao conversa interna: na
    tela do usuario elas nao informam nada e ainda expoem como o produto
    foi construido. Comentarios de codigo podem cita-las a vontade — o
    que este teste proibe e o texto que chega ao navegador.
    """

    #: Padroes que nao podem aparecer em conteudo visivel.
    PROIBIDOS = [
        (re.compile(r"Se[çc][ãa]o\s+\d+(\.\d+)?\s+do\s+plano", re.I), "referencia a secao do plano"),
        (re.compile(r"\bFase\s+[1-7]\b", re.I), "referencia a fase de desenvolvimento"),
    ]

    @staticmethod
    def _sem_comentarios(texto: str) -> str:
        """Remove comentarios de template e de HTML antes de avaliar."""
        texto = re.sub(r"\{#.*?#\}", " ", texto, flags=re.S)
        texto = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", " ", texto, flags=re.S | re.I)
        texto = re.sub(r"<!--.*?-->", " ", texto, flags=re.S)
        # Comentarios de CSS e de JS tambem sao codigo: citar a secao do
        # plano dentro deles e documentacao legitima, nao vazamento.
        texto = re.sub(r"/\*.*?\*/", " ", texto, flags=re.S)
        texto = re.sub(r"^\s*//.*$", " ", texto, flags=re.M)
        return texto

    def test_texto_visivel_nao_cita_o_plano_interno(self):
        vazando = []
        for caminho in templates():
            conteudo = self._sem_comentarios(
                caminho.read_text(encoding="utf-8")
            )
            for padrao, motivo in self.PROIBIDOS:
                for achado in padrao.finditer(conteudo):
                    relativo = caminho.relative_to(RAIZ)
                    vazando.append(f"{relativo}: {achado.group(0)!r} ({motivo})")

        self.assertEqual(
            vazando, [],
            "Texto interno chegando ao usuario final:\n  " + "\n  ".join(vazando),
        )
