"""
Kronus — marcacoes registradas sem conexao.

Anexo IX, requisitos 4 e 5: a marcacao deve vir de coletor on-line,
podendo **excepcionalmente** estar off-line — e, nesse caso, ser enviada
assim que a conexao voltar.

O que estes testes garantem e a promessa que o recurso faz: **a batida
feita sem conexao chega ao banco quando a conexao volta**. Um modo
offline que perde marcacao e pior do que nao ter modo offline: a pessoa
acredita que bateu o ponto e a empresa fica sem o registro.
"""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoRegistro
from apps.master.models import Plano
from apps.ponto.models import RegistroPonto
from apps.ponto.sincronizacao import ResultadoSincronizacao, sincronizar
from apps.rh.models import Colaborador
from apps.totem.models import Totem


class BaseOffline(TestCase):
    def setUp(self):
        plano = Plano.objects.create(
            nome="P", slug="p", max_empresas=3,
            max_colaboradores=50, max_totems=3, tem_offline=True,
        )
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.totem = Totem.objects.create(empresa=self.empresa, ativo=True)
        self.colaborador = Colaborador.objects.create(
            empresa=self.empresa, cpf="52998224725",
            nome_completo="Ana Souza",
            data_nascimento=date(1990, 5, 12),
            data_admissao=date(2024, 1, 1),
        )

    def _item(self, **extra):
        base = {
            "uuid": "aaaaaaaa-1111-2222-3333-444444444444",
            "colaborador_id": self.colaborador.pk,
            "tipo": TipoRegistro.ENTRADA,
            "momento": (timezone.now() - timedelta(hours=3)).isoformat(),
        }
        base.update(extra)
        return base


class SincronizacaoTests(BaseOffline):
    def test_a_batida_offline_chega_ao_banco(self):
        """A promessa central do recurso."""
        item = self._item()
        resultado = sincronizar(self.totem, [item])

        self.assertEqual(
            resultado[item["uuid"]]["situacao"], ResultadoSincronizacao.ACEITA
        )
        registro = RegistroPonto.objects.get()
        self.assertEqual(registro.colaborador, self.colaborador)
        self.assertTrue(registro.registrado_offline)
        self.assertEqual(registro.uuid_offline, item["uuid"])

    def test_guarda_a_hora_da_marcacao_e_nao_a_da_chegada(self):
        """
        Usar a hora da chegada seria registrar que a pessoa bateu o ponto
        no momento em que a internet voltou.
        """
        momento = timezone.now() - timedelta(hours=5)
        sincronizar(self.totem, [self._item(momento=momento.isoformat())])

        registro = RegistroPonto.objects.get()
        self.assertAlmostEqual(
            (registro.data_hora - momento).total_seconds(), 0, delta=2
        )
        # A gravacao e agora; os dois campos existem separados no AFD
        # justamente porque diferem quando ha fila.
        self.assertGreater(registro.created_at, registro.data_hora)

    def test_reenvio_nao_duplica(self):
        """
        Se a resposta se perder na volta, o totem reenvia. Sem
        idempotencia, a mesma batida entraria duas vezes, com dois NSR —
        quebrando a sequência que a Portaria exige.
        """
        item = self._item()
        sincronizar(self.totem, [item])
        segundo = sincronizar(self.totem, [item])

        self.assertEqual(
            segundo[item["uuid"]]["situacao"], ResultadoSincronizacao.DUPLICADA
        )
        self.assertEqual(RegistroPonto.objects.count(), 1)

    def test_a_unicidade_e_garantida_pelo_banco(self):
        """
        Verificar antes de inserir perde a corrida quando dois envios
        chegam juntos. A restrição na tabela, não.
        """
        from django.db import IntegrityError, transaction

        item = self._item()
        sincronizar(self.totem, [item])
        registro = RegistroPonto.objects.get()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RegistroPonto.objects.create(
                    colaborador=self.colaborador,
                    data_hora=timezone.now(),
                    tipo=TipoRegistro.SAIDA,
                    nsr=registro.nsr + 1,
                    hash_registro="x" * 64,
                    uuid_offline=item["uuid"],
                )

    def test_varias_marcacoes_de_uma_vez(self):
        itens = [
            self._item(
                uuid=f"bbbbbbbb-0000-0000-0000-00000000000{i}",
                tipo=tipo,
                momento=(timezone.now() - timedelta(hours=8 - i)).isoformat(),
            )
            for i, tipo in enumerate([
                TipoRegistro.ENTRADA, TipoRegistro.SAIDA,
                TipoRegistro.ENTRADA, TipoRegistro.SAIDA,
            ])
        ]
        resultados = sincronizar(self.totem, itens)

        self.assertEqual(len(resultados), 4)
        self.assertTrue(all(
            r["situacao"] == ResultadoSincronizacao.ACEITA
            for r in resultados.values()
        ))
        self.assertEqual(RegistroPonto.objects.count(), 4)

    def test_o_nsr_segue_sequencial(self):
        itens = [
            self._item(
                uuid=f"cccccccc-0000-0000-0000-00000000000{i}",
                momento=(timezone.now() - timedelta(hours=6 - i)).isoformat(),
            )
            for i in range(3)
        ]
        sincronizar(self.totem, itens)

        nsrs = sorted(RegistroPonto.objects.values_list("nsr", flat=True))
        self.assertEqual(nsrs, list(range(nsrs[0], nsrs[0] + 3)))


