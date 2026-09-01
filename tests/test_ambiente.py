"""
Kronus — o conteudo ambiente da tela ociosa.

Uma tela ligada o dia inteiro mostrando so a logo desperdica um canal
que a empresa ja tem. Mas encher de conteudo tem custo: o que importa
— como bater o ponto, a hora, a marca — nao pode ser empurrado para
fora por um enfeite.
"""
from decimal import Decimal

from django.test import TestCase

from apps.clientes.ambiente import (
    FraseAmbiente,
    ImagemAmbiente,
    Periodo,
    periodo_de,
)
from apps.clientes.ambiente_servico import conteudo_para, esquecer


class PeriodoTests(TestCase):
    """
    Os cortes seguem o dia de trabalho, nao o relogio astronomico.
    """

    def test_manha_da_madrugada_ao_meio_dia(self):
        self.assertEqual(periodo_de(5), Periodo.MANHA)
        self.assertEqual(periodo_de(9), Periodo.MANHA)
        self.assertEqual(periodo_de(11), Periodo.MANHA)

    def test_tarde_ate_as_dezoito(self):
        self.assertEqual(periodo_de(12), Periodo.TARDE)
        self.assertEqual(periodo_de(17), Periodo.TARDE)

    def test_a_noite_e_o_resto(self):
        """
        Definir "das 18h as 5h" exigiria tratar a virada da meia-noite
        como caso especial — e caso especial em regra de horario e onde
        nasce o erro que so aparece as 23h59.
        """
        for hora in (18, 21, 23, 0, 3, 4):
            self.assertEqual(periodo_de(hora), Periodo.NOITE, f"hora {hora}")

    def test_todas_as_24_horas_tem_periodo(self):
        for hora in range(24):
            self.assertIn(periodo_de(hora), Periodo.values)


class BaseAmbiente(TestCase):
    def setUp(self):
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano

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
        for i in range(6):
            FraseAmbiente.objects.create(
                periodo=Periodo.MANHA, texto=f"Bom dia {i}",
                tipo=FraseAmbiente.Tipo.SAUDACAO,
            )
        for i in range(3):
            FraseAmbiente.objects.create(
                periodo=Periodo.MANHA, texto=f"Beba água {i}",
                tipo=FraseAmbiente.Tipo.SAUDE,
            )
        esquecer()

    def _imagem(self, periodo=Periodo.MANHA, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile

        dados = extra.pop("dados", b"\x89PNG\r\n\x1a\n" + b"0" * 40)
        return ImagemAmbiente.objects.create(
            periodo=periodo,
            imagem=SimpleUploadedFile("f.png", dados, content_type="image/png"),
            fonte="https://exemplo.test/foto",
            licenca=extra.pop("licenca", "CC0"),
            **extra,
        )


class ConteudoTests(BaseAmbiente):
    def test_entrega_frases_do_periodo(self):
        c = conteudo_para(self.empresa, hora=9)
        self.assertEqual(c["periodo"], Periodo.MANHA)
        self.assertTrue(c["frases"])

    def test_a_dica_de_saude_entra_junto(self):
        """
        Uma tela que so da conselho de saude cansa; uma que nunca da
        perde a chance. Elas alternam com a saudacao.
        """
        esquecer()
        c = conteudo_para(self.empresa, hora=9)
        self.assertTrue(any("água" in f["texto"] for f in c["frases"]))

    def test_periodo_sem_frase_nao_estoura(self):
        c = conteudo_para(self.empresa, hora=22)
        self.assertEqual(c["frases"], [])

    def test_a_empresa_pode_desligar(self):
        self.empresa.telas_ambiente = False
        self.empresa.save(update_fields=["telas_ambiente"])
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9), {})

    def test_quem_quer_so_os_proprios_slides_nao_recebe_acervo(self):
        self.empresa.modo_slides = self.empresa.ModoDosSlides.SOMENTE_MEUS
        self.empresa.save(update_fields=["modo_slides"])
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9), {})

    def test_quem_quer_so_o_acervo_avisa_o_totem(self):
        self.empresa.modo_slides = self.empresa.ModoDosSlides.SOMENTE_ACERVO
        self.empresa.save(update_fields=["modo_slides"])
        esquecer()
        self.assertTrue(conteudo_para(self.empresa, hora=9)["exclusivo"])

    def test_por_padrao_soma_os_dois(self):
        """
        Quem nunca subiu slide fica com a tela vazia se o acervo nao
        entrar — por isso o padrao soma.
        """
        self.assertFalse(conteudo_para(self.empresa, hora=9)["exclusivo"])
        self.assertTrue(self.empresa.telas_ambiente)


