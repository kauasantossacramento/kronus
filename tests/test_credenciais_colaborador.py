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


class CaixaEhAcaoTests(BaseCredenciais):
    """
    A caixa nao guarda estado — e o texto de ajuda precisa dizer isso.

    Desmarcada foi lida como "esta pessoa nao tem acesso", que nao e o
    que ela significa.
    """

    def test_o_campo_nao_existe_no_banco(self):
        from apps.rh.models import Colaborador

        campos = {f.name for f in Colaborador._meta.get_fields()}
        self.assertNotIn("criar_acesso", campos)

    def test_a_ajuda_diz_que_envia_por_email(self):
        from apps.rh.forms import ColaboradorForm

        ajuda = ColaboradorForm().fields["criar_acesso"].help_text
        self.assertIn("e-mail", ajuda)


class CaixaSomeDepoisDeUsadaTests(BaseCredenciais):
    """
    Acao ja feita nao continua oferecida.

    Marcar a caixa para quem ja tem login nao produz nada. Mostrar mesmo
    assim convidava a marcar e esperar alguma coisa — e a caixa
    desmarcada na volta era lida como "esta pessoa nao tem acesso", que
    e o contrario do que acontecia.
    """

    def test_quem_nao_tem_acesso_ve_a_caixa(self):
        from apps.rh.forms import ColaboradorForm

        self.assertIn("criar_acesso", ColaboradorForm(instance=self.pessoa).fields)

    def test_quem_ja_tem_acesso_nao_ve(self):
        from apps.rh.forms import ColaboradorForm

        self.pessoa.garantir_usuario()
        self.pessoa.refresh_from_db()
        self.assertNotIn("criar_acesso", ColaboradorForm(instance=self.pessoa).fields)

    def test_no_cadastro_novo_a_caixa_aparece(self):
        """Sem instancia salva ninguem tem acesso ainda."""
        from apps.rh.forms import ColaboradorForm

        self.assertIn("criar_acesso", ColaboradorForm().fields)

    def test_salvar_sem_o_campo_nao_quebra(self):
        """
        A view le com `.get`: campo ausente e o mesmo que nao marcado.
        Sem isso, editar quem ja tem acesso levantaria KeyError.
        """
        self.pessoa.garantir_usuario()
        resposta = self._editar_como_rh()
        self.assertIn(resposta.status_code, (200, 302))

    def _editar_como_rh(self):
        from apps.core.middleware import CHAVE_SESSAO_EMPRESA

        self.client.force_login(self.rh)
        sessao = self.client.session
        sessao[CHAVE_SESSAO_EMPRESA] = self.empresa.pk
        sessao.save()
        return self.client.post(
            f"/rh/colaboradores/{self.pessoa.pk}/editar/",
            {
                "nome_completo": self.pessoa.nome_completo,
                "cpf": self.pessoa.cpf,
                "email": self.pessoa.email,
                "data_nascimento": "1990-01-01",
                "data_admissao": "2020-01-01",
                "ativo": "on",
            },
        )


class SincroniaDoEmailTests(BaseCredenciais):
    """
    O e-mail da ficha tem de alcancar o login.

    So era copiado na criacao. Quem tinha acesso criado sem e-mail e
    recebia o endereco depois ficava com o login sem e-mail para sempre
    — e a recuperacao de senha procura o usuario **por e-mail**: a
    pessoa pedia, a tela dizia "enviado", e nada saia.
    """

    def test_email_cadastrado_depois_alcanca_o_login(self):
        self.pessoa.email = ""
        self.pessoa.save(update_fields=["email"])
        self.pessoa.garantir_usuario()
        self.pessoa.refresh_from_db()
        self.assertFalse(self.pessoa.user.email)

        self.pessoa.email = "novo@empresa.test"
        self.pessoa.save()

        self.pessoa.user.refresh_from_db()
        self.assertEqual(self.pessoa.user.email, "novo@empresa.test")

    def test_email_trocado_na_ficha_troca_no_login(self):
        self.pessoa.garantir_usuario()
        self.pessoa.email = "outro@empresa.test"
        self.pessoa.save()
        self.pessoa.user.refresh_from_db()
        self.assertEqual(self.pessoa.user.email, "outro@empresa.test")

    def test_ficha_sem_email_nao_apaga_o_do_login(self):
        """
        Um campo esvaziado por engano tiraria o unico caminho de
        recuperacao que a pessoa tinha.
        """
        self.pessoa.garantir_usuario()
        self.pessoa.refresh_from_db()
        self.assertTrue(self.pessoa.user.email)

        self.pessoa.email = ""
        self.pessoa.save()

        self.pessoa.user.refresh_from_db()
        self.assertTrue(self.pessoa.user.email)

    def test_a_recuperacao_encontra_quem_tem_email(self):
        from django.contrib.auth.forms import PasswordResetForm

        self.pessoa.garantir_usuario()
        f = PasswordResetForm({"email": self.pessoa.email})
        self.assertTrue(f.is_valid())
        self.assertTrue(list(f.get_users(self.pessoa.email)))

    def test_sem_login_a_recuperacao_nao_encontra_ninguem(self):
        """
        E a tela diz "enviado" mesmo assim — comportamento deliberado do
        Django, para nao revelar quais enderecos tem conta. Documentado
        aqui porque parece falha de envio para quem esta olhando.
        """
        from django.contrib.auth.forms import PasswordResetForm

        f = PasswordResetForm({"email": self.pessoa.email})
        self.assertTrue(f.is_valid())
        self.assertEqual(list(f.get_users(self.pessoa.email)), [])
