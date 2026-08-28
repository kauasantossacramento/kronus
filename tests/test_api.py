"""
Kronus — testes da API REST pública e dos webhooks (Fase 5).

Cobrem o que a Seção 7 promete e o que a Seção 14 proíbe:

* autenticação por chave de Empresa e por chave de Cliente
* **isolamento**: uma chave nunca alcança dado de outra conta
* somente leitura vs. escrita
* rate limiting derivado do plano
* registro de ponto pela API, passando pelo mesmo service do totem
* verificação de integridade do hash exposta ao integrador
* AFD/AEJ pela API byte a byte iguais aos da tela
* assinatura HMAC dos webhooks, retentativa e desativação por falha

O teste de isolamento é o mais importante do arquivo: um vazamento
entre contas aqui é um vazamento de dado pessoal de terceiros.
"""
import hashlib
import hmac
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.api.models import APIKey
from apps.api.throttling import PlanoRateThrottle
from apps.clientes.models import Cliente, Empresa
from apps.core.constants import MetodoRegistro, StatusDia, TipoUsuario
from apps.core.utils import hash_api_key
from apps.master.models import Plano
from apps.notificacoes.models import EntregaWebhook, Webhook
from apps.ponto.models import BancoHoras, EscalaTrabalho, RegistroPonto
from apps.ponto.services import RegistroPontoService
from apps.rh.models import Atestado, Cargo, Colaborador, Departamento


class RespostaFalsa:
    """Substituta de `requests.Response` nos testes de webhook."""

    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class BaseAPITestCase(TestCase):
    """
    Duas contas completas e desconexas.

    A segunda (`rival`) existe só para provar que a primeira não a
    enxerga. Sem um vizinho no banco, todo teste de isolamento passa
    por vacuidade.
    """

    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Pro", slug="pro", max_colaboradores=200, max_totems=5,
            tem_api=True, tem_webhook=True, rate_limit_api_hora=1000,
        )
        cls.plano_basico = Plano.objects.create(
            nome="Starter", slug="starter", max_colaboradores=25,
            tem_api=True, tem_webhook=False, rate_limit_api_hora=100,
        )

        # -- conta A ------------------------------------------
        cls.cliente = Cliente.objects.create(
            razao_social="Grupo Alfa", cnpj="11222333000181",
            plano=cls.plano, email_contato="alfa@exemplo.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Alfa Matriz", cnpj="11222333000262"
        )
        cls.filial = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Alfa Filial", cnpj="11222333000343"
        )

        cls.departamento = Departamento.objects.create(
            empresa=cls.empresa, nome="Operações", centro_custo="OP-01"
        )
        cls.cargo = Cargo.objects.create(
            empresa=cls.empresa, nome="Analista", cbo="252105"
        )
        cls.escala = EscalaTrabalho.objects.create(
            empresa=cls.empresa, nome="Comercial", carga_diaria_min=480,
            carga_semanal_min=2640,
        )

        cls.joao = Colaborador.objects.create(
            empresa=cls.empresa, cpf="52998224725",
            nome_completo="João da Silva Souza", data_nascimento=date(1990, 3, 12),
            data_admissao=date(2024, 1, 1), matricula="A-001",
            departamento=cls.departamento, escala=cls.escala,
        )
        cls.maria = Colaborador.objects.create(
            empresa=cls.filial, cpf="71428793860",
            nome_completo="Maria Ramos", data_nascimento=date(1985, 6, 2),
            data_admissao=date(2024, 1, 1), matricula="A-002",
        )
        cls.desligado = Colaborador.objects.create(
            empresa=cls.empresa, cpf="15350946056",
            nome_completo="Pedro Antigo", data_nascimento=date(1980, 1, 1),
            data_admissao=date(2020, 1, 1), data_demissao=date(2025, 6, 30),
            ativo=False,
        )

        # -- conta B (o vizinho) -------------------------------
        cls.rival = Cliente.objects.create(
            razao_social="Grupo Beta", cnpj="45997418000153",
            plano=cls.plano, email_contato="beta@exemplo.com",
        )
        cls.empresa_rival = Empresa.objects.create(
            cliente=cls.rival, razao_social="Beta Ltda", cnpj="45997418000234"
        )
        cls.colaborador_rival = Colaborador.objects.create(
            empresa=cls.empresa_rival, cpf="03874649089",
            nome_completo="Ana Concorrente", data_nascimento=date(1992, 9, 9),
            data_admissao=date(2024, 1, 1),
        )

        # -- credenciais ---------------------------------------
        cls.chave_empresa_obj, cls.chave_empresa = APIKey.emitir(
            empresa=cls.empresa, nome="ERP folha", somente_leitura=True
        )
        cls.chave_escrita_obj, cls.chave_escrita = APIKey.emitir(
            empresa=cls.empresa, nome="Coletor", somente_leitura=False
        )
        cls.chave_rival_obj, cls.chave_rival = APIKey.emitir(
            empresa=cls.empresa_rival, nome="ERP Beta", somente_leitura=True
        )

        cls.chave_cliente = "kr_conta_alfa_teste_123456"
        cls.cliente.api_key_hash = hash_api_key(cls.chave_cliente)
        cls.cliente.api_key_ativa = True
        cls.cliente.save(update_fields=["api_key_hash", "api_key_ativa"])

    def setUp(self):
        # O throttle guarda histórico no cache; sem limpar, um teste
        # contamina o seguinte.
        cache.clear()

    # -- helpers ------------------------------------------------
    def get(self, url, chave=None, **params):
        cabecalhos = {"HTTP_X_API_KEY": chave} if chave else {}
        return self.client.get(url, params, **cabecalhos)

    def post(self, url, dados, chave=None):
        cabecalhos = {"HTTP_X_API_KEY": chave} if chave else {}
        return self.client.post(
            url, data=json.dumps(dados), content_type="application/json", **cabecalhos
        )


