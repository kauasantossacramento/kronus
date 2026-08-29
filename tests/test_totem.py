"""
Kronus — testes do totem (Fase 3).

Cobrem os quatro endpoints da Seção 7.3, a autenticação por token, o
escopo de reconhecimento (regra 12 da Seção 14), o fallback por CPF
(regra 6) e o monitoramento de equipamento offline (Seção 8.7).
"""
import base64
import io
import json
from datetime import date, timedelta

import numpy as np
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import MetodoRegistro
from apps.facial.providers import ProvedorDeterministico
from apps.facial.services import FaceRecognitionService
from apps.master.models import Plano
from apps.ponto.models import RegistroPonto
from apps.rh.models import Colaborador
from apps.totem.models import EventoTotem, GrupoTotem, Totem


def imagem_bytes(ruido=1, tamanho=(320, 240)) -> bytes:
    imagem = Image.new("RGB", tamanho, (200, 170, 150))
    pixels = imagem.load()
    gerador = np.random.default_rng(ruido)
    for _ in range(400):
        x = int(gerador.integers(0, tamanho[0]))
        y = int(gerador.integers(0, tamanho[1]))
        pixels[x, y] = tuple(int(v) for v in gerador.integers(0, 255, 3))
    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def como_base64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


class BaseTotemTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Pro", slug="pro", max_colaboradores=100, max_totems=5, tem_totem=True
        )
        cls.cliente = Cliente.objects.create(
            razao_social="Cliente", cnpj="11222333000181", plano=cls.plano, email_contato="c@c.com"
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Loja Centro", cnpj="11222333000262"
        )
        cls.filial = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Loja Norte", cnpj="11222333000343"
        )
        cls.totem = Totem.objects.create(
            identificador="TOTEM-01", empresa=cls.empresa, apelido="Recepção"
        )

        cls.joao = Colaborador.objects.create(
            empresa=cls.empresa,
            cpf="52998224725",
            nome_completo="João da Silva Souza",
            data_nascimento=date(1990, 3, 12),
            data_admissao=date(2024, 1, 1),
            consentimento_biometrico=True,
        )
        cls.carlos = Colaborador.objects.create(
            empresa=cls.filial,
            cpf="71428793860",
            nome_completo="Carlos Ramos",
            data_nascimento=date(1978, 11, 23),
            data_admissao=date(2024, 1, 1),
            consentimento_biometrico=True,
        )

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.servico = FaceRecognitionService(provedor=ProvedorDeterministico())

    # -- helpers -----------------------------------------------
    def cadastrar_face(self, colaborador, ruido):
        self.servico.cadastrar_amostra(
            colaborador, como_base64(imagem_bytes(ruido)), exigir_qualidade=False
        )
        self.servico.consolidar_cadastro(colaborador)

    def post(self, nome_rota, dados, token=None):
        return self.client.post(
            reverse(nome_rota),
            data=json.dumps(dados),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token or self.totem.token_acesso}",
        )

    def reconhecer(self, ruido, token=None):
        """
        Envia o mesmo quadro duas vezes.

        O servidor so grava o ponto quando dois quadros seguidos apontam
        a mesma pessoa: um acerto por acaso vem de um quadro especifico e
        nao se repete, um reconhecimento verdadeiro se repete. O primeiro
        envio devolve "confirmando"; o segundo e o que registra.
        """
        dados = {"image": como_base64(imagem_bytes(ruido))}
        self.post("api:totem:totem_recognize", dados, token=token)
        return self.post("api:totem:totem_recognize", dados, token=token)


# ══════════════════════════════════════════════════════════════
# Autenticação
# ══════════════════════════════════════════════════════════════
class AutenticacaoTotemTests(BaseTotemTestCase):
    def test_sem_token_e_recusado(self):
        resposta = self.client.post(
            reverse("api:totem:totem_heartbeat"),
            data="{}",
            content_type="application/json",
        )
        self.assertIn(resposta.status_code, (401, 403))

    def test_token_desconhecido_e_recusado(self):
        resposta = self.post("api:totem:totem_heartbeat", {}, token="token-invalido")
        self.assertEqual(resposta.status_code, 401)

    def test_token_malformado_e_recusado(self):
        resposta = self.client.post(
            reverse("api:totem:totem_heartbeat"),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION="Token a b c",
        )
        self.assertEqual(resposta.status_code, 401)

    def test_totem_inativo_e_recusado(self):
        self.totem.ativo = False
        self.totem.save(update_fields=["ativo"])
        self.assertEqual(self.post("api:totem:totem_heartbeat", {}).status_code, 401)

    def test_cliente_suspenso_bloqueia_o_equipamento(self):
        self.cliente.suspender("Inadimplência")
        resposta = self.post("api:totem:totem_heartbeat", {})
        self.assertEqual(resposta.status_code, 401)


