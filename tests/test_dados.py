"""
Kronus — testes de importação e exportação de dados (Fase 6).

Duas operações com riscos opostos:

* **Importação** cria gente no sistema. O risco é gravar lixo — CPF
  inválido, duplicata, data impossível — e depois ter de limpar. Por
  isso os testes insistem que nada é gravado antes da confirmação.
* **Exportação para folha** manda números para quem paga. O risco é o
  arredondamento e a conversão: 1h30 tem de virar 1,50, não 1,30.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import StatusDia, TipoUsuario
from apps.master.models import Plano
from apps.ponto.models import BancoHoras, EscalaTrabalho
from apps.relatorios.folha import FolhaExporter, minutos_para_decimal
from apps.rh.importacao import ImportadorColaboradores, modelo_csv
from apps.rh.models import Colaborador, Departamento


class BaseDadosTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Pro", slug="pro", max_colaboradores=500, tem_api=True
        )
        cls.cliente = Cliente.objects.create(
            razao_social="Grupo Alfa", cnpj="11222333000181",
            plano=cls.plano, email_contato="alfa@exemplo.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Alfa Matriz", cnpj="11222333000262"
        )
        cls.departamento = Departamento.objects.create(
            empresa=cls.empresa, nome="Administrativo"
        )
        cls.escala = EscalaTrabalho.objects.create(
            empresa=cls.empresa, nome="Comercial",
            carga_diaria_min=480, carga_semanal_min=2640,
        )


# ══════════════════════════════════════════════════════════════
# Conversão de horas — onde a folha diverge
# ══════════════════════════════════════════════════════════════
class ConversaoDecimalTests(TestCase):
    def test_hora_e_meia_vira_um_virgula_cinco(self):
        """O erro clássico: 1h30 exportado como 1,30 paga 20 min a menos."""
        self.assertEqual(minutos_para_decimal(90), Decimal("1.50"))

    def test_conversoes_conhecidas(self):
        for minutos, esperado in [
            (0, "0.00"), (60, "1.00"), (30, "0.50"),
            (480, "8.00"), (495, "8.25"), (45, "0.75"),
        ]:
            self.assertEqual(minutos_para_decimal(minutos), Decimal(esperado))

    def test_arredonda_meio_para_cima(self):
        """
        A folha brasileira arredonda meio para cima. O padrão do Python
        é o bancário (para o par), que divergiria num total mensal.
        """
        # 5 min = 0,08333… -> 0,08 ; 15 min = 0,25 exato
        self.assertEqual(minutos_para_decimal(5), Decimal("0.08"))
        # 0,875 h = 52,5 min -> arredonda para cima
        self.assertEqual(minutos_para_decimal(53), Decimal("0.88"))

    def test_negativo_preserva_o_sinal(self):
        self.assertEqual(minutos_para_decimal(-90), Decimal("-1.50"))


# ══════════════════════════════════════════════════════════════
# Exportação para folha
# ══════════════════════════════════════════════════════════════
class ExportacaoFolhaTests(BaseDadosTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.joao = Colaborador.objects.create(
            empresa=cls.empresa, cpf="52998224725",
            nome_completo="João da Silva Souza", data_nascimento=date(1990, 3, 12),
            data_admissao=date(2024, 1, 1), matricula="0001",
        )
        cls.maria = Colaborador.objects.create(
            empresa=cls.empresa, cpf="71428793860",
            nome_completo="Maria Ramos", data_nascimento=date(1985, 6, 2),
            data_admissao=date(2024, 1, 1), matricula="0002",
        )
        cls.inicio = date(2026, 7, 1)
        cls.fim = date(2026, 7, 31)

        for indice in range(5):
            BancoHoras.objects.create(
                empresa=cls.empresa, colaborador=cls.joao,
                data=cls.inicio + timedelta(days=indice),
                minutos_trabalhados=510, minutos_esperados=480,
                minutos_extras=30, minutos_noturnos=12, minutos_atraso=5,
                saldo_dia=30, saldo_acumulado=30 * (indice + 1),
                status=StatusDia.COMPLETO,
            )
        BancoHoras.objects.create(
            empresa=cls.empresa, colaborador=cls.joao,
            data=cls.inicio + timedelta(days=5),
            minutos_trabalhados=0, minutos_esperados=480,
            saldo_dia=-480, saldo_acumulado=-330, status=StatusDia.FALTA,
        )
        BancoHoras.objects.create(
            empresa=cls.empresa, colaborador=cls.maria,
            data=cls.inicio, minutos_trabalhados=480, minutos_esperados=480,
            saldo_dia=0, saldo_acumulado=0, status=StatusDia.COMPLETO,
        )

    def test_uma_linha_por_colaborador_no_csv(self):
        conteudo = FolhaExporter(self.empresa, self.inicio, self.fim).gerar()
        linhas = [l for l in conteudo.splitlines() if l.strip()]
        self.assertEqual(len(linhas), 3)  # cabeçalho + 2 colaboradores

    def test_totais_agregados_corretamente(self):
        conteudo = FolhaExporter(self.empresa, self.inicio, self.fim).gerar()
        linha = next(l for l in conteudo.splitlines() if l.startswith("0001"))
        campos = linha.split(";")

        # 5 dias x 510 min = 2550 min = 42,50 h
        self.assertIn("42,50", campos)
        # 5 x 30 = 150 min de extras = 2,50 h
        self.assertIn("2,50", campos)
        # 1 falta
        self.assertEqual(campos[11], "1")

    def test_colaborador_sem_apuracao_fica_de_fora(self):
        """
        Exportar zeros para quem não tem apuração é diferente de não
        exportar: a folha leria "mês sem horas" em vez de "sem dado".
        """
        Colaborador.objects.create(
            empresa=self.empresa, cpf="15350946056", nome_completo="Sem Apuracao",
            data_nascimento=date(1980, 1, 1), data_admissao=date(2026, 7, 1),
            matricula="0003",
        )
        conteudo = FolhaExporter(self.empresa, self.inicio, self.fim).gerar()
        self.assertNotIn("Sem Apuracao", conteudo)

    def test_layout_dominio_e_posicional_e_de_largura_fixa(self):
        conteudo = FolhaExporter(
            self.empresa, self.inicio, self.fim, layout="dominio"
        ).gerar()
        linhas = [l for l in conteudo.split("\r\n") if l]
        self.assertTrue(linhas)
        # 10 + 11 + 4 + 9 + 6 = 40 posições
        for linha in linhas:
            self.assertEqual(len(linha), 40, f"linha fora do gabarito: {linha!r}")

    def test_dominio_gera_um_lancamento_por_evento(self):
        conteudo = FolhaExporter(
            self.empresa, self.inicio, self.fim, layout="dominio"
        ).gerar()
        linhas = [l for l in conteudo.split("\r\n") if l]
        # João tem extras, noturnas e atrasos = 3 lançamentos.
        # Maria não tem nenhum evento = nenhum lançamento.
        codigos = {linha[21:25] for linha in linhas}
        self.assertEqual(codigos, {"0001", "0002", "0003"})
        self.assertEqual(len(linhas), 3)

    def test_evento_zerado_nao_vira_lancamento(self):
        """Mandar '0 horas extras' cria um lançamento vazio que o RH terá de explicar."""
        conteudo = FolhaExporter(
            self.empresa, self.inicio, self.fim, layout="dominio"
        ).gerar()
        for linha in conteudo.split("\r\n"):
            if linha:
                self.assertNotEqual(linha[25:34], "0" * 9)

    def test_layout_totvs_usa_ponto_decimal(self):
        conteudo = FolhaExporter(
            self.empresa, self.inicio, self.fim, layout="totvs"
        ).gerar()
        self.assertIn("42.50", conteudo)
        self.assertNotIn("42,50", conteudo)

    def test_codificacao_por_layout(self):
        posicional = FolhaExporter(
            self.empresa, self.inicio, self.fim, layout="dominio"
        )
        self.assertIsInstance(posicional.gerar_bytes(), bytes)
        # utf-8-sig no genérico: o Excel pt-BR precisa do BOM
        generico = FolhaExporter(self.empresa, self.inicio, self.fim).gerar_bytes()
        self.assertTrue(generico.startswith(b"\xef\xbb\xbf"))

    def test_layout_desconhecido_e_recusado(self):
        with self.assertRaises(ValueError):
            FolhaExporter(self.empresa, self.inicio, self.fim, layout="inexistente")

    def test_resumo_bate_com_o_arquivo(self):
        exportador = FolhaExporter(self.empresa, self.inicio, self.fim)
        resumo = exportador.resumo()
        self.assertEqual(resumo["colaboradores"], 2)
        self.assertEqual(resumo["minutos_extras"], 150)
        self.assertEqual(resumo["horas_extras_decimal"], Decimal("2.50"))
        self.assertEqual(resumo["dias_falta"], 1)

    def test_nome_do_arquivo_identifica_empresa_e_periodo(self):
        nome = FolhaExporter(self.empresa, self.inicio, self.fim, "dominio").nome_arquivo()
        self.assertEqual(nome, "folha_dominio_11222333000262_20260701_20260731.txt")

    def test_nao_vaza_colaborador_de_outra_empresa(self):
        outra = Empresa.objects.create(
            cliente=self.cliente, razao_social="Beta", cnpj="11222333000343"
        )
        alheio = Colaborador.objects.create(
            empresa=outra, cpf="03874649089", nome_completo="Alheio Silva",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
            matricula="9999",
        )
        BancoHoras.objects.create(
            empresa=outra, colaborador=alheio, data=self.inicio,
            minutos_trabalhados=480, minutos_esperados=480,
            saldo_dia=0, saldo_acumulado=0, status=StatusDia.COMPLETO,
        )
        conteudo = FolhaExporter(self.empresa, self.inicio, self.fim).gerar()
        self.assertNotIn("Alheio Silva", conteudo)


# ══════════════════════════════════════════════════════════════
# Importação de colaboradores
# ══════════════════════════════════════════════════════════════
CABECALHO = (
    "cpf;nome;data_nascimento;data_admissao;matricula;email;telefone;"
    "cargo;departamento;escala;pis;ctps;ctps_serie"
)


def csv_com(*linhas, cabecalho=CABECALHO):
    return ("\r\n".join([cabecalho, *linhas]) + "\r\n").encode("utf-8")


class ImportacaoTests(BaseDadosTestCase):
    def conferir(self, conteudo):
        return ImportadorColaboradores(self.empresa, conteudo).conferir()

    def importar(self, conteudo):
        return ImportadorColaboradores(self.empresa, conteudo).importar()

    # -- conferência ------------------------------------------
    def test_conferir_nao_grava_nada(self):
        """A garantia central: validar não pode criar ninguém."""
        laudo = self.conferir(csv_com(
            "529.982.247-25;João da Silva;12/03/1990;01/02/2024;0001;;;;;;;;"
        ))
        self.assertEqual(len(laudo.validas), 1)
        self.assertEqual(Colaborador.objects.count(), 0)

    def test_linha_valida_e_importada(self):
        laudo = self.importar(csv_com(
            "529.982.247-25;João da Silva;12/03/1990;01/02/2024;0001;"
            "joao@x.com;(73) 99999-0000;Analista;Administrativo;Comercial;;;"
        ))
        self.assertEqual(laudo.criados, 1)
        colaborador = Colaborador.objects.get()
        self.assertEqual(colaborador.cpf, "52998224725")
        self.assertEqual(colaborador.matricula, "0001")
        self.assertEqual(colaborador.departamento, self.departamento)
        self.assertEqual(colaborador.escala, self.escala)

    def test_cpf_invalido_e_recusado(self):
        laudo = self.conferir(csv_com(
            "111.111.111-11;Fulano;01/01/1990;01/01/2024;;;;;;;;;"
        ))
        self.assertEqual(len(laudo.invalidas), 1)
        self.assertIn("CPF inválido", laudo.invalidas[0].erros[0])

    def test_cpf_ja_cadastrado_e_recusado(self):
        Colaborador.objects.create(
            empresa=self.empresa, cpf="52998224725", nome_completo="Já Existe",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )
        laudo = self.conferir(csv_com(
            "529.982.247-25;João da Silva;12/03/1990;01/02/2024;;;;;;;;;"
        ))
        self.assertIn("já cadastrado", laudo.invalidas[0].erros[0])

    def test_cpf_repetido_no_arquivo_e_recusado_uma_vez(self):
        laudo = self.conferir(csv_com(
            "529.982.247-25;João A;12/03/1990;01/02/2024;;;;;;;;;",
            "529.982.247-25;João B;12/03/1990;01/02/2024;;;;;;;;;",
        ))
        self.assertEqual(len(laudo.validas), 1)
        self.assertIn("repetido", laudo.invalidas[0].erros[0])

    def test_data_em_formato_errado_e_reportada(self):
        laudo = self.conferir(csv_com(
            "529.982.247-25;João;1990-03-12;fevereiro de 2024;;;;;;;;;"
        ))
        self.assertTrue(any("data" in e for e in laudo.invalidas[0].erros))

    def test_aceita_data_iso_e_barra(self):
        laudo = self.conferir(csv_com(
            "529.982.247-25;João;1990-03-12;2024-02-01;;;;;;;;;"
        ))
        self.assertEqual(len(laudo.validas), 1)
        self.assertEqual(laudo.validas[0].dados["data_admissao"], date(2024, 2, 1))

    def test_admissao_no_futuro_e_recusada(self):
        futuro = (timezone.localdate() + timedelta(days=30)).strftime("%d/%m/%Y")
        laudo = self.conferir(csv_com(
            f"529.982.247-25;João;12/03/1990;{futuro};;;;;;;;;"
        ))
        self.assertTrue(any("futuro" in e for e in laudo.invalidas[0].erros))

    def test_nascimento_posterior_a_admissao_e_recusado(self):
        laudo = self.conferir(csv_com(
            "529.982.247-25;João;01/01/2025;01/02/2024;;;;;;;;;"
        ))
        self.assertTrue(
            any("nascimento" in e for e in laudo.invalidas[0].erros)
        )

    def test_pis_invalido_e_recusado(self):
        laudo = self.conferir(csv_com(
            "529.982.247-25;João;12/03/1990;01/02/2024;;;;;;;123.4567.890-9;;"
        ))
        self.assertTrue(any("PIS" in e for e in laudo.invalidas[0].erros))

    def test_colunas_obrigatorias_ausentes_param_a_importacao(self):
        laudo = self.conferir(csv_com("João;01/02/2024", cabecalho="nome;data_admissao"))
        self.assertFalse(laudo.pode_importar)
        self.assertIn("cpf", laudo.invalidas[0].erros[0])

    def test_aceita_nomes_alternativos_de_coluna(self):
        """'chapa' e 'setor' são o que o sistema antigo do cliente exporta."""
        laudo = self.conferir(csv_com(
            "529.982.247-25;João da Silva;01/02/2024;0007;Administrativo",
            cabecalho="CPF;Nome Completo;Data de Admissão;Chapa;Setor",
        ))
        self.assertEqual(len(laudo.validas), 1)
        self.assertEqual(laudo.validas[0].dados["matricula"], "0007")

    def test_aceita_separador_virgula(self):
        conteudo = (
            "cpf,nome,data_admissao\r\n"
            "529.982.247-25,João da Silva,01/02/2024\r\n"
        ).encode("utf-8")
        laudo = self.conferir(conteudo)
        self.assertEqual(len(laudo.validas), 1)

    def test_aceita_arquivo_em_latin1(self):
        """Planilha de sistema antigo quase sempre vem em Latin-1."""
        conteudo = (
            "cpf;nome;data_admissao\r\n"
            "529.982.247-25;João Conceição;01/02/2024\r\n"
        ).encode("iso-8859-1")
        laudo = self.conferir(conteudo)
        self.assertEqual(len(laudo.validas), 1)
        self.assertIn("Concei", laudo.validas[0].dados["nome_completo"])

    def test_linhas_em_branco_sao_ignoradas(self):
        laudo = self.conferir(csv_com(
            "529.982.247-25;João;12/03/1990;01/02/2024;;;;;;;;;",
            ";;;;;;;;;;;;",
            "",
        ))
        self.assertEqual(laudo.total, 1)

    def test_importa_so_as_validas_e_relata_o_resto(self):
        laudo = self.importar(csv_com(
            "529.982.247-25;João da Silva;12/03/1990;01/02/2024;0001;;;;;;;;",
            "111.111.111-11;CPF Ruim;01/01/1990;01/01/2024;0002;;;;;;;;",
            "714.287.938-60;Maria Ramos;02/06/1985;01/03/2024;0003;;;;;;;;",
        ))
        self.assertEqual(laudo.criados, 2)
        self.assertEqual(len(laudo.invalidas), 1)
        self.assertEqual(Colaborador.objects.count(), 2)

    def test_departamento_inexistente_vira_aviso_nao_erro(self):
        """
        A estrutura organizacional é decisão do RH: um erro de digitação
        não pode criar um departamento fantasma no relatório.
        """
        laudo = self.importar(csv_com(
            "529.982.247-25;João;12/03/1990;01/02/2024;;;;;Setor Que Nao Existe;;;;"
        ))
        self.assertEqual(laudo.criados, 1)
        colaborador = Colaborador.objects.get()
        self.assertIsNone(colaborador.departamento)
        self.assertIn("não existe", laudo.validas[0].aviso)
        self.assertEqual(Departamento.objects.count(), 1)

    def test_arquivo_vazio_nao_quebra(self):
        laudo = self.conferir(b"")
        self.assertFalse(laudo.pode_importar)

    def test_modelo_csv_e_importavel(self):
        """O modelo oferecido para download tem de passar na própria validação."""
        laudo = self.conferir(modelo_csv().encode("utf-8"))
        self.assertEqual(len(laudo.validas), 1, laudo.linhas[0].erros if laudo.linhas else "")


# ══════════════════════════════════════════════════════════════
# Telas
# ══════════════════════════════════════════════════════════════
class TelasDadosTests(BaseDadosTestCase):
    def setUp(self):
        from apps.accounts.models import CustomUser

        self.rh = CustomUser.objects.create_user(
            username="rh@alfa.com", password="senha-forte-123",
            nome_completo="Analista RH", tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        self.rh.empresas.add(self.empresa)
        self.client.force_login(self.rh)
        sessao = self.client.session
        sessao["empresa_ativa_id"] = self.empresa.pk
        sessao.save()

    def test_tela_de_importacao_abre(self):
        resposta = self.client.get(reverse("rh:importar_colaboradores"))
        self.assertEqual(resposta.status_code, 200)

    def test_modelo_e_baixavel(self):
        resposta = self.client.get(reverse("rh:modelo_importacao"))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("attachment", resposta["Content-Disposition"])

    def test_tela_de_folha_abre(self):
        resposta = self.client.get(reverse("rh:exportar_folha"))
        self.assertEqual(resposta.status_code, 200)

    def test_download_da_folha_traz_o_aviso_de_layout(self):
        resposta = self.client.get(
            reverse("rh:baixar_folha"),
            {"data_inicio": "2026-07-01", "data_fim": "2026-07-31", "layout": "dominio"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["X-Kronus-Layout"], "nao-validado-em-homologacao")
        self.assertIn("attachment", resposta["Content-Disposition"])

    def test_layout_invalido_no_download_e_recusado(self):
        resposta = self.client.get(
            reverse("rh:baixar_folha"), {"layout": "nao-existe"}
        )
        self.assertEqual(resposta.status_code, 302)

    def test_tela_de_equipamentos_abre(self):
        resposta = self.client.get(reverse("rh:equipamentos"))
        self.assertEqual(resposta.status_code, 200)

    def test_rh_so_ve_os_proprios_equipamentos(self):
        from apps.totem.models import Totem

        outra = Empresa.objects.create(
            cliente=self.cliente, razao_social="Beta", cnpj="11222333000343"
        )
        Totem.objects.create(identificador="MEU-01", empresa=self.empresa)
        Totem.objects.create(identificador="ALHEIO-01", empresa=outra)

        resposta = self.client.get(reverse("rh:equipamentos"))
        conteudo = resposta.content.decode()
        self.assertIn("MEU-01", conteudo)
        self.assertNotIn("ALHEIO-01", conteudo)


# ══════════════════════════════════════════════════════════════
# Páginas públicas de documentação (Fase 6)
# ══════════════════════════════════════════════════════════════
class DocumentacaoPublicaTests(TestCase):
    """
    O guia é público de propósito: quem avalia a integração costuma ser
    o desenvolvedor do ERP do cliente, que não tem — e não deveria
    precisar de — uma conta no Kronus para ler a documentação.
    """

    def test_guia_abre_sem_autenticacao(self):
        resposta = self.client.get(reverse("api:guia"))
        self.assertEqual(resposta.status_code, 200)

    def test_guia_explica_a_sincronizacao_por_nsr(self):
        conteudo = self.client.get(reverse("api:guia")).content.decode()
        self.assertIn("nsr_maior_que", conteudo)
        self.assertIn("X-Kronus-Signature", conteudo)

    def test_landing_aponta_para_a_documentacao(self):
        conteudo = self.client.get(reverse("landing:index")).content.decode()
        self.assertIn(reverse("api:guia"), conteudo)


# ══════════════════════════════════════════════════════════════
# Segurança de produção (Fase 6 — deploy)
# ══════════════════════════════════════════════════════════════
class SegurancaProducaoTests(TestCase):
    """
    Os cabeçalhos de segurança estavam **configurados e inertes**: o
    `production.py` declarava a CSP e apontava para o middleware, mas o
    middleware nunca entrou em `MIDDLEWARE`. Configuração que não é
    aplicada é pior que ausência — dá a impressão de proteção.
    """

    CSP = {
        "CSP_DEFAULT_SRC": "'self'",
        "CSP_IMG_SRC": "'self' data:",
        "CSP_SCRIPT_SRC": "'self' 'unsafe-inline'",
        "CSP_STYLE_SRC": "'self'",
        "CSP_FONT_SRC": "'self'",
        "CSP_CONNECT_SRC": "'self'",
    }

    def test_middleware_esta_instalado(self):
        from django.conf import settings

        self.assertIn(
            "apps.core.middleware.SecurityHeadersMiddleware", settings.MIDDLEWARE
        )

    def test_aplica_csp_quando_configurada(self):
        with self.settings(**self.CSP):
            resposta = self.client.get(reverse("api:guia"))
        politica = resposta["Content-Security-Policy"]
        self.assertIn("default-src 'self'", politica)
        self.assertIn("frame-ancestors 'none'", politica)
        self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")

    def test_totem_ganha_permissao_para_blob(self):
        """A câmera e o Service Worker do totem usam blob: — sem isso o quiosque quebra."""
        from apps.totem.models import Totem
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano

        plano = Plano.objects.create(nome="P", slug="p")
        cliente = Cliente.objects.create(
            razao_social="C", cnpj="11222333000181", plano=plano, email_contato="c@c.com"
        )
        empresa = Empresa.objects.create(
            cliente=cliente, razao_social="E", cnpj="11222333000262"
        )
        totem = Totem.objects.create(identificador="T-01", empresa=empresa)

        with self.settings(**self.CSP):
            resposta = self.client.get(f"/totem/{totem.token_acesso}/")
        politica = resposta["Content-Security-Policy"]
        self.assertIn("blob:", politica)
        self.assertIn("worker-src", politica)

    def test_fica_inerte_sem_configuracao_de_csp(self):
        """Em dev e teste o middleware não deve inventar política."""
        resposta = self.client.get(reverse("api:guia"))
        self.assertNotIn("Content-Security-Policy", resposta)


class HasherDeSenhaTests(TestCase):
    def test_argon2_e_o_primeiro_hasher_fora_dos_testes(self):
        """
        O settings de teste troca por MD5 para ganhar velocidade; o que
        vale em produção está no `base.py`, e é ele que este teste lê.
        """
        import importlib

        base = importlib.import_module("config.settings.base")
        self.assertEqual(
            base.PASSWORD_HASHERS[0],
            "django.contrib.auth.hashers.Argon2PasswordHasher",
        )

    def test_argon2_esta_instalado(self):
        """Sem o pacote, o primeiro hash de senha em produção explodiria."""
        import argon2  # noqa: F401
