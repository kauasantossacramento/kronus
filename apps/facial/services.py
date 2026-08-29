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
        self.margem_minima = settings.FACE_MARGEM_MINIMA

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
        self._recusar_se_for_outro_rosto(colaborador, vetor)

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

        self._aposentar_excedentes(colaborador)

        logger.info(
            "Amostra facial cadastrada: colaborador=%s angulo=%s qualidade=%.1f",
            colaborador.pk,
            angulo,
            qualidade,
        )
        return registro

    def _recusar_se_for_outro_rosto(self, colaborador, vetor) -> None:
        """
        Recusa uma amostra que não se pareça com as já cadastradas.

        Existe por um caso real: a sexta captura de um colaborador entrou
        a 0,70 das cinco anteriores — distância de pessoa diferente.
        Provavelmente outra pessoa no quadro, ou um recorte errado.
        Ninguém notou, porque nada no cadastro compara a amostra nova com
        o que já estava lá.

        O estrago aparece depois, e longe daqui: como o reconhecimento
        fica com a menor distância entre as amostras, aquela captura
        passou a aceitar rostos que não eram do titular.

        A comparação é contra a **mediana** das distâncias, e não a
        menor: bastaria uma amostra ruim já cadastrada para avalizar a
        próxima, e o erro se propagaria.
        """
        if not getattr(self.provedor, "modela_rostos", True):
            return

        anteriores = [
            registro.obter_embedding()
            for registro in FaceRegistro.objects.filter(
                colaborador=colaborador, ativo=True
            )
        ]
        anteriores = [v for v in anteriores if v is not None and len(v)]
        # Tres ou mais: com duas, a mediana e ruidosa demais para recusar
        # a captura de alguem na frente da camera.
        if len(anteriores) < 3:
            return

        distancias = sorted(self._distancia(vetor, v) for v in anteriores)
        mediana = distancias[len(distancias) // 2]
        limite = settings.FACE_DISTANCIA_MAXIMA_AMOSTRA
        if mediana > limite:
            raise ImagemInvalida(
                "Esta foto não parece a mesma pessoa das anteriores. "
                "Confira se há outra pessoa no enquadramento e repita a "
                "captura.",
                codigo="rosto_divergente",
            )

    @staticmethod
    def _aposentar_excedentes(colaborador):
        """
        Mantem apenas as N amostras mais recentes ativas.

        Sem isto, adicionar fotos novas nao muda o reconhecimento: a
        media fica dominada pelas amostras antigas. Quem cadastrou com
        luz ruim e depois tentou corrigir com fotos boas via o sistema
        continuar recusando — foi exatamente o sintoma relatado.

        As excedentes sao **desativadas, nao apagadas**: o historico de
        qual foto gerou qual embedding faz parte da trilha de auditoria
        do dado biometrico.
        """
        limite = getattr(settings, "FACE_AMOSTRAS_MAXIMAS", 5)
        ativas = list(
            colaborador.registros_faciais.filter(ativo=True).order_by("-created_at")
        )
        excedentes = ativas[limite:]
        for registro in excedentes:
            registro.ativo = False
            registro.save(update_fields=["ativo", "updated_at"])
        return len(excedentes)

    def refazer_cadastro(self, colaborador) -> int:
        """
        Aposenta todas as amostras atuais para um cadastro do zero.

        Usado quando a pessoa mudou de aparencia (barba, oculos, corte)
        ou quando o cadastro original saiu ruim. Desativa em vez de
        apagar, e zera o embedding consolidado para que o colaborador
        nao seja reconhecido por um cadastro que estamos refazendo.
        """
        total = colaborador.registros_faciais.filter(ativo=True).update(ativo=False)
        colaborador.limpar_biometria()
        self.invalidar_cache(colaborador.empresa_id)
        logger.info(
            "Cadastro facial reiniciado: colaborador=%s amostras aposentadas=%s",
            colaborador.pk, total,
        )
        return total

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

        pontos = self._pontuar(vetor, candidatos)
        melhor_id, melhor_distancia = pontos[0]

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

        # Depois do limiar, e nao antes: um rosto desconhecido fica longe
        # de todo mundo, e as distancias de dois desconhecidos podem ser
        # parecidas entre si sem que exista ambiguidade alguma. A margem
        # so tem sentido entre candidatos que ja passariam.
        if len(pontos) > 1:
            _, segunda = pontos[1]
            if segunda - melhor_distancia < self.margem_minima:
                return concluir(
                    ResultadoReconhecimento(
                        identificado=False,
                        distancia=round(melhor_distancia, 4),
                        candidatos=len(candidatos),
                        motivo=(
                            "Não foi possível distinguir com segurança. "
                            "Use o CPF."
                        ),
                        codigo="ambiguo",
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

    def _pontuar(self, vetor, candidatos: dict) -> list[tuple[int, float]]:
        """
        Distância de cada colaborador ao rosto, do mais próximo ao menos.

        Vale a **menor** distância entre as amostras da pessoa, e não a
        distância até a média delas. A média não funciona no caso mais
        comum — cadastrar pela webcam e reconhecer no tablet: câmeras
        diferentes produzem vetores em regiões diferentes, e o centroide
        entre elas não se parece com nenhuma.

        A menor distância tem um risco conhecido: uma amostra ruim passa
        a autorizar sozinha. Aconteceu em produção — uma captura de outro
        rosto entrou no cadastro e um visitante foi identificado como o
        titular. A proteção contra isso **não** está aqui, e sim em
        `_amostras_coerentes`, que impede a amostra contaminada de
        participar.

        Foi uma tentativa de resolver isso aqui, exigindo a segunda menor
        distância. Não se sustentou: o roteiro de cadastro pede cinco
        poses, e poses da mesma pessoa ficam a 0,38–0,48 entre si. Exigir
        que duas concordassem punia justamente o cadastro bem feito — o
        titular passou a ser reconhecido no limite do limiar, quando
        antes era reconhecido com folga.
        """
        pontos = []
        for pk, vetores in candidatos.items():
            amostras = vetores if isinstance(vetores, list) else [vetores]
            pontos.append(
                (pk, min(self._distancia(vetor, a) for a in amostras))
            )

        pontos.sort(key=lambda par: par[1])
        return pontos

    @classmethod
    def _amostras_coerentes(cls, amostras: list) -> list:
        """
        Descarta a amostra que não combina com as demais do titular.

        Uma captura de outro rosto — ou um recorte errado — não é
        diversidade de pose: é contaminação. E como o reconhecimento fica
        com a menor distância, ela vira uma porta aberta para quem se
        pareça com ela.

        A medida é a **mediana** das distâncias às irmãs, porque separa
        bem no caso real: entre poses legítimas fica em 0,38–0,48; a
        contaminada medida em produção estava em 0,70.

        Só age com três ou mais amostras. Com duas não há maioria: apontar
        a divergente seria escolher uma das duas no cara ou coroa.
        """
        if len(amostras) < 3:
            return amostras

        limite = settings.FACE_DISTANCIA_MAXIMA_AMOSTRA
        mantidas = []
        for i, amostra in enumerate(amostras):
            outras = sorted(
                cls._distancia(amostra, v)
                for j, v in enumerate(amostras) if j != i
            )
            if outras[len(outras) // 2] <= limite:
                mantidas.append(amostra)

        # Nunca deixar o colaborador sem referencia: se quase tudo
        # diverge, o cadastro inteiro esta errado, e recusar tudo aqui
        # so trocaria o erro por um colaborador que nao bate ponto.
        return mantidas if len(mantidas) >= 2 else amostras

    @staticmethod
    def _distancia(vetor, amostra) -> float:
        a = np.asarray(vetor, dtype=np.float32)
        b = np.asarray(amostra, dtype=np.float32)
        na = float(np.linalg.norm(a)) or 1e-9
        nb = float(np.linalg.norm(b)) or 1e-9
        return 1.0 - float(a @ b) / (na * nb)

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
        """
        Todas as amostras ativas de cada colaborador da empresa.

        Devolve `{colaborador_id: [vetor, vetor, ...]}` — cada captura
        entra como referência própria, e não diluída numa média.
        """
        chave = f"{CACHE_PREFIXO}:empresa:{empresa_id}:v3"
        cacheado = cache.get(chave)
        if cacheado is not None:
            return self._limpar(cacheado)

        from apps.facial.models import FaceRegistro
        from apps.rh.models import Colaborador

        elegiveis = Colaborador.objects.filter(
            empresa_id=empresa_id,
            ativo=True,
            face_registrada=True,
            deleted_at__isnull=True,
        )

        por_colaborador = {}

        # As amostras individuais sao a referencia principal.
        amostras = (
            FaceRegistro.objects.filter(colaborador__in=elegiveis, ativo=True)
            .exclude(embedding__isnull=True)
            .values_list("colaborador_id", "embedding")
        )
        for pk, dados in amostras:
            if dados:
                por_colaborador.setdefault(pk, []).append(bytes(dados))

        # A media entra **so** para quem nao tem amostra individual —
        # cadastros anteriores a elas serem guardadas.
        #
        # Somar a media a quem ja tem amostras acrescentava um vetor que
        # nao corresponde a captura nenhuma: o centroide de cinco poses
        # cai numa regiao generica do espaco, perto de rostos em geral. E
        # como vale a menor distancia, esse ponto medio funcionava como
        # mais uma porta.
        sem_amostras = [pk for pk in elegiveis.values_list("pk", flat=True)
                        if pk not in por_colaborador]
        if sem_amostras:
            for pk, dados in elegiveis.filter(pk__in=sem_amostras).exclude(
                face_embedding__isnull=True
            ).values_list("pk", "face_embedding"):
                if dados:
                    por_colaborador.setdefault(pk, []).append(bytes(dados))

        serializado = list(por_colaborador.items())
        cache.set(chave, serializado, CACHE_TTL_SEGUNDOS)
        return self._limpar(serializado)

    @classmethod
    def _limpar(cls, serializado) -> dict:
        """Converte o cache em vetores, sem as amostras incoerentes."""
        return {
            pk: cls._amostras_coerentes(
                [np.frombuffer(d, dtype=np.float32) for d in dados]
            )
            for pk, dados in serializado
        }

    @staticmethod
    def invalidar_cache(empresa_id=None):
        """Chamado sempre que um cadastro facial muda."""
        if empresa_id is None:
            return
        cache.delete(f"{CACHE_PREFIXO}:empresa:{empresa_id}")
        cache.delete(f"{CACHE_PREFIXO}:empresa:{empresa_id}:v2")
        cache.delete(f"{CACHE_PREFIXO}:empresa:{empresa_id}:v3")

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
        elif resultado.codigo in ("nao_identificado", "sem_candidatos", "ambiguo"):
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
