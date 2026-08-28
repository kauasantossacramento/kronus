"""
Kronus — testes dos arquivos fiscais AFD e AEJ (Fase 4).

São os arquivos que o Auditor-Fiscal do Trabalho exige. O que a
fiscalização checa — continuidade do NSR, consistência do trailer,
tamanho fixo de linha — é exatamente o que estes testes checam.

**Fora do escopo:** conformidade das larguras de campo contra o Anexo
oficial da Portaria 671/2021. Isso exige o documento normativo e é um
débito registrado no `SESSION_LOG_004`.
"""
from datetime import date, datetime, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoEscala, TipoUsuario
from apps.master.models import Plano
from apps.ponto.models import EscalaTrabalho, RegistroPonto
from apps.ponto.services import AjustePontoService, RegistroPontoService
from apps.relatorios.aej import AEJGenerator
from apps.relatorios.aej import LAYOUT as LAYOUT_AEJ
from apps.relatorios.afd import (
    LAYOUT as LAYOUT_AFD,
    tipo_da_linha,
    AFDGenerator,
    fatiar_linha,
    ler_campo,
    posicao_do_campo,
    tamanho_da_linha,
)
from apps.rh.models import Colaborador

User = get_user_model()
SENHA = "senha-forte-123"

JORNADA = {
    "dias": {
        str(d): {"entrada": "08:00", "intervalo_inicio": "12:00",
                 "intervalo_fim": "13:00", "saida": "17:00"}
        for d in range(5)
    }
}


class BaseFiscalTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(nome="Teste", slug="teste", max_colaboradores=50)
        cls.cliente = Cliente.objects.create(
            razao_social="Grupo Teste Ltda",
            cnpj="11222333000181",
            plano=cls.plano,
            email_contato="c@c.com",
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente,
            razao_social="Comércio Ação e Serviços Ltda",  # acentos de propósito
            cnpj="11222333000262",
            cidade="Valença",
            uf="BA",
        )
        cls.escala = EscalaTrabalho.objects.create(
            empresa=cls.empresa, nome="Comercial", tipo=TipoEscala.FIXA,
            jornada_config=JORNADA, carga_diaria_min=480,
        )
        cls.joao = Colaborador.objects.create(
            empresa=cls.empresa, cpf="52998224725", nome_completo="João da Silva Souza",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
            escala=cls.escala, matricula="0001", cargo="Operador",
        )
        cls.maria = Colaborador.objects.create(
            empresa=cls.empresa, cpf="15350946056", nome_completo="Maria Aparecida Lima",
            data_nascimento=date(1985, 1, 1), data_admissao=date(2024, 1, 1),
            escala=cls.escala, matricula="0002",
        )

    def bater(self, colaborador, dia, *horas):
        with self.captureOnCommitCallbacks(execute=True):
            for hora in horas:
                h, m = (int(p) for p in hora.split(":"))
                RegistroPontoService.registrar(
                    colaborador=colaborador,
                    momento=timezone.make_aware(datetime.combine(dia, time(h, m))),
                    validar_intervalo=False,
                )

    def jornada_padrao(self, colaborador, dia):
        self.bater(colaborador, dia, "08:00", "12:00", "13:00", "17:00")


