"""
Kronus — o comando que limpa registros de ponto para novos testes.

Apagar ponto e a operacao mais perigosa do sistema: e prova trabalhista.
O que estes testes guardam nao e o "apagou?", e sim tudo o que precisa
acontecer junto para o que sobra continuar valendo.
"""
import json
from datetime import date, timedelta
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import MetodoRegistro
from apps.master.models import Plano
from apps.ponto.models import RegistroPonto
from apps.ponto.services import RegistroPontoService
from apps.rh.models import Colaborador


class BaseReset(TestCase):
    def setUp(self):
        plano = Plano.objects.create(nome="P", slug="p", max_colaboradores=50)
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa Matriz", cnpj="45997418000234",
        )
        self.outra = Empresa.objects.create(
            cliente=self.cliente, razao_social="Beta Filial", cnpj="34028316000103",
        )
        self.pessoa = self._pessoa(self.empresa, "Ana", "52998224725")
        self.vizinha = self._pessoa(self.outra, "Bia", "11144477735")

    def _pessoa(self, empresa, nome, cpf):
        return Colaborador.objects.create(
            empresa=empresa, nome_completo=nome, cpf=cpf,
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )

    def bater(self, pessoa, quantos=3):
        base = timezone.localtime()
        for i in range(quantos):
            RegistroPontoService.registrar(
                colaborador=pessoa,
                metodo=MetodoRegistro.WEB,
                momento=base - timedelta(hours=quantos - i),
                validar_intervalo=False,
            )

    def rodar(self, *args, **kwargs):
        saida = StringIO()
        call_command("resetar_pontos", *args, stdout=saida, **kwargs)
        return saida.getvalue()


class SemConfirmarTests(BaseReset):
    def test_sem_o_sinalizador_nada_e_apagado(self):
        self.bater(self.pessoa)
        antes = RegistroPonto.objects.count()

        saida = self.rodar("--empresa", str(self.empresa.pk))

        self.assertEqual(RegistroPonto.objects.count(), antes)
        self.assertIn("Nada foi alterado", saida)

    def test_mostra_o_que_seria_apagado(self):
        self.bater(self.pessoa, 4)
        saida = self.rodar("--empresa", str(self.empresa.pk))
        self.assertIn("registros de ponto : 4", saida)


class ResetTests(BaseReset):
    def test_apaga_e_zera_o_nsr(self):
        self.bater(self.pessoa, 3)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.nsr_atual, 3)

        self.rodar("--empresa", str(self.empresa.pk), "--confirmar")

        self.empresa.refresh_from_db()
        self.assertEqual(RegistroPonto.objects.filter(empresa=self.empresa).count(), 0)
        self.assertEqual(
            self.empresa.nsr_atual, 0,
            "sem zerar, a proxima batida nasce com uma lacuna que o AFD acusa",
        )

    def test_a_proxima_batida_recomeca_a_corrente(self):
        """
        O primeiro registro de uma empresa guarda hash anterior vazio.
        Se sobrasse qualquer coisa atras, o novo primeiro apontaria para
        um registro que nao existe mais.
        """
        self.bater(self.pessoa, 2)
        self.rodar("--empresa", str(self.empresa.pk), "--confirmar")

        self.bater(self.pessoa, 1)
        novo = RegistroPonto.objects.get(empresa=self.empresa)
        self.assertEqual(novo.nsr, 1)
        self.assertEqual(novo.hash_anterior, "")

    def test_nao_encosta_em_outra_empresa(self):
        self.bater(self.pessoa, 2)
        self.bater(self.vizinha, 2)

        self.rodar("--empresa", str(self.empresa.pk), "--confirmar")

        self.assertEqual(RegistroPonto.objects.filter(empresa=self.empresa).count(), 0)
        self.assertEqual(RegistroPonto.objects.filter(empresa=self.outra).count(), 2)
        self.outra.refresh_from_db()
        self.assertEqual(self.outra.nsr_atual, 2)

    def test_guarda_copia_antes_de_apagar(self):
        import tempfile

        self.bater(self.pessoa, 2)
        with tempfile.TemporaryDirectory() as pasta:
            self.rodar(
                "--empresa", str(self.empresa.pk), "--confirmar", "--destino", pasta
            )
            arquivos = list(__import__("pathlib").Path(pasta).glob("*.json"))
            self.assertEqual(len(arquivos), 1)
            conteudo = json.loads(arquivos[0].read_text(encoding="utf-8"))

        self.assertEqual(len(conteudo["registros"]), 2)
        self.assertEqual(conteudo["registros"][0]["nsr"], 1)
        self.assertIn("hash_registro", conteudo["registros"][0])


class ProtecoesTests(BaseReset):
    def test_recusa_quando_ha_ajuste_manual_apontando(self):
        """
        A chave e `SET_NULL`, entao apagar o ponto nao apaga o ajuste:
        deixa-o apontando para o vazio, em silencio. Uma correcao sem o
        registro que ela corrige nao significa mais nada, e a auditoria
        passa a ter uma alteracao sobre coisa nenhuma.
        """
        from apps.ponto.models import AjustePonto

        self.bater(self.pessoa, 1)
        registro = RegistroPonto.objects.get()
        from apps.accounts.models import CustomUser

        gestor = CustomUser.objects.create_user(
            email="gestor@x.test", password="Prova!12345",
            nome_completo="Gestor", tipo="rh", cliente=self.cliente,
        )
        AjustePonto.objects.create(
            empresa=self.empresa,
            colaborador=self.pessoa,
            tipo_ajuste=AjustePonto.TipoAjuste.SUBSTITUICAO,
            registro_original=registro,
            data_hora_nova=registro.data_hora,
            justificativa="teste",
            executado_por=gestor,
        )

        with self.assertRaises(CommandError) as erro:
            self.rodar("--empresa", str(self.empresa.pk), "--confirmar")
        self.assertIn("ajuste", str(erro.exception).lower())
        self.assertEqual(RegistroPonto.objects.count(), 1)

    def test_nome_ambiguo_exige_o_id(self):
        # "Alfa Matriz" e "Beta Filial" nao colidem; usamos um trecho que
        # casa com as duas para provar a recusa.
        Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa Segunda", cnpj="11444777000161",
        )
        with self.assertRaises(CommandError) as erro:
            self.rodar("--empresa", "Alfa", "--confirmar")
        self.assertIn("mais de uma", str(erro.exception))

    def test_empresa_inexistente_e_erro_e_nao_silencio(self):
        with self.assertRaises(CommandError):
            self.rodar("--empresa", "Inexistente", "--confirmar")

    def test_aceita_o_nome_quando_e_unico(self):
        self.bater(self.pessoa, 1)
        self.rodar("--empresa", "Alfa Matriz", "--confirmar")
        self.assertEqual(RegistroPonto.objects.filter(empresa=self.empresa).count(), 0)
