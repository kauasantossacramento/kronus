"""
Kronus — identidade do totem: patrimonio, etiqueta e verificacao publica.

O equipamento e da KS TEC mesmo quando esta em comodato no cliente. A
etiqueta colada nele responde de quem e, qual o patrimonio, e permite a
qualquer pessoa conferir a procedencia pela camera — sem que essa mesma
pessoa ganhe qualquer acesso ao registro de ponto.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoUsuario
from apps.master.models import Plano
from apps.totem.models import Totem


class BaseTotem(TestCase):
    def setUp(self):
        self.plano = Plano.objects.create(
            nome="Plano", slug="plano", max_empresas=3,
            max_colaboradores=50, max_totems=5,
        )
        self.cliente = Cliente.objects.create(
            razao_social="Alfa LTDA", cnpj="45997418000153",
            plano=self.plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa", cnpj="45997418000234",
        )

    def _totem(self, **extra):
        return Totem.objects.create(empresa=self.empresa, **extra)


class PatrimonioTests(BaseTotem):
    def test_identificador_e_gerado_sozinho(self):
        totem = self._totem()
        self.assertTrue(totem.identificador)
        self.assertTrue(totem.identificador.startswith("KST-"))

    def test_formato_kst_ano_sequencial(self):
        import re

        from django.utils import timezone

        totem = self._totem()
        ano = timezone.localdate().year
        self.assertRegex(totem.identificador, rf"^KST-{ano}-\d{{5}}$")

    def test_numeros_avancam_e_nunca_se_repetem(self):
        emitidos = [self._totem().identificador for _ in range(5)]
        self.assertEqual(len(set(emitidos)), 5)

        numeros = [int(i.rsplit("-", 1)[1]) for i in emitidos]
        self.assertEqual(numeros, sorted(numeros))

    def test_numero_nao_e_reaproveitado_apos_exclusao(self):
        """
        Dois equipamentos com a mesma etiqueta, em clientes diferentes, e
        o tipo de erro que so aparece quando ja e caro.
        """
        primeiro = self._totem()
        segundo = self._totem()
        usado = segundo.identificador
        segundo.delete()

        terceiro = self._totem()
        self.assertNotEqual(terceiro.identificador, usado)
        self.assertNotEqual(terceiro.identificador, primeiro.identificador)

    def test_identificador_informado_e_respeitado(self):
        totem = self._totem(identificador="LEGADO-01")
        self.assertEqual(totem.identificador, "LEGADO-01")

    def test_nao_muda_ao_salvar_de_novo(self):
        totem = self._totem()
        original = totem.identificador
        totem.apelido = "Recepcao"
        totem.save()
        totem.refresh_from_db()
        self.assertEqual(totem.identificador, original)


class CodigoDeAutenticidadeTests(BaseTotem):
    def test_e_estavel(self):
        totem = self._totem()
        self.assertEqual(totem.codigo_autenticidade, totem.codigo_autenticidade)

    def test_difere_entre_totens(self):
        self.assertNotEqual(
            self._totem().codigo_autenticidade,
            self._totem().codigo_autenticidade,
        )

    def test_nao_revela_o_token_de_acesso(self):
        """
        A etiqueta fica visivel numa recepcao. Quem a fotografa nao pode
        sair com a credencial que abre o registro de ponto.
        """
        totem = self._totem()
        codigo = totem.codigo_autenticidade

        self.assertNotIn(codigo, totem.token_acesso)
        self.assertNotIn(totem.token_acesso, codigo)
        self.assertLess(len(codigo), len(totem.token_acesso))

    def test_muda_quando_o_token_e_rotacionado(self):
        totem = self._totem()
        antes = totem.codigo_autenticidade
        totem.regenerar_token()
        self.assertNotEqual(totem.codigo_autenticidade, antes)


class PaginaPublicaTests(BaseTotem):
    def test_confirma_equipamento_legitimo_sem_login(self):
        totem = self._totem(local_instalacao="Recepção")
        resposta = self.client.get(
            reverse("totem:autenticidade", args=[totem.codigo_autenticidade])
        )
        corpo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("autêntico", corpo)
        self.assertIn(totem.identificador, corpo)
        self.assertIn("KS TEC", corpo)

    def test_nao_expoe_o_token_nem_dado_de_pessoa(self):
        totem = self._totem()
        corpo = self.client.get(
            reverse("totem:autenticidade", args=[totem.codigo_autenticidade])
        ).content.decode()

        self.assertNotIn(totem.token_acesso, corpo)
        self.assertNotIn("cpf", corpo.lower())

    def test_codigo_desconhecido_nao_estoura(self):
        resposta = self.client.get(
            reverse("totem:autenticidade", args=["ZZZZZZZZZZZZ"])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("não encontrado", resposta.content.decode())


class EtiquetaTests(BaseTotem):
    def _master(self):
        usuario = CustomUser.objects.create_user(
            email="m@kstec.online", password="x", nome_completo="Master",
            tipo=TipoUsuario.MASTER, is_staff=True, is_superuser=True,
        )
        self.client.force_login(usuario)
        return usuario

    def test_gera_png_valido_no_tamanho_da_etiqueta(self):
        import io

        from PIL import Image

        self._master()
        totem = self._totem()
        resposta = self.client.get(reverse("totem:etiqueta", args=[totem.pk]))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "image/png")
        with Image.open(io.BytesIO(resposta.content)) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.size, (1063, 591))

    def test_o_qr_aponta_para_a_verificacao_e_nao_para_o_totem(self):
        from apps.totem.etiqueta import gerar

        totem = self._totem()
        # Confere o alvo pela propria URL montada, e nao lendo o QR:
        # o que importa e que o endereco impresso seja o publico.
        self.assertIn("autenticidade", totem.url_autenticidade)
        self.assertNotIn(totem.token_acesso, totem.url_autenticidade)
        self.assertTrue(gerar(totem, "https://kronus.online"))

    def test_somente_o_master_emite_etiqueta(self):
        totem = self._totem()
        usuario = CustomUser.objects.create_user(
            email="rh@x.com", password="x", nome_completo="RH",
            tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        self.client.force_login(usuario)

        resposta = self.client.get(reverse("totem:etiqueta", args=[totem.pk]))
        self.assertEqual(resposta.status_code, 403)

    def test_anonimo_nao_emite_etiqueta(self):
        totem = self._totem()
        resposta = self.client.get(reverse("totem:etiqueta", args=[totem.pk]))
        self.assertIn(resposta.status_code, (302, 403))


class VersaoDoAppTests(BaseTotem):
    def test_versao_vem_de_uma_fonte_unica(self):
        from django.conf import settings

        from apps.totem.views import VERSAO_APP

        self.assertEqual(VERSAO_APP, settings.KRONUS["VERSAO"])

    def test_heartbeat_preenche_a_versao(self):
        """Digitada, a versao envelhece; vinda do aparelho, acompanha."""
        totem = self._totem()
        self.assertEqual(totem.versao_firmware, "")

        totem.registrar_heartbeat(ip="10.0.0.5", versao="1.4.2")
        totem.refresh_from_db()
        self.assertEqual(totem.versao_firmware, "1.4.2")

    def test_formulario_nao_pede_versao_nem_patrimonio(self):
        from apps.master.forms import TotemForm

        campos = set(TotemForm().fields)
        self.assertNotIn("versao_firmware", campos)
        self.assertNotIn("identificador", campos)
