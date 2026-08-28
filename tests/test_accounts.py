"""Kronus — testes de autenticacao (Fase 1)."""
from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.constants import TipoUsuario

User = get_user_model()


class CriacaoDeUsuarioTests(TestCase):
    def test_cria_usuario_por_email(self):
        user = User.objects.create_user(
            email="Fulano@Empresa.com", password="senha-forte-123", nome_completo="Fulano"
        )
        self.assertEqual(user.email, "fulano@empresa.com")
        self.assertEqual(user.username, "fulano@empresa.com")
        self.assertEqual(user.tipo, TipoUsuario.COLABORADOR)

    def test_cria_usuario_por_cpf_normalizando_mascara(self):
        user = User.objects.create_user(
            cpf="529.982.247-25", password="senha-forte-123", nome_completo="Ciclano"
        )
        self.assertEqual(user.cpf, "52998224725")
        self.assertEqual(user.username, "52998224725")

    def test_exige_email_ou_cpf(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(password="x", nome_completo="Sem identificador")

    def test_superusuario_nasce_master(self):
        user = User.objects.create_superuser(
            email="master@kstec.online", password="senha-forte-123"
        )
        self.assertEqual(user.tipo, TipoUsuario.MASTER)
        self.assertTrue(user.is_staff and user.is_superuser)

    def test_iniciais_e_primeiro_nome(self):
        user = User(nome_completo="João da Silva Souza")
        self.assertEqual(user.primeiro_nome, "João")
        self.assertEqual(user.iniciais, "JS")


class BackendsDeAutenticacaoTests(TestCase):
    def setUp(self):
        self.senha = "senha-forte-123"
        self.user = User.objects.create_user(
            email="colab@empresa.com",
            cpf="52998224725",
            password=self.senha,
            nome_completo="Colaborador Teste",
        )

    def test_autentica_por_email(self):
        self.assertEqual(
            authenticate(username="colab@empresa.com", password=self.senha), self.user
        )

    def test_autentica_por_email_ignorando_caixa(self):
        self.assertEqual(
            authenticate(username="COLAB@empresa.com", password=self.senha), self.user
        )

    def test_autentica_por_cpf_sem_mascara(self):
        self.assertEqual(
            authenticate(username="52998224725", password=self.senha), self.user
        )

    def test_autentica_por_cpf_com_mascara(self):
        self.assertEqual(
            authenticate(username="529.982.247-25", password=self.senha), self.user
        )

    def test_senha_incorreta_falha(self):
        self.assertIsNone(authenticate(username="52998224725", password="errada"))

    def test_bloqueio_apos_cinco_tentativas(self):
        for _ in range(5):
            authenticate(username="52998224725", password="errada")
        self.user.refresh_from_db()
        self.assertTrue(self.user.esta_bloqueado)
        # Mesmo com a senha correta, o usuário permanece bloqueado.
        self.assertIsNone(authenticate(username="52998224725", password=self.senha))


class FluxoDeLoginTests(TestCase):
    def setUp(self):
        self.senha = "senha-forte-123"
        self.user = User.objects.create_user(
            cpf="52998224725",
            password=self.senha,
            nome_completo="Colaborador Teste",
        )

    def test_tela_de_login_responde(self):
        resposta = self.client.get(reverse("accounts:login"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Kronus")

    def test_login_valido_redireciona(self):
        resposta = self.client.post(
            reverse("accounts:login"),
            {"username": "529.982.247-25", "password": self.senha},
        )
        self.assertEqual(resposta.status_code, 302)

    def test_login_registra_auditoria(self):
        from apps.core.models import LogAcesso

        self.client.post(
            reverse("accounts:login"),
            {"username": "52998224725", "password": self.senha},
        )
        self.assertTrue(LogAcesso.objects.filter(acao=LogAcesso.Acao.LOGIN).exists())

    def test_login_invalido_registra_falha(self):
        from apps.core.models import LogAcesso

        self.client.post(
            reverse("accounts:login"),
            {"username": "52998224725", "password": "errada"},
        )
        self.assertTrue(
            LogAcesso.objects.filter(acao=LogAcesso.Acao.LOGIN_FALHA).exists()
        )
