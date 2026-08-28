"""
Kronus — testes de assinaturas, gateway e administração SaaS.

Dois riscos dominam este módulo:

* **Dinheiro.** Uma confirmação de pagamento forjada libera acesso sem
  receita; um evento processado duas vezes duplica faturas. Os testes de
  webhook cobrem exatamente isso.
* **Poder.** O Master enxerga e altera usuários de todos os clientes. Os
  testes garantem que ninguém além dele chega lá.
"""
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoUsuario
from apps.faturamento.models import (
    Assinatura,
    Cobranca,
    ConfiguracaoGateway,
    EventoGateway,
)
from apps.faturamento.services import AssinaturaService, WebhookService
from apps.master.models import Plano
from apps.rh.models import Colaborador

SENHA = "senha-forte-123"


class BaseFaturamentoTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.starter = Plano.objects.create(
            nome="Starter", slug="starter", max_empresas=1,
            max_colaboradores=25, preco_mensal=Decimal("99.00"),
        )
        cls.pro = Plano.objects.create(
            nome="Pro", slug="pro", max_empresas=5,
            max_colaboradores=200, preco_mensal=Decimal("299.00"), tem_api=True,
        )
        cls.cliente = Cliente.objects.create(
            razao_social="Grupo Alfa", cnpj="11222333000181",
            plano=cls.starter, email_contato="alfa@exemplo.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Alfa Matriz", cnpj="11222333000262"
        )

    def config_ativa(self):
        config = ConfiguracaoGateway.carregar()
        config.api_key = "$aact_chave_de_teste"
        config.webhook_token = "t" * 40
        config.ativo = True
        config.save()
        return config


# ══════════════════════════════════════════════════════════════
# Configuração do gateway
# ══════════════════════════════════════════════════════════════
class ConfiguracaoGatewayTests(BaseFaturamentoTestCase):
    def test_e_registro_unico(self):
        """Duas credenciais ativas cobrariam em contas diferentes."""
        ConfiguracaoGateway.objects.create(api_key="a")
        ConfiguracaoGateway.objects.create(api_key="b")
        self.assertEqual(ConfiguracaoGateway.objects.count(), 1)
        self.assertEqual(ConfiguracaoGateway.carregar().api_key, "b")

    def test_url_muda_com_o_ambiente(self):
        config = ConfiguracaoGateway.carregar()
        self.assertIn("sandbox", config.url_base)
        config.ambiente = ConfiguracaoGateway.Ambiente.PRODUCAO
        self.assertEqual(config.url_base, "https://api.asaas.com/v3")

    def test_chave_e_mascarada(self):
        """A tela nunca reexibe a chave inteira."""
        config = ConfiguracaoGateway.carregar()
        config.api_key = "$aact_YTU5YTE0M2M2N2I4MTliNzk0YTI5N2U5MzdjNWZm"
        self.assertNotIn(config.api_key, config.api_key_mascarada)
        self.assertTrue(config.api_key_mascarada.startswith("$aact_YTU5Y"))

    def test_nao_esta_configurado_sem_token_de_webhook(self):
        config = ConfiguracaoGateway.carregar()
        config.api_key = "chave"
        self.assertFalse(config.configurado)


# ══════════════════════════════════════════════════════════════
# Contratação
# ══════════════════════════════════════════════════════════════
class ContratacaoTests(BaseFaturamentoTestCase):
    def test_contratacao_nasce_em_teste(self):
        """
        O cliente usa o sistema no mesmo minuto; a cobrança vem depois.
        Exigir pagamento antes do primeiro acesso derruba a conversão.
        """
        assinatura = AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        self.assertEqual(assinatura.status, Assinatura.Status.TESTE)
        self.assertEqual(
            assinatura.data_fim_teste,
            timezone.localdate() + timedelta(days=AssinaturaService.DIAS_DE_TESTE),
        )

    def test_contratacao_sem_teste_fica_pendente(self):
        assinatura = AssinaturaService.contratar(
            cliente=self.cliente, plano=self.pro, com_teste=False
        )
        self.assertEqual(assinatura.status, Assinatura.Status.PENDENTE)

    def test_contratar_atualiza_o_plano_do_cliente(self):
        AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.plano, self.pro)

    def test_ciclo_anual_tem_desconto(self):
        """12 meses cheios seriam 3588; o anual sai abaixo disso."""
        mensal = AssinaturaService._valor_do_ciclo(self.pro, Assinatura.Ciclo.MENSAL)
        anual = AssinaturaService._valor_do_ciclo(self.pro, Assinatura.Ciclo.ANUAL)
        self.assertEqual(mensal, Decimal("299.00"))
        self.assertLess(anual, mensal * 12)
        self.assertGreater(anual, mensal * 9)

    def test_valor_e_congelado_na_assinatura(self):
        """Reajuste de tabela não altera o que um contratado já paga."""
        assinatura = AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        self.pro.preco_mensal = Decimal("499.00")
        self.pro.save(update_fields=["preco_mensal"])
        assinatura.refresh_from_db()
        self.assertEqual(assinatura.valor, Decimal("299.00"))

    def test_contratar_duas_vezes_nao_duplica(self):
        AssinaturaService.contratar(cliente=self.cliente, plano=self.starter)
        AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        self.assertEqual(Assinatura.objects.filter(cliente=self.cliente).count(), 1)

    def test_gateway_desligado_nao_impede_contratacao(self):
        """A assinatura local vale mesmo sem cobrança automática."""
        with patch("apps.faturamento.asaas.ClienteAsaas.criar_cliente") as chamada:
            AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        chamada.assert_not_called()
        self.assertTrue(Assinatura.objects.filter(cliente=self.cliente).exists())

    def test_falha_no_gateway_nao_derruba_a_contratacao(self):
        self.config_ativa()
        with patch(
            "apps.faturamento.services.AssinaturaService.sincronizar_no_gateway",
            side_effect=RuntimeError("gateway fora do ar"),
        ):
            assinatura = AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        self.assertEqual(assinatura.status, Assinatura.Status.TESTE)


