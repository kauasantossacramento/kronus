"""
Kronus — testes de atestados, justificativas, fechamento e assinatura (Fase 4).

O que estes testes protegem não é a mudança de status, e sim o **efeito
dela**: aprovar um atestado tem que reprocessar o banco de horas e
transformar falta em dia abonado. Se isso silenciosamente parar de
funcionar, o espelho e o AEJ ficam errados sem ninguém perceber.
"""
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import StatusAprovacao, StatusDia, TipoEscala, TipoUsuario
from apps.master.models import Plano
from apps.ponto.models import BancoHoras, EscalaTrabalho, FechamentoMensal
from apps.ponto.services import ConsolidacaoService, RegistroPontoService
from apps.rh.models import Afastamento, Atestado, Colaborador, Justificativa

User = get_user_model()
SENHA = "senha-forte-123"

JORNADA = {
    "dias": {
        str(d): {"entrada": "08:00", "intervalo_inicio": "12:00",
                 "intervalo_fim": "13:00", "saida": "17:00"}
        for d in range(5)
    }
}


def arquivo_pdf(nome="atestado.pdf"):
    return SimpleUploadedFile(nome, b"%PDF-1.4 conteudo", content_type="application/pdf")


class BaseGestaoTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Teste", slug="teste", max_colaboradores=50, tem_api=True
        )
        cls.cliente = Cliente.objects.create(
            razao_social="Cliente", cnpj="11222333000181",
            plano=cls.plano, email_contato="c@c.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Empresa", cnpj="11222333000262"
        )
        cls.escala = EscalaTrabalho.objects.create(
            empresa=cls.empresa, nome="Comercial", tipo=TipoEscala.FIXA,
            jornada_config=JORNADA, carga_diaria_min=480,
        )
        cls.joao = Colaborador.objects.create(
            empresa=cls.empresa, cpf="52998224725", nome_completo="João da Silva",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
            escala=cls.escala,
        )
        cls.rh = User.objects.create_user(
            email="rh@teste.com", password=SENHA, nome_completo="RH",
            tipo=TipoUsuario.RH, cliente=cls.cliente,
        )
        cls.rh.empresas.set([cls.empresa])

        # Segunda a quarta de uma semana passada, sem marcação → faltas.
        cls.dia1 = date(2026, 8, 24)
        cls.dia2 = date(2026, 8, 25)
        cls.dia3 = date(2026, 8, 26)

    def setUp(self):
        self.client.login(username="rh@teste.com", password=SENHA)
        ConsolidacaoService.consolidar_periodo(self.joao, self.dia1, self.dia3)

    def banco(self, dia):
        return BancoHoras.objects.get(colaborador=self.joao, data=dia)

    def bater(self, dia, *horas):
        with self.captureOnCommitCallbacks(execute=True):
            for hora in horas:
                h, m = (int(p) for p in hora.split(":"))
                RegistroPontoService.registrar(
                    colaborador=self.joao,
                    momento=timezone.make_aware(datetime.combine(dia, time(h, m))),
                    validar_intervalo=False,
                )


