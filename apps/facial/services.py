"""
Kronus — serviço de reconhecimento facial.

`FaceRecognitionService` implementa o pipeline da Seção 8.2 do plano:

    CADASTRO
      1. o RH captura de 3 a 5 fotos em ângulos diferentes
      2. cada foto vira um embedding ArcFace de 512 dimensões
      3. o embedding médio é gravado em `rh.Colaborador.face_embedding`
      4. as fotos originais podem ser descartadas (minimização, LGPD)

    RECONHECIMENTO
      1. o totem envia o frame JPEG
      2. o servidor gera o embedding do frame
      3. compara por distância cosseno contra os colaboradores
         autorizados naquele equipamento
      4. abaixo do threshold (0,68) há match; acima, "não identificado"

O conjunto de candidatos fica em cache no Redis: sem ele, cada batida
faria um SELECT de todos os embeddings da empresa — que é justamente o
gargalo que impediria o alvo de "menos de 2 segundos".
"""
import logging
import time

import numpy as np
from django.conf import settings
from django.core.cache import cache

from apps.facial.models import FaceRegistro, TentativaReconhecimento
from apps.facial.processors import (
    ImagemInvalida,
    calcular_qualidade,
    como_arquivo,
    preparar,
    qualidade_aceitavel,
)
from apps.facial.providers import (
    ErroReconhecimento,
    ProvedorFacial,
    obter_provedor,
)

logger = logging.getLogger("kronus.facial")

#: Tempo de vida do cache de embeddings por escopo de reconhecimento.
CACHE_TTL_SEGUNDOS = 300
CACHE_PREFIXO = "kronus:faces"


class ResultadoReconhecimento:
    """Resultado de uma tentativa, pronto para virar resposta de API."""

    def __init__(
        self,
        *,
        identificado: bool,
        colaborador=None,
        distancia: float = None,
        confianca: float = None,
        candidatos: int = 0,
        tempo_ms: int = 0,
        motivo: str = "",
        codigo: str = "",
    ):
        self.identificado = identificado
        self.colaborador = colaborador
        self.distancia = distancia
        self.confianca = confianca
        self.candidatos = candidatos
        self.tempo_ms = tempo_ms
        self.motivo = motivo
        self.codigo = codigo

    def __repr__(self):  # pragma: no cover
        alvo = self.colaborador or "—"
        return f"<ResultadoReconhecimento {alvo} d={self.distancia} {self.tempo_ms}ms>"


