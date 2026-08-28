"""
Kronus — despacho de webhooks (Seção 8.8 do plano).

O model `Webhook` existe desde a Fase 1; aqui está o que o faz entregar.

**O contrato com o receptor.** Toda entrega é um POST JSON com:

    POST https://erp.cliente.com/kronus/
    Content-Type: application/json
    X-Kronus-Event: ponto.registrado
    X-Kronus-Delivery: 8f3a…            (uuid, para deduplicação)
    X-Kronus-Timestamp: 1756...          (epoch, para janela de replay)
    X-Kronus-Signature: sha256=abc123…   (HMAC do corpo + timestamp)

    {"evento": "...", "empresa": {...}, "ocorrido_em": "...", "dados": {...}}

O timestamp entra na assinatura, e não só no header, porque assinar só
o corpo permitiria reenviar uma entrega antiga válida indefinidamente.
Com o timestamp dentro do HMAC, o receptor pode recusar qualquer coisa
fora de uma janela de minutos sem que o atacante possa reescrevê-la.

**Por que nada é enviado dentro da transação.** Um webhook é uma chamada
de rede a um servidor de terceiro: pode travar por 30 s, pode falhar,
pode ser lento. Se ele rodasse dentro do `atomic` que grava o ponto, o
totem ficaria esperando o ERP do cliente. Todo despacho passa por
`transaction.on_commit` e vai para a fila — o ponto é gravado e
confirmado sem depender de ninguém.

**Falha não perde evento.** Cada tentativa grava uma `EntregaWebhook`. O
retry é exponencial (1 min, 5 min, 25 min, 2 h, 10 h); depois de 5
falhas consecutivas o webhook é desativado e o RH notificado — um
endpoint morto não deve consumir fila para sempre.
"""
import hashlib
import hmac
import json
import logging
import uuid

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("kronus.webhooks")

#: Espera antes de cada retentativa, em segundos. O índice é o número
#: de tentativas já feitas. Cresce rápido de propósito: se o endereço
#: do cliente caiu, insistir de minuto em minuto não o levanta.
BACKOFF_SEGUNDOS = (60, 300, 1500, 7200, 36000)

#: Falhas consecutivas que desativam o webhook.
LIMITE_FALHAS = 5

#: Tempo máximo de espera por resposta. Um receptor que demora mais que
#: isso deve enfileirar do lado dele, não segurar nossa fila.
TIMEOUT_SEGUNDOS = 10


