"""
Kronus — cadastro facial feito no proprio totem.

Por que existe. Um rosto cadastrado pela webcam do computador e
reconhecido pela camera do tablet com folga bem menor: otica, resolucao
e iluminacao diferentes produzem vetores em regioes diferentes do
espaco. Cadastrar no mesmo equipamento em que a pessoa vai bater o ponto
elimina essa diferenca na origem — e sai mais barato do que compensa-la
depois afrouxando o limiar, que e o caminho que leva a reconhecer a
pessoa errada.

O que este modo NAO e. Nao e uma via alternativa de autenticacao: nao
registra ponto, nao consulta espelho e nao expoe dado de ninguem alem do
nome de quem esta na lista. Ele so cadastra rosto.

Como e protegido. O totem fica na parede, ao alcance de quem passa.
Entao:

  · a porta so existe quando o cliente a liga **e** define uma senha;
  · a senha e guardada com hash e conferida com tentativa limitada;
  · a sessao dura minutos, e vive no servidor — revogar e imediato;
  · entrada, recusa e captura viram evento do totem e log de acesso.
"""
import logging
import secrets

from django.conf import settings
from django.core.cache import cache
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
    AmostraTotemSerializer,
    ConsentimentoTotemSerializer,
    EntrarManutencaoSerializer,
)
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.facial.processors import ImagemInvalida
from apps.facial.providers import ErroReconhecimento
from apps.facial.services import FaceRecognitionService
from apps.rh.models import Colaborador
from apps.totem.models import EventoTotem

logger = logging.getLogger("kronus.totem")

#: Duracao da sessao de manutencao.
#:
#: Curta de proposito: quem cadastra fica na frente do equipamento, e
#: uma sessao longa e uma sessao esquecida aberta na parede.
MINUTOS_SESSAO = 20

#: Tentativas de senha antes do bloqueio, e por quanto tempo.
#:
#: A senha e digitada num teclado de tela por alguem em pe — errar
#: acontece. Mas um tablet ao alcance de todos tambem convida a tentar.
MAX_TENTATIVAS = 5
MINUTOS_BLOQUEIO = 15

PREFIXO_SESSAO = "kronus:totem:manutencao"
PREFIXO_TENTATIVAS = "kronus:totem:manutencao:tentativas"


class ManutencaoThrottle(ScopedRateThrottle):
    scope = "totem_manutencao"


def _chave_tentativas(totem) -> str:
    return f"{PREFIXO_TENTATIVAS}:{totem.pk}"


def _bloqueado(totem) -> bool:
    return cache.get(_chave_tentativas(totem), 0) >= MAX_TENTATIVAS


def _registrar_evento(totem, detalhes: str) -> None:
    try:
        EventoTotem.objects.create(
            totem=totem,
            tipo=EventoTotem.Tipo.CONFIGURACAO,
            detalhes=detalhes[:255],
        )
    except Exception:  # pragma: no cover - auditoria nunca derruba o fluxo
        logger.exception("Falha ao registrar evento de manutencao %s", totem.pk)


def _sessao_valida(request) -> bool:
    """
    A sessao vive no cache do servidor, e nao num token assinado.

    Assim revogar e imediato: apagar a chave encerra a sessao aberta no
    equipamento, sem esperar a expiracao de algo que ja saiu daqui.
    """
    chave = request.headers.get("X-Manutencao", "")
    if not chave:
        return False
    guardado = cache.get(f"{PREFIXO_SESSAO}:{request.totem.pk}")
    return bool(guardado) and secrets.compare_digest(guardado, chave)


