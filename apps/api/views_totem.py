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
from datetime import timedelta

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


def _registrar_degradacao(totem, motivo: str) -> None:
    """
    Anota que o totem esta sem reconhecimento facial.

    O heartbeat chega a cada 30 segundos; anotar todos encheria o
    historico de linhas iguais e esconderia os eventos que importam.
    Registra a primeira vez e depois so uma vez por hora, o suficiente
    para mostrar que o problema persiste.
    """
    limite = timezone.now() - timedelta(hours=1)
    ja_avisado = EventoTotem.objects.filter(
        totem=totem,
        tipo=EventoTotem.Tipo.ERRO,
        detalhes__startswith="Reconhecimento facial indisponivel",
        created_at__gte=limite,
    ).exists()
    if ja_avisado:
        return
    _registrar_evento(
        totem,
        EventoTotem.Tipo.ERRO,
        f"Reconhecimento facial indisponivel: {motivo}",
    )


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

    # ── Prova de vida ──────────────────────────────────────
    # Roda **antes** do reconhecimento: gastar 217 ms identificando uma
    # foto impressa e so depois recusa-la seria desperdicio de CPU num
    # servidor de um nucleo. E, mais importante, a recusa por spoofing
    # nao deve revelar se a foto correspondia a alguem cadastrado.
    config = getattr(totem.empresa, "config", None)
    if config is not None and config.exigir_liveness:
        quadros_b64 = serializer.validated_data.get("quadros") or []
        if not quadros_b64:
            return _resposta_erro(
                "liveness_ausente",
                "Siga a instrução na tela para confirmar que é você.",
                permite_fallback=totem.permite_fallback_cpf,
            )

        from apps.facial.liveness import LivenessRecusado, LivenessService
        from apps.facial.processors import preparar

        try:
            quadros = [preparar(q) for q in quadros_b64]
            LivenessService(provedor=servico.provedor).verificar(
                quadros, desafio=serializer.validated_data.get("desafio")
            )
        except LivenessRecusado as recusa:
            _registrar_evento(
                totem,
                EventoTotem.Tipo.RECONHECIMENTO_FALHA,
                f"Prova de vida recusada: {recusa.codigo}",
                recusa.detalhes,
            )
            return _resposta_erro(
                recusa.codigo, recusa.mensagem,
                permite_fallback=totem.permite_fallback_cpf,
            )
        except Exception:
            # Falha do proprio verificador nao pode travar o ponto: a
            # prova de vida e uma camada a mais, nao a obrigacao legal.
            logger.exception("Falha ao verificar prova de vida.")

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

    degradado = (serializer.validated_data.get("degradado") or "").strip()
    if degradado:
        _registrar_degradacao(totem, degradado)

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
            # O totem compara com o que carregou. Numero maior, ou uma
            # recarga pedida pelo suporte, e ele se recarrega sozinho —
            # e por isso que trocar a logo no painel aparece no quiosque
            # sem ninguem ir ate o tablet.
            "config": {
                "versao": totem.empresa.config_versao,
                "recarregar_em": (
                    totem.recarga_solicitada_em.isoformat()
                    if totem.recarga_solicitada_em
                    else None
                ),
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


# ══════════════════════════════════════════════════════════════
# Modo sem conexão
# ══════════════════════════════════════════════════════════════
@extend_schema(
    tags=["Totem"],
    summary="Colaboradores para uso sem conexão",
    description=(
        "Lista que o totem guarda localmente para identificar quem bate o "
        "ponto quando a conexão cai. **Não traz CPF em claro**: o coletor "
        "recebe um resumo criptográfico e compara com o que for digitado."
    ),
)
@api_view(["GET"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
def colaboradores_offline(request):
    """
    Cache de identificacao para o modo sem conexao.

    **Por que nao mandar o CPF.** A lista fica num tablet de portaria, que
    e roubavel e compartilhado. Mandar CPF em claro seria despejar a base
    de documentos da empresa num aparelho sem custodia. O coletor recebe
    um HMAC de CPF+nascimento, calculado com uma chave derivada do token
    do totem: ele consegue **verificar** quem digitou, e nao consegue
    **listar** ninguem.

    Rotacionar o token do totem invalida a lista inteira, que e o
    comportamento desejado quando um equipamento e perdido.
    """
    from apps.rh.models import Colaborador
    from apps.totem.identificacao import (
        ITERACOES,
        resumo_de_identificacao,
        sal_do_totem,
    )

    totem = request.auth
    empresas = list(totem.empresas_atendidas().values_list("pk", flat=True))
    colaboradores = (
        Colaborador.objects.filter(
            empresa_id__in=empresas,
            ativo=True,
            deleted_at__isnull=True,
        )
        # Sem `.only()`: combinado com o queryset proprio do Colaborador,
        # ele faz o construtor de consultas do Django recursar ate
        # estourar. A economia seria de alguns campos numa lista de
        # dezenas de linhas — nao vale o risco.
        .order_by("nome_completo")
    )

    lista = [
        {
            "id": c.pk,
            "nome": c.nome_completo,
            "identificacao": resumo_de_identificacao(
                totem, c.cpf, c.data_nascimento
            ),
        }
        for c in colaboradores
        if c.data_nascimento
    ]

    return Response({
        "colaboradores": lista,
        # O sal e as iteracoes viajam junto: o coletor precisa deles para
        # refazer a derivacao do que for digitado. Nao sao segredo — quem
        # protege e o custo de cada derivacao.
        "sal": sal_do_totem(totem),
        "iteracoes": ITERACOES,
        "gerado_em": timezone.now().isoformat(),
        "total": len(lista),
    })


@extend_schema(
    tags=["Totem"],
    summary="Enviar marcações registradas sem conexão",
    description=(
        "Recebe a fila do totem. Idempotente pelo identificador de cada "
        "marcação: reenviar não duplica."
    ),
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
def sincronizar_offline(request):
    """
    Grava a fila acumulada pelo coletor.

    Responde o destino de **cada** item. O totem só apaga da fila o que
    voltar como aceita ou duplicada: apagar em silêncio uma recusada
    perderia o registro de trabalho de alguém.
    """
    from apps.ponto.sincronizacao import sincronizar

    totem = request.auth
    itens = request.data.get("marcacoes") or []
    # Estes dois sao erros de requisicao, e nao resultados de negocio —
    # por isso 400, e nao o 200 que o totem usa para "nao identificado".
    if not isinstance(itens, list):
        return _resposta_erro(
            "formato_invalido", "Formato inesperado.",
            http=status.HTTP_400_BAD_REQUEST,
        )
    if len(itens) > 500:
        # Um lote gigante e sinal de problema, nao de uso. Recusar em
        # bloco evita segurar a transacao por minutos.
        return _resposta_erro(
            "lote_grande", "Envie no máximo 500 marcações por vez.",
            http=status.HTTP_400_BAD_REQUEST,
        )

    resultados = sincronizar(totem, itens)

    if resultados:
        _registrar_evento(
            totem,
            EventoTotem.Tipo.ONLINE,
            f"Sincronizadas {len(resultados)} marcação(ões) da fila offline.",
        )

    return Response({"ok": True, "resultados": resultados})