# ══════════════════════════════════════════════════════════════
# Assinatura
# ══════════════════════════════════════════════════════════════
def assinar(corpo: bytes, segredo: str, timestamp: int) -> str:
    """
    Devolve o valor de `X-Kronus-Signature`.

    Formato `sha256=<hex>`, com o prefixo do algoritmo explícito para
    que uma futura troca de algoritmo não quebre receptores antigos:
    eles conseguem ver que a assinatura mudou de família.
    """
    mensagem = f"{timestamp}.".encode("utf-8") + corpo
    digest = hmac.new(
        segredo.encode("utf-8"), mensagem, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def assinatura_confere(corpo: bytes, segredo: str, timestamp: int, recebida: str) -> bool:
    """
    Verificação do lado do receptor — publicada aqui para servir de
    referência na documentação da integração.

    Usa `compare_digest`: comparar com `==` vazaria o número de bytes
    corretos pelo tempo de execução.
    """
    esperada = assinar(corpo, segredo, timestamp)
    return hmac.compare_digest(esperada, recebida or "")


# ══════════════════════════════════════════════════════════════
# Montagem do payload
# ══════════════════════════════════════════════════════════════
def _serializar(obj):
    """Converte o objeto de domínio no dicionário que vai no `dados`."""
    from apps.ponto.models import RegistroPonto
    from apps.rh.models import Atestado, Colaborador

    if isinstance(obj, RegistroPonto):
        return {
            "uuid": str(obj.uuid),
            "nsr": obj.nsr,
            "data_hora": obj.data_hora.isoformat(),
            "tipo": obj.tipo,
            "metodo": obj.metodo,
            "hash_registro": obj.hash_registro,
            "cancelado": obj.cancelado,
            "colaborador": {
                "uuid": str(obj.colaborador.uuid),
                "cpf": obj.colaborador.cpf,
                "nome": obj.colaborador.nome_exibicao,
                "matricula": obj.colaborador.matricula,
            },
        }

    if isinstance(obj, Colaborador):
        return {
            "uuid": str(obj.uuid),
            "cpf": obj.cpf,
            "nome": obj.nome_exibicao,
            "matricula": obj.matricula,
            "cargo": obj.cargo,
            "data_admissao": obj.data_admissao.isoformat() if obj.data_admissao else None,
            "data_demissao": obj.data_demissao.isoformat() if obj.data_demissao else None,
            "ativo": obj.ativo,
        }

    if isinstance(obj, Atestado):
        # Sem CID: dado de saúde não sai da plataforma (LGPD, Art. 5º, II).
        return {
            "uuid": str(obj.uuid),
            "colaborador": {
                "uuid": str(obj.colaborador.uuid),
                "cpf": obj.colaborador.cpf,
                "nome": obj.colaborador.nome_exibicao,
            },
            "data_inicio": obj.data_inicio.isoformat(),
            "data_fim": obj.data_fim.isoformat(),
            "dias": obj.dias,
            "status": obj.status,
        }

    if isinstance(obj, dict):
        return obj

    return {"uuid": str(getattr(obj, "uuid", "")), "repr": str(obj)}


def montar_payload(evento: str, empresa, objeto) -> dict:
    """Envelope comum a todos os eventos."""
    return {
        "evento": evento,
        "ocorrido_em": timezone.now().isoformat(),
        "empresa": {
            "uuid": str(empresa.uuid),
            "cnpj": empresa.cnpj,
            "razao_social": empresa.razao_social,
        },
        "dados": _serializar(objeto),
    }


# ══════════════════════════════════════════════════════════════
# Disparo
# ══════════════════════════════════════════════════════════════
def disparar(evento: str, empresa, objeto):
    """
    Enfileira o evento para todos os webhooks da empresa que o assinam.

    Chamado de dentro de transações — por isso o `on_commit`. Se a
    transação der rollback, nada é entregue: não existe webhook de um
    ponto que não foi gravado.
    """
    from apps.notificacoes.models import Webhook

    if empresa is None:
        return []

    # `tem_webhook` é do plano: quem não contratou não dispara, mesmo
    # que tenha um webhook cadastrado de um plano anterior.
    plano = getattr(getattr(empresa, "cliente", None), "plano", None)
    if plano is not None and not plano.tem_webhook:
        return []

    inscritos = [
        webhook
        for webhook in Webhook.objects.filter(empresa=empresa, ativo=True)
        if webhook.assina(evento)
    ]
    if not inscritos:
        return []

    payload = montar_payload(evento, empresa, objeto)
    entregas = []

    for webhook in inscritos:
        entrega = _criar_entrega(webhook, evento, payload)
        entregas.append(entrega)
        transaction.on_commit(_agendador(entrega.pk))

    return entregas


def _criar_entrega(webhook, evento, payload):
    from apps.notificacoes.models import EntregaWebhook

    return EntregaWebhook.objects.create(
        webhook=webhook,
        empresa=webhook.empresa,
        evento=evento,
        identificador=uuid.uuid4(),
        payload=payload,
    )


def _agendador(entrega_pk):
    """Devolve o callable que o `on_commit` executa."""

    def _enfileirar():
        from apps.notificacoes.tasks import entregar_webhook

        try:
            entregar_webhook.delay(entrega_pk)
        except Exception:  # broker fora do ar
            # Não perdemos o evento: a entrega já está no banco como
            # pendente, e `reprocessar_entregas_pendentes` a recupera.
            logger.warning(
                "Broker indisponível ao enfileirar entrega %s; ficará pendente.",
                entrega_pk,
            )

    return _enfileirar


# ══════════════════════════════════════════════════════════════
# Execução da entrega
# ══════════════════════════════════════════════════════════════
def executar(entrega) -> bool:
    """
    Faz a chamada HTTP e atualiza o estado da entrega.

    Devolve `True` se o receptor respondeu 2xx. Qualquer outra coisa —
    4xx, 5xx, timeout, DNS — conta como falha e agenda retentativa.
    """
    import requests

    webhook = entrega.webhook
    corpo = json.dumps(entrega.payload, ensure_ascii=False).encode("utf-8")
    momento = int(timezone.now().timestamp())

    cabecalhos = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Kronus-Webhook/1.0",
        "X-Kronus-Event": entrega.evento,
        "X-Kronus-Delivery": str(entrega.identificador),
        "X-Kronus-Timestamp": str(momento),
        "X-Kronus-Signature": assinar(corpo, webhook.segredo, momento),
    }

    entrega.tentativas += 1
    entrega.ultima_tentativa = timezone.now()

    try:
        resposta = requests.post(
            webhook.url, data=corpo, headers=cabecalhos, timeout=TIMEOUT_SEGUNDOS
        )
        entrega.status_code = resposta.status_code
        # Guardamos um trecho da resposta: quando o cliente diz que "não
        # chegou", o corpo do 4xx dele costuma explicar por quê.
        entrega.resposta = (resposta.text or "")[:500]
        sucesso = 200 <= resposta.status_code < 300
    except Exception as erro:
        entrega.status_code = None
        entrega.resposta = f"{type(erro).__name__}: {erro}"[:500]
        sucesso = False

    if sucesso:
        entrega.status = entrega.Status.ENTREGUE
        entrega.entregue_em = timezone.now()
        entrega.proxima_tentativa = None
        _marcar_sucesso(webhook, entrega.status_code)
    else:
        _agendar_retentativa(entrega)
        _marcar_falha(webhook, entrega.status_code)

    entrega.save()
    return sucesso


