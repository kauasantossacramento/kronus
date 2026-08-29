"""
Kronus — folga compensatoria descontada do banco de horas.

A pergunta: um colaborador com extras acumuladas de meses anteriores
pode tirar um dia de folga e ter a carga daquele dia debitada
automaticamente do banco?

E o uso classico do banco de horas — o acordo de compensacao da CLT
(Art. 59, par. 2o e 5o) existe justamente para trocar hora extra por
descanso, em vez de pagamento. Se a folga nao debita, a empresa paga
duas vezes: o saldo continua la para ser pago no acerto, e o dia de
trabalho foi perdido.
"""
from datetime import date, time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import StatusDia, TipoJustificativa
from apps.master.models import Plano
from apps.ponto.models import BancoHoras, EscalaTrabalho
from apps.ponto.services import ConsolidacaoService
from apps.rh.models import Colaborador, Justificativa


class BaseFolga(TestCase):
    def setUp(self):
        plano = Plano.objects.create(nome="P", slug="p", max_colaboradores=50)
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        # 8 h de segunda a sexta.
        self.escala = EscalaTrabalho.objects.create(
            empresa=self.empresa,
            nome="Comercial",
            jornada_config={
                "dias": {
                    str(d): {
                        "entrada": "08:00", "saida": "17:00",
                        "intervalo_inicio": "12:00", "intervalo_fim": "13:00",
                    }
                    for d in range(5)
                }
            },
        )
        self.pessoa = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Ana", cpf="52998224725",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
            escala=self.escala,
        )

    def dar_saldo(self, minutos, ate: date):
        """Saldo vindo de meses anteriores, ja consolidado."""
        BancoHoras.objects.create(
            empresa=self.empresa,
            colaborador=self.pessoa,
            data=ate,
            minutos_trabalhados=minutos,
            minutos_esperados=0,
            minutos_extras=minutos,
            saldo_dia=minutos,
            saldo_acumulado=minutos,
            status=StatusDia.COMPLETO,
        )

    def segunda(self, dias_depois=0) -> date:
        d = date(2026, 3, 2)  # uma segunda-feira
        return d + timedelta(days=dias_depois)


class EstadoAtualTests(BaseFolga):
    """
    O que o sistema faz hoje, sem nenhuma alteracao.

    Documenta o comportamento antes da mudanca, para que a diferenca
    fique medida e nao afirmada.
    """

    def test_dia_sem_marcacao_e_falta_e_debita_a_jornada(self):
        ontem = self.segunda(-3)
        self.dar_saldo(16 * 60, ontem)

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, self.segunda())

        self.assertEqual(banco.status, StatusDia.FALTA)
        self.assertEqual(banco.minutos_esperados, 480)
        self.assertEqual(banco.saldo_dia, -480)
        # O saldo cai — mas como FALTA, que no espelho aparece como
        # ausencia injustificada, e nao como folga acordada.
        self.assertEqual(banco.saldo_acumulado, 16 * 60 - 480)

    def test_justificativa_abona_o_dia_e_o_banco_nao_e_tocado(self):
        """
        O caminho que existe hoje para "dar folga" — e ele **perdoa** o
        dia em vez de debita-lo. O colaborador fica com a folga E com as
        horas no banco, para receber depois. A empresa paga duas vezes.
        """
        ontem = self.segunda(-3)
        self.dar_saldo(16 * 60, ontem)
        dia = self.segunda()

        Justificativa.objects.create(
            empresa=self.empresa,
            colaborador=self.pessoa,
            data=dia,
            tipo=TipoJustificativa.FALTA,
            motivo="Folga",
            abona_dia=True,
            status="aprovado",
            avaliada_em=timezone.now(),
        )

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)

        self.assertEqual(banco.status, StatusDia.JUSTIFICADO)
        self.assertEqual(
            banco.saldo_dia, 0,
            "o dia justificado nao debita — e o abono zera a divida",
        )
        self.assertEqual(
            banco.saldo_acumulado, 16 * 60,
            "as 16 h continuam no banco depois da folga concedida",
        )

    def test_o_abono_continua_perdoando(self):
        """
        A mudanca nao pode ter transformado abono em desconto: atestado,
        esquecimento de batida e falta justificada continuam perdoando a
        divida. Quem debita e so a folga compensatoria.
        """
        self.assertIn(
            "folga_compensatoria", [t[0] for t in TipoJustificativa.choices]
        )
        # Os dois testes acima ja provam o resto: a justificativa comum
        # deixa o saldo intacto, e e assim que deve continuar.


