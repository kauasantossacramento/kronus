"""
Kronus — nenhum script vem de fora.

Existe por um defeito concreto: o face-api.js era carregado de um CDN
publico, e a sua ausencia levava o detector a um modo degradado que
nunca declara um rosto pronto. O totem seguia bonito, aceitava CPF, e
**nao enviava uma unica imagem ao servidor** — que foi como o
reconhecimento facial ficou parado em producao sem nada acusar.

Um script de terceiro nao e um enfeite que falta: e uma funcao que
desaparece. E o totem, que promete funcionar sem internet, nao pode
buscar fora aquilo de que depende para funcionar.
"""
import pathlib
import re

from django.test import TestCase

RAIZ = pathlib.Path(__file__).resolve().parent.parent

#: Pastas de trabalho, nao de producao.
IGNORADAS = {".telas", "staticfiles", "node_modules", ".venv", "docs"}

SCRIPT_EXTERNO = re.compile(
    r"""<script[^>]*\ssrc\s*=\s*["'](https?:)?//""", re.I
)


def _sob_guarda_de_debug(texto: str, posicao: int) -> bool:
    """
    O script externo esta dentro de um `{% if KRONUS.DEBUG %}`?

    O Tailwind Play e um caso legitimo: existe so em desenvolvimento,
    para dispensar a etapa de build, e em producao o arquivo compilado e
    servido por nos. O que nao pode e um script de terceiro alcancar o
    equipamento do cliente.
    """
    antes = texto[:posicao]
    abertura = antes.rfind("{% if KRONUS.DEBUG %}")
    if abertura == -1:
        return False
    return "{% endif %}" not in antes[abertura:]


def _templates():
    for caminho in RAIZ.rglob("*.html"):
        if IGNORADAS & set(caminho.relative_to(RAIZ).parts):
            continue
        yield caminho


class SemScriptExternoTests(TestCase):
    def test_nenhum_template_carrega_script_de_outro_host(self):
        infratores = []
        for caminho in _templates():
            texto = caminho.read_text(encoding="utf-8", errors="ignore")
            for achado in SCRIPT_EXTERNO.finditer(texto):
                if _sob_guarda_de_debug(texto, achado.start()):
                    continue
                linha = texto[: achado.start()].count("\n") + 1
                infratores.append(f"{caminho.relative_to(RAIZ)}:{linha}")
        self.assertEqual(
            infratores, [],
            "script vindo de outro host — baixe para static/vendor/: "
            + ", ".join(infratores),
        )

    def test_a_politica_de_seguranca_nao_libera_cdn(self):
        # Lido como texto: `production` exige variaveis de ambiente que a
        # suite nao tem, e o que interessa aqui e o que esta escrito.
        fonte = (RAIZ / "config/settings/production.py").read_text(encoding="utf-8")
        trecho = fonte[fonte.index("CSP_SCRIPT_SRC"):][:400]
        for host in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs"):
            self.assertNotIn(
                host, trecho,
                f"a CSP ainda libera {host}: liberar convida a voltar a usar",
            )

    def test_a_excecao_do_tailwind_continua_presa_ao_debug(self):
        # Se alguem tirar o `{% if KRONUS.DEBUG %}`, o Play CDN vaza para
        # producao sem que nada acuse.
        pagina = (RAIZ / "templates/components/_estilos.html").read_text(
            encoding="utf-8"
        )
        posicao = pagina.index("cdn.tailwindcss.com")
        self.assertTrue(
            _sob_guarda_de_debug(pagina, posicao),
            "o Tailwind Play saiu de dentro do guarda de DEBUG",
        )


