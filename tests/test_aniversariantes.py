"""
Kronus — aniversariantes: calendario, totem e e-mail.

A data ja estava no cadastro; o que faltava era chegar a quem usa. Sao
tres caminhos, e cada um alcanca alguem que os outros nao alcancam: o
calendario e para o RH planejar, a tela do totem alcanca quem nao tem
e-mail, e o e-mail chega a quem nao passa pelo totem naquele dia.
"""
from datetime import date, timedelta

from django.test import TestCase

from apps.rh.aniversariantes import MESES, grade


class GradeDoCalendarioTests(TestCase):
    """
    A grade sai pronta da view.

    Template que faz aritmetica de calendario e template que erra em
    fevereiro — e o erro so aparece uma vez a cada quatro anos.
    """

    def test_semanas_sempre_com_sete_casas(self):
        for mes in range(1, 13):
            for semana in grade(2026, mes, []):
                self.assertEqual(len(semana), 7, f"mes {mes}")

    def test_fevereiro_bissexto_tem_29_dias(self):
        dias = [c["dia"] for s in grade(2024, 2, []) for c in s if c]
        self.assertEqual(max(dias), 29)

    def test_fevereiro_comum_tem_28(self):
        dias = [c["dia"] for s in grade(2026, 2, []) for c in s if c]
        self.assertEqual(max(dias), 28)

    def test_todos_os_dias_do_mes_aparecem_uma_vez(self):
        dias = [c["dia"] for s in grade(2026, 8, []) for c in s if c]
        self.assertEqual(sorted(dias), list(range(1, 32)))

    def test_as_casas_vazias_vem_como_none(self):
        # 1/8/2026 e sabado: cinco casas vazias antes dele.
        primeira = grade(2026, 8, [])[0]
        self.assertEqual(primeira[:5], [None] * 5)

    def test_o_aniversariante_cai_no_proprio_dia(self):
        pessoa = {"id": 1, "nome": "Ana", "dia": 15, "idade": 30,
                  "cargo": "", "empresa": "X", "email": "", "hoje": False}
        celulas = {c["dia"]: c for s in grade(2026, 8, [pessoa]) for c in s if c}
        self.assertEqual(celulas[15]["pessoas"], [pessoa])
        self.assertEqual(celulas[14]["pessoas"], [])

    def test_os_meses_estao_em_portugues(self):
        self.assertEqual(MESES[2], "março")
        self.assertEqual(len(MESES), 12)


class FelicitacaoNoTotemTests(TestCase):
    """A mensagem que aparece na tela de quem acabou de bater."""

    class Pessoa:
        def __init__(self, nascimento, nome="Maria Silva"):
            self.data_nascimento = nascimento
            self.nome_exibicao = nome

    def _felicitar(self, pessoa):
        from apps.api.views_totem import _felicitacao

        return _felicitacao(pessoa)

    def test_parabeniza_no_dia(self):
        hoje = date.today()
        pessoa = self.Pessoa(date(1990, hoje.month, hoje.day))
        self.assertIn("Maria", self._felicitar(pessoa))

    def test_compara_dia_e_mes_e_nao_o_ano(self):
        """
        O ano do nascimento nunca coincide com hoje: comparar a data
        inteira nunca daria aniversario nenhum.
        """
        hoje = date.today()
        self.assertTrue(self._felicitar(self.Pessoa(date(1970, hoje.month, hoje.day))))

    def test_nos_outros_dias_nao_diz_nada(self):
        outro = date.today() + timedelta(days=3)
        self.assertEqual(self._felicitar(self.Pessoa(date(1990, outro.month, outro.day))), "")

    def test_sem_data_de_nascimento_nao_quebra(self):
        self.assertEqual(self._felicitar(self.Pessoa(None)), "")


class DespedidaTests(TestCase):
    """
    "Ate amanha" so quando a jornada acaba.

    A batida do intervalo tambem e uma "saida" no sentido coloquial, e
    quem volta do almoco ouvindo "ate amanha" fica em duvida se o ponto
    entrou no lugar certo.
    """

    class Pessoa:
        nome_exibicao = "Joao Souza"

    class Registro:
        def __init__(self, tipo):
            self.tipo = tipo

    def _despedir(self, tipo):
        from apps.api.views_totem import _despedida

        return _despedida(self.Pessoa(), self.Registro(tipo))

    def test_a_saida_ganha_despedida(self):
        from apps.core.constants import TipoRegistro

        self.assertIn("Joao", self._despedir(TipoRegistro.SAIDA))

    def test_a_entrada_nao(self):
        from apps.core.constants import TipoRegistro

        self.assertEqual(self._despedir(TipoRegistro.ENTRADA), "")

    def test_o_intervalo_nao(self):
        from apps.core.constants import TipoRegistro

        self.assertEqual(self._despedir(TipoRegistro.INTERVALO_INICIO), "")
        self.assertEqual(self._despedir(TipoRegistro.INTERVALO_FIM), "")

    def test_na_sexta_o_ate_amanha_estaria_errado(self):
        from unittest.mock import patch

        from apps.core.constants import TipoRegistro

        sexta = date(2026, 8, 28)   # sexta-feira
        self.assertEqual(sexta.weekday(), 4)
        with patch("apps.api.views_totem.timezone.localdate", return_value=sexta):
            self.assertIn("fim de semana", self._despedir(TipoRegistro.SAIDA))


