"""
Kronus — tarefas do RH.

Por ora, uma so: os parabens do dia.
"""
import logging

from celery import shared_task

logger = logging.getLogger("kronus.rh")


@shared_task(name="apps.rh.tasks.parabenizar_aniversariantes")
def parabenizar_aniversariantes() -> dict:
    """
    Manda os parabens de hoje, em nome da empresa.

    **Em nome da empresa, e nao do Kronus.** Quem faz aniversario
    trabalha para a empresa; um "parabens" assinado pelo fornecedor do
    ponto eletronico seria estranho e frio. A marca do Kronus fica no
    rodape, onde a assinatura de quem construiu a ferramenta pertence.

    Roda uma vez por dia, de manha. Uma falha de envio nao repete: um
    parabens duplicado e pior que um parabens que faltou, e reenviar sem
    saber o que ja saiu e como isso acontece.

    So envia para quem tem e-mail. A tela do totem alcanca quem nao tem —
    as duas coisas se completam em vez de se substituirem.
    """
    from datetime import date

    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    from apps.clientes.models import Empresa
    from apps.rh.models import Colaborador

    hoje = date.today()
    enviados, falhas, sem_email = 0, 0, 0

    pessoas = (
        Colaborador.objects.filter(
            ativo=True,
            data_nascimento__day=hoje.day,
            data_nascimento__month=hoje.month,
            empresa__ativo=True,
        )
        .select_related("empresa")
    )

    for pessoa in pessoas:
        if not (pessoa.email or "").strip():
            sem_email += 1
            continue
        empresa = pessoa.empresa
        primeiro = (pessoa.nome_exibicao or "").split()[0].title()
        try:
            contexto = {
                "primeiro_nome": primeiro,
                "colaborador": pessoa,
                "empresa": empresa,
                "KRONUS": settings.KRONUS,
            }
            html = render_to_string("rh/email/aniversario.html", contexto)
            texto = (
                f"Feliz aniversário, {primeiro}!\n\n"
                f"A equipe da {empresa.nome_exibicao} deseja um dia muito "
                "especial e um ano cheio de conquistas.\n\n"
                "— Enviado pelo Kronus, o ponto eletrônico da sua empresa."
            )
            # `from` da empresa no nome, remetente tecnico do Kronus: o
            # dominio precisa ser um que o servidor esteja autorizado a
            # assinar, ou o e-mail cai em spam.
            mensagem = EmailMultiAlternatives(
                subject=f"Feliz aniversário, {primeiro}!",
                body=texto,
                from_email=(
                    f"{empresa.nome_exibicao} <{settings.DEFAULT_FROM_EMAIL}>"
                    if "<" not in settings.DEFAULT_FROM_EMAIL
                    else settings.DEFAULT_FROM_EMAIL
                ),
                to=[pessoa.email],
            )
            mensagem.attach_alternative(html, "text/html")
            mensagem.send(fail_silently=False)
            enviados += 1
        except Exception:
            falhas += 1
            logger.exception(
                "Falha ao parabenizar o colaborador %s", pessoa.pk
            )

    if enviados or falhas:
        logger.info(
            "Parabéns do dia: %s enviado(s), %s falha(s), %s sem e-mail.",
            enviados, falhas, sem_email,
        )
    return {"enviados": enviados, "falhas": falhas, "sem_email": sem_email}
