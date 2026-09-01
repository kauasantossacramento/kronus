"""
Kronus — quantas tentativas custa uma batida.

O painel de semelhancas media a galeria: quais cadastros ficam perto uns
dos outros. E um dado teorico, e ele assustou sem informar — 13 de 17
pessoas apareciam em algum par, o que se leu como "quase todo mundo
precisa recadastrar".

O que responde de verdade e outra coisa: **quantas tentativas a pessoa
gasta ate o ponto ser gravado**. Um par proximo so custa alguma coisa
quando custa; medir o custo direto dispensa a inferencia.

Uma "sessao" e a sequencia de tentativas do mesmo totem que termina numa
batida. Contar assim, e nao por tentativa isolada, e o que corresponde a
experiencia: quem esta na fila nao conta quadros, conta quanto demorou
para o totem dizer o nome dele.
"""
import collections
from datetime import timedelta

#: Intervalo que separa uma sessao da seguinte.
#:
#: Duas tentativas a mais de dois minutos uma da outra sao de pessoas
#: diferentes, ou da mesma pessoa em momentos diferentes do dia. Juntar
#: as duas inflaria a conta com tempo em que ninguem estava tentando.
CORTE_DE_SESSAO = timedelta(minutes=2)


def _sessoes(tentativas):
    """Agrupa tentativas seguidas do mesmo totem numa sessao."""
    grupos = []
    atual = []
    for t in tentativas:
        if atual and (t.created_at - atual[-1].created_at) > CORTE_DE_SESSAO:
            grupos.append(atual)
            atual = []
        atual.append(t)
    if atual:
        grupos.append(atual)
    return grupos


def medir(*, empresa=None, desde=None, ate=None) -> dict:
    """
    Quantas tentativas por batida, de verdade.

    Devolve o que se pode agir: a mediana (o caso tipico), o pior caso
    observado e quem mais repete — porque a media esconde a pessoa que
    tenta oito vezes atras de nove que acertam de primeira.
    """
    from apps.facial.models import TentativaReconhecimento as T

    qs = T.objects.select_related("colaborador", "totem").order_by(
        "totem_id", "created_at"
    )
    if empresa is not None:
        qs = qs.filter(empresa=empresa)
    if desde is not None:
        qs = qs.filter(created_at__gte=desde)
    if ate is not None:
        qs = qs.filter(created_at__lt=ate)

    por_totem = collections.defaultdict(list)
    for t in qs:
        por_totem[t.totem_id].append(t)

    sessoes = []
    for tentativas in por_totem.values():
        sessoes.extend(_sessoes(tentativas))

    concluidas = []          # sessoes que terminaram em ponto
    abandonadas = 0          # tentaram e desistiram
    por_pessoa = collections.defaultdict(list)

    for sessao in sessoes:
        bateu = next(
            (t for t in sessao if t.desfecho == T.Desfecho.PONTO), None
        )
        if bateu is None:
            # So conta como abandono se alguem foi identificado em algum
            # momento: sessao inteira sem rosto e camera vendo a parede,
            # nao pessoa desistindo.
            if any(t.colaborador_id for t in sessao):
                abandonadas += 1
            continue
        # Tentativas ate a batida, inclusive.
        gastas = sessao.index(bateu) + 1
        concluidas.append(gastas)
        if bateu.colaborador_id:
            por_pessoa[bateu.colaborador].append(gastas)

    def mediana(valores):
        if not valores:
            return None
        ordenado = sorted(valores)
        meio = len(ordenado) // 2
        if len(ordenado) % 2:
            return ordenado[meio]
        return (ordenado[meio - 1] + ordenado[meio]) / 2

    reincidentes = sorted(
        (
            {
                "colaborador": c,
                "batidas": len(v),
                "media": round(sum(v) / len(v), 2),
                "pior": max(v),
            }
            for c, v in por_pessoa.items()
        ),
        key=lambda r: (-r["media"], -r["pior"]),
    )

    return {
        "sessoes": len(sessoes),
        "batidas": len(concluidas),
        "abandonadas": abandonadas,
        "media": round(sum(concluidas) / len(concluidas), 2) if concluidas else None,
        "mediana": mediana(concluidas),
        "pior": max(concluidas) if concluidas else None,
        "de_primeira": sum(1 for n in concluidas if n == 1),
        "ate_duas": sum(1 for n in concluidas if n <= 2),
        "acima_de_tres": sum(1 for n in concluidas if n > 3),
        "por_pessoa": reincidentes,
    }
