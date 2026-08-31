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
