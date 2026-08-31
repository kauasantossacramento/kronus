"""
Kronus — transferir colaborador entre empresas do mesmo cliente.

Acontece de verdade: a pessoa e contratada por uma unidade e passa a
atuar em outra do mesmo grupo. Sem isto, o caminho era apagar e
recadastrar — e junto se perdia o historico de ponto, que e prova
trabalhista.
"""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import MetodoRegistro
from apps.master.models import Plano
from apps.ponto.models import EscalaTrabalho, RegistroPonto
from apps.ponto.services import RegistroPontoService
from apps.rh.models import Colaborador


class BaseMover(TestCase):
    def setUp(self):
        self.plano = Plano.objects.create(nome="P", slug="p", max_colaboradores=50)
        self.cliente = Cliente.objects.create(
            razao_social="Grupo", cnpj="45997418000153",
            plano=self.plano, email_contato="g@x.com",
        )
        self.matriz = Empresa.objects.create(
            cliente=self.cliente, razao_social="Matriz", cnpj="45997418000234",
        )
        self.filial = Empresa.objects.create(
            cliente=self.cliente, razao_social="Filial", cnpj="34028316000103",
        )
        self.pessoa = Colaborador.objects.create(
            empresa=self.matriz, nome_completo="Ana", cpf="52998224725",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )


class TransferenciaTests(BaseMover):
    def test_move_o_cadastro(self):
        self.pessoa.mover_para(self.filial)
        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.empresa, self.filial)

    def test_as_batidas_ficam_onde_aconteceram(self):
        """
        Elas ficam na empresa onde o trabalho foi prestado, e cada uma
        carrega o NSR daquela empresa numa corrente encadeada.
        Reescrever quebraria a corrente e falsificaria o arquivo fiscal.
        """
        RegistroPontoService.registrar(
            colaborador=self.pessoa, metodo=MetodoRegistro.WEB,
            momento=timezone.localtime() - timedelta(hours=2),
            validar_intervalo=False,
        )
        self.pessoa.mover_para(self.filial)

        registro = RegistroPonto.objects.get()
        self.assertEqual(registro.empresa, self.matriz)
        self.assertEqual(registro.nsr, 1)

    def test_a_escala_da_empresa_antiga_nao_vai_junto(self):
        # Uma jornada que o destino nao reconhece produziria calculo
        # sobre uma escala de outra empresa.
        escala = EscalaTrabalho.objects.create(
            empresa=self.matriz, nome="Comercial", jornada_config={"dias": {}}
        )
        self.pessoa.escala = escala
        self.pessoa.save(update_fields=["escala"])

        self.pessoa.mover_para(self.filial)
        self.pessoa.refresh_from_db()
        self.assertIsNone(self.pessoa.escala)

    def test_o_acesso_acompanha(self):
        # Sem o vinculo com a nova empresa, a pessoa entra e nao ve nada.
        usuario, _ = self.pessoa.garantir_usuario()
        self.assertIn(self.matriz, usuario.empresas.all())

        self.pessoa.mover_para(self.filial)
        usuario.refresh_from_db()
        self.assertIn(self.filial, usuario.empresas.all())
        self.assertNotIn(self.matriz, usuario.empresas.all())

    def test_a_biometria_acompanha(self):
        from apps.facial.models import FaceRegistro
        import numpy as np

        registro = FaceRegistro(colaborador=self.pessoa, angulo="frontal")
        registro.definir_embedding(np.ones(512, dtype=np.float32), salvar=False)
        registro.save()

        self.pessoa.mover_para(self.filial)
        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=self.pessoa).count(), 1,
            "a amostra e do colaborador e segue com ele",
        )

    def test_recusa_empresa_de_outro_cliente(self):
        """A fronteira da assinatura e o limite de tudo neste sistema."""
        outro = Cliente.objects.create(
            razao_social="Outro", cnpj="11444777000161",
            plano=self.plano, email_contato="o@x.com",
        )
        alheia = Empresa.objects.create(
            cliente=outro, razao_social="Alheia", cnpj="72344591000125",
        )

        with self.assertRaises(ValidationError):
            self.pessoa.mover_para(alheia)

        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.empresa, self.matriz)

    def test_mover_para_a_propria_empresa_nao_faz_nada(self):
        self.pessoa.mover_para(self.matriz)
        self.pessoa.refresh_from_db()
        self.assertEqual(self.pessoa.empresa, self.matriz)