# ══════════════════════════════════════════════════════════════
# Heartbeat
# ══════════════════════════════════════════════════════════════
class HeartbeatTests(BaseTotemTestCase):
    def test_heartbeat_atualiza_o_equipamento(self):
        resposta = self.post(
            "api:totem:totem_heartbeat", {"versao": "1.2.3", "bateria": 87}
        )
        self.assertEqual(resposta.status_code, 200)

        self.totem.refresh_from_db()
        self.assertIsNotNone(self.totem.ultimo_heartbeat)
        self.assertEqual(self.totem.versao_firmware, "1.2.3")
        self.assertEqual(self.totem.bateria_percentual, 87)
        self.assertTrue(self.totem.online)

    def test_resposta_traz_a_hora_do_servidor(self):
        """
        O relógio do tablet pode estar errado; o totem sincroniza pela
        resposta para não exibir hora diferente da que foi gravada.
        """
        dados = self.post("api:totem:totem_heartbeat", {}).json()
        self.assertIn("servidor", dados)
        self.assertIn("iso", dados["servidor"])
        self.assertIn("hora", dados["servidor"])

    def test_volta_de_offline_gera_evento(self):
        self.totem.ultimo_heartbeat = timezone.now() - timedelta(hours=2)
        self.totem.save(update_fields=["ultimo_heartbeat"])

        self.post("api:totem:totem_heartbeat", {})
        self.assertTrue(
            EventoTotem.objects.filter(
                totem=self.totem, tipo=EventoTotem.Tipo.ONLINE
            ).exists()
        )


# ══════════════════════════════════════════════════════════════
# Configuração
# ══════════════════════════════════════════════════════════════
class ConfigTests(BaseTotemTestCase):
    def test_config_traz_identidade_e_parametros(self):
        resposta = self.client.get(
            reverse("api:totem:totem_config"),
            HTTP_AUTHORIZATION=f"Token {self.totem.token_acesso}",
        )
        self.assertEqual(resposta.status_code, 200)

        dados = resposta.json()
        self.assertEqual(dados["identificador"], "TOTEM-01")
        self.assertEqual(dados["empresa"]["nome"], "Loja Centro")
        self.assertIn("mensagem_boas_vindas", dados["empresa"])
        self.assertTrue(dados["interface"]["permite_fallback_cpf"])
        self.assertEqual(dados["interface"]["segundos_tela_sucesso"], 5)


