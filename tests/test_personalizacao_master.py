"""
Kronus — personalizacao de uma empresa pelo Master.

A mesma tela existe no RH, mas so alcanca `request.empresa_ativa` — e o
Master nao tem empresa ativa. Na pratica, quem faz a implantacao do
cliente nao conseguia subir a logo dele em lugar nenhum.
"""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import CustomUser
from apps.clientes.models import Cliente, Empresa, SlideTotem
from apps.core.constants import TipoUsuario
from apps.master.models import Plano
from apps.totem.models import Totem

MIDIA = tempfile.mkdtemp()


def imagem(nome="logo.png", tamanho=(120, 60), cor=(30, 58, 95)):
    buffer = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(buffer, "PNG")
    return SimpleUploadedFile(nome, buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MIDIA)
class PersonalizacaoPeloMasterTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MIDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.plano = Plano.objects.create(
            nome="Plano", slug="plano", max_empresas=3,
            max_colaboradores=20, max_totems=3,
        )
        self.cliente = Cliente.objects.create(
            razao_social="Invicta LTDA", cnpj="45997418000153",
            plano=self.plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Invicta", cnpj="45997418000234",
        )
        self.master = CustomUser.objects.create_user(
            email="m@kstec.online", password="x", nome_completo="Master",
            tipo=TipoUsuario.MASTER, is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.master)
        self.url = reverse("master:empresa_personalizacao", args=[self.empresa.pk])

    def _post(self, **extra):
        dados = {
            "cor_primaria": "#1E3A5F", "cor_secundaria": "#D4A017",
            "logo_altura_px": 40, "logo_deslocamento_px": 0, "logo_css": "",
            "msg_boas_vindas": "Registre seu ponto",
            "msg_sucesso_ponto": "Ponto registrado!",
        }
        dados.update(extra)
        return self.client.post(self.url, dados, follow=True)

    def test_a_tela_abre(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Personalização")

    def test_envia_a_logo(self):
        self._post(logo=imagem())

        self.empresa.refresh_from_db()
        self.assertTrue(self.empresa.logo)
        self.assertIn("logo", self.empresa.logo.name)

    def test_envia_a_capa_do_totem(self):
        self._post(idle_screen_img=imagem("capa.png", (800, 480)))

        self.empresa.refresh_from_db()
        self.assertTrue(self.empresa.idle_screen_img)

    def test_troca_as_cores(self):
        self._post(cor_primaria="#123456", cor_secundaria="#ABCDEF")

        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.cor_primaria, "#123456")
        self.assertEqual(self.empresa.cor_secundaria, "#ABCDEF")

    def test_totens_sao_avisados_para_recarregar(self):
        """
        Sem isto, a logo nova so apareceria quando alguem reiniciasse o
        tablet — e ninguem reinicia um totem de portaria.
        """
        totem = Totem.objects.create(empresa=self.empresa, ativo=True)
        self.assertIsNone(totem.recarga_solicitada_em)

        self._post(cor_primaria="#111111")

        totem.refresh_from_db()
        self.assertIsNotNone(totem.recarga_solicitada_em)

    def test_adiciona_slide(self):
        self.client.post(self.url, {
            "acao": "slide", "imagem": imagem("slide.png", (800, 480)),
            "legenda": "Campanha de segurança",
        }, follow=True)

        slides = SlideTotem.objects.filter(empresa=self.empresa)
        self.assertEqual(slides.count(), 1)
        self.assertEqual(slides.first().legenda, "Campanha de segurança")

    def test_remove_slide(self):
        slide = SlideTotem.objects.create(
            empresa=self.empresa, imagem=imagem("s.png"), ordem=0
        )
        self.client.post(self.url, {"acao": "slide", "remover": slide.pk}, follow=True)
        self.assertEqual(SlideTotem.objects.filter(empresa=self.empresa).count(), 0)

    def test_recusa_imagem_grande_demais(self):
        """O totem baixa a imagem a cada troca; um arquivo grande trava a tela."""
        grande = SimpleUploadedFile(
            "grande.png", b"x" * (9 * 1024 * 1024), content_type="image/png"
        )
        resposta = self.client.post(self.url, {
            "acao": "slide", "imagem": grande,
        }, follow=True)

        self.assertEqual(SlideTotem.objects.filter(empresa=self.empresa).count(), 0)
        self.assertContains(resposta, "8 MB")

    def test_slide_sem_imagem_avisa(self):
        resposta = self.client.post(self.url, {"acao": "slide"}, follow=True)
        self.assertContains(resposta, "Selecione uma imagem")

    def test_somente_o_master_acessa(self):
        rh = CustomUser.objects.create_user(
            email="rh@x.com", password="x", nome_completo="RH",
            tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        rh.empresas.add(self.empresa)
        self.client.force_login(rh)

        resposta = self.client.get(self.url)
        self.assertNotEqual(resposta.status_code, 200)

    def test_a_edicao_leva_para_a_personalizacao(self):
        resposta = self.client.get(
            reverse("master:empresa_editar", args=[self.empresa.pk])
        )
        self.assertContains(resposta, self.url)