class FaceRecognitionService:
    """Cadastro e reconhecimento facial."""

    def __init__(self, provedor: ProvedorFacial = None, threshold: float = None):
        self.provedor = provedor or obter_provedor()
        self.threshold = (
            threshold
            if threshold is not None
            else settings.FACE_RECOGNITION_THRESHOLD
        )

    @property
    def disponivel(self) -> bool:
        return self.provedor.disponivel

    # ══════════════════════════════════════════════════════════
    # Cadastro
    # ══════════════════════════════════════════════════════════
    def cadastrar_amostra(
        self,
        colaborador,
        imagem,
        *,
        angulo: str = FaceRegistro.Angulo.FRONTAL,
        guardar_imagem: bool = True,
        exigir_qualidade: bool = True,
    ) -> FaceRegistro:
        """
        Processa e grava uma amostra facial.

        Levanta `ImagemInvalida` ou `ErroReconhecimento` quando a foto
        não serve — a interface converte isso em orientação ao operador
        ("aproxime-se", "melhore a iluminação").
        """
        imagem_bytes = preparar(imagem)
        qualidade = calcular_qualidade(imagem_bytes)

        if exigir_qualidade and not qualidade_aceitavel(qualidade):
            raise ImagemInvalida(
                "Foto com qualidade insuficiente. Verifique a iluminação e "
                "mantenha a câmera estável.",
                codigo="qualidade_baixa",
            )

        vetor = self.provedor.gerar_embedding(imagem_bytes)

        registro = FaceRegistro(
            colaborador=colaborador,
            angulo=angulo,
            modelo=settings.DEEPFACE_MODEL,
            detector=settings.DEEPFACE_DETECTOR,
            qualidade=qualidade,
        )
        registro.definir_embedding(vetor, salvar=False)

        if guardar_imagem and not colaborador.empresa.configuracao.apagar_foto_apos_encoding:
            registro.imagem = como_arquivo(
                imagem_bytes,
                f"{colaborador.cpf}_{angulo}_{int(time.time())}.jpg",
            )
        registro.save()

        logger.info(
            "Amostra facial cadastrada: colaborador=%s angulo=%s qualidade=%.1f",
            colaborador.pk,
            angulo,
            qualidade,
        )
        return registro

    def consolidar_cadastro(self, colaborador) -> int:
        """
        Recalcula o embedding médio do colaborador a partir das amostras
        ativas e devolve quantas foram usadas.
        """
        vetores = [
            registro.obter_embedding()
            for registro in colaborador.registros_faciais.filter(ativo=True)
            if registro.embedding
        ]
        vetores = [v for v in vetores if v is not None and v.size]

        if not vetores:
            colaborador.limpar_biometria()
            self.invalidar_cache(colaborador.empresa_id)
            return 0

        colaborador.definir_embedding(self.provedor.media_normalizada(vetores))
        self.invalidar_cache(colaborador.empresa_id)
        logger.info(
            "Cadastro facial consolidado: colaborador=%s amostras=%s",
            colaborador.pk,
            len(vetores),
        )
        return len(vetores)

    def remover_cadastro(self, colaborador):
        """Direito de exclusão da LGPD (Seção 10 do plano)."""
        empresa_id = colaborador.empresa_id
        colaborador.limpar_biometria()
        self.invalidar_cache(empresa_id)

    # ══════════════════════════════════════════════════════════
    # Reconhecimento
    # ══════════════════════════════════════════════════════════
    def reconhecer(
        self,
        imagem,
        *,
        empresas,
        totem=None,
        registrar_tentativa: bool = True,
        guardar_frame: bool = False,
        ip: str = None,
    ) -> ResultadoReconhecimento:
        """
        Identifica um rosto entre os colaboradores das `empresas`.

        `empresas` é sempre um escopo explícito — nunca "todos os
        colaboradores da plataforma". É o que materializa a regra 12 da
        Seção 14: o colaborador só é reconhecido nos totens da sua
        empresa ou do grupo vinculado.
        """
        inicio = time.perf_counter()
        empresa_principal = totem.empresa if totem else _primeira(empresas)

        def concluir(resultado: ResultadoReconhecimento, frame: bytes = None):
            resultado.tempo_ms = int((time.perf_counter() - inicio) * 1000)
            if registrar_tentativa and empresa_principal is not None:
                self._registrar_tentativa(
                    resultado,
                    empresa=empresa_principal,
                    totem=totem,
                    frame=frame if guardar_frame else None,
                    ip=ip,
                )
            return resultado

        # -- 1. preparo da imagem ------------------------------
        try:
            frame = preparar(imagem)
        except ImagemInvalida as erro:
            return concluir(
                ResultadoReconhecimento(
                    identificado=False, motivo=erro.mensagem, codigo=erro.codigo
                )
            )

        # -- 2. embedding do frame -----------------------------
        try:
            vetor = self.provedor.gerar_embedding(frame)
        except ErroReconhecimento as erro:
            return concluir(
                ResultadoReconhecimento(
                    identificado=False, motivo=erro.mensagem, codigo=erro.codigo
                ),
                frame,
            )

        # -- 3. comparação contra os candidatos ----------------
        candidatos = self.candidatos(empresas)
        if not candidatos:
            return concluir(
                ResultadoReconhecimento(
                    identificado=False,
                    motivo="Nenhum colaborador com cadastro facial neste equipamento.",
                    codigo="sem_candidatos",
                ),
                frame,
            )

        melhor_id, melhor_distancia = self._mais_proximo(vetor, candidatos)

        if melhor_distancia >= self.threshold:
            return concluir(
                ResultadoReconhecimento(
                    identificado=False,
                    distancia=round(melhor_distancia, 4),
                    candidatos=len(candidatos),
                    motivo="Rosto não identificado.",
                    codigo="nao_identificado",
                ),
                frame,
            )

        from apps.rh.models import Colaborador

        colaborador = (
            Colaborador.objects.select_related("empresa", "escala")
            .filter(pk=melhor_id)
            .first()
        )
        if colaborador is None:  # cache defasado
            self.invalidar_cache(empresa_principal.pk if empresa_principal else None)
            return concluir(
                ResultadoReconhecimento(
                    identificado=False,
                    motivo="Cadastro não encontrado. Tente novamente.",
                    codigo="cadastro_removido",
                ),
                frame,
            )

        return concluir(
            ResultadoReconhecimento(
                identificado=True,
                colaborador=colaborador,
                distancia=round(melhor_distancia, 4),
                confianca=self.provedor.confianca(melhor_distancia, self.threshold),
                candidatos=len(candidatos),
            ),
            frame,
        )

    def _mais_proximo(self, vetor, candidatos: dict) -> tuple[int, float]:
        """
        Compara o vetor contra todos os candidatos de uma vez.

        A operação vetorizada com numpy mantém a busca em milissegundos
        mesmo com milhares de colaboradores — um laço em Python não
        sustentaria o alvo de resposta do totem.
        """
        ids = list(candidatos.keys())
        matriz = np.vstack([candidatos[pk] for pk in ids]).astype(np.float32)

        vetor = np.asarray(vetor, dtype=np.float32)
        norma_vetor = np.linalg.norm(vetor)
        normas = np.linalg.norm(matriz, axis=1)
        normas[normas == 0] = 1e-9
        if norma_vetor == 0:
            norma_vetor = 1e-9

        similaridades = (matriz @ vetor) / (normas * norma_vetor)
        distancias = 1.0 - similaridades

        indice = int(np.argmin(distancias))
        return ids[indice], float(distancias[indice])

    # ══════════════════════════════════════════════════════════
    # Cache de candidatos
    # ══════════════════════════════════════════════════════════
    def candidatos(self, empresas) -> dict:
        """
        Mapa `{colaborador_id: embedding}` das empresas informadas.

        Cada empresa tem a própria entrada de cache, o que permite
        invalidar apenas a empresa alterada quando um cadastro muda.
        """
        resultado = {}
        for empresa_id in _ids(empresas):
            resultado.update(self._candidatos_da_empresa(empresa_id))
        return resultado

    def _candidatos_da_empresa(self, empresa_id: int) -> dict:
        chave = f"{CACHE_PREFIXO}:empresa:{empresa_id}"
        cacheado = cache.get(chave)
        if cacheado is not None:
            return {pk: np.frombuffer(dados, dtype=np.float32) for pk, dados in cacheado}

        from apps.rh.models import Colaborador

        linhas = (
            Colaborador.objects.filter(
                empresa_id=empresa_id,
                ativo=True,
                face_registrada=True,
                deleted_at__isnull=True,
            )
            .exclude(face_embedding__isnull=True)
            .values_list("pk", "face_embedding")
        )

        # Guardamos bytes no cache — arrays numpy não são serializáveis
        # de forma compacta pelo backend do Django.
        serializado = [(pk, bytes(dados)) for pk, dados in linhas if dados]
        cache.set(chave, serializado, CACHE_TTL_SEGUNDOS)
        return {pk: np.frombuffer(dados, dtype=np.float32) for pk, dados in serializado}

    @staticmethod
    def invalidar_cache(empresa_id=None):
        """Chamado sempre que um cadastro facial muda."""
        if empresa_id is None:
            return
        cache.delete(f"{CACHE_PREFIXO}:empresa:{empresa_id}")

    # ══════════════════════════════════════════════════════════
    # Auditoria
    # ══════════════════════════════════════════════════════════
    def _registrar_tentativa(self, resultado, *, empresa, totem, frame, ip):
        """
        Grava a tentativa para métrica, auditoria e suporte.

        Nunca deixa a auditoria derrubar o reconhecimento: uma falha aqui
        impediria o colaborador de bater o ponto.
        """
        if resultado.identificado:
            situacao = TentativaReconhecimento.Resultado.IDENTIFICADO
        elif resultado.codigo == "sem_rosto":
            situacao = TentativaReconhecimento.Resultado.SEM_ROSTO
        elif resultado.codigo == "multiplos_rostos":
            situacao = TentativaReconhecimento.Resultado.MULTIPLOS_ROSTOS
        elif resultado.codigo in ("nao_identificado", "sem_candidatos"):
            situacao = TentativaReconhecimento.Resultado.NAO_IDENTIFICADO
        else:
            situacao = TentativaReconhecimento.Resultado.ERRO

        try:
            tentativa = TentativaReconhecimento(
                totem=totem,
                empresa=empresa,
                colaborador=resultado.colaborador,
                resultado=situacao,
                distancia=resultado.distancia,
                confianca=resultado.confianca,
                tempo_processamento_ms=resultado.tempo_ms,
                candidatos_avaliados=resultado.candidatos,
                ip=ip,
            )
            if frame:
                tentativa.imagem = como_arquivo(
                    frame, f"tentativa_{int(time.time() * 1000)}.jpg"
                )
            tentativa.save()
        except Exception:
            logger.exception("Falha ao registrar tentativa de reconhecimento")


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _ids(empresas) -> list[int]:
    """Aceita queryset, lista de objetos ou lista de ids."""
    if hasattr(empresas, "values_list"):
        return list(empresas.values_list("pk", flat=True))
    return [getattr(item, "pk", item) for item in empresas]


def _primeira(empresas):
    if hasattr(empresas, "first"):
        return empresas.first()
    return empresas[0] if empresas else None


# ══════════════════════════════════════════════════════════════
# Fallback por CPF (regra 6 da Seção 14)
# ══════════════════════════════════════════════════════════════
def identificar_por_cpf(cpf: str, data_nascimento, empresas):
    """
    Identificação alternativa do totem.

    O fallback existe porque o reconhecimento facial pode falhar por
    iluminação, máscara, óculos ou simples ausência de cadastro — e o
    plano determina que o totem **sempre** permita registrar o ponto.

    A data de nascimento é o segundo fator: sem ela, bastaria conhecer o
    CPF de um colega para bater o ponto no lugar dele.
    """
    from apps.core.utils import apenas_digitos
    from apps.rh.models import Colaborador

    digitos = apenas_digitos(cpf)
    if len(digitos) != 11:
        return None

    return (
        Colaborador.objects.select_related("empresa", "escala")
        .filter(
            cpf=digitos,
            data_nascimento=data_nascimento,
            ativo=True,
            deleted_at__isnull=True,
            empresa_id__in=_ids(empresas),
        )
        .first()
    )
