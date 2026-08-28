"""
Kronus — extensões do drf-spectacular.

Sem isto o schema é gerado, mas **sem esquema de segurança**: o Swagger
UI aparece sem o botão "Authorize", e quem abre `/api/v1/docs/` não
consegue experimentar um único endpoint — vê a lista de recursos e
recebe 401 em todos. Documentação de API que não deixa testar não
economiza suporte, gera suporte.

Cada extensão declara ao OpenAPI *onde* a credencial viaja e *como* se
chama, para que a UI monte o campo certo.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class APIKeySchema(OpenApiAuthenticationExtension):
    """`X-API-Key: kr_…` — integrações de sistema."""

    target_class = "apps.api.authentication.APIKeyAuthentication"
    name = "ChaveDeAPI"
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "Chave de integração. Aceita a chave de conta do Cliente "
                "(alcança todas as empresas) ou a chave de escopo de Empresa "
                "(uma só). Emitida em Configurações › Integrações; o texto "
                "pleno é exibido uma única vez."
            ),
        }


class TotemSchema(OpenApiAuthenticationExtension):
    """`Authorization: Token …` — equipamento de quiosque."""

    target_class = "apps.api.authentication.TotemAuthentication"
    name = "TokenDoTotem"
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "Token",
            "description": (
                "Token opaco do equipamento, no formato "
                "`Authorization: Token <token>`. Não representa um usuário: "
                "o colaborador se identifica depois, pelo rosto ou pelo CPF."
            ),
        }
