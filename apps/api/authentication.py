"""
Kronus — autenticação da API REST (Seção 7.4 do plano).

Três credenciais coexistem:

    Authorization: Token <token_totem>   equipamento de quiosque
    X-API-Key: <chave>                   integração de sistema externo
    Authorization: Bearer <jwt>          colaborador autenticado

O totem e a API Key **não** representam um usuário do Django: são
credenciais de máquina. Elas autenticam a requisição e anexam o escopo
(`request.totem` ou `request.api_empresa`), sem sessão e sem senha.
"""
import logging

from rest_framework import authentication, exceptions

from apps.core.utils import hash_api_key

logger = logging.getLogger("kronus.api")


class TotemAuthentication(authentication.BaseAuthentication):
    """
    Autentica pelo token opaco do equipamento.

    Um totem não tem usuário: quem se identifica depois é o colaborador,
    pelo rosto ou pelo CPF. Por isso devolvemos `(None, totem)` — a view
    lê `request.auth` (ou `request.totem`) para saber de qual equipamento
    veio a chamada.
    """

    palavra_chave = "Token"

    def authenticate(self, request):
        cabecalho = authentication.get_authorization_header(request).split()
        if not cabecalho or cabecalho[0].lower() != self.palavra_chave.lower().encode():
            return None
        if len(cabecalho) == 1:
            raise exceptions.AuthenticationFailed("Token do totem ausente.")
        if len(cabecalho) > 2:
            raise exceptions.AuthenticationFailed("Token do totem malformado.")

        try:
            token = cabecalho[1].decode()
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Token do totem inválido.")

        from apps.totem.models import Totem

        totem = (
            Totem.objects.select_related("empresa", "empresa__cliente", "grupo")
            .filter(token_acesso=token, ativo=True, deleted_at__isnull=True)
            .first()
        )
        if totem is None:
            raise exceptions.AuthenticationFailed("Totem não reconhecido ou inativo.")

        if totem.empresa.cliente.suspenso:
            raise exceptions.AuthenticationFailed(
                "A assinatura desta empresa está suspensa."
            )

        request.totem = totem
        return (None, totem)

    def authenticate_header(self, request):
        return self.palavra_chave


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Autentica integrações pelo header `X-API-Key`.

    Aceita a chave de conta do Cliente (emitida pelo Master, alcança
    todas as empresas dele) e a chave de escopo de Empresa (emitida pelo
    RH). Só o hash SHA-256 é comparado — a chave em texto plano nunca
    existiu no banco.
    """

    cabecalho = "HTTP_X_API_KEY"

    def authenticate(self, request):
        chave = request.META.get(self.cabecalho)
        if not chave:
            return None

        hash_recebido = hash_api_key(chave)

        # 1. chave com escopo de empresa
        from apps.api.models import APIKey

        api_key = (
            APIKey.objects.select_related("empresa", "empresa__cliente")
            .filter(chave_hash=hash_recebido)
            .first()
        )
        if api_key is not None:
            if not api_key.valida:
                raise exceptions.AuthenticationFailed("Chave de API revogada ou expirada.")
            if api_key.empresa.cliente.suspenso:
                raise exceptions.AuthenticationFailed("Assinatura suspensa.")
            self._verificar_ip(api_key, request)

            api_key.registrar_uso()
            request.api_key = api_key
            request.api_empresas = api_key.empresa.__class__.objects.filter(
                pk=api_key.empresa_id
            )
            return (None, api_key)

        # 2. chave de conta do cliente
        from apps.clientes.models import Cliente, Empresa

        cliente = Cliente.objects.filter(
            api_key_hash=hash_recebido, api_key_ativa=True
        ).first()
        if cliente is not None:
            if cliente.suspenso:
                raise exceptions.AuthenticationFailed("Assinatura suspensa.")
            request.api_key = None
            request.api_cliente = cliente
            request.api_empresas = Empresa.objects.filter(cliente=cliente, ativo=True)
            return (None, cliente)

        raise exceptions.AuthenticationFailed("Chave de API inválida.")

    @staticmethod
    def _verificar_ip(api_key, request):
        """Restrição de origem, quando a chave declara IPs permitidos."""
        permitidos = api_key.ips_permitidos or []
        if not permitidos:
            return

        import ipaddress

        from apps.core.utils import obter_ip

        origem = obter_ip(request)
        if not origem:
            raise exceptions.AuthenticationFailed("Origem da requisição não identificada.")

        try:
            endereco = ipaddress.ip_address(origem)
        except ValueError:
            raise exceptions.AuthenticationFailed("Origem inválida.")

        for entrada in permitidos:
            try:
                if endereco in ipaddress.ip_network(entrada, strict=False):
                    return
            except ValueError:
                logger.warning("IP permitido inválido na chave %s: %s", api_key.pk, entrada)

        raise exceptions.AuthenticationFailed(
            f"Origem {origem} não autorizada para esta chave."
        )

    def authenticate_header(self, request):
        return "X-API-Key"
