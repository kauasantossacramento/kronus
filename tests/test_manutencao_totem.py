"""
Kronus — cadastro facial feito no proprio totem.

O modo existe porque um rosto cadastrado pela webcam do computador e
reconhecido pela camera do tablet com folga bem menor. Cadastrar no
mesmo equipamento em que a pessoa bate o ponto elimina a diferenca na
origem.

O que estes testes guardam e o outro lado disso: a porta que o modo abre.
O totem fica na parede, ao alcance de quem passa, e o token do
equipamento esta no HTML da propria pagina. Entao nenhuma das barreiras
abaixo pode depender da tela se comportar bem.
"""
from datetime import date

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.clientes.models import Cliente, Empresa
from apps.master.models import Plano
from apps.rh.models import Colaborador
from apps.totem.models import Totem


class BaseManutencao(TestCase):
    def setUp(self):
        cache.clear()
        self.plano = Plano.objects.create(nome="P", slug="p", max_totems=5)
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=self.plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.totem = Totem.objects.create(empresa=self.empresa, ativo=True)
        self.pessoa = Colaborador.objects.create(
            empresa=self.empresa, nome_completo="Ana Souza", cpf="52998224725",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )
        self.cabecalho = {"HTTP_AUTHORIZATION": f"Token {self.totem.token_acesso}"}

    def ligar(self, senha="segredo123"):
        self.cliente.cadastro_facial_no_totem = True
        self.cliente.save(update_fields=["cadastro_facial_no_totem"])
        self.cliente.definir_senha_totem(senha)

    def entrar(self, senha="segredo123"):
        return self.client.post(
            reverse("api:totem:totem_manutencao_entrar"),
            {"senha": senha}, content_type="application/json", **self.cabecalho,
        )

    def com_sessao(self, chave):
        return {**self.cabecalho, "HTTP_X_MANUTENCAO": chave}


class PortaFechadaTests(BaseManutencao):
    def test_desligado_recusa(self):
        resposta = self.entrar()
        self.assertEqual(resposta.status_code, 403)

    def test_ligado_sem_senha_nao_abre(self):
        # Um dos dois sozinho nao basta: marcar a opcao e esquecer a
        # senha deixaria a porta destrancada.
        self.cliente.cadastro_facial_no_totem = True
        self.cliente.save(update_fields=["cadastro_facial_no_totem"])
        self.assertFalse(self.cliente.cadastro_no_totem_disponivel)
        self.assertEqual(self.entrar("qualquer").status_code, 403)

    def test_desligado_responde_igual_a_senha_errada(self):
        """
        Nao dizer "esta desligado".

        A diferenca entre "desligado" e "senha errada" contaria a quem
        tentou que a porta existe neste modelo de equipamento — e ele
        esta na parede, exposto a qualquer um.
        """
        desligado = self.entrar("x")
        self.ligar()
        errada = self.entrar("outra")
        self.assertEqual(desligado.status_code, errada.status_code)
        self.assertEqual(
            desligado.json()["mensagem"], errada.json()["mensagem"]
        )

    def test_a_senha_nunca_fica_em_texto_puro(self):
        self.ligar("segredo123")
        self.cliente.refresh_from_db()
        self.assertNotIn("segredo123", self.cliente.senha_totem)
        self.assertTrue(self.cliente.conferir_senha_totem("segredo123"))
        self.assertFalse(self.cliente.conferir_senha_totem("segredo124"))