class BibliotecasPresentesTests(TestCase):
    """
    Baixar a biblioteca so resolve enquanto o arquivo existir. Um `git
    add` esquecido devolveria o defeito inteiro, e em silencio.
    """

    ESPERADAS = {
        "apps/totem/static/totem/js/vendor/face-api.min.js": 500_000,
        "static/vendor/alpine.min.js": 20_000,
        "static/vendor/htmx.min.js": 20_000,
        "static/vendor/chart.umd.min.js": 50_000,
        "static/img/ks-tec-logo.png": 1_000,
    }

    def test_os_arquivos_existem_e_nao_estao_truncados(self):
        for relativo, minimo in self.ESPERADAS.items():
            caminho = RAIZ / relativo
            with self.subTest(arquivo=relativo):
                self.assertTrue(caminho.is_file(), f"faltando: {relativo}")
                self.assertGreater(
                    caminho.stat().st_size, minimo,
                    f"{relativo} parece truncado — download incompleto?",
                )

    def test_o_totem_aponta_para_a_copia_local(self):
        pagina = (RAIZ / "apps/totem/templates/totem/index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("totem/js/vendor/face-api.min.js", pagina)


class DetectorNaoDesisteCedoTests(TestCase):
    """
    O script e `defer`: pode nao ter executado quando o app inicia. A
    versao anterior conferia `typeof faceapi` uma unica vez e escolhia o
    modo degradado por causa de alguns milissegundos — uma corrida que a
    rede local esconde e a rede real revela.
    """

    def setUp(self):
        self.js = (
            RAIZ / "apps/totem/static/totem/js/face-detector.js"
        ).read_text(encoding="utf-8")

    def test_espera_o_face_api_em_vez_de_conferir_uma_vez(self):
        self.assertIn("_esperarFaceApi", self.js)

    def test_o_modo_degradado_guarda_o_motivo(self):
        self.assertIn("motivoDegradado", self.js)

    def test_o_modo_degradado_nunca_declara_rosto_pronto(self):
        # A garantia que impede o totem de mandar imagem ao acaso quando
        # esta sem detector — e o que tornava a falha silenciosa, agora
        # compensado pelo aviso na tela.
        self.assertIn("pronto: false", self.js)


class ProximidadeTests(TestCase):
    """
    O totem so envia ao servidor quando a pessoa esta perto.

    Existe por uma faixa de defeitos concreta: identificacoes no fio do
    limiar, vindas de rostos distantes. O ArcFace consome um recorte de
    112x112; um rosto que ocupa o minimo para nao precisar ser ampliado
    nao tem detalhe sobrando — e detalhe e o que separa duas pessoas
    parecidas.
    """

    def setUp(self):
        self.js = (
            RAIZ / "apps/totem/static/totem/js/face-detector.js"
        ).read_text(encoding="utf-8")

    def _valor(self, nome):
        import re
        achado = re.search(rf"{nome}:\s*([0-9.]+)", self.js)
        self.assertIsNotNone(achado, f"{nome} sumiu do detector")
        return float(achado.group(1))

    def test_exige_o_rosto_ocupando_boa_parte_do_quadro(self):
        minimo = self._valor("LARGURA_MINIMA_ROSTO")
        # 0.175 e o ponto em que o recorte deixa de ser ampliado (112 px
        # num quadro de 640). Ficar nele nao basta: e preciso folga.
        self.assertGreaterEqual(
            minimo, 0.25,
            "abaixo disso o recorte chega ao modelo sem detalhe sobrando, "
            "e foi essa faixa que produziu identificacao no fio do limiar",
        )

    def test_ainda_recusa_quem_esta_perto_demais(self):
        # Rosto cortado pela moldura tambem estraga o recorte.
        self.assertLess(
            self._valor("LARGURA_MINIMA_ROSTO"),
            self._valor("LARGURA_MAXIMA_ROSTO"),
        )

    def test_acordar_a_tela_continua_sendo_mais_facil_que_enviar(self):
        # Presenca e envio sao decisoes diferentes: a tela acorda com
        # pouco, o envio exige enquadramento. Igualar as duas faria o
        # totem so acordar quando ja desse para identificar — e a pessoa
        # ficaria na frente de uma tela apagada.
        self.assertLess(
            self._valor("CONFIANCA_PRESENCA"), self._valor("CONFIANCA_MINIMA")
        )
