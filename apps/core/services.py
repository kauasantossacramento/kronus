"""Kronus — servicos transversais (auditoria)."""
import logging

from apps.core.middleware import contexto_atual

logger = logging.getLogger("kronus.auditoria")


def registrar_log(
    *,
    acao,
    descricao: str = "",
    request=None,
    usuario=None,
    cliente=None,
    empresa=None,
    objeto=None,
    metadados: dict | None = None,
):
    """
    Grava um `core.LogAcesso`.

    Pode ser chamado a partir de views (passando `request`) ou de signals
    (usando o contexto de thread preenchido pelos middlewares).
    """
    from apps.core.models import LogAcesso

    contexto = contexto_atual()

    if request is not None:
        usuario = usuario or getattr(request, "user", None)
        cliente = cliente or getattr(request, "cliente", None)
        empresa = empresa or getattr(request, "empresa_ativa", None)
        ip = contexto.get("ip")
        user_agent = contexto.get("user_agent", "")
    else:
        usuario = usuario or contexto.get("usuario")
        cliente = cliente or contexto.get("cliente")
        empresa = empresa or contexto.get("empresa")
        ip = contexto.get("ip")
        user_agent = contexto.get("user_agent", "")

    if usuario is not None and not getattr(usuario, "is_authenticated", False):
        usuario = None

    if empresa is not None and cliente is None:
        cliente = getattr(empresa, "cliente", None)

    try:
        return LogAcesso.objects.create(
            usuario=usuario,
            cliente=cliente,
            empresa=empresa,
            acao=acao,
            descricao=descricao[:255],
            objeto_tipo=objeto._meta.label if objeto is not None else "",
            objeto_id=str(getattr(objeto, "pk", "") or ""),
            ip=ip,
            user_agent=user_agent,
            metadados=metadados or {},
        )
    except Exception:  # auditoria nunca pode derrubar a operacao principal
        logger.exception("Falha ao gravar log de auditoria (ação=%s)", acao)
        return None