# ══════════════════════════════════════════════════════════════
# Layout declarativo
# ══════════════════════════════════════════════════════════════
class LayoutTests(TestCase):
    def test_todo_tipo_tem_campos(self):
        for tipo, campos in LAYOUT_AFD.items():
            self.assertTrue(campos, f"tipo {tipo} sem campos")

    def test_tamanhos_conferem_com_o_anexo_v(self):
        """
        Os tamanhos de linha do Anexo V da Portaria 671/2021, conferidos
        contra a integra publicada no DOU (portaria-359094139).

        Este e o teste que trava a conformidade: qualquer mexida em
        `LAYOUT` que desloque um campo quebra aqui.
        """
        oficial = {
            "1": 302, "2": 331, "3": 50, "4": 73,
            "5": 118, "6": 36, "7": 137, "9": 64, "A": 100,
        }
        for tipo, esperado in oficial.items():
            self.assertEqual(
                tamanho_da_linha(tipo), esperado,
                f"registro tipo {tipo}: {tamanho_da_linha(tipo)} posicoes, "
                f"o Anexo V especifica {esperado}",
            )

    def test_registros_comuns_trazem_nsr_e_tipo_no_inicio(self):
        """
        Vale para 1 a 7 — mas **nao** para o trailer, que comeca com
        "999999999" e leva o tipo na ultima posicao, nem para a linha de
        assinatura, que nao tem nem NSR nem tipo.
        """
        for tipo in ("1", "2", "3", "4", "5", "6", "7"):
            campos = LAYOUT_AFD[tipo]
            self.assertEqual(campos[0].nome, "nsr")
            self.assertEqual(campos[0].tamanho, 9)
            self.assertEqual(campos[1].nome, "tipo")
            self.assertEqual(campos[1].tamanho, 1)

    def test_posicao_derivada_do_layout(self):
        self.assertEqual(posicao_do_campo("7", "nsr"), (0, 9))
        self.assertEqual(posicao_do_campo("7", "tipo"), (9, 10))
        inicio, fim = posicao_do_campo("7", "hash")
        self.assertEqual(fim - inicio, 64)

    def test_campo_inexistente_falha_alto(self):
        with self.assertRaises(KeyError):
            posicao_do_campo("7", "campo_que_nao_existe")

    def test_numerico_alinha_a_direita_com_zeros(self):
        campo = next(c for c in LAYOUT_AFD["7"] if c.nome == "nsr")
        self.assertEqual(campo.formatar(42), "000000042")

    def test_texto_alinha_a_esquerda_com_espacos(self):
        campo = next(c for c in LAYOUT_AFD["1"] if c.nome == "razao_social")
        self.assertEqual(campo.formatar("ACME").rstrip(), "ACME")
        self.assertTrue(campo.formatar("ACME").startswith("ACME"))

    def test_valor_longo_e_truncado_sem_estourar_a_linha(self):
        """Um campo longo demais deslocaria todos os seguintes."""
        campo = next(c for c in LAYOUT_AFD["1"] if c.nome == "razao_social")
        self.assertEqual(len(campo.formatar("X" * 500)), campo.tamanho)


