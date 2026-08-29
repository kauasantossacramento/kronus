"""
Kronus — testes do reconhecimento facial (Fase 3).

Rodam com `FACE_PROVIDER = "deterministico"` (ver `config/settings/test.py`):
o embedding deriva do conteúdo da imagem, então o fluxo completo de
cadastro, comparação e threshold é exercitado sem carregar o ArcFace.

O que **não** é coberto aqui é a acurácia do modelo real — isso depende
de dataset com rostos e é validado em ambiente com a stack instalada.
"""
import base64
import io
from datetime import date

import numpy as np
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoUsuario
from apps.facial.models import FaceRegistro, TentativaReconhecimento
from apps.facial.processors import (
    ImagemInvalida,
    calcular_qualidade,
    decodificar_base64,
    normalizar,
    preparar,
    validar_dimensoes,
)
from apps.facial.providers import (
    MultiplosRostosDetectados,
    NenhumRostoDetectado,
    ProvedorDeterministico,
    ProvedorFacial,
    ProvedorIndisponivel,
    obter_provedor,
)
from apps.facial.services import FaceRecognitionService, identificar_por_cpf
from apps.master.models import Plano
from apps.rh.models import Colaborador

User = get_user_model()
SENHA = "senha-forte-123"


# ══════════════════════════════════════════════════════════════
# Utilitários dos testes
# ══════════════════════════════════════════════════════════════
def imagem_bytes(cor=(200, 170, 150), tamanho=(320, 240), ruido=None) -> bytes:
    """Gera um JPEG sintético. `ruido` diferencia imagens de mesma cor."""
    imagem = Image.new("RGB", tamanho, cor)
    if ruido is not None:
        pixels = imagem.load()
        gerador = np.random.default_rng(ruido)
        for _ in range(400):
            x = int(gerador.integers(0, tamanho[0]))
            y = int(gerador.integers(0, tamanho[1]))
            pixels[x, y] = tuple(int(v) for v in gerador.integers(0, 255, 3))
    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def como_base64(dados: bytes, data_uri=False) -> str:
    texto = base64.b64encode(dados).decode()
    return f"data:image/jpeg;base64,{texto}" if data_uri else texto


# ══════════════════════════════════════════════════════════════
# Provedores
# ══════════════════════════════════════════════════════════════
class ProvedorTests(TestCase):
    def setUp(self):
        self.provedor = ProvedorDeterministico()

    def test_embedding_tem_512_dimensoes(self):
        vetor = self.provedor.gerar_embedding(imagem_bytes())
        self.assertEqual(vetor.shape, (512,))
        self.assertEqual(vetor.dtype, np.float32)

    def test_embedding_e_normalizado(self):
        vetor = self.provedor.gerar_embedding(imagem_bytes())
        self.assertAlmostEqual(float(np.linalg.norm(vetor)), 1.0, places=5)

    def test_mesma_imagem_gera_mesmo_vetor(self):
        dados = imagem_bytes(ruido=1)
        np.testing.assert_array_equal(
            self.provedor.gerar_embedding(dados), self.provedor.gerar_embedding(dados)
        )

    def test_imagens_diferentes_geram_vetores_distantes(self):
        a = self.provedor.gerar_embedding(imagem_bytes(ruido=1))
        b = self.provedor.gerar_embedding(imagem_bytes(ruido=2))
        self.assertGreater(ProvedorFacial.distancia_cosseno(a, b), 0.68)

    def test_imagem_vazia_e_recusada(self):
        with self.assertRaises(Exception):
            self.provedor.gerar_embedding(b"")

    def test_marcadores_simulam_falhas_de_enquadramento(self):
        with self.assertRaises(NenhumRostoDetectado):
            self.provedor.gerar_embedding(b"xx__SEM_ROSTO__xx")
        with self.assertRaises(MultiplosRostosDetectados):
            self.provedor.gerar_embedding(b"xx__MULTIPLOS_ROSTOS__xx")

    def test_provedor_indisponivel_recusa_com_instrucao(self):
        provedor = ProvedorIndisponivel()
        self.assertFalse(provedor.disponivel)
        with self.assertRaises(Exception) as contexto:
            provedor.gerar_embedding(imagem_bytes())
        self.assertIn("requirements.txt", str(contexto.exception))

    @override_settings(FACE_PROVIDER="deterministico")
    def test_selecao_por_settings(self):
        self.assertEqual(obter_provedor().nome, "deterministico")

    @override_settings(FACE_PROVIDER="indisponivel")
    def test_selecao_desligada(self):
        self.assertEqual(obter_provedor().nome, "indisponivel")


