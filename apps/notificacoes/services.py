"""
Kronus — emissão de notificações (Seção 8.7 do plano).

Uma notificação sempre nasce in-app; o e-mail é enviado quando o evento
e a configuração da empresa pedem. O envio nunca derruba a operação que
o originou — um SMTP fora do ar não pode impedir uma batida de ponto.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.constants import TipoUsuario
from apps.notificacoes.models import Notificacao

logger = logging.getLogger("kronus.notificacoes")


def criar(
    *,
    destinatario,
    evento,
    titulo: str,
    mensagem: str,
    nivel=Notificacao.Nivel.INFO,
    empresa=None,
    url_acao: str = "",
    canal=Notificacao.Canal.IN_APP,
    metadados: dict = None,
    template_email: str = None,
    contexto_email: dict = None,
) -> Notificacao | None:
    """Cria a notificação e, se o canal pedir, dispara o e-mail."""
    try:
        notificacao = Notificacao.objects.create(
            destinatario=destinatario,
            empresa=empresa,
            evento=evento,
            nivel=nivel,
            canal=canal,
            titulo=titulo[:150],
            mensagem=mensagem,
            url_acao=url_acao[:255],
            metadados=metadados or {},
        )
    except Exception:
        logger.exception("Falha ao criar notificação (%s)", evento)
        return None

    if canal in (Notificacao.Canal.EMAIL, Notificacao.Canal.AMBOS):
        enviar_email(notificacao, template_email, contexto_email)
    return notificacao


def enviar_email(notificacao, template: str = None, contexto: dict = None):
    """Envia o e-mail da notificação. Falha aqui é logada, não propagada."""
    endereco = notificacao.destinatario.email
    if not endereco:
        return False

    contexto = {
        "notificacao": notificacao,
        "destinatario": notificacao.destinatario,
        "empresa": notificacao.empresa,
        "KRONUS": settings.KRONUS,
        **(contexto or {}),
    }

    try:
        corpo_html = render_to_string(
            template or "notificacoes/email/generico.html", contexto
        )
        send_mail(
            subject=f"[Kronus] {notificacao.titulo}",
            message=notificacao.mensagem,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[endereco],
            html_message=corpo_html,
            fail_silently=False,
        )
    except Exception:
        logger.exception("Falha ao enviar e-mail da notificação %s", notificacao.pk)
        return False

    notificacao.enviada_email = True
    notificacao.enviada_email_em = timezone.now()
    notificacao.save(update_fields=["enviada_email", "enviada_email_em", "updated_at"])
    return True


# ══════════════════════════════════════════════════════════════
# Destinatários
# ══════════════════════════════════════════════════════════════
def gestores_da_empresa(empresa):
    """Admins RH vinculados à empresa, mais o admin do cliente."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    User = get_user_model()
    return User.objects.filter(
        Q(tipo=TipoUsuario.RH, empresas=empresa)
        | Q(tipo=TipoUsuario.CLIENTE, cliente_id=empresa.cliente_id),
        is_active=True,
    ).distinct()


def usuarios_master():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(tipo=TipoUsuario.MASTER, is_active=True)


# ══════════════════════════════════════════════════════════════
# Eventos
# ══════════════════════════════════════════════════════════════
def notificar_totem_offline(totem):
    """Totem sem heartbeat há mais de 10 minutos (Seção 8.7)."""
    empresa = totem.empresa
    config = getattr(empresa, "config", None)
    if config is not None and not config.notif_totem_offline:
        return 0

    minutos = totem.minutos_desde_heartbeat
    mensagem = (
        f"O totem {totem.identificador} da empresa {empresa.nome_exibicao} está "
        + (f"sem comunicação há {minutos} minutos." if minutos else "sem comunicação.")
    )

    enviadas = 0
    canal = (
        Notificacao.Canal.AMBOS
        if config is None or config.notif_totem_offline
        else Notificacao.Canal.IN_APP
    )
    for destinatario in list(gestores_da_empresa(empresa)) + list(usuarios_master()):
        if criar(
            destinatario=destinatario,
            evento=Notificacao.Evento.TOTEM_OFFLINE,
            nivel=Notificacao.Nivel.ALERTA,
            titulo=f"Totem offline: {totem.identificador}",
            mensagem=mensagem,
            empresa=empresa,
            canal=canal,
            url_acao="/rh/",
            metadados={"totem_id": totem.pk, "minutos": minutos},
        ):
            enviadas += 1
    return enviadas


def notificar_ponto_registrado(registro):
    """
    Confirmação da batida ao colaborador.

    Só existe se ele tiver credenciais de acesso — quem bate apenas no
    totem recebe o comprovante impresso/na tela, não uma notificação.
    """
    colaborador = registro.colaborador
    usuario = colaborador.user
    if usuario is None:
        return None

    config = getattr(registro.empresa, "config", None)
    canal = (
        Notificacao.Canal.AMBOS
        if config is not None and config.notif_comprovante_email
        else Notificacao.Canal.IN_APP
    )

    momento = timezone.localtime(registro.data_hora)
    return criar(
        destinatario=usuario,
        evento=Notificacao.Evento.PONTO_REGISTRADO,
        nivel=Notificacao.Nivel.SUCESSO,
        titulo=f"{registro.get_tipo_display()} registrada às {momento:%H:%M}",
        mensagem=(
            f"Ponto registrado em {momento:%d/%m/%Y às %H:%M:%S}. "
            f"NSR {registro.nsr} · código {registro.codigo_verificacao}."
        ),
        empresa=registro.empresa,
        canal=canal,
        url_acao=f"/ponto/comprovante/{registro.uuid}/",
        metadados={"nsr": registro.nsr},
    )


def notificar_fraude_gps(registro):
    """Suspeita de GPS fictício (Seção 8.7)."""
    empresa = registro.empresa
    momento = timezone.localtime(registro.data_hora)
    enviadas = 0
    for gestor in gestores_da_empresa(empresa):
        if criar(
            destinatario=gestor,
            evento=Notificacao.Evento.FRAUDE_GPS,
            nivel=Notificacao.Nivel.ALERTA,
            titulo="Possível GPS fictício",
            mensagem=(
                f"O registro de {registro.colaborador.nome_exibicao} em "
                f"{momento:%d/%m/%Y %H:%M} apresentou indício de localização "
                "falsificada. Verifique o NSR "
                f"{registro.nsr}."
            ),
            empresa=empresa,
            canal=Notificacao.Canal.AMBOS,
            url_acao="/rh/registros/?apenas_alertas=1",
            metadados={"nsr": registro.nsr},
        ):
            enviadas += 1
    return enviadas