# ══════════════════════════════════════════════════════════════
# AFD
# ══════════════════════════════════════════════════════════════
class AFDTests(BaseFiscalTestCase):
    def setUp(self):
        self.dia = date(2026, 8, 24)  # segunda
        self.jornada_padrao(self.joao, self.dia)
        self.jornada_padrao(self.maria, self.dia)
        self.gerador = AFDGenerator(self.empresa, self.dia, self.dia)

    def linhas(self, gerador=None):
        conteudo = (gerador or self.gerador).gerar()
        return [linha for linha in conteudo.split("\r\n") if linha]

    def test_arquivo_tem_cabecalho_trailer_e_assinatura(self):
        """
        A ordem oficial e: cabecalho, registros, trailer e — por ultimo —
        a linha de assinatura digital de 100 posicoes. O trailer nao e a
        ultima linha do arquivo.
        """
        linhas = self.linhas()
        self.assertEqual(tipo_da_linha(linhas[0]), "1")
        self.assertEqual(tipo_da_linha(linhas[-2]), "9")
        self.assertEqual(len(linhas[-1]), 100)

    def test_toda_linha_tem_o_tamanho_do_seu_tipo(self):
        for linha in self.linhas():
            self.assertEqual(len(linha), tamanho_da_linha(tipo_da_linha(linha)))

    def test_uma_linha_tipo_7_por_marcacao(self):
        marcacoes = [linha for linha in self.linhas() if tipo_da_linha(linha) == "7"]
        self.assertEqual(len(marcacoes), 8)  # 2 colaboradores x 4 batidas

    def test_um_registro_tipo_5_por_empregado(self):
        empregados = [linha for linha in self.linhas() if tipo_da_linha(linha) == "5"]
        self.assertEqual(len(empregados), 2)

    def test_nsr_e_continuo_e_ordenado(self):
        nsrs = [int(l[:9]) for l in self.linhas() if tipo_da_linha(l) == "7"]
        self.assertEqual(nsrs, sorted(nsrs))
        self.assertEqual(nsrs, list(range(nsrs[0], nsrs[-1] + 1)))

    def test_marcacao_traz_cpf_e_hash(self):
        linha = next(l for l in self.linhas() if tipo_da_linha(l) == "7")
        campos = fatiar_linha(linha)
        # Campo de 12 posicoes para um CPF de 11 digitos: zero a
        # esquerda, como o layout declara (tipo N).
        self.assertIn(
            campos["cpf"], {f"0{self.joao.cpf}", f"0{self.maria.cpf}"}
        )
        self.assertEqual(len(campos["hash"]), 64)

    def test_data_hora_em_iso_com_fuso(self):
        linha = next(l for l in self.linhas() if tipo_da_linha(l) == "7")
        valor = ler_campo(linha, "7", "data_hora_marcacao")
        # Anexo V, item 6.7: os segundos sao fixos em "00" e o fuso vem
        # sem dois-pontos.
        self.assertRegex(valor, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00[+-]\d{4}$")

    def test_acentos_sao_removidos(self):
        """Sistemas legados leem o AFD como ASCII de largura fixa."""
        cabecalho = self.linhas()[0]
        razao = ler_campo(cabecalho, "1", "razao_social")
        self.assertIn("Comercio Acao", razao)
        self.assertNotIn("ç", razao)

    def test_gerar_e_idempotente(self):
        """Gerar duas vezes precisa produzir exatamente o mesmo arquivo."""
        primeiro = self.gerador.gerar()
        segundo = self.gerador.gerar()
        self.assertEqual(primeiro, segundo)

    def test_trailer_bate_com_o_conteudo(self):
        linhas = self.linhas()
        trailer = linhas[-2]   # a ultima e a assinatura
        marcacoes = sum(1 for l in linhas if tipo_da_linha(l) == "7")
        self.assertEqual(int(ler_campo(trailer, "9", "qtd_tipo_7")), marcacoes)
        self.assertEqual(int(ler_campo(trailer, "9", "qtd_tipo_5")), 2)

    def test_verificacao_aprova_arquivo_integro(self):
        resultado = self.gerador.verificar()
        self.assertTrue(resultado["valido"], resultado["problemas"])
        self.assertEqual(resultado["marcacoes"], 8)

    def test_verificacao_e_repetivel(self):
        """verificar() chama gerar() — não pode corromper o estado."""
        for _ in range(3):
            self.assertTrue(self.gerador.verificar()["valido"])

    def test_registro_cancelado_permanece_no_arquivo(self):
        """
        Um ajuste não apaga a marcação original do AFD: omiti-la abriria
        uma lacuna de NSR e invalidaria o arquivo.
        """
        rh = User.objects.create_user(
            email="rh@t.com", password=SENHA, nome_completo="RH",
            tipo=TipoUsuario.RH, cliente=self.cliente,
        )
        registro = RegistroPonto.objects.filter(colaborador=self.joao).first()
        AjustePontoService.cancelar(
            registro=registro, justificativa="Batida em duplicidade", executado_por=rh
        )

        gerador = AFDGenerator(self.empresa, self.dia, self.dia)
        nsrs = [int(l[:9]) for l in self.linhas(gerador) if tipo_da_linha(l) == "7"]
        self.assertIn(registro.nsr, nsrs)
        self.assertTrue(gerador.verificar()["valido"])

    def test_codificacao_iso_8859_1(self):
        conteudo = self.gerador.gerar_bytes()
        self.assertIsInstance(conteudo, bytes)
        conteudo.decode("iso-8859-1")  # não levanta

    def test_quebra_de_linha_crlf(self):
        self.assertIn(b"\r\n", self.gerador.gerar_bytes())

    def test_nome_do_arquivo_segue_a_regra_do_rep_p(self):
        """
        Anexo V, item 19.3: "AFD" + registro no INPI + CNPJ/CPF do
        empregador + "REP_P". Sem registro no INPI ainda, o lugar dele
        no nome fica marcado — o arquivo nao finge ter um.
        """
        nome = self.gerador.nome_arquivo()
        self.assertTrue(nome.startswith("AFD"))
        self.assertIn("11222333000262", nome)
        self.assertIn("REP_P", nome)
        self.assertTrue(nome.endswith(".txt"))

    def test_periodo_vazio_gera_arquivo_valido(self):
        vazio = AFDGenerator(self.empresa, date(2020, 1, 1), date(2020, 1, 2))
        resultado = vazio.verificar()
        self.assertTrue(resultado["valido"], resultado["problemas"])
        self.assertEqual(resultado["marcacoes"], 0)


# ══════════════════════════════════════════════════════════════
# AEJ
# ══════════════════════════════════════════════════════════════
class AEJTests(BaseFiscalTestCase):
    def setUp(self):
        self.inicio = date(2026, 8, 24)
        self.fim = date(2026, 8, 26)
        self.jornada_padrao(self.joao, self.inicio)
        # Dia com hora extra
        self.bater(self.joao, date(2026, 8, 25), "08:00", "12:00", "13:00", "18:00")
        # Dia sem marcação → falta
        from apps.ponto.services import ConsolidacaoService

        ConsolidacaoService.consolidar_periodo(self.joao, self.inicio, self.fim)
        self.gerador = AEJGenerator(
            self.empresa, self.inicio, self.fim, colaboradores=[self.joao]
        )

    def linhas(self):
        return [l for l in self.gerador.gerar().split("\r\n") if l]

    def campos(self, tipo):
        """Todas as linhas de um tipo, ja fatiadas em dicionario."""
        from apps.relatorios.aej import fatiar_linha

        return [
            fatiar_linha(l) for l in self.linhas() if l.split("|")[0] == tipo
        ]

    def test_arquivo_e_delimitado_por_pipe(self):
        """
        Anexo VI, item 5: campos separados por "|", **sem** preenchimento
        e sem pipe sobrando no fim da linha. O AEJ nao e de largura fixa
        — foi exatamente o que a primeira implementacao errou.
        """
        from apps.relatorios.aej import quantidade_de_campos

        for linha in self.linhas():
            self.assertIn("|", linha)
            tipo = linha.split("|")[0]
            # A contagem de campos e o criterio, nao a ausencia de pipe
            # no fim: quando o ultimo campo do registro e opcional e sai
            # vazio, a linha termina no delimitador que separa o
            # penultimo — e isso esta correto pela regra do item 5.
            self.assertEqual(
                len(linha.split("|")), quantidade_de_campos(tipo),
                f"contagem de campos errada no tipo {tipo}: {linha!r}",
            )

    def test_ultimo_campo_preenchido_nao_deixa_pipe_sobrando(self):
        """
        Quando o ultimo campo tem conteudo, a linha nao pode terminar em
        delimitador — seria um campo extra vazio para o importador.
        """
        for linha in self.linhas():
            partes = linha.split("|")
            if partes[-1]:
                self.assertFalse(linha.endswith("|"), linha)

    def test_linhas_nao_tem_largura_fixa(self):
        """Se todas tivessem o mesmo tamanho, seria sinal de preenchimento."""
        marcacoes = [l for l in self.linhas() if l.startswith("05")]
        self.assertTrue(marcacoes)
        for linha in marcacoes:
            for campo in linha.split("|"):
                self.assertEqual(campo, campo.strip())

    def test_cabecalho_traz_empregador_e_periodo(self):
        cabecalho = self.campos("01")[0]
        self.assertEqual(cabecalho["idtEmpregador"], "11222333000262")
        self.assertEqual(cabecalho["dataInicialAej"], "2026-08-24")
        self.assertEqual(cabecalho["dataFinalAej"], "2026-08-26")
        self.assertEqual(cabecalho["versaoAej"], "001")

    def test_declara_o_rep_como_rep_p(self):
        rep = self.campos("02")[0]
        self.assertEqual(rep["tpRep"], "3")   # 3 = REP-P

    def test_declara_o_ptrp(self):
        """O Kronus e o REP-P que coleta e o PTRP que trata."""
        ptrp = self.campos("08")[0]
        self.assertEqual(ptrp["nomeProg"], "Kronus")
        self.assertTrue(ptrp["idtDesenv"])
        self.assertTrue(ptrp["emailDesenv"])

    def test_tem_registro_de_vinculo(self):
        vinculos = self.campos("03")
        self.assertEqual(len(vinculos), 1)
        self.assertEqual(vinculos[0]["cpf"], self.joao.cpf)

    def test_horario_contratual_vem_da_escala(self):
        horario = self.campos("04")[0]
        self.assertEqual(horario["hrEntrada01"], "0800")
        self.assertEqual(horario["hrSaida01"], "1200")
        self.assertEqual(horario["hrEntrada02"], "1300")
        self.assertEqual(horario["hrSaida02"], "1700")
        self.assertTrue(horario["durJornada"].isdigit())

    def test_marcacoes_alternam_entrada_e_saida(self):
        """
        O par e posicional, como na apuracao: primeira do dia e entrada,
        segunda e saida. Usar o `tipo` declarado aqui e a posicao no
        calculo produziria AEJ e espelho divergentes.
        """
        marcacoes = [m for m in self.campos("05") if m["dataHoraMarc"].startswith("2026-08-24")]
        self.assertEqual([m["tpMarc"] for m in marcacoes], ["E", "S", "E", "S"])
        self.assertEqual([m["seqEntSaida"] for m in marcacoes], ["001", "001", "002", "002"])

    def test_primeira_entrada_referencia_o_horario_contratual(self):
        """Campo obrigatorio so na primeira entrada do dia (Anexo VI)."""
        marcacoes = [m for m in self.campos("05") if m["dataHoraMarc"].startswith("2026-08-24")]
        self.assertTrue(marcacoes[0]["codHorContratual"])
        self.assertEqual(marcacoes[1]["codHorContratual"], "")

    def test_marcacao_do_rep_declara_a_fonte_original(self):
        marcacao = self.campos("05")[0]
        self.assertEqual(marcacao["fonteMarc"], "O")
        self.assertEqual(marcacao["idRepAej"], "1")

    def test_falta_gera_registro_de_ausencia(self):
        ausencias = self.campos("07")
        faltas = [a for a in ausencias if a["tipoAusenOuComp"] == "2"]
        self.assertTrue(faltas, "a falta do dia 26 nao gerou registro tipo 07")

    def test_movimento_de_banco_traz_minutos_e_sentido(self):
        movimentos = [a for a in self.campos("07") if a["tipoAusenOuComp"] == "3"]
        self.assertTrue(movimentos)
        for movimento in movimentos:
            self.assertTrue(movimento["qtMinutos"].isdigit())
            self.assertIn(movimento["tipoMovBH"], ("1", "2"))

    def test_data_hora_segue_o_formato_dh(self):
        marcacao = self.campos("05")[0]
        self.assertRegex(
            marcacao["dataHoraMarc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00[+-]\d{4}$",
        )

    def test_pipe_no_cadastro_nao_parte_o_registro(self):
        """
        Um "|" na razao social deslocaria todos os campos seguintes —
        a falha caracteristica de formato delimitado.
        """
        self.empresa.razao_social = "Aurora | Comercio"
        self.empresa.save(update_fields=["razao_social"])

        from apps.relatorios.aej import quantidade_de_campos

        cabecalho = self.linhas()[0]
        self.assertEqual(len(cabecalho.split("|")), quantidade_de_campos("01"))

    def test_gerar_e_idempotente(self):
        self.assertEqual(self.gerador.gerar(), self.gerador.gerar())

    def test_verificacao_aprova_arquivo_integro(self):
        resultado = self.gerador.verificar()
        self.assertTrue(resultado["valido"], resultado["problemas"])
        self.assertEqual(resultado["vinculos"], 1)


# ══════════════════════════════════════════════════════════════
# Interface de download
# ══════════════════════════════════════════════════════════════
class DownloadFiscalTests(BaseFiscalTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rh = User.objects.create_user(
            email="rh@teste.com", password=SENHA, nome_completo="RH",
            tipo=TipoUsuario.RH, cliente=cls.cliente,
        )
        cls.rh.empresas.set([cls.empresa])

    def setUp(self):
        self.client.login(username="rh@teste.com", password=SENHA)
        self.jornada_padrao(self.joao, date(2026, 8, 24))

    def test_tela_de_arquivos_fiscais_responde(self):
        resposta = self.client.get(reverse("relatorios:fiscais"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "AFD")
        self.assertContains(resposta, "AEJ")

    def test_download_do_afd(self):
        resposta = self.client.get(
            reverse("relatorios:afd") + "?inicio=2026-08-24&fim=2026-08-24"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("attachment", resposta["Content-Disposition"])
        self.assertIn("REP_P", resposta["Content-Disposition"])
        self.assertTrue(resposta.content)

    def test_download_do_aej(self):
        resposta = self.client.get(
            reverse("relatorios:aej") + "?inicio=2026-08-24&fim=2026-08-24"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("AEJ_", resposta["Content-Disposition"])

    def test_download_fica_na_trilha_de_auditoria(self):
        """Numa inspeção, saber quem gerou o arquivo faz parte da defesa."""
        from apps.core.models import LogAcesso

        self.client.get(reverse("relatorios:afd"))
        self.assertTrue(
            LogAcesso.objects.filter(
                acao=LogAcesso.Acao.DOWNLOAD, descricao__startswith="AFD"
            ).exists()
        )

    def test_colaborador_nao_baixa_afd(self):
        colaborador_user = User.objects.create_user(
            cpf="71428793860", password=SENHA, nome_completo="Colab",
            tipo=TipoUsuario.COLABORADOR, cliente=self.cliente,
        )
        self.client.force_login(colaborador_user)
        resposta = self.client.get(reverse("relatorios:afd"))
        self.assertEqual(resposta.status_code, 403)

    def test_exportacao_csv(self):
        resposta = self.client.get(reverse("relatorios:gerenciais_csv"))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("text/csv", resposta["Content-Type"])
        self.assertIn("João da Silva Souza", resposta.content.decode("utf-8-sig"))