# ══════════════════════════════════════════════════════════════
# Atestados
# ══════════════════════════════════════════════════════════════
class AtestadoTests(BaseGestaoTestCase):
    def criar_atestado(self, inicio=None, fim=None):
        return Atestado.objects.create(
            empresa=self.empresa,
            colaborador=self.joao,
            arquivo=arquivo_pdf(),
            data_inicio=inicio or self.dia1,
            data_fim=fim or self.dia2,
        )

    def test_dia_sem_marcacao_comeca_como_falta(self):
        self.assertEqual(self.banco(self.dia1).status, StatusDia.FALTA)
        self.assertEqual(self.banco(self.dia1).saldo_dia, -480)

    def test_aprovacao_converte_falta_em_atestado(self):
        """O efeito da aprovação é o que importa, não o status em si."""
        atestado = self.criar_atestado()
        self.client.post(
            reverse("rh:atestado_avaliar", args=[atestado.pk]),
            {"decisao": "aprovar", "parecer": ""},
        )

        atestado.refresh_from_db()
        self.assertEqual(atestado.status, StatusAprovacao.APROVADO)
        self.assertEqual(self.banco(self.dia1).status, StatusDia.ATESTADO)
        self.assertEqual(self.banco(self.dia2).status, StatusDia.ATESTADO)

    def test_atestado_aprovado_zera_o_debito(self):
        atestado = self.criar_atestado()
        self.client.post(
            reverse("rh:atestado_avaliar", args=[atestado.pk]),
            {"decisao": "aprovar", "parecer": ""},
        )
        self.assertEqual(self.banco(self.dia1).saldo_dia, 0)

    def test_dia_fora_do_atestado_permanece_falta(self):
        self.criar_atestado(inicio=self.dia1, fim=self.dia1)
        atestado = Atestado.objects.first()
        self.client.post(
            reverse("rh:atestado_avaliar", args=[atestado.pk]),
            {"decisao": "aprovar", "parecer": ""},
        )
        self.assertEqual(self.banco(self.dia2).status, StatusDia.FALTA)

    def test_rejeicao_exige_parecer(self):
        atestado = self.criar_atestado()
        resposta = self.client.post(
            reverse("rh:atestado_avaliar", args=[atestado.pk]),
            {"decisao": "rejeitar", "parecer": ""},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertFormError(resposta.context["form"], "parecer", "Informe o motivo da rejeição.")
        atestado.refresh_from_db()
        self.assertEqual(atestado.status, StatusAprovacao.PENDENTE)

    def test_rejeicao_mantem_a_falta(self):
        atestado = self.criar_atestado()
        self.client.post(
            reverse("rh:atestado_avaliar", args=[atestado.pk]),
            {"decisao": "rejeitar", "parecer": "Documento ilegível."},
        )
        atestado.refresh_from_db()
        self.assertEqual(atestado.status, StatusAprovacao.REJEITADO)
        self.assertEqual(self.banco(self.dia1).status, StatusDia.FALTA)

    def test_dias_sao_calculados_no_save(self):
        atestado = self.criar_atestado(inicio=self.dia1, fim=self.dia3)
        self.assertEqual(atestado.dias, 3)

    def test_formulario_recusa_periodo_invertido(self):
        from apps.rh.forms_rh import AtestadoForm

        form = AtestadoForm(
            data={"colaborador": self.joao.pk, "data_inicio": self.dia3, "data_fim": self.dia1},
            files={"arquivo": arquivo_pdf()},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("data_fim", form.errors)

    def test_formulario_recusa_sobreposicao(self):
        """Lançamento duplicado é comum quando RH e gestor enviam o mesmo atestado."""
        from apps.rh.forms_rh import AtestadoForm

        self.criar_atestado(inicio=self.dia1, fim=self.dia3)
        form = AtestadoForm(
            data={"colaborador": self.joao.pk, "data_inicio": self.dia2, "data_fim": self.dia2},
            files={"arquivo": arquivo_pdf()},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())

    def test_formulario_recusa_extensao_invalida(self):
        from apps.rh.forms_rh import AtestadoForm

        form = AtestadoForm(
            data={"colaborador": self.joao.pk, "data_inicio": self.dia1, "data_fim": self.dia1},
            files={"arquivo": SimpleUploadedFile("virus.exe", b"MZ", content_type="application/x-msdownload")},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("arquivo", form.errors)

    def test_lista_responde(self):
        self.criar_atestado()
        resposta = self.client.get(reverse("rh:atestado_lista"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "João da Silva")


# ══════════════════════════════════════════════════════════════
# Justificativas
# ══════════════════════════════════════════════════════════════
class JustificativaTests(BaseGestaoTestCase):
    def criar(self, abona=True, dia=None):
        return Justificativa.objects.create(
            empresa=self.empresa,
            colaborador=self.joao,
            data=dia or self.dia1,
            tipo="falta",
            motivo="Comparecimento a audiência judicial obrigatória.",
            abona_dia=abona,
        )

    def test_aprovacao_abona_o_dia(self):
        justificativa = self.criar()
        self.client.post(
            reverse("rh:justificativa_avaliar", args=[justificativa.pk]),
            {"decisao": "aprovar", "parecer": "Documentação conferida."},
        )
        self.assertEqual(self.banco(self.dia1).status, StatusDia.JUSTIFICADO)
        self.assertEqual(self.banco(self.dia1).saldo_dia, 0)

    def test_justificativa_sem_abono_nao_muda_o_status(self):
        """Registrar o motivo é diferente de abonar o dia."""
        justificativa = self.criar(abona=False)
        self.client.post(
            reverse("rh:justificativa_avaliar", args=[justificativa.pk]),
            {"decisao": "aprovar", "parecer": "Ciente."},
        )
        self.assertEqual(self.banco(self.dia1).status, StatusDia.FALTA)

    def test_rejeicao_mantem_a_falta(self):
        justificativa = self.criar()
        self.client.post(
            reverse("rh:justificativa_avaliar", args=[justificativa.pk]),
            {"decisao": "rejeitar", "parecer": "Sem comprovação."},
        )
        justificativa.refresh_from_db()
        self.assertEqual(justificativa.status, StatusAprovacao.REJEITADO)
        self.assertEqual(self.banco(self.dia1).status, StatusDia.FALTA)

    def test_motivo_curto_e_recusado(self):
        from apps.rh.forms_rh import JustificativaForm

        form = JustificativaForm(
            data={"colaborador": self.joao.pk, "data": self.dia1, "tipo": "falta", "motivo": "faltei"},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("motivo", form.errors)

    def test_data_futura_e_recusada(self):
        from apps.rh.forms_rh import JustificativaForm

        form = JustificativaForm(
            data={
                "colaborador": self.joao.pk,
                "data": timezone.localdate() + timedelta(days=5),
                "tipo": "falta",
                "motivo": "Motivo suficientemente descrito aqui.",
            },
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("data", form.errors)


# ══════════════════════════════════════════════════════════════
# Afastamentos
# ══════════════════════════════════════════════════════════════
class AfastamentoTests(BaseGestaoTestCase):
    def test_afastamento_reprocessa_o_periodo(self):
        Afastamento.objects.create(
            empresa=self.empresa, colaborador=self.joao, tipo="ferias",
            data_inicio=self.dia1, data_fim=self.dia3,
        )
        ConsolidacaoService.consolidar_periodo(self.joao, self.dia1, self.dia3)
        self.assertEqual(self.banco(self.dia1).status, StatusDia.AFASTAMENTO)
        self.assertEqual(self.banco(self.dia1).saldo_dia, 0)

    def test_dias_calculados(self):
        afastamento = Afastamento.objects.create(
            empresa=self.empresa, colaborador=self.joao, tipo="ferias",
            data_inicio=self.dia1, data_fim=self.dia3,
        )
        self.assertEqual(afastamento.dias, 3)


# ══════════════════════════════════════════════════════════════
# Fechamento mensal
# ══════════════════════════════════════════════════════════════
class FechamentoTests(BaseGestaoTestCase):
    def setUp(self):
        super().setUp()
        self.ano, self.mes = 2026, 8
        self.bater(self.dia1, "08:00", "12:00", "13:00", "17:00")
        self.bater(self.dia2, "08:00", "12:00", "13:00", "17:00")

    def test_painel_responde(self):
        resposta = self.client.get(
            reverse("rh:fechamento") + f"?ano={self.ano}&mes={self.mes}"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "João da Silva")

    def test_fechamento_cria_registro_e_congela_os_dias(self):
        self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk]),
            {"forcar": "1"},
        )
        registro = FechamentoMensal.objects.get(
            colaborador=self.joao, ano=self.ano, mes=self.mes
        )
        self.assertTrue(registro.fechado)
        self.assertIsNotNone(registro.fechado_em)
        self.assertEqual(registro.fechado_por, self.rh)
        self.assertTrue(self.banco(self.dia1).fechado)

    def test_dia_fechado_nao_e_recalculado(self):
        """
        Sem isso, uma marcação lançada depois mudaria silenciosamente
        um mês já pago.
        """
        self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk]),
            {"forcar": "1"},
        )
        saldo_antes = self.banco(self.dia1).saldo_dia
        self.bater(self.dia1, "18:00", "20:00")  # duas horas a mais
        self.assertEqual(self.banco(self.dia1).saldo_dia, saldo_antes)

    def test_fechamento_grava_o_hash_do_espelho(self):
        self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk]),
            {"forcar": "1"},
        )
        registro = FechamentoMensal.objects.get(colaborador=self.joao)
        self.assertEqual(len(registro.hash_documento), 64)

    def test_jornada_em_aberto_bloqueia_o_fechamento(self):
        """Fechar com marcação faltando congelaria um erro conhecido."""
        self.bater(self.dia3, "08:00", "12:00", "13:00")  # ímpar
        resposta = self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk])
        )
        self.assertFalse(
            FechamentoMensal.objects.filter(colaborador=self.joao, fechado=True).exists()
        )
        mensagens = [str(m) for m in resposta.wsgi_request._messages]
        self.assertTrue(any("aberto" in m for m in mensagens))

    def test_forcar_ignora_o_bloqueio(self):
        self.bater(self.dia3, "08:00", "12:00", "13:00")
        self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk]),
            {"forcar": "1"},
        )
        self.assertTrue(
            FechamentoMensal.objects.filter(colaborador=self.joao, fechado=True).exists()
        )

    def test_reabertura_exige_motivo(self):
        self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk]),
            {"forcar": "1"},
        )
        self.client.post(
            reverse("rh:reabrir_periodo", args=[self.ano, self.mes, self.joao.pk]),
            {"motivo": "curto"},
        )
        self.assertTrue(
            FechamentoMensal.objects.get(colaborador=self.joao).fechado
        )

    def test_reabertura_descongela_os_dias(self):
        self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk]),
            {"forcar": "1"},
        )
        self.client.post(
            reverse("rh:reabrir_periodo", args=[self.ano, self.mes, self.joao.pk]),
            {"motivo": "Correção de marcação esquecida na portaria."},
        )
        self.assertFalse(FechamentoMensal.objects.get(colaborador=self.joao).fechado)
        self.assertFalse(self.banco(self.dia1).fechado)

    def test_espelho_assinado_nao_reabre(self):
        """Regra 4 da Seção 14 — a assinatura perderia o valor probatório."""
        self.client.post(
            reverse("rh:fechar_periodo_colaborador", args=[self.ano, self.mes, self.joao.pk]),
            {"forcar": "1"},
        )
        registro = FechamentoMensal.objects.get(colaborador=self.joao)
        registro.assinado = True
        registro.assinado_em = timezone.now()
        registro.save(update_fields=["assinado", "assinado_em"])

        self.client.post(
            reverse("rh:reabrir_periodo", args=[self.ano, self.mes, self.joao.pk]),
            {"motivo": "Tentativa de reabrir um espelho já assinado."},
        )
        registro.refresh_from_db()
        self.assertTrue(registro.fechado)