# ══════════════════════════════════════════════════════════════
# Autenticação
# ══════════════════════════════════════════════════════════════
class AutenticacaoAPITests(BaseAPITestCase):
    def test_sem_chave_recusa(self):
        resposta = self.client.get(reverse("api:colaborador-list"))
        self.assertIn(resposta.status_code, (401, 403))

    def test_chave_invalida_recusa(self):
        resposta = self.get(reverse("api:colaborador-list"), chave="kr_naoexiste_123")
        self.assertEqual(resposta.status_code, 401)

    def test_chave_de_empresa_autentica(self):
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 200)

    def test_chave_de_cliente_alcanca_todas_as_empresas(self):
        """A chave de conta enxerga matriz e filial; a de empresa, só a matriz."""
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_cliente)
        nomes = {item["nome_completo"] for item in resposta.json()["results"]}
        self.assertIn("João da Silva Souza", nomes)
        self.assertIn("Maria Ramos", nomes)

        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        nomes = {item["nome_completo"] for item in resposta.json()["results"]}
        self.assertIn("João da Silva Souza", nomes)
        self.assertNotIn("Maria Ramos", nomes)

    def test_chave_revogada_recusa(self):
        self.chave_empresa_obj.revogar()
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 401)

    def test_chave_expirada_recusa(self):
        self.chave_empresa_obj.expira_em = timezone.now() - timedelta(minutes=1)
        self.chave_empresa_obj.save(update_fields=["expira_em"])
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 401)

    def test_cliente_suspenso_recusa(self):
        self.cliente.suspenso = True
        self.cliente.save(update_fields=["suspenso"])
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 401)

    def test_restricao_de_ip(self):
        self.chave_empresa_obj.ips_permitidos = ["203.0.113.0/24"]
        self.chave_empresa_obj.save(update_fields=["ips_permitidos"])

        recusada = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        self.assertEqual(recusada.status_code, 401)

        aceita = self.client.get(
            reverse("api:colaborador-list"),
            HTTP_X_API_KEY=self.chave_empresa,
            REMOTE_ADDR="203.0.113.42",
        )
        self.assertEqual(aceita.status_code, 200)

    def test_registrar_uso_incrementa_contador(self):
        self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        self.chave_empresa_obj.refresh_from_db()
        self.assertEqual(self.chave_empresa_obj.total_requisicoes, 1)
        self.assertIsNotNone(self.chave_empresa_obj.ultimo_uso)


# ══════════════════════════════════════════════════════════════
# Isolamento entre contas — o teste que não pode falhar
# ══════════════════════════════════════════════════════════════
class IsolamentoAPITests(BaseAPITestCase):
    def test_lista_de_colaboradores_nao_vaza(self):
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        cpfs = {item["cpf"] for item in resposta.json()["results"]}
        self.assertNotIn(self.colaborador_rival.cpf, cpfs)

    def test_detalhe_de_colaborador_alheio_da_404(self):
        url = reverse("api:colaborador-detail", args=[self.colaborador_rival.uuid])
        resposta = self.get(url, chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 404)

    def test_filtro_por_cpf_alheio_nao_revela(self):
        """Filtrar pelo CPF do vizinho devolve lista vazia, não o registro."""
        resposta = self.get(
            reverse("api:colaborador-list"),
            chave=self.chave_empresa,
            cpf=self.colaborador_rival.cpf,
        )
        self.assertEqual(resposta.json()["count"], 0)

    def test_pontos_de_outra_conta_nao_aparecem(self):
        with self.captureOnCommitCallbacks(execute=True):
            RegistroPontoService.registrar(
                colaborador=self.colaborador_rival,
                momento=timezone.now() - timedelta(hours=3),
            )
        resposta = self.get(reverse("api:ponto-list"), chave=self.chave_empresa)
        self.assertEqual(resposta.json()["count"], 0)

    def test_registrar_ponto_para_colaborador_alheio_da_404(self):
        resposta = self.post(
            reverse("api:ponto-registrar"),
            {"colaborador": str(self.colaborador_rival.uuid)},
            chave=self.chave_escrita,
        )
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(
            RegistroPonto.objects.filter(colaborador=self.colaborador_rival).exists()
        )

    def test_departamento_de_outra_conta_nao_aparece(self):
        Departamento.objects.create(empresa=self.empresa_rival, nome="RH Beta")
        resposta = self.get(reverse("api:departamento-list"), chave=self.chave_empresa)
        nomes = {item["nome"] for item in resposta.json()["results"]}
        self.assertNotIn("RH Beta", nomes)

    def test_relatorio_afd_de_empresa_alheia_da_404(self):
        resposta = self.get(
            reverse("api:relatorios:afd"),
            chave=self.chave_empresa,
            empresa=str(self.empresa_rival.uuid),
            data_inicio="2026-01-01",
            data_fim="2026-01-31",
        )
        self.assertEqual(resposta.status_code, 404)