class MetricaTests(TestCase):
    def test_distancia_de_vetores_identicos_e_zero(self):
        vetor = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        self.assertAlmostEqual(ProvedorFacial.distancia_cosseno(vetor, vetor), 0.0, places=6)

    def test_distancia_de_vetores_ortogonais_e_um(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        self.assertAlmostEqual(ProvedorFacial.distancia_cosseno(a, b), 1.0, places=6)

    def test_distancia_de_vetores_opostos_e_dois(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        self.assertAlmostEqual(ProvedorFacial.distancia_cosseno(a, -a), 2.0, places=6)

    def test_confianca_no_threshold_e_zero(self):
        self.assertEqual(ProvedorFacial.confianca(0.68, 0.68), 0.0)

    def test_confianca_em_distancia_zero_e_cem(self):
        self.assertEqual(ProvedorFacial.confianca(0.0, 0.68), 100.0)

    def test_media_normalizada(self):
        vetores = [
            np.array([1.0, 0.0, 0.0], dtype=np.float32),
            np.array([0.0, 1.0, 0.0], dtype=np.float32),
        ]
        media = ProvedorFacial.media_normalizada(vetores)
        self.assertAlmostEqual(float(np.linalg.norm(media)), 1.0, places=5)


# ══════════════════════════════════════════════════════════════
# Pré-processamento
# ══════════════════════════════════════════════════════════════
class ProcessamentoTests(TestCase):
    def test_decodifica_base64_puro(self):
        dados = imagem_bytes()
        self.assertEqual(decodificar_base64(como_base64(dados)), dados)

    def test_decodifica_data_uri(self):
        dados = imagem_bytes()
        self.assertEqual(decodificar_base64(como_base64(dados, data_uri=True)), dados)

    def test_base64_invalido_e_recusado(self):
        with self.assertRaises(ImagemInvalida):
            decodificar_base64("isto-nao-e-base64!!!")

    def test_payload_vazio_e_recusado(self):
        with self.assertRaises(ImagemInvalida):
            decodificar_base64("")

    def test_imagem_pequena_demais_e_recusada(self):
        with self.assertRaises(ImagemInvalida) as contexto:
            validar_dimensoes(imagem_bytes(tamanho=(80, 60)))
        self.assertEqual(contexto.exception.codigo, "imagem_pequena")

    def test_arquivo_que_nao_e_imagem_e_recusado(self):
        with self.assertRaises(ImagemInvalida):
            validar_dimensoes(b"isto nao e uma imagem")

    def test_normalizacao_leva_o_lado_menor_ao_alvo(self):
        """
        A normalizacao agora escala nos **dois** sentidos.

        Antes so reduzia: uma foto de tablet 480p chegava ao ArcFace com
        metade da escala de uma foto de celular 12 MP, e o mesmo rosto
        gerava embeddings diferentes conforme o aparelho do cadastro.
        Levar o lado menor a uma medida fixa uniformiza a entrada.
        """
        from apps.facial.processors import LADO_ALVO

        grande = imagem_bytes(tamanho=(1600, 1200))
        with Image.open(io.BytesIO(normalizar(grande))) as resultado:
            self.assertEqual(min(resultado.size), LADO_ALVO)

    def test_normalizacao_amplia_imagem_pequena(self):
        pequena = imagem_bytes(tamanho=(320, 240))
        from apps.facial.processors import LADO_ALVO

        with Image.open(io.BytesIO(normalizar(pequena))) as resultado:
            self.assertEqual(min(resultado.size), LADO_ALVO)

    def test_normalizacao_preserva_a_proporcao(self):
        with Image.open(io.BytesIO(normalizar(imagem_bytes(tamanho=(1200, 900))))) as r:
            self.assertAlmostEqual(r.size[0] / r.size[1], 1200 / 900, places=1)

    def test_normalizacao_equaliza_iluminacao(self):
        """
        Duas fotos do mesmo conteudo sob luzes diferentes precisam sair
        parecidas — e o que faz um cadastro na sala do RH valer no
        corredor da portaria.
        """
        from PIL import Image as PILImage, ImageEnhance

        base = PILImage.open(io.BytesIO(imagem_bytes(tamanho=(640, 640))))
        escura, clara = io.BytesIO(), io.BytesIO()
        ImageEnhance.Brightness(base).enhance(0.45).save(escura, format="JPEG")
        ImageEnhance.Brightness(base).enhance(1.7).save(clara, format="JPEG")

        def brilho_medio(dados):
            with PILImage.open(io.BytesIO(dados)) as img:
                cinza = img.convert("L")
                pixels = list(cinza.getdata())
                return sum(pixels) / len(pixels)

        antes_diferenca = abs(
            brilho_medio(escura.getvalue()) - brilho_medio(clara.getvalue())
        )
        depois_diferenca = abs(
            brilho_medio(normalizar(escura.getvalue()))
            - brilho_medio(normalizar(clara.getvalue()))
        )
        self.assertLess(
            depois_diferenca, antes_diferenca,
            "a equalizacao deveria aproximar o brilho das duas versoes",
        )

    def test_normalizacao_converte_para_jpeg(self):
        png = io.BytesIO()
        Image.new("RGBA", (300, 300), (200, 170, 150, 255)).save(png, format="PNG")
        with Image.open(io.BytesIO(normalizar(png.getvalue()))) as resultado:
            self.assertEqual(resultado.format, "JPEG")
            self.assertEqual(resultado.mode, "RGB")

    def test_pipeline_completo(self):
        self.assertTrue(preparar(como_base64(imagem_bytes(ruido=3))))

    def test_qualidade_fica_entre_zero_e_cem(self):
        score = calcular_qualidade(imagem_bytes(ruido=4))
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_imagem_uniforme_tem_qualidade_baixa(self):
        """Foto sem textura (parede, escuro) não serve para biometria."""
        self.assertLess(calcular_qualidade(imagem_bytes(cor=(10, 10, 10))), 25.0)


# ══════════════════════════════════════════════════════════════
# Serviço de reconhecimento
# ══════════════════════════════════════════════════════════════
class BaseFacialTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plano = Plano.objects.create(
            nome="Teste", slug="teste", max_colaboradores=100, max_totems=5, tem_totem=True
        )
        cls.cliente = Cliente.objects.create(
            razao_social="Cliente", cnpj="11222333000181", plano=cls.plano, email_contato="c@c.com"
        )
        cls.empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Empresa A", cnpj="11222333000262"
        )
        cls.outra_empresa = Empresa.objects.create(
            cliente=cls.cliente, razao_social="Empresa B", cnpj="11222333000343"
        )
        cls.joao = Colaborador.objects.create(
            empresa=cls.empresa,
            cpf="52998224725",
            nome_completo="João da Silva",
            data_nascimento=date(1990, 3, 12),
            data_admissao=date(2024, 1, 1),
            consentimento_biometrico=True,
        )
        cls.maria = Colaborador.objects.create(
            empresa=cls.empresa,
            cpf="15350946056",
            nome_completo="Maria Lima",
            data_nascimento=date(1985, 7, 4),
            data_admissao=date(2024, 1, 1),
            consentimento_biometrico=True,
        )
        cls.carlos = Colaborador.objects.create(
            empresa=cls.outra_empresa,
            cpf="71428793860",
            nome_completo="Carlos Ramos",
            data_nascimento=date(1978, 11, 23),
            data_admissao=date(2024, 1, 1),
            consentimento_biometrico=True,
        )

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.servico = FaceRecognitionService(provedor=ProvedorDeterministico())

    def cadastrar(self, colaborador, *ruidos):
        for ruido in ruidos:
            self.servico.cadastrar_amostra(
                colaborador, como_base64(imagem_bytes(ruido=ruido)), exigir_qualidade=False
            )
        return self.servico.consolidar_cadastro(colaborador)


class CadastroFacialTests(BaseFacialTestCase):
    def test_amostra_gera_registro_com_embedding(self):
        registro = self.servico.cadastrar_amostra(
            self.joao, como_base64(imagem_bytes(ruido=10)), exigir_qualidade=False
        )
        self.assertIsNotNone(registro.embedding)
        self.assertEqual(registro.obter_embedding().shape, (512,))

    def test_consolidacao_marca_face_registrada(self):
        self.cadastrar(self.joao, 10, 11, 12)
        self.joao.refresh_from_db()
        self.assertTrue(self.joao.face_registrada)
        self.assertIsNotNone(self.joao.face_embedding)
        self.assertIsNotNone(self.joao.face_atualizada_em)

    def test_consolidacao_usa_todas_as_amostras(self):
        self.assertEqual(self.cadastrar(self.joao, 10, 11, 12), 3)

    def test_qualidade_baixa_e_recusada(self):
        with self.assertRaises(ImagemInvalida) as contexto:
            self.servico.cadastrar_amostra(
                self.joao, como_base64(imagem_bytes(cor=(8, 8, 8)))
            )
        self.assertEqual(contexto.exception.codigo, "qualidade_baixa")

    def test_remocao_limpa_embedding_e_amostras(self):
        self.cadastrar(self.joao, 10, 11, 12)
        self.servico.remover_cadastro(self.joao)
        self.joao.refresh_from_db()
        self.assertFalse(self.joao.face_registrada)
        self.assertIsNone(self.joao.face_embedding)
        self.assertEqual(self.joao.registros_faciais.count(), 0)

    def test_consolidar_sem_amostras_limpa_o_cadastro(self):
        self.cadastrar(self.joao, 10)
        self.joao.registros_faciais.all().delete()
        self.assertEqual(self.servico.consolidar_cadastro(self.joao), 0)
        self.joao.refresh_from_db()
        self.assertFalse(self.joao.face_registrada)


class ReconhecimentoTests(BaseFacialTestCase):
    def setUp(self):
        super().setUp()
        # João é cadastrado com a imagem de ruído 10.
        self.cadastrar(self.joao, 10)
        self.cadastrar(self.maria, 20)

    def test_identifica_o_colaborador_correto(self):
        resultado = self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=10)),
            empresas=[self.empresa],
            registrar_tentativa=False,
        )
        self.assertTrue(resultado.identificado)
        self.assertEqual(resultado.colaborador, self.joao)
        self.assertLess(resultado.distancia, 0.68)

    def test_nao_confunde_colaboradores(self):
        resultado = self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=20)),
            empresas=[self.empresa],
            registrar_tentativa=False,
        )
        self.assertEqual(resultado.colaborador, self.maria)

    def test_rosto_desconhecido_nao_e_identificado(self):
        resultado = self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=999)),
            empresas=[self.empresa],
            registrar_tentativa=False,
        )
        self.assertFalse(resultado.identificado)
        self.assertEqual(resultado.codigo, "nao_identificado")

    def test_escopo_de_empresa_e_respeitado(self):
        """Regra 12 da Seção 14: só reconhece quem pertence ao escopo."""
        self.cadastrar(self.carlos, 30)
        resultado = self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=30)),
            empresas=[self.empresa],  # Carlos é da outra empresa
            registrar_tentativa=False,
        )
        self.assertFalse(resultado.identificado)

    def test_empresa_sem_cadastro_facial_informa_o_motivo(self):
        resultado = self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=10)),
            empresas=[self.outra_empresa],
            registrar_tentativa=False,
        )
        self.assertEqual(resultado.codigo, "sem_candidatos")

    def test_sem_rosto_devolve_codigo_proprio(self):
        """
        O marcador do provedor determinístico não sobrevive à
        normalização (que reencoda o JPEG), então aqui testamos o que
        interessa neste nível: a tradução do erro do motor em código de
        resposta para o totem.
        """
        from unittest.mock import patch

        with patch.object(
            self.servico.provedor, "gerar_embedding", side_effect=NenhumRostoDetectado()
        ):
            resultado = self.servico.reconhecer(
                como_base64(imagem_bytes(ruido=5)),
                empresas=[self.empresa],
                registrar_tentativa=False,
            )
        self.assertEqual(resultado.codigo, "sem_rosto")

    def test_multiplos_rostos_devolve_codigo_proprio(self):
        from unittest.mock import patch

        with patch.object(
            self.servico.provedor,
            "gerar_embedding",
            side_effect=MultiplosRostosDetectados(),
        ):
            resultado = self.servico.reconhecer(
                como_base64(imagem_bytes(ruido=5)),
                empresas=[self.empresa],
                registrar_tentativa=False,
            )
        self.assertEqual(resultado.codigo, "multiplos_rostos")

    def test_imagem_invalida_devolve_codigo_proprio(self):
        resultado = self.servico.reconhecer(
            "nao-e-base64!!!", empresas=[self.empresa], registrar_tentativa=False
        )
        self.assertFalse(resultado.identificado)
        self.assertEqual(resultado.codigo, "imagem_invalida")

    def test_tempo_de_processamento_e_medido(self):
        resultado = self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=10)),
            empresas=[self.empresa],
            registrar_tentativa=False,
        )
        self.assertGreaterEqual(resultado.tempo_ms, 0)

    def test_tentativa_e_registrada_para_auditoria(self):
        self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=10)), empresas=[self.empresa]
        )
        tentativa = TentativaReconhecimento.objects.latest("created_at")
        self.assertEqual(
            tentativa.resultado, TentativaReconhecimento.Resultado.IDENTIFICADO
        )
        self.assertEqual(tentativa.colaborador, self.joao)

    def test_falha_tambem_e_registrada(self):
        self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=999)), empresas=[self.empresa]
        )
        tentativa = TentativaReconhecimento.objects.latest("created_at")
        self.assertEqual(
            tentativa.resultado, TentativaReconhecimento.Resultado.NAO_IDENTIFICADO
        )

    def test_colaborador_inativo_sai_dos_candidatos(self):
        self.joao.ativo = False
        self.joao.save(update_fields=["ativo"])
        FaceRecognitionService.invalidar_cache(self.empresa.pk)

        resultado = self.servico.reconhecer(
            como_base64(imagem_bytes(ruido=10)),
            empresas=[self.empresa],
            registrar_tentativa=False,
        )
        self.assertNotEqual(resultado.colaborador, self.joao)


