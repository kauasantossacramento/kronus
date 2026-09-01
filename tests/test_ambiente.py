"""
Kronus — o conteudo ambiente da tela ociosa.

Uma tela ligada o dia inteiro mostrando so a logo desperdica um canal
que a empresa ja tem. Mas encher de conteudo tem custo: o que importa
— como bater o ponto, a hora, a marca — nao pode ser empurrado para
fora por um enfeite.
"""
from decimal import Decimal

from django.test import TestCase

from apps.clientes.ambiente import (
    FraseAmbiente,
    ImagemAmbiente,
    Periodo,
    periodo_de,
)
from apps.clientes.ambiente_servico import conteudo_para, esquecer


class PeriodoTests(TestCase):
    """
    Os cortes seguem o dia de trabalho, nao o relogio astronomico.
    """

    def test_manha_da_madrugada_ao_meio_dia(self):
        self.assertEqual(periodo_de(5), Periodo.MANHA)
        self.assertEqual(periodo_de(9), Periodo.MANHA)
        self.assertEqual(periodo_de(11), Periodo.MANHA)

    def test_tarde_ate_as_dezoito(self):
        self.assertEqual(periodo_de(12), Periodo.TARDE)
        self.assertEqual(periodo_de(17), Periodo.TARDE)

    def test_a_noite_e_o_resto(self):
        """
        Definir "das 18h as 5h" exigiria tratar a virada da meia-noite
        como caso especial — e caso especial em regra de horario e onde
        nasce o erro que so aparece as 23h59.
        """
        for hora in (18, 21, 23, 0, 3, 4):
            self.assertEqual(periodo_de(hora), Periodo.NOITE, f"hora {hora}")

    def test_todas_as_24_horas_tem_periodo(self):
        for hora in range(24):
            self.assertIn(periodo_de(hora), Periodo.values)


class BaseAmbiente(TestCase):
    def setUp(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano

        plano = Plano.objects.create(
            nome="P", slug="p", max_empresas=3, max_colaboradores=50,
            preco_mensal=Decimal("100"),
        )
        cliente = Cliente.objects.create(
            razao_social="C LTDA", cnpj="11222333000181",
            email_contato="c@t.com", plano=plano,
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="E LTDA", cnpj="60746948000112",
        )
        for i in range(6):
            FraseAmbiente.objects.create(
                periodo=Periodo.MANHA, texto=f"Bom dia {i}",
                tipo=FraseAmbiente.Tipo.SAUDACAO,
            )
        for i in range(3):
            FraseAmbiente.objects.create(
                periodo=Periodo.MANHA, texto=f"Beba água {i}",
                tipo=FraseAmbiente.Tipo.SAUDE,
            )
        esquecer()

    def _imagem(self, periodo=Periodo.MANHA, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile

        dados = extra.pop("dados", b"\x89PNG\r\n\x1a\n" + b"0" * 40)
        return ImagemAmbiente.objects.create(
            periodo=periodo,
            imagem=SimpleUploadedFile("f.png", dados, content_type="image/png"),
            fonte="https://exemplo.test/foto",
            licenca=extra.pop("licenca", "CC0"),
            **extra,
        )


class ConteudoTests(BaseAmbiente):
    def test_entrega_frases_do_periodo(self):
        c = conteudo_para(self.empresa, hora=9)
        self.assertEqual(c["periodo"], Periodo.MANHA)
        self.assertTrue(c["frases"])

    def test_a_dica_de_saude_entra_junto(self):
        """
        Uma tela que so da conselho de saude cansa; uma que nunca da
        perde a chance. Elas alternam com a saudacao.
        """
        esquecer()
        c = conteudo_para(self.empresa, hora=9)
        self.assertTrue(any("água" in f for f in c["frases"]))

    def test_periodo_sem_frase_nao_estoura(self):
        c = conteudo_para(self.empresa, hora=22)
        self.assertEqual(c["frases"], [])

    def test_a_empresa_pode_desligar(self):
        self.empresa.telas_ambiente = False
        self.empresa.save(update_fields=["telas_ambiente"])
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9), {})

    def test_quem_quer_so_os_proprios_slides_nao_recebe_acervo(self):
        self.empresa.modo_slides = self.empresa.ModoDosSlides.SOMENTE_MEUS
        self.empresa.save(update_fields=["modo_slides"])
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9), {})

    def test_quem_quer_so_o_acervo_avisa_o_totem(self):
        self.empresa.modo_slides = self.empresa.ModoDosSlides.SOMENTE_ACERVO
        self.empresa.save(update_fields=["modo_slides"])
        esquecer()
        self.assertTrue(conteudo_para(self.empresa, hora=9)["exclusivo"])

    def test_por_padrao_soma_os_dois(self):
        """
        Quem nunca subiu slide fica com a tela vazia se o acervo nao
        entrar — por isso o padrao soma.
        """
        self.assertFalse(conteudo_para(self.empresa, hora=9)["exclusivo"])
        self.assertTrue(self.empresa.telas_ambiente)


class ImagensTests(BaseAmbiente):
    def test_entrega_imagem_com_credito(self):
        self._imagem(autor="Fulano", licenca="CC0")
        esquecer()
        c = conteudo_para(self.empresa, hora=9)
        self.assertEqual(len(c["imagens"]), 1)
        self.assertIn("Fulano", c["imagens"][0]["credito"])
        self.assertIn("CC0", c["imagens"][0]["credito"])

    def test_sem_autor_o_credito_e_so_a_licenca(self):
        self._imagem(licenca="Unsplash License")
        esquecer()
        c = conteudo_para(self.empresa, hora=9)
        self.assertEqual(c["imagens"][0]["credito"], "Unsplash License")

    def test_a_empresa_pode_ocultar_uma_imagem(self):
        """
        Ocultar, e nao apagar: o acervo serve a todos os clientes, e um
        cliente que nao gosta de uma foto nao pode tira-la dos outros.
        """
        from apps.clientes.ambiente import ImagemOcultaPelaEmpresa

        img = self._imagem()
        outra = self._imagem()
        ImagemOcultaPelaEmpresa.objects.create(empresa=self.empresa, imagem=img)
        esquecer()

        c = conteudo_para(self.empresa, hora=9)
        urls = [i["url"] for i in c["imagens"]]
        self.assertEqual(len(urls), 1)
        self.assertIn(outra.imagem.url, urls)

    def test_imagem_de_outro_periodo_nao_aparece(self):
        self._imagem(periodo=Periodo.NOITE)
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9)["imagens"], [])

    def test_imagem_inativa_nao_aparece(self):
        img = self._imagem()
        img.ativo = False
        img.save(update_fields=["ativo"])
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9)["imagens"], [])


class ProcedenciaTests(TestCase):
    """
    Imagem de terceiro num totem comercial, sem licenca conferida, e
    risco juridico do cliente que instalou o equipamento.
    """

    def test_licenca_e_fonte_sao_obrigatorias(self):
        campo_licenca = ImagemAmbiente._meta.get_field("licenca")
        campo_fonte = ImagemAmbiente._meta.get_field("fonte")
        self.assertFalse(campo_licenca.blank)
        self.assertFalse(campo_fonte.blank)