class RecusasTests(BaseOffline):
    def test_marcacao_no_futuro_e_recusada(self):
        item = self._item(
            momento=(timezone.now() + timedelta(hours=2)).isoformat()
        )
        resultado = sincronizar(self.totem, [item])

        self.assertEqual(
            resultado[item["uuid"]]["situacao"], ResultadoSincronizacao.RECUSADA
        )
        self.assertIn("relógio", resultado[item["uuid"]]["motivo"])
        self.assertEqual(RegistroPonto.objects.count(), 0)

    def test_marcacao_antiga_demais_e_recusada(self):
        """Mais provável ser relógio errado do que fila legítima."""
        item = self._item(
            momento=(timezone.now() - timedelta(days=30)).isoformat()
        )
        resultado = sincronizar(self.totem, [item])

        self.assertEqual(
            resultado[item["uuid"]]["situacao"], ResultadoSincronizacao.RECUSADA
        )
        self.assertEqual(RegistroPonto.objects.count(), 0)

    def test_colaborador_de_outra_empresa_e_recusado(self):
        outra = Empresa.objects.create(
            cliente=self.cliente, razao_social="Beta", cnpj="11444777000161",
        )
        estranho = Colaborador.objects.create(
            empresa=outra, cpf="11144477735", nome_completo="Estranho",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )
        item = self._item(colaborador_id=estranho.pk)
        resultado = sincronizar(self.totem, [item])

        self.assertEqual(
            resultado[item["uuid"]]["situacao"], ResultadoSincronizacao.RECUSADA
        )
        self.assertEqual(RegistroPonto.objects.count(), 0)

    def test_data_ilegivel_e_recusada_com_motivo(self):
        item = self._item(momento="ontem de tarde")
        resultado = sincronizar(self.totem, [item])

        self.assertEqual(
            resultado[item["uuid"]]["situacao"], ResultadoSincronizacao.RECUSADA
        )
        self.assertTrue(resultado[item["uuid"]]["motivo"])

    def test_item_sem_identificador_e_ignorado(self):
        """Sem chave não há como garantir idempotência — melhor não gravar."""
        resultado = sincronizar(self.totem, [self._item(uuid="")])

        self.assertEqual(resultado, {})
        self.assertEqual(RegistroPonto.objects.count(), 0)

    def test_uma_recusa_nao_derruba_as_demais(self):
        bons = [
            self._item(uuid="dddddddd-0000-0000-0000-000000000001"),
            self._item(
                uuid="dddddddd-0000-0000-0000-000000000002",
                momento=(timezone.now() - timedelta(hours=2)).isoformat(),
            ),
        ]
        ruim = self._item(
            uuid="dddddddd-0000-0000-0000-000000000009",
            momento=(timezone.now() + timedelta(days=1)).isoformat(),
        )
        resultados = sincronizar(self.totem, bons + [ruim])

        aceitas = [
            u for u, r in resultados.items()
            if r["situacao"] == ResultadoSincronizacao.ACEITA
        ]
        self.assertEqual(len(aceitas), 2)
        self.assertEqual(RegistroPonto.objects.count(), 2)


