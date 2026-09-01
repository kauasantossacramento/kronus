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
from django.core.cache import cache
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
from apps.core.constants import MetodoRegistro
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.core.utils import obter_ip
from apps.core.versao import versao_dos_estaticos
from apps.facial.services import FaceRecognitionService, identificar_por_cpf
from apps.ponto import validators
from apps.ponto.services import RegistroPontoService
from apps.facial.models import TentativaReconhecimento
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


def _felicitacao(colaborador) -> str:
    """
    Mensagem de aniversario, quando for o dia.

    Compara dia e mes, e nao a data inteira — o ano do nascimento nunca
    coincide com hoje, e comparar tudo nunca daria aniversario nenhum.

    Devolve texto vazio nos demais dias: assim a tela decide mostrar ou
    nao sem precisar de uma segunda chave no payload.
    """
    nascimento = getattr(colaborador, "data_nascimento", None)
    if not nascimento:
        return ""
    hoje = timezone.localdate()
    if (nascimento.day, nascimento.month) != (hoje.day, hoje.month):
        return ""
    primeiro = (colaborador.nome_exibicao or "").split()[0].title()
    return f"Feliz aniversário, {primeiro}!"


def _aniversariantes_de_hoje(totem) -> list:
    """
    Primeiros nomes de quem faz aniversario hoje, para a tela ociosa.

    Vai no heartbeat, que ja bate a cada 30 segundos, em vez de num
    endpoint novo: um totem fica ligado dias seguidos, e uma lista
    renderizada uma vez na abertura da pagina ainda estaria mostrando os
    aniversariantes de anteontem.

    Guardada em cache ate o fim do dia — a lista nao muda, e consultar o
    banco a cada 30 segundos por totem seria pagar caro por um dado
    parado.

    Segue as empresas que o totem atende: num grupo, o totem da recepcao
    atende varios CNPJs e o aniversario nao pertence a um deles so.
    """
    from apps.rh.models import Colaborador

    hoje = timezone.localdate()
    chave = f"kronus:aniversarios:{totem.pk}:{hoje.isoformat()}"
    guardado = cache.get(chave)
    if guardado is not None:
        return guardado

    try:
        empresas = totem.empresas_atendidas()
        pessoas = Colaborador.objects.filter(
            empresa__in=empresas,
            ativo=True,
            data_nascimento__day=hoje.day,
            data_nascimento__month=hoje.month,
        ).order_by("nome_completo")
        nomes = [
            (p.nome_exibicao or "").split()[0].title()
            for p in pessoas
            if (p.nome_exibicao or "").strip()
        ]
    except Exception:
        # Falha **nao** entra no cache.
        #
        # Guardar a falha era pior do que a falha: um blip no banco
        # durante um restart gravava lista vazia com validade ate a
        # meia-noite, e o aniversariante do dia passava o dia inteiro sem
        # aparecer — foi exatamente o que aconteceu.
        logger.exception("Falha ao levantar aniversariantes do totem %s", totem.pk)
        return []

    # Ate a virada do dia: a lista de amanha e outra, e um cache longo
    # deixaria o parabens atrasado.
    amanha = timezone.localtime().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    ate_meia_noite = max(60, int((amanha - timezone.localtime()).total_seconds()))

    # Lista vazia vale por pouco tempo; lista com gente vale o dia.
    #
    # "Ninguem faz aniversario hoje" e indistinguivel de "nao consegui
    # descobrir", e das duas a segunda se corrige sozinha se a pergunta
    # for refeita. O custo de refazer e uma consulta barata a cada cinco
    # minutos; o custo de nao refazer e o aniversario de alguem passar em
    # branco.
    cache.set(chave, nomes, ate_meia_noite if nomes else 300)
    return nomes


def _despedida(colaborador, registro) -> str:
    """
    "Ate amanha" quando a batida encerra a jornada.

    So na saida: a batida do intervalo tambem e uma "saida" no sentido
    coloquial, e quem volta do almoco ouvindo "ate amanha" fica em
    duvida se o ponto foi registrado no lugar certo.

    Sexta-feira ganha "bom fim de semana" — o "ate amanha" literal
    estaria errado, e errar isso e o tipo de detalhe que faz a mensagem
    parecer automatica demais.
    """
    from apps.core.constants import TipoRegistro

    if getattr(registro, "tipo", None) != TipoRegistro.SAIDA:
        return ""

    primeiro = (colaborador.nome_exibicao or "").split()
    nome = primeiro[0].title() if primeiro else ""
    # 4 = sexta-feira em `weekday()`.
    if timezone.localdate().weekday() == 4:
        return f"Bom fim de semana, {nome}!" if nome else "Bom fim de semana!"
    return f"Até amanhã, {nome}!" if nome else "Até amanhã!"


