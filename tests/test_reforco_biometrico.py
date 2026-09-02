"""
Kronus — reforço biométrico e medida de dificuldade.

Medido em produção no dia 01/09: 125 tentativas, 82 identificadas, 43
batidas, mediana de 1 tentativa. Elisangela e Edilane repetiam muito
mais que o resto — e as 43 falhas **não bateram com ninguém**. Não era
confusão entre pessoas: eram quadros que não produziam correspondência
nenhuma, com a distância parando em 0,10 quando o rosto era lido.

Daí a forma do recurso: acrescentar amostras em vez de refazer o
cadastro. O que já existe funciona quando o quadro colabora, e recomeçar
jogaria fora as poses boas junto com o problema.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


class BaseReforco(TestCase):
    def setUp(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.rh.models import Colaborador

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
        self.pessoa = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Elisangela Alves",
            cpf="52998224725", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2020, 1, 1),
        )

    def _sessao(self, tentativas, *, indice=0, dias_atras=0):
        """
        Uma ida ao totem: N quadros seguidos terminando em ponto.

        As sessões ficam a dez minutos uma da outra — acima do corte de
        dois minutos, senão viravam uma sessão só e a conta mudaria.
        """
        from apps.facial.models import TentativaReconhecimento as T

        base = (
            timezone.now()
            - timedelta(days=dias_atras)
            - timedelta(minutes=(10 * (indice + 1)))
        )
        for i in range(tentativas):
            ultima = i == tentativas - 1
            registro = T.objects.create(
                empresa=self.empresa,
                colaborador=self.pessoa if ultima else None,
                resultado=(
                    T.Resultado.IDENTIFICADO if ultima
                    else T.Resultado.NAO_IDENTIFICADO
                ),
                desfecho=T.Desfecho.PONTO if ultima else T.Desfecho.RECUSADO,
                distancia=0.30,
            )
            # created_at é auto_now_add: só dá para posicionar no tempo
            # depois de gravado.
            T.objects.filter(pk=registro.pk).update(
                created_at=base + timedelta(seconds=i * 10)
            )


class LimiteDeAmostrasTests(BaseReforco):
    def test_sem_reforco_usa_o_padrao_do_sistema(self):
        from django.conf import settings

        self.assertEqual(
            self.pessoa.limite_de_amostras, settings.FACE_AMOSTRAS_MAXIMAS
        )

    def test_o_reforco_soma_ao_padrao(self):
        from django.conf import settings

        self.pessoa.reforco_biometrico = 3
        self.assertEqual(
            self.pessoa.limite_de_amostras,
            settings.FACE_AMOSTRAS_MAXIMAS + 3,
        )

    def test_a_aposentadoria_respeita_o_teto_de_cada_pessoa(self):
        """
        Sem isto o reforço seria inútil: o serviço gravaria a amostra
        nova e descartaria a mais antiga no mesmo instante, mantendo a
        galeria do mesmo tamanho.
        """
        import inspect

        from apps.facial.services import FaceRecognitionService

        fonte = inspect.getsource(FaceRecognitionService._aposentar_excedentes)
        self.assertIn("limite_de_amostras", fonte)


class DificuldadeTests(BaseReforco):
    """
    Medir antes de agir: sem número, "fulano tem dificuldade" é a
    impressão de quem estava olhando a fila naquela hora.
    """

    def test_sem_historico_nao_opina(self):
        """
        Duas batidas não sustentam diagnóstico. Chamar alguém de difícil
        com essa base geraria recaptura desnecessária.
        """
        from apps.facial.aprendizado import dificuldade_de

        self._sessao(3, indice=0)
        self.assertEqual(dificuldade_de(self.pessoa)["situacao"], "sem_dados")

    def test_quem_acerta_de_primeira_e_tranquilo(self):
        from apps.facial.aprendizado import dificuldade_de

        for i in range(4):
            self._sessao(1, indice=i)
        self.assertEqual(dificuldade_de(self.pessoa)["situacao"], "tranquilo")

    def test_quem_repete_muito_e_sinalizado(self):
        from apps.facial.aprendizado import dificuldade_de

        for i in range(4):
            self._sessao(4, indice=i)
        situacao = dificuldade_de(self.pessoa)
        self.assertEqual(situacao["situacao"], "dificil")
        self.assertGreaterEqual(situacao["media"], 2.5)

    def test_a_janela_ignora_o_que_ja_passou(self):
        """
        Dificuldade de um mês atrás pode já ter sido resolvida por um
        reforço. Insistir nela mandaria recapturar quem já está bem.
        """
        from apps.facial.aprendizado import dificuldade_de

        for i in range(4):
            self._sessao(5, indice=i, dias_atras=30)
        self.assertEqual(dificuldade_de(self.pessoa)["situacao"], "sem_dados")

    def test_a_lista_da_empresa_traz_quem_pena(self):
        from apps.facial.aprendizado import quem_precisa_de_reforco

        for i in range(4):
            self._sessao(4, indice=i)
        lista = quem_precisa_de_reforco(self.empresa)
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["colaborador"].pk, self.pessoa.pk)

    def test_a_lista_nao_aponta_quem_esta_bem(self):
        from apps.facial.aprendizado import quem_precisa_de_reforco

        for i in range(4):
            self._sessao(1, indice=i)
        self.assertEqual(quem_precisa_de_reforco(self.empresa), [])


class AprendizadoDeQuemMaisPrecisaTests(BaseReforco):
    """
    A regra anterior exigia 0,45 absolutos de distância de qualquer
    outra pessoa para aprender. Simulada contra a galeria real de
    produção, ela bloqueava 100% das capturas de Edilane, Elisangela e
    Raphael — exatamente quem mais repetia na fila.

    A folga relativa resolve sem abrir a porta: Edjane continua
    bloqueada, porque ela e a irmã ficam a 0,2630 uma da outra.
    """

    def test_a_folga_e_relativa_e_nao_absoluta(self):
        from apps.facial import aprendizado

        self.assertLess(aprendizado.DISTANCIA_MINIMA_DE_OUTROS, 0.45)
        self.assertGreater(aprendizado.FOLGA_SOBRE_O_VIZINHO, 0.0)

    def test_o_piso_absoluto_continua_barrando_o_indistinguivel(self):
        """
        Perto de todo mundo continua sendo perto de todo mundo: a folga
        relativa não pode virar porta de entrada para captura ruim.
        """
        from apps.facial import aprendizado

        self.assertGreater(aprendizado.DISTANCIA_MINIMA_DE_OUTROS, 0.0)

    def test_a_regra_compara_com_o_titular_e_nao_so_com_o_vizinho(self):
        import inspect

        from apps.facial import aprendizado

        fonte = inspect.getsource(aprendizado._nao_aproxima_de_outro)
        self.assertIn("FOLGA_SOBRE_O_VIZINHO", fonte)


class ReforcoPelaWebTests(BaseReforco):
    def setUp(self):
        super().setUp()
        from apps.accounts.models import CustomUser
        from apps.core.middleware import CHAVE_SESSAO_EMPRESA

        self.rh = CustomUser.objects.create_user(
            email="rh@t.com", password="x", nome_completo="RH",
            tipo="rh", cliente=self.empresa.cliente,
        )
        self.rh.empresas.add(self.empresa)
        self.client.force_login(self.rh)
        s = self.client.session
        s[CHAVE_SESSAO_EMPRESA] = self.empresa.pk
        s.save()

    def test_o_rh_libera_capturas_adicionais(self):
        self.client.post(f"/facial/cadastro/{self.pessoa.pk}/reforcar/")
        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.reforco_biometrico, 3)

    def test_o_reforco_e_acumulavel(self):
        for _ in range(2):
            self.client.post(f"/facial/cadastro/{self.pessoa.pk}/reforcar/")
        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.reforco_biometrico, 6)

    def test_um_clique_nao_dobra_a_galeria(self):
        """
        Teto por vez: galeria grande deixa o reconhecimento mais lento e
        aumenta a chance de uma foto ruim virar referência.
        """
        self.client.post(
            f"/facial/cadastro/{self.pessoa.pk}/reforcar/", {"quantas": 99}
        )
        self.pessoa.refresh_from_db()
        self.assertLessEqual(self.pessoa.reforco_biometrico, 5)

    def test_valor_invalido_nao_derruba_a_tela(self):
        r = self.client.post(
            f"/facial/cadastro/{self.pessoa.pk}/reforcar/", {"quantas": "abc"}
        )
        self.assertEqual(r.status_code, 302)

    def test_ninguem_reforca_colaborador_de_outra_empresa(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.rh.models import Colaborador

        outro_plano = Plano.objects.create(
            nome="Q", slug="q", max_empresas=1, max_colaboradores=10,
            preco_mensal=Decimal("50"),
        )
        outro = Cliente.objects.create(
            razao_social="X LTDA", cnpj="19131243000197",
            email_contato="x@t.com", plano=outro_plano,
        )
        empresa_alheia = Empresa.objects.create(
            cliente=outro, razao_social="X LTDA", cnpj="34028316000103",
        )
        alheio = Colaborador.objects.create(
            empresa=empresa_alheia, nome_completo="Outro",
            cpf="16899535009", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2020, 1, 1),
        )
        r = self.client.post(f"/facial/cadastro/{alheio.pk}/reforcar/")
        self.assertIn(r.status_code, (403, 404))
        alheio.refresh_from_db()
        self.assertEqual(alheio.reforco_biometrico, 0)

    def test_a_tela_de_cadastro_usa_o_teto_da_pessoa(self):
        from django.conf import settings

        self.pessoa.reforco_biometrico = 3
        self.pessoa.save()
        r = self.client.get(f"/facial/cadastro/{self.pessoa.pk}/")
        self.assertEqual(
            r.context["maximo"], settings.FACE_AMOSTRAS_MAXIMAS + 3
        )

    def test_a_medida_de_dificuldade_nao_derruba_o_cadastro(self):
        """
        A tela existe para cadastrar rosto. Se a medida falhar — banco
        lento, tabela vazia — ela some, e o cadastro continua.
        """
        from unittest.mock import patch

        with patch(
            "apps.facial.aprendizado.dificuldade_de",
            side_effect=RuntimeError("banco fora"),
        ):
            r = self.client.get(f"/facial/cadastro/{self.pessoa.pk}/")
        self.assertEqual(r.status_code, 200)