class ArquivoFiscalTests(BaseOffline):
    def test_o_afd_declara_a_marcacao_como_offline(self):
        """
        Dizer "0" numa batida que veio da fila seria declarar ao fiscal
        uma origem que não é a verdadeira.
        """
        from apps.relatorios.afd import AFDGenerator, ler_campo

        sincronizar(self.totem, [self._item()])

        hoje = timezone.localdate()
        conteudo = AFDGenerator(
            self.empresa, hoje - timedelta(days=1), hoje
        ).gerar()
        linhas = [
            linha for linha in conteudo.splitlines()
            if len(linha) > 10 and linha[9] == "7"
        ]
        self.assertTrue(linhas, "deveria haver ao menos uma marcação no AFD")
        self.assertEqual(ler_campo(linhas[0], "7", "offline"), "1")

    def test_marcacao_normal_continua_como_online(self):
        from apps.core.constants import MetodoRegistro
        from apps.ponto.services import RegistroPontoService
        from apps.relatorios.afd import AFDGenerator, ler_campo

        RegistroPontoService.registrar(
            colaborador=self.colaborador,
            metodo=MetodoRegistro.WEB,
            tipo=TipoRegistro.ENTRADA,
        )
        hoje = timezone.localdate()
        conteudo = AFDGenerator(
            self.empresa, hoje - timedelta(days=1), hoje
        ).gerar()
        linha = next(
            l for l in conteudo.splitlines() if len(l) > 10 and l[9] == "7"
        )
        self.assertEqual(ler_campo(linha, "7", "offline"), "0")


class IdentificacaoLocalTests(BaseOffline):
    """
    A lista que o totem guarda **não** traz CPF em claro: ela fica num
    tablet de portaria, que é compartilhado, roubável e sem custódia.
    """

    def test_o_resumo_nao_revela_o_cpf(self):
        from apps.totem.identificacao import resumo_de_identificacao

        resumo = resumo_de_identificacao(
            self.totem, self.colaborador.cpf, self.colaborador.data_nascimento
        )
        self.assertNotIn(self.colaborador.cpf, resumo)
        self.assertEqual(len(resumo), 64)

    def test_o_resumo_confere_quem_digitou_certo(self):
        from apps.totem.identificacao import resumo_de_identificacao

        certo = resumo_de_identificacao(self.totem, "52998224725", date(1990, 5, 12))
        de_novo = resumo_de_identificacao(self.totem, "529.982.247-25", date(1990, 5, 12))
        self.assertEqual(certo, de_novo)

    def test_data_de_nascimento_errada_nao_confere(self):
        """
        Sem a data, conhecer o CPF de um colega bastaria para bater o
        ponto no lugar dele.
        """
        from apps.totem.identificacao import resumo_de_identificacao

        certo = resumo_de_identificacao(self.totem, "52998224725", date(1990, 5, 12))
        errado = resumo_de_identificacao(self.totem, "52998224725", date(1990, 5, 13))
        self.assertNotEqual(certo, errado)

    def test_a_lista_de_um_totem_nao_serve_a_outro(self):
        from apps.totem.identificacao import resumo_de_identificacao

        outro = Totem.objects.create(empresa=self.empresa, ativo=True)
        self.assertNotEqual(
            resumo_de_identificacao(self.totem, "52998224725", date(1990, 5, 12)),
            resumo_de_identificacao(outro, "52998224725", date(1990, 5, 12)),
        )

    def test_rotacionar_o_token_invalida_a_lista(self):
        """O comportamento desejado quando um equipamento é perdido."""
        from apps.totem.identificacao import resumo_de_identificacao

        antes = resumo_de_identificacao(
            self.totem, "52998224725", date(1990, 5, 12)
        )
        self.totem.regenerar_token()
        depois = resumo_de_identificacao(
            self.totem, "52998224725", date(1990, 5, 12)
        )
        self.assertNotEqual(antes, depois)


