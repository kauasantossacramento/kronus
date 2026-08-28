"""
Kronus — testes de cálculo de jornada e banco de horas (Fase 2).

O cálculo trabalhista é a parte do sistema com consequência jurídica
direta. Estes testes fixam o comportamento das regras da CLT que o
plano determina na Seção 8.4.
"""
from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import StatusDia, TipoEscala
from apps.master.models import Plano
from apps.ponto.calculators import (
    CalculadoraBancoHoras,
    CalculadoraHorasExtras,
    CalculadoraJornada,
    proximo_tipo_esperado,
)
from apps.ponto.models import BancoHoras, EscalaTrabalho
from apps.ponto.services import ConsolidacaoService, RegistroPontoService
from apps.rh.models import Colaborador

FUSO = timezone.get_fixed_timezone(-180)  # UTC-3

JORNADA_COMERCIAL = {
    "dias": {
        "0": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "1": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "2": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "3": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "4": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "5": None,
        "6": None,
    }
}


class MarcacaoFalsa:
    """Dublê leve de RegistroPonto para testar a calculadora isolada."""

    def __init__(self, dia: date, hora: str):
        h, m = (int(p) for p in hora.split(":"))
        self.data_hora = datetime.combine(dia, time(h, m), tzinfo=FUSO)


class ConfigFalsa:
    """Dublê de ConfiguracaoEmpresa com os padrões da CLT."""

    tolerancia_atraso_min = 5
    intervalo_minimo_min = 60
    jornada_diaria_padrao_min = 480
    limite_hora_extra_diaria_min = 120
    hora_extra_percentual = 50
    hora_extra_percentual_2 = 70
    hora_extra_percentual_dsr = 100
    adicional_noturno = True
    adicional_noturno_percentual = 20
    hora_ini_noturno = time(22, 0)
    hora_fim_noturno = time(5, 0)
    hora_noturna_reduzida = True
    modo_compensacao = True
    prazo_compensacao_meses = 6


# ══════════════════════════════════════════════════════════════
# Escala de trabalho
# ══════════════════════════════════════════════════════════════
class EscalaTests(TestCase):
    def setUp(self):
        self.escala = EscalaTrabalho(
            nome="Comercial",
            tipo=TipoEscala.FIXA,
            jornada_config=JORNADA_COMERCIAL,
            carga_diaria_min=480,
        )

    def test_dia_util_tem_oito_horas(self):
        segunda = date(2026, 8, 24)  # segunda-feira
        self.assertEqual(self.escala.minutos_esperados(segunda), 480)

    def test_fim_de_semana_nao_tem_jornada(self):
        sabado, domingo = date(2026, 8, 29), date(2026, 8, 30)
        self.assertEqual(self.escala.minutos_esperados(sabado), 0)
        self.assertEqual(self.escala.minutos_esperados(domingo), 0)
        self.assertFalse(self.escala.eh_dia_util(domingo))

    def test_jornada_que_vira_o_dia(self):
        escala = EscalaTrabalho(
            nome="Noturna",
            tipo=TipoEscala.FIXA,
            jornada_config={"dias": {"0": {"entrada": "22:00", "saida": "06:00"}}},
        )
        self.assertEqual(escala.minutos_esperados(date(2026, 8, 24)), 480)

    def test_escala_12x36_alterna_dias(self):
        escala = EscalaTrabalho(
            nome="12x36",
            tipo=TipoEscala.ESCALA_12X36,
            data_referencia=date(2026, 8, 24),
            jornada_config={"padrao_12x36": {"entrada": "07:00", "saida": "19:00"}},
        )
        self.assertEqual(escala.minutos_esperados(date(2026, 8, 24)), 720)  # trabalha
        self.assertEqual(escala.minutos_esperados(date(2026, 8, 25)), 0)    # folga
        self.assertEqual(escala.minutos_esperados(date(2026, 8, 26)), 720)  # trabalha

    def test_escala_flexivel_usa_a_carga_diaria(self):
        escala = EscalaTrabalho(
            nome="Flexível", tipo=TipoEscala.FLEXIVEL, carga_diaria_min=360
        )
        self.assertEqual(escala.minutos_esperados(date(2026, 8, 24)), 360)