class TentativasTests(BaseManutencao):
    def test_bloqueia_apos_cinco_erros(self):
        self.ligar()
        for _ in range(5):
            self.assertEqual(self.entrar("errada").status_code, 403)
        # A sexta nem chega a conferir a senha.
        self.assertEqual(self.entrar("errada").status_code, 429)

    def test_bloqueio_vale_mesmo_com_a_senha_certa(self):
        # Senao bastaria intercalar: cinco erros nao custariam nada a
        # quem depois acertasse.
        self.ligar()
        for _ in range(5):
            self.entrar("errada")
        self.assertEqual(self.entrar("segredo123").status_code, 429)

    def test_acertar_zera_a_contagem(self):
        self.ligar()
        self.entrar("errada")
        self.entrar("errada")
        self.assertEqual(self.entrar("segredo123").status_code, 200)
        for _ in range(4):
            self.entrar("errada")
        # Se a contagem nao tivesse zerado, esta ja seria a sexta.
        self.assertEqual(self.entrar("errada").status_code, 403)


class SessaoTests(BaseManutencao):
    def test_sem_sessao_nao_lista_ninguem(self):
        self.ligar()
        resposta = self.client.get(
            reverse("api:totem:totem_manutencao_colaboradores"), **self.cabecalho
        )
        self.assertEqual(resposta.status_code, 403)

    def test_chave_de_outro_totem_nao_serve(self):
        self.ligar()
        chave = self.entrar().json()["chave"]

        outro = Totem.objects.create(empresa=self.empresa, ativo=True)
        resposta = self.client.get(
            reverse("api:totem:totem_manutencao_colaboradores"),
            HTTP_AUTHORIZATION=f"Token {outro.token_acesso}",
            HTTP_X_MANUTENCAO=chave,
        )
        self.assertEqual(resposta.status_code, 403)

    def test_sair_encerra_de_imediato(self):
        self.ligar()
        chave = self.entrar().json()["chave"]
        self.client.post(
            reverse("api:totem:totem_manutencao_sair"), **self.com_sessao(chave)
        )
        resposta = self.client.get(
            reverse("api:totem:totem_manutencao_colaboradores"),
            **self.com_sessao(chave),
        )
        self.assertEqual(resposta.status_code, 403)

    def test_lista_traz_os_colaboradores_sem_cpf(self):
        """
        O nome basta para escolher. O CPF apareceria na tela de um
        aparelho de parede, para quem estivesse por perto.
        """
        self.ligar()
        chave = self.entrar().json()["chave"]
        resposta = self.client.get(
            reverse("api:totem:totem_manutencao_colaboradores"),
            **self.com_sessao(chave),
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertEqual(len(corpo["colaboradores"]), 1)
        self.assertNotIn("52998224725", resposta.content.decode())
        self.assertEqual(corpo["colaboradores"][0]["nome"], "Ana Souza")


class AlcanceTests(BaseManutencao):
    def test_nao_alcanca_colaborador_de_outro_cliente(self):
        """
        O id vem digitado do outro lado da rede. O token prova de que
        equipamento a chamada veio, e nao que colaborador ela pode tocar.
        """
        self.ligar()
        chave = self.entrar().json()["chave"]

        outro_cliente = Cliente.objects.create(
            razao_social="Beta", cnpj="11444777000161",
            plano=self.plano, email_contato="b@x.com",
        )
        outra_empresa = Empresa.objects.create(
            cliente=outro_cliente, razao_social="Beta", cnpj="34028316000103",
        )
        alheio = Colaborador.objects.create(
            empresa=outra_empresa, nome_completo="Bruno Lima", cpf="11144477735",
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )

        resposta = self.client.post(
            reverse("api:totem:totem_manutencao_consentimento"),
            {"colaborador_id": alheio.pk, "aceite": True},
            content_type="application/json", **self.com_sessao(chave),
        )
        self.assertEqual(resposta.status_code, 404)
        alheio.refresh_from_db()
        self.assertFalse(alheio.consentimento_biometrico)


class ConsentimentoTests(BaseManutencao):
    def test_registra_o_consentimento(self):
        self.ligar()
        chave = self.entrar().json()["chave"]
        resposta = self.client.post(
            reverse("api:totem:totem_manutencao_consentimento"),
            {"colaborador_id": self.pessoa.pk, "aceite": True},
            content_type="application/json", **self.com_sessao(chave),
        )
        self.assertEqual(resposta.status_code, 200)
        self.pessoa.refresh_from_db()
        self.assertTrue(self.pessoa.consentimento_biometrico)
        self.assertIsNotNone(self.pessoa.consentimento_biometrico_em)

    def test_aceite_falso_nao_registra(self):
        # Um consentimento que aceita `False` nao e consentimento, e o
        # registro passaria a mentir sobre o que a pessoa autorizou.
        self.ligar()
        chave = self.entrar().json()["chave"]
        resposta = self.client.post(
            reverse("api:totem:totem_manutencao_consentimento"),
            {"colaborador_id": self.pessoa.pk, "aceite": False},
            content_type="application/json", **self.com_sessao(chave),
        )
        self.assertEqual(resposta.status_code, 400)
        self.pessoa.refresh_from_db()
        self.assertFalse(self.pessoa.consentimento_biometrico)

    def test_captura_sem_consentimento_e_recusada(self):
        """
        A ordem importa: capturar primeiro e perguntar depois ja teria
        tratado o dado biometrico antes de haver autorizacao.
        """
        self.ligar()
        chave = self.entrar().json()["chave"]
        resposta = self.client.post(
            reverse("api:totem:totem_manutencao_amostra"),
            {"colaborador_id": self.pessoa.pk, "imagem": "data:image/jpeg;base64,x"},
            content_type="application/json", **self.com_sessao(chave),
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()["codigo"], "sem_consentimento")


class ConfiguracaoTests(BaseManutencao):
    def test_o_totem_so_sabe_do_modo_quando_ele_existe(self):
        resposta = self.client.get(
            reverse("api:totem:totem_config"), **self.cabecalho
        )
        self.assertFalse(resposta.json()["interface"]["cadastro_facial_no_totem"])

        self.ligar()
        resposta = self.client.get(
            reverse("api:totem:totem_config"), **self.cabecalho
        )
        self.assertTrue(resposta.json()["interface"]["cadastro_facial_no_totem"])

    def test_a_pagina_do_totem_nao_liga_o_gesto_sem_a_opcao(self):
        pagina = self.client.get(
            f"/totem/{self.totem.token_acesso}/"
        ).content.decode()
        self.assertIn("disponivel: false", pagina)

        self.ligar()
        pagina = self.client.get(
            f"/totem/{self.totem.token_acesso}/"
        ).content.decode()
        self.assertIn("disponivel: true", pagina)


class FormularioDoMasterTests(TestCase):
    def test_ligar_sem_senha_e_recusado(self):
        """
        Marcar a opcao e esquecer a senha deixaria a tela dizendo que o
        recurso esta ligado e o totem recusando a entrada — alguem
        passaria a tarde procurando o motivo.
        """
        from apps.clientes.forms import ClienteForm

        plano = Plano.objects.create(nome="P", slug="p")
        dados = {
            "razao_social": "Alfa", "cnpj": "45997418000153",
            "plano": plano.pk, "email_contato": "a@x.com",
            "dia_vencimento": 10, "ativo": True,
            "cadastro_facial_no_totem": True,
        }
        form = ClienteForm(data=dados)
        self.assertFalse(form.is_valid())
        self.assertIn("senha_totem", form.errors)

    def test_com_senha_liga_e_guarda_com_hash(self):
        from apps.clientes.forms import ClienteForm

        plano = Plano.objects.create(nome="P", slug="p")
        form = ClienteForm(data={
            "razao_social": "Alfa", "cnpj": "45997418000153",
            "plano": plano.pk, "email_contato": "a@x.com",
            "dia_vencimento": 10, "ativo": True,
            "cadastro_facial_no_totem": True, "senha_totem": "segredo123",
        })
        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()
        self.assertTrue(cliente.cadastro_no_totem_disponivel)
        self.assertNotIn("segredo123", cliente.senha_totem)
        self.assertTrue(cliente.conferir_senha_totem("segredo123"))
