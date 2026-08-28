"""
Kronus — cliente da API do ASAAS.

Camada fina sobre `requests`, deliberadamente burra: monta a chamada,
trata o erro e devolve o JSON. Nenhuma regra de negócio mora aqui — ela
fica em `services.py`, que é testável sem rede.

    https://api.asaas.com/v3           produção
    https://api-sandbox.asaas.com/v3   sandbox
    header: access_token: <chave>

**Erro de gateway não é exceção genérica.** `ErroGateway` carrega o
status HTTP e as mensagens que o ASAAS devolveu, porque elas são o que
o operador precisa ler para corrigir — "CPF inválido" e "saldo
insuficiente" pedem ações diferentes, e um `Exception` genérico
esconderia as duas.
"""
import logging

logger = logging.getLogger("kronus.faturamento")

TIMEOUT = 20


class ErroGateway(Exception):
    """Falha numa chamada ao ASAAS, com o que ele respondeu."""

    def __init__(self, mensagem, status=None, erros=None):
        super().__init__(mensagem)
        self.status = status
        self.erros = erros or []

    @property
    def descricao(self) -> str:
        if self.erros:
            return "; ".join(
                e.get("description", str(e)) if isinstance(e, dict) else str(e)
                for e in self.erros
            )
        return str(self)


class ClienteAsaas:
    """
    Chamadas à API do ASAAS.

        gateway = ClienteAsaas.a_partir_da_configuracao()
        cliente = gateway.criar_cliente(nome=..., cpf_cnpj=...)
    """

    def __init__(self, api_key: str, url_base: str):
        if not api_key:
            raise ErroGateway("Chave de API do ASAAS não configurada.")
        self.api_key = api_key
        self.url_base = url_base.rstrip("/")

    @classmethod
    def a_partir_da_configuracao(cls) -> "ClienteAsaas":
        from apps.faturamento.models import ConfiguracaoGateway

        config = ConfiguracaoGateway.carregar()
        if not config.ativo:
            raise ErroGateway(
                "A cobrança automática está desligada em Configurações do gateway."
            )
        return cls(config.api_key, config.url_base)

    # -- transporte --------------------------------------------
    def _chamar(self, metodo: str, caminho: str, dados=None, params=None):
        import requests

        url = f"{self.url_base}/{caminho.lstrip('/')}"
        cabecalhos = {
            "access_token": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "Kronus/1.0",
        }

        try:
            resposta = requests.request(
                metodo, url, json=dados, params=params,
                headers=cabecalhos, timeout=TIMEOUT,
            )
        except Exception as erro:
            # Rede fora do ar não é "cobrança recusada": distinguir os
            # dois evita marcar como inadimplente quem só ficou sem
            # resposta do gateway.
            logger.exception("Falha de rede ao chamar o ASAAS: %s %s", metodo, url)
            raise ErroGateway(f"Gateway inacessível: {erro}") from erro

        if resposta.status_code >= 400:
            corpo = {}
            try:
                corpo = resposta.json()
            except Exception:
                pass
            erros = corpo.get("errors") or []
            logger.warning(
                "ASAAS recusou %s %s (HTTP %s): %s",
                metodo, caminho, resposta.status_code, erros or resposta.text[:300],
            )
            raise ErroGateway(
                f"O gateway recusou a operação (HTTP {resposta.status_code}).",
                status=resposta.status_code,
                erros=erros,
            )

        if not resposta.content:
            return {}
        return resposta.json()

    # -- clientes ----------------------------------------------
    def criar_cliente(self, *, nome, cpf_cnpj, email="", telefone="",
                      referencia_externa="") -> dict:
        return self._chamar("POST", "/customers", {
            "name": nome,
            "cpfCnpj": cpf_cnpj,
            "email": email,
            "mobilePhone": telefone,
            # Amarra o registro do ASAAS ao nosso Cliente. Sem isso, uma
            # reconciliação manual depois vira busca por nome.
            "externalReference": referencia_externa,
            "notificationDisabled": False,
        })

    def buscar_cliente_por_cpf_cnpj(self, cpf_cnpj: str) -> dict | None:
        resultado = self._chamar("GET", "/customers", params={"cpfCnpj": cpf_cnpj})
        dados = resultado.get("data") or []
        return dados[0] if dados else None

    def atualizar_cliente(self, customer_id: str, **campos) -> dict:
        return self._chamar("POST", f"/customers/{customer_id}", campos)

    # -- assinaturas -------------------------------------------
    def criar_assinatura(self, *, customer_id, valor, ciclo, vencimento,
                         descricao="", forma_pagamento="UNDEFINED",
                         referencia_externa="") -> dict:
        return self._chamar("POST", "/subscriptions", {
            "customer": customer_id,
            "billingType": forma_pagamento,
            "value": float(valor),
            "nextDueDate": vencimento.isoformat(),
            "cycle": ciclo,
            "description": descricao,
            "externalReference": referencia_externa,
        })

    def atualizar_assinatura(self, subscription_id: str, **campos) -> dict:
        if "value" in campos:
            campos["value"] = float(campos["value"])
        return self._chamar("POST", f"/subscriptions/{subscription_id}", campos)

    def cancelar_assinatura(self, subscription_id: str) -> dict:
        return self._chamar("DELETE", f"/subscriptions/{subscription_id}")

    def cobrancas_da_assinatura(self, subscription_id: str) -> list[dict]:
        resultado = self._chamar("GET", f"/subscriptions/{subscription_id}/payments")
        return resultado.get("data") or []

    # -- cobranças ---------------------------------------------
    def buscar_cobranca(self, payment_id: str) -> dict:
        return self._chamar("GET", f"/payments/{payment_id}")

    def linha_digitavel(self, payment_id: str) -> dict:
        return self._chamar("GET", f"/payments/{payment_id}/identificationField")

    def qrcode_pix(self, payment_id: str) -> dict:
        return self._chamar("GET", f"/payments/{payment_id}/pixQrCode")

    # -- diagnóstico -------------------------------------------
    def testar(self) -> dict:
        """
        Chamada barata para validar a credencial na tela de configuração.

        Lista um cliente só: confirma que a chave é aceita e que o
        ambiente responde, sem criar nada.
        """
        resultado = self._chamar("GET", "/customers", params={"limit": 1})
        return {
            "ok": True,
            "total_clientes": resultado.get("totalCount", 0),
        }
