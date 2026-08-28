"""Kronus — rotinas de fundo do comercial."""
import logging

from celery import shared_task

logger = logging.getLogger("kronus.comercial")


@shared_task(name="apps.comercial.tasks.expirar_demonstracoes")
def expirar_demonstracoes():
    """
    Suspende as demonstracoes vencidas.

    Roda de hora em hora. O corte tambem e verificado no acesso, entao um
    atraso desta task nao libera ambiente vencido — ela existe para que o
    painel do Master mostre a situacao correta e para que o cliente
    suspenso pare de consumir recurso.
    """
    from apps.comercial.services import expirar_demonstracoes as expirar

    total = expirar()
    return {"expiradas": total}