# ══════════════════════════════════════════════════════════════
# Permissão de escrita
# ══════════════════════════════════════════════════════════════
class PermissaoEscritaTests(BaseAPITestCase):
    def test_chave_somente_leitura_nao_registra_ponto(self):
        resposta = self.post(
            reverse("api:ponto-registrar"),
            {"colaborador": str(self.joao.uuid)},
            chave=self.chave_empresa,
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(RegistroPonto.objects.count(), 0)

    def test_chave_somente_leitura_ainda_le(self):
        resposta = self.get(reverse("api:ponto-list"), chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 200)

    def test_chave_de_escrita_registra(self):
        with self.captureOnCommitCallbacks(execute=True):
            resposta = self.post(
                reverse("api:ponto-registrar"),
                {"colaborador": str(self.joao.uuid), "tipo": "entrada"},
                chave=self.chave_escrita,
            )
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(RegistroPonto.objects.count(), 1)


# ══════════════════════════════════════════════════════════════
# Registro de ponto pela API
# ══════════════════════════════════════════════════════════════
class RegistroPontoAPITests(BaseAPITestCase):
    def test_usa_o_metodo_api(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post(
                reverse("api:ponto-registrar"),
                {"colaborador": str(self.joao.uuid)},
                chave=self.chave_escrita,
            )
        registro = RegistroPonto.objects.get()
        self.assertEqual(registro.metodo, MetodoRegistro.API)

    def test_nsr_e_hash_sao_atribuidos(self):
        """A API não pode ser um caminho paralelo que fura a cadeia."""
        with self.captureOnCommitCallbacks(execute=True):
            resposta = self.post(
                reverse("api:ponto-registrar"),
                {"colaborador": str(self.joao.uuid)},
                chave=self.chave_escrita,
            )
        corpo = resposta.json()
        self.assertEqual(corpo["nsr"], 1)
        self.assertEqual(len(corpo["hash_registro"]), 64)
        self.assertEqual(corpo["hash_anterior"], "")

    def test_encadeia_com_o_registro_anterior(self):
        with self.captureOnCommitCallbacks(execute=True):
            primeiro = RegistroPontoService.registrar(
                colaborador=self.joao, momento=timezone.now() - timedelta(hours=4)
            )
            resposta = self.post(
                reverse("api:ponto-registrar"),
                {"colaborador": str(self.joao.uuid)},
                chave=self.chave_escrita,
            )
        self.assertEqual(resposta.json()["hash_anterior"], primeiro.hash_registro)

    def test_recusa_marcacao_no_futuro(self):
        futuro = (timezone.now() + timedelta(hours=2)).isoformat()
        resposta = self.post(
            reverse("api:ponto-registrar"),
            {"colaborador": str(self.joao.uuid), "data_hora": futuro},
            chave=self.chave_escrita,
        )
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()["codigo"], "data_futura")

    def test_recusa_colaborador_desligado(self):
        resposta = self.post(
            reverse("api:ponto-registrar"),
            {"colaborador": str(self.desligado.uuid)},
            chave=self.chave_escrita,
        )
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()["codigo"], "colaborador_inativo")

    def test_colaborador_inexistente_da_404(self):
        resposta = self.post(
            reverse("api:ponto-registrar"),
            {"colaborador": "00000000-0000-0000-0000-000000000000"},
            chave=self.chave_escrita,
        )
        self.assertEqual(resposta.status_code, 404)


# ══════════════════════════════════════════════════════════════
# Consulta de marcações
# ══════════════════════════════════════════════════════════════
class ConsultaPontosTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        base = timezone.now() - timedelta(days=2)
        with self.captureOnCommitCallbacks(execute=True):
            self.r1 = RegistroPontoService.registrar(
                colaborador=self.joao, momento=base.replace(hour=8, minute=0)
            )
            self.r2 = RegistroPontoService.registrar(
                colaborador=self.joao, momento=base.replace(hour=17, minute=0)
            )

    def test_sincroniza_por_nsr(self):
        """O caminho recomendado: pedir o que veio depois do último NSR visto."""
        resposta = self.get(
            reverse("api:ponto-list"), chave=self.chave_empresa, nsr_maior_que=self.r1.nsr
        )
        nsrs = [item["nsr"] for item in resposta.json()["results"]]
        self.assertEqual(nsrs, [self.r2.nsr])

    def test_nsr_nao_numerico_devolve_400(self):
        resposta = self.get(
            reverse("api:ponto-list"), chave=self.chave_empresa, nsr_maior_que="abc"
        )
        self.assertEqual(resposta.status_code, 400)

    def test_data_mal_formatada_devolve_400(self):
        resposta = self.get(
            reverse("api:ponto-list"), chave=self.chave_empresa, data_inicio="31/01/2026"
        )
        self.assertEqual(resposta.status_code, 400)

    def test_filtra_por_cpf(self):
        resposta = self.get(
            reverse("api:ponto-list"), chave=self.chave_empresa, cpf=self.joao.cpf
        )
        self.assertEqual(resposta.json()["count"], 2)

    def test_cancelado_continua_visivel(self):
        """
        A Portaria anula, não apaga. Sumir com o cancelado abriria um
        buraco no NSR e faria a integração suspeitar de adulteração.
        """
        self.r2.cancelado = True
        self.r2.save(update_fields=["cancelado"])

        resposta = self.get(reverse("api:ponto-list"), chave=self.chave_empresa)
        cancelados = [i for i in resposta.json()["results"] if i["cancelado"]]
        self.assertEqual(len(cancelados), 1)

    def test_verificar_confirma_integridade(self):
        url = reverse("api:ponto-verificar", args=[self.r1.uuid])
        corpo = self.get(url, chave=self.chave_empresa).json()
        self.assertTrue(corpo["integro"])
        self.assertEqual(corpo["hash_gravado"], corpo["hash_recalculado"])

    def test_verificar_detecta_adulteracao(self):
        """
        Altera o hash gravado direto no banco (contornando o model, que
        proíbe) e confirma que a verificação acusa.
        """
        RegistroPonto.objects.filter(pk=self.r1.pk).update(hash_registro="0" * 64)

        url = reverse("api:ponto-verificar", args=[self.r1.uuid])
        corpo = self.get(url, chave=self.chave_empresa).json()
        self.assertFalse(corpo["integro"])
        self.assertIn("DIVERG", corpo["mensagem"])


# ══════════════════════════════════════════════════════════════
# Colaboradores
# ══════════════════════════════════════════════════════════════
class ColaboradorAPITests(BaseAPITestCase):
    def test_desligados_ficam_de_fora_por_padrao(self):
        """Uma folha que recebesse desligados sem pedir pagaria quem saiu."""
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        cpfs = {item["cpf"] for item in resposta.json()["results"]}
        self.assertNotIn(self.desligado.cpf, cpfs)

    def test_desligados_com_ativo_false(self):
        resposta = self.get(
            reverse("api:colaborador-list"), chave=self.chave_empresa, ativo="false"
        )
        cpfs = {item["cpf"] for item in resposta.json()["results"]}
        self.assertIn(self.desligado.cpf, cpfs)

    def test_nao_expoe_biometria(self):
        """LGPD Art. 11: nenhuma finalidade justifica exportar o embedding."""
        resposta = self.get(reverse("api:colaborador-list"), chave=self.chave_empresa)
        item = resposta.json()["results"][0]
        self.assertIn("face_registrada", item)
        for proibido in ("embedding", "face_embedding", "foto_referencia"):
            self.assertNotIn(proibido, item)

    def test_busca_por_nome(self):
        resposta = self.get(
            reverse("api:colaborador-list"), chave=self.chave_empresa, busca="João"
        )
        self.assertEqual(resposta.json()["count"], 1)

    def test_cpf_formatado_acompanha_o_cru(self):
        resposta = self.get(
            reverse("api:colaborador-list"), chave=self.chave_empresa, cpf=self.joao.cpf
        )
        item = resposta.json()["results"][0]
        self.assertEqual(item["cpf"], "52998224725")
        self.assertEqual(item["cpf_formatado"], "529.982.247-25")