class CacheTests(BaseFacialTestCase):
    def test_candidatos_vem_do_cache_na_segunda_chamada(self):
        self.cadastrar(self.joao, 10)

        primeira = self.servico.candidatos([self.empresa])
        self.assertIn(self.joao.pk, primeira)

        # Alteração direta no banco não invalida o cache — é justamente
        # essa economia que mantém o reconhecimento abaixo de 2 s.
        Colaborador.objects.filter(pk=self.joao.pk).update(face_registrada=False)
        segunda = self.servico.candidatos([self.empresa])
        self.assertIn(self.joao.pk, segunda)

    def test_invalidacao_forca_releitura(self):
        self.cadastrar(self.joao, 10)
        self.servico.candidatos([self.empresa])

        Colaborador.objects.filter(pk=self.joao.pk).update(face_registrada=False)
        FaceRecognitionService.invalidar_cache(self.empresa.pk)

        self.assertNotIn(self.joao.pk, self.servico.candidatos([self.empresa]))

    def test_cadastro_invalida_o_cache_automaticamente(self):
        self.servico.candidatos([self.empresa])
        self.cadastrar(self.maria, 20)
        self.assertIn(self.maria.pk, self.servico.candidatos([self.empresa]))


# ══════════════════════════════════════════════════════════════
# Fallback por CPF
# ══════════════════════════════════════════════════════════════
class FallbackCPFTests(BaseFacialTestCase):
    def test_identifica_com_cpf_e_nascimento_corretos(self):
        encontrado = identificar_por_cpf(
            "529.982.247-25", date(1990, 3, 12), [self.empresa]
        )
        self.assertEqual(encontrado, self.joao)

    def test_data_de_nascimento_errada_nao_identifica(self):
        """A data é o segundo fator: só o CPF não basta."""
        self.assertIsNone(
            identificar_por_cpf("52998224725", date(1991, 1, 1), [self.empresa])
        )

    def test_colaborador_de_outra_empresa_nao_e_encontrado(self):
        self.assertIsNone(
            identificar_por_cpf("71428793860", date(1978, 11, 23), [self.empresa])
        )

    def test_colaborador_inativo_nao_e_encontrado(self):
        self.joao.ativo = False
        self.joao.save(update_fields=["ativo"])
        self.assertIsNone(
            identificar_por_cpf("52998224725", date(1990, 3, 12), [self.empresa])
        )

    def test_cpf_malformado_devolve_none(self):
        self.assertIsNone(identificar_por_cpf("123", date(1990, 3, 12), [self.empresa]))


