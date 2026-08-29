"""
Kronus — a biometria cadastrada pertence a quem foi escolhido na lista.

Escrito porque a pergunta certa sobre um cadastro feito no totem nao e
"a captura funcionou?", e sim "ela foi parar na pessoa certa?". Um
cadastro atribuido ao colaborador errado nao da erro nenhum: da ponto
batido no nome de outra pessoa, semanas depois, e sem pista de origem.

O motor destes testes e o `ProvedorDeterministico`, que deriva o vetor do
conteudo da imagem. Ele nao reconhece rostos — mas e **estavel**: a mesma
imagem sempre produz o mesmo vetor, e imagens diferentes produzem vetores
distantes. Isso e exatamente o que se precisa aqui, porque o que esta sob
teste e o caminho do dado, e nao a qualidade do reconhecimento.
"""
import base64
import io
from datetime import date

import numpy as np
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.clientes.models import Cliente, Empresa
from apps.facial.models import FaceRegistro
from apps.facial.providers import ProvedorDeterministico
from apps.facial.services import FaceRecognitionService
from apps.master.models import Plano
from apps.rh.models import Colaborador
from apps.totem.models import Totem


def rosto(semente: int) -> str:
    """Uma 'foto' estavel e distinta por semente, em data URI."""
    imagem = Image.new("RGB", (320, 240), (200, 170, 150))
    pixels = imagem.load()
    gerador = np.random.default_rng(semente)
    for _ in range(400):
        x = int(gerador.integers(0, 320))
        y = int(gerador.integers(0, 240))
        pixels[x, y] = tuple(int(v) for v in gerador.integers(0, 255, 3))
    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


class BaseAtribuicao(TestCase):
    def setUp(self):
        cache.clear()
        plano = Plano.objects.create(nome="P", slug="p", max_totems=5)
        self.cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=self.cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.totem = Totem.objects.create(empresa=self.empresa, ativo=True)

        self.ana = self._pessoa("Ana Souza", "52998224725")
        self.bruno = self._pessoa("Bruno Lima", "11144477735")

        self.cliente.cadastro_facial_no_totem = True
        self.cliente.save(update_fields=["cadastro_facial_no_totem"])
        self.cliente.definir_senha_totem("segredo123")

        self.cabecalho = {"HTTP_AUTHORIZATION": f"Token {self.totem.token_acesso}"}
        chave = self.client.post(
            reverse("api:totem:totem_manutencao_entrar"),
            {"senha": "segredo123"},
            content_type="application/json", **self.cabecalho,
        ).json()["chave"]
        self.sessao = {**self.cabecalho, "HTTP_X_MANUTENCAO": chave}

    def _pessoa(self, nome, cpf):
        return Colaborador.objects.create(
            empresa=self.empresa, nome_completo=nome, cpf=cpf,
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )

    def consentir(self, pessoa):
        return self.client.post(
            reverse("api:totem:totem_manutencao_consentimento"),
            {"colaborador_id": pessoa.pk, "aceite": True},
            content_type="application/json", **self.sessao,
        )

    def capturar(self, pessoa, semente, angulo="frontal"):
        return self.client.post(
            reverse("api:totem:totem_manutencao_amostra"),
            {"colaborador_id": pessoa.pk, "imagem": rosto(semente), "angulo": angulo},
            content_type="application/json", **self.sessao,
        )


class AtribuicaoTests(BaseAtribuicao):
    def test_a_amostra_fica_no_colaborador_escolhido(self):
        self.consentir(self.ana)
        resposta = self.capturar(self.ana, 101)

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["ok"], resposta.json())

        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=self.ana, ativo=True).count(), 1
        )
        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=self.bruno).count(), 0,
            "cadastrar a Ana encostou no Bruno",
        )

    def test_cadastrar_um_nao_marca_o_outro_como_cadastrado(self):
        self.consentir(self.ana)
        self.capturar(self.ana, 101)

        self.ana.refresh_from_db()
        self.bruno.refresh_from_db()
        self.assertTrue(self.ana.face_registrada)
        self.assertFalse(self.bruno.face_registrada)

    def test_o_consentimento_e_de_quem_foi_escolhido(self):
        self.consentir(self.ana)

        self.ana.refresh_from_db()
        self.bruno.refresh_from_db()
        self.assertTrue(self.ana.consentimento_biometrico)
        self.assertFalse(self.bruno.consentimento_biometrico)

    def test_as_cinco_poses_vao_todas_para_a_mesma_pessoa(self):
        self.consentir(self.ana)
        for i, angulo in enumerate(
            ("frontal", "esquerda", "direita", "cima", "baixo")
        ):
            self.assertTrue(
                self.capturar(self.ana, 200 + i, angulo).json()["ok"]
            )

        registros = FaceRegistro.objects.filter(colaborador=self.ana, ativo=True)
        self.assertEqual(registros.count(), 5)
        self.assertEqual(
            set(registros.values_list("angulo", flat=True)),
            {"frontal", "esquerda", "direita", "cima", "baixo"},
        )
        self.assertEqual(FaceRegistro.objects.exclude(colaborador=self.ana).count(), 0)

    def test_duas_pessoas_seguidas_nao_se_misturam(self):
        """
        O caso que mais preocupa na pratica: o operador cadastra varias
        pessoas em sequencia, sem sair do modo. Se algo do estado da
        anterior vazar para a seguinte, e aqui que aparece.
        """
        self.consentir(self.ana)
        for i in range(3):
            self.capturar(self.ana, 300 + i)

        self.consentir(self.bruno)
        for i in range(3):
            self.capturar(self.bruno, 400 + i)

        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=self.ana, ativo=True).count(), 3
        )
        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=self.bruno, ativo=True).count(), 3
        )

        # E os vetores de um nao aparecem no outro.
        de_ana = {
            r.obter_embedding().tobytes()
            for r in FaceRegistro.objects.filter(colaborador=self.ana)
        }
        de_bruno = {
            r.obter_embedding().tobytes()
            for r in FaceRegistro.objects.filter(colaborador=self.bruno)
        }
        self.assertEqual(de_ana & de_bruno, set())


