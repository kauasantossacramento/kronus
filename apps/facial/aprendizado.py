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
#: A galeria guarda sete: cinco poses do cadastro supervisionado e tres
#: lugares para aprendidas. A maioria continua sendo o que alguem
#: conferiu, com a pessoa na frente da camera.
MAXIMO_APRENDIDAS = 3

#: Quanto a foto precisa ser DIFERENTE das que ja existem.
#:
#: Esta e a regra que decide, e nao o calendario. Guardar uma foto quase
#: igual a uma que ja esta la nao acrescenta nada: gasta um lugar da
#: cota e deixa o cadastro mais estreito, nao mais largo. O que faz o
#: reconhecimento melhorar e cobrir condicao nova — outra luz, outro
#: angulo, o cabelo de hoje.
#:
#: 0,18 e a faixa em que a foto ainda e claramente a mesma pessoa (as
#: poses do cadastro ficam entre 0,05 e 0,48 entre si) e ja traz
#: informacao que as outras nao tinham.
NOVIDADE_MINIMA = 0.18

#: Teto diario, so para nao aprender em rajada.
#:
#: Era uma por semana, e a pergunta e justa: uma por semana leva quase um
#: mes para preencher tres lugares. O que precisava de limite nao era a
#: frequencia — era a repeticao, e disso cuida a regra de novidade. Um
#: por dia sobra para o proposito e ainda impede que cinco batidas de uma
#: manha ocupem a cota inteira.
DIAS_ENTRE_APRENDIZADOS = 1


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

        if not _traz_algo_novo(servico, colaborador, imagem_bytes):
            return False

        # A trava que faltava. Ver `_nao_aproxima_de_outro`.
        if not _nao_aproxima_de_outro(servico, colaborador, imagem_bytes):
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

        excedente = aprendidas.count() - (MAXIMO_APRENDIDAS - 1)
        if excedente > 0:
            for velha in _piores_aprendidas(servico, colaborador, aprendidas, excedente):
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


def _traz_algo_novo(servico, colaborador, imagem_bytes) -> bool:
    """
    A foto acrescenta alguma coisa ao que ja esta gravado?

    Uma captura quase igual a uma existente ocupa um lugar da cota e nao
    melhora nada — o cadastro fica mais estreito, e nao mais largo. O que
    faz o reconhecimento melhorar e cobrir condicao que ainda nao estava
    coberta.

    Na duvida, aprende. Falha aqui (motor fora do ar, imagem que nao
    volta) nao pode virar motivo para nunca mais aprender: o risco de
    guardar uma foto redundante e menor do que o de o cadastro parar no
    tempo.
    """
    try:
        vetor = servico.provedor.gerar_embedding(imagem_bytes)
        atuais = servico.candidatos([colaborador.empresa]).get(colaborador.pk) or []
        if not atuais:
            return True
        perto = min(servico._distancia(vetor, v) for v in atuais)
        return perto >= NOVIDADE_MINIMA
    except Exception:
        logger.info("Nao foi possivel medir a novidade da captura; aprendendo.")
        return True


#: Quanto a amostra aprendida pode encostar em outra pessoa.
#:
#: Uma amostra que fica a menos disto de outro cadastro nao entra, mesmo
#: sendo do titular. Nao e o mesmo que o limiar do reconhecimento: ali
#: se decide uma batida, que erra e se corrige na proxima; aqui se
#: decide uma referencia permanente, que erra e passa a errar sempre.
DISTANCIA_MINIMA_DE_OUTROS = 0.45