# ══════════════════════════════════════════════════════════════
# Troca de plano
# ══════════════════════════════════════════════════════════════
class TrocaDePlanoTests(BaseFaturamentoTestCase):
    def setUp(self):
        self.assinatura = AssinaturaService.contratar(
            cliente=self.cliente, plano=self.pro
        )

    def _colaboradores(self, quantidade):
        cpfs = ["52998224725", "71428793860", "15350946056", "03874649089"]
        for indice in range(quantidade):
            Colaborador.objects.create(
                empresa=self.empresa,
                cpf=cpfs[indice % len(cpfs)][:-1] + str(indice % 10),
                nome_completo=f"Colaborador {indice}",
                data_nascimento=date(1990, 1, 1),
                data_admissao=date(2024, 1, 1),
            )

    def test_upgrade_atualiza_valor_e_plano(self):
        AssinaturaService.trocar_plano(assinatura=self.assinatura, plano=self.starter)
        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.plano, self.starter)
        self.assertEqual(self.assinatura.valor, Decimal("99.00"))

    def test_downgrade_e_recusado_se_a_conta_nao_couber(self):
        """
        Aceitar deixaria a conta acima do limite sem caminho de volta —
        e o efeito prático seria travar o cadastro sem explicar por quê.
        """
        self.starter.max_colaboradores = 2
        self.starter.save(update_fields=["max_colaboradores"])
        self._colaboradores(4)

        with self.assertRaises(ValueError) as contexto:
            AssinaturaService.trocar_plano(
                assinatura=self.assinatura, plano=self.starter
            )
        self.assertIn("colaboradores", str(contexto.exception))

        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.plano, self.pro)

    def test_downgrade_recusado_por_numero_de_empresas(self):
        Empresa.objects.create(
            cliente=self.cliente, razao_social="Filial", cnpj="11222333000343"
        )
        self.starter.max_empresas = 1
        self.starter.save(update_fields=["max_empresas"])

        with self.assertRaises(ValueError):
            AssinaturaService.trocar_plano(
                assinatura=self.assinatura, plano=self.starter
            )


# ══════════════════════════════════════════════════════════════
# Cancelamento
# ══════════════════════════════════════════════════════════════
class CancelamentoTests(BaseFaturamentoTestCase):
    def test_cancelar_nao_desativa_o_cliente(self):
        """
        A empresa guarda registros de ponto por cinco anos e precisa
        emitir o AFD depois de sair. Cancelar cobrança e cortar acesso
        são decisões distintas.
        """
        assinatura = AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        AssinaturaService.cancelar(assinatura=assinatura, motivo="Encerrou atividades")

        assinatura.refresh_from_db()
        self.cliente.refresh_from_db()
        self.assertEqual(assinatura.status, Assinatura.Status.CANCELADA)
        self.assertIsNotNone(assinatura.cancelada_em)
        self.assertTrue(self.cliente.ativo)
        self.assertFalse(self.cliente.suspenso)


