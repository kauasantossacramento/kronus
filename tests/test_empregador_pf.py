"""
Kronus — empregador pessoa fisica.

O empregador domestico e o produtor rural pessoa fisica registram ponto e
sao alcancados pela Portaria 671 como qualquer outro. Os anexos ja
preveem o caso: o AFD tem `tipo_identificador` (1=CNPJ, 2=CPF) e o AEJ
tem `tpIdtEmpregador`. Os dois estavam fixos em "1" — o arquivo declarava
CNPJ e trazia onze digitos.
"""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.clientes.models import Cliente, Empresa
from apps.core.utils import (
    formatar_cnpj_ou_cpf,
    tipo_identificador,
    validar_cnpj_ou_cpf,
)
from apps.master.models import Plano

CNPJ = "45997418000153"
CPF = "52998224725"


class DocumentoTests(TestCase):
    def test_reconhece_cnpj_e_cpf(self):
        self.assertEqual(tipo_identificador(CNPJ), "1")
        self.assertEqual(tipo_identificador(CPF), "2")

    def test_reconhece_com_mascara(self):
        self.assertEqual(tipo_identificador("529.982.247-25"), "2")
        self.assertEqual(tipo_identificador("45.997.418/0001-53"), "1")

    def test_formata_conforme_o_tipo(self):
        self.assertEqual(formatar_cnpj_ou_cpf(CPF), "529.982.247-25")
        self.assertEqual(formatar_cnpj_ou_cpf(CNPJ), "45.997.418/0001-53")

    def test_aceita_os_dois_validos(self):
        self.assertEqual(validar_cnpj_ou_cpf("529.982.247-25"), CPF)
        self.assertEqual(validar_cnpj_ou_cpf("45.997.418/0001-53"), CNPJ)

    def test_recusa_cpf_invalido(self):
        with self.assertRaises(ValidationError):
            validar_cnpj_ou_cpf("11111111111")

    def test_recusa_cnpj_invalido(self):
        with self.assertRaises(ValidationError):
            validar_cnpj_ou_cpf("11111111111111")

    def test_recusa_tamanho_sem_sentido(self):
        with self.assertRaises(ValidationError):
            validar_cnpj_ou_cpf("12345")


class CadastroPessoaFisicaTests(TestCase):
    def setUp(self):
        self.plano = Plano.objects.create(
            nome="Plano", slug="plano", max_empresas=3, max_colaboradores=20
        )

    def test_cliente_pessoa_fisica(self):
        cliente = Cliente.objects.create(
            razao_social="José da Silva", cnpj=CPF,
            plano=self.plano, email_contato="jose@x.com",
        )
        self.assertTrue(cliente.pessoa_fisica)
        self.assertEqual(cliente.rotulo_documento, "CPF")
        self.assertEqual(cliente.cnpj_formatado, "529.982.247-25")

    def test_cliente_pessoa_juridica_segue_igual(self):
        cliente = Cliente.objects.create(
            razao_social="Alfa LTDA", cnpj=CNPJ,
            plano=self.plano, email_contato="a@x.com",
        )
        self.assertFalse(cliente.pessoa_fisica)
        self.assertEqual(cliente.rotulo_documento, "CNPJ")

    def test_empresa_propria_de_cliente_pessoa_fisica(self):
        cliente = Cliente.objects.create(
            razao_social="José da Silva", cnpj=CPF,
            plano=self.plano, email_contato="jose@x.com",
        )
        empresa = cliente.garantir_empresa_propria()

        self.assertEqual(empresa.cnpj, CPF)
        self.assertTrue(empresa.pessoa_fisica)
        self.assertEqual(empresa.tipo_identificador_afd, "2")

    def test_formulario_aceita_cpf(self):
        from apps.clientes.forms import EmpresaForm

        cliente = Cliente.objects.create(
            razao_social="José", cnpj=CNPJ, plano=self.plano,
            email_contato="j@x.com",
        )
        form = EmpresaForm(data={
            "cliente": cliente.pk, "razao_social": "José da Silva",
            "cnpj": "529.982.247-25", "cei_caepf": "123456789012",
            "fuso_horario": "America/Bahia", "ativo": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cnpj"], CPF)

    def test_formulario_recusa_documento_invalido(self):
        from apps.clientes.forms import EmpresaForm

        form = EmpresaForm(data={"razao_social": "X", "cnpj": "00000000000"})
        self.assertFalse(form.is_valid())
        self.assertIn("cnpj", form.errors)


class ArquivosFiscaisTests(TestCase):
    """O tipo do identificador precisa chegar correto ao AFD e ao AEJ."""

    def _empresa(self, documento, caepf=""):
        plano = Plano.objects.create(
            nome=f"P{documento[:4]}", slug=f"p{documento[:4]}",
            max_empresas=3, max_colaboradores=20,
        )
        cliente = Cliente.objects.create(
            razao_social="Empregador", cnpj=documento,
            plano=plano, email_contato="e@x.com",
        )
        return Empresa.objects.create(
            cliente=cliente, razao_social="Empregador",
            cnpj=documento, cei_caepf=caepf,
        )

    def test_cabecalho_do_afd_marca_cpf(self):
        from apps.relatorios.afd import AFDGenerator, ler_campo

        empresa = self._empresa(CPF, caepf="123456789012")
        linha = AFDGenerator(
            empresa, date.today() - timedelta(days=1), date.today()
        ).gerar().splitlines()[0]

        self.assertEqual(ler_campo(linha, "1", "tipo_identificador"), "2")
        self.assertIn(CPF, ler_campo(linha, "1", "identificador"))

    def test_cabecalho_do_afd_marca_cnpj(self):
        from apps.relatorios.afd import AFDGenerator, ler_campo

        empresa = self._empresa(CNPJ)
        linha = AFDGenerator(
            empresa, date.today() - timedelta(days=1), date.today()
        ).gerar().splitlines()[0]

        self.assertEqual(ler_campo(linha, "1", "tipo_identificador"), "1")

    def test_caepf_do_empregador_pf_vai_no_cabecalho(self):
        """
        Para o empregador pessoa fisica, o CAEPF e o que identifica a
        matricula junto a Previdencia — sem ele o arquivo identifica uma
        pessoa, mas nao o vinculo.
        """
        from apps.relatorios.afd import AFDGenerator, ler_campo

        empresa = self._empresa(CPF, caepf="123456789012")
        linha = AFDGenerator(
            empresa, date.today() - timedelta(days=1), date.today()
        ).gerar().splitlines()[0]

        self.assertIn("123456789012", ler_campo(linha, "1", "cno_caepf"))

    def test_aej_marca_o_tipo_do_empregador(self):
        from apps.relatorios.aej import AEJGenerator

        empresa = self._empresa(CPF, caepf="123456789012")
        conteudo = AEJGenerator(
            empresa, date.today() - timedelta(days=1), date.today()
        ).gerar()
        primeira = conteudo.splitlines()[0]

        campos = primeira.split("|")
        self.assertEqual(campos[0], "01")
        self.assertEqual(campos[1], "2", "tpIdtEmpregador deveria ser 2 (CPF)")