# ══════════════════════════════════════════════════════════════
# Banco de horas
# ══════════════════════════════════════════════════════════════
class BancoHorasAPITests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        hoje = timezone.localdate()
        for indice in range(3):
            BancoHoras.objects.create(
                empresa=self.empresa,
                colaborador=self.joao,
                data=hoje - timedelta(days=indice + 1),
                minutos_trabalhados=490,
                minutos_esperados=480,
                minutos_extras=10,
                saldo_dia=10,
                saldo_acumulado=10 * (3 - indice),
                status=StatusDia.COMPLETO,
            )

    def test_lista_traz_minutos_e_hhmm(self):
        resposta = self.get(reverse("api:bancohoras-list"), chave=self.chave_empresa)
        item = resposta.json()["results"][0]
        self.assertEqual(item["minutos_trabalhados"], 490)
        self.assertEqual(item["horas_trabalhadas"], "08:10")

    def test_saldo_negativo_sai_com_sinal(self):
        BancoHoras.objects.create(
            empresa=self.empresa, colaborador=self.joao,
            data=timezone.localdate() - timedelta(days=10),
            minutos_trabalhados=400, minutos_esperados=480,
            saldo_dia=-80, saldo_acumulado=-80, status=StatusDia.COMPLETO,
        )
        resposta = self.get(
            reverse("api:bancohoras-list"), chave=self.chave_empresa,
            data_inicio=(timezone.localdate() - timedelta(days=10)).isoformat(),
            data_fim=(timezone.localdate() - timedelta(days=10)).isoformat(),
        )
        self.assertEqual(resposta.json()["results"][0]["saldo"], "-01:20")

    def test_resumo_agrega_o_periodo(self):
        hoje = timezone.localdate()
        resposta = self.get(
            reverse("api:bancohoras-resumo"), chave=self.chave_empresa,
            data_inicio=(hoje - timedelta(days=5)).isoformat(),
            data_fim=hoje.isoformat(),
        )
        linha = resposta.json()[0]
        self.assertEqual(linha["minutos_trabalhados"], 1470)
        self.assertEqual(linha["minutos_extras"], 30)
        self.assertEqual(linha["saldo_periodo"], 30)

    def test_resumo_exige_periodo(self):
        resposta = self.get(reverse("api:bancohoras-resumo"), chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 400)

    def test_resumo_recusa_periodo_invertido(self):
        resposta = self.get(
            reverse("api:bancohoras-resumo"), chave=self.chave_empresa,
            data_inicio="2026-03-31", data_fim="2026-03-01",
        )
        self.assertEqual(resposta.status_code, 400)


# ══════════════════════════════════════════════════════════════
# Atestados
# ══════════════════════════════════════════════════════════════
class AtestadoAPITests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.atestado = Atestado.objects.create(
            empresa=self.empresa,
            colaborador=self.joao,
            data_inicio=timezone.localdate() - timedelta(days=3),
            data_fim=timezone.localdate() - timedelta(days=1),
            dias=3,
            cid="J11",
        )

    def test_nao_expoe_cid(self):
        """Dado de saúde não sai da plataforma (LGPD, Art. 5º, II)."""
        resposta = self.get(reverse("api:atestado-list"), chave=self.chave_empresa)
        item = resposta.json()["results"][0]
        self.assertNotIn("cid", item)
        self.assertEqual(item["dias"], 3)


