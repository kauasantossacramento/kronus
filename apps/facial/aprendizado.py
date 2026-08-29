"""
Kronus — o cadastro aprende com as batidas do dia a dia.

O problema que isto resolve. O cadastro e feito uma vez, em cinco poses,
num minuto. O reconhecimento acontece todos os dias, o ano inteiro, com
outra luz, outro cabelo, oculos novo, barba que cresceu. Quanto mais o
tempo passa, mais longe a pessoa fica da propria referencia — e o totem
comeca a pedir CPF de quem sempre foi reconhecido.

A ideia. Toda batida bem-sucedida e uma foto da pessoa, tirada pela
camera que vai reconhece-la amanha, na luz em que ela costuma chegar.
Aproveitar as melhores dessas fotos mantem o cadastro atual sozinho.

Por que isso e perigoso, e o que impede o estrago. Aprender com o proprio
resultado e realimentacao: se uma identificacao errada virar referencia,
o erro deixa de ser um episodio e passa a ser o cadastro. A partir dali o
sistema estaria cada vez mais convencido da pessoa errada.

As travas, em ordem de importancia:

  1. So aprende com folga larga. Nao basta ter passado no limiar — a
     distancia precisa estar na metade de baixo dele. Um acerto no fio
     nao vira referencia.
  2. So aprende do segundo colocado bem longe. Se outro cadastro estava
     perto, a identificacao pode estar certa por sorte, e sorte nao se
     grava.
  3. Nunca aprende uma amostra que se pareca com outra pessoa. E a mesma
     regra que ja limpa a galeria, aplicada antes de deixar entrar.
  4. Nunca substitui o cadastro original inteiro. As capturas do
     cadastro sao supervisionadas — alguem viu quem estava na frente da
     camera. As aprendidas nao. O limite de aprendidas mantem sempre a
     maioria supervisionada.
"""
import logging

from django.conf import settings

logger = logging.getLogger("kronus.facial")

#: Fracao do limiar abaixo da qual a identificacao e "folgada".
#:
#: Com limiar 0,52, aprende so abaixo de 0,26 — a faixa onde as
#: identificacoes legitimas medidas em producao se concentram (0,08 a
#: 0,29). Um acerto a 0,45 passa no limiar e nao vira referencia.
FRACAO_PARA_APRENDER = 0.5

#: Folga minima ate o segundo colocado.
#:
#: Maior que a margem do reconhecimento: para registrar o ponto basta
#: nao haver duvida; para virar referencia permanente, e preciso nao ter
#: havido nem sombra de duvida.
MARGEM_PARA_APRENDER = 0.20

#: Quantas amostras aprendidas um cadastro pode ter.
#:
#: O cadastro guarda cinco. Duas aprendidas deixam tres supervisionadas —
#: a maioria continua sendo o que alguem conferiu.
MAXIMO_APRENDIDAS = 2

#: Intervalo minimo entre dois aprendizados do mesmo colaborador.
#:
#: Sem ele, cinco batidas de uma manha encheriam a cota com fotos quase
#: identicas, e o cadastro ficaria mais estreito em vez de mais largo.
DIAS_ENTRE_APRENDIZADOS = 7


def pode_aprender(resultado, threshold: float) -> bool:
    """
    A identificacao foi boa o bastante para virar referencia?

    Recebe o `ResultadoReconhecimento` ja decidido. Nao refaz a decisao:
    pergunta se ela foi folgada.
    """
    if not resultado.identificado or resultado.distancia is None:
        return False

    if resultado.distancia > threshold * FRACAO_PARA_APRENDER:
        return False

    # `segunda_distancia` so existe quando ha outro cadastro na empresa.
    # Sozinho na galeria, nao ha segundo colocado de quem se afastar.
    segunda = getattr(resultado, "segunda_distancia", None)
    if segunda is not None and (segunda - resultado.distancia) < MARGEM_PARA_APRENDER:
        return False

    return True


def registrar_aprendizado(servico, colaborador, imagem_bytes, resultado) -> bool:
    """
    Guarda o quadro como mais uma referencia do colaborador.

    Devolve `True` quando aprendeu. Nunca levanta: o aprendizado e um
    ganho, e derrubar o registro de ponto por causa dele seria trocar o
    essencial pelo acessorio.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.facial.models import FaceRegistro

    try:
        if not colaborador.empresa.aprendizado_facial:
            return False
        if not pode_aprender(resultado, servico.threshold):
            return False

        aprendidas = FaceRegistro.objects.filter(
            colaborador=colaborador, ativo=True, aprendida=True
        )
        if aprendidas.count() >= MAXIMO_APRENDIDAS:
            # A cota esta cheia: a mais antiga sai para a nova entrar.
            # Assim o cadastro acompanha a pessoa em vez de acumular.
            mais_antiga = aprendidas.order_by("created_at").first()
            if mais_antiga:
                limite = timezone.now() - timedelta(days=DIAS_ENTRE_APRENDIZADOS)
                if mais_antiga.created_at > limite:
                    return False

        recente = aprendidas.order_by("-created_at").first()
        if recente:
            limite = timezone.now() - timedelta(days=DIAS_ENTRE_APRENDIZADOS)
            if recente.created_at > limite:
                return False

        # `cadastrar_amostra` traz as travas que ja existem: recusa a
        # captura que e de outra pessoa e aposenta o excedente. Reusar
        # em vez de gravar direto evita que o caminho automatico seja
        # mais permissivo que o manual.
        registro = servico.cadastrar_amostra(
            colaborador,
            imagem_bytes,
            angulo="frontal",
            exigir_qualidade=True,
        )
        registro.aprendida = True
        registro.save(update_fields=["aprendida", "updated_at"])

        if aprendidas.count() > MAXIMO_APRENDIDAS - 1:
            for velha in aprendidas.order_by("created_at")[
                : aprendidas.count() - (MAXIMO_APRENDIDAS - 1)
            ]:
                velha.ativo = False
                velha.save(update_fields=["ativo", "updated_at"])

        servico.consolidar_cadastro(colaborador)
        logger.info(
            "Cadastro facial aprendeu com uma batida: colaborador=%s dist=%.3f",
            colaborador.pk,
            resultado.distancia,
        )
        return True
    except Exception:
        logger.exception("Falha ao aprender com a batida — ignorada.")
        return False
