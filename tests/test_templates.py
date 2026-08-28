"""
Kronus — verificacoes estruturais dos templates.

Coisas que quebram em producao e nenhum teste de view pega, porque a
pagina responde 200 do mesmo jeito — o defeito e o que aparece nela.
"""
import pathlib
import re

from django.test import SimpleTestCase, TestCase

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


class CarimboDeVersaoTests(TestCase):
    """
    O CSS e servido de uma URL fixa com `Cache-Control: immutable`. Sem o
    carimbo `?v=`, o navegador guarda o arquivo por trinta dias e nao
    revalida — foi o que fez o site aparecer sem estilo e o PWA parar de
    atualizar depois de um deploy.
    """

    def test_css_sai_com_carimbo_de_versao(self):
        from django.template import Context, Template

        html = Template(
            "{% load kronus_tags %}{% estatico 'css/main.css' %}"
        ).render(Context({}))
        self.assertIn("?v=", html, "o CSS precisa sair com carimbo de versao")

    def test_carimbo_e_estavel_dentro_do_mesmo_deploy(self):
        from apps.core.versao import versao_dos_estaticos

        self.assertEqual(versao_dos_estaticos(), versao_dos_estaticos())

    def test_service_worker_carrega_a_versao_do_deploy(self):
        from apps.core.versao import versao_dos_estaticos

        resposta = self.client.get("/sw.js")
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.content.decode()
        self.assertIn(versao_dos_estaticos(), corpo,
                      "a chave de cache do SW precisa mudar a cada deploy")
        # `@never_cache` acrescenta no-store/private por cima; o que
        # importa e que o proprio SW nunca seja servido do cache.
        self.assertIn("no-cache", resposta["Cache-Control"])


class PoliticaDeSegurancaTests(SimpleTestCase):
    """
    A CSP de producao precisa permitir o que o front realmente usa.

    Este defeito e invisivel em desenvolvimento: la nao ha CSP, entao
    tudo funciona. Em producao o Alpine carregava, removia o `x-cloak` e
    parava — deixando todo painel escondido permanentemente aberto e
    surdo a cliques.
    """

    @staticmethod
    def _script_src():
        """
        Le a diretiva do arquivo em vez de importar o modulo: importar
        `config.settings.production` exige o `.env` da VPS e estouraria
        `ImproperlyConfigured` na maquina de quem roda os testes.
        """
        fonte = (RAIZ / "config" / "settings" / "production.py").read_text(encoding="utf-8")
        trecho = fonte.split("CSP_SCRIPT_SRC", 1)[1].split(")", 1)[0]
        return trecho

    def test_csp_de_producao_permite_o_que_o_alpine_exige(self):
        base = RAIZ / "templates" / "base.html"
        usa_alpine = "alpinejs" in base.read_text(encoding="utf-8")
        if not usa_alpine:
            self.skipTest("base.html nao carrega mais o Alpine")

        self.assertIn(
            "'unsafe-eval'", self._script_src(),
            "o Alpine avalia expressoes com new Function(); sem "
            "'unsafe-eval' na CSP toda diretiva dele morre em producao",
        )

    def test_cdns_carregados_estao_liberados_na_csp(self):
        base = (RAIZ / "templates" / "base.html").read_text(encoding="utf-8")
        for host in re.findall(r'src="https://([^/"]+)', base):
            self.assertIn(
                host, self._script_src(),
                f"base.html carrega script de {host}, que a CSP bloqueia",
            )


class ArgumentoDeFiltroTests(SimpleTestCase):
    """
    `{{ a.b|default:x.y }}` derruba a pagina quando `x` e None.

    O Django engole a falha de lookup na *variavel* principal, mas nao no
    *argumento* do filtro: ali a `VariableDoesNotExist` sobe e vira 500.
    Foi o que quebrou a tela de auditoria — um log sem cliente vinculado
    bastava. `{% firstof %}` faz a mesma coisa sem estourar.
    """

    PADRAO = re.compile(r"\|\s*default(?:_if_none)?\s*:\s*[\w]+\.[\w.]+")

    def test_nenhum_filtro_default_recebe_variavel_com_ponto(self):
        ofensores = []
        for caminho in RAIZ.rglob("*.html"):
            if "node_modules" in caminho.parts or ".venv" in caminho.parts:
                continue
            for numero, linha in enumerate(
                caminho.read_text(encoding="utf-8").splitlines(), 1
            ):
                if self.PADRAO.search(linha):
                    ofensores.append(f"{caminho.relative_to(RAIZ)}:{numero}")

        self.assertEqual(
            ofensores, [],
            "argumento de filtro com lookup encadeado vira 500 quando o "
            "objeto e None. Use {% firstof a b %}. Ocorrencias:\n  "
            + "\n  ".join(ofensores),
        )


