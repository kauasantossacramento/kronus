"""
Kronus — o totem parado tem algo a dizer.

Uma tela ligada o dia inteiro mostrando so a logo e desperdicio de um
canal que a empresa ja tem. Mas encher de conteudo tem um custo: o que
importa na tela — como bater o ponto, a hora, a marca — nao pode ser
empurrado para fora por um enfeite.

Por isso o conteudo ambiente e **fundo**, e nunca substitui o que ja
esta la. O selo de toque, o relogio e as logos continuam por cima.

Tres periodos, com intencoes diferentes:

  manha  — saudacao e motivacao, para quem esta comecando
  tarde  — leve, sem cobranca; ninguem quer discurso as 15h
  noite  — descanso, tons escuros, frases curtas

Dicas de saude entram nos tres, misturadas: beber agua e alimentar-se
bem nao tem hora. Elas alternam com as saudacoes em vez de virarem uma
quarta categoria — uma tela que so da conselho de saude cansa.

**Sobre as imagens.** Este modulo guarda credito, fonte e licenca de
cada uma, e nao por burocracia: imagem de terceiro num totem comercial,
sem licenca conferida, e risco juridico do cliente que instalou o
equipamento. O campo `licenca` e obrigatorio de proposito — quem
adicionar precisa ter olhado.
"""
from django.db import models

from apps.core.models import BaseModel


class Periodo(models.TextChoices):
    """
    Os cortes seguem o dia de trabalho, nao o relogio astronomico.

    A madrugada entra em "noite" porque quem bate ponto as 3h esta no
    fim de um turno, e a tela que serve para ele e a mesma que serve
    para quem sai as 22h: escura, curta, sobre descanso.
    """

    MANHA = "manha", "Manhã"
    TARDE = "tarde", "Tarde"
    NOITE = "noite", "Noite e madrugada"


#: De que hora a que hora cada periodo vale.
#:
#: A noite e o resto: definir "das 18h as 5h" exigiria tratar a virada
#: da meia-noite como caso especial, e caso especial em regra de horario
#: e onde nasce o erro que so aparece as 23h59.
FAIXAS = {
    Periodo.MANHA: (5, 12),
    Periodo.TARDE: (12, 18),
}


def periodo_de(hora: int) -> str:
    """Qual periodo vale nesta hora."""
    for periodo, (inicio, fim) in FAIXAS.items():
        if inicio <= hora < fim:
            return periodo
    return Periodo.NOITE


class FraseAmbiente(BaseModel):
    """
    Uma frase da tela ociosa.

    Vive no banco, e nao no codigo, porque quem escreve bem uma
    saudacao nao e quem faz deploy — e trocar o tom de uma frase nao
    pode exigir uma versao nova do sistema.
    """

    class Tipo(models.TextChoices):
        SAUDACAO = "saudacao", "Saudação"
        MOTIVACAO = "motivacao", "Motivação"
        SAUDE = "saude", "Dica de saúde"
        DESCANSO = "descanso", "Descanso"

    periodo = models.CharField(
        "Período", max_length=10, choices=Periodo.choices, db_index=True
    )
    tipo = models.CharField(
        "Tipo", max_length=10, choices=Tipo.choices, default=Tipo.SAUDACAO
    )
    texto = models.CharField("Texto", max_length=200)
    #: Quem disse, quando nao foi o Kronus.
    #:
    #: Uma frase assinada carrega peso que uma anonima nao carrega — e a
    #: mesma ideia dita por Seneca ha dois mil anos le diferente de um
    #: aviso de mural. So autores em dominio publico: citar quem morreu
    #: ontem num produto comercial e problema de direito autoral, e o
    #: totem esta na parede do cliente.
    autor = models.CharField("Autor", max_length=80, blank=True)
    #: Frases longas nao cabem numa tela vista de longe e em pe.
    ativo = models.BooleanField("Ativa", default=True, db_index=True)

    class Meta:
        verbose_name = "Frase da tela ociosa"
        verbose_name_plural = "Frases da tela ociosa"
        ordering = ("periodo", "tipo", "texto")

    def __str__(self):
        return f"[{self.get_periodo_display()}] {self.texto[:50]}"


