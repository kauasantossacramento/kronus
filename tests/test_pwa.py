"""
Kronus — instalabilidade dos apps.

O defeito que motivou estes testes era silencioso: os manifestos
declaravam `"type": "image/png"` apontando para um `.svg`. O Chrome
valida o icone antes de considerar o site instalavel, descartava o icone
e nunca disparava `beforeinstallprompt` — o convite de instalacao
simplesmente nao existia, e nada no servidor acusava erro.
"""
import mimetypes
import pathlib

from django.test import TestCase

RAIZ = pathlib.Path(__file__).resolve().parent.parent


class IconesDoManifestoTests(TestCase):
    def test_os_png_existem_de_verdade(self):
        for nome in ("icon-192.png", "icon-512.png", "icon-512-maskable.png"):
            caminho = RAIZ / "static" / "img" / nome
            self.assertTrue(caminho.exists(), f"{nome} nao foi versionado")
            self.assertGreater(caminho.stat().st_size, 1000)

    def test_os_png_tem_o_tamanho_declarado(self):
        from PIL import Image

        esperado = {
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "icon-512-maskable.png": (512, 512),
        }
        for nome, tamanho in esperado.items():
            with Image.open(RAIZ / "static" / "img" / nome) as img:
                self.assertEqual(img.size, tamanho, f"{nome} tem {img.size}")
                self.assertEqual(img.format, "PNG")

    def test_tipo_declarado_bate_com_a_extensao(self):
        from apps.core.icones_pwa import PADRAO, para_logo

        listas = [PADRAO, para_logo(None), para_logo("/media/logos/x.png"),
                  para_logo("/media/logos/y.svg"), para_logo("/media/logos/z.jpg")]
        for icones in listas:
            for icone in icones:
                real = mimetypes.guess_type(icone["src"])[0]
                self.assertEqual(
                    icone["type"], real,
                    f"{icone['src']} declarado como {icone['type']}, mas e {real}",
                )

    def test_svg_do_cliente_nao_declara_tamanho_falso(self):
        from apps.core.icones_pwa import para_logo

        primeiro = para_logo("/media/logos/marca.svg")[0]
        self.assertEqual(primeiro["type"], "image/svg+xml")
        self.assertEqual(primeiro["sizes"], "any")

    def test_icones_do_kronus_sempre_acompanham_a_logo_do_cliente(self):
        """Logo fora do tamanho minimo nao pode tornar o app nao instalavel."""
        from apps.core.icones_pwa import para_logo

        fontes = [i["src"] for i in para_logo("/media/logos/marca.png")]
        self.assertIn("/static/img/icon-512.png", fontes)

    def test_ha_um_icone_maskable(self):
        from apps.core.icones_pwa import para_logo

        propositos = [i.get("purpose") for i in para_logo(None)]
        self.assertIn("maskable", propositos)


class ManifestosServidosTests(TestCase):
    """Os tres manifestos precisam sair validos, nao so a funcao de icones."""

    def test_manifesto_do_painel(self):
        from apps.accounts.models import CustomUser

        usuario = CustomUser.objects.create_user(
            email="admin@x.com", password="x", nome_completo="Admin"
        )
        self.client.force_login(usuario)
        dados = self.client.get("/app/manifest.json").json()

        self.assertTrue(dados["icons"])
        self.assertEqual(dados["start_url"], "/app/")
        for icone in dados["icons"]:
            self.assertEqual(
                icone["type"], mimetypes.guess_type(icone["src"])[0]
            )


class ConviteDeInstalacaoTests(TestCase):
    """O ramo de iOS precisa reconhecer o iPad."""

    def setUp(self):
        self.fonte = (
            RAIZ / "templates" / "components" / "instalar_app.html"
        ).read_text(encoding="utf-8")

    def test_reconhece_o_ipad_moderno(self):
        # Desde o iPadOS 13 o Safari do iPad se identifica como
        # "Macintosh": testar so por /iPad/ nunca casa em tablet.
        self.assertIn("maxTouchPoints", self.fonte)
        self.assertIn("Macintosh", self.fonte)

    def test_nao_insiste_com_quem_recusou(self):
        self.assertIn("localStorage", self.fonte)

    def test_nao_aparece_para_quem_ja_instalou(self):
        self.assertIn("display-mode: standalone", self.fonte)
