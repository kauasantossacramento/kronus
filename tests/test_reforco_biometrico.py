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


class PisoDoAprendizadoTests(BaseReforco):
    """
    O piso do aprendizado automático fica em 0,45 — e isso é resultado
    de medição, não de inércia.

    A tentativa era baixá-lo para 0,22 com folga relativa sobre o
    vizinho, para que Elisangela e Edilane conseguissem aprender.
    Simulado contra a galeria real de produção, com a galeria evoluindo
    a cada amostra como acontece de verdade:

      regra de hoje  — 30 amostras aprendidas, 0 pares perigosos novos
      regra frouxa   — 22 amostras aprendidas, 5 pares perigosos novos

    Pior nos dois eixos, e as irmãs continuavam sem aprender. O motivo:
    as travas relativas dependem de o titular já ter amostras. Quem tem
    poucas cai só no piso, e a 0,22 entra captura a 0,36 de outra
    pessoa — foi assim que os cinco pares nasceram.

    Quem precisa de mais foto recebe foto, pelo reforço biométrico, com
    alguém olhando. Afrouxar a regra automática cobra da fila inteira.
    """

    def test_o_piso_nao_cede(self):
        from apps.facial import aprendizado

        self.assertEqual(aprendizado.DISTANCIA_MINIMA_DE_OUTROS, 0.45)

    def test_a_medicao_nao_altera_regra_nenhuma(self):
        """
        `dificuldade_de` e `quem_precisa_de_reforco` são leitura pura:
        se um dia passarem a decidir o que entra na galeria, esta
        separação some sem ninguém perceber.
        """
        import inspect

        from apps.facial import aprendizado

        for funcao in (aprendizado.dificuldade_de,
                       aprendizado.quem_precisa_de_reforco):
            fonte = inspect.getsource(funcao)
            self.assertNotIn("save(", fonte)
            self.assertNotIn("create(", fonte)
            self.assertNotIn("DISTANCIA_MINIMA_DE_OUTROS", fonte)


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


class OrientacaoNoTotemTests(TestCase):
    """
    Quem já tem cadastro e captura de novo precisa de outra **condição**,
    e não de mais ângulos.

    Elisangela falha no reconhecimento com cinco amostras de qualidade 74
    a 80 — todas capturadas às 16h03 de um mesmo dia. Cinco poses, uma
    luz só. Repetir a sessão de boa fé rende mais do mesmo, e a tela é o
    único lugar onde dá para avisar o operador a tempo.
    """

    def _js(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        return (
            raiz / "apps" / "totem" / "static" / "totem" / "js"
            / "manutencao.js"
        ).read_text(encoding="utf-8")

    def test_a_tela_pede_condicao_diferente(self):
        js = self._js()
        self.assertIn("orientacaoDeReforco", js)
        self.assertIn("condição diferente", js)

    def test_o_aviso_e_falado_e_nao_so_escrito(self):
        """
        Quem está capturando olha para a câmera, não para a tela — foi
        por isso que as instruções de pose já saem em voz.
        """
        js = self._js()
        # A partir da DEFINICAO, e nao da chamada: `_atualizarReforco`
        # aparece antes no arquivo, dentro de `_abrirCaptura`.
        trecho = js[js.index("_atualizarReforco: function"):]
        self.assertIn("Voz.falar", trecho[:700])

    def test_quem_nao_tem_cadastro_nao_ve_aviso_nenhum(self):
        """
        Primeiro cadastro não é reforço: o aviso ali seria ruído.
        """
        js = self._js()
        trecho = js[js.index("function orientacaoDeReforco"):]
        self.assertIn("if (!amostras) return '';", trecho[:400])

    def test_a_tela_diz_quando_a_captura_vai_substituir(self):
        """
        Com o cadastro cheio a amostra nova aposenta a pior. O operador
        precisa saber disso antes de capturar, e não depois.
        """
        js = self._js()
        self.assertIn("substitui", js)

    def test_o_teto_vem_por_pessoa_e_nao_do_sistema(self):
        """
        O reforço é individual: usar o padrão global mostraria o número
        errado justamente para quem recebeu capturas a mais.
        """
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        api = (
            raiz / "apps" / "api" / "views_manutencao.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"limite": p.limite_de_amostras', api)
        self.assertIn("this.pessoa.limite", self._js())

    def test_o_aviso_existe_na_pagina(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        pagina = (
            raiz / "apps" / "totem" / "templates" / "totem" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="manut-reforco"', pagina)
