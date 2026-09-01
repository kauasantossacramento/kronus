"""
Kronus — tarefas assíncronas do módulo de ponto.

Agendadas em `config/celery.py` (Celery Beat).
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("kronus.ponto")


@shared_task(name="apps.ponto.tasks.fechar_banco_horas_do_dia")
def fechar_banco_horas_do_dia(data_iso: str = None):
    """
    Consolida o banco de horas de todos os colaboradores ativos.

    Executa às 23:59 (Seção 8.4 do plano). Aceita `data_iso` para
    reprocessar um dia específico.
    """
    from datetime import date

    from apps.clientes.models import Empresa
    from apps.ponto.services import ConsolidacaoService

    dia = date.fromisoformat(data_iso) if data_iso else timezone.localdate()
    total_colaboradores = 0
    total_empresas = 0

    empresas = Empresa.objects.filter(
        ativo=True, cliente__ativo=True, cliente__suspenso=False
    ).select_related("cliente", "config")

    for empresa in empresas:
        try:
            total_colaboradores += ConsolidacaoService.consolidar_empresa_no_dia(
                empresa, dia
            )
            total_empresas += 1
        except Exception:  # uma empresa com problema não derruba as demais
            logger.exception("Falha ao consolidar a empresa %s em %s", empresa.pk, dia)

    logger.info(
        "Banco de horas consolidado: %s empresa(s), %s colaborador(es), dia %s",
        total_empresas,
        total_colaboradores,
        dia,
    )
    return {
        "dia": dia.isoformat(),
        "empresas": total_empresas,
        "colaboradores": total_colaboradores,
    }


@shared_task(name="apps.ponto.tasks.reconsolidar_colaborador")
def reconsolidar_colaborador(colaborador_id: int, inicio_iso: str, fim_iso: str):
    """Recalcula um intervalo — usado após ajustes retroativos do RH."""
    from datetime import date

    from apps.ponto.services import ConsolidacaoService
    from apps.rh.models import Colaborador

    colaborador = Colaborador.objects.select_related("escala", "empresa").get(
        pk=colaborador_id
    )
    resultados = ConsolidacaoService.consolidar_periodo(
        colaborador, date.fromisoformat(inicio_iso), date.fromisoformat(fim_iso)
    )
    return {"colaborador": colaborador_id, "dias": len(resultados)}


@shared_task(name="apps.ponto.tasks.gerar_comprovante_pdf")
def gerar_comprovante_pdf(registro_id: int):
    """
    Gera e anexa o comprovante de registro em PDF.

    Roda fora do ciclo de request para não atrasar a batida — o
    colaborador vê a confirmação imediatamente e baixa o PDF depois.
    """
    from apps.ponto.models import RegistroPonto
    from apps.relatorios.generators import ComprovanteGenerator

    registro = RegistroPonto.objects.select_related(
        "colaborador", "empresa", "totem"
    ).get(pk=registro_id)
    if registro.comprovante_pdf:
        return {"registro": registro_id, "status": "ja_existente"}

    try:
        ComprovanteGenerator(registro).salvar()
        return {"registro": registro_id, "status": "gerado"}
    except Exception:
        logger.exception("Falha ao gerar comprovante do registro %s", registro_id)
        return {"registro": registro_id, "status": "erro"}


@shared_task(name="apps.ponto.tasks.verificar_integridade_das_cadeias")
def verificar_integridade_das_cadeias():
    """
    Auditoria periódica da cadeia de hashes de cada empresa
    (Portaria 671 — integridade dos registros).
    """
    from apps.clientes.models import Empresa
    from apps.ponto.services import RegistroPontoService

    problemas = []
    for empresa in Empresa.objects.filter(ativo=True):
        resultado = RegistroPontoService.verificar_cadeia(empresa)
        if not resultado["integra"]:
            logger.error(
                "Integridade comprometida na empresa %s: %s", empresa.pk, resultado
            )
            problemas.append({"empresa": empresa.pk, **resultado})
    return {"empresas_com_problema": problemas}


@shared_task(name="apps.ponto.tasks.limpar_registros_antigos_de_tentativa")
def limpar_registros_antigos_de_tentativa(dias: int = 90):
    """
    Descarta frames de tentativas de reconhecimento antigos.

    Minimização de dados da LGPD (Seção 10): a imagem só interessa para
    diagnóstico recente; a métrica permanece.
    """
    from apps.facial.models import TentativaReconhecimento

    limite = timezone.now() - timedelta(days=dias)
    antigas = TentativaReconhecimento.objects.filter(
        created_at__lt=limite, imagem__isnull=False
    ).exclude(imagem="")

    total = 0
    for tentativa in antigas.iterator():
        tentativa.imagem.delete(save=False)
        tentativa.imagem = None
        tentativa.save(update_fields=["imagem", "updated_at"])
        total += 1
    return {"imagens_removidas": total}


@shared_task(name="apps.ponto.tasks.verificar_relogio")
def verificar_relogio():
    """
    Confere o sincronismo com a Hora Legal Brasileira e alerta o Master.

    Anexo IX, requisito 2. Configurar o NTP atende metade do requisito; a
    outra metade e perceber quando ele para. Sem esta verificacao, o
    relogio pode derivar por semanas com as batidas sendo gravadas
    normalmente — com hora errada.
    """
    from apps.notificacoes.models import Notificacao
    from apps.notificacoes.services import criar, usuarios_master
    from apps.ponto.relogio import (
        DESVIO_ALERTA_SEGUNDOS,
        DESVIO_LEGAL_SEGUNDOS,
        estado_do_relogio,
    )

    estado = estado_do_relogio()

    if estado["dentro_do_limite"]:
        logger.debug(
            "Relogio sincronizado com %s, desvio %.3fs.",
            estado["servidor"], estado["desvio_segundos"],
        )
        return estado

    if estado["desvio_segundos"] is not None:
        titulo = "Relógio fora do sincronismo com a Hora Legal Brasileira"
        mensagem = (
            f"Desvio de {estado['desvio_segundos']:.1f}s "
            f"(alerta acima de {DESVIO_ALERTA_SEGUNDOS:.0f}s; "
            f"limite legal {DESVIO_LEGAL_SEGUNDOS:.0f}s). "
            f"Fonte: {estado['servidor'] or 'desconhecida'}. "
            "As marcações continuam sendo gravadas — com a hora errada."
        )
        nivel = Notificacao.Nivel.ALERTA
    else:
        titulo = "Não foi possível verificar o sincronismo do relógio"
        mensagem = (
            f"{estado['erro']}. O Anexo IX exige manter o relógio "
            "sincronizado com o Observatório Nacional; sem a verificação, "
            "uma deriva passaria despercebida."
        )
        nivel = Notificacao.Nivel.INFO

    logger.warning("Relogio: %s — %s", titulo, mensagem)
    for master in usuarios_master():
        criar(
            destinatario=master,
            evento=Notificacao.Evento.SISTEMA,
            titulo=titulo,
            mensagem=mensagem,
            nivel=nivel,
        )
    return estado


@shared_task(name="apps.ponto.tasks.resolver_endereco")
def resolver_endereco(registro_id: int) -> str:
    """
    Preenche o endereco de uma batida, depois de ela ja estar gravada.

    Fora do caminho da batida de proposito: a consulta ao servico de
    mapas depende de uma rede que nao e nossa, e ninguem deve esperar
    por ela para registrar ponto.

    Grava com `update` direto, sem passar pelo `save` do modelo: o
    registro de ponto e imutavel por determinacao legal, e o endereco e
    dado acessorio — resolve-lo nao pode disparar recalculo, hash novo
    nem sinal de alteracao.
    """
    from apps.ponto.geocodificacao import endereco_de
    from apps.ponto.models import RegistroPonto

    try:
        registro = RegistroPonto.objects.filter(pk=registro_id).first()
        if registro is None or registro.endereco:
            return ""
        if not registro.tem_geolocalizacao:
            return ""

        endereco = endereco_de(registro.latitude, registro.longitude)
        if endereco:
            RegistroPonto.objects.filter(pk=registro_id).update(endereco=endereco)
        return endereco
    except Exception:
        logger.exception("Falha ao resolver o endereço do registro %s", registro_id)
        return ""