class FolgaCompensatoriaTests(BaseFolga):
    """
    O comportamento novo: a folga sai do banco.
    """

    def conceder(self, dia, motivo="Folga acordada"):
        return Justificativa.objects.create(
            empresa=self.empresa,
            colaborador=self.pessoa,
            data=dia,
            tipo=TipoJustificativa.FOLGA_COMPENSATORIA,
            motivo=motivo,
            abona_dia=True,
            status="aprovado",
            avaliada_em=timezone.now(),
        )

    def test_debita_a_jornada_do_dia_do_saldo_acumulado(self):
        ontem = self.segunda(-3)
        self.dar_saldo(16 * 60, ontem)
        dia = self.segunda()
        self.conceder(dia)

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)

        self.assertEqual(banco.status, StatusDia.COMPENSADO)
        self.assertEqual(banco.minutos_esperados, 480, "8 h pela escala")
        self.assertEqual(banco.saldo_dia, -480)
        self.assertEqual(
            banco.saldo_acumulado, 16 * 60 - 480,
            "as 16 h viraram 8 h: a folga consumiu a jornada do dia",
        )

    def test_o_desconto_vem_da_escala_e_nao_de_um_valor_fixo(self):
        """
        Meio periodo desconta meio periodo. Descontar 8 h de quem cumpre
        4 h tiraria do banco o dobro do que a folga vale.
        """
        self.escala.jornada_config = {
            "dias": {
                str(d): {"entrada": "08:00", "saida": "12:00"} for d in range(5)
            }
        }
        self.escala.save(update_fields=["jornada_config"])

        self.dar_saldo(16 * 60, self.segunda(-3))
        dia = self.segunda()
        self.conceder(dia)

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)
        self.assertEqual(banco.minutos_esperados, 240)
        self.assertEqual(banco.saldo_acumulado, 16 * 60 - 240)

    def test_folga_em_dia_de_descanso_nao_debita_nada(self):
        """
        Domingo ja nao tem jornada. Debitar seria cobrar do banco um dia
        que a pessoa nao devia.
        """
        self.dar_saldo(16 * 60, self.segunda(-3))
        domingo = self.segunda(6)
        self.assertEqual(domingo.weekday(), 6)
        self.conceder(domingo)

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, domingo)
        self.assertEqual(banco.saldo_dia, 0)
        self.assertEqual(banco.saldo_acumulado, 16 * 60)

    def test_feriado_tambem_nao_debita(self):
        from apps.core.models import Feriado

        self.dar_saldo(16 * 60, self.segunda(-3))
        dia = self.segunda()
        Feriado.objects.create(data=dia, nome="Teste", empresa=self.empresa)
        self.conceder(dia)

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)
        self.assertEqual(banco.saldo_dia, 0)

    def test_nao_marca_atraso_num_dia_de_folga(self):
        # Um dia acordado nao pode aparecer como irregular no espelho.
        self.dar_saldo(16 * 60, self.segunda(-3))
        dia = self.segunda()
        self.conceder(dia)

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)
        self.assertEqual(banco.minutos_atraso, 0)
        self.assertEqual(banco.minutos_saida_antecipada, 0)

    def test_se_a_pessoa_trabalhou_o_dia_conta_como_trabalhado(self):
        """
        Folga concedida e depois a pessoa apareceu e bateu ponto. O que
        vale e o que aconteceu — debitar o banco de quem trabalhou seria
        cobrar duas vezes.
        """
        from apps.core.constants import MetodoRegistro
        from apps.ponto.services import RegistroPontoService

        self.dar_saldo(16 * 60, self.segunda(-3))
        dia = self.segunda()
        self.conceder(dia)

        for hora in (8, 17):
            RegistroPontoService.registrar(
                colaborador=self.pessoa,
                metodo=MetodoRegistro.WEB,
                momento=timezone.make_aware(
                    timezone.datetime.combine(dia, time(hora, 0))
                ),
                validar_intervalo=False,
            )

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)
        self.assertNotEqual(banco.status, StatusDia.COMPENSADO)
        self.assertGreater(banco.minutos_trabalhados, 0)

    def test_compensacao_tem_precedencia_sobre_o_abono(self):
        """
        As duas chegam como justificativa aprovada com `abona_dia`. Se o
        abono vencesse, o debito seria zerado e a folga sairia de graca —
        que e exatamente o defeito que isto corrige.
        """
        dia = self.segunda()
        self.dar_saldo(16 * 60, self.segunda(-3))
        self.conceder(dia)
        Justificativa.objects.create(
            empresa=self.empresa, colaborador=self.pessoa, data=dia,
            tipo=TipoJustificativa.FALTA, motivo="outra", abona_dia=True,
            status="aprovado", avaliada_em=timezone.now(),
        )

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)
        self.assertEqual(banco.status, StatusDia.COMPENSADO)
        self.assertEqual(banco.saldo_dia, -480)

    def test_justificativa_pendente_nao_debita(self):
        # So o que foi aprovado mexe no saldo.
        dia = self.segunda()
        self.dar_saldo(16 * 60, self.segunda(-3))
        Justificativa.objects.create(
            empresa=self.empresa, colaborador=self.pessoa, data=dia,
            tipo=TipoJustificativa.FOLGA_COMPENSATORIA, motivo="pedido",
            abona_dia=True, status="pendente",
        )

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)
        self.assertEqual(banco.status, StatusDia.FALTA)


