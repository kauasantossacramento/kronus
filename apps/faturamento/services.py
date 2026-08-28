"""
Kronus — ciclo de vida das assinaturas.

Toda regra comercial mora aqui, e nenhuma chamada de rede acontece sem
passar por `ClienteAsaas`. A separação é o que torna estes testes
possíveis sem gateway.

**A regra que atravessa o módulo: o gateway manda no dinheiro, nós
mandamos no acesso.** Quem decide que uma fatura foi paga é o ASAAS;
quem decide se a empresa continua batendo ponto somos nós — e essa
segunda decisão tem uma tolerância deliberada, porque boleto compensa
em até três dias úteis e suspender antes disso tira o relógio de ponto
de um cliente que já pagou.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.utils import apenas_digitos

logger = logging.getLogger("kronus.faturamento")

#: Estados do ASAAS mapeados para os nossos.
STATUS_ASAAS = {
    "PENDING": "pendente",
    "AWAITING_RISK_ANALYSIS": "pendente",
    "CONFIRMED": "confirmada",
    "RECEIVED": "recebida",
    "RECEIVED_IN_CASH": "recebida",
    "OVERDUE": "vencida",
    "REFUNDED": "estornada",
    "REFUND_REQUESTED": "estornada",
    "CHARGEBACK_REQUESTED": "estornada",
    "CHARGEBACK_DISPUTE": "estornada",
    "DELETED": "cancelada",
}

#: Eventos que mexem no estado de uma cobrança.
EVENTOS_TRATADOS = {
    "PAYMENT_CREATED",
    "PAYMENT_UPDATED",
    "PAYMENT_CONFIRMED",
    "PAYMENT_RECEIVED",
    "PAYMENT_OVERDUE",
    "PAYMENT_DELETED",
    "PAYMENT_REFUNDED",
    "PAYMENT_RECEIVED_IN_CASH_UNDONE",
    "PAYMENT_CHARGEBACK_REQUESTED",
}


class AssinaturaService:
    """Contratação, upgrade, cancelamento e reconciliação."""

    #: Dias de teste concedidos a uma contratação nova.
    DIAS_DE_TESTE = 7

    # ══════════════════════════════════════════════════════════
    # Contratação
    # ══════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def contratar(cls, *, cliente, plano, ciclo=None, forma_pagamento=None,
                  colaboradores_extras=0, com_teste=True):
        """
        Cria (ou troca) a assinatura de um cliente.

        Nasce em **período de teste** por padrão: o cliente cadastra a
        empresa e começa a usar no mesmo minuto, e a primeira cobrança
        vence depois. Exigir pagamento antes do primeiro acesso é o que
        faz a maioria desistir na tela de checkout.
        """
        from apps.faturamento.models import Assinatura, ConfiguracaoGateway

        config = ConfiguracaoGateway.carregar()
        hoje = timezone.localdate()
        ciclo = ciclo or Assinatura.Ciclo.MENSAL

        valor = cls._valor_do_ciclo(plano, ciclo)

        assinatura, criada = Assinatura.objects.get_or_create(
            cliente=cliente,
            defaults={
                "plano": plano,
                "ciclo": ciclo,
                "valor": valor,
                "colaboradores_contratados": colaboradores_extras,
                "forma_pagamento": forma_pagamento or Assinatura.FormaPagamento.INDEFINIDO,
            },
        )

        if not criada:
            # Troca de plano numa assinatura existente é upgrade, não
            # nova contratação: preserva histórico e ids do gateway.
            return cls.trocar_plano(
                assinatura=assinatura, plano=plano, ciclo=ciclo,
                colaboradores_extras=colaboradores_extras,
            )

        if com_teste:
            assinatura.status = Assinatura.Status.TESTE
            assinatura.data_fim_teste = hoje + timedelta(days=cls.DIAS_DE_TESTE)
            assinatura.proxima_cobranca = assinatura.data_fim_teste
        else:
            assinatura.status = Assinatura.Status.PENDENTE
            assinatura.proxima_cobranca = hoje + timedelta(
                days=config.dias_ate_vencimento
            )
        assinatura.save()

        cliente.plano = plano
        cliente.save(update_fields=["plano", "updated_at"])

        if config.ativo:
            try:
                cls.sincronizar_no_gateway(assinatura)
            except Exception:
                # A assinatura local vale mesmo que o gateway falhe: o
                # cliente já pode usar o sistema no período de teste, e
                # `reconciliar_pendentes` recupera a criação depois.
                logger.exception(
                    "Assinatura %s criada localmente, mas sem espelho no gateway.",
                    assinatura.pk,
                )
        return assinatura

    @staticmethod
    def _valor_do_ciclo(plano, ciclo) -> Decimal:
        """
        Preço do ciclo a partir do mensal.

        Ciclos longos ganham desconto — é o incentivo padrão para
        antecipar receita e reduzir churn. Os fatores estão aqui, não
        espalhados na tela, para que mudá-los seja uma decisão só.
        """
        from apps.faturamento.models import Assinatura

        meses = {
            Assinatura.Ciclo.MENSAL: 1,
            Assinatura.Ciclo.TRIMESTRAL: 3,
            Assinatura.Ciclo.SEMESTRAL: 6,
            Assinatura.Ciclo.ANUAL: 12,
        }
        desconto = {
            Assinatura.Ciclo.MENSAL: Decimal("1.00"),
            Assinatura.Ciclo.TRIMESTRAL: Decimal("0.95"),
            Assinatura.Ciclo.SEMESTRAL: Decimal("0.90"),
            Assinatura.Ciclo.ANUAL: Decimal("0.83"),
        }
        base = Decimal(plano.preco_mensal or 0) * meses.get(ciclo, 1)
        return (base * desconto.get(ciclo, Decimal("1.00"))).quantize(Decimal("0.01"))

    # ══════════════════════════════════════════════════════════
    # Gateway
    # ══════════════════════════════════════════════════════════
    @classmethod
    def sincronizar_no_gateway(cls, assinatura):
        """Cria ou atualiza cliente e assinatura no ASAAS."""
        from apps.faturamento.asaas import ClienteAsaas

        gateway = ClienteAsaas.a_partir_da_configuracao()
        cliente = assinatura.cliente

        if not assinatura.asaas_customer_id:
            documento = apenas_digitos(cliente.cnpj)
            # Reaproveita o cadastro se o CNPJ já existir no ASAAS —
            # criar um segundo cliente para o mesmo documento espalha as
            # faturas em dois cadastros e confunde a cobrança.
            existente = gateway.buscar_cliente_por_cpf_cnpj(documento)
            if existente:
                assinatura.asaas_customer_id = existente["id"]
            else:
                criado = gateway.criar_cliente(
                    nome=cliente.razao_social,
                    cpf_cnpj=documento,
                    email=cliente.email_contato,
                    telefone=apenas_digitos(getattr(cliente, "telefone", "")),
                    referencia_externa=str(cliente.uuid),
                )
                assinatura.asaas_customer_id = criado["id"]
            assinatura.save(update_fields=["asaas_customer_id", "updated_at"])

        if assinatura.asaas_subscription_id:
            gateway.atualizar_assinatura(
                assinatura.asaas_subscription_id,
                value=assinatura.valor_total(),
                cycle=assinatura.ciclo,
            )
        else:
            criada = gateway.criar_assinatura(
                customer_id=assinatura.asaas_customer_id,
                valor=assinatura.valor_total(),
                ciclo=assinatura.ciclo,
                vencimento=assinatura.proxima_cobranca or timezone.localdate(),
                descricao=f"Kronus — plano {assinatura.plano.nome}",
                forma_pagamento=assinatura.forma_pagamento,
                referencia_externa=str(assinatura.cliente.uuid),
            )
            assinatura.asaas_subscription_id = criada["id"]
            assinatura.save(update_fields=["asaas_subscription_id", "updated_at"])

        cls.importar_cobrancas(assinatura)
        return assinatura

    @classmethod
    def importar_cobrancas(cls, assinatura) -> int:
        """Traz as faturas do gateway para o banco local."""
        from apps.faturamento.asaas import ClienteAsaas

        if not assinatura.asaas_subscription_id:
            return 0

        gateway = ClienteAsaas.a_partir_da_configuracao()
        importadas = 0
        for pagamento in gateway.cobrancas_da_assinatura(
            assinatura.asaas_subscription_id
        ):
            _, criada = cls.registrar_cobranca(assinatura, pagamento)
            importadas += int(criada)
        return importadas

    @staticmethod
    def registrar_cobranca(assinatura, pagamento: dict):
        """
        Grava ou atualiza uma cobrança a partir do payload do ASAAS.

        `update_or_create` pela chave externa: o mesmo pagamento chega
        várias vezes (criação, confirmação, recebimento) e cada chegada
        deve atualizar a mesma linha, nunca criar outra.
        """
        from apps.faturamento.models import Cobranca

        status = STATUS_ASAAS.get(pagamento.get("status"), "pendente")
        vencimento = pagamento.get("dueDate")

        defaults = {
            "assinatura": assinatura,
            "valor": Decimal(str(pagamento.get("value", 0))),
            "vencimento": vencimento,
            "status": status,
            "link_pagamento": pagamento.get("invoiceUrl") or "",
            "linha_digitavel": (pagamento.get("identificationField") or "")[:60],
            "url_nota": pagamento.get("transactionReceiptUrl") or "",
        }
        if status in Cobranca.STATUS_PAGOS:
            defaults["pago_em"] = timezone.now()

        return Cobranca.objects.update_or_create(
            identificador_externo=pagamento["id"], defaults=defaults
        )

    # ══════════════════════════════════════════════════════════
    # Mudanças de plano e cancelamento
    # ══════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def trocar_plano(cls, *, assinatura, plano, ciclo=None, colaboradores_extras=None):
        """
        Upgrade ou downgrade.

        **O downgrade é recusado se o cliente já usa mais do que o plano
        novo comporta.** Aceitar deixaria a conta acima do limite sem
        nenhum caminho automático de volta — e o efeito prático seria
        travar o cadastro de colaboradores sem explicar por quê.
        """
        from apps.rh.models import Colaborador

        em_uso = Colaborador.objects.filter(
            empresa__cliente=assinatura.cliente, ativo=True
        ).count()
        if plano.max_colaboradores and em_uso > plano.max_colaboradores:
            raise ValueError(
                f"O plano {plano.nome} permite {plano.max_colaboradores} "
                f"colaboradores e a conta tem {em_uso} ativos. "
                "Desative colaboradores antes de reduzir o plano."
            )

        empresas = assinatura.cliente.empresas.filter(ativo=True).count()
        if plano.max_empresas and empresas > plano.max_empresas:
            raise ValueError(
                f"O plano {plano.nome} permite {plano.max_empresas} empresa(s) "
                f"e a conta tem {empresas} ativa(s)."
            )

        assinatura.plano = plano
        if ciclo:
            assinatura.ciclo = ciclo
        if colaboradores_extras is not None:
            assinatura.colaboradores_contratados = colaboradores_extras
        assinatura.valor = cls._valor_do_ciclo(plano, assinatura.ciclo)
        assinatura.save()

        assinatura.cliente.plano = plano
        assinatura.cliente.save(update_fields=["plano", "updated_at"])

        from apps.faturamento.models import ConfiguracaoGateway

        if ConfiguracaoGateway.carregar().ativo and assinatura.asaas_subscription_id:
            try:
                cls.sincronizar_no_gateway(assinatura)
            except Exception:
                logger.exception(
                    "Plano trocado localmente, gateway nao atualizado (assinatura %s).",
                    assinatura.pk,
                )
        return assinatura

    @classmethod
    @transaction.atomic
    def cancelar(cls, *, assinatura, motivo=""):
        """
        Cancela a assinatura.

        **Não desativa o cliente.** Cancelar a cobrança e apagar o acesso
        são decisões distintas: a empresa continua obrigada a guardar os
        registros de ponto por cinco anos, e o cliente precisa poder
        emitir o AFD depois de sair. Quem suspende o acesso é o Master,
        de forma explícita.
        """
        from apps.faturamento.models import Assinatura, ConfiguracaoGateway

        if ConfiguracaoGateway.carregar().ativo and assinatura.asaas_subscription_id:
            try:
                from apps.faturamento.asaas import ClienteAsaas

                ClienteAsaas.a_partir_da_configuracao().cancelar_assinatura(
                    assinatura.asaas_subscription_id
                )
            except Exception:
                logger.exception(
                    "Falha ao cancelar no gateway a assinatura %s.", assinatura.pk
                )

        assinatura.status = Assinatura.Status.CANCELADA
        assinatura.cancelada_em = timezone.now()
        assinatura.motivo_cancelamento = motivo[:255]
        assinatura.proxima_cobranca = None
        assinatura.save()
        return assinatura

    # ══════════════════════════════════════════════════════════
    # Inadimplência
    # ══════════════════════════════════════════════════════════
    @classmethod
    def avaliar_inadimplencia(cls, assinatura) -> str:
        """
        Decide o estado da assinatura a partir das faturas.

        A tolerância existe porque boleto compensa em até três dias
        úteis: marcar inadimplente no dia seguinte ao vencimento
        suspenderia clientes que já pagaram.
        """
        from apps.faturamento.models import Assinatura, Cobranca, ConfiguracaoGateway

        if assinatura.status == Assinatura.Status.CANCELADA:
            return assinatura.status

        config = ConfiguracaoGateway.carregar()
        limite = timezone.localdate() - timedelta(
            days=config.dias_tolerancia_suspensao
        )

        vencidas = Cobranca.objects.filter(
            assinatura=assinatura,
            vencimento__lt=limite,
        ).exclude(status__in=list(Cobranca.STATUS_PAGOS) + ["cancelada"])

        if vencidas.exists():
            novo = Assinatura.Status.INADIMPLENTE
        elif assinatura.status == Assinatura.Status.TESTE and (
            assinatura.data_fim_teste
            and assinatura.data_fim_teste < timezone.localdate()
        ):
            # Teste terminou sem pagamento: volta a pendente, não a
            # inadimplente — ainda não houve fatura vencida de verdade.
            novo = Assinatura.Status.PENDENTE
        else:
            novo = Assinatura.Status.ATIVA

        if novo != assinatura.status:
            assinatura.status = novo
            assinatura.save(update_fields=["status", "updated_at"])
        return novo


class WebhookService:
    """Recebimento e processamento dos eventos do ASAAS."""

    @staticmethod
    def token_confere(token_recebido: str) -> bool:
        """
        Valida o `asaas-access-token`.

        Comparação em tempo constante: comparar com `==` vazaria o
        número de bytes corretos pelo tempo de execução, o que permite
        descobrir o token caractere a caractere.
        """
        import hmac

        from apps.faturamento.models import ConfiguracaoGateway

        esperado = ConfiguracaoGateway.carregar().webhook_token
        if not esperado:
            # Sem token configurado, qualquer um poderia confirmar
            # pagamentos. Recusar é o comportamento certo.
            return False
        return hmac.compare_digest(esperado, token_recebido or "")

    @classmethod
    @transaction.atomic
    def registrar(cls, payload: dict):
        """
        Grava o evento e o processa.

        O evento é persistido **antes** de ser processado: se o
        processamento falhar, o evento continua no banco para
        reprocessamento, em vez de sumir com um 500.
        """
        from apps.faturamento.models import EventoGateway

        identificador = payload.get("id") or payload.get("payment", {}).get("id", "")
        evento = payload.get("event", "")
        if not identificador:
            raise ValueError("Evento sem identificador.")

        registro, criado = EventoGateway.objects.get_or_create(
            identificador_externo=f"{evento}:{identificador}",
            defaults={"evento": evento, "payload": payload},
        )
        if not criado and registro.processado:
            # Reentrega: o ASAAS reenvia até receber 200. Reprocessar
            # marcaria a mesma fatura como paga duas vezes.
            return registro

        try:
            cls.processar(registro)
        except Exception as erro:
            registro.erro = str(erro)[:2000]
            registro.save(update_fields=["erro", "updated_at"])
            logger.exception("Falha ao processar evento %s do ASAAS.", evento)
            raise
        return registro

    @staticmethod
    def processar(registro):
        from apps.faturamento.models import Assinatura, Cobranca

        payload = registro.payload
        evento = registro.evento

        if evento not in EVENTOS_TRATADOS:
            registro.processado = True
            registro.processado_em = timezone.now()
            registro.save(update_fields=["processado", "processado_em", "updated_at"])
            return registro

        pagamento = payload.get("payment") or {}
        subscription_id = pagamento.get("subscription")

        assinatura = None
        if subscription_id:
            assinatura = Assinatura.objects.filter(
                asaas_subscription_id=subscription_id
            ).first()
        if assinatura is None:
            referencia = pagamento.get("externalReference")
            if referencia:
                assinatura = Assinatura.objects.filter(
                    cliente__uuid=referencia
                ).first()

        if assinatura is None:
            raise ValueError(
                f"Evento {evento} sem assinatura correspondente "
                f"(subscription={subscription_id!r})."
            )

        AssinaturaService.registrar_cobranca(assinatura, pagamento)
        AssinaturaService.avaliar_inadimplencia(assinatura)

        # Pagamento confirmado tira a conta da suspensao na hora — o
        # cliente acabou de pagar e nao pode ficar sem bater ponto
        # esperando a proxima varredura.
        if STATUS_ASAAS.get(pagamento.get("status")) in Cobranca.STATUS_PAGOS:
            cliente = assinatura.cliente
            if cliente.suspenso:
                cliente.suspenso = False
                cliente.save(update_fields=["suspenso", "updated_at"])

        registro.processado = True
        registro.processado_em = timezone.now()
        registro.erro = ""
        registro.save(
            update_fields=["processado", "processado_em", "erro", "updated_at"]
        )
        return registro