def _anotar_desfecho(resultado, desfecho) -> None:
    """
    Registra o que de fato aconteceu com a tentativa.

    "Identificado" nao quer dizer ponto batido. O primeiro quadro da
    dupla confirmacao identifica e nao grava nada; uma consulta
    identifica e nao grava nada; uma batida repetida identifica e e
    recusada pelo intervalo minimo.

    Sem esta anotacao, quem audita ve tres linhas iguais para tres
    desfechos diferentes — e foi exatamente essa confusao que levou a
    pergunta "estes retornaram sucesso?".
    """
    pk = getattr(resultado, "tentativa_id", None)
    if not pk:
        return
    try:
        TentativaReconhecimento.objects.filter(pk=pk).update(desfecho=desfecho)
    except Exception:  # pragma: no cover - auditoria nao derruba o ponto
        logger.exception("Falha ao anotar o desfecho da tentativa %s", pk)


def _conferir_segunda_opiniao(totem, colaborador):
    """
    Guarda o primeiro reconhecimento e cobra a confirmacao no proximo.

    Devolve `(confirmado, resposta)`. Quando ainda falta confirmar, a
    resposta leva `identificado=False` de proposito: o totem mostra
    "confirmando" e continua enviando quadros, e nenhum ponto e gravado
    ate os dois concordarem.

    A discordancia apaga os dois. Um nome no primeiro quadro e outro no
    segundo e o sistema dizendo que nao sabe — e nesse caso escolher
    qualquer um dos dois seria escolher no acaso.
    """
    chave = f"kronus:totem:confirmacao:{totem.pk}"
    pendente = cache.get(chave)

    if pendente == colaborador.pk:
        cache.delete(chave)
        return True, None

    if pendente is not None and pendente != colaborador.pk:
        cache.delete(chave)
        _registrar_evento(
            totem,
            EventoTotem.Tipo.RECONHECIMENTO_FALHA,
            "Quadros seguidos apontaram pessoas diferentes",
            {"primeiro": pendente, "segundo": colaborador.pk},
        )
        return False, _resposta_erro(
            "discordancia",
            "Não foi possível confirmar. Fique parado e tente de novo.",
            permite_fallback=totem.permite_fallback_cpf,
        )

    cache.set(chave, colaborador.pk, settings.FACE_SEGUNDOS_CONFIRMACAO)
    return False, Response(
        {
            "ok": True,
            "identificado": False,
            "codigo": "confirmando",
            "mensagem": "Confirmando…",
            "aguardando_confirmacao": True,
        }
    )


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
        # Aniversario de quem acabou de bater.
        #
        # Vai no proprio payload da batida, e nao numa consulta a parte:
        # a tela de sucesso dura poucos segundos, e uma segunda ida ao
        # servidor chegaria depois de ela ter sumido.
        "aniversario": _felicitacao(colaborador),
        # "Ate amanha" fecha a jornada. Perde para o aniversario: as
        # duas na mesma tela de poucos segundos viram parede de texto, e
        # o aniversario e o mais raro dos dois.
        "despedida": _despedida(colaborador, registro),
        # Da empresa quando ela definiu as suas; as padrao quando nao.
        # Da empresa quando ela definiu as suas; as padrao quando nao —
        # e sorteada ou fixa, conforme ela escolher.
        "mensagem": totem.empresa.frase_de_sucesso(),
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
        guardar_frame=(
            settings.FACE_GUARDAR_FRAME_TENTATIVA
            or totem.empresa.configuracao.guardar_frames_reconhecimento
        ),
        ip=obter_ip(request),
    )

    if not resultado.identificado:
        _anotar_desfecho(
            resultado, TentativaReconhecimento.Desfecho.RECUSADO
        )
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

    # -- segunda opiniao antes de registrar --------------------
    #
    # Um acerto por acaso vem de um quadro especifico — angulo, sombra,
    # movimento — e nao se repete no seguinte. Um reconhecimento
    # verdadeiro se repete. Exigir que dois quadros apontem a mesma
    # pessoa derruba o falso positivo de um quadro isolado, que e o que
    # confunde pessoas parecidas.
    #
    # **Mas so na faixa em que ha duvida.** O custo real medido nao foi
    # "cerca de um segundo": entre um quadro e o seguinte o totem precisa
    # reacumular estabilidade, esperar o debounce e pagar outra ida ao
    # servidor — 4,7 s numa batida real, e 10 s ou mais quando um quadro
    # se perde no meio. Numa fila, isso e o que faz o totem parecer mais
    # lento que anotar o ponto no papel.
    #
    # Abaixo de FACE_ACEITE_DIRETO nao ha duvida a resolver: a media de
    # acerto medida nesta base e 0,2254, e um reconhecimento a 0,13 esta
    # tao dentro do titular que um segundo quadro so confirmaria o que o
    # primeiro ja disse. A margem escalonada continua valendo, e e ela
    # que responde pelo caso dificil — a dupla confirmacao fica para a
    # faixa onde ela realmente decide alguma coisa.
    # Duas condicoes, e as duas precisam valer para dispensar o segundo
    # quadro: o reconhecimento tem de ser folgado **e** sem ninguem
    # perto. Só a primeira nao bastaria — um sosia pode dar uma leitura
    # confiante, e ai o que separa os dois nao e a confianca, e a
    # distancia ate o segundo colocado.
    segunda = getattr(resultado, "segunda_distancia", None)
    sem_ninguem_perto = (
        segunda is None
        or (segunda - (resultado.distancia or 0)) >= settings.FACE_FOLGA_SEM_CONFIRMAR
    )
    precisa_confirmar = not (
        resultado.distancia is not None
        and resultado.distancia < settings.FACE_ACEITE_DIRETO
        and sem_ninguem_perto
    )
    if (
        settings.FACE_DUPLA_CONFIRMACAO
        and precisa_confirmar
        and serializer.validated_data.get("registrar_ponto", True)
    ):
        confirmado, resposta = _conferir_segunda_opiniao(totem, colaborador)
        if not confirmado:
            _anotar_desfecho(
                resultado, TentativaReconhecimento.Desfecho.AGUARDANDO
            )
            return resposta

    if not serializer.validated_data.get("registrar_ponto", True):
        _anotar_desfecho(
            resultado, TentativaReconhecimento.Desfecho.SO_CONSULTA
        )
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

    # A batida que acabou de dar certo pode virar referencia do cadastro.
    # Depois de gravar o ponto, de proposito: aprender e ganho, e nao
    # pode ser o motivo de uma batida falhar.
    if erro is None:
        from apps.facial.aprendizado import registrar_aprendizado
        from apps.facial.processors import preparar

        try:
            registrar_aprendizado(
                servico, colaborador,
                preparar(serializer.validated_data["image"]),
                resultado,
            )
        except Exception:
            logger.exception("Aprendizado facial falhou — ignorado.")
    if erro is not None:
        # Reconheceu, e nao gravou: batida repetida dentro do intervalo
        # minimo, quase sempre. A tela mostra o aviso, e nao o sucesso.
        _anotar_desfecho(
            resultado,
            TentativaReconhecimento.Desfecho.DUPLICADO
            if erro.codigo == "intervalo_minimo"
            else TentativaReconhecimento.Desfecho.RECUSADO,
        )
        return _resposta_erro(
            erro.codigo,
            erro.mensagem,
            identificado=True,
            colaborador=ColaboradorTotemSerializer(colaborador).data,
            **erro.detalhes,
        )

    # Aqui, e so aqui, a tela mostra sucesso e o ponto existe.
    _anotar_desfecho(resultado, TentativaReconhecimento.Desfecho.PONTO)

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

    modo = (serializer.validated_data.get("modo_exibicao") or "").strip()
    if modo and modo != totem.modo_exibicao:
        totem.modo_exibicao = modo[:20]
        totem.save(update_fields=["modo_exibicao"])

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
            "aniversariantes": _aniversariantes_de_hoje(totem),
            # O totem compara com o que carregou. Numero maior, ou uma
            # recarga pedida pelo suporte, e ele se recarrega sozinho —
            # e por isso que trocar a logo no painel aparece no quiosque
            # sem ninguem ir ate o tablet.
            "config": {
                "versao": totem.empresa.config_versao,
                # Carimbo dos arquivos estaticos: muda a cada deploy.
                # E por ele que um totem instalado descobre que existe
                # codigo novo — o Service Worker tambem avisa, mas so
                # quando o navegador resolve conferi-lo, o que pode
                # demorar um dia. O heartbeat bate a cada 30 segundos.
                "estaticos": versao_dos_estaticos(),
                "recarregar_em": (
                    totem.recarga_solicitada_em.isoformat()
                    if totem.recarga_solicitada_em
                    else None
                ),
                # Recarga da pagina, pedida pelo suporte. Separada da de
                # cima: aquela aplica configuracao ao vivo, esta traz
                # codigo novo — e so a segunda faz a tela piscar.
                "recarga_total_em": (
                    totem.recarga_total_em.isoformat()
                    if totem.recarga_total_em
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
