"""
Kronus — a cor da empresa vence no portal dela.

O `<body>` trazia a classe utilitaria `bg-[var(--kronus-gray-50)]`, e
uma classe tem especificidade maior que o seletor de elemento. A cor
escolhida pela empresa era escrita na folha de estilo e sobrescrita
logo depois pelo padrao do Kronus: o campo existia, a tela ignorava.
"""
from django.test import TestCase

from apps.clientes.models import Cliente, Empresa
from apps.master.models import Plano


class FundoDoPortalTests(TestCase):
    def setUp(self):
        plano = Plano.objects.create(nome="P", slug="p")
        cliente = Cliente.objects.create(
            razao_social="Bella", cnpj="72344591000125",
            plano=plano, email_contato="b@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="Bella Janela",
            cnpj="45997418000234", cor_fundo_login="#566B57",
        )

    def _pagina(self):
        return self.client.get(f"/{self.empresa.slug}/").content.decode()

    def test_a_cor_escolhida_aparece_na_folha(self):
        self.assertIn("background: #566B57", self._pagina())

    def test_nenhuma_classe_de_fundo_disputa_com_ela(self):
        pagina = self._pagina()
        corpo = pagina[pagina.index("<body"):pagina.index(">", pagina.index("<body"))]
        self.assertNotIn(
            "bg-[", corpo,
            "classe utilitaria no body vence a regra de elemento e apaga "
            "a cor da empresa",
        )

    def test_sem_cor_escolhida_o_padrao_continua(self):
        # Tirar a classe nao pode deixar a pagina sem fundo nenhum.
        self.empresa.cor_fundo_login = ""
        self.empresa.save(update_fields=["cor_fundo_login"])
        self.assertIn("background: #F8FAFC", self._pagina())


class ContrasteDoTextoTests(TestCase):
    """
    O texto acompanha o fundo escolhido.

    A tela foi escrita para fundo claro: titulo quase preto, subtitulo
    cinza, rodape cinza mais claro ainda. Uma empresa que usa logo
    branca escolhe fundo escuro — e ali esses textos desaparecem.
    """

    def _empresa(self, cor):
        plano = Plano.objects.create(nome="P", slug=f"p{cor[1:]}")
        cliente = Cliente.objects.create(
            razao_social="C", cnpj="72344591000125",
            plano=plano, email_contato="c@x.com",
        )
        return Empresa.objects.create(
            cliente=cliente, razao_social="E",
            cnpj="45997418000234", cor_fundo_login=cor,
        )

    def test_fundo_escuro_pede_texto_claro(self):
        self.assertTrue(self._empresa("#566B57").fundo_do_login_e_escuro)

    def test_fundo_claro_mantem_o_texto_escuro(self):
        self.assertFalse(self._empresa("#F8FAFC").fundo_do_login_e_escuro)

    def test_cor_ausente_ou_invalida_nao_quebra(self):
        # Campo vazio, ou um valor digitado errado, nao pode derrubar a
        # pagina de acesso de uma empresa inteira.
        for valor in ("", "verde", "#12", "#GGGGGG"):
            empresa = Empresa(cor_fundo_login=valor)
            self.assertFalse(empresa.fundo_do_login_e_escuro)

    def test_a_pagina_inverte_o_titulo(self):
        empresa = self._empresa("#566B57")
        pagina = self.client.get(f"/{empresa.slug}/").content.decode()
        bloco = pagina[pagina.index("<h1"):pagina.index("</h1>")]
        self.assertIn("text-white", bloco)
