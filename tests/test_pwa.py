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


class InstalacaoDoTotemTests(TestCase):
    """
    O totem e o aparelho onde a instalacao mais importa: sem ela a tela
    fica com barra de navegador, e barra de navegador convida o
    colaborador a sair da pagina.
    """

    def setUp(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.totem.models import Totem

        plano = Plano.objects.create(nome="P", slug="p", max_totems=3)
        cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        empresa = Empresa.objects.create(
            cliente=cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.totem = Totem.objects.create(empresa=empresa, ativo=True)
        self.pagina = self.client.get(
            f"/totem/{self.totem.token_acesso}/"
        ).content.decode()

    def test_o_convite_esta_na_pagina(self):
        self.assertIn("totem-instalar", self.pagina)

    def test_reconhece_o_ipad(self):
        """
        Sem este ramo o convite nunca aparecia em tablet da Apple — que e
        justamente um aparelho comum de totem. Desde o iPadOS 13 o Safari
        do iPad se identifica como "Macintosh".
        """
        self.assertIn("maxTouchPoints", self.pagina)
        self.assertIn("Macintosh", self.pagina)

    def test_ensina_o_gesto_manual(self):
        self.assertIn("Adicionar à Tela de Início", self.pagina)

    def test_declara_capacidade_de_app_no_ios(self):
        """Sem isto, o atalho do iPad abre dentro do Safari, com barra."""
        self.assertIn("apple-mobile-web-app-capable", self.pagina)
        self.assertIn("apple-touch-icon", self.pagina)

    def test_manifesto_do_totem_tem_icone_valido(self):
        dados = self.client.get(
            f"/totem/{self.totem.token_acesso}/manifest.json"
        ).json()

        self.assertTrue(dados["icons"])
        self.assertIn(dados["display"], ("fullscreen", "standalone", "minimal-ui"))
        for icone in dados["icons"]:
            self.assertEqual(icone["type"], mimetypes.guess_type(icone["src"])[0])

    def test_o_escopo_do_manifesto_cobre_a_pagina(self):
        """`start_url` fora do `scope` torna o app nao instalavel."""
        dados = self.client.get(
            f"/totem/{self.totem.token_acesso}/manifest.json"
        ).json()
        self.assertTrue(dados["start_url"].startswith(dados["scope"]))

    def test_hidden_vence_o_display_do_css(self):
        """
        `hidden` vale `display: none` pelo navegador, mas qualquer
        `display` do autor vence. Sem a regra, o ramo do Android aparecia
        junto com o do iPad — um botao "Instalar" visivel no iPhone que
        nao faz nada, porque la o evento nao existe.
        """
        css = (
            RAIZ / "apps" / "totem" / "static" / "totem" / "css" / "totem.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".totem-instalar [hidden]", css)
