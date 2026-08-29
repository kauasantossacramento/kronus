"""
Kronus — assinaturas, cobranças e integração com o gateway (ASAAS).

Três objetos sustentam a operação comercial:

    ConfiguracaoGateway   credenciais e ambiente, editáveis pelo Master
    Assinatura            o vínculo Cliente ↔ Plano, com ciclo e valor
    Cobranca              cada fatura emitida, com o estado no gateway

**Por que a chave do gateway fica no banco, e não no `.env`.** O Master
precisa trocar a credencial e alternar entre sandbox e produção sem
depender de um deploy. O custo dessa escolha é que a chave passa a viver
no banco: por isso ela nunca é reexibida na tela depois de salva (só o
prefixo), e o acesso à tela é restrito ao Master.

**O estado de pagamento é sempre do gateway, nunca nosso.** O Kronus não
decide que uma fatura foi paga: ele registra o que o ASAAS informou, com
o id do evento que o disse. Se a nossa cópia divergir, a verdade é a
deles — e `EventoGateway` guarda a trilha para reconciliar.
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class ConfiguracaoGateway(BaseModel):
    """
    Credenciais do gateway. **Registro único** (singleton).

    O `pk=1` é forçado no `save()`: dois conjuntos de credenciais ativos
    ao mesmo tempo produziriam cobranças em contas diferentes conforme a
    ordem de leitura, e o cliente veria faturas sumindo.
    """

    class Ambiente(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox (testes)"
        PRODUCAO = "producao", "Produção"

    ambiente = models.CharField(
        "Ambiente", max_length=10,
        choices=Ambiente.choices, default=Ambiente.SANDBOX,
        help_text="Sandbox não move dinheiro real. Troque para Produção só depois de testar.",
    )
    api_key = models.CharField(
        "Chave de API do ASAAS", max_length=255, blank=True,
        help_text="Gerada no painel do ASAAS em Integrações › Chave de API.",
    )
    webhook_token = models.CharField(
        "Token do webhook", max_length=255, blank=True,
        help_text=(
            "Enviado pelo ASAAS no header 'asaas-access-token'. Entre 32 e 255 "
            "caracteres. Sem ele, qualquer um pode forjar uma confirmação de pagamento."
        ),
    )
    ativo = models.BooleanField(
        "Cobrança automática ativa", default=False,
        help_text="Desligado, o sistema não cria nem consulta cobranças no gateway.",
    )

    dias_ate_vencimento = models.PositiveSmallIntegerField(
        "Dias até o primeiro vencimento", default=7
    )
    # -- custos por transacao ----------------------------------
    #
    # A tabela do ASAAS muda, e varia por conta negociada. Numero fixo no
    # codigo vira margem errada em silencio — o relatorio continua
    # somando, so que errado, e ninguem percebe ate fechar o mes.
    custo_pix = models.DecimalField(
        "Custo por Pix recebido (R$)", max_digits=6, decimal_places=2, default=0
    )
    custo_boleto = models.DecimalField(
        "Custo por boleto compensado (R$)", max_digits=6, decimal_places=2, default=0
    )
    custo_cartao_percentual = models.DecimalField(
        "Taxa do cartão (%)", max_digits=5, decimal_places=2, default=0
    )
    custo_cartao_fixo = models.DecimalField(
        "Custo fixo por transação no cartão (R$)",
        max_digits=6, decimal_places=2, default=0,
    )
    custo_nota_fiscal = models.DecimalField(
        "Custo por nota fiscal (R$)", max_digits=6, decimal_places=2, default=0
    )
    custo_mensal_fixo = models.DecimalField(
        "Custo fixo mensal da operação (R$)",
        max_digits=10, decimal_places=2, default=0,
        help_text="VPS, domínio, e-mail — rateado no relatório de margem.",
    )

    emitir_nota_fiscal = models.BooleanField(
        "Emitir nota fiscal automaticamente",
        default=False,
        help_text=(
            "Emite NFS-e pelo ASAAS quando a fatura é paga. Custa R$ 0,49 por "
            "documento, além da taxa da cobrança. Exige a inscrição municipal "
            "configurada no painel do ASAAS."
        ),
    )
    nota_fiscal_descricao = models.CharField(
        "Descrição do serviço na nota",
        max_length=255,
        blank=True,
        default="Licença de uso de software de ponto eletrônico",
    )

    dias_tolerancia_suspensao = models.PositiveSmallIntegerField(
        "Dias de tolerância após o vencimento", default=5,
        help_text=(
            "Uma fatura vencida não suspende a conta imediatamente: boleto "
            "leva até 3 dias úteis para compensar, e suspender antes disso "
            "tira o ponto de quem já pagou."
        ),
    )

    class Meta:
        verbose_name = "Configuração do gateway"
        verbose_name_plural = "Configuração do gateway"

    def __str__(self):
        return f"ASAAS ({self.get_ambiente_display()})"

    def save(self, *args, **kwargs):
        # Forcar `pk=1` nao basta: o Django decide INSERT ou UPDATE pelo
        # estado do objeto, e um objeto novo com pk=1 tentaria INSERT
        # sobre a linha existente. Marcar como "ja persistido" quando a
        # linha existe faz o save virar UPDATE, que e o que um singleton
        # precisa.
        self.pk = 1
        if self._state.adding:
            existente = (
                type(self).objects.filter(pk=1).values("created_at").first()
            )
            if existente:
                # Vira UPDATE. `created_at` precisa ser copiado da linha
                # existente: `auto_now_add` so preenche em INSERT, e sem
                # isso o UPDATE gravaria NULL sobre a data de criacao.
                self._state.adding = False
                self.created_at = existente["created_at"]
                kwargs.pop("force_insert", None)
        super().save(*args, **kwargs)

    @classmethod
    def carregar(cls) -> "ConfiguracaoGateway":
        objeto, _ = cls.objects.get_or_create(pk=1)
        return objeto

    @property
    def configurado(self) -> bool:
        return bool(self.api_key and self.webhook_token)

    @property
    def api_key_mascarada(self) -> str:
        """
        O que a tela mostra depois de salva.

        Exibir a chave inteira num painel web a expõe a quem olhar a
        tela, ao histórico do navegador e a qualquer captura. O prefixo
        basta para conferir *qual* chave está configurada.
        """
        if not self.api_key:
            return ""
        return f"{self.api_key[:12]}{'•' * 20}{self.api_key[-4:]}"

    @property
    def url_base(self) -> str:
        if self.ambiente == self.Ambiente.PRODUCAO:
            return "https://api.asaas.com/v3"
        return "https://api-sandbox.asaas.com/v3"


class Assinatura(BaseModel):
    """
    O vínculo comercial entre um Cliente e um Plano.

    Guardamos `valor` em vez de sempre ler `plano.preco_mensal`: um
    reajuste de tabela não pode alterar retroativamente o que um cliente
    já contratado paga. O preço vigente é o que está aqui.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Aguardando primeiro pagamento"
        ATIVA = "ativa", "Ativa"
        INADIMPLENTE = "inadimplente", "Inadimplente"
        CANCELADA = "cancelada", "Cancelada"
        TESTE = "teste", "Período de teste"

    class Ciclo(models.TextChoices):
        MENSAL = "MONTHLY", "Mensal"
        TRIMESTRAL = "QUARTERLY", "Trimestral"
        SEMESTRAL = "SEMIANNUALLY", "Semestral"
        ANUAL = "YEARLY", "Anual"

    class FormaPagamento(models.TextChoices):
        INDEFINIDO = "UNDEFINED", "Cliente escolhe na hora"
        BOLETO = "BOLETO", "Boleto"
        PIX = "PIX", "Pix"
        CARTAO = "CREDIT_CARD", "Cartão de crédito"

    cliente = models.OneToOneField(
        "clientes.Cliente",
        on_delete=models.CASCADE,
        related_name="assinatura",
        verbose_name="Cliente",
    )
    plano = models.ForeignKey(
        "master.Plano",
        on_delete=models.PROTECT,
        related_name="assinaturas",
        verbose_name="Plano",
    )
    status = models.CharField(
        "Status", max_length=15, choices=Status.choices,
        default=Status.PENDENTE, db_index=True,
    )
    ciclo = models.CharField(
        "Ciclo", max_length=15, choices=Ciclo.choices, default=Ciclo.MENSAL
    )
    forma_pagamento = models.CharField(
        "Forma de pagamento", max_length=15,
        choices=FormaPagamento.choices, default=FormaPagamento.INDEFINIDO,
    )

    valor = models.DecimalField("Valor do ciclo (R$)", max_digits=10, decimal_places=2)
    colaboradores_contratados = models.PositiveIntegerField(
        "Colaboradores contratados", default=0,
        help_text="Acima do incluso no plano, cobrados por `preco_por_colaborador`.",
    )
    totens_contratados = models.PositiveIntegerField(
        "Totens adicionais", default=0,
        help_text="Acima do incluído no plano, cobrados por `preco_por_totem`.",
    )

    data_inicio = models.DateField("Início", default=timezone.localdate)
    data_fim_teste = models.DateField("Fim do período de teste", null=True, blank=True)
    proxima_cobranca = models.DateField("Próxima cobrança", null=True, blank=True)
    # -- Desconto comercial ------------------------------------
    #
    # Concedido pelo master, e nao pelo cliente. Fica na assinatura
    # porque e o contrato: muda com a renegociacao, e nao com o cadastro
    # da empresa.
    desconto_percentual = models.DecimalField(
        "Desconto (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Sobre o total do ciclo, adicionais inclusos.",
    )
    desconto_valor = models.DecimalField(
        "Desconto fixo (R$)",
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Somado ao percentual, quando houver os dois.",
    )
    desconto_motivo = models.CharField(
        "Motivo do desconto", max_length=200, blank=True,
        help_text=(
            "Por que foi concedido. Quem for renovar daqui a um ano "
            "precisa saber se o desconto era permanente ou de campanha."
        ),
    )
    desconto_ate = models.DateField(
        "Desconto válido até", null=True, blank=True,
        help_text="Em branco, vale enquanto a assinatura durar.",
    )

    cancelada_em = models.DateTimeField("Cancelada em", null=True, blank=True)
    motivo_cancelamento = models.CharField("Motivo", max_length=255, blank=True)

    # -- espelho do gateway ------------------------------------
    asaas_customer_id = models.CharField(
        "ID do cliente no ASAAS", max_length=60, blank=True, db_index=True
    )
    asaas_subscription_id = models.CharField(
        "ID da assinatura no ASAAS", max_length=60, blank=True, db_index=True
    )

    class Meta:
        verbose_name = "Assinatura"
        verbose_name_plural = "Assinaturas"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "proxima_cobranca"])]

    def __str__(self):
        return f"{self.cliente} — {self.plano} ({self.get_status_display()})"

    @property
    def em_dia(self) -> bool:
        return self.status in (self.Status.ATIVA, self.Status.TESTE)

    @property
    def dias_de_teste_restantes(self) -> int | None:
        if self.status != self.Status.TESTE or not self.data_fim_teste:
            return None
        return max(0, (self.data_fim_teste - timezone.localdate()).days)

    def valor_total(self):
        """
        O que o cliente paga: ciclo mais adicionais, menos o desconto.

        O desconto entra por ultimo, sobre a soma. Aplicar so no plano e
        deixar os adicionais cheios daria um numero que nem o comercial
        nem o cliente reconhecem como o combinado.
        """
        bruto = self.valor + self.valor_dos_adicionais()
        return max(bruto - self.desconto_aplicado(bruto), Decimal("0.00"))

    def desconto_aplicado(self, bruto=None):
        """
        Quanto o desconto tira deste ciclo.

        Percentual e valor fixo somam: um acordo pode ser "10% e mais R$
        50 nos tres primeiros meses", e obrigar a escolher um so faria
        alguem converter na mao e errar.

        Vencido, nao desconta nada — mas continua gravado, porque a
        pergunta "por que o valor mudou?" precisa de resposta.
        """
        if self.desconto_ate and self.desconto_ate < timezone.localdate():
            return Decimal("0.00")

        if bruto is None:
            bruto = self.valor + self.valor_dos_adicionais()

        de_percentual = bruto * (self.desconto_percentual or 0) / Decimal("100")
        total = de_percentual + (self.desconto_valor or 0)
        return min(total.quantize(Decimal("0.01")), bruto)

    @property
    def tem_desconto(self) -> bool:
        return bool(self.desconto_percentual or self.desconto_valor)

    def valor_dos_adicionais(self):
        """
        Quanto os adicionais somam ao ciclo.

        Separado de `valor_total` para que a fatura e a tela do cliente
        possam mostrar a composicao: "plano X + 2 totens" e uma linha que
        o cliente confere; um total fechado, nao.
        """
        colaboradores = (
            self.plano.preco_por_colaborador or 0
        ) * self.colaboradores_contratados
        totens = (self.plano.preco_por_totem or 0) * self.totens_contratados
        return colaboradores + totens

    @property
    def totens_permitidos(self) -> int:
        """Incluidos no plano mais os contratados a parte."""
        return (self.plano.max_totems or 0) + self.totens_contratados


