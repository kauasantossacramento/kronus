"""
Kronus — de onde a pessoa bateu o ponto.

Caso real: 321 batidas pela web, zero com coordenada. O front só pedia
a localização quando a empresa ligava o geofencing — então o RH não
tinha como saber de onde ninguém bateu.

E coordenada crua não responde a pergunta que se faz: "-12.2664,
-38.9663" não diz se a pessoa estava na empresa ou em casa.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase


class BaseLocal(TestCase):
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
            empresa=self.empresa, nome_completo="Fulano de Tal",
            cpf="52998224725", data_nascimento=date(1990, 1, 1),
            data_admissao=date(2020, 1, 1),
        )

    def _registro(self, **extra):
        from apps.ponto.models import RegistroPonto
        from django.utils import timezone

        return RegistroPonto.objects.create(
            empresa=self.empresa, colaborador=self.pessoa,
            data_hora=timezone.now(), tipo="entrada", metodo="web",
            nsr=1, hash_registro="x", **extra,
        )


class LocalLegivelTests(BaseLocal):
    def test_mostra_o_endereco_quando_ja_resolvido(self):
        r = self._registro(
            latitude=Decimal("-12.2664"), longitude=Decimal("-38.9663"),
            endereco="Rua Marechal Deodoro, Centro, Feira de Santana",
        )
        self.assertIn("Marechal Deodoro", r.local_legivel)

    def test_mostra_a_coordenada_enquanto_o_endereco_nao_chega(self):
        """
        O endereço vem em segundo plano. Até lá a coordenada já serve —
        e o mapa abre com ela.
        """
        r = self._registro(
            latitude=Decimal("-12.2664"), longitude=Decimal("-38.9663")
        )
        self.assertIn("-12.2664", r.local_legivel)

    def test_sem_gps_nao_inventa_local(self):
        """
        Vazio também informa: diz que a pessoa não autorizou o GPS.
        """
        self.assertEqual(self._registro().local_legivel, "")

    def test_o_mapa_abre_sem_conta(self):
        """
        OpenStreetMap, e não Google: sem login, sem cookie de rastreio,
        e sem mandar o RH para uma página que pede conta.
        """
        r = self._registro(
            latitude=Decimal("-12.2664"), longitude=Decimal("-38.9663")
        )
        self.assertIn("openstreetmap.org", r.link_do_mapa)
        self.assertIn("-12.2664", r.link_do_mapa)

    def test_sem_gps_nao_ha_mapa(self):
        self.assertEqual(self._registro().link_do_mapa, "")


class GeocodificacaoTests(TestCase):
    def test_monta_o_endereco_do_especifico_para_o_geral(self):
        """
        O `display_name` do Nominatim traz país, CEP e estado inteiro —
        quinze palavras onde três bastam.
        """
        from apps.ponto.geocodificacao import _resumir

        resumo = _resumir({
            "address": {
                "road": "Rua Marechal Deodoro",
                "suburb": "Centro",
                "city": "Feira de Santana",
                "state": "Bahia",
                "country": "Brasil",
                "postcode": "44000-000",
            }
        })
        self.assertTrue(resumo.startswith("Rua Marechal Deodoro"))
        self.assertIn("Feira de Santana", resumo)
        self.assertNotIn("Brasil", resumo)
        self.assertNotIn("44000", resumo)

    def test_nao_repete_o_mesmo_nome(self):
        from apps.ponto.geocodificacao import _resumir

        resumo = _resumir({
            "address": {"suburb": "Centro", "city": "Centro", "state": "Bahia"}
        })
        self.assertEqual(resumo.count("Centro"), 1)

    def test_sem_coordenada_nao_consulta(self):
        from apps.ponto.geocodificacao import endereco_de

        self.assertEqual(endereco_de(None, None), "")

    def test_falha_no_servico_devolve_vazio(self):
        """
        Serviço de mapas fora do ar deixa o registro sem endereço — e o
        registro sem endereço continua sendo um registro válido.
        """
        from apps.ponto import geocodificacao

        class Quebrado:
            def get(self, *a, **kw):
                raise RuntimeError("rede caiu")

        with patch.dict("sys.modules", {"requests": Quebrado()}):
            self.assertEqual(geocodificacao.endereco_de(-12.2, -38.9), "")

    def test_identifica_quem_esta_chamando(self):
        """
        A política do Nominatim bloqueia chamada anônima — e com razão:
        sem identificar quem chama, não há como avisar antes de barrar.
        """
        from apps.ponto.geocodificacao import AGENTE

        self.assertIn("Kronus", AGENTE)
        self.assertIn("@", AGENTE)


class ColetaSempreTests(TestCase):
    """
    O front pedia a localização só com o geofencing ligado — e o
    resultado foram 321 batidas sem uma única coordenada.
    """

    def test_a_pagina_pede_a_posicao_sempre(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        pagina = (
            raiz / "apps" / "ponto" / "templates" / "ponto" / "bater_ponto.html"
        ).read_text(encoding="utf-8")

        self.assertIn("const posicao = await this.obterPosicao();", pagina)
        self.assertNotIn(
            "this.exigeGeo ? await this.obterPosicao() : null", pagina
        )

    def test_quem_recusa_o_gps_continua_batendo(self):
        """
        A permissão negada não pode impedir o registro: bater ponto é
        obrigação legal, e o local é evidência acessória.
        """
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        pagina = (
            raiz / "apps" / "ponto" / "templates" / "ponto" / "bater_ponto.html"
        ).read_text(encoding="utf-8")
        # O bloqueio só existe quando a empresa exige E bloqueia.
        self.assertIn("this.exigeGeo && this.bloqueiaFora && !posicao", pagina)


class CienciaDaLocalizacaoTests(BaseLocal):
    """
    Ciencia, e nao consentimento.

    A base legal da coleta e o contrato de trabalho e a Portaria 671,
    que ja obrigam o controle de jornada. A distincao importa: a LGPD
    exige consentimento livre (Art. 8, §1), e consentimento obtido sob
    condicao de nao poder trabalhar seria coagido — logo invalido, e
    inutil como defesa numa fiscalizacao.
    """

    def setUp(self):
        super().setUp()
        from apps.accounts.models import CustomUser

        self.user = CustomUser.objects.create_user(
            email="fulano@t.com", password="x", nome_completo="Fulano de Tal",
            tipo="colaborador", cliente=self.empresa.cliente,
        )
        self.user.empresas.add(self.empresa)
        self.pessoa.user = self.user
        self.pessoa.permite_ponto_web = True
        self.pessoa.save()

    def _logar(self):
        from apps.core.middleware import CHAVE_SESSAO_EMPRESA

        self.client.force_login(self.user)
        s = self.client.session
        s[CHAVE_SESSAO_EMPRESA] = self.empresa.pk
        s.save()

    def test_comeca_precisando_dar_ciencia(self):
        self.assertTrue(self.pessoa.precisa_dar_ciencia_da_localizacao)

    def test_sem_ciencia_a_batida_e_recusada(self):
        """
        Cobrado no servidor, e nao so no modal: a tela pode ser
        recarregada e o aviso fechado pelo navegador.
        """
        self._logar()
        r = self.client.post(
            "/ponto/registrar/batida/", data="{}", content_type="application/json"
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["codigo"], "sem_ciencia")

    def test_depois_da_ciencia_a_batida_passa(self):
        self._logar()
        self.client.post("/ponto/registrar/ciencia-local/")
        r = self.client.post(
            "/ponto/registrar/batida/", data="{}", content_type="application/json"
        )
        self.assertNotEqual(r.status_code, 403)

    def test_a_ciencia_fica_registrada_com_data_e_ip(self):
        """
        "A pessoa foi informada" precisa ser demonstravel, e nao apenas
        afirmado.
        """
        self._logar()
        self.client.post("/ponto/registrar/ciencia-local/")
        self.pessoa.refresh_from_db()
        self.assertIsNotNone(self.pessoa.ciencia_localizacao_em)

    def test_dar_ciencia_duas_vezes_nao_reescreve_a_data(self):
        """
        A data que vale e a de quando a pessoa soube, e nao a da ultima
        vez que abriu a tela.
        """
        self._logar()
        self.client.post("/ponto/registrar/ciencia-local/")
        self.pessoa.refresh_from_db()
        primeira = self.pessoa.ciencia_localizacao_em

        self.client.post("/ponto/registrar/ciencia-local/")
        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.ciencia_localizacao_em, primeira)

    def test_o_aviso_informa_em_vez_de_pedir_permissao(self):
        """
        Pedir permissao e nao aceitar "nao" seria pior que nao
        perguntar. O texto informa e pede ciencia.
        """
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        pagina = (
            raiz / "apps" / "ponto" / "templates" / "ponto" / "bater_ponto.html"
        ).read_text(encoding="utf-8")

        self.assertIn("Li e estou ciente", pagina)
        # E diz que recusar o GPS nao impede de bater ponto. Comparado
        # sem quebras de linha: o HTML quebra a frase, e procurar o
        # texto literal testaria a formatacao, nao o conteudo.
        corrido = " ".join(pagina.split())
        self.assertIn("o ponto ainda é registrado", corrido)
        # E nao usa a palavra que implicaria escolha que a pessoa nao
        # tem: pedir permissao e nao aceitar "nao" seria pior que nao
        # perguntar.
        self.assertNotIn("Autorizo", corrido)
        self.assertNotIn("Concordo com a coleta", corrido)


class AbaAbertaAntesDoAvisoTests(TestCase):
    """
    Quem estava com a pagina aberta desde antes do aviso existir.

    O modal nunca apareceu para essa pessoa: ela clica em registrar, o
    servidor recusa com 403, e sem tratamento ela ve so uma mensagem de
    erro — precisando adivinhar que era para recarregar.

    Sao 30 pessoas batendo pela web em producao, e o deploy acontece no
    meio do expediente.
    """

    def _pagina(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parent.parent
        return (
            raiz / "apps" / "ponto" / "templates" / "ponto" / "bater_ponto.html"
        ).read_text(encoding="utf-8")

    def test_a_recusa_por_falta_de_ciencia_abre_o_aviso(self):
        pagina = self._pagina()
        self.assertIn("dados.codigo === 'sem_ciencia'", pagina)
        self.assertIn("this.precisaCiencia = true;", pagina)

    def test_a_batida_e_retomada_depois_da_ciencia(self):
        """
        A pessoa clicou em "registrar": a intencao dela nao pode se
        perder por causa de um aviso no meio do caminho.
        """
        pagina = self._pagina()
        self.assertIn("retomarAposCiencia", pagina)
        self.assertIn("this.registrar();", pagina)

    def test_a_falta_de_ciencia_nao_vira_mensagem_de_erro(self):
        """
        O tratamento vem ANTES do ramo de erro generico — senao a
        pessoa veria "Nao foi possivel registrar o ponto" e o aviso
        junto.
        """
        pagina = self._pagina()
        pos_ciencia = pagina.index("dados.codigo === 'sem_ciencia'")
        pos_erro = pagina.index("Não foi possível registrar o ponto.")
        self.assertLess(pos_ciencia, pos_erro)