def _nao_aproxima_de_outro(servico, colaborador, imagem_bytes) -> bool:
    """
    A foto aprendida encosta em outra pessoa?

    Existe pelo caso das irmas Alves dos Santos: Elisangela e Edjane
    ficam a 0,2630 uma da outra no cadastro supervisionado. Sem esta
    trava, bastava uma batida em que a semelhanca ajudasse para o rosto
    de uma entrar na galeria da outra — e ali ficar.

    O estrago do aprendizado errado nao e uma batida errada: e um
    cadastro que passa a aceitar duas pessoas para sempre, sem que
    ninguem tenha conferido. Por isso a exigencia aqui e mais dura que a
    do reconhecimento, e a duvida pesa contra aprender.

    Duas perguntas, e as duas precisam passar:
      1. a foto esta longe o bastante das OUTRAS pessoas?
      2. ela nao aproxima o titular de quem ele ja e mais parecido?

    Falhar em medir **impede** o aprendizado, ao contrario de
    `_traz_algo_novo`, onde a duvida libera. La o risco e guardar uma
    foto redundante; aqui e contaminar um cadastro.
    """
    try:
        vetor = servico.provedor.gerar_embedding(imagem_bytes)
        galeria = servico.candidatos([colaborador.empresa])

        outros = {
            pk: vs for pk, vs in galeria.items()
            if pk != colaborador.pk and vs
        }
        if not outros:
            return True  # sozinho na empresa: nao ha de quem se confundir

        perto_de_outro = min(
            servico._distancia(vetor, v) for vs in outros.values() for v in vs
        )
        if perto_de_outro < DISTANCIA_MINIMA_DE_OUTROS:
            logger.info(
                "Nao aprendeu: a captura fica a %.3f de outro cadastro "
                "(minimo %.2f). colaborador=%s",
                perto_de_outro, DISTANCIA_MINIMA_DE_OUTROS, colaborador.pk,
            )
            return False

        # Ja existe alguem perto do titular? Entao a amostra nova nao
        # pode estreitar essa distancia — seria empurrar os dois
        # cadastros um para o outro, que e como a confusao se instala.
        atuais = galeria.get(colaborador.pk) or []
        if atuais:
            antes = min(
                servico._distancia(a, b)
                for a in atuais
                for vs in outros.values() for b in vs
            )
            if perto_de_outro < antes:
                logger.info(
                    "Nao aprendeu: aproximaria %s de outro cadastro "
                    "(%.3f -> %.3f).", colaborador.pk, antes, perto_de_outro,
                )
                return False
        return True
    except Exception:
        # Ao contrario de `_traz_algo_novo`, aqui a duvida bloqueia.
        logger.info("Nao foi possivel conferir a vizinhanca; nao aprendeu.")
        return False


def _piores_aprendidas(servico, colaborador, aprendidas, quantas: int) -> list:
    """
    Quais amostras aprendidas sair, quando a cota enche.

    Antes saia a mais antiga. Idade e um criterio pobre: a amostra mais
    velha pode ser a melhor que a pessoa tem, e a mais nova pode ser a
    que a aproxima de um sosia. Trocar por idade mantem o cadastro
    recente e nao o mantem **bom**.

    Agora sai a que mais encosta em outra pessoa. Assim cada aprendizado
    deixa a galeria um pouco mais separada do resto — o cadastro melhora
    com o uso em vez de so acompanhar o tempo. E o que faz diferenca
    justamente em quem tem um parecido na empresa.

    Empate, ou impossibilidade de medir, volta ao criterio antigo: a
    mais antiga sai. Um criterio pior e melhor que nenhum.
    """
    try:
        galeria = servico.candidatos([colaborador.empresa])
        outros = [
            v for pk, vs in galeria.items() if pk != colaborador.pk for v in vs
        ]
        if not outros:
            return list(aprendidas.order_by("created_at")[:quantas])

        def encosta_quanto(registro):
            vetor = registro.obter_embedding()
            if vetor is None:
                # Sem vetor nao ha o que defender: sai primeiro.
                return -1.0
            return min(servico._distancia(vetor, o) for o in outros)

        # Menor distancia a outra pessoa = pior amostra.
        ordenadas = sorted(aprendidas, key=encosta_quanto)
        piores = ordenadas[:quantas]
        for r in piores:
            logger.info(
                "Aposentando a amostra aprendida %s: era a mais proxima de "
                "outro cadastro.", r.pk,
            )
        return piores
    except Exception:
        logger.exception("Falha ao escolher a amostra a aposentar; usando a idade.")
        return list(aprendidas.order_by("created_at")[:quantas])


