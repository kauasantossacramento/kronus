"""
Kronus — tarefas assíncronas do reconhecimento facial.

A geração de embedding leva de centenas de milissegundos a alguns
segundos. No cadastro isso pode rodar fora do ciclo de request; no
reconhecimento do totem, não — lá a resposta é síncrona por natureza.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("kronus.facial")


@shared_task(name="apps.facial.tasks.expurgar_embeddings_desligados")
def expurgar_embeddings_desligados():
    """
    Apaga dados biométricos de colaboradores desligados.

    Regra 5 da Seção 14 e política de retenção da Seção 10: os embeddings
    são descartados N dias após o desligamento (padrão 30, configurável
    por empresa). Dado biométrico é sensível sob a LGPD — mantê-lo além
    da finalidade é irregular, então este expurgo é obrigatório, não
    higiene opcional.
    """
    from apps.facial.services import FaceRecognitionService
    from apps.rh.models import Colaborador

    hoje = timezone.localdate()
    expurgados = 0
    empresas_afetadas = set()

    candidatos = Colaborador.objects.filter(
        face_registrada=True, data_demissao__isnull=False
    ).select_related("empresa", "empresa__config")

    for colaborador in candidatos.iterator():
        config = getattr(colaborador.empresa, "config", None)
        dias = (
            config.retencao_faces_dias
            if config
            else settings.FACE_RETENTION_DAYS_AFTER_TERMINATION
        )
        if colaborador.data_demissao + timedelta(days=dias) > hoje:
            continue

        try:
            colaborador.limpar_biometria()
            empresas_afetadas.add(colaborador.empresa_id)
            expurgados += 1
            logger.info(
                "Biometria expurgada: colaborador=%s desligado em %s (retenção %s dias)",
                colaborador.pk,
                colaborador.data_demissao,
                dias,
            )
        except Exception:
            logger.exception("Falha ao expurgar biometria do colaborador %s", colaborador.pk)

    for empresa_id in empresas_afetadas:
        FaceRecognitionService.invalidar_cache(empresa_id)

    return {"expurgados": expurgados, "empresas": len(empresas_afetadas)}


@shared_task(name="apps.facial.tasks.processar_amostra")
def processar_amostra(colaborador_id: int, imagem_base64: str, angulo: str = "frontal"):
    """
    Gera o embedding de uma amostra fora do ciclo de request.

    Útil na importação em lote de fotos; o cadastro pela webcam é
    síncrono, porque o operador precisa do retorno imediato para saber
    se deve repetir a captura.
    """
    from apps.facial.services import FaceRecognitionService
    from apps.rh.models import Colaborador

    colaborador = Colaborador.objects.select_related("empresa").get(pk=colaborador_id)
    servico = FaceRecognitionService()

    try:
        registro = servico.cadastrar_amostra(
            colaborador, imagem_base64, angulo=angulo
        )
    except Exception as erro:
        logger.warning("Amostra recusada para o colaborador %s: %s", colaborador_id, erro)
        return {"colaborador": colaborador_id, "status": "recusada", "motivo": str(erro)}

    total = servico.consolidar_cadastro(colaborador)
    return {"colaborador": colaborador_id, "amostra": registro.pk, "amostras": total}


@shared_task(name="apps.facial.tasks.reconsolidar_cadastros")
def reconsolidar_cadastros(empresa_id: int = None):
    """
    Recalcula o embedding médio de todos os colaboradores.

    Necessário após trocar de modelo (ArcFace → outro) ou ao corrigir um
    lote de amostras. Sem isso, embeddings de modelos diferentes ficariam
    misturados no mesmo espaço vetorial — e nada mais bateria.
    """
    from apps.facial.services import FaceRecognitionService
    from apps.rh.models import Colaborador

    servico = FaceRecognitionService()
    consulta = Colaborador.objects.filter(face_registrada=True)
    if empresa_id:
        consulta = consulta.filter(empresa_id=empresa_id)

    total = 0
    for colaborador in consulta.select_related("empresa").iterator():
        servico.consolidar_cadastro(colaborador)
        total += 1
    return {"colaboradores": total}


@shared_task(
    name="apps.facial.tasks.gerar_embedding_remoto",
    queue="facial",
    time_limit=60,
    soft_time_limit=45,
)
def gerar_embedding_remoto(imagem_b64: str) -> dict:
    """
    Gera um embedding no worker dedicado.

    **Por que existe.** O ArcFace ocupa ~1,1 GB de RAM residente, e esse
    custo é *por processo*. Com o reconhecimento em linha no worker web,
    cada worker que atendesse um rosto carregaria a sua própria cópia:
    dois workers = 2,2 GB, o que num servidor de 3,9 GB empurra o
    Postgres para o swap.

    Concentrando aqui, o modelo carrega **uma vez só**, num worker Celery
    de concorrência 1. Os workers web nunca importam TensorFlow.

    O custo dessa escolha é a ida e volta pelo Redis — na ordem de
    dezenas de milissegundos contra os ~217 ms da inferência. Vale.

    A imagem trafega em base64 porque o serializador do Celery é JSON:
    trocá-lo por pickle para economizar 33% de tamanho abriria execução
    remota de código a quem alcançasse o Redis.
    """
    import base64

    from apps.facial.providers import DeepFaceProvider

    dados = base64.b64decode(imagem_b64)
    # Direto no DeepFace: passar por `obter_provedor` correria o risco de
    # o worker estar configurado como delegado e chamar a si mesmo.
    vetor = DeepFaceProvider().gerar_embedding(dados)
    return {"embedding": [float(x) for x in vetor]}
