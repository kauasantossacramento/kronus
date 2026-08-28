"""
Kronus — endpoints do totem (Seção 7.3 do plano).

    POST /api/v1/totem/recognize/    frame facial → identifica e registra
    POST /api/v1/totem/punch-cpf/    fallback por CPF + data de nascimento
    POST /api/v1/totem/heartbeat/    sinal de vida (a cada 30 s)
    GET  /api/v1/totem/config/       identidade visual e parâmetros

Todos autenticam por `Authorization: Token <token_totem>`.

**Contrato de erro:** o totem é um quiosque sem operador. Uma resposta
de erro precisa dizer ao equipamento o que mostrar na tela, não apenas
que algo falhou. Por isso todas as respostas — inclusive as negativas —
carregam `codigo` (para a máquina de estados) e `mensagem` (para o
colaborador ler).
"""
import logging
import random

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.api.authentication import TotemAuthentication
from apps.api.permissions import TotemAutenticado
from apps.api.serializers import (
    ColaboradorTotemSerializer,
    ConfigTotemSerializer,
    HeartbeatSerializer,
    PunchCPFSerializer,
    ReconhecimentoSerializer,
    RegistroTotemSerializer,
)
from apps.core.constants import MENSAGENS_TOTEM, MetodoRegistro
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.core.utils import obter_ip
from apps.facial.services import FaceRecognitionService, identificar_por_cpf
from apps.ponto import validators
from apps.ponto.services import RegistroPontoService
from apps.totem.models import EventoTotem

logger = logging.getLogger("kronus.totem")


class RecognizeThrottle(ScopedRateThrottle):
    scope = "totem_recognize"


class HeartbeatThrottle(ScopedRateThrottle):
    scope = "totem_heartbeat"


def _resposta_erro(codigo: str, mensagem: str, http=status.HTTP_200_OK, **extra):
    """
    Erro de negócio devolvido com HTTP 200 por padrão.

    "Rosto não identificado" não é falha da requisição: é um resultado
    previsto que leva o totem ao estado de fallback. Reservamos os status
    4xx para erros de fato (token inválido, payload malformado).
    """
    return Response(
        {"ok": False, "identificado": False, "codigo": codigo, "mensagem": mensagem, **extra},
        status=http,
    )


def _registrar_evento(totem, tipo, detalhes="", metadados=None):
    try:
        EventoTotem.objects.create(
            totem=totem, tipo=tipo, detalhes=detalhes[:255], metadados=metadados or {}
        )
    except Exception:
        logger.exception("Falha ao registrar evento do totem %s", totem.pk)


def _bater_ponto(colaborador, totem, request, *, metodo, confianca=None):
    """
    Grava a batida e monta a carga de sucesso do totem.

    Devolve `(payload, erro)`: quando `erro` não é nulo, o totem exibe a
    mensagem em vez da tela de sucesso.
    """
    try:
        registro = RegistroPontoService.registrar(
            colaborador=colaborador,
            metodo=metodo,
            totem=totem,
            confianca_face=confianca,
            request=request,
        )
    except validators.RegistroInvalido as erro:
        return None, erro

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.PONTO,
        descricao=(
            f"Ponto no totem {totem.identificador} — "
            f"{colaborador.nome_exibicao} ({registro.get_tipo_display()}) NSR {registro.nsr}"
        ),
        objeto=registro,
        empresa=colaborador.empresa,
        usuario=None,
    )

    return {
        "ok": True,
        "identificado": True,
        "colaborador": ColaboradorTotemSerializer(colaborador).data,
        "registro": RegistroTotemSerializer(registro).data,
        "mensagem": random.choice(MENSAGENS_TOTEM),
        "segundos_exibicao": totem.segundos_tela_sucesso,
    }, None