def _agendar_retentativa(entrega):
    if entrega.tentativas >= len(BACKOFF_SEGUNDOS):
        entrega.status = entrega.Status.DESISTIU
        entrega.proxima_tentativa = None
        logger.error(
            "Webhook %s desistiu do evento %s após %s tentativas.",
            entrega.webhook_id, entrega.evento, entrega.tentativas,
        )
        return

    espera = BACKOFF_SEGUNDOS[entrega.tentativas - 1]
    entrega.status = entrega.Status.PENDENTE
    entrega.proxima_tentativa = timezone.now() + timezone.timedelta(seconds=espera)


def _marcar_sucesso(webhook, status_code):
    webhook.ultima_entrega = timezone.now()
    webhook.ultimo_status = status_code
    webhook.falhas_consecutivas = 0
    webhook.save(
        update_fields=[
            "ultima_entrega", "ultimo_status", "falhas_consecutivas", "updated_at",
        ]
    )


def _marcar_falha(webhook, status_code):
    webhook.ultima_entrega = timezone.now()
    webhook.ultimo_status = status_code
    webhook.falhas_consecutivas += 1
    campos = [
        "ultima_entrega", "ultimo_status", "falhas_consecutivas", "updated_at",
    ]

    if webhook.falhas_consecutivas >= LIMITE_FALHAS:
        # Desativar é a escolha certa: um endpoint que falhou 5 vezes
        # seguidas está fora do ar ou mudou de endereço, e continuar
        # tentando só entope a fila. O RH reativa depois de corrigir.
        webhook.ativo = False
        campos.append("ativo")
        logger.error(
            "Webhook %s desativado após %s falhas consecutivas.",
            webhook.pk, webhook.falhas_consecutivas,
        )

    webhook.save(update_fields=campos)