def _recusar_sem_sessao():
    return Response(
        {
            "ok": False,
            "codigo": "sem_sessao",
            "mensagem": "Sessão de manutenção expirada. Entre novamente.",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _pessoa_do_totem(totem, colaborador_id):
    """
    Busca restrita as empresas do totem.

    Sem esse recorte, um id vindo da tela alcancaria colaborador de outro
    cliente: o equipamento tem token proprio, mas o numero digitado do
    outro lado nao e confiavel.
    """
    return (
        Colaborador.objects.filter(
            pk=colaborador_id,
            empresa__in=totem.empresas_atendidas(),
            ativo=True,
            deleted_at__isnull=True,
        )
        .select_related("empresa")
        .first()
    )


@extend_schema(
    request=EntrarManutencaoSerializer,
    responses={200: None},
    description="Abre a sessão de manutenção do totem mediante senha do cliente.",
    tags=["Totem"],
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([ManutencaoThrottle])
def entrar(request):
    totem = request.totem
    cliente = totem.empresa.cliente

    if not cliente.cadastro_no_totem_disponivel:
        # Mesma resposta de senha errada. Dizer "esta desligado"
        # confirmaria a quem tentou que a porta existe neste modelo de
        # equipamento — e ele esta na parede, exposto a qualquer um.
        return Response(
            {"ok": False, "codigo": "indisponivel", "mensagem": "Senha incorreta."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if _bloqueado(totem):
        return Response(
            {
                "ok": False,
                "codigo": "bloqueado",
                "mensagem": f"Muitas tentativas. Aguarde {MINUTOS_BLOQUEIO} minutos.",
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    serializer = EntrarManutencaoSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    if not cliente.conferir_senha_totem(serializer.validated_data["senha"]):
        tentativas = cache.get(_chave_tentativas(totem), 0) + 1
        cache.set(_chave_tentativas(totem), tentativas, MINUTOS_BLOQUEIO * 60)
        _registrar_evento(totem, f"Senha de manutencao incorreta ({tentativas})")
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.SEGURANCA,
            descricao=(
                f"Senha de manutenção incorreta no totem "
                f"{totem.identificador} (tentativa {tentativas})"
            ),
            empresa=totem.empresa,
            usuario=None,
        )
        return Response(
            {
                "ok": False,
                "codigo": "senha_incorreta",
                "mensagem": "Senha incorreta.",
                "restantes": max(MAX_TENTATIVAS - tentativas, 0),
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    cache.delete(_chave_tentativas(totem))
    chave = secrets.token_urlsafe(32)
    cache.set(f"{PREFIXO_SESSAO}:{totem.pk}", chave, MINUTOS_SESSAO * 60)

    _registrar_evento(totem, "Modo de manutencao aberto")
    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=f"Modo de manutenção aberto no totem {totem.identificador}",
        empresa=totem.empresa,
        usuario=None,
    )
    return Response(
        {
            "ok": True,
            "chave": chave,
            "expira_em_minutos": MINUTOS_SESSAO,
            "empresa": totem.empresa.nome_exibicao,
        }
    )


@extend_schema(
    responses={200: None},
    description="Colaboradores elegíveis a cadastro facial neste totem.",
    tags=["Totem"],
)
@api_view(["GET"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([ManutencaoThrottle])
def colaboradores(request):
    totem = request.totem
    if not _sessao_valida(request):
        return _recusar_sem_sessao()

    # As mesmas empresas que o totem ja reconhece: um totem de grupo
    # cadastra quem ele reconheceria, e ninguem alem disso.
    pessoas = (
        Colaborador.objects.filter(
            empresa__in=totem.empresas_atendidas(),
            ativo=True,
            deleted_at__isnull=True,
        )
        .select_related("empresa")
        .order_by("nome_completo")
    )

    return Response(
        {
            "ok": True,
            "colaboradores": [
                {
                    "id": p.pk,
                    "nome": p.nome_exibicao,
                    "empresa": p.empresa.nome_exibicao,
                    # Sem CPF: a lista fica aberta na tela de um aparelho
                    # de parede, e escolher um nome nao exige o documento
                    # de ninguem.
                    "matricula": p.matricula or "",
                    "consentimento": p.consentimento_biometrico,
                    "amostras": p.registros_faciais.filter(ativo=True).count(),
                }
                for p in pessoas
            ],
        }
    )


@extend_schema(
    request=ConsentimentoTotemSerializer,
    responses={200: None},
    description="Registra o consentimento LGPD colhido na tela do totem.",
    tags=["Totem"],
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([ManutencaoThrottle])
def consentimento(request):
    totem = request.totem
    if not _sessao_valida(request):
        return _recusar_sem_sessao()

    serializer = ConsentimentoTotemSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    if not serializer.validated_data["aceite"]:
        return Response(
            {
                "ok": False,
                "codigo": "sem_aceite",
                "mensagem": "É necessário confirmar o consentimento.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    pessoa = _pessoa_do_totem(totem, serializer.validated_data["colaborador_id"])
    if pessoa is None:
        return Response(
            {
                "ok": False,
                "codigo": "nao_encontrado",
                "mensagem": "Colaborador não encontrado neste equipamento.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    pessoa.registrar_consentimento_biometrico()
    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=(
            f"Consentimento biométrico registrado no totem "
            f"{totem.identificador} — {pessoa.nome_exibicao}"
        ),
        objeto=pessoa,
        empresa=pessoa.empresa,
        usuario=None,
    )
    return Response({"ok": True})


@extend_schema(
    request=AmostraTotemSerializer,
    responses={200: None},
    description="Grava uma captura facial feita no totem.",
    tags=["Totem"],
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([ManutencaoThrottle])
def amostra(request):
    totem = request.totem
    if not _sessao_valida(request):
        return _recusar_sem_sessao()

    serializer = AmostraTotemSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    pessoa = _pessoa_do_totem(totem, serializer.validated_data["colaborador_id"])
    if pessoa is None:
        return Response(
            {
                "ok": False,
                "codigo": "nao_encontrado",
                "mensagem": "Colaborador não encontrado neste equipamento.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    # O consentimento vem antes da camera, e nao depois: capturar
    # primeiro e perguntar em seguida ja teria tratado o dado biometrico.
    if not pessoa.consentimento_biometrico:
        return Response(
            {
                "ok": False,
                "codigo": "sem_consentimento",
                "mensagem": "Registre o consentimento antes de capturar.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    servico = FaceRecognitionService()
    try:
        registro = servico.cadastrar_amostra(
            pessoa,
            serializer.validated_data["imagem"],
            angulo=serializer.validated_data.get("angulo") or "frontal",
        )
    except (ImagemInvalida, ErroReconhecimento) as erro:
        # HTTP 200 de proposito: "melhore a iluminacao" e orientacao ao
        # operador, e nao falha da requisicao.
        return Response(
            {
                "ok": False,
                "codigo": getattr(erro, "codigo", "imagem_invalida"),
                "mensagem": getattr(erro, "mensagem", str(erro)),
            }
        )

    total = pessoa.registros_faciais.filter(ativo=True).count()
    servico.consolidar_cadastro(pessoa)

    _registrar_evento(
        totem, f"Amostra facial cadastrada — {pessoa.nome_exibicao} ({total})"
    )
    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=(
            f"Biometria facial cadastrada no totem {totem.identificador} — "
            f"{pessoa.nome_exibicao} (amostra {total})"
        ),
        objeto=pessoa,
        empresa=pessoa.empresa,
        usuario=None,
    )
    # O espalhamento vai junto para que quem esta cadastrando saiba, ali
    # mesmo, que o cadastro saiu fraco — e refaca enquanto a pessoa ainda
    # esta na frente da camera. Descobrir isso semanas depois, pelo
    # colaborador que nunca e reconhecido, e tarde.
    espalhamento = servico.espalhamento(pessoa)
    limite = settings.FACE_ESPALHAMENTO_ACEITAVEL
    fraco = espalhamento is not None and espalhamento > limite

    return Response(
        {
            "ok": True,
            "qualidade": round(registro.qualidade, 1),
            "amostras": total,
            "espalhamento": round(espalhamento, 3) if espalhamento else None,
            "cadastro_fraco": fraco,
            "aviso": (
                "As capturas estão muito diferentes entre si. Refaça o "
                "cadastro com iluminação estável e sem virar demais o rosto."
            ) if fraco else "",
        }
    )


@extend_schema(
    responses={200: None},
    description="Encerra a sessão de manutenção.",
    tags=["Totem"],
)
@api_view(["POST"])
@authentication_classes([TotemAuthentication])
@permission_classes([TotemAutenticado])
@throttle_classes([ManutencaoThrottle])
def sair(request):
    cache.delete(f"{PREFIXO_SESSAO}:{request.totem.pk}")
    _registrar_evento(request.totem, "Modo de manutencao encerrado")
    return Response({"ok": True})