# ══════════════════════════════════════════════════════════════
# Quanto custa reconhecer cada pessoa
# ══════════════════════════════════════════════════════════════
#
# Medicao pura: nada aqui altera o que e aprendido. Serve para apontar
# quem precisa de reforco biometrico — capturas a mais, feitas com
# alguem olhando, e nao afrouxamento da regra automatica.
#
# A tentacao era baixar o piso do aprendizado para as irmas Alves dos
# Santos conseguirem aprender. Medido contra a galeria real, com a
# galeria evoluindo a cada amostra como acontece em producao: a regra
# frouxa aprendia 22 amostras no lugar de 30 e criava 5 pares novos na
# faixa de duvida — e as irmas continuavam sem aprender. O piso fica
# onde esta; quem precisa de mais foto recebe foto.

TENTATIVAS_QUE_INCOMODAM = 2.5

#: Quantas batidas a pessoa precisa ter para a medida valer.
#:
#: Com uma ou duas, a media e a propria batida. Preferir "ainda nao da
#: para saber" a apontar alguem para recadastro por causa de um quadro
#: tremido.
BATIDAS_PARA_MEDIR = 3


def dificuldade_de(colaborador, *, dias: int = 7) -> dict:
    """
    Quanto custa reconhecer esta pessoa, em tentativas por batida.

    Serve a duas coisas: apontar quem precisa de reforco biometrico, e
    permitir que o aprendizado seja mais atento a quem esta penando —
    quem e reconhecido de primeira nao precisa de amostra nova.

    Devolve `situacao`:
      sem_dados  — poucas batidas para dizer qualquer coisa
      tranquilo  — dentro do padrao
      dificil    — repete mais que o resto
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.facial.repeticao import medir

    desde = timezone.now() - timedelta(days=dias)
    dados = medir(empresa=colaborador.empresa, desde=desde)

    minha = next(
        (
            linha for linha in dados["por_pessoa"]
            if linha["colaborador"].pk == colaborador.pk
        ),
        None,
    )
    if minha is None or minha["batidas"] < BATIDAS_PARA_MEDIR:
        return {
            "situacao": "sem_dados",
            "media": minha["media"] if minha else None,
            "batidas": minha["batidas"] if minha else 0,
            "pior": minha["pior"] if minha else None,
        }

    dificil = minha["media"] >= TENTATIVAS_QUE_INCOMODAM
    return {
        "situacao": "dificil" if dificil else "tranquilo",
        "media": minha["media"],
        "batidas": minha["batidas"],
        "pior": minha["pior"],
    }


def quem_precisa_de_reforco(empresa, *, dias: int = 7) -> list[dict]:
    """
    Quem esta repetindo mais do que devia, do pior para o melhor.

    Aponta candidatos ao reforco biometrico — mais capturas cobrindo
    mais condicoes. Medido em producao, as falhas nao vinham de confusao
    entre pessoas: vinham de quadros que nao produziam correspondencia
    nenhuma, com a distancia ficando em 0,10 quando o rosto era lido.
    Faltava cobertura, e nao precisao.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.facial.repeticao import medir

    desde = timezone.now() - timedelta(days=dias)
    dados = medir(empresa=empresa, desde=desde)

    return [
        {
            **linha,
            "reforco_atual": getattr(linha["colaborador"], "reforco_biometrico", 0),
        }
        for linha in dados["por_pessoa"]
        if linha["batidas"] >= BATIDAS_PARA_MEDIR
        and linha["media"] >= TENTATIVAS_QUE_INCOMODAM
    ]