# ══════════════════════════════════════════════════════════════
# Reconhecimento facial
# ══════════════════════════════════════════════════════════════
class RecognizeTests(BaseTotemTestCase):
    def setUp(self):
        super().setUp()
        self.cadastrar_face(self.joao, ruido=10)

    def test_reconhece_e_registra_o_ponto(self):
        with self.captureOnCommitCallbacks(execute=True):
            resposta = self.reconhecer(10)
        self.assertEqual(resposta.status_code, 200)

        dados = resposta.json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["colaborador"]["nome"], "João da Silva Souza")
        self.assertEqual(dados["registro"]["nsr"], 1)
        self.assertIn("codigo_verificacao", dados["registro"])

        registro = RegistroPonto.objects.get(colaborador=self.joao)
        self.assertEqual(registro.metodo, MetodoRegistro.FACIAL)
        self.assertEqual(registro.totem, self.totem)
        self.assertIsNotNone(registro.confianca_face)

    def test_cpf_sai_mascarado_na_resposta(self):
        """A tela do totem é visível para quem estiver na fila."""
        dados = self.reconhecer(10).json()
        self.assertEqual(dados["colaborador"]["cpf_mascarado"], "***.***.247-25")
        # Nem os tres primeiros nem os do meio podem aparecer.
        self.assertNotIn("982", dados["colaborador"]["cpf_mascarado"])
        self.assertNotIn("52998224725", json.dumps(dados))

    def test_rosto_desconhecido_oferece_fallback(self):
        dados = self.post(
            "api:totem:totem_recognize", {"image": como_base64(imagem_bytes(999))}
        ).json()
        self.assertFalse(dados["ok"])
        self.assertEqual(dados["codigo"], "nao_identificado")
        self.assertTrue(dados["permite_fallback"])
        self.assertFalse(RegistroPonto.objects.exists())

    def test_colaborador_de_outra_empresa_nao_e_reconhecido(self):
        """Regra 12 da Seção 14."""
        self.cadastrar_face(self.carlos, ruido=30)
        dados = self.post(
            "api:totem:totem_recognize", {"image": como_base64(imagem_bytes(30))}
        ).json()
        self.assertFalse(dados["ok"])
        self.assertFalse(RegistroPonto.objects.filter(colaborador=self.carlos).exists())

    def test_grupo_de_totens_amplia_o_escopo(self):
        """Um totem de grupo reconhece colaboradores das empresas do grupo."""
        grupo = GrupoTotem.objects.create(cliente=self.cliente, nome="Rede Salvador")
        grupo.empresas.set([self.empresa, self.filial])
        self.totem.grupo = grupo
        self.totem.save(update_fields=["grupo"])

        self.cadastrar_face(self.carlos, ruido=30)
        dados = self.reconhecer(30).json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["colaborador"]["nome"], "Carlos Ramos")

    def test_batida_duplicada_e_recusada(self):
        self.reconhecer(10)
        dados = self.reconhecer(10).json()
        self.assertFalse(dados["ok"])
        self.assertEqual(dados["codigo"], "intervalo_minimo")
        self.assertEqual(RegistroPonto.objects.count(), 1)

    def test_apenas_identificar_sem_registrar(self):
        dados = self.post(
            "api:totem:totem_recognize",
            {"image": como_base64(imagem_bytes(10)), "registrar_ponto": False},
        ).json()
        self.assertTrue(dados["identificado"])
        self.assertFalse(RegistroPonto.objects.exists())

    def test_imagem_ausente_e_erro_de_requisicao(self):
        self.assertEqual(
            self.post("api:totem:totem_recognize", {}).status_code, 400
        )

    def test_sucesso_gera_evento_no_diario_do_equipamento(self):
        self.reconhecer(10)
        self.assertTrue(
            EventoTotem.objects.filter(
                totem=self.totem, tipo=EventoTotem.Tipo.RECONHECIMENTO_OK
            ).exists()
        )

    def test_falha_gera_evento(self):
        self.post("api:totem:totem_recognize", {"image": como_base64(imagem_bytes(999))})
        self.assertTrue(
            EventoTotem.objects.filter(
                totem=self.totem, tipo=EventoTotem.Tipo.RECONHECIMENTO_FALHA
            ).exists()
        )

    def test_mensagem_motivacional_acompanha_o_sucesso(self):
        from apps.core.constants import MENSAGENS_TOTEM

        dados = self.reconhecer(10).json()
        self.assertIn(dados["mensagem"], MENSAGENS_TOTEM)


