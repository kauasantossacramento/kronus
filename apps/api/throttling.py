"""
Kronus — rate limiting da API pública (Seção 7.4 do plano).

O limite **não é global**: cada plano comercial vende uma cota
(`Plano.rate_limit_api_hora`), e cada chave pode restringir ainda mais
(`APIKey.rate_limit_hora`). O menor dos dois vence — uma chave não pode
comprar mais cota do que o plano do cliente contratou.

    plano Starter      1.000/h
    chave "ERP folha"    200/h   →  vale 200/h
    chave "BI"         5.000/h   →  vale 1.000/h  (teto do plano)

**Por que não o `ScopedRateThrottle` puro.** Ele lê a taxa de
`DEFAULT_THROTTLE_RATES`, que é estático no settings. Aqui a taxa é um
dado de negócio, muda quando o cliente troca de plano, e precisa valer
imediatamente. Então herdamos de `SimpleRateThrottle` e resolvemos a
taxa por requisição, a partir da credencial já autenticada.
"""
import logging

from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger("kronus.api")

#: Cota de quem chega sem chave reconhecida. Baixa de propósito: são
#: requisições que ainda vão ser recusadas pela autenticação, e o
#: throttle serve só para conter varredura de chaves.
TAXA_ANONIMA = 60


class PlanoRateThrottle(SimpleRateThrottle):
    """
    Limite horário derivado do plano contratado e da chave usada.

    A janela é a padrão do `SimpleRateThrottle`: histórico deslizante de
    uma hora no cache, por credencial. Chave revogada não chega aqui —
    a autenticação já barrou.
    """

    scope = "api_plano"

    def __init__(self):
        # A taxa é resolvida por requisição em `allow_request`; o
        # construtor da classe-mãe exigiria uma taxa estática.
        self.rate = None
        self.num_requests = None
        self.duration = None
        self.history = []
        self.now = None
        self.key = None

    # -- identificação da cota ---------------------------------
    def get_cache_key(self, request, view):
        api_key = getattr(request, "api_key", None)
        if api_key is not None:
            return f"throttle:apikey:{api_key.pk}"

        cliente = getattr(request, "api_cliente", None)
        if cliente is not None:
            return f"throttle:cliente:{cliente.pk}"

        # Sem credencial reconhecida: agrupa por origem.
        return f"throttle:anon:{self.get_ident(request)}"

    @staticmethod
    def limite_por_hora(request) -> int:
        """
        Resolve a cota efetiva desta requisição.

        Regra: o menor entre o teto do plano e o teto da chave. Uma
        chave com limite maior que o plano não amplia a cota — o plano
        é o contrato.
        """
        api_key = getattr(request, "api_key", None)
        cliente = getattr(request, "api_cliente", None)

        if api_key is not None:
            cliente = getattr(api_key.empresa, "cliente", None)

        teto_plano = None
        plano = getattr(cliente, "plano", None) if cliente is not None else None
        if plano is not None:
            teto_plano = plano.rate_limit_api_hora or None

        teto_chave = api_key.rate_limit_hora if api_key is not None else None

        candidatos = [valor for valor in (teto_plano, teto_chave) if valor]
        if not candidatos:
            return TAXA_ANONIMA if cliente is None else 1000
        return min(candidatos)

    # -- ciclo do throttle -------------------------------------
    def allow_request(self, request, view):
        self.num_requests = self.limite_por_hora(request)
        self.duration = 3600
        self.rate = f"{self.num_requests}/hour"
        return super().allow_request(request, view)

    def throttle_failure(self):
        """Registra o estouro — cota estourada é sinal comercial, não só técnico."""
        logger.warning(
            "Rate limit excedido: chave=%s cota=%s/h",
            self.key,
            self.num_requests,
        )
        return super().throttle_failure()


class ColaboradorRateThrottle(SimpleRateThrottle):
    """
    Limite do app do colaborador (JWT), por usuário.

    Bem menor que o da integração: um humano batendo ponto pelo celular
    não faz centenas de chamadas por hora, e um pico aqui é bug de
    cliente ou tentativa de abuso.
    """

    scope = "colaborador"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"throttle:colab:{request.user.pk}"
        return f"throttle:anon:{self.get_ident(request)}"