# ══════════════════════════════════════════════════════════════
# Calculadora de jornada
# ══════════════════════════════════════════════════════════════
class CalculadoraJornadaTests(TestCase):
    def setUp(self):
        self.escala = EscalaTrabalho(
            nome="Comercial",
            tipo=TipoEscala.FIXA,
            tolerancia_min=5,
            jornada_config=JORNADA_COMERCIAL,
            carga_diaria_min=480,
        )
        self.calc = CalculadoraJornada(escala=self.escala, config=ConfigFalsa())
        self.dia = date(2026, 8, 24)  # segunda

    def marcacoes(self, *horas):
        return [MarcacaoFalsa(self.dia, hora) for hora in horas]

    def test_jornada_completa_fecha_em_zero(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:00", "12:00", "13:00", "17:00")
        )
        self.assertEqual(resultado.minutos_trabalhados, 480)
        self.assertEqual(resultado.minutos_esperados, 480)
        self.assertEqual(resultado.saldo_dia, 0)
        self.assertEqual(resultado.status, StatusDia.COMPLETO)

    def test_intervalo_e_descontado(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:00", "12:00", "13:00", "17:00")
        )
        self.assertEqual(resultado.minutos_intervalo, 60)

    def test_hora_extra_alem_da_tolerancia(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:00", "12:00", "13:00", "18:00")
        )
        self.assertEqual(resultado.minutos_trabalhados, 540)
        self.assertEqual(resultado.minutos_extras, 60)
        self.assertEqual(resultado.saldo_dia, 60)

    def test_excedente_dentro_da_tolerancia_nao_vira_extra(self):
        """Art. 58 §1º: até 5 min por marcação não são jornada extraordinária."""
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:00", "12:00", "13:00", "17:04")
        )
        self.assertEqual(resultado.minutos_extras, 0)

    def test_extra_respeita_o_limite_diario(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:00", "12:00", "13:00", "22:00")
        )
        self.assertEqual(resultado.minutos_extras, 120)  # teto de 2h

    def test_atraso_acima_da_tolerancia(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:20", "12:00", "13:00", "17:00")
        )
        self.assertEqual(resultado.minutos_atraso, 20)
        self.assertEqual(resultado.saldo_dia, -20)

    def test_atraso_dentro_da_tolerancia_e_ignorado(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:04", "12:00", "13:00", "17:04")
        )
        self.assertEqual(resultado.minutos_atraso, 0)

    def test_saida_antecipada(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:00", "12:00", "13:00", "16:00")
        )
        self.assertEqual(resultado.minutos_saida_antecipada, 60)
        self.assertEqual(resultado.saldo_dia, -60)

    def test_marcacoes_impares_deixam_o_dia_incompleto(self):
        resultado = self.calc.calcular(self.dia, self.marcacoes("08:00", "12:00", "13:00"))
        self.assertTrue(resultado.marcacoes_impares)
        self.assertEqual(resultado.status, StatusDia.INCOMPLETO)
        self.assertIn("ímpar", resultado.observacao)

    def test_dia_sem_marcacao_e_falta(self):
        resultado = self.calc.calcular(self.dia, [])
        self.assertEqual(resultado.status, StatusDia.FALTA)
        self.assertEqual(resultado.saldo_dia, -480)

    def test_folga_sem_marcacao(self):
        domingo = date(2026, 8, 30)
        resultado = self.calc.calcular(domingo, [])
        self.assertEqual(resultado.status, StatusDia.FOLGA)
        self.assertEqual(resultado.saldo_dia, 0)

    def test_trabalho_em_folga_e_todo_credito(self):
        domingo = date(2026, 8, 30)
        resultado = self.calc.calcular(
            domingo, [MarcacaoFalsa(domingo, "08:00"), MarcacaoFalsa(domingo, "12:00")]
        )
        self.assertEqual(resultado.minutos_esperados, 0)
        self.assertEqual(resultado.saldo_dia, 240)

    def test_atestado_zera_o_debito(self):
        resultado = self.calc.calcular(self.dia, [], coberto_por_atestado=True)
        self.assertEqual(resultado.status, StatusDia.ATESTADO)
        self.assertEqual(resultado.saldo_dia, 0)

    def test_justificativa_aprovada_abona_o_dia(self):
        resultado = self.calc.calcular(self.dia, [], justificado=True)
        self.assertEqual(resultado.status, StatusDia.JUSTIFICADO)
        self.assertEqual(resultado.saldo_dia, 0)

    def test_feriado_nao_gera_debito(self):
        resultado = self.calc.calcular(self.dia, [], eh_feriado=True)
        self.assertEqual(resultado.status, StatusDia.FERIADO)
        self.assertEqual(resultado.minutos_esperados, 0)

    def test_jornada_longa_sem_intervalo_e_sinalizada(self):
        """Art. 71: acima de 6h exige intervalo."""
        resultado = self.calc.calcular(self.dia, self.marcacoes("08:00", "17:00"))
        self.assertTrue(resultado.intervalo_irregular)
        self.assertIn("Art. 71", resultado.observacao)

    def test_intervalo_curto_e_sinalizado(self):
        resultado = self.calc.calcular(
            self.dia, self.marcacoes("08:00", "12:00", "12:20", "17:00")
        )
        self.assertTrue(resultado.intervalo_irregular)