class ImagensTests(BaseAmbiente):
    def test_entrega_a_imagem(self):
        self._imagem(autor="Fulano", licenca="Pexels License")
        esquecer()
        c = conteudo_para(self.empresa, hora=9)
        self.assertEqual(len(c["imagens"]), 1)
        self.assertIn("url", c["imagens"][0])

    def test_a_tela_nao_carrega_credito(self):
        """
        A licenca do Pexels dispensa atribuicao, e um rodape de credito
        numa tela vista de longe so tira espaco do que a pessoa precisa
        ler. A procedencia continua guardada no acervo.
        """
        img = self._imagem(autor="Fulano", licenca="Pexels License")
        esquecer()
        c = conteudo_para(self.empresa, hora=9)
        self.assertNotIn("credito", c["imagens"][0])
        # Guardada, ainda que nao exibida.
        self.assertEqual(img.autor, "Fulano")
        self.assertEqual(img.licenca, "Pexels License")

    def test_a_empresa_pode_ocultar_uma_imagem(self):
        """
        Ocultar, e nao apagar: o acervo serve a todos os clientes, e um
        cliente que nao gosta de uma foto nao pode tira-la dos outros.
        """
        from apps.clientes.ambiente import ImagemOcultaPelaEmpresa

        img = self._imagem()
        outra = self._imagem()
        ImagemOcultaPelaEmpresa.objects.create(empresa=self.empresa, imagem=img)
        esquecer()

        c = conteudo_para(self.empresa, hora=9)
        urls = [i["url"] for i in c["imagens"]]
        self.assertEqual(len(urls), 1)
        self.assertIn(outra.imagem.url, urls)

    def test_imagem_de_outro_periodo_nao_aparece(self):
        self._imagem(periodo=Periodo.NOITE)
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9)["imagens"], [])

    def test_imagem_inativa_nao_aparece(self):
        img = self._imagem()
        img.ativo = False
        img.save(update_fields=["ativo"])
        esquecer()
        self.assertEqual(conteudo_para(self.empresa, hora=9)["imagens"], [])


class ProcedenciaTests(TestCase):
    """
    A procedencia e guardada mesmo quando a licenca dispensa credito.

    Os campos deixaram de ser obrigatorios porque o importador preenche
    sozinho, e exigir digitacao numa importacao automatica so criaria
    caminho para preencher errado. Mas o registro continua: um ano
    depois, "de onde veio esta foto?" precisa ter resposta.
    """

    def test_o_acervo_guarda_de_onde_veio(self):
        campos = {f.name for f in ImagemAmbiente._meta.get_fields()}
        self.assertIn("fonte", campos)
        self.assertIn("licenca", campos)
        self.assertIn("autor", campos)

    def test_guarda_o_id_da_origem_para_nao_repetir(self):
        """
        Sem ele, cada atualizacao semanal traria as mesmas fotos de
        novo — e em um mes a tela repetiria a mesma paisagem seis vezes.
        """
        self.assertIn(
            "id_externo", {f.name for f in ImagemAmbiente._meta.get_fields()}
        )