# ══════════════════════════════════════════════════════════════
# Tela de cadastro (painel RH)
# ══════════════════════════════════════════════════════════════
class TelaCadastroTests(BaseFacialTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rh = User.objects.create_user(
            email="rh@teste.com",
            password=SENHA,
            nome_completo="RH",
            tipo=TipoUsuario.RH,
            cliente=cls.cliente,
        )
        cls.rh.empresas.set([cls.empresa])

    def setUp(self):
        super().setUp()
        self.client.login(username="rh@teste.com", password=SENHA)

    def test_tela_responde(self):
        resposta = self.client.get(reverse("facial:cadastro", args=[self.joao.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "João da Silva")

    def test_colaborador_de_outra_empresa_da_404(self):
        resposta = self.client.get(reverse("facial:cadastro", args=[self.carlos.pk]))
        self.assertEqual(resposta.status_code, 404)

    def test_captura_sem_consentimento_e_bloqueada(self):
        """LGPD Art. 11: biometria exige consentimento específico."""
        self.joao.consentimento_biometrico = False
        self.joao.save(update_fields=["consentimento_biometrico"])

        resposta = self.client.post(
            reverse("facial:receber_amostra", args=[self.joao.pk]),
            data='{"image": "x"}',
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()["codigo"], "sem_consentimento")

    def test_amostra_valida_e_aceita(self):
        resposta = self.client.post(
            reverse("facial:receber_amostra", args=[self.joao.pk]),
            data=f'{{"image": "{como_base64(imagem_bytes(ruido=42))}", "angulo": "frontal"}}',
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["total_amostras"], 1)
        self.assertFalse(dados["completo"])

    def test_amostra_ruim_e_recusada_com_orientacao(self):
        resposta = self.client.post(
            reverse("facial:receber_amostra", args=[self.joao.pk]),
            data=f'{{"image": "{como_base64(imagem_bytes(cor=(8, 8, 8)))}"}}',
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()["codigo"], "qualidade_baixa")

    def test_limite_de_amostras_e_respeitado(self):
        # Contado a partir do limite configurado, e nao de um numero
        # escrito aqui: ele mudou de cinco para sete quando o cadastro
        # ganhou espaco para as amostras aprendidas, e um numero fixo no
        # teste teria reprovado a mudanca em vez de acompanha-la.
        from django.conf import settings

        limite = settings.FACE_AMOSTRAS_MAXIMAS
        for ruido in range(60, 60 + limite):
            self.servico.cadastrar_amostra(
                self.joao, como_base64(imagem_bytes(ruido=ruido)), exigir_qualidade=False
            )
        resposta = self.client.post(
            reverse("facial:receber_amostra", args=[self.joao.pk]),
            data=f'{{"image": "{como_base64(imagem_bytes(ruido=70))}"}}',
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()["codigo"], "limite_amostras")

    def test_registro_de_consentimento(self):
        self.joao.consentimento_biometrico = False
        self.joao.save(update_fields=["consentimento_biometrico"])

        self.client.post(reverse("facial:consentimento", args=[self.joao.pk]))
        self.joao.refresh_from_db()
        self.assertTrue(self.joao.consentimento_biometrico)
        self.assertIsNotNone(self.joao.consentimento_biometrico_em)

    def test_exclusao_de_biometria_revoga_o_consentimento(self):
        self.cadastrar(self.joao, 10, 11, 12)
        self.client.post(reverse("facial:excluir_biometria", args=[self.joao.pk]))

        self.joao.refresh_from_db()
        self.assertFalse(self.joao.face_registrada)
        self.assertFalse(self.joao.consentimento_biometrico)
        self.assertEqual(FaceRegistro.objects.filter(colaborador=self.joao).count(), 0)


# ══════════════════════════════════════════════════════════════
# Expurgo LGPD
# ══════════════════════════════════════════════════════════════
class ExpurgoLGPDTests(BaseFacialTestCase):
    def test_desligado_ha_mais_de_30_dias_tem_biometria_expurgada(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.facial.tasks import expurgar_embeddings_desligados

        self.cadastrar(self.joao, 10)
        self.joao.data_demissao = timezone.localdate() - timedelta(days=31)
        self.joao.save(update_fields=["data_demissao"])

        resultado = expurgar_embeddings_desligados()

        self.joao.refresh_from_db()
        self.assertFalse(self.joao.face_registrada)
        self.assertIsNone(self.joao.face_embedding)
        self.assertEqual(resultado["expurgados"], 1)

    def test_desligado_recente_e_preservado(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.facial.tasks import expurgar_embeddings_desligados

        self.cadastrar(self.joao, 10)
        self.joao.data_demissao = timezone.localdate() - timedelta(days=5)
        self.joao.save(update_fields=["data_demissao"])

        expurgar_embeddings_desligados()

        self.joao.refresh_from_db()
        self.assertTrue(self.joao.face_registrada)

    def test_colaborador_ativo_nunca_e_expurgado(self):
        from apps.facial.tasks import expurgar_embeddings_desligados

        self.cadastrar(self.joao, 10)
        expurgar_embeddings_desligados()

        self.joao.refresh_from_db()
        self.assertTrue(self.joao.face_registrada)


# ══════════════════════════════════════════════════════════════
# Recadastro — o bug da "imutabilidade"
# ══════════════════════════════════════════════════════════════
class RecadastroTests(BaseFacialTestCase):
    def setUp(self):
        self.servico = FaceRecognitionService(provedor=ProvedorDeterministico())

    @staticmethod
    def foto(semente):
        """Fotos distintas: o provedor deterministico deriva o vetor dos bytes."""
        return imagem_bytes(ruido=semente + 1)

    """
    Adicionar fotos novas precisa mudar o reconhecimento.

    O sintoma relatado era que, depois do primeiro cadastro, o sistema
    "continuava aceitando apenas o registro anterior". Duas causas:
    a tela travava ao atingir o maximo de amostras, e mesmo passando por
    ela a media continuaria dominada pelas fotos antigas.
    """

    def amostras_ativas(self):
        return self.joao.registros_faciais.filter(ativo=True).count()

    def test_amostra_alem_do_limite_aposenta_a_mais_antiga(self):
        from django.conf import settings

        limite = settings.FACE_AMOSTRAS_MAXIMAS
        for indice in range(limite + 3):
            self.servico.cadastrar_amostra(
                self.joao, self.foto(indice), exigir_qualidade=False
            )

        self.assertEqual(self.amostras_ativas(), limite)
        # Nada e apagado: a trilha de qual foto gerou qual embedding
        # faz parte da auditoria do dado biometrico.
        self.assertEqual(
            self.joao.registros_faciais.count(), limite + 3
        )

    def test_a_mais_recente_sobrevive(self):
        from django.conf import settings

        for indice in range(settings.FACE_AMOSTRAS_MAXIMAS + 2):
            ultima = self.servico.cadastrar_amostra(
                self.joao, self.foto(indice), exigir_qualidade=False
            )
        ultima.refresh_from_db()
        self.assertTrue(ultima.ativo)

    def test_refazer_aposenta_tudo_e_zera_o_embedding(self):
        for indice in range(3):
            self.servico.cadastrar_amostra(
                self.joao, self.foto(indice), exigir_qualidade=False
            )
        self.servico.consolidar_cadastro(self.joao)
        self.joao.refresh_from_db()
        self.assertTrue(self.joao.face_registrada)

        total = self.servico.refazer_cadastro(self.joao)

        self.joao.refresh_from_db()
        self.assertEqual(total, 3)
        self.assertEqual(self.amostras_ativas(), 0)
        self.assertFalse(self.joao.face_registrada)

    def test_apos_refazer_um_novo_cadastro_funciona(self):
        """O caminho completo: cadastrar, refazer, cadastrar de novo."""
        for indice in range(3):
            self.servico.cadastrar_amostra(
                self.joao, self.foto(indice), exigir_qualidade=False
            )
        self.servico.refazer_cadastro(self.joao)

        for indice in range(10, 13):
            self.servico.cadastrar_amostra(
                self.joao, self.foto(indice), exigir_qualidade=False
            )
        total = self.servico.consolidar_cadastro(self.joao)

        self.joao.refresh_from_db()
        self.assertEqual(total, 3)
        self.assertTrue(self.joao.face_registrada)

    def test_consolidacao_usa_so_as_ativas(self):
        from django.conf import settings

        for indice in range(settings.FACE_AMOSTRAS_MAXIMAS + 2):
            self.servico.cadastrar_amostra(
                self.joao, self.foto(indice), exigir_qualidade=False
            )
        usadas = self.servico.consolidar_cadastro(self.joao)
        self.assertEqual(usadas, settings.FACE_AMOSTRAS_MAXIMAS)


# ══════════════════════════════════════════════════════════════
# Personalização do totem
# ══════════════════════════════════════════════════════════════
class PersonalizacaoTotemTests(BaseFacialTestCase):
    """
    A API já enviava as cores desde o começo, e o totem nunca as lia —
    o quiosque ficava azul-Kronus em toda empresa. Estes testes travam o
    contrato que a tela consome.
    """

    def setUp(self):
        from apps.totem.models import Totem

        self.totem = Totem.objects.create(
            identificador="PERSO-01", empresa=self.empresa
        )

    def config(self):
        from apps.api.serializers import ConfigTotemSerializer

        return ConfigTotemSerializer(self.totem).data

    def test_cores_da_empresa_vao_para_o_totem(self):
        self.empresa.cor_primaria = "#7C3AED"
        self.empresa.cor_secundaria = "#F59E0B"
        self.empresa.save(update_fields=["cor_primaria", "cor_secundaria"])

        empresa = self.config()["empresa"]
        self.assertEqual(empresa["cor_primaria"], "#7C3AED")
        self.assertEqual(empresa["cor_secundaria"], "#F59E0B")

    def test_ajustes_da_logo_vao_para_o_totem(self):
        self.empresa.logo_altura_px = 120
        self.empresa.logo_deslocamento_px = -30
        self.empresa.logo_css = "filter: brightness(0) invert(1);"
        self.empresa.save(update_fields=[
            "logo_altura_px", "logo_deslocamento_px", "logo_css"
        ])

        empresa = self.config()["empresa"]
        self.assertEqual(empresa["logo_altura_px"], 120)
        self.assertEqual(empresa["logo_deslocamento_px"], -30)
        self.assertIn("invert", empresa["logo_css"])

    def test_slides_vigentes_entram_na_ordem(self):
        from apps.clientes.models import SlideTotem

        SlideTotem.objects.create(
            empresa=self.empresa, imagem="idle_screens/b.jpg", ordem=1, legenda="B"
        )
        SlideTotem.objects.create(
            empresa=self.empresa, imagem="idle_screens/a.jpg", ordem=0, legenda="A"
        )
        legendas = [s["legenda"] for s in self.config()["empresa"]["slides"]]
        self.assertEqual(legendas, ["A", "B"])

    def test_slide_fora_do_periodo_nao_e_enviado(self):
        """Uma campanha com prazo sai da rotação sozinha."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.clientes.models import SlideTotem

        ontem = timezone.localdate() - timedelta(days=1)
        SlideTotem.objects.create(
            empresa=self.empresa, imagem="idle_screens/velho.jpg",
            legenda="Campanha encerrada", fim_exibicao=ontem,
        )
        self.assertEqual(self.config()["empresa"]["slides"], [])

    def test_mensagem_de_sucesso_personalizada(self):
        self.empresa.msg_sucesso_ponto = "Bom trabalho, {nome}!"
        self.empresa.save(update_fields=["msg_sucesso_ponto"])
        self.assertIn("{nome}", self.config()["empresa"]["mensagem_sucesso"])

    def test_liveness_reflete_a_configuracao_da_empresa(self):
        config = self.empresa.configuracao
        config.exigir_liveness = True
        config.save(update_fields=["exigir_liveness"])

        interface = self.config()["interface"]
        self.assertTrue(interface["liveness"])
        self.assertGreater(interface["liveness_quadros"], 0)

    def test_versao_da_configuracao_sobe_ao_personalizar(self):
        """É o que faz o totem se recarregar sem alguém ir até o tablet."""
        antes = self.empresa.config_versao
        self.empresa.marcar_configuracao_alterada()
        self.assertEqual(self.empresa.config_versao, antes + 1)

    def test_recarga_pontual_de_um_totem(self):
        self.assertIsNone(self.totem.recarga_solicitada_em)
        self.totem.solicitar_recarga()
        self.totem.refresh_from_db()
        self.assertIsNotNone(self.totem.recarga_solicitada_em)


class CamerasDiferentesTests(TestCase):
    """
    Cadastrar num aparelho e reconhecer em outro.

    E o caso mais comum na implantacao: o RH cadastra pela webcam do
    computador e a pessoa bate o ponto na camera do tablet. Cameras
    diferentes produzem vetores em regioes diferentes do espaco, e a
    media entre elas e um centroide que nao se parece com nenhuma — fica
    longe das duas ao mesmo tempo.
    """

    def setUp(self):
        import numpy as np

        from apps.clientes.models import Cliente, Empresa
        from apps.master.models import Plano

        plano = Plano.objects.create(nome="P", slug="p", max_colaboradores=50)
        cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.np = np

    def _vetor(self, semente, dimensao=512):
        """Vetor determinístico e normalizado."""
        gerador = self.np.random.default_rng(semente)
        v = gerador.normal(size=dimensao).astype(self.np.float32)
        return v / self.np.linalg.norm(v)

    def _colaborador(self, nome, cpf, amostras):
        from datetime import date

        from apps.facial.models import FaceRegistro
        from apps.rh.models import Colaborador

        colaborador = Colaborador.objects.create(
            empresa=self.empresa, cpf=cpf, nome_completo=nome,
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
            face_registrada=True,
        )
        for vetor in amostras:
            FaceRegistro.objects.create(
                colaborador=colaborador,
                embedding=vetor.tobytes(),
                ativo=True,
            )
        # A média, como o desenho antigo guardava.
        media = self.np.mean(amostras, axis=0)
        media = media / self.np.linalg.norm(media)
        colaborador.face_embedding = media.tobytes()
        colaborador.save(update_fields=["face_embedding"])
        return colaborador

    def test_reconhece_pela_amostra_da_camera_usada(self):
        """
        A pessoa é reconhecida se **qualquer** captura dela se parecer
        com o rosto do dia — não a média de todas.
        """
        from apps.facial.services import FaceRecognitionService

        webcam = self._vetor(1)
        tablet = self._vetor(2)   # câmera bem diferente
        self._colaborador("Ana", "52998224725", [webcam, tablet])

        servico = FaceRecognitionService()
        candidatos = servico.candidatos([self.empresa])

        # Rosto capturado no tablet, quase idêntico à amostra do tablet.
        do_dia = tablet + self._vetor(99) * 0.05
        do_dia = do_dia / self.np.linalg.norm(do_dia)

        _, distancia = servico._pontuar(do_dia, candidatos)[0]
        self.assertLess(
            distancia, servico.threshold,
            "a amostra da própria câmera deveria reconhecer",
        )

    def test_a_amostra_propria_fica_sempre_mais_perto_que_a_media(self):
        """
        A comparação por amostra **nunca** piora e costuma melhorar: a
        menor distância entre as capturas é, por definição, menor ou
        igual à distância até a média delas.

        Não é uma diferença cosmética — é a margem que separa reconhecer
        de mandar a pessoa digitar o CPF quando a câmera do dia não é a
        do cadastro.
        """
        from apps.facial.services import FaceRecognitionService

        servico = FaceRecognitionService()
        for semente in range(1, 20):
            webcam = self._vetor(semente)
            tablet = self._vetor(semente + 100)
            media = self.np.mean([webcam, tablet], axis=0)
            media = media / self.np.linalg.norm(media)

            do_dia = tablet + self._vetor(semente + 900) * 0.15
            do_dia = do_dia / self.np.linalg.norm(do_dia)

            por_media = servico._pontuar(do_dia, {1: [media]})[0][1]
            por_amostra = servico._pontuar(do_dia, {1: [webcam, tablet]})[0][1]

            self.assertLessEqual(
                por_amostra, por_media,
                f"semente {semente}: a amostra própria deveria estar mais perto",
            )

    def test_pessoa_diferente_continua_recusada(self):
        """Afrouxar a comparação não pode aceitar quem não é."""
        from apps.facial.services import FaceRecognitionService

        self._colaborador("Ana", "52998224725", [self._vetor(1), self._vetor(2)])
        servico = FaceRecognitionService()
        candidatos = servico.candidatos([self.empresa])

        outra_pessoa = self._vetor(500)
        _, distancia = servico._pontuar(outra_pessoa, candidatos)[0]
        self.assertGreater(distancia, servico.threshold)

    def test_cada_amostra_e_uma_referencia(self):
        from apps.facial.services import FaceRecognitionService

        colaborador = self._colaborador(
            "Ana", "52998224725", [self._vetor(1), self._vetor(2), self._vetor(3)]
        )
        candidatos = FaceRecognitionService().candidatos([self.empresa])

        # Três amostras, e só. A média não entra mais para quem tem
        # amostras: o centroide de poses diferentes não corresponde a
        # captura nenhuma e cai numa região genérica do espaço, perto de
        # rostos em geral — e como vale a menor distância, ele funcionava
        # como mais uma porta de entrada.
        self.assertEqual(len(candidatos[colaborador.pk]), 3)


class MensagemDeErroTests(TestCase):
    """
    A mensagem que chega a tela e escrita para quem esta na frente da
    camera, e nao para quem depura a biblioteca.

    O DeepFace fala em "numpy array" e em `enforce_detection param` — e
    esse texto chegou a aparecer no totem para quem estava cadastrando,
    que nao tem o que fazer com ele.
    """

    def test_a_mensagem_padrao_diz_o_que_fazer(self):
        from apps.facial.providers import NenhumRostoDetectado

        erro = NenhumRostoDetectado()
        self.assertIn("Aproxime-se", erro.mensagem)
        self.assertNotIn("numpy", erro.mensagem.lower())
        self.assertNotIn("enforce", erro.mensagem.lower())

    def test_o_texto_do_deepface_nao_e_repassado(self):
        # A deteccao falhando levanta a mensagem nossa, e nao a da
        # biblioteca — o `from` guarda a original para o log.
        import inspect
        from apps.facial import providers

        fonte = inspect.getsource(providers.DeepFaceProvider._detectar)
        self.assertIn("raise NenhumRostoDetectado() from ultima", fonte)
        self.assertNotIn("NenhumRostoDetectado(str(", fonte)

    def test_ha_um_detector_de_reserva(self):
        # O MTCNN perde rosto em contraluz e queixo levantado —
        # justamente as poses que o roteiro de cadastro pede.
        from apps.facial.providers import DeepFaceProvider

        self.assertTrue(DeepFaceProvider.DETECTOR_RESERVA)

    def test_falha_do_motor_nao_expoe_o_interno(self):
        import inspect
        from apps.facial import providers

        fonte = inspect.getsource(providers.DeepFaceProvider._detectar)
        self.assertIn("Falha ao processar a imagem. Tente novamente.", fonte)