# ══════════════════════════════════════════════════════════════
# Fallback por CPF
# ══════════════════════════════════════════════════════════════
class PunchCPFTests(BaseTotemTestCase):
    def test_registra_com_cpf_e_nascimento_corretos(self):
        with self.captureOnCommitCallbacks(execute=True):
            resposta = self.post(
                "api:totem:totem_punch_cpf",
                {"cpf": "529.982.247-25", "data_nascimento": "12/03/1990"},
            )
        dados = resposta.json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["colaborador"]["nome"], "João da Silva Souza")

        registro = RegistroPonto.objects.get(colaborador=self.joao)
        self.assertEqual(registro.metodo, MetodoRegistro.CPF)
        self.assertEqual(registro.totem, self.totem)

    def test_aceita_data_no_formato_ddmmaaaa(self):
        """O WebView do Android envia a data sem separadores."""
        dados = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "52998224725", "data_nascimento": "12031990"},
        ).json()
        self.assertTrue(dados["ok"])

    def test_funciona_sem_cadastro_facial(self):
        """Regra 6: o fallback está sempre disponível."""
        self.assertFalse(self.joao.face_registrada)
        dados = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "52998224725", "data_nascimento": "1990-03-12"},
        ).json()
        self.assertTrue(dados["ok"])

    def test_data_errada_nao_registra(self):
        dados = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "52998224725", "data_nascimento": "01/01/1991"},
        ).json()
        self.assertFalse(dados["ok"])
        self.assertEqual(dados["codigo"], "dados_invalidos")
        self.assertFalse(RegistroPonto.objects.exists())

    def test_mensagem_nao_revela_se_o_cpf_existe(self):
        """
        Distinguir "CPF inexistente" de "data errada" permitiria
        descobrir quem trabalha na empresa.
        """
        com_cpf_valido = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "52998224725", "data_nascimento": "01/01/1991"},
        ).json()
        com_cpf_inexistente = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "15350946056", "data_nascimento": "01/01/1991"},
        ).json()
        self.assertEqual(com_cpf_valido["mensagem"], com_cpf_inexistente["mensagem"])

    def test_cpf_invalido_e_recusado(self):
        dados = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "111.111.111-11", "data_nascimento": "12/03/1990"},
        ).json()
        self.assertFalse(dados["ok"])

    def test_colaborador_de_outra_empresa_nao_registra(self):
        dados = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "71428793860", "data_nascimento": "23/11/1978"},
        ).json()
        self.assertFalse(dados["ok"])

    def test_fallback_desabilitado_no_equipamento(self):
        self.totem.permite_fallback_cpf = False
        self.totem.save(update_fields=["permite_fallback_cpf"])

        resposta = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "52998224725", "data_nascimento": "12/03/1990"},
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()["codigo"], "fallback_desabilitado")

    def test_colaborador_desligado_nao_registra(self):
        self.joao.data_demissao = date(2024, 6, 30)
        self.joao.ativo = False
        self.joao.save(update_fields=["data_demissao", "ativo"])

        dados = self.post(
            "api:totem:totem_punch_cpf",
            {"cpf": "52998224725", "data_nascimento": "12/03/1990"},
        ).json()
        self.assertFalse(dados["ok"])