# ══════════════════════════════════════════════════════════════
# Adicional noturno — Art. 73 CLT
# ══════════════════════════════════════════════════════════════
class AdicionalNoturnoTests(TestCase):
    def setUp(self):
        self.calc = CalculadoraJornada(config=ConfigFalsa())
        self.dia = date(2026, 8, 24)

    def test_jornada_diurna_nao_tem_horas_noturnas(self):
        marcacoes = [MarcacaoFalsa(self.dia, "08:00"), MarcacaoFalsa(self.dia, "17:00")]
        resultado = self.calc.calcular(self.dia, marcacoes)
        self.assertEqual(resultado.minutos_noturnos, 0)

    def test_horas_apos_as_22h_contam_como_noturnas(self):
        """
        Das 22h à 0h são 120 minutos reais. Com a hora noturna reduzida
        (52min30s), equivalem a 137 minutos-relógio.
        """
        marcacoes = [
            MarcacaoFalsa(self.dia, "20:00"),
            MarcacaoFalsa(self.dia + timedelta(days=1), "00:00"),
        ]
        resultado = self.calc.calcular(self.dia, marcacoes)
        self.assertEqual(resultado.minutos_noturnos, 137)

    def test_sem_reducao_conta_os_minutos_reais(self):
        config = ConfigFalsa()
        config.hora_noturna_reduzida = False
        calc = CalculadoraJornada(config=config)
        marcacoes = [
            MarcacaoFalsa(self.dia, "20:00"),
            MarcacaoFalsa(self.dia + timedelta(days=1), "00:00"),
        ]
        self.assertEqual(calc.calcular(self.dia, marcacoes).minutos_noturnos, 120)

    def test_adicional_desligado_zera_o_calculo(self):
        config = ConfigFalsa()
        config.adicional_noturno = False
        calc = CalculadoraJornada(config=config)
        marcacoes = [
            MarcacaoFalsa(self.dia, "22:00"),
            MarcacaoFalsa(self.dia + timedelta(days=1), "02:00"),
        ]
        self.assertEqual(calc.calcular(self.dia, marcacoes).minutos_noturnos, 0)

    def test_madrugada_ate_as_5h_e_noturna(self):
        """Das 0h às 5h são 300 min reais → 343 min-relógio com a redução."""
        marcacoes = [
            MarcacaoFalsa(self.dia, "00:00"),
            MarcacaoFalsa(self.dia, "05:00"),
        ]
        resultado = self.calc.calcular(self.dia, marcacoes)
        self.assertEqual(resultado.minutos_noturnos, 343)


