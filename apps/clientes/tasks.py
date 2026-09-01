"""
Kronus — tarefas dos clientes.

Por ora, uma so: manter o acervo da tela ociosa vivo.
"""
import logging

from celery import shared_task

logger = logging.getLogger("kronus.ambiente")


@shared_task(name="apps.clientes.tasks.renovar_acervo_ambiente")
def renovar_acervo_ambiente() -> dict:
    """
    Busca imagens novas para os periodos que estiverem abaixo do teto.

    Semanal, e nao diaria: a mesma paisagem numa tela de recepcao passa
    despercebida por dias, e trocar todo dia gastaria banda de totens em
    rede fraca sem que ninguem notasse a diferenca.

    Acrescenta, nunca substitui — o que o master curou a mao continua.
    Falha aqui nao derruba nada: o acervo antigo segue na tela.
    """
    from django.core.management import call_command

    try:
        call_command("importar_imagens_ambiente", confirmar=True, verbosity=0)
        from apps.clientes.ambiente import ImagemAmbiente

        total = ImagemAmbiente.objects.filter(ativo=True).count()
        logger.info("Acervo da tela ociosa renovado: %s imagem(ns).", total)
        return {"imagens": total}
    except Exception:
        logger.exception("Falha ao renovar o acervo da tela ociosa.")
        return {"imagens": None}