class Cobranca(BaseModel):
    """
    Uma fatura. Espelho local do `payment` do ASAAS.

    `identificador_externo` é único: o webhook do ASAAS pode chegar mais
    de uma vez para o mesmo pagamento (é assim que eles garantem
    entrega), e sem essa restrição a mesma fatura viraria duas.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Aguardando pagamento"
        CONFIRMADA = "confirmada", "Confirmada"
        RECEBIDA = "recebida", "Recebida"
        VENCIDA = "vencida", "Vencida"
        ESTORNADA = "estornada", "Estornada"
        CANCELADA = "cancelada", "Cancelada"

    #: Estados do ASAAS que representam dinheiro efetivamente disponível.
    STATUS_PAGOS = {"confirmada", "recebida"}

    assinatura = models.ForeignKey(
        Assinatura,
        on_delete=models.CASCADE,
        related_name="cobrancas",
        verbose_name="Assinatura",
    )
    valor = models.DecimalField("Valor (R$)", max_digits=10, decimal_places=2)
    vencimento = models.DateField("Vencimento", db_index=True)
    status = models.CharField(
        "Status", max_length=12, choices=Status.choices,
        default=Status.PENDENTE, db_index=True,
    )
    pago_em = models.DateTimeField("Pago em", null=True, blank=True)

    identificador_externo = models.CharField(
        "ID no ASAAS", max_length=60, unique=True, db_index=True
    )
    link_pagamento = models.URLField("Link de pagamento", max_length=500, blank=True)
    linha_digitavel = models.CharField("Linha digitável", max_length=60, blank=True)
    pix_copia_cola = models.TextField("Pix copia e cola", blank=True)
    url_nota = models.URLField("Nota fiscal", max_length=500, blank=True)

    class Meta:
        verbose_name = "Cobrança"
        verbose_name_plural = "Cobranças"
        ordering = ("-vencimento",)
        indexes = [models.Index(fields=["assinatura", "-vencimento"])]

    def __str__(self):
        return f"{self.assinatura.cliente} — R$ {self.valor} em {self.vencimento:%d/%m/%Y}"

    @property
    def paga(self) -> bool:
        return self.status in self.STATUS_PAGOS

    @property
    def dias_de_atraso(self) -> int:
        if self.paga or self.status == self.Status.CANCELADA:
            return 0
        return max(0, (timezone.localdate() - self.vencimento).days)


class EventoGateway(BaseModel):
    """
    Toda notificação recebida do gateway, crua.

    Guardar o payload original é o que permite reconciliar quando o
    cliente diz que pagou e o sistema diz que não: dá para reprocessar o
    evento e ver exatamente o que o ASAAS informou e quando.

    `identificador_externo` deduplica — o ASAAS reenvia até receber 200.
    """

    identificador_externo = models.CharField(
        "ID do evento", max_length=100, unique=True, db_index=True
    )
    evento = models.CharField("Evento", max_length=60, db_index=True)
    payload = models.JSONField("Payload recebido", default=dict)
    processado = models.BooleanField("Processado", default=False, db_index=True)
    processado_em = models.DateTimeField("Processado em", null=True, blank=True)
    erro = models.TextField("Erro no processamento", blank=True)

    class Meta:
        verbose_name = "Evento do gateway"
        verbose_name_plural = "Eventos do gateway"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.evento} — {self.identificador_externo}"


def custo_da_cobranca(cobranca, config=None):
    """
    Quanto a KS TEC paga para receber esta cobranca.

    Fica fora do modelo `Cobranca` de proposito: o custo depende da
    tabela vigente, que muda, e congelar o valor no registro faria o
    historico mentir quando a tabela fosse atualizada. Recalcular a cada
    leitura mantem o relatorio coerente com o que se paga hoje.
    """
    from decimal import Decimal

    config = config or ConfiguracaoGateway.carregar()
    forma = (cobranca.assinatura.forma_pagamento or "").upper()

    if forma == "PIX":
        custo = config.custo_pix
    elif forma == "BOLETO":
        custo = config.custo_boleto
    elif forma in ("CREDIT_CARD", "CARTAO"):
        custo = (
            cobranca.valor * config.custo_cartao_percentual / Decimal("100")
            + config.custo_cartao_fixo
        )
    else:
        # Forma indefinida: o cliente escolhe na hora de pagar. Assumir o
        # mais barato subestimaria o custo; assumir o mais caro assustaria
        # sem motivo. O boleto e o caso mais comum na base.
        custo = config.custo_boleto

    if cobranca.url_nota:
        custo += config.custo_nota_fiscal
    return custo
