"""
Kronus — ajuda de tela.

Um sistema de ponto e operado por gente que nao escolheu usa-lo: o RH
recebeu a tarefa, o colaborador tem que bater o ponto. Quem nao escolheu
a ferramenta nao procura documentacao — a ajuda precisa estar na propria
tela, no momento da duvida.
"""
import pathlib

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.core import ajuda
from apps.core.constants import TipoUsuario

RAIZ = pathlib.Path(__file__).resolve().parent.parent


class ConteudoTests(TestCase):
    def test_rota_conhecida_traz_o_proprio_conteudo(self):
        item = ajuda.para_rota("master:dashboard")

        self.assertTrue(item["tem_conteudo"])
        self.assertIn("KS TEC", item["titulo"])
        self.assertTrue(item["itens"])

    def test_rota_desconhecida_cai_no_padrao_em_vez_de_estourar(self):
        """
        Um botao que aparece em algumas telas e some em outras ensina o
        usuario a nao procurar por ele.
        """
        item = ajuda.para_rota("rota:que:nao:existe")

        self.assertFalse(item["tem_conteudo"])
        self.assertTrue(item["titulo"])
        self.assertEqual(item["passos"], [])

    def test_todo_conteudo_tem_titulo_e_resumo(self):
        faltando = [
            rota for rota, item in ajuda.AJUDA.items()
            if not item.get("titulo") or not item.get("resumo")
        ]
        self.assertEqual(faltando, [])

    def test_passos_do_roteiro_tem_texto(self):
        sem_texto = []
        for rota, item in ajuda.AJUDA.items():
            for i, passo in enumerate(item.get("passos", [])):
                if not passo.get("texto"):
                    sem_texto.append(f"{rota}[{i}]")
        self.assertEqual(sem_texto, [])

    def test_as_rotas_documentadas_existem(self):
        """
        Ajuda apontando para rota inexistente e ajuda que nunca aparece.
        """
        from django.urls import NoReverseMatch

        quebradas = []
        for rota in ajuda.AJUDA:
            try:
                reverse(rota)
            except NoReverseMatch as erro:
                # Rotas com argumento levantam por falta de parametro, nao
                # por inexistirem — o que interessa e o nome estar
                # registrado.
                if "not a valid view function or pattern name" in str(erro):
                    quebradas.append(rota)
        self.assertEqual(quebradas, [])


class NaTelaTests(TestCase):
    def setUp(self):
        self.master = CustomUser.objects.create_user(
            email="m@kstec.online", password="x", nome_completo="Master",
            tipo=TipoUsuario.MASTER, is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.master)

    def test_o_botao_aparece_na_tela(self):
        corpo = self.client.get(reverse("master:dashboard")).content.decode()

        self.assertIn('id="ajuda-botao"', corpo)
        self.assertIn("Painel da KS TEC", corpo)

    def test_aparece_tambem_onde_ainda_nao_ha_conteudo(self):
        corpo = self.client.get(reverse("master:plano_lista")).content.decode()
        self.assertIn('id="ajuda-botao"', corpo)

    def test_anonimo_nao_recebe_a_ajuda(self):
        self.client.logout()
        corpo = self.client.get("/").content.decode()
        self.assertNotIn('id="ajuda-botao"', corpo)


class HiddenTests(TestCase):
    """
    `hidden` vale `display: none` pelo navegador, mas qualquer `display`
    do autor vence — e `flex` aparece em quase todo modal. O resultado e
    uma camada invisivel cobrindo a tela e engolindo **todos** os cliques
    do sistema, sem nada que denuncie a causa.
    """

    def test_o_atributo_hidden_vence_o_css(self):
        css = (RAIZ / "static" / "css" / "kronus-design-system.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("[hidden] { display: none !important; }", css)