class ChegaNaPaginaTests(TestCase):
    """
    O conteudo precisa chegar na PAGINA, e nao so na API.

    Bug real: a API entregava tudo certo e o totem nao mostrava nada. O
    JS le a configuracao renderizada no proprio HTML — a resposta da API
    so chega na primeira atualizacao de configuracao, e ate la a tela
    ficava vazia.

    Nenhum teste pegou porque todos olhavam o servico e a API, que eram
    justamente as duas partes que funcionavam.
    """

    def setUp(self):
        from decimal import Decimal

        from apps.clientes.ambiente import FraseAmbiente, Periodo
        from apps.clientes.ambiente_servico import esquecer
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.totem.models import Totem

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
        self.totem = Totem.objects.create(empresa=self.empresa, apelido="T")
        for periodo in Periodo.values:
            FraseAmbiente.objects.create(
                periodo=periodo, texto=f"Frase de {periodo}",
                tipo=FraseAmbiente.Tipo.SAUDACAO,
            )
        esquecer()

    def _pagina(self):
        return self.client.get(
            f"/totem/{self.totem.token_acesso}/"
        ).content.decode()

    def test_a_pagina_carrega_o_bloco_ambiente(self):
        pagina = self._pagina()
        self.assertIn("ambiente:", pagina)
        self.assertIn("Frase de", pagina)

    def test_desligado_a_pagina_nao_traz_frase(self):
        from apps.clientes.ambiente_servico import esquecer

        self.empresa.telas_ambiente = False
        self.empresa.save(update_fields=["telas_ambiente"])
        esquecer()
        self.assertNotIn("Frase de", self._pagina())

    def test_a_pagina_continua_de_pe_sem_acervo(self):
        """
        Sem frase e sem imagem o totem tem de abrir igual: enfeite que
        derruba o quiosque troca o essencial pelo acessorio.
        """
        from apps.clientes.ambiente import FraseAmbiente
        from apps.clientes.ambiente_servico import esquecer

        FraseAmbiente.objects.all().delete()
        esquecer()
        self.assertIn("ambiente:", self._pagina())


class ClaridadeChegaNaPaginaTests(TestCase):
    """
    A marca so escurece se a pagina souber que a foto e clara.

    Quarta vez do mesmo erro nesta sessao: o servico e a API foram
    atualizados, e o template da pagina — que e de onde o JS le — ficou
    para tras. O dado existia e nao chegava.
    """

    def setUp(self):
        from decimal import Decimal

        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.clientes.ambiente import ImagemAmbiente, Periodo
        from apps.clientes.ambiente_servico import esquecer
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.totem.models import Totem

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
        self.totem = Totem.objects.create(empresa=self.empresa, apelido="T")
        for periodo in Periodo.values:
            ImagemAmbiente.objects.create(
                periodo=periodo,
                imagem=SimpleUploadedFile(
                    "f.png", b"\x89PNG\r\n\x1a\n" + b"0" * 40,
                    content_type="image/png",
                ),
                fonte="https://x.test", licenca="Pexels License",
                clara=True,
            )
        esquecer()

    def test_a_pagina_informa_que_a_foto_e_clara(self):
        pagina = self.client.get(
            f"/totem/{self.totem.token_acesso}/"
        ).content.decode()
        self.assertIn('"clara": true', pagina)

    def test_foto_escura_chega_como_falsa(self):
        from apps.clientes.ambiente import ImagemAmbiente
        from apps.clientes.ambiente_servico import esquecer

        ImagemAmbiente.objects.update(clara=False)
        esquecer()
        pagina = self.client.get(
            f"/totem/{self.totem.token_acesso}/"
        ).content.decode()
        self.assertIn('"clara": false', pagina)
        self.assertNotIn('"clara": true', pagina)


