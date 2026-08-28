"""
Kronus — consumers WebSocket (Django Channels).

Dois canais:

    /ws/totem/<token>/         equipamento ↔ servidor
    /ws/painel/<empresa_uuid>/ dashboard do RH em tempo real

**Por que WebSocket se o heartbeat já é HTTP?** O heartbeat resolve o
sentido totem→servidor. O caminho inverso — servidor→totem — não tem
como ser feito por polling sem desperdiçar bateria: recarregar a
configuração após o RH trocar a logo, ou forçar um reload remoto no
suporte, exige que o servidor fale primeiro.

O HTTP continua sendo o caminho do registro de ponto. Uma batida nunca
depende de WebSocket: se o canal cair, o totem segue funcionando.
"""
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

logger = logging.getLogger("kronus.totem")

GRUPO_TOTEM = "totem_{token}"
GRUPO_PAINEL = "painel_{empresa}"


class TotemConsumer(AsyncJsonWebsocketConsumer):
    """Canal do equipamento. Autentica pelo token na URL."""

    async def connect(self):
        self.token = self.scope["url_route"]["kwargs"]["token"]
        self.totem = await self._buscar_totem(self.token)

        if self.totem is None:
            # 4001: token inválido. O totem não deve tentar reconectar.
            await self.close(code=4001)
            return

        self.grupo = GRUPO_TOTEM.format(token=self.token)
        await self.channel_layer.group_add(self.grupo, self.channel_name)
        await self.accept()

        await self.send_json(
            {
                "tipo": "conectado",
                "identificador": self.totem.identificador,
                "servidor": timezone.localtime().isoformat(),
            }
        )
        logger.info("Totem conectado ao WebSocket: %s", self.totem.identificador)

    async def disconnect(self, code):
        if getattr(self, "grupo", None):
            await self.channel_layer.group_discard(self.grupo, self.channel_name)

    async def receive_json(self, conteudo, **kwargs):
        tipo = conteudo.get("tipo")

        if tipo == "heartbeat":
            await self._registrar_heartbeat(conteudo)
            await self.send_json(
                {"tipo": "heartbeat_ok", "servidor": timezone.localtime().isoformat()}
            )
        elif tipo == "ping":
            await self.send_json({"tipo": "pong"})
        else:
            await self.send_json({"tipo": "erro", "mensagem": "Comando desconhecido."})

    # -- mensagens enviadas pelo servidor ----------------------
    async def totem_recarregar(self, evento):
        """Força o totem a recarregar a página (usado pelo suporte)."""
        await self.send_json({"tipo": "recarregar", "motivo": evento.get("motivo", "")})

    async def totem_config_alterada(self, evento):
        """Avisa que a identidade visual ou os parâmetros mudaram."""
        await self.send_json({"tipo": "config_alterada"})

    async def totem_mensagem(self, evento):
        """Mensagem exibida na tela do equipamento."""
        await self.send_json(
            {"tipo": "mensagem", "texto": evento.get("texto", ""),
             "segundos": evento.get("segundos", 10)}
        )

    # -- acesso ao banco ---------------------------------------
    @database_sync_to_async
    def _buscar_totem(self, token):
        from apps.totem.models import Totem

        return (
            Totem.objects.select_related("empresa", "empresa__cliente")
            .filter(token_acesso=token, ativo=True, deleted_at__isnull=True)
            .exclude(empresa__cliente__suspenso=True)
            .first()
        )

    @database_sync_to_async
    def _registrar_heartbeat(self, conteudo):
        self.totem.registrar_heartbeat(
            versao=conteudo.get("versao"), bateria=conteudo.get("bateria")
        )


class PainelConsumer(AsyncJsonWebsocketConsumer):
    """
    Canal do dashboard do RH: registros de ponto chegando ao vivo
    (Seção 6.6 — "Últimos registros — tempo real").

    Autentica pela sessão: o usuário precisa estar logado e ter a
    empresa no escopo.
    """

    async def connect(self):
        self.empresa_uuid = self.scope["url_route"]["kwargs"]["empresa"]
        usuario = self.scope.get("user")

        if usuario is None or not usuario.is_authenticated:
            await self.close(code=4003)
            return

        self.empresa = await self._empresa_no_escopo(usuario, self.empresa_uuid)
        if self.empresa is None:
            await self.close(code=4003)
            return

        self.grupo = GRUPO_PAINEL.format(empresa=self.empresa_uuid)
        await self.channel_layer.group_add(self.grupo, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if getattr(self, "grupo", None):
            await self.channel_layer.group_discard(self.grupo, self.channel_name)

    async def ponto_registrado(self, evento):
        await self.send_json({"tipo": "ponto", **evento.get("dados", {})})

    async def totem_status(self, evento):
        await self.send_json({"tipo": "totem_status", **evento.get("dados", {})})

    @database_sync_to_async
    def _empresa_no_escopo(self, usuario, empresa_uuid):
        from apps.core.mixins import escopo_empresas

        return escopo_empresas(usuario).filter(uuid=empresa_uuid).first()


# ══════════════════════════════════════════════════════════════
# Emissão a partir de código síncrono
# ══════════════════════════════════════════════════════════════
def notificar_painel(empresa, dados: dict):
    """
    Publica um evento no dashboard da empresa.

    Falha aqui é silenciosa por decisão: se o Redis estiver fora, o
    registro de ponto não pode ser afetado — o painel simplesmente não
    atualiza sozinho.
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    try:
        camada = get_channel_layer()
        if camada is None:
            return
        async_to_sync(camada.group_send)(
            GRUPO_PAINEL.format(empresa=empresa.uuid),
            {"type": "ponto.registrado", "dados": dados},
        )
    except Exception:
        logger.debug("Não foi possível publicar no painel", exc_info=True)


def comandar_totem(totem, comando: str, **extra):
    """Envia um comando ao equipamento (recarregar, mensagem, config)."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    try:
        camada = get_channel_layer()
        if camada is None:
            return False
        async_to_sync(camada.group_send)(
            GRUPO_TOTEM.format(token=totem.token_acesso),
            {"type": comando, **extra},
        )
        return True
    except Exception:
        logger.debug("Não foi possível comandar o totem %s", totem.pk, exc_info=True)
        return False