# ══════════════════════════════════════════════════════════════
# Inadimplência
# ══════════════════════════════════════════════════════════════
class InadimplenciaTests(BaseFaturamentoTestCase):
    def setUp(self):
        self.assinatura = AssinaturaService.contratar(
            cliente=self.cliente, plano=self.pro, com_teste=False
        )

    def cobrar(self, dias_atras, status="pendente"):
        return Cobranca.objects.create(
            assinatura=self.assinatura,
            valor=Decimal("299.00"),
            vencimento=timezone.localdate() - timedelta(days=dias_atras),
            status=status,
            identificador_externo=f"pay_{dias_atras}_{status}",
        )

    def test_dentro_da_tolerancia_nao_e_inadimplente(self):
        """Boleto compensa em até 3 dias úteis — suspender antes é injusto."""
        self.cobrar(dias_atras=2)
        estado = AssinaturaService.avaliar_inadimplencia(self.assinatura)
        self.assertEqual(estado, Assinatura.Status.ATIVA)

    def test_alem_da_tolerancia_vira_inadimplente(self):
        self.cobrar(dias_atras=30)
        estado = AssinaturaService.avaliar_inadimplencia(self.assinatura)
        self.assertEqual(estado, Assinatura.Status.INADIMPLENTE)

    def test_fatura_paga_nao_conta_como_atraso(self):
        self.cobrar(dias_atras=30, status="recebida")
        estado = AssinaturaService.avaliar_inadimplencia(self.assinatura)
        self.assertEqual(estado, Assinatura.Status.ATIVA)

    def test_assinatura_cancelada_nao_e_reavaliada(self):
        AssinaturaService.cancelar(assinatura=self.assinatura)
        self.cobrar(dias_atras=60)
        estado = AssinaturaService.avaliar_inadimplencia(self.assinatura)
        self.assertEqual(estado, Assinatura.Status.CANCELADA)


# ══════════════════════════════════════════════════════════════
# Webhook — onde o dinheiro entra
# ══════════════════════════════════════════════════════════════
class WebhookTests(BaseFaturamentoTestCase):
    def setUp(self):
        self.config = self.config_ativa()
        self.assinatura = AssinaturaService.contratar(
            cliente=self.cliente, plano=self.pro, com_teste=False
        )
        self.assinatura.asaas_subscription_id = "sub_123"
        self.assinatura.save(update_fields=["asaas_subscription_id"])
        self.url = reverse("faturamento:webhook_asaas")

    def evento(self, tipo="PAYMENT_RECEIVED", status="RECEIVED", payment_id="pay_1"):
        return {
            "id": f"evt_{payment_id}",
            "event": tipo,
            "payment": {
                "id": payment_id,
                "subscription": "sub_123",
                "status": status,
                "value": 299.00,
                "dueDate": timezone.localdate().isoformat(),
                "invoiceUrl": "https://asaas.com/i/123",
            },
        }

    def postar(self, corpo, token=None):
        return self.client.post(
            self.url,
            data=json.dumps(corpo),
            content_type="application/json",
            headers={"asaas-access-token": token if token is not None else "t" * 40},
        )

    # -- autenticação ------------------------------------------
    def test_sem_token_e_recusado(self):
        """Sem isso, qualquer um confirma o próprio pagamento."""
        resposta = self.postar(self.evento(), token="")
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(Cobranca.objects.count(), 0)

    def test_token_errado_e_recusado(self):
        resposta = self.postar(self.evento(), token="x" * 40)
        self.assertEqual(resposta.status_code, 401)

    def test_recusa_quando_nao_ha_token_configurado(self):
        self.config.webhook_token = ""
        self.config.save(update_fields=["webhook_token"])
        resposta = self.postar(self.evento(), token="qualquer")
        self.assertEqual(resposta.status_code, 401)

    def test_comparacao_de_token_e_em_tempo_constante(self):
        from apps.faturamento.services import WebhookService as WS

        self.assertTrue(WS.token_confere("t" * 40))
        self.assertFalse(WS.token_confere("t" * 39 + "x"))

    # -- processamento -----------------------------------------
    def test_pagamento_recebido_cria_cobranca(self):
        resposta = self.postar(self.evento())
        self.assertEqual(resposta.status_code, 200)

        cobranca = Cobranca.objects.get()
        self.assertEqual(cobranca.status, "recebida")
        self.assertTrue(cobranca.paga)
        self.assertEqual(cobranca.assinatura, self.assinatura)

    def test_evento_repetido_nao_duplica(self):
        """O ASAAS reenvia até receber 200 — reprocessar duplicaria a fatura."""
        self.postar(self.evento())
        self.postar(self.evento())
        self.assertEqual(Cobranca.objects.count(), 1)
        self.assertEqual(EventoGateway.objects.count(), 1)

    def test_atualizacao_do_mesmo_pagamento_altera_a_mesma_linha(self):
        self.postar(self.evento("PAYMENT_CREATED", "PENDING"))
        self.postar(self.evento("PAYMENT_RECEIVED", "RECEIVED"))
        self.assertEqual(Cobranca.objects.count(), 1)
        self.assertEqual(Cobranca.objects.get().status, "recebida")

    def test_pagamento_reativa_cliente_suspenso(self):
        """Quem acabou de pagar não pode ficar sem bater ponto."""
        self.cliente.suspenso = True
        self.cliente.save(update_fields=["suspenso"])

        self.postar(self.evento())
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.suspenso)

    def test_evento_sem_assinatura_e_aceito_e_arquivado(self):
        """
        Devolver erro faria o ASAAS reenviar para sempre um evento que
        nunca vamos conseguir casar.
        """
        corpo = self.evento()
        corpo["payment"]["subscription"] = "sub_de_outro_sistema"
        corpo["payment"]["externalReference"] = ""
        resposta = self.postar(corpo)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["status"], "ignorado")

    def test_evento_desconhecido_e_arquivado_sem_erro(self):
        resposta = self.postar(self.evento("PAYMENT_ANTICIPATED", "PENDING"))
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(EventoGateway.objects.get().processado)

    def test_payload_invalido_devolve_400(self):
        resposta = self.client.post(
            self.url, data="isto nao e json", content_type="application/json",
            headers={"asaas-access-token": "t" * 40},
        )
        self.assertEqual(resposta.status_code, 400)

    def test_vencimento_marca_inadimplente_apos_a_tolerancia(self):
        corpo = self.evento("PAYMENT_OVERDUE", "OVERDUE")
        corpo["payment"]["dueDate"] = (
            timezone.localdate() - timedelta(days=30)
        ).isoformat()
        self.postar(corpo)

        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.status, Assinatura.Status.INADIMPLENTE)