class ApiTests(BaseOffline):
    def _cabecalho(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.totem.token_acesso}"}

    def test_a_lista_nao_expoe_cpf(self):
        resposta = self.client.get(
            reverse("api:totem:totem_colaboradores_offline"), **self._cabecalho()
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.content.decode()

        self.assertIn("Ana Souza", corpo)
        self.assertNotIn("52998224725", corpo)

    def test_o_envio_grava_e_responde_por_item(self):
        item = self._item()
        resposta = self.client.post(
            reverse("api:totem:totem_sincronizar"),
            {"marcacoes": [item]},
            content_type="application/json",
            **self._cabecalho(),
        )

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["ok"])
        self.assertEqual(
            dados["resultados"][item["uuid"]]["situacao"],
            ResultadoSincronizacao.ACEITA,
        )
        self.assertEqual(RegistroPonto.objects.count(), 1)

    def test_sem_token_nao_sincroniza(self):
        resposta = self.client.post(
            reverse("api:totem:totem_sincronizar"),
            {"marcacoes": [self._item()]},
            content_type="application/json",
        )
        self.assertIn(resposta.status_code, (401, 403))
        self.assertEqual(RegistroPonto.objects.count(), 0)

    def test_lote_grande_demais_e_recusado(self):
        itens = [
            self._item(uuid=f"eeeeeeee-0000-0000-0000-{i:012d}")
            for i in range(501)
        ]
        resposta = self.client.post(
            reverse("api:totem:totem_sincronizar"),
            {"marcacoes": itens},
            content_type="application/json",
            **self._cabecalho(),
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(RegistroPonto.objects.count(), 0)


class AcessoDoColaboradorTests(TestCase):
    """
    O login do colaborador precisa estar **vinculado a empresa**.

    Sem esse vinculo a pessoa entra e nao enxerga nada, porque todo o
    sistema e escopado por empresa — e o sintoma que chega e "nao consigo
    acessar", sem nada no log indicando o motivo.
    """

    def setUp(self):
        from apps.master.models import Plano

        plano = Plano.objects.create(nome="P", slug="p", max_colaboradores=50)
        cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="Alfa",
            cnpj="45997418000234", slug="alfa",
        )
        self.colaborador = Colaborador.objects.create(
            empresa=self.empresa, cpf="52998224725",
            nome_completo="Ana Souza", email="ana@alfa.com",
            data_nascimento=date(1990, 5, 12),
            data_admissao=date(2024, 1, 1),
        )

    def test_cria_o_login_vinculado_a_empresa(self):
        usuario, senha = self.colaborador.garantir_usuario()

        self.assertIsNotNone(senha)
        self.assertIn(self.empresa, usuario.empresas.all())
        self.assertEqual(usuario.cliente, self.empresa.cliente)
        self.assertTrue(usuario.trocar_senha_no_proximo_login)

    def test_o_colaborador_enxerga_o_proprio_painel(self):
        usuario, senha = self.colaborador.garantir_usuario()
        usuario.trocar_senha_no_proximo_login = False
        usuario.save(update_fields=["trocar_senha_no_proximo_login"])

        self.client.force_login(usuario)
        resposta = self.client.get("/app/", follow=True)
        self.assertEqual(resposta.status_code, 200)

    def test_ao_sair_volta_para_a_pagina_da_empresa(self):
        """
        Sem o vínculo, o logout caía na capa comercial do Kronus — a
        pessoa perdia o endereço de volta e via a nossa marca no lugar da
        do empregador.
        """
        from django.urls import reverse

        usuario, _ = self.colaborador.garantir_usuario()
        usuario.trocar_senha_no_proximo_login = False
        usuario.save(update_fields=["trocar_senha_no_proximo_login"])

        self.client.force_login(usuario)
        self.client.get("/app/")
        resposta = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(resposta, "/alfa/", fetch_redirect_response=False)

    def test_e_idempotente(self):
        primeiro, senha = self.colaborador.garantir_usuario()
        segundo, sem_senha = self.colaborador.garantir_usuario()

        self.assertEqual(primeiro.pk, segundo.pk)
        self.assertIsNotNone(senha)
        self.assertIsNone(sem_senha)

    def test_reaproveita_login_existente_com_o_mesmo_cpf(self):
        """Criar um segundo esbarraria na unicidade do CPF."""
        from apps.accounts.models import CustomUser
        from apps.core.constants import TipoUsuario

        existente = CustomUser.objects.create_user(
            cpf="52998224725", password="x", nome_completo="Ana",
            tipo=TipoUsuario.COLABORADOR,
        )
        usuario, _ = self.colaborador.garantir_usuario()

        self.assertEqual(usuario.pk, existente.pk)
        self.assertIn(self.empresa, usuario.empresas.all())