class JargaoInternoTests(SimpleTestCase):
    """
    `help_text` e `verbose_name` aparecem na tela do usuario. Referencias
    ao documento de planejamento ("Regra 6 da Seção 14") nao dizem nada a
    quem opera o sistema — e passam a impressao de rascunho.
    """

    PADRAO = re.compile(
        r"(Seção|Secao|Regra|regra)\s+\d+[^\"']{0,40}(do plano|da Seção|da Secao)"
    )

    def test_nenhum_texto_visivel_cita_o_documento_de_planejamento(self):
        ofensores = []
        for caminho in (RAIZ / "apps").rglob("*.py"):
            if "migrations" in caminho.parts:
                continue
            for numero, linha in enumerate(
                caminho.read_text(encoding="utf-8").splitlines(), 1
            ):
                if "help_text" not in linha and "verbose_name" not in linha:
                    continue
                if self.PADRAO.search(linha):
                    ofensores.append(f"{caminho.relative_to(RAIZ)}:{numero}")

        self.assertEqual(
            ofensores, [],
            "texto visivel citando o documento de planejamento:\n  "
            + "\n  ".join(ofensores),
        )


class LarguraEmCelularTests(SimpleTestCase):
    """
    Item de grade ou flex nasce com `min-width: auto` e nao encolhe
    abaixo da largura do conteudo. Sem `min-width: 0` no `.card`, a
    tabela empurrava o card, o card empurrava a grade, e o navegador
    alargava o viewport de 390 para 465 — a pagina inteira rolava de
    lado no celular, inclusive o convite de instalacao, que acompanha a
    largura da janela.
    """

    def test_card_pode_encolher(self):
        css = (RAIZ / "static" / "css" / "kronus-design-system.css").read_text(
            encoding="utf-8"
        )
        bloco = css.split(".card {", 1)[1].split("}", 1)[0]
        self.assertIn(
            "min-width: 0", bloco,
            "sem `min-width: 0` no .card, toda tabela larga volta a "
            "empurrar a pagina de lado no celular",
        )


class TabelaResponsivaTests(SimpleTestCase):
    """
    Tabela de seis colunas numa tela de 390px rola por dentro do card,
    mas nada indica isso — e as colunas que somem sao as ultimas, onde
    ficam status e acoes. O usuario de celular ve nome e documento e
    conclui que a tela nao tem o resto.
    """

    LISTAS = [
        "apps/master/templates/master/clientes/lista.html",
        "apps/master/templates/master/empresas/lista.html",
        "apps/master/templates/master/saas/usuarios.html",
        "apps/master/templates/master/saas/auditoria.html",
        "apps/master/templates/master/saas/assinaturas.html",
        "apps/master/templates/master/totens/lista.html",
        "apps/master/templates/master/comercial/demonstracoes.html",
        "apps/rh/templates/rh/dados/qualidade_facial.html",
        "apps/rh/templates/rh/colaboradores/lista.html",
    ]

    def test_as_listas_usam_o_padrao_responsivo(self):
        faltando = [
            caminho for caminho in self.LISTAS
            if "tabela-responsiva" not in (RAIZ / caminho).read_text(encoding="utf-8")
        ]
        self.assertEqual(faltando, [], f"listas sem o padrão: {faltando}")

    def test_as_celulas_tem_rotulo(self):
        """
        Com o `<thead>` escondido, valor sem rótulo perde o significado:
        "2/3" sozinho não diz que são empresas.
        """
        sem_rotulo = []
        for caminho in self.LISTAS:
            texto = (RAIZ / caminho).read_text(encoding="utf-8")
            if "data-rotulo" not in texto:
                sem_rotulo.append(caminho)
        self.assertEqual(sem_rotulo, [])

    def test_a_regra_css_existe(self):
        css = (RAIZ / "static" / "css" / "kronus-design-system.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".tabela-responsiva", css)
        self.assertIn("data-rotulo", css)