class ImagemAmbiente(BaseModel):
    """
    Uma imagem do acervo, com a licenca que permite usa-la.

    `licenca` e `fonte` sao obrigatorios porque a alternativa e o
    cliente descobrir o problema quando alguem reclamar — e o
    equipamento esta na parede dele, com a marca dele.
    """

    periodo = models.CharField(
        "Período", max_length=10, choices=Periodo.choices, db_index=True
    )
    imagem = models.ImageField("Imagem", upload_to="ambiente/")
    titulo = models.CharField("Título", max_length=120, blank=True)

    # -- procedencia -------------------------------------------
    autor = models.CharField("Autor", max_length=120, blank=True)
    #: Guardados mesmo quando a licenca dispensa credito na tela.
    #:
    #: O Pexels nao exige atribuicao, e por isso o totem nao mostra
    #: nada. Mas o registro fica: um ano depois, "de onde veio esta
    #: foto?" precisa ter resposta — e nao ter e o tipo de divida que so
    #: aparece quando alguem cobra.
    fonte = models.URLField(
        "Onde foi obtida", max_length=500, blank=True,
        help_text="Endereço da página de origem, para conferência.",
    )
    licenca = models.CharField(
        "Licença", max_length=80, blank=True,
        help_text="Ex.: Pexels License, CC0, Unsplash License.",
    )

    #: Identificador na origem, quando veio de uma API.
    #:
    #: Existe para nao baixar a mesma foto duas vezes: sem ele, cada
    #: atualizacao do acervo acrescentaria as mesmas imagens de novo, e
    #: em um mes o totem estaria repetindo a mesma paisagem seis vezes.
    id_externo = models.CharField(
        "ID na origem", max_length=40, blank=True, db_index=True
    )

    #: A imagem e clara o bastante para engolir uma logo branca?
    #:
    #: Medido uma vez, na entrada, e nao a cada quadro no tablet: a
    #: conta e a mesma, mas fazer no aparelho custaria a cada troca de
    #: slide, num equipamento que ja divide CPU com o reconhecimento.
    #:
    #: Guardado como booleano, e nao como o valor da luminancia: o totem
    #: nao tem o que fazer com 0,63 — ele so precisa saber se troca a
    #: cor da marca.
    clara = models.BooleanField(
        "Imagem clara", default=False,
        help_text="Quando marcada, o totem escurece a logo para não sumir.",
    )

    ativo = models.BooleanField("Ativa", default=True, db_index=True)
    ordem = models.PositiveSmallIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Imagem da tela ociosa"
        verbose_name_plural = "Imagens da tela ociosa"
        ordering = ("periodo", "ordem", "-created_at")

    def __str__(self):
        return self.titulo or f"{self.get_periodo_display()} #{self.pk}"

    @property
    def credito(self) -> str:
        """Como creditar na tela, quando a licenca pedir."""
        if self.autor:
            return f"{self.autor} · {self.licenca}"
        return self.licenca


class ImagemOcultaPelaEmpresa(BaseModel):
    """
    Uma imagem do acervo que esta empresa nao quer mostrar.

    Ocultar em vez de apagar: o acervo e do Kronus e serve a todos os
    clientes. Um cliente que nao gosta de uma foto nao pode tira-la dos
    outros — e tambem nao deve precisar pedir permissao para nao
    mostrar algo no proprio totem.
    """

    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="imagens_ambiente_ocultas",
        verbose_name="Empresa",
    )
    imagem = models.ForeignKey(
        ImagemAmbiente,
        on_delete=models.CASCADE,
        related_name="ocultada_por",
        verbose_name="Imagem",
    )

    class Meta:
        verbose_name = "Imagem oculta pela empresa"
        verbose_name_plural = "Imagens ocultas pela empresa"
        unique_together = ("empresa", "imagem")

    def __str__(self):
        return f"{self.empresa} oculta {self.imagem}"


#: Acima disto, a imagem e clara o bastante para apagar uma logo branca.
#:
#: Luminancia relativa media, de 0 a 1. Medido no topo da imagem, e nao
#: na foto inteira: e la que a marca fica, e uma paisagem de ceu claro
#: com terra escura embaixo tem media enganosa — a logo sumiria mesmo
#: com a media dando "escura".
LIMITE_DE_CLARIDADE = 0.58


def medir_claridade(dados: bytes) -> bool:
    """
    A parte de cima desta imagem apaga uma logo branca?

    Usa a formula de luminancia relativa (a mesma do WCAG), e nao a
    media dos canais: o olho enxerga verde muito mais que azul, e tratar
    os tres igual erra justamente em ceu e vegetacao — que e quase tudo
    o que ha no acervo.

    Na duvida devolve `False`: manter a logo branca e o comportamento de
    sempre, e errar para o lado do que ja funcionava e mais barato do
    que escurecer uma marca sobre foto escura.
    """
    try:
        import io

        from PIL import Image

        imagem = Image.open(io.BytesIO(dados)).convert("RGB")
        largura, altura = imagem.size
        # So a faixa de cima: e onde a marca fica.
        topo = imagem.crop((0, 0, largura, max(1, altura // 3)))
        # Reduzir antes de somar: a media de 3 milhoes de pixels e a
        # mesma da versao pequena, e custa muito menos.
        topo = topo.resize((32, 32))

        total = 0.0
        for r, g, b in topo.getdata():
            total += (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        return (total / 1024) > LIMITE_DE_CLARIDADE
    except Exception:
        return False