# ══════════════════════════════════════════════════════════════
# Reconhecimento facial
# ══════════════════════════════════════════════════════════════
@extend_schema(
    request=ReconhecimentoSerializer,
    responses={200: None},
    description="Recebe um frame JPEG em base64, identifica o colaborador e registra o ponto.",
    tags=["Totem"],
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([RecognizeThrottle])
def recognize(request):
    """Identificação facial e registro de ponto (Seção 8.2 do plano)."""
    serializer = ReconhecimentoSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    totem = request.totem
    servico = FaceRecognitionService()

    if not servico.disponivel:
        _registrar_evento(
            totem, EventoTotem.Tipo.ERRO, "Motor de reconhecimento indisponível"
        )
        return _resposta_erro(
            "motor_indisponivel",
            "Reconhecimento facial temporariamente indisponível. Use o CPF.",
        )

    resultado = servico.reconhecer(
        serializer.validated_data["image"],
        empresas=totem.empresas_atendidas(),
        totem=totem,
        guardar_frame=settings.FACE_GUARDAR_FRAME_TENTATIVA,
        ip=obter_ip(request),
    )

    if not resultado.identificado:
        _registrar_evento(
            totem,
            EventoTotem.Tipo.RECONHECIMENTO_FALHA,
            resultado.motivo,
            {"codigo": resultado.codigo, "tempo_ms": resultado.tempo_ms},
        )
        return _resposta_erro(
            resultado.codigo or "nao_identificado",
            resultado.motivo or "Rosto não identificado.",
            permite_fallback=totem.permite_fallback_cpf,
            tempo_ms=resultado.tempo_ms,
        )

    colaborador = resultado.colaborador

    if not serializer.validated_data.get("registrar_ponto", True):
        return Response(
            {
                "ok": True,
                "identificado": True,
                "colaborador": ColaboradorTotemSerializer(colaborador).data,
                "confianca": resultado.confianca,
                "tempo_ms": resultado.tempo_ms,
            }
        )

    payload, erro = _bater_ponto(
        colaborador,
        totem,
        request,
        metodo=MetodoRegistro.FACIAL,
        confianca=resultado.confianca,
    )
    if erro is not None:
        return _resposta_erro(
            erro.codigo,
            erro.mensagem,
            identificado=True,
            colaborador=ColaboradorTotemSerializer(colaborador).data,
            **erro.detalhes,
        )

    _registrar_evento(
        totem,
        EventoTotem.Tipo.RECONHECIMENTO_OK,
        f"{colaborador.nome_exibicao} — NSR {payload['registro']['nsr']}",
        {"distancia": resultado.distancia, "tempo_ms": resultado.tempo_ms},
    )
    payload["confianca"] = resultado.confianca
    payload["tempo_ms"] = resultado.tempo_ms
    return Response(payload)


# ══════════════════════════════════════════════════════════════
# Fallback por CPF
# ══════════════════════════════════════════════════════════════
@extend_schema(
    request=PunchCPFSerializer,
    responses={200: None},
    description="Registro de ponto por CPF e data de nascimento, quando o rosto não é identificado.",
    tags=["Totem"],
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([RecognizeThrottle])
def punch_cpf(request):
    """
    Fallback sempre disponível (regra 6 da Seção 14).

    O reconhecimento facial falha por iluminação, máscara, óculos ou
    simples ausência de cadastro — e nenhuma dessas situações pode
    impedir o trabalhador de registrar a jornada.
    """
    totem = request.totem
    if not totem.permite_fallback_cpf:
        return _resposta_erro(
            "fallback_desabilitado",
            "Este equipamento não permite registro por CPF.",
            http=status.HTTP_403_FORBIDDEN,
        )

    serializer = PunchCPFSerializer(data=request.data)
    if not serializer.is_valid():
        primeiro = next(iter(serializer.errors.values()))[0]
        return _resposta_erro("dados_invalidos", str(primeiro))

    colaborador = identificar_por_cpf(
        serializer.validated_data["cpf"],
        serializer.validated_data["data_nascimento"],
        totem.empresas_atendidas(),
    )

    if colaborador is None:
        _registrar_evento(
            totem, EventoTotem.Tipo.FALLBACK_CPF, "Dados não conferem"
        )
        # Mensagem propositalmente genérica: dizer "CPF existe mas a data
        # está errada" permitiria descobrir quem trabalha na empresa.
        return _resposta_erro(
            "dados_invalidos", "Dados inválidos. Verifique o CPF e a data de nascimento."
        )

    payload, erro = _bater_ponto(
        colaborador, totem, request, metodo=MetodoRegistro.CPF
    )
    if erro is not None:
        return _resposta_erro(
            erro.codigo,
            erro.mensagem,
            identificado=True,
            colaborador=ColaboradorTotemSerializer(colaborador).data,
            **erro.detalhes,
        )

    _registrar_evento(
        totem,
        EventoTotem.Tipo.FALLBACK_CPF,
        f"{colaborador.nome_exibicao} — NSR {payload['registro']['nsr']}",
    )
    return Response(payload)


# ══════════════════════════════════════════════════════════════
# Heartbeat
# ══════════════════════════════════════════════════════════════
@extend_schema(
    request=HeartbeatSerializer,
    responses={200: None},
    description="Sinal de vida do equipamento. Enviado a cada 30 segundos.",
    tags=["Totem"],
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([HeartbeatThrottle])
def heartbeat(request):
    """Atualiza o último sinal do totem e devolve a hora do servidor."""
    totem = request.totem
    serializer = HeartbeatSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    estava_offline = not totem.online

    totem.registrar_heartbeat(
        ip=obter_ip(request),
        versao=serializer.validated_data.get("versao"),
        bateria=serializer.validated_data.get("bateria"),
    )

    if estava_offline:
        _registrar_evento(
            totem, EventoTotem.Tipo.ONLINE, "Heartbeat restabelecido"
        )

    agora = timezone.localtime()
    return Response(
        {
            "ok": True,
            # O totem sincroniza o relógio pela resposta: o horário do
            # tablet pode estar errado, e o registro usa o do servidor.
            "servidor": {
                "iso": agora.isoformat(),
                "hora": agora.strftime("%H:%M:%S"),
                "data": agora.strftime("%d/%m/%Y"),
                "fuso": str(agora.tzinfo),
            },
            "totem": {
                "identificador": totem.identificador,
                "ativo": totem.ativo,
                "permite_fallback_cpf": totem.permite_fallback_cpf,
            },
        }
    )


# ══════════════════════════════════════════════════════════════
# Configuração
# ══════════════════════════════════════════════════════════════
@extend_schema(
    responses={200: None},
    description="Identidade visual e parâmetros de interface do equipamento.",
    tags=["Totem"],
)
@api_view(["GET"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
def config(request):
    """Configuração buscada pelo totem ao iniciar (Seção 7.3)."""
    return Response({"ok": True, **ConfigTotemSerializer(request.totem).data})