# ══════════════════════════════════════════════════════════════
# Assinatura eletrônica pelo colaborador
# ══════════════════════════════════════════════════════════════
class AssinaturaEspelhoTests(BaseGestaoTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = User.objects.create_user(
            cpf="52998224725", password=SENHA, nome_completo="João da Silva",
            tipo=TipoUsuario.COLABORADOR, cliente=self.cliente,
        )
        self.joao.user = self.usuario
        self.joao.save(update_fields=["user"])

        self.espelho = FechamentoMensal.objects.create(
            empresa=self.empresa, colaborador=self.joao, ano=2026, mes=8,
            data_inicio=date(2026, 8, 1), data_fim=date(2026, 8, 31),
            fechado=True, fechado_em=timezone.now(),
            hash_documento="a" * 64,
        )
        self.client.force_login(self.usuario)

    def test_lista_de_espelhos_responde(self):
        resposta = self.client.get(reverse("ponto:meus_espelhos"))
        self.assertEqual(resposta.status_code, 200)

    def test_tela_de_conferencia_responde(self):
        resposta = self.client.get(
            reverse("ponto:conferir_espelho", args=[self.espelho.pk])
        )
        self.assertEqual(resposta.status_code, 200)

    def test_assinatura_grava_data_ip_e_hash(self):
        self.client.post(
            reverse("ponto:assinar_espelho", args=[self.espelho.pk]), {"aceite": "1"}
        )
        self.espelho.refresh_from_db()
        self.assertTrue(self.espelho.assinado)
        self.assertIsNotNone(self.espelho.assinado_em)
        self.assertIsNotNone(self.espelho.assinatura_ip)
        self.assertEqual(len(self.espelho.assinatura_hash), 64)

    def test_assinatura_sem_aceite_e_recusada(self):
        self.client.post(reverse("ponto:assinar_espelho", args=[self.espelho.pk]), {})
        self.espelho.refresh_from_db()
        self.assertFalse(self.espelho.assinado)

    def test_nao_assina_espelho_de_outro_colaborador(self):
        outro = Colaborador.objects.create(
            empresa=self.empresa, cpf="15350946056", nome_completo="Maria",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )
        alheio = FechamentoMensal.objects.create(
            empresa=self.empresa, colaborador=outro, ano=2026, mes=8,
            data_inicio=date(2026, 8, 1), data_fim=date(2026, 8, 31), fechado=True,
        )
        resposta = self.client.post(
            reverse("ponto:assinar_espelho", args=[alheio.pk]), {"aceite": "1"}
        )
        self.assertEqual(resposta.status_code, 404)
        alheio.refresh_from_db()
        self.assertFalse(alheio.assinado)

    def test_assinar_duas_vezes_nao_sobrescreve(self):
        self.client.post(
            reverse("ponto:assinar_espelho", args=[self.espelho.pk]), {"aceite": "1"}
        )
        self.espelho.refresh_from_db()
        primeira = self.espelho.assinado_em

        self.client.post(
            reverse("ponto:assinar_espelho", args=[self.espelho.pk]), {"aceite": "1"}
        )
        self.espelho.refresh_from_db()
        self.assertEqual(self.espelho.assinado_em, primeira)

    def test_solicitacao_de_justificativa_nasce_pendente(self):
        self.client.post(
            reverse("ponto:solicitar_justificativa"),
            {
                "data": self.dia1.isoformat(),
                "tipo": "esquecimento",
                "motivo": "Esqueci de registrar a saída na portaria.",
            },
        )
        justificativa = Justificativa.objects.get(colaborador=self.joao)
        self.assertEqual(justificativa.status, StatusAprovacao.PENDENTE)
        self.assertEqual(justificativa.solicitada_por, self.usuario)


# ══════════════════════════════════════════════════════════════
# Configurações
# ══════════════════════════════════════════════════════════════
class ConfiguracaoTests(BaseGestaoTestCase):
    def test_tela_responde(self):
        self.assertEqual(self.client.get(reverse("rh:configuracoes")).status_code, 200)

    def test_personalizacao_responde(self):
        self.assertEqual(self.client.get(reverse("rh:personalizacao")).status_code, 200)

    def test_notificacoes_salva_preferencias(self):
        self.client.post(
            reverse("rh:notificacoes_config"),
            {"notif_esq_ponto": "on", "email_notificacoes": "rh@empresa.com"},
        )
        config = self.empresa.configuracao
        config.refresh_from_db()
        self.assertTrue(config.notif_esq_ponto)
        self.assertFalse(config.notif_banco_negativo)  # não veio no POST
        self.assertEqual(config.email_notificacoes, "rh@empresa.com")

    def test_emissao_de_chave_de_api(self):
        from apps.api.models import APIKey

        resposta = self.client.post(
            reverse("rh:integracao"), {"acao": "emitir", "nome": "ERP Domínio"}
        )
        self.assertEqual(resposta.status_code, 200)
        chave = APIKey.objects.get(empresa=self.empresa)
        self.assertEqual(chave.nome, "ERP Domínio")
        # A chave em texto plano aparece uma única vez, na resposta.
        self.assertIsNotNone(resposta.context["chave_nova"])
        self.assertNotIn(resposta.context["chave_nova"], chave.chave_hash)

    def test_plano_sem_api_bloqueia_emissao(self):
        from apps.api.models import APIKey

        self.plano.tem_api = False
        self.plano.save(update_fields=["tem_api"])

        self.client.post(reverse("rh:integracao"), {"acao": "emitir", "nome": "X"})
        self.assertFalse(APIKey.objects.filter(empresa=self.empresa).exists())

    def test_revogacao_de_chave(self):
        from apps.api.models import APIKey

        chave, _ = APIKey.emitir(empresa=self.empresa, nome="Teste")
        self.client.post(reverse("rh:integracao"), {"acao": "revogar", "chave": chave.pk})
        chave.refresh_from_db()
        self.assertFalse(chave.valida)

    def test_reprocessamento_do_mes(self):
        resposta = self.client.post(reverse("rh:reprocessar_mes"))
        self.assertEqual(resposta.status_code, 302)