class AutoriaDasFrasesTests(TestCase):
    """
    Frase assinada carrega peso que anonima nao carrega.

    A mesma ideia dita por Seneca ha dois mil anos le diferente de um
    aviso de mural — e foi a falta disso que fez as duas primeiras
    versoes soarem a conselho de calendario.
    """

    def test_a_frase_leva_o_autor_junto(self):
        from apps.clientes.ambiente import FraseAmbiente, Periodo

        FraseAmbiente.objects.create(
            periodo=Periodo.MANHA, tipo=FraseAmbiente.Tipo.MOTIVACAO,
            texto="Enquanto adiamos, a vida passa.", autor="Sêneca",
        )
        from apps.clientes.ambiente_servico import conteudo_para, esquecer
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from decimal import Decimal

        plano = Plano.objects.create(
            nome="P", slug="p", max_empresas=3, max_colaboradores=50,
            preco_mensal=Decimal("100"),
        )
        cliente = Cliente.objects.create(
            razao_social="C LTDA", cnpj="11222333000181",
            email_contato="c@t.com", plano=plano,
        )
        empresa = Empresa.objects.create(
            cliente=cliente, razao_social="E LTDA", cnpj="60746948000112",
        )
        esquecer()
        frases = conteudo_para(empresa, hora=9)["frases"]
        self.assertEqual(frases[0]["autor"], "Sêneca")
        self.assertIn("adiamos", frases[0]["texto"])

    def test_a_dica_de_saude_nao_tem_autor(self):
        """Conselho pratico assinado por alguem soaria a citacao falsa."""
        from apps.clientes.ambiente import FraseAmbiente

        campo = FraseAmbiente._meta.get_field("autor")
        self.assertTrue(campo.blank)

    def test_o_acervo_so_cita_dominio_publico(self):
        """
        Citar quem morreu ontem num produto comercial e problema de
        direito autoral, e o totem esta na parede do cliente.
        """
        from apps.clientes.management.commands.semear_ambiente import (
            MANHA, NOITE, TARDE,
        )

        livres = {
            "", "Sêneca", "Marco Aurélio", "Epicteto", "Sócrates",
            "Lao-Tsé", "Confúcio", "Fernando Pessoa",
        }
        for bloco in (MANHA, TARDE, NOITE):
            for _, _, autor in bloco:
                self.assertIn(autor, livres, f"autor não verificado: {autor}")


class VariedadeAoLongoDaSemanaTests(TestCase):
    """
    Dias diferentes tem de trazer conjuntos diferentes.

    Com `random` solto, dois dias seguidos podiam cair quase no mesmo
    recorte — sorte nao garante variedade. Semeando pelo dia, cada dia
    da semana recebe o seu, e dentro do mesmo dia o conjunto e estavel:
    o totem nao troca o elenco a cada cinco minutos, o que faria a mesma
    pessoa ver frases diferentes na entrada e na saida do almoco sem
    entender por que.
    """

    def setUp(self):
        from decimal import Decimal

        from apps.clientes.ambiente import FraseAmbiente, Periodo
        from apps.clientes.ambiente_servico import esquecer
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano

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
        # Acervo grande o bastante para o sorteio ter o que variar.
        for i in range(20):
            FraseAmbiente.objects.create(
                periodo=Periodo.MANHA, texto=f"Frase {i}",
                tipo=FraseAmbiente.Tipo.MOTIVACAO,
            )
        for i in range(8):
            FraseAmbiente.objects.create(
                periodo=Periodo.MANHA, texto=f"Saúde {i}",
                tipo=FraseAmbiente.Tipo.SAUDE,
            )
        esquecer()

    def _do_dia(self, dia):
        from apps.clientes.ambiente_servico import conteudo_para

        return [
            f["texto"]
            for f in conteudo_para(self.empresa, hora=9, dia=dia)["frases"]
        ]

    def test_dias_diferentes_trazem_conjuntos_diferentes(self):
        from datetime import date

        semana = [self._do_dia(date(2026, 9, d)) for d in range(7, 14)]
        # Nenhum par de dias da semana pode sair identico.
        for i in range(len(semana)):
            for j in range(i + 1, len(semana)):
                self.assertNotEqual(
                    semana[i], semana[j],
                    f"dias {i} e {j} trouxeram o mesmo conjunto",
                )

    def test_o_mesmo_dia_sempre_traz_o_mesmo_conjunto(self):
        """
        Estavel dentro do dia: quem passa de manha e a tarde ve o mesmo
        elenco, e nao se pergunta se a tela quebrou.
        """
        from datetime import date

        from apps.clientes.ambiente_servico import esquecer

        dia = date(2026, 9, 7)
        primeiro = self._do_dia(dia)
        esquecer()
        self.assertEqual(primeiro, self._do_dia(dia))

    def test_a_semana_seguinte_nao_repete_a_anterior(self):
        from datetime import date

        self.assertNotEqual(
            self._do_dia(date(2026, 9, 7)), self._do_dia(date(2026, 9, 14))
        )