# ══════════════════════════════════════════════════════════════
# Interface de quiosque
# ══════════════════════════════════════════════════════════════
class KioskTests(BaseTotemTestCase):
    def test_pagina_do_totem_responde(self):
        resposta = self.client.get(
            reverse("totem:kiosk", args=[self.totem.token_acesso])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "tela-idle")
        self.assertContains(resposta, "tela-fallback")
        self.assertContains(resposta, "tela-offline")

    def test_token_invalido_da_404(self):
        resposta = self.client.get(reverse("totem:kiosk", args=["token-que-nao-existe"]))
        self.assertEqual(resposta.status_code, 404)

    def test_totem_inativo_da_404(self):
        self.totem.ativo = False
        self.totem.save(update_fields=["ativo"])
        resposta = self.client.get(
            reverse("totem:kiosk", args=[self.totem.token_acesso])
        )
        self.assertEqual(resposta.status_code, 404)

    def test_cliente_suspenso_mostra_aviso(self):
        self.cliente.suspender("Inadimplência")
        resposta = self.client.get(
            reverse("totem:kiosk", args=[self.totem.token_acesso])
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertContains(resposta, "indisponível", status_code=403)

    def test_pagina_nao_e_cacheada(self):
        resposta = self.client.get(
            reverse("totem:kiosk", args=[self.totem.token_acesso])
        )
        self.assertIn("no-cache", resposta["Cache-Control"])

    def test_service_worker_tem_escopo_correto(self):
        resposta = self.client.get(reverse("totem:service_worker"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/javascript")
        self.assertEqual(resposta["Service-Worker-Allowed"], "/totem/")

    def test_service_worker_nao_cacheia_a_api(self):
        """Uma batida servida do cache seria registro falso."""
        corpo = self.client.get(reverse("totem:service_worker")).content.decode()
        self.assertIn("/api/", corpo)
        self.assertIn("return;", corpo)

    def test_pagina_offline_responde(self):
        self.assertEqual(self.client.get(reverse("totem:offline")).status_code, 200)

    def test_diagnostico_responde(self):
        resposta = self.client.get(
            reverse("totem:diagnostico", args=[self.totem.token_acesso])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "TOTEM-01")


# ══════════════════════════════════════════════════════════════
# Modelo e monitoramento
# ══════════════════════════════════════════════════════════════
class ModeloTotemTests(BaseTotemTestCase):
    def test_token_e_gerado_automaticamente(self):
        self.assertTrue(self.totem.token_acesso)
        self.assertGreater(len(self.totem.token_acesso), 30)

    def test_regenerar_token_invalida_o_anterior(self):
        anterior = self.totem.token_acesso
        novo = self.totem.regenerar_token()
        self.assertNotEqual(anterior, novo)
        self.assertEqual(self.post("api:totem:totem_heartbeat", {}, token=anterior).status_code, 401)

    def test_online_depende_do_heartbeat_recente(self):
        self.assertFalse(self.totem.online)

        self.totem.registrar_heartbeat()
        self.assertTrue(self.totem.online)

        self.totem.ultimo_heartbeat = timezone.now() - timedelta(minutes=11)
        self.totem.save(update_fields=["ultimo_heartbeat"])
        self.assertFalse(self.totem.online)

    def test_empresas_atendidas_sem_grupo(self):
        self.assertEqual(list(self.totem.empresas_atendidas()), [self.empresa])

    def test_empresas_atendidas_com_grupo(self):
        grupo = GrupoTotem.objects.create(cliente=self.cliente, nome="Rede")
        grupo.empresas.set([self.empresa, self.filial])
        self.totem.grupo = grupo
        self.totem.save(update_fields=["grupo"])
        self.assertEqual(self.totem.empresas_atendidas().count(), 2)


class MonitoramentoOfflineTests(BaseTotemTestCase):
    def test_totem_sem_heartbeat_e_sinalizado(self):
        from apps.totem.tasks import monitorar_totens_offline

        self.totem.ultimo_heartbeat = timezone.now() - timedelta(minutes=30)
        self.totem.save(update_fields=["ultimo_heartbeat"])

        resultado = monitorar_totens_offline()
        self.assertIn("TOTEM-01", resultado["novos_offline"])
        self.assertTrue(
            EventoTotem.objects.filter(
                totem=self.totem, tipo=EventoTotem.Tipo.OFFLINE
            ).exists()
        )

    def test_alerta_nao_se_repete_a_cada_ciclo(self):
        """Repetir o alerta treinaria o RH a ignorá-lo."""
        from apps.totem.tasks import monitorar_totens_offline

        self.totem.ultimo_heartbeat = timezone.now() - timedelta(minutes=30)
        self.totem.save(update_fields=["ultimo_heartbeat"])

        monitorar_totens_offline()
        segundo = monitorar_totens_offline()

        self.assertEqual(segundo["novos_offline"], [])
        self.assertEqual(
            EventoTotem.objects.filter(
                totem=self.totem, tipo=EventoTotem.Tipo.OFFLINE
            ).count(),
            1,
        )

    def test_totem_online_nao_gera_alerta(self):
        from apps.totem.tasks import monitorar_totens_offline

        self.totem.registrar_heartbeat()
        self.assertEqual(monitorar_totens_offline()["novos_offline"], [])

    def test_volta_ao_ar_e_registrada(self):
        from apps.totem.tasks import monitorar_totens_offline

        self.totem.ultimo_heartbeat = timezone.now() - timedelta(minutes=30)
        self.totem.save(update_fields=["ultimo_heartbeat"])
        monitorar_totens_offline()

        self.totem.registrar_heartbeat()
        monitorar_totens_offline()

        self.assertTrue(
            EventoTotem.objects.filter(
                totem=self.totem, tipo=EventoTotem.Tipo.ONLINE
            ).exists()
        )

    def test_notificacao_e_enviada_aos_gestores(self):
        from django.contrib.auth import get_user_model

        from apps.core.constants import TipoUsuario
        from apps.notificacoes.models import Notificacao
        from apps.totem.tasks import monitorar_totens_offline

        User = get_user_model()
        gestor = User.objects.create_user(
            email="gestor@teste.com",
            password="senha-forte-123",
            nome_completo="Gestor",
            tipo=TipoUsuario.RH,
            cliente=self.cliente,
        )
        gestor.empresas.set([self.empresa])

        self.totem.ultimo_heartbeat = timezone.now() - timedelta(minutes=30)
        self.totem.save(update_fields=["ultimo_heartbeat"])
        monitorar_totens_offline()

        self.assertTrue(
            Notificacao.objects.filter(
                destinatario=gestor, evento=Notificacao.Evento.TOTEM_OFFLINE
            ).exists()
        )


class DuplaConfirmacaoTests(BaseTotemTestCase):
    """
    Dois quadros seguidos precisam apontar a mesma pessoa.

    Existe porque o totem confundia pessoas parecidas — mulheres entre
    si, no caso relatado. Um acerto por acaso vem de um quadro
    especifico: angulo, sombra, movimento. No quadro seguinte ele nao se
    repete; um reconhecimento verdadeiro, sim.
    """

    def setUp(self):
        super().setUp()
        # Duas pessoas na MESMA empresa: e entre elas que a troca pode
        # acontecer, porque as duas sao candidatas no mesmo totem.
        self.maria = Colaborador.objects.create(
            empresa=self.empresa,
            cpf="11144477735",
            nome_completo="Maria Oliveira",
            data_nascimento=date(1992, 7, 4),
            data_admissao=date(2024, 1, 1),
            consentimento_biometrico=True,
        )
        self.cadastrar_face(self.joao, ruido=10)
        self.cadastrar_face(self.maria, ruido=20)

    def _um_quadro(self, ruido):
        return self.post(
            "api:totem:totem_recognize",
            {"image": como_base64(imagem_bytes(ruido))},
        ).json()

    def test_o_primeiro_quadro_nao_grava_ponto(self):
        dados = self._um_quadro(10)
        self.assertEqual(dados["codigo"], "confirmando")
        self.assertFalse(dados["identificado"])
        self.assertFalse(
            RegistroPonto.objects.exists(),
            "um quadro sozinho gravou ponto — a confirmacao nao esta valendo",
        )

    def test_o_segundo_quadro_igual_grava(self):
        self._um_quadro(10)
        dados = self._um_quadro(10)
        self.assertTrue(dados["ok"])
        self.assertEqual(RegistroPonto.objects.count(), 1)

    def test_quadros_com_pessoas_diferentes_nao_gravam_nada(self):
        """
        Um nome no primeiro quadro e outro no segundo e o sistema
        dizendo que nao sabe. Escolher qualquer um dos dois seria
        escolher no acaso — e foi assim que o ponto foi parar no nome
        errado.
        """
        self._um_quadro(10)
        dados = self._um_quadro(20)

        self.assertFalse(dados["ok"])
        self.assertEqual(dados["codigo"], "discordancia")
        self.assertFalse(RegistroPonto.objects.exists())

    def test_apos_discordancia_a_contagem_recomeca(self):
        # Os dois quadros sao descartados: o seguinte e um primeiro
        # quadro de novo, e nao a confirmacao do que foi descartado.
        self._um_quadro(10)
        self._um_quadro(20)
        dados = self._um_quadro(10)
        self.assertEqual(dados["codigo"], "confirmando")
        self.assertFalse(RegistroPonto.objects.exists())

    def test_identificar_sem_registrar_nao_exige_confirmacao(self):
        # A consulta nao grava nada, entao nao ha o que confirmar.
        dados = self.post(
            "api:totem:totem_recognize",
            {"image": como_base64(imagem_bytes(10)), "registrar_ponto": False},
        ).json()
        self.assertTrue(dados["identificado"])

    def test_a_confirmacao_e_por_totem(self):
        """
        Dois totens no mesmo lugar sao dois fluxos independentes: o
        quadro de um nao pode confirmar o do outro.
        """
        outro = Totem.objects.create(empresa=self.empresa, ativo=True)
        self._um_quadro(10)
        dados = self.post(
            "api:totem:totem_recognize",
            {"image": como_base64(imagem_bytes(10))},
            token=outro.token_acesso,
        ).json()
        self.assertEqual(dados["codigo"], "confirmando")
        self.assertFalse(RegistroPonto.objects.exists())