# ══════════════════════════════════════════════════════════════
# Faixas de hora extra
# ══════════════════════════════════════════════════════════════
class HorasExtrasTests(TestCase):
    def setUp(self):
        self.calc = CalculadoraHorasExtras(ConfigFalsa())

    def test_sem_extras_devolve_lista_vazia(self):
        self.assertEqual(self.calc.distribuir(0), [])

    def test_ate_duas_horas_fica_na_primeira_faixa(self):
        faixas = self.calc.distribuir(90, dia=date(2026, 8, 24))
        self.assertEqual(len(faixas), 1)
        self.assertEqual(faixas[0].percentual, 50)
        self.assertEqual(faixas[0].minutos, 90)

    def test_acima_de_duas_horas_abre_segunda_faixa(self):
        faixas = self.calc.distribuir(180, dia=date(2026, 8, 24))
        self.assertEqual([(f.percentual, f.minutos) for f in faixas], [(50, 120), (70, 60)])

    def test_domingo_usa_o_percentual_de_dsr(self):
        domingo = date(2026, 8, 30)
        faixas = self.calc.distribuir(180, dia=domingo)
        self.assertEqual(len(faixas), 1)
        self.assertEqual(faixas[0].percentual, 100)

    def test_feriado_usa_o_percentual_de_dsr(self):
        faixas = self.calc.distribuir(60, dia=date(2026, 8, 24), eh_feriado=True)
        self.assertEqual(faixas[0].percentual, 100)

    def test_minutos_remunerados_incluem_o_adicional(self):
        faixa = self.calc.distribuir(60, dia=date(2026, 8, 24))[0]
        self.assertEqual(faixa.minutos_remunerados, 90)  # 60 min + 50%


# ══════════════════════════════════════════════════════════════
# Banco de horas
# ══════════════════════════════════════════════════════════════
class CalculadoraBancoHorasTests(TestCase):
    def setUp(self):
        self.calc = CalculadoraBancoHoras(ConfigFalsa())

    def test_separa_credito_e_debito(self):
        credito, debito = self.calc.separar_credito_debito([60, -30, 120, -15])
        self.assertEqual((credito, debito), (180, 45))

    def test_saldo_final_compensa(self):
        self.assertEqual(self.calc.saldo_final([60, -30, 120, -15], saldo_anterior=100), 235)

    def test_classificacao_por_faixa(self):
        self.assertEqual(self.calc.classificar(60), "positivo")
        self.assertEqual(self.calc.classificar(0), "atencao")
        self.assertEqual(self.calc.classificar(-119), "atencao")
        self.assertEqual(self.calc.classificar(-121), "negativo")

    def test_prazo_de_compensacao(self):
        credito = date(2026, 1, 15)
        self.assertFalse(self.calc.prazo_expirado(credito, hoje=date(2026, 6, 1)))
        self.assertTrue(self.calc.prazo_expirado(credito, hoje=date(2026, 8, 1)))