class PeriodoForcadoTests(TestCase):
    """
    Conferir a tela da noite as 10h, num totem so.

    A alternativa era mexer no relogio do servidor — que afetaria os
    registros de ponto. Preco errado para ver uma tela.
    """

    def setUp(self):
        from decimal import Decimal

        from apps.clientes.ambiente import FraseAmbiente, Periodo
        from apps.clientes.ambiente_servico import esquecer
        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano
        from apps.totem.models import Totem

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
        self.teste = Totem.objects.create(empresa=self.empresa, apelido="TESTE")
        self.producao = Totem.objects.create(empresa=self.empresa, apelido="PROD")
        for periodo in Periodo.values:
            FraseAmbiente.objects.create(
                periodo=periodo, texto=f"marcador{periodo}",
                tipo=FraseAmbiente.Tipo.SAUDACAO,
            )
        esquecer()

    def test_o_totem_marcado_recebe_o_periodo_forcado(self):
        from apps.clientes.ambiente_servico import conteudo_para

        c = conteudo_para(self.empresa, hora=9, periodo_forcado="noite")
        self.assertEqual(c["periodo"], "noite")

    def test_sem_forcar_segue_o_relogio(self):
        from apps.clientes.ambiente_servico import conteudo_para

        self.assertEqual(conteudo_para(self.empresa, hora=9)["periodo"], "manha")

    def test_periodo_invalido_volta_para_o_relogio(self):
        """Um valor digitado errado no painel nao pode apagar a tela."""
        from apps.clientes.ambiente_servico import conteudo_para

        c = conteudo_para(self.empresa, hora=9, periodo_forcado="madrugada")
        self.assertEqual(c["periodo"], "manha")

    def test_um_totem_forcado_nao_afeta_o_outro(self):
        """
        A conferencia acontece num equipamento; os outros continuam
        seguindo a hora, com gente batendo ponto neles.

        A hora e fixada em 9h: sem isso o teste passava de dia e
        falhava de madrugada, quando o relogio ja aponta "noite" e os
        dois totens mostram a mesma coisa por coincidencia.
        """
        from datetime import datetime
        from unittest.mock import patch

        from django.utils import timezone as tz

        self.teste.periodo_forcado = "noite"
        self.teste.save(update_fields=["periodo_forcado"])

        manha = tz.make_aware(datetime(2026, 9, 7, 9, 0))
        # `timezone` e importado dentro da funcao da view, entao o alvo
        # do patch e o modulo de origem.
        with patch("django.utils.timezone.localtime", return_value=manha):
            pagina_teste = self.client.get(
                f"/totem/{self.teste.token_acesso}/"
            ).content.decode()
            pagina_prod = self.client.get(
                f"/totem/{self.producao.token_acesso}/"
            ).content.decode()

        self.assertIn("marcadornoite", pagina_teste)
        self.assertIn("marcadormanha", pagina_prod)
        self.assertNotIn("marcadornoite", pagina_prod)