# ══════════════════════════════════════════════════════════════
# Relatórios fiscais
# ══════════════════════════════════════════════════════════════
class RelatoriosAPITests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        base = timezone.now() - timedelta(days=1)
        with self.captureOnCommitCallbacks(execute=True):
            RegistroPontoService.registrar(
                colaborador=self.joao, momento=base.replace(hour=8, minute=0)
            )
            RegistroPontoService.registrar(
                colaborador=self.joao, momento=base.replace(hour=17, minute=0)
            )
        self.inicio = (timezone.localdate() - timedelta(days=5)).isoformat()
        self.fim = timezone.localdate().isoformat()

    def test_afd_sai_em_texto_iso_8859_1(self):
        resposta = self.get(
            reverse("api:relatorios:afd"), chave=self.chave_empresa,
            data_inicio=self.inicio, data_fim=self.fim,
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("iso-8859-1", resposta["Content-Type"])
        self.assertIn("attachment", resposta["Content-Disposition"])

    def test_afd_da_api_e_igual_ao_do_gerador(self):
        """
        O arquivo da API tem de ser o mesmo da tela do RH: dois
        "originais" diferentes tornariam impossível dizer qual foi
        entregue ao fiscal.

        A comparação ignora `data_geracao`/`hora_geracao` do cabeçalho —
        e só eles. Esses campos gravam *quando o arquivo foi emitido*, e
        duas emissões em segundos diferentes divergem legitimamente ali.
        Exigir igualdade byte a byte no arquivo inteiro seria um teste
        que falha sozinho ao virar o segundo, sem nada de errado no
        sistema.
        """
        from apps.relatorios.afd import AFDGenerator, posicao_do_campo

        esperado = AFDGenerator(
            self.empresa,
            date.fromisoformat(self.inicio),
            date.fromisoformat(self.fim),
        ).gerar()
        obtido = self.get(
            reverse("api:relatorios:afd"), chave=self.chave_empresa,
            data_inicio=self.inicio, data_fim=self.fim,
        ).content.decode("iso-8859-1")

        linhas_esperadas = esperado.split("\r\n")
        linhas_obtidas = obtido.split("\r\n")
        self.assertEqual(len(linhas_obtidas), len(linhas_esperadas))

        # O tipo do registro vem **depois** do NSR, nunca na posição 0.
        # Toda posição sai de `posicao_do_campo`, nunca de índice
        # literal — foi um índice chutado que já mascarou um bug de
        # contagem no trailer, na Fase 4.
        inicio_geracao, fim_geracao = posicao_do_campo("1", "data_hora_geracao")

        def tipo_de(linha):
            from apps.relatorios.afd import tipo_da_linha

            return tipo_da_linha(linha)

        for indice, (uma, outra) in enumerate(zip(linhas_esperadas, linhas_obtidas)):
            if tipo_de(uma) == "1":
                # Cabeçalho: mascara o instante de emissão **e o CRC-16**,
                # que é calculado sobre a linha inteira e portanto muda
                # junto com ele.
                crc_ini, crc_fim = posicao_do_campo("1", "crc16")
                uma = uma[:inicio_geracao] + uma[fim_geracao:crc_ini]
                outra = outra[:inicio_geracao] + outra[fim_geracao:crc_ini]
            self.assertEqual(uma, outra, f"divergência na linha {indice + 1}")

        # E as marcações — a substância do arquivo — batem exatamente.
        marcacoes_esperadas = [l for l in linhas_esperadas if tipo_de(l) == "7"]
        marcacoes_obtidas = [l for l in linhas_obtidas if tipo_de(l) == "7"]
        self.assertTrue(marcacoes_esperadas)
        self.assertEqual(marcacoes_esperadas, marcacoes_obtidas)

    def test_afd_avisa_que_o_layout_nao_foi_conferido(self):
        """
        O alerta de conformidade que está na tela do RH precisa chegar
        também a quem consome pela API — senão a integração acredita
        num arquivo cujo layout ainda não foi validado contra o Anexo.
        """
        resposta = self.get(
            reverse("api:relatorios:afd"), chave=self.chave_empresa,
            data_inicio=self.inicio, data_fim=self.fim,
        )
        self.assertEqual(
            resposta["X-Kronus-Layout"], "nao-conferido-com-anexo-oficial"
        )

    def test_aej_responde(self):
        resposta = self.get(
            reverse("api:relatorios:aej"), chave=self.chave_empresa,
            data_inicio=self.inicio, data_fim=self.fim,
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertGreater(len(resposta.content), 0)

    def test_relatorio_exige_periodo(self):
        resposta = self.get(reverse("api:relatorios:afd"), chave=self.chave_empresa)
        self.assertEqual(resposta.status_code, 400)

    def test_chave_de_cliente_precisa_dizer_a_empresa(self):
        """O arquivo fiscal é sempre de um CNPJ; ambiguidade vira erro."""
        resposta = self.get(
            reverse("api:relatorios:afd"), chave=self.chave_cliente,
            data_inicio=self.inicio, data_fim=self.fim,
        )
        self.assertEqual(resposta.status_code, 400)

        resposta = self.get(
            reverse("api:relatorios:afd"), chave=self.chave_cliente,
            empresa=str(self.empresa.uuid),
            data_inicio=self.inicio, data_fim=self.fim,
        )
        self.assertEqual(resposta.status_code, 200)

    def test_espelho_em_json(self):
        hoje = timezone.localdate()
        resposta = self.get(
            reverse("api:relatorios:espelho"), chave=self.chave_empresa,
            colaborador=str(self.joao.uuid), ano=hoje.year, mes=hoje.month,
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertEqual(corpo["colaborador"]["cpf"], self.joao.cpf)
        self.assertEqual(len(corpo["hash_documento"]), 64)
        self.assertIsInstance(corpo["linhas"], list)

    def test_espelho_de_colaborador_alheio_da_404(self):
        hoje = timezone.localdate()
        resposta = self.get(
            reverse("api:relatorios:espelho"), chave=self.chave_empresa,
            colaborador=str(self.colaborador_rival.uuid), ano=hoje.year, mes=hoje.month,
        )
        self.assertEqual(resposta.status_code, 404)

    def test_espelho_recusa_mes_invalido(self):
        resposta = self.get(
            reverse("api:relatorios:espelho"), chave=self.chave_empresa,
            colaborador=str(self.joao.uuid), ano=2026, mes=13,
        )
        self.assertEqual(resposta.status_code, 400)


# ══════════════════════════════════════════════════════════════
# Conta e rate limiting
# ══════════════════════════════════════════════════════════════
class ContaERateLimitTests(BaseAPITestCase):
    def test_conta_descreve_a_credencial(self):
        corpo = self.get(reverse("api:conta"), chave=self.chave_empresa).json()
        self.assertEqual(corpo["credencial"]["tipo"], "empresa")
        self.assertEqual(corpo["credencial"]["nome"], "ERP folha")
        self.assertTrue(corpo["credencial"]["somente_leitura"])
        self.assertEqual(corpo["plano"]["nome"], "Pro")
        self.assertEqual(len(corpo["empresas"]), 1)

    def test_conta_de_chave_de_cliente_lista_todas(self):
        corpo = self.get(reverse("api:conta"), chave=self.chave_cliente).json()
        self.assertEqual(corpo["credencial"]["tipo"], "cliente")
        self.assertEqual(len(corpo["empresas"]), 2)

    def test_limite_e_o_menor_entre_plano_e_chave(self):
        """A chave não compra cota além do que o plano vendeu."""
        self.chave_empresa_obj.rate_limit_hora = 200
        self.chave_empresa_obj.save(update_fields=["rate_limit_hora"])
        corpo = self.get(reverse("api:conta"), chave=self.chave_empresa).json()
        self.assertEqual(corpo["limite_hora"], 200)

        self.chave_empresa_obj.rate_limit_hora = 99999
        self.chave_empresa_obj.save(update_fields=["rate_limit_hora"])
        corpo = self.get(reverse("api:conta"), chave=self.chave_empresa).json()
        self.assertEqual(corpo["limite_hora"], 1000)  # teto do plano Pro

    def test_troca_de_plano_muda_a_cota_na_hora(self):
        self.cliente.plano = self.plano_basico
        self.cliente.save(update_fields=["plano"])
        self.chave_empresa_obj.rate_limit_hora = 5000
        self.chave_empresa_obj.save(update_fields=["rate_limit_hora"])

        corpo = self.get(reverse("api:conta"), chave=self.chave_empresa).json()
        self.assertEqual(corpo["limite_hora"], 100)

    def test_estourar_a_cota_devolve_429(self):
        self.chave_empresa_obj.rate_limit_hora = 3
        self.chave_empresa_obj.save(update_fields=["rate_limit_hora"])

        url = reverse("api:colaborador-list")
        for _ in range(3):
            self.assertEqual(self.get(url, chave=self.chave_empresa).status_code, 200)

        self.assertEqual(self.get(url, chave=self.chave_empresa).status_code, 429)

    def test_cotas_de_chaves_diferentes_nao_se_misturam(self):
        self.chave_empresa_obj.rate_limit_hora = 2
        self.chave_empresa_obj.save(update_fields=["rate_limit_hora"])

        url = reverse("api:colaborador-list")
        for _ in range(2):
            self.get(url, chave=self.chave_empresa)
        self.assertEqual(self.get(url, chave=self.chave_empresa).status_code, 429)

        # A outra chave da mesma empresa segue com cota própria.
        self.assertEqual(self.get(url, chave=self.chave_escrita).status_code, 200)


# ══════════════════════════════════════════════════════════════
# Webhooks — assinatura
# ══════════════════════════════════════════════════════════════
class AssinaturaWebhookTests(TestCase):
    def test_assinatura_inclui_o_timestamp(self):
        """
        Assinar só o corpo permitiria reenviar uma entrega antiga
        indefinidamente. Com o timestamp dentro do HMAC, o receptor pode
        recusar o que estiver fora da janela.
        """
        from apps.notificacoes.webhooks import assinar

        corpo = b'{"evento":"ponto.registrado"}'
        uma = assinar(corpo, "segredo", 1000)
        outra = assinar(corpo, "segredo", 2000)
        self.assertNotEqual(uma, outra)

    def test_assinatura_confere_com_o_calculo_manual(self):
        from apps.notificacoes.webhooks import assinar

        corpo = b'{"a":1}'
        esperado = hmac.new(
            b"segredo", b"1700000000." + corpo, hashlib.sha256
        ).hexdigest()
        self.assertEqual(assinar(corpo, "segredo", 1700000000), f"sha256={esperado}")

    def test_verificacao_recusa_segredo_errado(self):
        from apps.notificacoes.webhooks import assinar, assinatura_confere

        corpo = b'{"a":1}'
        assinatura = assinar(corpo, "certo", 1700000000)
        self.assertTrue(assinatura_confere(corpo, "certo", 1700000000, assinatura))
        self.assertFalse(assinatura_confere(corpo, "errado", 1700000000, assinatura))


# ══════════════════════════════════════════════════════════════
# Webhooks — entrega
# ══════════════════════════════════════════════════════════════
class EntregaWebhookTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.webhook = Webhook.objects.create(
            empresa=self.empresa,
            nome="ERP",
            url="https://erp.exemplo.com/kronus/",
            eventos=["ponto.registrado", "colaborador.desligado"],
            segredo="segredo-de-teste",
        )

    def test_ponto_registrado_gera_entrega(self):
        with patch("requests.post", return_value=RespostaFalsa()):
            with self.captureOnCommitCallbacks(execute=True):
                RegistroPontoService.registrar(
                    colaborador=self.joao, momento=timezone.now() - timedelta(hours=2)
                )

        entrega = EntregaWebhook.objects.get(evento="ponto.registrado")
        self.assertEqual(entrega.status, EntregaWebhook.Status.ENTREGUE)
        self.assertEqual(entrega.payload["dados"]["colaborador"]["cpf"], self.joao.cpf)

    def test_evento_nao_assinado_nao_gera_entrega(self):
        self.webhook.eventos = ["atestado.aprovado"]
        self.webhook.save(update_fields=["eventos"])

        with self.captureOnCommitCallbacks(execute=True):
            RegistroPontoService.registrar(
                colaborador=self.joao, momento=timezone.now() - timedelta(hours=2)
            )
        self.assertEqual(EntregaWebhook.objects.count(), 0)

    def test_plano_sem_webhook_nao_dispara(self):
        self.cliente.plano = self.plano_basico
        self.cliente.save(update_fields=["plano"])

        with self.captureOnCommitCallbacks(execute=True):
            RegistroPontoService.registrar(
                colaborador=self.joao, momento=timezone.now() - timedelta(hours=2)
            )
        self.assertEqual(EntregaWebhook.objects.count(), 0)

    def test_cabecalhos_da_entrega(self):
        from apps.notificacoes.webhooks import assinatura_confere, executar

        entrega = EntregaWebhook.objects.create(
            webhook=self.webhook, empresa=self.empresa,
            evento="ponto.registrado", identificador=self.joao.uuid,
            payload={"evento": "ponto.registrado"},
        )

        with patch("requests.post", return_value=RespostaFalsa()) as chamada:
            executar(entrega)

        _, kwargs = chamada.call_args
        cabecalhos = kwargs["headers"]
        self.assertEqual(cabecalhos["X-Kronus-Event"], "ponto.registrado")
        self.assertEqual(cabecalhos["X-Kronus-Delivery"], str(self.joao.uuid))
        self.assertTrue(cabecalhos["X-Kronus-Signature"].startswith("sha256="))
        self.assertTrue(
            assinatura_confere(
                kwargs["data"],
                self.webhook.segredo,
                int(cabecalhos["X-Kronus-Timestamp"]),
                cabecalhos["X-Kronus-Signature"],
            )
        )

    def test_falha_agenda_retentativa_com_backoff(self):
        from apps.notificacoes.webhooks import executar

        entrega = EntregaWebhook.objects.create(
            webhook=self.webhook, empresa=self.empresa,
            evento="ponto.registrado", identificador=self.joao.uuid, payload={},
        )

        with patch("requests.post", return_value=RespostaFalsa(500, "erro interno")):
            self.assertFalse(executar(entrega))

        entrega.refresh_from_db()
        self.assertEqual(entrega.status, EntregaWebhook.Status.PENDENTE)
        self.assertEqual(entrega.tentativas, 1)
        self.assertIsNotNone(entrega.proxima_tentativa)
        self.assertIn("erro interno", entrega.resposta)

    def test_timeout_conta_como_falha(self):
        from apps.notificacoes.webhooks import executar

        entrega = EntregaWebhook.objects.create(
            webhook=self.webhook, empresa=self.empresa,
            evento="ponto.registrado", identificador=self.joao.uuid, payload={},
        )
        with patch("requests.post", side_effect=TimeoutError("estourou")):
            self.assertFalse(executar(entrega))

        entrega.refresh_from_db()
        self.assertIsNone(entrega.status_code)
        self.assertIn("TimeoutError", entrega.resposta)

    def test_desiste_apos_esgotar_o_backoff(self):
        from apps.notificacoes.webhooks import BACKOFF_SEGUNDOS, executar

        entrega = EntregaWebhook.objects.create(
            webhook=self.webhook, empresa=self.empresa,
            evento="ponto.registrado", identificador=self.joao.uuid, payload={},
        )
        with patch("requests.post", return_value=RespostaFalsa(500)):
            for _ in range(len(BACKOFF_SEGUNDOS)):
                executar(entrega)

        entrega.refresh_from_db()
        self.assertEqual(entrega.status, EntregaWebhook.Status.DESISTIU)
        self.assertIsNone(entrega.proxima_tentativa)

    def test_cinco_falhas_desativam_o_webhook(self):
        """Endpoint morto não deve consumir fila para sempre."""
        from apps.notificacoes.webhooks import LIMITE_FALHAS, executar

        with patch("requests.post", return_value=RespostaFalsa(502)):
            for _ in range(LIMITE_FALHAS):
                entrega = EntregaWebhook.objects.create(
                    webhook=self.webhook, empresa=self.empresa,
                    evento="ponto.registrado", identificador=self.joao.uuid, payload={},
                )
                executar(entrega)

        self.webhook.refresh_from_db()
        self.assertFalse(self.webhook.ativo)
        self.assertEqual(self.webhook.falhas_consecutivas, LIMITE_FALHAS)

    def test_sucesso_zera_o_contador_de_falhas(self):
        from apps.notificacoes.webhooks import executar

        self.webhook.falhas_consecutivas = 3
        self.webhook.save(update_fields=["falhas_consecutivas"])

        entrega = EntregaWebhook.objects.create(
            webhook=self.webhook, empresa=self.empresa,
            evento="ponto.registrado", identificador=self.joao.uuid, payload={},
        )
        with patch("requests.post", return_value=RespostaFalsa(204)):
            executar(entrega)

        self.webhook.refresh_from_db()
        self.assertEqual(self.webhook.falhas_consecutivas, 0)

    def test_task_nao_reentrega_o_que_ja_foi_entregue(self):
        """on_commit e varredura podem enfileirar a mesma entrega."""
        from apps.notificacoes.tasks import entregar_webhook

        entrega = EntregaWebhook.objects.create(
            webhook=self.webhook, empresa=self.empresa,
            evento="ponto.registrado", identificador=self.joao.uuid, payload={},
            status=EntregaWebhook.Status.ENTREGUE,
        )
        with patch("requests.post") as chamada:
            entregar_webhook(entrega.pk)
        chamada.assert_not_called()

    def test_falha_de_webhook_nao_derruba_o_ponto(self):
        """
        A batida é a obrigação legal; o webhook é conveniência. Um ERP
        quebrado do cliente não pode impedir alguém de bater ponto.
        """
        with patch(
            "apps.notificacoes.webhooks.disparar", side_effect=RuntimeError("boom")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                registro = RegistroPontoService.registrar(
                    colaborador=self.joao, momento=timezone.now() - timedelta(hours=2)
                )
        self.assertEqual(RegistroPonto.objects.filter(pk=registro.pk).count(), 1)


# ══════════════════════════════════════════════════════════════
# Webhooks — eventos de cadastro
# ══════════════════════════════════════════════════════════════
class EventosDeCadastroTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.webhook = Webhook.objects.create(
            empresa=self.empresa, nome="ERP",
            url="https://erp.exemplo.com/kronus/",
            eventos=[
                "colaborador.criado", "colaborador.desligado", "atestado.aprovado",
            ],
            segredo="s",
        )

    def test_colaborador_criado(self):
        with patch("requests.post", return_value=RespostaFalsa()):
            with self.captureOnCommitCallbacks(execute=True):
                Colaborador.objects.create(
                    empresa=self.empresa, cpf="19100000000",
                    nome_completo="Novo Colaborador",
                    data_nascimento=date(1995, 5, 5),
                    data_admissao=date(2026, 1, 5),
                )
        self.assertTrue(
            EntregaWebhook.objects.filter(evento="colaborador.criado").exists()
        )

    def test_desligamento_e_detectado_pela_transicao(self):
        colaborador = Colaborador.objects.get(pk=self.joao.pk)

        with patch("requests.post", return_value=RespostaFalsa()):
            with self.captureOnCommitCallbacks(execute=True):
                colaborador.ativo = False
                colaborador.data_demissao = timezone.localdate()
                colaborador.save()

        self.assertEqual(
            EntregaWebhook.objects.filter(evento="colaborador.desligado").count(), 1
        )

    def test_salvar_de_novo_nao_redispara_o_desligamento(self):
        colaborador = Colaborador.objects.get(pk=self.joao.pk)

        with patch("requests.post", return_value=RespostaFalsa()):
            with self.captureOnCommitCallbacks(execute=True):
                colaborador.ativo = False
                colaborador.save()
                colaborador.observacoes = "anotação"
                colaborador.save()

        self.assertEqual(
            EntregaWebhook.objects.filter(evento="colaborador.desligado").count(), 1
        )

    def test_atestado_aprovado(self):
        from apps.accounts.models import CustomUser

        operador = CustomUser.objects.create_user(
            username="rh@alfa.com", password="x", nome_completo="Operadora RH",
            tipo=TipoUsuario.RH
        )
        atestado = Atestado.objects.create(
            empresa=self.empresa, colaborador=self.joao,
            data_inicio=timezone.localdate() - timedelta(days=2),
            data_fim=timezone.localdate(), dias=3,
        )
        with patch("requests.post", return_value=RespostaFalsa()):
            with self.captureOnCommitCallbacks(execute=True):
                atestado.aprovar(operador)

        entrega = EntregaWebhook.objects.get(evento="atestado.aprovado")
        # O CID nunca sai, nem por webhook.
        self.assertNotIn("cid", entrega.payload["dados"])


# ══════════════════════════════════════════════════════════════
# Painel Master — totens e comodato
# ══════════════════════════════════════════════════════════════
class MasterTotemTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        from apps.accounts.models import CustomUser

        self.master = CustomUser.objects.create_user(
            username="master@kstec.online", password="senha-forte-123",
            nome_completo="Operador KS TEC", tipo=TipoUsuario.MASTER, is_staff=True,
        )
        self.client.force_login(self.master)

    def test_lista_do_parque_abre(self):
        resposta = self.client.get(reverse("master:totem_lista"))
        self.assertEqual(resposta.status_code, 200)

    def test_cadastro_gera_token_sem_ninguem_digitar(self):
        resposta = self.client.post(
            reverse("master:totem_criar"),
            {
                "identificador": "totem recepcao 01",
                "empresa": self.empresa.pk,
                "modelo_tablet": "Positivo Tab 7 Vision",
                "permite_fallback_cpf": "on",
                "segundos_tela_sucesso": 5,
                "segundos_countdown_offline": 120,
                "ativo": "on",
            },
        )
        self.assertEqual(resposta.status_code, 302)

        from apps.totem.models import Totem

        totem = Totem.objects.get()
        self.assertEqual(totem.identificador, "TOTEM-RECEPCAO-01")
        # `gerar_token(32)` = 32 bytes em base64 urlsafe. O que importa
        # e ser longo o bastante para nao ser adivinhavel; o numero
        # exato de caracteres e detalhe da codificacao.
        self.assertGreaterEqual(len(totem.token_acesso), 40)

    def test_limite_de_totens_do_plano_e_respeitado(self):
        from apps.totem.models import Totem

        self.plano.max_totems = 1
        self.plano.save(update_fields=["max_totems"])
        Totem.objects.create(identificador="TOTEM-01", empresa=self.empresa)

        resposta = self.client.post(
            reverse("master:totem_criar"),
            {
                "identificador": "TOTEM-02",
                "empresa": self.empresa.pk,
                "segundos_tela_sucesso": 5,
                "segundos_countdown_offline": 120,
                "ativo": "on",
            },
        )
        self.assertEqual(resposta.status_code, 200)  # reexibe com erro
        self.assertEqual(Totem.objects.count(), 1)

    def test_grupo_nao_atravessa_clientes(self):
        """Regra 12 da Seção 14: um grupo nunca junta contas diferentes."""
        from apps.master.forms import GrupoTotemForm

        form = GrupoTotemForm(data={
            "cliente": self.cliente.pk,
            "nome": "Portaria compartilhada",
            "empresas": [self.empresa.pk, self.empresa_rival.pk],
            "ativo": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("empresas", form.errors)

    def test_grupo_de_outro_cliente_no_totem_e_recusado(self):
        from apps.master.forms import TotemForm
        from apps.totem.models import GrupoTotem

        grupo = GrupoTotem.objects.create(cliente=self.rival, nome="Beta")
        form = TotemForm(data={
            "identificador": "TOTEM-X",
            "empresa": self.empresa.pk,
            "grupo": grupo.pk,
            "segundos_tela_sucesso": 5,
            "segundos_countdown_offline": 120,
            "ativo": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("grupo", form.errors)

    def test_regenerar_token_invalida_o_anterior(self):
        from apps.totem.models import EventoTotem, Totem

        totem = Totem.objects.create(identificador="TOTEM-01", empresa=self.empresa)
        antigo = totem.token_acesso

        self.client.post(reverse("master:totem_regenerar_token", args=[totem.pk]))
        totem.refresh_from_db()

        self.assertNotEqual(totem.token_acesso, antigo)
        self.assertTrue(
            EventoTotem.objects.filter(
                totem=totem, tipo=EventoTotem.Tipo.CONFIGURACAO
            ).exists()
        )

    def test_devolucao_preserva_o_historico(self):
        """
        O AFD referencia o identificador do dispositivo e precisa
        continuar reproduzível anos depois — devolver não apaga.
        """
        from apps.totem.models import Totem

        totem = Totem.objects.create(identificador="TOTEM-01", empresa=self.empresa)
        with self.captureOnCommitCallbacks(execute=True):
            registro = RegistroPontoService.registrar(
                colaborador=self.joao,
                momento=timezone.now() - timedelta(hours=2),
                totem=totem,
                metodo=MetodoRegistro.FACIAL,
            )

        self.client.post(reverse("master:totem_devolver", args=[totem.pk]))
        totem.refresh_from_db()
        registro.refresh_from_db()

        self.assertFalse(totem.ativo)
        self.assertIsNotNone(totem.data_devolucao)
        self.assertEqual(registro.totem_id, totem.pk)

    def test_rh_nao_acessa_o_parque_de_totens(self):
        from apps.accounts.models import CustomUser

        rh = CustomUser.objects.create_user(
            username="rh@alfa.com", password="senha-forte-123",
            nome_completo="Analista RH", tipo=TipoUsuario.RH,
        )
        self.client.force_login(rh)
        resposta = self.client.get(reverse("master:totem_lista"))
        self.assertNotEqual(resposta.status_code, 200)


# ══════════════════════════════════════════════════════════════
# Documentação da API
# ══════════════════════════════════════════════════════════════
class DocumentacaoAPITests(TestCase):
    def test_schema_openapi_e_gerado(self):
        resposta = self.client.get(reverse("api:schema"))
        self.assertEqual(resposta.status_code, 200)

    def test_schema_declara_os_esquemas_de_seguranca(self):
        """
        Sem isso o Swagger não mostra o botão "Authorize" e a
        documentação vira uma lista de endpoints que dão 401.
        """
        import yaml

        corpo = yaml.safe_load(self.client.get(reverse("api:schema")).content)
        esquemas = corpo["components"]["securitySchemes"]
        self.assertIn("ChaveDeAPI", esquemas)
        self.assertEqual(esquemas["ChaveDeAPI"]["name"], "X-API-Key")
        self.assertIn("TokenDoTotem", esquemas)

    def test_swagger_abre(self):
        resposta = self.client.get(reverse("api:swagger"))
        self.assertEqual(resposta.status_code, 200)