@override_settings(FACE_RECOGNITION_ENGINE="deterministico")
class ReconhecimentoDepoisDoCadastroTests(BaseAtribuicao):
    """
    A volta completa: cadastrar pelo totem e reconhecer o mesmo rosto
    devolve a pessoa que foi escolhida na lista, e nao outra.
    """

    def _servico(self):
        return FaceRecognitionService(provedor=ProvedorDeterministico())

    def test_reconhece_como_a_pessoa_cadastrada(self):
        self.consentir(self.ana)
        for i in range(3):
            self.capturar(self.ana, 500 + i)

        FaceRecognitionService.invalidar_cache(self.empresa.pk)
        resultado = self._servico().reconhecer(
            rosto(500), empresas=[self.empresa], registrar_tentativa=False
        )

        self.assertTrue(resultado.identificado, resultado.motivo)
        self.assertEqual(resultado.colaborador.pk, self.ana.pk)

    def test_nao_troca_uma_pessoa_pela_outra(self):
        self.consentir(self.ana)
        for i in range(3):
            self.capturar(self.ana, 600 + i)
        self.consentir(self.bruno)
        for i in range(3):
            self.capturar(self.bruno, 700 + i)

        FaceRecognitionService.invalidar_cache(self.empresa.pk)
        servico = self._servico()

        da_ana = servico.reconhecer(
            rosto(600), empresas=[self.empresa], registrar_tentativa=False
        )
        do_bruno = servico.reconhecer(
            rosto(700), empresas=[self.empresa], registrar_tentativa=False
        )

        self.assertTrue(da_ana.identificado, da_ana.motivo)
        self.assertTrue(do_bruno.identificado, do_bruno.motivo)
        self.assertEqual(da_ana.colaborador.pk, self.ana.pk)
        self.assertEqual(do_bruno.colaborador.pk, self.bruno.pk)

    def test_rosto_de_fora_nao_vira_ninguem(self):
        self.consentir(self.ana)
        for i in range(3):
            self.capturar(self.ana, 800 + i)

        FaceRecognitionService.invalidar_cache(self.empresa.pk)
        resultado = self._servico().reconhecer(
            rosto(9999), empresas=[self.empresa], registrar_tentativa=False
        )
        self.assertFalse(resultado.identificado)


class CapturaParecidaComOutroTests(BaseAtribuicao):
    """
    O cadastro recusa a captura que ficaria perto do cadastro alheio.

    Barrar aqui e muito melhor do que descartar depois: a pessoa ainda
    esta na frente da camera, e refazer a pose custa segundos. Descoberto
    semanas depois, custa uma batida no nome errado.
    """

    def test_recusa_e_explica_o_que_fazer(self):
        self.consentir(self.ana)
        for i in range(3):
            self.capturar(self.ana, 700 + i)

        # O Bruno tenta cadastrar exatamente a mesma imagem da Ana.
        self.consentir(self.bruno)
        resposta = self.capturar(self.bruno, 700)

        corpo = resposta.json()
        self.assertFalse(corpo["ok"], corpo)
        self.assertEqual(corpo["codigo"], "parecida_com_outro")
        self.assertIn("Ana Souza", corpo["mensagem"])
        self.assertIn("Refaça", corpo["mensagem"])

    def test_a_captura_recusada_nao_entra_na_galeria(self):
        from apps.facial.models import FaceRegistro

        self.consentir(self.ana)
        for i in range(3):
            self.capturar(self.ana, 800 + i)
        self.consentir(self.bruno)
        self.capturar(self.bruno, 800)

        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=self.bruno).count(), 0,
            "a captura recusada nao pode ficar gravada",
        )

    def test_captura_distinta_entra_normalmente(self):
        from apps.facial.models import FaceRegistro

        self.consentir(self.ana)
        for i in range(3):
            self.capturar(self.ana, 900 + i)
        self.consentir(self.bruno)
        self.assertTrue(self.capturar(self.bruno, 5000).json()["ok"])
        self.assertEqual(
            FaceRegistro.objects.filter(colaborador=self.bruno).count(), 1
        )

    def test_o_primeiro_cadastro_da_empresa_nao_e_barrado(self):
        # Sem ninguem para comparar, a regra nao tem o que dizer.
        self.consentir(self.ana)
        self.assertTrue(self.capturar(self.ana, 1234).json()["ok"])
