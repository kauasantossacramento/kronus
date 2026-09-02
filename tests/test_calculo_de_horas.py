"""
Kronus — o líquido de horas do dia e da folha.

Conferido contra a produção em 02/09/2026, com 382 dias fechados. Duas
contas estavam certas e duas erradas:

  certo — saldo do dia = trabalhado − esperado, em 382 de 382
  certo — a cadeia do acumulado, sem um furo

  errado — 117 faltas anteriores ao primeiro ponto da empresa. Só a
           INVICTA acumulou 116, somando 928 horas de débito inventado;
           Adriana e Marlene abriam o espelho em −240h cada, sem nunca
           terem faltado um dia.
  errado — nove pessoas sem escala levavam falta em sábado e domingo,
           porque sem escala o sistema cobrava jornada nos sete dias.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


class BaseHoras(TestCase):
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
            empresa=self.empresa, nome_completo="Adriana Moreira",
            cpf="52998224725", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2025, 3, 14),
        )


class SemEscalaTests(TestCase):
    """
    Sem escala o sistema tem de supor alguma coisa — e a suposição da
    CLT é a semana de segunda a sexta, não sete dias.
    """

    def _calculadora(self):
        from apps.ponto.calculators import CalculadoraJornada

        return CalculadoraJornada(escala=None, config=None)

    def test_dia_util_cobra_a_jornada(self):
        # 2026-09-02 é uma quarta-feira.
        esperado = self._calculadora()._minutos_esperados(
            date(2026, 9, 2), False
        )
        self.assertGreater(esperado, 0)

    def test_sabado_nao_cobra_jornada(self):
        # 2026-09-05 é um sábado.
        self.assertEqual(
            self._calculadora()._minutos_esperados(date(2026, 9, 5), False), 0
        )

    def test_domingo_nao_cobra_jornada(self):
        # 2026-09-06 é um domingo.
        self.assertEqual(
            self._calculadora()._minutos_esperados(date(2026, 9, 6), False), 0
        )

    def test_domingo_sem_ponto_nao_vira_falta(self):
        """
        Era isto que aparecia no espelho: falta num domingo em que
        ninguém foi chamado para trabalhar.
        """
        resultado = self._calculadora().calcular(date(2026, 9, 6), [])
        self.assertEqual(resultado.saldo_dia, 0)

    def test_feriado_continua_sem_jornada(self):
        self.assertEqual(
            self._calculadora()._minutos_esperados(
                date(2026, 9, 2), True
            ),
            0,
        )


class InicioDaApuracaoTests(BaseHoras):
    """
    Só uma declaração explícita corta a apuração.

    A primeira versão deduzia a data pelo cadastro do colaborador, e a
    dedução era pior que não cortar: um dia importado depois, ou
    reprocessado após uma correção retroativa, sumia sem aviso. Foram 27
    testes de banco de horas quebrando de uma vez — o sistema recusando
    apurar dias que tinham marcação de verdade.
    """

    def test_sem_ninguem_declarar_vale_a_admissao(self):
        from apps.ponto.services import ConsolidacaoService

        self.assertEqual(
            ConsolidacaoService.inicio_da_apuracao(self.pessoa),
            self.pessoa.data_admissao,
        )

    def test_a_empresa_pode_declarar_a_data(self):
        from apps.clientes.models import ConfiguracaoEmpresa
        from apps.ponto.services import ConsolidacaoService

        ConfiguracaoEmpresa.objects.update_or_create(
            empresa=self.empresa,
            defaults={"inicio_do_controle": date(2026, 9, 1)},
        )
        self.empresa.refresh_from_db()
        self.assertEqual(
            ConsolidacaoService.inicio_da_apuracao(self.pessoa),
            date(2026, 9, 1),
        )

    def test_admissao_futura_adia_a_apuracao(self):
        """Quem ainda não começou não pode faltar."""
        from apps.ponto.services import ConsolidacaoService

        self.pessoa.data_admissao = timezone.localdate() + timedelta(days=5)
        self.pessoa.save()
        self.assertEqual(
            ConsolidacaoService.inicio_da_apuracao(self.pessoa),
            self.pessoa.data_admissao,
        )

    def test_a_data_de_cadastro_nao_corta_nada(self):
        """
        O que fecha a porta é a decisão de alguém, e não o dia em que a
        linha entrou no banco. Um dia continua sendo apurado, tenha o
        cadastro a idade que tiver.
        """
        from apps.ponto.models import BancoHoras
        from apps.ponto.services import ConsolidacaoService

        antes_do_cadastro = self.pessoa.created_at.date() - timedelta(days=20)
        ConsolidacaoService.consolidar_dia(self.pessoa, antes_do_cadastro)
        self.assertTrue(
            BancoHoras.objects.filter(
                colaborador=self.pessoa, data=antes_do_cadastro
            ).exists()
        )


class NaoInventaFaltaTests(BaseHoras):
    def setUp(self):
        super().setUp()
        from apps.clientes.models import ConfiguracaoEmpresa

        ConfiguracaoEmpresa.objects.update_or_create(
            empresa=self.empresa,
            defaults={"inicio_do_controle": date(2026, 9, 1)},
        )
        self.empresa.refresh_from_db()

    def test_dia_anterior_ao_declarado_nao_gera_registro(self):
        from apps.ponto.models import BancoHoras
        from apps.ponto.services import ConsolidacaoService

        ConsolidacaoService.consolidar_dia(self.pessoa, date(2026, 8, 20))
        self.assertFalse(
            BancoHoras.objects.filter(
                colaborador=self.pessoa, data=date(2026, 8, 20)
            ).exists()
        )

    def test_o_proprio_dia_declarado_ja_conta(self):
        """
        A trava não pode virar desculpa para não apurar nada: o dia em
        que o controle passa a valer já é apurado.
        """
        from apps.ponto.models import BancoHoras
        from apps.ponto.services import ConsolidacaoService

        ConsolidacaoService.consolidar_dia(self.pessoa, date(2026, 9, 1))
        self.assertTrue(
            BancoHoras.objects.filter(
                colaborador=self.pessoa, data=date(2026, 9, 1)
            ).exists()
        )

    def test_o_que_ja_estava_fechado_nao_e_mexido(self):
        """
        Fechamento é fechamento: a trava age sobre o que ainda vai ser
        calculado, e não sobre folha já encerrada.
        """
        from apps.ponto.models import BancoHoras
        from apps.ponto.services import ConsolidacaoService

        antigo = date(2026, 8, 20)
        BancoHoras.objects.create(
            empresa=self.empresa, colaborador=self.pessoa, data=antigo,
            minutos_trabalhados=480, minutos_esperados=480,
            saldo_dia=0, saldo_acumulado=0, status="completo", fechado=True,
        )
        ConsolidacaoService.consolidar_dia(self.pessoa, antigo)
        self.assertTrue(
            BancoHoras.objects.filter(
                colaborador=self.pessoa, data=antigo, fechado=True
            ).exists()
        )


class LiquidoDoPeriodoTests(BaseHoras):
    """
    O líquido é o que sobra depois de somar o que faltou com o que
    excedeu — e é ele que vai para a folha.
    """

    def _dia(self, quando, saldo, *, trabalhado=480, esperado=480, extras=0):
        from apps.ponto.models import BancoHoras

        return BancoHoras.objects.create(
            empresa=self.empresa, colaborador=self.pessoa, data=quando,
            minutos_trabalhados=trabalhado, minutos_esperados=esperado,
            minutos_extras=extras, saldo_dia=saldo, saldo_acumulado=0,
            status="completo",
        )

    def test_o_excesso_abate_o_que_faltou(self):
        from apps.ponto.services import ConsolidacaoService

        base = date(2026, 9, 7)
        self._dia(base, +60, trabalhado=540, extras=60)
        self._dia(base + timedelta(days=1), -30, trabalhado=450)
        resumo = ConsolidacaoService.resumo_periodo(
            self.pessoa, base, base + timedelta(days=1)
        )
        self.assertEqual(resumo["saldo_periodo"], 30)
        self.assertEqual(resumo["credito"], 60)
        # Debito e devolvido como grandeza positiva: quem le a folha
        # ve "faltaram 30 min", e nao "-30 de falta".
        self.assertEqual(resumo["debito"], 30)

    def test_o_saldo_final_soma_o_que_vinha_de_antes(self):
        """
        Sem isto o banco de horas recomeçaria do zero a cada mês, e o
        crédito de quem trabalhou a mais sumiria na virada.
        """
        from apps.ponto.models import BancoHoras
        from apps.ponto.services import ConsolidacaoService

        anterior = self._dia(date(2026, 9, 1), +120)
        BancoHoras.objects.filter(pk=anterior.pk).update(saldo_acumulado=120)

        base = date(2026, 9, 7)
        self._dia(base, -60, trabalhado=420)
        resumo = ConsolidacaoService.resumo_periodo(self.pessoa, base, base)
        self.assertEqual(resumo["saldo_anterior"], 120)
        self.assertEqual(resumo["saldo_periodo"], -60)
        self.assertEqual(resumo["saldo_final"], 60)

    def test_periodo_sem_dia_fechado_nao_inventa_numero(self):
        from apps.ponto.services import ConsolidacaoService

        resumo = ConsolidacaoService.resumo_periodo(
            self.pessoa, date(2026, 9, 7), date(2026, 9, 8)
        )
        self.assertEqual(resumo["saldo_periodo"], 0)
        self.assertEqual(resumo["minutos_trabalhados"], 0)


class ExtraAcimaDoTetoTests(BaseHoras):
    """
    Encontrado na produção e **mantido de propósito**: em 01/09 o
    Valteir teve saldo de +142 e hora extra de 120. Os 22 minutos de
    diferença são o teto diário do Art. 59 da CLT.

    Eles não somem — entram no saldo do banco de horas. O que o teto
    limita é quanto vira hora extra remunerada no dia, e não quanto a
    pessoa trabalhou.
    """

    def test_o_teto_limita_a_extra_mas_nao_o_saldo(self):
        from apps.ponto.calculators import CalculadoraJornada

        calc = CalculadoraJornada(escala=None, config=None)
        resultado = calc.calcular(date(2026, 9, 2), [])
        resultado.minutos_trabalhados = 622
        resultado.minutos_esperados = 480
        calc._avaliar_extras(resultado)
        resultado.saldo_dia = (
            resultado.minutos_trabalhados - resultado.minutos_esperados
        )

        self.assertEqual(resultado.saldo_dia, 142)
        self.assertEqual(resultado.minutos_extras, calc.limite_extra_diaria_min)
        self.assertLess(resultado.minutos_extras, resultado.saldo_dia)

    def test_minuto_residual_dentro_da_tolerancia_nao_vira_extra(self):
        """
        Art. 58 §1º: a tolerância protege os dois lados. Cinco minutos a
        mais na saída não são hora extra.
        """
        from apps.ponto.calculators import CalculadoraJornada

        calc = CalculadoraJornada(escala=None, config=None)
        resultado = calc.calcular(date(2026, 9, 2), [])
        resultado.minutos_trabalhados = 480 + calc.tolerancia_min
        resultado.minutos_esperados = 480
        calc._avaliar_extras(resultado)
        self.assertEqual(resultado.minutos_extras, 0)


class ConfiguracaoSalvavelTests(TestCase):
    """
    A aba de jornada não salvava — e o motivo não aparecia na tela.

    `regime_horas` é obrigatório e nenhuma seção o desenhava. O navegador
    não enviava o campo, o form recusava por "campo obrigatório", e o
    erro era renderizado dentro da seção que não existe. O RH clicava em
    "Salvar configurações", a página voltava igual, e nada era gravado.

    Já tinha acontecido antes com `minutos_entre_marcacoes` — a página
    agrupa por prefixo do nome, então todo campo novo nasce órfão. Este
    teste é o que fecha a porta.
    """

    def _prefixos(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        pagina = (
            raiz / "apps" / "rh" / "templates" / "rh" / "configuracoes"
            / "empresa.html"
        ).read_text(encoding="utf-8")

        prefixos = []
        for linha in pagina.splitlines():
            if "campos=form_config" in linha and 'prefixos="' in linha:
                prefixos += linha.split('prefixos="')[1].split('"')[0].split(",")
        return [p.strip() for p in prefixos if p.strip()]

    def test_todo_campo_do_form_aparece_em_alguma_secao(self):
        from apps.clientes.forms import ConfiguracaoEmpresaForm

        prefixos = self._prefixos()
        orfaos = [
            nome for nome in ConfiguracaoEmpresaForm().fields
            if not any(nome.startswith(p) for p in prefixos)
        ]
        self.assertEqual(
            orfaos, [],
            "Campos sem seção na página: %s. Um campo que a página não "
            "desenha não chega no POST — se for obrigatório, trava o "
            "save inteiro; se for checkbox, é gravado como False." % orfaos,
        )

    def test_os_avisos_nao_pertencem_a_este_form(self):
        """
        A aba de notificações grava esses campos na mão. Se eles também
        estivessem aqui, salvar a jornada desligaria todos os avisos —
        inclusive o de totem offline.
        """
        from apps.clientes.forms import ConfiguracaoEmpresaForm

        campos = ConfiguracaoEmpresaForm().fields
        for nome in ("notif_totem_offline", "notif_esq_ponto",
                     "email_notificacoes"):
            self.assertNotIn(nome, campos)

    def test_o_inicio_do_controle_e_editavel_pelo_rh(self):
        from apps.clientes.forms import ConfiguracaoEmpresaForm

        self.assertIn("inicio_do_controle", ConfiguracaoEmpresaForm().fields)


class SalvarDeVerdadeTests(TestCase):
    """
    A prova funcional: preencher a página como o navegador preenche e
    conferir que o valor mudou no banco.
    """

    def setUp(self):
        from apps.accounts.models import CustomUser
        from apps.clientes.models import Cliente, Empresa
        from apps.core.middleware import CHAVE_SESSAO_EMPRESA
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
        user = CustomUser.objects.create_user(
            email="rh@t.com", password="x", nome_completo="RH",
            tipo="rh", cliente=cliente,
        )
        user.empresas.add(self.empresa)
        self.client.force_login(user)
        sessao = self.client.session
        sessao[CHAVE_SESSAO_EMPRESA] = self.empresa.pk
        sessao.save()

    def _como_o_navegador_envia(self, resposta):
        """Só o que a página desenha chega ao POST."""
        html = resposta.content.decode()
        dados = {}
        for form in ("form_config", "form_operacao"):
            for campo in resposta.context[form]:
                if 'name="%s"' % campo.name not in html:
                    continue
                valor = campo.value()
                if valor is None or valor is False:
                    continue
                dados[campo.name] = "on" if valor is True else valor
        return dados

    def test_a_pagina_de_jornada_salva(self):
        pagina = self.client.get("/rh/configuracoes/")
        dados = self._como_o_navegador_envia(pagina)
        dados["tolerancia_atraso_min"] = 9

        self.client.post("/rh/configuracoes/", dados)

        config = self.empresa.configuracao
        config.refresh_from_db()
        self.assertEqual(config.tolerancia_atraso_min, 9)

    def test_salvar_a_jornada_nao_desliga_os_avisos(self):
        config = self.empresa.configuracao
        config.notif_totem_offline = True
        config.notif_esq_ponto = True
        config.save()

        pagina = self.client.get("/rh/configuracoes/")
        self.client.post(
            "/rh/configuracoes/", self._como_o_navegador_envia(pagina)
        )

        config.refresh_from_db()
        self.assertTrue(config.notif_totem_offline)
        self.assertTrue(config.notif_esq_ponto)


class ExcecaoPorPessoaTests(BaseHoras):
    """
    Caso real do grupo INVICTA.

    O cliente declarou que o controle passa a valer em 01/09/2026 — de
    31/08 para trás, nada conta. Mas Adriana e Marlene já batiam ponto
    pela empresa da pessoa física desde 31/08, e o dia de trabalho delas
    é real.

    Sem exceção por pessoa, honrar a data do grupo apagaria trabalho
    efetivamente prestado; e antecipar a data do grupo para 31/08 daria
    falta a um terceiro colega que só começou em 01/09. As duas coisas
    erradas, por falta de um lugar para dizer "esta pessoa é diferente".
    """

    def setUp(self):
        super().setUp()
        from apps.clientes.models import ConfiguracaoEmpresa

        ConfiguracaoEmpresa.objects.update_or_create(
            empresa=self.empresa,
            defaults={"inicio_do_controle": date(2026, 9, 1)},
        )
        self.empresa.refresh_from_db()

    def test_sem_excecao_vale_a_data_da_empresa(self):
        from apps.ponto.services import ConsolidacaoService

        self.assertEqual(
            ConsolidacaoService.inicio_da_apuracao(self.pessoa),
            date(2026, 9, 1),
        )

    def test_a_data_da_pessoa_substitui_a_da_empresa(self):
        from apps.ponto.services import ConsolidacaoService

        self.pessoa.inicio_do_controle = date(2026, 8, 31)
        self.pessoa.save()
        self.assertEqual(
            ConsolidacaoService.inicio_da_apuracao(self.pessoa),
            date(2026, 8, 31),
        )

    def test_a_excecao_nao_alcanca_o_periodo_anterior_a_admissao(self):
        """
        A exceção libera o dia de trabalho, e não uma data arbitrária:
        antes de ser admitida a pessoa não devia jornada a ninguém.
        """
        from apps.ponto.services import ConsolidacaoService

        self.pessoa.inicio_do_controle = date(2020, 1, 1)
        self.pessoa.save()
        self.assertEqual(
            ConsolidacaoService.inicio_da_apuracao(self.pessoa),
            self.pessoa.data_admissao,
        )

    def test_o_colega_sem_excecao_continua_na_data_do_grupo(self):
        from apps.ponto.services import ConsolidacaoService
        from apps.rh.models import Colaborador

        colega = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Colega Sem Excecao",
            cpf="16899535009", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2024, 1, 1),
        )
        self.pessoa.inicio_do_controle = date(2026, 8, 31)
        self.pessoa.save()

        self.assertEqual(
            ConsolidacaoService.inicio_da_apuracao(colega), date(2026, 9, 1)
        )