# ══════════════════════════════════════════════════════════════
# Consolidação ponta a ponta
# ══════════════════════════════════════════════════════════════
class ConsolidacaoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(nome="Teste", slug="teste", max_colaboradores=50)
        cls.cliente = Cliente.objects.create(
            razao_social="Cliente", cnpj="11222333000181", plano=cls.plano, email_contato="c@c.com"
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Empresa", cnpj="11222333000262"
        )
        cls.escala = EscalaTrabalho.objects.create(
            empresa=cls.empresa,
            nome="Comercial",
            tipo=TipoEscala.FIXA,
            jornada_config=JORNADA_COMERCIAL,
            carga_diaria_min=480,
        )
        cls.colaborador = Colaborador.objects.create(
            empresa=cls.empresa,
            cpf="52998224725",
            nome_completo="João da Silva",
            data_nascimento=date(1990, 1, 1),
            data_admissao=date(2024, 1, 1),
            escala=cls.escala,
        )

    def bater_jornada(self, dia, *horas):
        """
        Registra marcações em um dia, contornando o intervalo mínimo.

        A consolidação do banco de horas roda em `transaction.on_commit`
        — que, dentro de um `TestCase`, só é executado por
        `captureOnCommitCallbacks`. Sem isso o teste passaria a validar
        um caminho que não é o de produção.
        """
        with self.captureOnCommitCallbacks(execute=True):
            for hora in horas:
                h, m = (int(p) for p in hora.split(":"))
                momento = timezone.make_aware(datetime.combine(dia, time(h, m)))
                RegistroPontoService.registrar(
                    colaborador=self.colaborador, momento=momento, validar_intervalo=False
                )

    def test_consolidacao_cria_banco_de_horas(self):
        dia = date(2026, 8, 24)
        self.bater_jornada(dia, "08:00", "12:00", "13:00", "17:00")
        banco = BancoHoras.objects.get(colaborador=self.colaborador, data=dia)
        self.assertEqual(banco.minutos_trabalhados, 480)
        self.assertEqual(banco.saldo_dia, 0)
        self.assertEqual(banco.status, StatusDia.COMPLETO)

    def test_saldo_acumulado_soma_os_dias(self):
        self.bater_jornada(date(2026, 8, 24), "08:00", "12:00", "13:00", "18:00")  # +60
        self.bater_jornada(date(2026, 8, 25), "08:00", "12:00", "13:00", "16:00")  # -60
        segundo = BancoHoras.objects.get(colaborador=self.colaborador, data=date(2026, 8, 25))
        self.assertEqual(segundo.saldo_dia, -60)
        self.assertEqual(segundo.saldo_acumulado, 0)

    def test_ajuste_retroativo_propaga_o_acumulado(self):
        """
        Corrigir um dia antigo precisa reescrever o saldo corrente de
        todos os dias seguintes — senão o painel mostra número errado.
        """
        self.bater_jornada(date(2026, 8, 24), "08:00", "12:00", "13:00", "17:00")
        self.bater_jornada(date(2026, 8, 25), "08:00", "12:00", "13:00", "17:00")
        self.bater_jornada(date(2026, 8, 26), "08:00", "12:00", "13:00", "17:00")

        # Uma hora extra lançada no primeiro dia.
        self.bater_jornada(date(2026, 8, 24), "18:00", "19:00")
        ConsolidacaoService.consolidar_dia(self.colaborador, date(2026, 8, 24))

        ultimo = BancoHoras.objects.get(colaborador=self.colaborador, data=date(2026, 8, 26))
        self.assertEqual(ultimo.saldo_acumulado, 60)

    def test_resumo_do_periodo(self):
        self.bater_jornada(date(2026, 8, 24), "08:00", "12:00", "13:00", "18:00")
        self.bater_jornada(date(2026, 8, 25), "08:00", "12:00", "13:00", "17:00")
        resumo = ConsolidacaoService.resumo_periodo(
            self.colaborador, date(2026, 8, 24), date(2026, 8, 25)
        )
        self.assertEqual(resumo["minutos_trabalhados"], 1020)
        self.assertEqual(resumo["minutos_esperados"], 960)
        self.assertEqual(resumo["saldo_periodo"], 60)
        self.assertEqual(resumo["credito"], 60)
        self.assertEqual(resumo["debito"], 0)

    def test_dia_fechado_nao_e_recalculado(self):
        dia = date(2026, 8, 24)
        self.bater_jornada(dia, "08:00", "12:00", "13:00", "17:00")
        banco = BancoHoras.objects.get(colaborador=self.colaborador, data=dia)
        banco.fechado = True
        banco.saldo_dia = 999
        banco.save()

        ConsolidacaoService.consolidar_dia(self.colaborador, dia)
        banco.refresh_from_db()
        self.assertEqual(banco.saldo_dia, 999)

    def test_consolidar_periodo_cobre_dias_sem_marcacao(self):
        resultados = ConsolidacaoService.consolidar_periodo(
            self.colaborador, date(2026, 8, 24), date(2026, 8, 28)
        )
        self.assertEqual(len(resultados), 5)
        faltas = BancoHoras.objects.filter(
            colaborador=self.colaborador, status=StatusDia.FALTA
        ).count()
        self.assertEqual(faltas, 5)


# ══════════════════════════════════════════════════════════════
# Sequência esperada de marcação
# ══════════════════════════════════════════════════════════════
class ProximoTipoTests(TestCase):
    def test_sequencia_com_intervalo(self):
        esperados = ["entrada", "intervalo_inicio", "intervalo_fim", "saida"]
        for quantidade, esperado in enumerate(esperados):
            self.assertEqual(proximo_tipo_esperado([None] * quantidade), esperado)

    def test_alterna_apos_a_quarta_marcacao(self):
        self.assertEqual(proximo_tipo_esperado([None] * 4), "entrada")
        self.assertEqual(proximo_tipo_esperado([None] * 5), "saida")

    def test_sem_intervalo_alterna_entrada_e_saida(self):
        self.assertEqual(proximo_tipo_esperado([], exige_intervalo=False), "entrada")
        self.assertEqual(proximo_tipo_esperado([None], exige_intervalo=False), "saida")
        self.assertEqual(proximo_tipo_esperado([None, None], exige_intervalo=False), "entrada")
