"""
Kronus — credenciais de acesso do colaborador.

Bug relatado: o administrador marcava "criar credenciais" na edicao,
salvava, e nada acontecia — sem erro, sem aviso, sem acesso criado. A
caixa vive no formulario, que e o mesmo das duas telas, mas o gatilho
existia so na criacao.

E a senha aparecia numa mensagem que some na primeira navegacao: quem
cadastrava dez pessoas seguidas entregava zero senhas.
"""
from datetime import date
from decimal import Decimal

from django.core import mail
from django.test import TestCase


class BaseCredenciais(TestCase):
    def setUp(self):
        from apps.accounts.models import CustomUser
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
            cpf="52998224725", email="fulano@empresa.test",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2020, 1, 1),
        )
        self.rh = CustomUser.objects.create_user(
            email="rh@t.com", password="x", nome_completo="RH da Empresa",
            tipo="rh", cliente=cliente,
        )
        self.rh.empresas.add(self.empresa)


class EnvioTests(BaseCredenciais):
    def test_manda_a_senha_para_o_colaborador(self):
        from apps.rh.credenciais import enviar_credenciais

        self.pessoa.garantir_usuario()
        self.assertTrue(enviar_credenciais(self.pessoa, "senha-provisoria"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("fulano@empresa.test", mail.outbox[0].to)
        self.assertIn("senha-provisoria", mail.outbox[0].body)

    def test_sem_email_nao_envia_e_nao_quebra(self):
        """
        Devolve False, e nao erro: a entrega fica com quem cadastrou, e a
        tela avisa isso.
        """
        from apps.rh.credenciais import enviar_credenciais

        self.pessoa.email = ""
        self.pessoa.save(update_fields=["email"])
        self.assertFalse(enviar_credenciais(self.pessoa, "x"))
        self.assertEqual(len(mail.outbox), 0)

    def test_falha_no_envio_nao_desfaz_o_acesso(self):
        """
        Um servidor de e-mail fora do ar nao pode impedir a criacao de um
        acesso que ja foi criada.
        """
        from unittest.mock import patch

        from apps.rh.credenciais import enviar_credenciais

        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=RuntimeError("smtp fora"),
        ):
            self.assertFalse(enviar_credenciais(self.pessoa, "x"))

    def test_o_email_leva_o_usuario_e_nao_so_a_senha(self):
        from apps.rh.credenciais import enviar_credenciais

        usuario, _ = self.pessoa.garantir_usuario()
        enviar_credenciais(self.pessoa, "abc123")
        corpo = mail.outbox[0].body
        self.assertIn(usuario.username, corpo)


class EdicaoTests(BaseCredenciais):
    """
    O caso relatado: marcar na edicao nao fazia nada.
    """

    def _editar(self, **extra):
        self.client.force_login(self.rh)
        sessao = self.client.session
        from apps.core.middleware import CHAVE_SESSAO_EMPRESA

        sessao[CHAVE_SESSAO_EMPRESA] = self.empresa.pk
        sessao.save()

        dados = {
            "nome_completo": self.pessoa.nome_completo,
            "cpf": self.pessoa.cpf,
            "email": self.pessoa.email,
            "data_nascimento": "1990-01-01",
            "data_admissao": "2020-01-01",
            "ativo": "on",
            **extra,
        }
        return self.client.post(
            f"/rh/colaboradores/{self.pessoa.pk}/editar/", dados
        )

    def test_marcar_na_edicao_cria_o_acesso(self):
        self.assertIsNone(self.pessoa.user)
        self._editar(criar_acesso="on")
        self.pessoa.refresh_from_db()
        self.assertIsNotNone(self.pessoa.user)

    def test_marcar_na_edicao_envia_o_email(self):
        self._editar(criar_acesso="on")
        self.assertEqual(len(mail.outbox), 1)

    def test_sem_marcar_nao_cria_acesso(self):
        self._editar()
        self.pessoa.refresh_from_db()
        self.assertIsNone(self.pessoa.user)
        self.assertEqual(len(mail.outbox), 0)


class CaixaEhAcaoTests(TestCase):
    """
    A caixa nao guarda estado — e o texto de ajuda precisa dizer isso.

    Desmarcada foi lida como "esta pessoa nao tem acesso", que nao e o
    que ela significa.
    """

    def test_o_campo_nao_existe_no_banco(self):
        from apps.rh.models import Colaborador

        campos = {f.name for f in Colaborador._meta.get_fields()}
        self.assertNotIn("criar_acesso", campos)

    def test_a_ajuda_explica_que_volta_desmarcada(self):
        from apps.rh.forms import ColaboradorForm

        ajuda = ColaboradorForm().fields["criar_acesso"].help_text
        self.assertIn("desmarcada", ajuda)
        self.assertIn("e-mail", ajuda)