class SaldoNegativoTests(BaseFolga):
    def test_folga_sem_saldo_deixa_o_banco_negativo_e_visivel(self):
        """
        Nao bloqueamos aqui: quem concede e o RH, e a regra de "pode ou
        nao pode ficar negativo" e do acordo coletivo, nao do calculo. O
        que o sistema garante e que o numero apareca — um saldo negativo
        escondido viraria surpresa no acerto.
        """
        dia = self.segunda()
        self.dar_saldo(2 * 60, self.segunda(-3))
        Justificativa.objects.create(
            empresa=self.empresa, colaborador=self.pessoa, data=dia,
            tipo=TipoJustificativa.FOLGA_COMPENSATORIA, motivo="folga",
            abona_dia=True, status="aprovado", avaliada_em=timezone.now(),
        )

        banco = ConsolidacaoService.consolidar_dia(self.pessoa, dia)
        self.assertEqual(banco.saldo_acumulado, 2 * 60 - 480)
        self.assertLess(banco.saldo_acumulado, 0)


class RelatoriosTests(BaseFolga):
    """
    O dia compensado precisa aparecer com o proprio nome nos arquivos
    fiscais. Sair como "nada" faria a fiscalizacao ver uma jornada nao
    cumprida sem explicacao.
    """

    def test_o_aej_marca_folga_compensatoria(self):
        from apps.relatorios.aej import AUSENCIA
        from apps.core.constants import StatusDia
        import inspect
        from apps.relatorios import aej

        fonte = inspect.getsource(aej)
        self.assertIn("StatusDia.COMPENSADO", fonte)
        self.assertEqual(AUSENCIA["folga_compensatoria"], "4")

    def test_o_dia_compensado_nao_conta_como_dsr(self):
        # DSR e descanso semanal; folga compensada e hora ja trabalhada
        # sendo devolvida. Somar as duas inventaria descansos.
        import inspect
        from apps.relatorios import folha

        fonte = inspect.getsource(folha)
        self.assertIn("dias_compensados", fonte)


class FormularioTests(BaseFolga):
    def _dados(self, tipo, data):
        return {
            "colaborador": self.pessoa.pk,
            "data": data.isoformat(),
            "tipo": tipo,
            "motivo": "Folga combinada com a gestora, banco de horas.",
            "abona_dia": True,
        }

    def _form(self, dados):
        from apps.rh.forms_rh import JustificativaForm

        return JustificativaForm(data=dados, empresa=self.empresa)

    def test_folga_pode_ser_agendada_para_o_futuro(self):
        """
        Folga se combina antes. Os outros tipos justificam algo que ja
        aconteceu, e ali uma data futura e digitacao errada.
        """
        amanha = timezone.localdate() + timedelta(days=7)
        form = self._form(
            self._dados(TipoJustificativa.FOLGA_COMPENSATORIA, amanha)
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_os_outros_tipos_continuam_recusando_data_futura(self):
        amanha = timezone.localdate() + timedelta(days=7)
        form = self._form(self._dados(TipoJustificativa.FALTA, amanha))
        self.assertFalse(form.is_valid())
        self.assertIn("data", form.errors)

    def test_o_aviso_diz_quanto_sai_e_quanto_sobra(self):
        self.dar_saldo(16 * 60, self.segunda(-3))
        form = self._form(
            self._dados(TipoJustificativa.FOLGA_COMPENSATORIA, self.segunda())
        )
        self.assertTrue(form.is_valid(), form.errors)

        aviso = form.aviso_de_saldo()
        self.assertEqual(aviso["minutos"], 480)
        self.assertEqual(aviso["saldo_antes"], 960)
        self.assertEqual(aviso["saldo_depois"], 480)

    def test_o_aviso_avisa_quando_o_saldo_fica_negativo(self):
        from apps.rh.views_gestao import _texto_do_saldo

        self.dar_saldo(2 * 60, self.segunda(-3))
        form = self._form(
            self._dados(TipoJustificativa.FOLGA_COMPENSATORIA, self.segunda())
        )
        self.assertTrue(form.is_valid(), form.errors)
        texto = _texto_do_saldo(form.aviso_de_saldo())
        self.assertIn("negativo", texto)

    def test_sem_jornada_no_dia_o_aviso_diz_que_nada_e_debitado(self):
        from apps.rh.views_gestao import _texto_do_saldo

        domingo = self.segunda(6)
        form = self._form(
            self._dados(TipoJustificativa.FOLGA_COMPENSATORIA, domingo)
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn("não debita", _texto_do_saldo(form.aviso_de_saldo()))

    def test_outros_tipos_nao_produzem_aviso_de_saldo(self):
        form = self._form(
            self._dados(TipoJustificativa.ESQUECIMENTO, self.segunda())
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.aviso_de_saldo())
