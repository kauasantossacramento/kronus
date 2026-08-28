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


class LogoNaEtiquetaTests(BaseTotem):
    """
    A faixa superior existe para dizer de quem e o equipamento. Sem a
    marca, ela e so um retangulo azul.
    """

    def test_a_logo_branca_esta_versionada(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        arquivo = raiz / "static" / "img" / "kstec-logo-branca.png"
        self.assertTrue(
            arquivo.exists(),
            "a logo precisa estar no repositorio: a etiqueta e gerada sob "
            "demanda e nao pode depender de kstec.online estar no ar",
        )

    def test_a_logo_e_realmente_branca_e_com_transparencia(self):
        import pathlib

        from PIL import Image

        raiz = pathlib.Path(__file__).resolve().parent.parent
        with Image.open(raiz / "static" / "img" / "kstec-logo-branca.png") as img:
            self.assertEqual(img.mode, "RGBA", "sem alfa, vira caixa branca")
            cores = {p[:3] for p in img.convert("RGBA").getdata() if p[3] > 200}
            self.assertTrue(
                cores and all(c == (255, 255, 255) for c in cores),
                f"todo pixel opaco deveria ser branco; achei {list(cores)[:3]}",
            )

    def test_a_faixa_da_etiqueta_recebe_a_logo(self):
        import io

        from PIL import Image

        from apps.totem.etiqueta import gerar

        totem = self._totem()
        with Image.open(io.BytesIO(gerar(totem))) as etiqueta:
            faixa = etiqueta.convert("RGB").crop((30, 20, 220, 70))
            # Pixel branco dentro da faixa azul so pode vir da logo.
            brancos = sum(
                1 for p in faixa.getdata()
                if p[0] > 230 and p[1] > 230 and p[2] > 230
            )
        self.assertGreater(
            brancos, 200,
            "a logo branca nao aparece na faixa superior da etiqueta",
        )


class EscopoDoTotemTests(BaseTotem):
    """
    Quem pode bater ponto em cada totem — pelos dois caminhos, facial e
    digitacao do CPF.

    O grupo **amplia** o alcance do equipamento; nao o substitui. Antes,
    um grupo montado so com as filiais fazia a matriz perder acesso ao
    proprio totem instalado na recepcao dela.
    """

    def setUp(self):
        super().setUp()
        from apps.clientes.models import Empresa

        self.filial_b = Empresa.objects.create(
            cliente=self.cliente, razao_social="Filial B", cnpj="11444777000161",
        )
        self.filial_c = Empresa.objects.create(
            cliente=self.cliente, razao_social="Filial C", cnpj="34028316000103",
        )

    def _grupo(self, empresas, nome="Grupo"):
        from apps.totem.models import GrupoTotem

        grupo = GrupoTotem.objects.create(cliente=self.cliente, nome=nome)
        grupo.empresas.set(empresas)
        return grupo

    def _atendidas(self, totem):
        return set(totem.empresas_atendidas().values_list("pk", flat=True))

    def test_sem_grupo_atende_so_a_propria_empresa(self):
        totem = self._totem()
        self.assertEqual(self._atendidas(totem), {self.empresa.pk})

    def test_com_grupo_atende_todas_as_empresas_do_grupo(self):
        totem = self._totem(
            grupo=self._grupo([self.empresa, self.filial_b, self.filial_c])
        )
        self.assertEqual(
            self._atendidas(totem),
            {self.empresa.pk, self.filial_b.pk, self.filial_c.pk},
        )

    def test_a_propria_empresa_entra_mesmo_fora_do_grupo(self):
        """
        O totem esta instalado nela: recusar quem trabalha ali porque
        alguem esqueceu de marcar a empresa no grupo seria negar o ponto
        a quem esta parado na frente da maquina.
        """
        totem = self._totem(grupo=self._grupo([self.filial_b, self.filial_c]))
        self.assertIn(self.empresa.pk, self._atendidas(totem))

    def test_grupo_vazio_nao_amplia_nada(self):
        totem = self._totem(grupo=self._grupo([], nome="Vazio"))
        self.assertEqual(self._atendidas(totem), {self.empresa.pk})

    def test_empresa_de_fora_do_grupo_e_recusada(self):
        from apps.ponto.validators import RegistroInvalido, validar_totem_autorizado

        totem = self._totem(grupo=self._grupo([self.empresa, self.filial_b]))
        de_fora = self._colaborador(self.filial_c)

        with self.assertRaises(RegistroInvalido) as contexto:
            validar_totem_autorizado(totem, de_fora)
        self.assertEqual(contexto.exception.codigo, "totem_nao_autorizado")

    def test_colaborador_do_grupo_bate_ponto(self):
        from apps.ponto.validators import validar_totem_autorizado

        totem = self._totem(grupo=self._grupo([self.empresa, self.filial_b]))
        validar_totem_autorizado(totem, self._colaborador(self.filial_b))

    def test_o_fallback_por_cpf_respeita_o_mesmo_escopo(self):
        """
        Se a digitacao do CPF tivesse escopo maior que o facial, o limite
        seria contornavel digitando em vez de olhar para a camera.
        """
        from apps.facial.services import identificar_por_cpf

        totem = self._totem(grupo=self._grupo([self.empresa, self.filial_b]))
        dentro = self._colaborador(self.filial_b)
        fora = self._colaborador(self.filial_c)
        empresas = totem.empresas_atendidas()

        self.assertIsNotNone(
            identificar_por_cpf(dentro.cpf, dentro.data_nascimento, empresas)
        )
        self.assertIsNone(
            identificar_por_cpf(fora.cpf, fora.data_nascimento, empresas)
        )

    def _colaborador(self, empresa):
        from datetime import date

        from apps.comercial.services import gerar_cpf
        from apps.rh.models import Colaborador

        return Colaborador.objects.create(
            empresa=empresa, cpf=gerar_cpf(),
            nome_completo=f"Pessoa {empresa.pk}",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )
