"""
Kronus — testes do núcleo de ponto (Fase 2).

Cobrem as garantias legais do produto: NSR sequencial, hash encadeado,
imutabilidade do registro, intervalo mínimo entre batidas, geofencing e
ajustes manuais.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import MetodoRegistro, TipoUsuario, TipoRegistro
from apps.core.utils import gerar_hash_registro
from apps.master.models import Plano
from apps.ponto import validators
from apps.ponto.models import AjustePonto, RegistroPonto
from apps.ponto.services import AjustePontoService, RegistroPontoService
from apps.rh.models import Colaborador

User = get_user_model()
SENHA = "senha-forte-123"


class BasePontoTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Teste", slug="teste", max_empresas=5, max_colaboradores=100
        )
        cls.cliente = Cliente.objects.create(
            razao_social="Cliente Teste",
            cnpj="11222333000181",
            plano=cls.plano,
            email_contato="c@c.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Empresa Teste", cnpj="11222333000262"
        )
        cls.outra_empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Outra", cnpj="11222333000343"
        )
        cls.colaborador = Colaborador.objects.create(
            empresa=cls.empresa,
            cpf="52998224725",
            nome_completo="João da Silva",
            data_nascimento=date(1990, 1, 1),
            data_admissao=date(2024, 1, 1),
        )
        cls.colega = Colaborador.objects.create(
            empresa=cls.empresa,
            cpf="15350946056",
            nome_completo="Maria Lima",
            data_nascimento=date(1990, 1, 1),
            data_admissao=date(2024, 1, 1),
        )
        cls.de_outra_empresa = Colaborador.objects.create(
            empresa=cls.outra_empresa,
            cpf="71428793860",
            nome_completo="Carlos Ramos",
            data_nascimento=date(1990, 1, 1),
            data_admissao=date(2024, 1, 1),
        )

    def bater(self, colaborador=None, **kwargs):
        """Atalho: registra sem a trava de intervalo mínimo."""
        kwargs.setdefault("validar_intervalo", False)
        return RegistroPontoService.registrar(
            colaborador=colaborador or self.colaborador, **kwargs
        )


# ══════════════════════════════════════════════════════════════
# NSR — regra 2 da Seção 14
# ══════════════════════════════════════════════════════════════
class NSRTests(BasePontoTestCase):
    def test_nsr_comeca_em_um(self):
        self.assertEqual(self.bater().nsr, 1)

    def test_nsr_e_sequencial_sem_lacunas(self):
        nsrs = [self.bater().nsr for _ in range(6)]
        self.assertEqual(nsrs, [1, 2, 3, 4, 5, 6])

    def test_nsr_e_compartilhado_entre_colaboradores_da_empresa(self):
        """O NSR é sequencial **por empresa**, não por colaborador."""
        self.assertEqual(self.bater().nsr, 1)
        self.assertEqual(self.bater(self.colega).nsr, 2)
        self.assertEqual(self.bater().nsr, 3)

    def test_nsr_e_independente_entre_empresas(self):
        self.bater()
        self.bater()
        self.assertEqual(self.bater(self.de_outra_empresa).nsr, 1)

    def test_nsr_nao_se_repete(self):
        for _ in range(10):
            self.bater()
        nsrs = list(
            RegistroPonto.objects.filter(empresa=self.empresa).values_list(
                "nsr", flat=True
            )
        )
        self.assertEqual(len(nsrs), len(set(nsrs)))


# ══════════════════════════════════════════════════════════════
# Hash encadeado — regra 3 da Seção 14
# ══════════════════════════════════════════════════════════════
class HashEncadeadoTests(BasePontoTestCase):
    def test_primeiro_registro_nao_tem_hash_anterior(self):
        registro = self.bater()
        self.assertEqual(registro.hash_anterior, "")
        self.assertEqual(len(registro.hash_registro), 64)

    def test_registro_seguinte_encadeia_o_anterior(self):
        primeiro = self.bater()
        segundo = self.bater()
        self.assertEqual(segundo.hash_anterior, primeiro.hash_registro)

    def test_hash_e_reproduzivel(self):
        registro = self.bater()
        recalculado = gerar_hash_registro(
            colaborador_id=registro.colaborador_id,
            data_hora=registro.data_hora,
            nsr=registro.nsr,
            salt_empresa=self.empresa.salt_registro,
            hash_anterior=registro.hash_anterior,
        )
        self.assertEqual(recalculado, registro.hash_registro)

    def test_cadeia_integra_e_verificavel(self):
        for _ in range(5):
            self.bater()
        resultado = RegistroPontoService.verificar_cadeia(self.empresa)
        self.assertTrue(resultado["integra"])
        self.assertEqual(resultado["registros_verificados"], 5)

    def test_adulteracao_e_detectada(self):
        """
        Alterar o hash de um registro no banco — passando por fora do
        model — tem que ser detectado pela verificação da cadeia.
        """
        for _ in range(4):
            self.bater()
        alvo = RegistroPonto.objects.get(empresa=self.empresa, nsr=2)
        RegistroPonto.objects.filter(pk=alvo.pk).update(hash_registro="0" * 64)

        resultado = RegistroPontoService.verificar_cadeia(self.empresa)
        self.assertFalse(resultado["integra"])
        self.assertEqual(resultado["motivo"], "hash_divergente")
        self.assertEqual(resultado["nsr"], 2)

    def test_alteracao_de_horario_invalida_a_cadeia(self):
        for _ in range(3):
            self.bater()
        alvo = RegistroPonto.objects.get(empresa=self.empresa, nsr=1)
        RegistroPonto.objects.filter(pk=alvo.pk).update(
            data_hora=alvo.data_hora - timedelta(hours=2)
        )
        resultado = RegistroPontoService.verificar_cadeia(self.empresa)
        self.assertFalse(resultado["integra"])

    def test_codigo_de_verificacao_e_legivel(self):
        registro = self.bater()
        self.assertRegex(
            registro.codigo_verificacao, r"^[0-9A-F]{4}(-[0-9A-F]{4}){3}$"
        )

    def test_cadeia_sobrevive_a_marcacao_gravada_em_horario_local(self):
        """
        Regressao de um defeito real (achado na Fase 5).

        O totem e o ponto web gravam a partir de um horario **local**
        (`-03:00`); o banco devolve sempre UTC. Enquanto o hash usava a
        string ISO crua, o mesmo instante gerava dois hashes e a
        verificacao reprovava registros legitimos — justamente o
        contrario do que a Portaria 671 pede da prova de integridade.
        """
        from datetime import timezone as dt_timezone

        # Um horario local, como o formulario do RH e o totem entregam.
        local = timezone.localtime(timezone.now() - timedelta(hours=3))
        self.assertNotEqual(local.utcoffset(), dt_timezone.utc.utcoffset(None))

        RegistroPontoService.registrar(colaborador=self.colaborador, momento=local)

        resultado = RegistroPontoService.verificar_cadeia(self.empresa)
        self.assertTrue(
            resultado["integra"],
            f"cadeia reprovada para marcacao em horario local: {resultado}",
        )

    def test_verificacao_independe_do_fuso_da_aplicacao(self):
        """
        Trocar o TIME_ZONE do servidor nao pode invalidar registros ja
        gravados: o hash e do instante, nao do fuso de quem consulta.
        """
        registro = self.bater()

        with self.settings(TIME_ZONE="America/Manaus"):
            resultado = RegistroPontoService.verificar_cadeia(self.empresa)
        self.assertTrue(resultado["integra"])

        with self.settings(TIME_ZONE="UTC"):
            resultado = RegistroPontoService.verificar_cadeia(self.empresa)
        self.assertTrue(resultado["integra"])
        self.assertEqual(registro.nsr, 1)


# ══════════════════════════════════════════════════════════════
# Imutabilidade — regra 1 da Seção 14
# ══════════════════════════════════════════════════════════════
class ImutabilidadeTests(BasePontoTestCase):
    def test_nao_permite_alterar_horario(self):
        registro = self.bater()
        registro.data_hora = timezone.now() - timedelta(hours=1)
        with self.assertRaises(ValidationError):
            registro.save()

    def test_nao_permite_alterar_tipo(self):
        registro = self.bater()
        registro.tipo = TipoRegistro.SAIDA
        with self.assertRaises(ValidationError):
            registro.save(update_fields=["tipo"])

    def test_nao_permite_excluir(self):
        registro = self.bater()
        with self.assertRaises(ValidationError):
            registro.delete()

    def test_permite_gravar_campos_mutaveis(self):
        registro = self.bater()
        registro.cancelado = True
        registro.save(update_fields=["cancelado"])  # não levanta
        registro.refresh_from_db()
        self.assertTrue(registro.cancelado)


# ══════════════════════════════════════════════════════════════
# Validações de negócio
# ══════════════════════════════════════════════════════════════
class ValidacoesTests(BasePontoTestCase):
    def test_intervalo_minimo_entre_batidas(self):
        """Regra 11: nada de duas batidas em menos de um minuto."""
        RegistroPontoService.registrar(colaborador=self.colaborador)
        with self.assertRaises(validators.RegistroInvalido) as contexto:
            RegistroPontoService.registrar(colaborador=self.colaborador)
        self.assertEqual(contexto.exception.codigo, "intervalo_minimo")

    def test_permite_apos_o_intervalo_minimo(self):
        """
        O prazo agora vem da empresa (padrao 10 min), nao de uma
        constante do sistema: cada operacao tem o seu ritmo.
        """
        config = self.empresa.config
        # Ancorado no passado: somar 10 min a "agora" cairia no futuro, e
        # o servico recusa marcacao futura.
        inicio = timezone.now() - timedelta(hours=1)
        RegistroPontoService.registrar(colaborador=self.colaborador, momento=inicio)
        registro = RegistroPontoService.registrar(
            colaborador=self.colaborador,
            momento=inicio + timedelta(minutes=config.minutos_entre_marcacoes, seconds=1),
        )
        self.assertEqual(registro.nsr, 2)

    def test_recusa_batida_repetida_dentro_do_prazo_da_empresa(self):
        """O toque duplo no totem: a segunda marcacao e engano, nao jornada."""
        inicio = timezone.now() - timedelta(hours=1)
        RegistroPontoService.registrar(colaborador=self.colaborador, momento=inicio)

        with self.assertRaises(validators.RegistroInvalido) as contexto:
            RegistroPontoService.registrar(
                colaborador=self.colaborador, momento=inicio + timedelta(minutes=3)
            )
        self.assertEqual(contexto.exception.codigo, "intervalo_minimo")

    def test_empresa_pode_encurtar_o_prazo(self):
        config = self.empresa.config
        config.minutos_entre_marcacoes = 1
        config.save(update_fields=["minutos_entre_marcacoes"])

        inicio = timezone.now() - timedelta(hours=1)
        RegistroPontoService.registrar(colaborador=self.colaborador, momento=inicio)
        registro = RegistroPontoService.registrar(
            colaborador=self.colaborador, momento=inicio + timedelta(seconds=70)
        )
        self.assertEqual(registro.nsr, 2)

    def test_zero_desliga_a_trava(self):
        """
        Operacoes com plantao fracionado precisam poder desligar — a
        trava existe para evitar engano, nao para impedir jornada real.
        """
        config = self.empresa.config
        config.minutos_entre_marcacoes = 0
        config.save(update_fields=["minutos_entre_marcacoes"])

        inicio = timezone.now() - timedelta(hours=1)
        RegistroPontoService.registrar(colaborador=self.colaborador, momento=inicio)
        registro = RegistroPontoService.registrar(
            colaborador=self.colaborador, momento=inicio + timedelta(seconds=5)
        )
        self.assertEqual(registro.nsr, 2)

    def test_mensagem_usa_minutos_quando_a_espera_e_longa(self):
        """"Aguarde 540 segundos" e pior do que "aguarde 9 minutos"."""
        inicio = timezone.now() - timedelta(hours=1)
        RegistroPontoService.registrar(colaborador=self.colaborador, momento=inicio)

        with self.assertRaises(validators.RegistroInvalido) as contexto:
            RegistroPontoService.registrar(
                colaborador=self.colaborador, momento=inicio + timedelta(minutes=1)
            )
        self.assertIn("minuto", str(contexto.exception))

    def test_recusa_colaborador_inativo(self):
        self.colaborador.ativo = False
        self.colaborador.save(update_fields=["ativo"])
        with self.assertRaises(validators.RegistroInvalido) as contexto:
            self.bater()
        self.assertEqual(contexto.exception.codigo, "colaborador_inativo")

    def test_recusa_colaborador_desligado(self):
        self.colaborador.data_demissao = date.today() - timedelta(days=1)
        self.colaborador.save(update_fields=["data_demissao"])
        with self.assertRaises(validators.RegistroInvalido) as contexto:
            self.bater()
        self.assertEqual(contexto.exception.codigo, "desligado")

    def test_recusa_cliente_suspenso(self):
        self.cliente.suspender("Inadimplência")
        self.colaborador.empresa.refresh_from_db()
        with self.assertRaises(validators.RegistroInvalido) as contexto:
            self.bater()
        self.assertEqual(contexto.exception.codigo, "cliente_suspenso")

    def test_recusa_data_no_futuro(self):
        with self.assertRaises(validators.RegistroInvalido) as contexto:
            self.bater(momento=timezone.now() + timedelta(hours=2))
        self.assertEqual(contexto.exception.codigo, "data_futura")


# ══════════════════════════════════════════════════════════════
# Geofencing — Seção 8.3
# ══════════════════════════════════════════════════════════════
class GeofencingTests(BasePontoTestCase):
    #: Praça da Matriz, Valença/BA — centro autorizado dos testes.
    LAT, LNG = -13.3705, -39.0733

    def ativar_geofencing(self, bloqueia=False, raio=200):
        self.empresa.geofencing_ativo = True
        self.empresa.geofencing_lat = self.LAT
        self.empresa.geofencing_lng = self.LNG
        self.empresa.geofencing_raio = raio
        self.empresa.geofencing_bloqueia = bloqueia
        self.empresa.save()
        self.colaborador.refresh_from_db()

    def test_sem_geofencing_nao_marca_fora_de_area(self):
        registro = self.bater(latitude=-12.9777, longitude=-38.5016)
        self.assertFalse(registro.fora_area)

    def test_dentro_do_raio_e_aceito(self):
        self.ativar_geofencing()
        registro = self.bater(latitude=self.LAT, longitude=self.LNG)
        self.assertFalse(registro.fora_area)

    def test_fora_do_raio_sem_bloqueio_registra_com_flag(self):
        self.ativar_geofencing(bloqueia=False)
        registro = self.bater(latitude=-12.9777, longitude=-38.5016)
        self.assertTrue(registro.fora_area)

    def test_fora_do_raio_com_bloqueio_recusa(self):
        self.ativar_geofencing(bloqueia=True)
        with self.assertRaises(validators.ForaDaAreaAutorizada) as contexto:
            self.bater(latitude=-12.9777, longitude=-38.5016)
        self.assertEqual(contexto.exception.codigo, "fora_da_area")

    def test_sem_coordenadas_com_bloqueio_recusa(self):
        self.ativar_geofencing(bloqueia=True)
        with self.assertRaises(validators.ForaDaAreaAutorizada) as contexto:
            self.bater()
        self.assertEqual(contexto.exception.codigo, "sem_geolocalizacao")

    def test_velocidade_impossivel_marca_suspeita(self):
        """Valença → Salvador em 1 minuto exigiria ~4.500 km/h."""
        agora = timezone.now()
        self.bater(momento=agora, latitude=self.LAT, longitude=self.LNG)
        registro = self.bater(
            momento=agora + timedelta(minutes=1),
            latitude=-12.9777,
            longitude=-38.5016,
        )
        self.assertTrue(registro.suspeita_fraude)

    def test_precisao_boa_demais_marca_suspeita(self):
        registro = self.bater(latitude=self.LAT, longitude=self.LNG, precisao_gps=0.2)
        self.assertTrue(registro.suspeita_fraude)


# ══════════════════════════════════════════════════════════════
# Sequência de marcações
# ══════════════════════════════════════════════════════════════
class SequenciaTests(BasePontoTestCase):
    """
    A dedução do tipo pela ordem das marcações.

    As jornadas destes testes são ancoradas em **ontem**, não em uma
    hora fixa de hoje: o serviço recusa marcação no futuro, e ancorar em
    "hoje às 08:00" faz o teste passar à tarde e falhar de madrugada —
    uma falha de relógio, não de código.
    """

    def jornada_de_ontem(self, hora):
        ontem = timezone.localtime() - timedelta(days=1)
        return ontem.replace(hour=hora, minute=0, second=0, microsecond=0)

    def test_tipos_seguem_a_sequencia_da_jornada(self):
        agora = self.jornada_de_ontem(8)
        tipos = []
        for indice in range(4):
            registro = self.bater(momento=agora + timedelta(hours=indice * 2))
            tipos.append(registro.tipo)
        self.assertEqual(
            tipos,
            [
                TipoRegistro.ENTRADA,
                TipoRegistro.INTERVALO_INICIO,
                TipoRegistro.INTERVALO_FIM,
                TipoRegistro.SAIDA,
            ],
        )

    def test_quinta_marcacao_volta_a_entrada(self):
        agora = self.jornada_de_ontem(6)
        for indice in range(4):
            self.bater(momento=agora + timedelta(hours=indice))
        quinta = self.bater(momento=agora + timedelta(hours=5))
        self.assertEqual(quinta.tipo, TipoRegistro.ENTRADA)

    def test_tipo_explicito_prevalece(self):
        registro = self.bater(tipo=TipoRegistro.SAIDA)
        self.assertEqual(registro.tipo, TipoRegistro.SAIDA)


# ══════════════════════════════════════════════════════════════
# Ajustes manuais
# ══════════════════════════════════════════════════════════════
class AjusteTests(BasePontoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rh = User.objects.create_user(
            email="rh@teste.com",
            password=SENHA,
            nome_completo="RH",
            tipo=TipoUsuario.RH,
            cliente=cls.cliente,
        )
        cls.rh.empresas.set([cls.empresa])

    def test_inclusao_cria_registro_manual(self):
        momento = timezone.now() - timedelta(hours=3)
        ajuste, registro = AjustePontoService.incluir(
            colaborador=self.colaborador,
            data_hora=momento,
            tipo=TipoRegistro.ENTRADA,
            justificativa="Esquecimento de batida na portaria",
            executado_por=self.rh,
        )
        self.assertEqual(registro.metodo, MetodoRegistro.MANUAL)
        self.assertEqual(registro.origem_ajuste, ajuste)
        self.assertEqual(registro.registrado_por, self.rh)
        self.assertEqual(ajuste.tipo_ajuste, AjustePonto.TipoAjuste.INCLUSAO)

    def test_cancelamento_preserva_o_registro_original(self):
        registro = self.bater()
        AjustePontoService.cancelar(
            registro=registro,
            justificativa="Batida em duplicidade",
            executado_por=self.rh,
        )
        registro.refresh_from_db()
        self.assertTrue(registro.cancelado)
        # O registro continua existindo — permanece no AFD.
        self.assertTrue(RegistroPonto.objects.filter(pk=registro.pk).exists())

    def test_substituicao_cancela_e_cria_novo(self):
        original = self.bater()
        ajuste, novo = AjustePontoService.substituir(
            registro=original,
            data_hora=timezone.now() - timedelta(hours=1),
            tipo=TipoRegistro.ENTRADA,
            justificativa="Horário registrado incorretamente pelo totem",
            executado_por=self.rh,
        )
        original.refresh_from_db()
        self.assertTrue(original.cancelado)
        self.assertFalse(novo.cancelado)
        self.assertGreater(novo.nsr, original.nsr)
        self.assertEqual(ajuste.tipo_ajuste, AjustePonto.TipoAjuste.SUBSTITUICAO)

    def test_cancelado_sai_das_marcacoes_do_dia(self):
        registro = self.bater()
        self.assertEqual(len(RegistroPontoService.registros_do_dia(self.colaborador)), 1)
        AjustePontoService.cancelar(
            registro=registro, justificativa="Duplicidade", executado_por=self.rh
        )
        self.assertEqual(len(RegistroPontoService.registros_do_dia(self.colaborador)), 0)


# ══════════════════════════════════════════════════════════════
# Interface web do colaborador
# ══════════════════════════════════════════════════════════════
class InterfaceColaboradorTests(BasePontoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create_user(
            cpf="52998224725",
            password=SENHA,
            nome_completo="João da Silva",
            tipo=TipoUsuario.COLABORADOR,
            cliente=cls.cliente,
        )
        cls.colaborador.user = cls.user
        cls.colaborador.save(update_fields=["user"])

    def setUp(self):
        self.client.login(username="52998224725", password=SENHA)
        # Ciencia da coleta de localizacao, exigida antes da primeira
        # batida. Dada aqui porque estes testes exercitam o registro em
        # si — o fluxo do aviso tem os seus proprios, em
        # `tests/test_local_do_ponto.py`.
        from django.utils import timezone

        type(self).colaborador.ciencia_localizacao_em = timezone.now()
        type(self).colaborador.save(update_fields=["ciencia_localizacao_em"])

    def test_sem_ciencia_a_batida_e_recusada(self):
        """
        O aviso e cobrado no servidor, e nao so no modal: a tela pode
        ser recarregada e o aviso fechado pelo navegador.
        """
        type(self).colaborador.ciencia_localizacao_em = None
        type(self).colaborador.save(update_fields=["ciencia_localizacao_em"])

        resposta = self.client.post(
            reverse("ponto:registrar_batida"),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()["codigo"], "sem_ciencia")

    def test_tela_de_registro_responde(self):
        resposta = self.client.get(reverse("ponto:registrar"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "João da Silva")

    def test_batida_via_api_cria_registro(self):
        resposta = self.client.post(
            reverse("ponto:registrar_batida"),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["nsr"], 1)
        self.assertEqual(dados["tipo"], TipoRegistro.ENTRADA)
        self.assertTrue(RegistroPonto.objects.filter(colaborador=self.colaborador).exists())

    def test_batida_duplicada_e_recusada_com_422(self):
        self.client.post(
            reverse("ponto:registrar_batida"), data="{}", content_type="application/json"
        )
        resposta = self.client.post(
            reverse("ponto:registrar_batida"), data="{}", content_type="application/json"
        )
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()["codigo"], "intervalo_minimo")

    def test_batida_registra_ip_e_user_agent(self):
        self.client.post(
            reverse("ponto:registrar_batida"),
            data="{}",
            content_type="application/json",
            HTTP_USER_AGENT="KronusTest/1.0",
        )
        registro = RegistroPonto.objects.get(colaborador=self.colaborador)
        self.assertEqual(registro.user_agent, "KronusTest/1.0")
        self.assertIsNotNone(registro.ip_address)

    def test_colaborador_sem_ponto_web_e_bloqueado(self):
        self.colaborador.permite_ponto_web = False
        self.colaborador.save(update_fields=["permite_ponto_web"])
        resposta = self.client.post(
            reverse("ponto:registrar_batida"), data="{}", content_type="application/json"
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()["codigo"], "web_bloqueado")

    def test_meus_pontos_bloqueado_quando_empresa_nao_permite(self):
        self.empresa.permite_ver_ponto = False
        self.empresa.save(update_fields=["permite_ver_ponto"])
        resposta = self.client.get(reverse("ponto:meus_pontos"))
        self.assertRedirects(resposta, reverse("ponto:registrar"))

    def test_meus_pontos_responde_quando_permitido(self):
        resposta = self.client.get(reverse("ponto:meus_pontos"))
        self.assertEqual(resposta.status_code, 200)

    def test_comprovante_do_proprio_registro_e_acessivel(self):
        registro = self.bater()
        resposta = self.client.get(
            reverse("ponto:comprovante", args=[registro.uuid])
        )
        self.assertEqual(resposta.status_code, 200)

    def test_comprovante_de_outro_colaborador_e_negado(self):
        registro = self.bater(self.colega)
        resposta = self.client.get(
            reverse("ponto:comprovante", args=[registro.uuid])
        )
        self.assertEqual(resposta.status_code, 403)
