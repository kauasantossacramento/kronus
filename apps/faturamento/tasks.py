"""
Kronus — lembretes de vencimento.

Dois avisos, com tons deliberadamente diferentes.

**Tres dias antes**, um lembrete. Quem paga em dia nao precisa de
cobranca: precisa de aviso. Tratar o cliente adimplente como
inadimplente em potencial e o jeito mais rapido de azedar uma relacao
que estava boa.

**Depois do vencimento**, um pedido de atencao. Tambem sem aspereza: a
esmagadora maioria dos atrasos e esquecimento, e o texto que serve para
quem esqueceu ofende quem esqueceu — e nao convence quem decidiu nao
pagar.

Os dois apontam para a fatura no dominio do Kronus. Um e-mail de
cobranca que manda o cliente para outro dominio e indistinguivel de
golpe para quem foi treinado a desconfiar disso.
"""
import logging

from celery import shared_task

logger = logging.getLogger("kronus.faturamento")

#: Quantos dias antes do vencimento o lembrete sai.
#:
#: Tres da tempo de o financeiro incluir no lote da semana sem virar
#: aviso antecipado demais, que a pessoa le e esquece.
DIAS_DE_ANTECEDENCIA = 3

#: De quanto em quanto tempo o aviso de atraso se repete.
#:
#: Diario vira assedio; uma vez so se perde. Tres dias mantem presente
#: sem cansar — e cobre quem so olha e-mail as segundas.
INTERVALO_DO_ATRASO = 3

#: Depois disto, o sistema para de avisar por conta propria.
#:
#: Passado um mes, o silencio nao e mais o problema: o caso virou
#: conversa comercial, e insistir por robo atrapalha quem for negociar.
LIMITE_DE_AVISOS = 30


def _destinatarios(cliente):
    """
    Quem recebe: os usuarios que administram a conta.

    Nao o RH, e nao os colaboradores. Fatura e assunto de quem assina o
    contrato, e mandar valor de mensalidade para a operacao inteira e
    vazar informacao comercial dentro do proprio cliente.
    """
    from apps.accounts.models import CustomUser as Usuario

    return list(
        Usuario.objects.filter(cliente=cliente, tipo="cliente", is_active=True)
    )


def _url_da_fatura(cobranca) -> str:
    from django.conf import settings
    from django.urls import reverse

    caminho = reverse("faturamento:fatura", args=[cobranca.uuid])
    base = (getattr(settings, "KRONUS", {}) or {}).get("APP_URL", "")
    return f"{base.rstrip('/')}{caminho}" if base else caminho


def _ja_avisado(cobranca, chave: str, dentro_de_dias: int = None) -> bool:
    """
    Este aviso ja saiu?

    Guardado nos metadados da notificacao, e nao num campo novo: o que
    se quer saber e "ja mandei este e-mail", e a notificacao **e** o
    registro de ter mandado.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.notificacoes.models import Notificacao

    qs = Notificacao.objects.filter(
        evento=Notificacao.Evento.SISTEMA,
        metadados__cobranca=str(cobranca.uuid),
        metadados__aviso=chave,
    )
    if dentro_de_dias is not None:
        qs = qs.filter(
            created_at__gte=timezone.now() - timedelta(days=dentro_de_dias)
        )
    return qs.exists()


@shared_task(name="apps.faturamento.tasks.lembrar_vencimentos")
def lembrar_vencimentos() -> dict:
    """
    Avisa quem vence em breve e quem ja venceu.

    Roda uma vez por dia. Nao cobra, nao ameaca e nao suspende nada —
    suspensao tem regra propria e caminho proprio.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.faturamento.models import Cobranca
    from apps.notificacoes.models import Notificacao
    from apps.notificacoes.services import criar

    hoje = timezone.localdate()
    alvo = hoje + timedelta(days=DIAS_DE_ANTECEDENCIA)
    lembrados = atrasados = 0

    em_aberto = Cobranca.objects.filter(
        status__in=[Cobranca.Status.PENDENTE, Cobranca.Status.VENCIDA]
    ).select_related("assinatura", "assinatura__cliente", "assinatura__plano")

    # -- vence em tres dias -----------------------------------
    for cobranca in em_aberto.filter(vencimento=alvo):
        if _ja_avisado(cobranca, "antecedencia"):
            continue
        cliente = cobranca.assinatura.cliente
        url = _url_da_fatura(cobranca)
        for usuario in _destinatarios(cliente):
            criar(
                destinatario=usuario,
                evento=Notificacao.Evento.SISTEMA,
                nivel=Notificacao.Nivel.INFO,
                titulo=f"Sua fatura vence em {DIAS_DE_ANTECEDENCIA} dias",
                mensagem=(
                    f"A fatura de R$ {cobranca.valor:.2f} vence em "
                    f"{cobranca.vencimento.strftime('%d/%m/%Y')}. "
                    "O Pix e o boleto estão na sua área de assinatura."
                ),
                canal=Notificacao.Canal.AMBOS,
                url_acao=url,
                metadados={
                    "cobranca": str(cobranca.uuid),
                    "aviso": "antecedencia",
                },
                template_email="faturamento/email/lembrete.html",
                contexto_email={
                    "cobranca": cobranca,
                    "cliente": cliente,
                    "url_fatura": url,
                    "atrasada": False,
                },
            )
            lembrados += 1

    # -- ja venceu --------------------------------------------
    for cobranca in em_aberto.filter(vencimento__lt=hoje):
        atraso = (hoje - cobranca.vencimento).days
        if atraso > LIMITE_DE_AVISOS:
            continue
        if _ja_avisado(cobranca, "atraso", dentro_de_dias=INTERVALO_DO_ATRASO):
            continue
        cliente = cobranca.assinatura.cliente
        url = _url_da_fatura(cobranca)
        for usuario in _destinatarios(cliente):
            criar(
                destinatario=usuario,
                evento=Notificacao.Evento.SISTEMA,
                nivel=Notificacao.Nivel.ALERTA,
                titulo="Fatura em aberto",
                mensagem=(
                    f"A fatura de R$ {cobranca.valor:.2f} venceu em "
                    f"{cobranca.vencimento.strftime('%d/%m/%Y')}. "
                    "Se já pagou, a confirmação pode levar até um dia útil."
                ),
                canal=Notificacao.Canal.AMBOS,
                url_acao=url,
                metadados={
                    "cobranca": str(cobranca.uuid),
                    "aviso": "atraso",
                    "dias": atraso,
                },
                template_email="faturamento/email/lembrete.html",
                contexto_email={
                    "cobranca": cobranca,
                    "cliente": cliente,
                    "url_fatura": url,
                    "atrasada": True,
                    "dias_de_atraso": atraso,
                },
            )
            atrasados += 1

    if lembrados or atrasados:
        logger.info(
            "Lembretes de vencimento: %s antecipado(s), %s de atraso.",
            lembrados, atrasados,
        )
    return {"lembrados": lembrados, "atrasados": atrasados}