class CacheDosAniversariantesTests(TestCase):
    """
    A lista vazia nao pode valer o dia inteiro.

    Caso real: o aniversariante do dia nao apareceu em nenhum totem. A
    query estava certa — o cache e que guardava `[]`, gravado quando a
    consulta falhou durante um restart. Com validade ate a meia-noite,
    um blip de segundos apagou o aniversario de alguem por 24 horas.

    "Ninguem faz aniversario hoje" e indistinguivel de "nao consegui
    descobrir", e das duas so a segunda se corrige refazendo a pergunta.
    """

    def _totem(self):
        class Empresas(list):
            pass

        class TotemFalso:
            pk = 4242

            def empresas_atendidas(self):
                raise RuntimeError("banco fora do ar")

        return TotemFalso()

    def test_a_falha_nao_entra_no_cache(self):
        from django.core.cache import cache
        from django.utils import timezone

        from apps.api.views_totem import _aniversariantes_de_hoje

        totem = self._totem()
        chave = f"kronus:aniversarios:{totem.pk}:{timezone.localdate().isoformat()}"
        cache.delete(chave)

        self.assertEqual(_aniversariantes_de_hoje(totem), [])
        # O ponto do teste: nada foi guardado, entao a proxima pergunta
        # volta ao banco em vez de repetir a falha ate a meia-noite.
        self.assertIsNone(cache.get(chave))

    def test_a_lista_expira_rapido_mesmo_quando_encontra_alguem(self):
        """
        Caso real: a data de nascimento foi corrigida e o totem continuou
        parabenizando o dia inteiro.

        A versao anterior guardava a lista cheia ate a meia-noite, com o
        argumento de que "a lista nao muda durante o dia". Ela muda —
        quem corrige uma data, cadastra ou desativa alguem muda a lista.
        E o pior nao era o erro: era a pessoa ver que corrigir nao
        adiantou.
        """
        import inspect

        from apps.api import views_totem

        fonte = inspect.getsource(views_totem._aniversariantes_de_hoje)
        self.assertIn("cache.set(chave, nomes, 300)", fonte)
        self.assertNotIn("ate_meia_noite", fonte)


class PaginaDoCalendarioTests(TestCase):
    """
    A pagina precisa abrir.

    Ela quebrou em producao com FieldError: `select_related("cargo")`,
    sendo que `cargo` e texto livre e a relacao chama `cargo_ref`. Um
    erro de nome de campo derrubou a tela inteira, e nenhum teste pegou
    porque nenhum chamava `do_mes` contra o banco de verdade.
    """

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.rh.models import Colaborador

        plano = Plano.objects.create(
            nome="P", slug="p", max_empresas=5, max_colaboradores=50,
            preco_mensal=Decimal("100"),
        )
        cliente = Cliente.objects.create(
            razao_social="C LTDA", nome_fantasia="C", cnpj="11222333000181",
            email_contato="c@t.com", plano=plano,
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="E LTDA", cnpj="60746948000112",
        )
        self.pessoa = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Fulano de Tal",
            cpf="52998224725", data_nascimento=date(1990, 9, 15),
            data_admissao=date(2020, 1, 10), cargo="Analista",
        )

    def test_monta_a_lista_sem_estourar(self):
        from apps.rh.aniversariantes import do_mes

        lista = do_mes([self.empresa], 2026, 9)
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["dia"], 15)
        self.assertEqual(lista[0]["idade"], 36)

    def test_usa_o_cargo_de_texto_livre_quando_nao_ha_cadastro(self):
        from apps.rh.aniversariantes import do_mes

        self.assertEqual(do_mes([self.empresa], 2026, 9)[0]["cargo"], "Analista")

    def test_o_cargo_cadastrado_vence_o_texto_livre(self):
        from apps.rh.models import Cargo

        cargo = Cargo.objects.create(empresa=self.empresa, nome="Gerente")
        self.pessoa.cargo_ref = cargo
        self.pessoa.save(update_fields=["cargo_ref"])

        from apps.rh.aniversariantes import do_mes

        self.assertEqual(do_mes([self.empresa], 2026, 9)[0]["cargo"], "Gerente")

    def test_mes_sem_aniversariante_devolve_vazio(self):
        from apps.rh.aniversariantes import do_mes

        self.assertEqual(do_mes([self.empresa], 2026, 3), [])