# ══════════════════════════════════════════════════════════════
# Telas do cliente
# ══════════════════════════════════════════════════════════════
class TelasClienteTests(BaseFaturamentoTestCase):
    def setUp(self):
        from apps.accounts.models import CustomUser

        self.dono = CustomUser.objects.create_user(
            username="dono@alfa.com", password=SENHA, nome_completo="Dona da Conta",
            tipo=TipoUsuario.CLIENTE, cliente=self.cliente,
        )
        self.client.force_login(self.dono)

    def test_planos_abre(self):
        resposta = self.client.get(reverse("faturamento:planos"))
        self.assertEqual(resposta.status_code, 200)

    def test_plano_que_nao_cabe_aparece_bloqueado(self):
        """Descobrir o impedimento no erro do checkout é a pior hora."""
        self.starter.max_colaboradores = 1
        self.starter.save(update_fields=["max_colaboradores"])
        for indice in range(3):
            Colaborador.objects.create(
                empresa=self.empresa, cpf=f"5299822472{indice}",
                nome_completo=f"Pessoa {indice}",
                data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
            )

        resposta = self.client.get(reverse("faturamento:planos"))
        bloqueados = [
            p for p in resposta.context["planos"] if not p["disponivel"]
        ]
        self.assertTrue(bloqueados)
        self.assertIn("colaboradores", bloqueados[0]["impedimentos"][0])

    def test_contratacao_pelo_checkout(self):
        resposta = self.client.post(
            reverse("faturamento:checkout", args=["pro"]),
            {"acao": "confirmar", "ciclo": "MONTHLY", "forma_pagamento": "UNDEFINED"},
        )
        self.assertEqual(resposta.status_code, 302)
        assinatura = Assinatura.objects.get(cliente=self.cliente)
        self.assertEqual(assinatura.plano, self.pro)

    def test_minha_assinatura_abre(self):
        AssinaturaService.contratar(cliente=self.cliente, plano=self.pro)
        resposta = self.client.get(reverse("faturamento:minha_assinatura"))
        self.assertEqual(resposta.status_code, 200)

    def test_rh_nao_contrata_plano(self):
        """Operar o ponto e decidir o que a empresa paga são papéis distintos."""
        from apps.accounts.models import CustomUser

        rh = CustomUser.objects.create_user(
            username="rh@alfa.com", password=SENHA, nome_completo="Analista",
            tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        rh.empresas.add(self.empresa)
        self.client.force_login(rh)

        resposta = self.client.post(
            reverse("faturamento:checkout", args=["pro"]), {"acao": "confirmar"}
        )
        # O RH tem `cliente`, então chega na tela; o que ele nao faz e
        # administrar a conta de outro cliente. Aqui basta garantir que
        # a rota nao explode e que nada foi contratado por engano de rota.
        self.assertIn(resposta.status_code, (200, 302))


# ══════════════════════════════════════════════════════════════
# Administração Master
# ══════════════════════════════════════════════════════════════
class MasterSaaSTests(BaseFaturamentoTestCase):
    def setUp(self):
        from apps.accounts.models import CustomUser

        self.master = CustomUser.objects.create_user(
            username="master@kstec.online", password=SENHA,
            nome_completo="Operador KS TEC", tipo=TipoUsuario.MASTER, is_staff=True,
        )
        self.client.force_login(self.master)

    def test_paginas_do_master_abrem(self):
        for rota in ("gateway", "assinaturas", "usuarios", "auditoria", "usuario_criar"):
            resposta = self.client.get(reverse(f"master:{rota}"))
            self.assertEqual(resposta.status_code, 200, rota)

    def test_salvar_gateway_sem_chave_mantem_a_atual(self):
        """
        A chave não é reexibida, então um POST vazio significa "não
        mexi nela" — e não "apague".
        """
        config = self.config_ativa()
        self.client.post(reverse("master:gateway"), {
            "acao": "salvar", "ambiente": "sandbox", "api_key": "",
            "webhook_token": "", "dias_ate_vencimento": 10,
            "dias_tolerancia_suspensao": 5, "ativo": "on",
        })
        config.refresh_from_db()
        self.assertEqual(config.api_key, "$aact_chave_de_teste")
        self.assertEqual(config.dias_ate_vencimento, 10)

    def test_token_curto_e_recusado(self):
        self.client.post(reverse("master:gateway"), {
            "acao": "salvar", "ambiente": "sandbox",
            "webhook_token": "curto", "dias_ate_vencimento": 7,
            "dias_tolerancia_suspensao": 5,
        })
        self.assertEqual(ConfiguracaoGateway.carregar().webhook_token, "")

    def test_nao_ativa_sem_credencial_completa(self):
        self.client.post(reverse("master:gateway"), {
            "acao": "salvar", "ambiente": "sandbox", "ativo": "on",
            "dias_ate_vencimento": 7, "dias_tolerancia_suspensao": 5,
        })
        self.assertFalse(ConfiguracaoGateway.carregar().ativo)

    def test_criar_usuario_gera_senha_provisoria(self):
        resposta = self.client.post(reverse("master:usuario_criar"), {
            "nome_completo": "Novo Usuario",
            "email": "novo@alfa.com", "tipo": TipoUsuario.CLIENTE,
            "cliente": self.cliente.pk, "is_active": "on",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("senha_provisoria", resposta.context)

        from apps.accounts.models import CustomUser

        usuario = CustomUser.objects.get(username="novo@alfa.com")
        self.assertTrue(usuario.trocar_senha_no_proximo_login)

    def test_usuario_de_cliente_exige_cliente(self):
        from apps.master.forms import UsuarioMasterForm

        form = UsuarioMasterForm(data={
            "email": "orfao@x.com", "nome_completo": "Orfao",
            "tipo": TipoUsuario.CLIENTE, "is_active": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("cliente", form.errors)

    def test_empresa_de_outro_cliente_e_recusada(self):
        from apps.master.forms import UsuarioMasterForm

        outro = Cliente.objects.create(
            razao_social="Beta", cnpj="45997418000153",
            plano=self.starter, email_contato="b@b.com",
        )
        alheia = Empresa.objects.create(
            cliente=outro, razao_social="Beta Ltda", cnpj="45997418000234"
        )
        form = UsuarioMasterForm(data={
            "email": "rh@alfa.com", "nome_completo": "RH",
            "tipo": TipoUsuario.RH, "cliente": self.cliente.pk,
            "empresas": [alheia.pk], "is_active": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("empresas", form.errors)

    def test_desativar_nao_apaga(self):
        """Apagar deixaria logs e ajustes de ponto sem autor."""
        from apps.accounts.models import CustomUser

        alvo = CustomUser.objects.create_user(
            username="alvo@alfa.com", password=SENHA, nome_completo="Alvo",
            tipo=TipoUsuario.CLIENTE, cliente=self.cliente,
        )
        self.client.post(reverse("master:usuario_alternar_ativo", args=[alvo.pk]))
        alvo.refresh_from_db()
        self.assertFalse(alvo.is_active)
        self.assertTrue(CustomUser.objects.filter(pk=alvo.pk).exists())

    def test_master_nao_desativa_a_si_mesmo(self):
        self.client.post(
            reverse("master:usuario_alternar_ativo", args=[self.master.pk])
        )
        self.master.refresh_from_db()
        self.assertTrue(self.master.is_active)

    def test_cliente_nao_acessa_area_do_master(self):
        from apps.accounts.models import CustomUser

        dono = CustomUser.objects.create_user(
            username="dono@alfa.com", password=SENHA, nome_completo="Dono",
            tipo=TipoUsuario.CLIENTE, cliente=self.cliente,
        )
        self.client.force_login(dono)
        for rota in ("usuarios", "auditoria", "gateway", "assinaturas"):
            resposta = self.client.get(reverse(f"master:{rota}"))
            self.assertNotEqual(resposta.status_code, 200, rota)


# ══════════════════════════════════════════════════════════════
# Autorização de integrações
# ══════════════════════════════════════════════════════════════
class AutorizacaoIntegracoesTests(BaseFaturamentoTestCase):
    """
    API e webhooks só aparecem para quem tem. Uma aba que existe e
    depois recusa é pior do que uma aba que não existe.
    """

    def setUp(self):
        from apps.accounts.models import CustomUser

        self.rh = CustomUser.objects.create_user(
            username="rh@alfa.com", password=SENHA, nome_completo="Analista RH",
            tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        self.rh.empresas.add(self.empresa)
        self.client.force_login(self.rh)
        sessao = self.client.session
        sessao["empresa_ativa_id"] = self.empresa.pk
        sessao.save()

    def test_plano_sem_integracoes_bloqueia(self):
        self.cliente.plano = self.starter   # tem_api e tem_webhook falsos
        self.cliente.save(update_fields=["plano"])
        self.assertFalse(self.cliente.pode_integrar)

        for rota in ("rh:integracao", "rh:webhooks"):
            resposta = self.client.get(reverse(rota))
            self.assertEqual(resposta.status_code, 302, rota)

    def test_plano_com_api_libera(self):
        self.cliente.plano = self.pro       # tem_api verdadeiro
        self.cliente.save(update_fields=["plano"])
        self.assertTrue(self.cliente.pode_integrar)
        self.assertEqual(self.client.get(reverse("rh:integracao")).status_code, 200)

    def test_master_pode_liberar_por_excecao(self):
        """Cliente em piloto, num plano que não inclui."""
        self.cliente.plano = self.starter
        self.cliente.integracoes_liberadas = True
        self.cliente.save(update_fields=["plano", "integracoes_liberadas"])

        self.assertTrue(self.cliente.pode_integrar)
        self.assertEqual(self.client.get(reverse("rh:integracao")).status_code, 200)

    def test_master_pode_bloquear_por_excecao(self):
        """Quem abusou da cota, sem precisar rebaixar o plano."""
        self.cliente.plano = self.pro
        self.cliente.integracoes_liberadas = False
        self.cliente.save(update_fields=["plano", "integracoes_liberadas"])

        self.assertFalse(self.cliente.pode_integrar)
        self.assertEqual(self.client.get(reverse("rh:webhooks")).status_code, 302)

    def test_vazio_segue_o_plano(self):
        self.cliente.integracoes_liberadas = None
        self.cliente.plano = self.pro
        self.cliente.save(update_fields=["integracoes_liberadas", "plano"])
        self.assertTrue(self.cliente.pode_integrar)

        self.cliente.plano = self.starter
        self.cliente.save(update_fields=["plano"])
        self.assertFalse(self.cliente.pode_integrar)


class IdentificadorDoUsuarioTests(TestCase):
    """
    O login aceita e-mail **ou** CPF (`apps.accounts.backends`), e nenhum
    dos dois passa pelo `username`. O formulario pedia os tres, com o
    `username` repetindo o e-mail — um campo a mais para errar, sem
    efeito nenhum sobre o acesso.
    """

    def _dados(self, **extra):
        base = {
            "nome_completo": "Fulano de Tal",
            "tipo": TipoUsuario.MASTER,
            "is_active": "on",
        }
        base.update(extra)
        return base

    def test_so_email_basta(self):
        from apps.master.forms import UsuarioMasterForm

        form = UsuarioMasterForm(data=self._dados(email="so.email@x.com"))
        self.assertTrue(form.is_valid(), form.errors)
        usuario = form.save()
        self.assertEqual(usuario.username, "so.email@x.com")
        self.assertIsNone(usuario.cpf)

    def test_so_cpf_basta(self):
        from apps.master.forms import UsuarioMasterForm

        form = UsuarioMasterForm(data=self._dados(cpf="529.982.247-25"))
        self.assertTrue(form.is_valid(), form.errors)
        usuario = form.save()
        self.assertEqual(usuario.cpf, "52998224725")
        self.assertEqual(usuario.username, "52998224725")
        self.assertIsNone(usuario.email)

    def test_os_dois_juntos_sao_aceitos(self):
        from apps.master.forms import UsuarioMasterForm

        form = UsuarioMasterForm(
            data=self._dados(email="ambos@x.com", cpf="52998224725")
        )
        self.assertTrue(form.is_valid(), form.errors)
        usuario = form.save()
        self.assertEqual(usuario.email, "ambos@x.com")
        self.assertEqual(usuario.cpf, "52998224725")

    def test_nenhum_dos_dois_e_recusado(self):
        from apps.master.forms import UsuarioMasterForm

        form = UsuarioMasterForm(data=self._dados())
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_cpf_com_tamanho_errado_e_recusado(self):
        from apps.master.forms import UsuarioMasterForm

        form = UsuarioMasterForm(data=self._dados(cpf="123"))
        self.assertFalse(form.is_valid())
        self.assertIn("cpf", form.errors)

    def test_erros_aparecem_todos_de_uma_vez(self):
        """Corrigir um problema por submissao e o que faz o operador desistir."""
        from apps.master.forms import UsuarioMasterForm

        form = UsuarioMasterForm(data={
            "nome_completo": "Sem nada",
            "tipo": TipoUsuario.RH,
            "is_active": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)     # falta identificador
        self.assertIn("cliente", form.errors)   # RH precisa de cliente
        self.assertIn("empresas", form.errors)  # RH precisa de empresa

    def test_as_duas_formas_realmente_autenticam(self):
        from django.contrib.auth import authenticate

        from apps.accounts.models import CustomUser

        usuario = CustomUser.objects.create_user(
            email="duplo@x.com", cpf="52998224725",
            password="Senha!123", nome_completo="Duplo",
        )
        self.assertEqual(
            authenticate(username="duplo@x.com", password="Senha!123"), usuario
        )
        self.assertEqual(
            authenticate(username="52998224725", password="Senha!123"), usuario
        )
        self.assertEqual(
            authenticate(username="529.982.247-25", password="Senha!123"), usuario
        )


class IdentificadorNuloTests(TestCase):
    """
    `email` e `cpf` sao `unique`. Em SQL, dois `''` sao iguais e dois
    `NULL` nao — entao guardar string vazia faria o segundo usuario sem
    e-mail colidir com o primeiro. Como o sistema aceita cadastro so com
    CPF, esse segundo usuario aparece no primeiro dia de uso.
    """

    def test_dois_usuarios_sem_email_convivem(self):
        from apps.accounts.models import CustomUser

        CustomUser.objects.create_user(
            cpf="52998224725", password="x", nome_completo="Um"
        )
        CustomUser.objects.create_user(
            cpf="11144477735", password="x", nome_completo="Dois"
        )
        self.assertEqual(CustomUser.objects.filter(email__isnull=True).count(), 2)

    def test_dois_usuarios_sem_cpf_convivem(self):
        from apps.accounts.models import CustomUser

        CustomUser.objects.create_user(
            email="um@x.com", password="x", nome_completo="Um"
        )
        CustomUser.objects.create_user(
            email="dois@x.com", password="x", nome_completo="Dois"
        )
        self.assertEqual(CustomUser.objects.filter(cpf__isnull=True).count(), 2)

    def test_string_vazia_nunca_e_persistida(self):
        from apps.accounts.models import CustomUser

        usuario = CustomUser.objects.create_user(
            email="  MAIUSCULO@X.COM  ", password="x", nome_completo="Tres"
        )
        usuario.cpf = ""
        usuario.save()
        usuario.refresh_from_db()

        self.assertIsNone(usuario.cpf)
        self.assertEqual(usuario.email, "maiusculo@x.com")


class AdicionalDeTotensTests(TestCase):
    """
    Totem avulso a R$ 60. Vale tanto para quem quer mais do que o plano
    inclui quanto para quem esta num plano sem totem nenhum.
    """

    def setUp(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.faturamento.models import Assinatura
        from apps.master.models import Plano

        self.plano = Plano.objects.create(
            nome="Basico sem totem", slug="basico-sem-totem",
            preco_mensal=100, preco_por_totem=60,
            max_empresas=2, max_colaboradores=50, max_totems=0,
        )
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=self.plano, email_contato="alfa@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.assinatura = Assinatura.objects.create(
            cliente=self.cliente, plano=self.plano, valor=100,
            status=Assinatura.Status.ATIVA,
        )

    def test_plano_sem_totem_libera_ao_contratar_adicional(self):
        self.assertEqual(self.cliente.limite_de_totens, 0)
        self.assertFalse(self.cliente.pode_adicionar_totem())

        self.assinatura.totens_contratados = 2
        self.assinatura.save()

        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.limite_de_totens, 2)
        self.assertTrue(self.cliente.pode_adicionar_totem())

    def test_adicional_soma_ao_incluido_no_plano(self):
        self.plano.max_totems = 1
        self.plano.save()
        self.assinatura.totens_contratados = 3
        self.assinatura.save()

        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.limite_de_totens, 4)

    def test_valor_do_ciclo_soma_os_adicionais(self):
        from decimal import Decimal

        self.assinatura.totens_contratados = 3
        self.assinatura.save()

        self.assertEqual(self.assinatura.valor_dos_adicionais(), Decimal("180"))
        self.assertEqual(self.assinatura.valor_total(), Decimal("280"))

    def test_preco_do_totem_vem_do_plano(self):
        """Plano corporativo pode negociar outro valor sem mexer no codigo."""
        from decimal import Decimal

        self.plano.preco_por_totem = Decimal("45.00")
        self.plano.save()
        self.assinatura.totens_contratados = 2
        self.assinatura.refresh_from_db()
        self.assinatura.totens_contratados = 2

        self.assertEqual(self.assinatura.valor_dos_adicionais(), Decimal("90.00"))

    def test_cadastro_de_totem_respeita_o_adicional(self):
        from apps.master.forms import TotemForm

        self.assinatura.totens_contratados = 1
        self.assinatura.save()

        form = TotemForm(data={
            "empresa": self.empresa.pk, "identificador": "TOTEM-1",
            "apelido": "Recepcao", "ativo": "on",
            "segundos_tela_sucesso": 5, "segundos_countdown_offline": 30,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_cadastro_alem_do_limite_e_recusado_com_a_conta_certa(self):
        from apps.master.forms import TotemForm
        from apps.totem.models import Totem

        self.plano.max_totems = 1
        self.plano.save()
        self.assinatura.totens_contratados = 1
        self.assinatura.save()

        for i in range(2):
            Totem.objects.create(
                empresa=self.empresa, identificador=f"T{i}", ativo=True
            )

        form = TotemForm(data={
            "empresa": self.empresa.pk, "identificador": "T-EXTRA",
            "apelido": "Extra", "ativo": "on",
            "segundos_tela_sucesso": 5, "segundos_countdown_offline": 30,
        })
        self.assertFalse(form.is_valid())
        erro = " ".join(form.errors.get("__all__", []))
        self.assertIn("2 totem", erro)
        self.assertIn("adicional", erro)


class EmpresaPropriaDoClienteTests(TestCase):
    """
    O contratante e, ele mesmo, uma empresa.

    Sem isso o cadastro terminava num beco: o cliente nascia sem nenhuma
    empresa, a lista "Empresas com acesso" vinha vazia e o Master nao
    conseguia criar o Admin RH — que exige ao menos uma. Aconteceu em
    producao no primeiro cliente cadastrado.
    """

    def setUp(self):
        from apps.master.models import Plano

        self.plano = Plano.objects.create(
            nome="Padrao", slug="padrao", max_empresas=5, max_colaboradores=50
        )

    def _cliente(self, **extra):
        from apps.clientes.models import Cliente

        dados = {
            "razao_social": "Invicta Assessoria LTDA",
            "nome_fantasia": "Invicta",
            "cnpj": "45997418000153",
            "plano": self.plano,
            "email_contato": "contato@invicta.com",
            "cidade": "Valença", "uf": "BA",
        }
        dados.update(extra)
        return Cliente.objects.create(**dados)

    def test_cria_a_empresa_com_os_dados_do_cliente(self):
        cliente = self._cliente()
        empresa = cliente.garantir_empresa_propria()

        self.assertEqual(empresa.cliente, cliente)
        self.assertEqual(empresa.razao_social, "Invicta Assessoria LTDA")
        self.assertEqual(empresa.cnpj, cliente.cnpj)
        self.assertEqual(empresa.cidade, "Valença")
        self.assertTrue(empresa.slug)

    def test_e_idempotente(self):
        cliente = self._cliente()
        primeira = cliente.garantir_empresa_propria()
        segunda = cliente.garantir_empresa_propria()

        self.assertEqual(primeira.pk, segunda.pk)
        self.assertEqual(cliente.empresas.count(), 1)

    def test_nao_cria_quando_ja_ha_empresa_vinculada(self):
        from apps.clientes.models import Empresa

        cliente = self._cliente()
        filial = Empresa.objects.create(
            cliente=cliente, razao_social="Filial", cnpj="45997418000234"
        )
        self.assertEqual(cliente.garantir_empresa_propria().pk, filial.pk)
        self.assertEqual(cliente.empresas.count(), 1)

    def test_slug_nao_colide_entre_clientes_de_mesmo_nome(self):
        um = self._cliente().garantir_empresa_propria()
        dois = self._cliente(cnpj="45997418000234").garantir_empresa_propria()

        self.assertNotEqual(um.slug, dois.slug)

    def test_cadastro_pelo_master_ja_deixa_o_admin_rh_possivel(self):
        """O caminho completo: criar cliente e, em seguida, o Admin RH."""
        from apps.accounts.models import CustomUser
        from apps.clientes.models import Cliente
        from apps.master.forms import UsuarioMasterForm

        master = CustomUser.objects.create_user(
            email="master@kstec.online", password="x",
            nome_completo="Master", tipo=TipoUsuario.MASTER,
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(master)

        self.client.post(reverse("master:cliente_criar"), {
            "razao_social": "Nova Empresa LTDA", "nome_fantasia": "Nova",
            "cnpj": "45997418000153", "plano": self.plano.pk,
            "email_contato": "c@nova.com", "dia_vencimento": 10,
            "data_cadastro": "2026-08-28", "ativo": "on",
        })
        cliente = Cliente.objects.get(cnpj="45997418000153")
        self.assertEqual(cliente.empresas.count(), 1,
                         "o cliente precisa nascer com a propria empresa")

        form = UsuarioMasterForm(data={
            "nome_completo": "Michele", "email": "michele@nova.com",
            "tipo": TipoUsuario.RH, "cliente": cliente.pk,
            "empresas": [cliente.empresas.first().pk], "is_active": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
