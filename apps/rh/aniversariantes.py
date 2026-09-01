"""
Kronus — aniversariantes do mes.

Um calendario de aniversarios nao e enfeite: e a informacao que o RH
usa para lembrar do bolo, do recado no mural e da mensagem no grupo. Ela
ja esta no cadastro — o que faltava era estar num lugar onde alguem
olhasse.

Ordena por dia, e nao por nome: quem abre esta tela quer saber quem vem
primeiro, nao quem comeca com A.
"""
from calendar import monthrange
from datetime import date

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

DIAS_DA_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def do_mes(empresas, ano: int, mes: int) -> list[dict]:
    """
    Aniversariantes do mes, com a idade que farao.

    Recebe `empresas` (e nao uma so) porque um totem de grupo atende
    varios CNPJs, e o RH que cuida do grupo quer a lista inteira.
    """
    from apps.rh.models import Colaborador

    pessoas = (
        Colaborador.objects.filter(
            empresa__in=empresas, ativo=True, data_nascimento__month=mes
        )
        # `cargo_ref` e a relacao; `cargo` e texto livre no proprio
        # registro. Pedir select_related no texto livre e erro de campo,
        # e derrubava a pagina inteira.
        .select_related("empresa", "cargo_ref")
        .order_by("data_nascimento__day", "nome_completo")
    )

    hoje = date.today()
    resultado = []
    for p in pessoas:
        nascimento = p.data_nascimento
        # A idade que completa neste aniversario, e nao a de hoje: a
        # tela e sobre o dia que vem, nao sobre agora.
        idade = ano - nascimento.year
        resultado.append({
            "id": p.pk,
            "nome": p.nome_exibicao,
            "dia": nascimento.day,
            "idade": idade if idade > 0 else None,
            # O cargo cadastrado vence; o texto livre atende quem nunca
            # criou a tabela de cargos.
            "cargo": (p.cargo_ref.nome if p.cargo_ref_id else "") or p.cargo or "",
            "empresa": p.empresa.nome_exibicao,
            "email": p.email or "",
            "hoje": (nascimento.day, nascimento.month) == (hoje.day, hoje.month)
                    and ano == hoje.year,
        })
    return resultado


def grade(ano: int, mes: int, aniversariantes: list[dict]) -> list[list[dict]]:
    """
    O mes em semanas, para desenhar o calendario.

    Devolve listas de 7 posicoes comecando na segunda-feira. As casas
    vazias do inicio e do fim vem como `None` para que o template nao
    precise contar nada — template que faz aritmetica de calendario e
    template que erra em fevereiro.
    """
    primeiro_dia_semana, dias_no_mes = monthrange(ano, mes)

    por_dia = {}
    for a in aniversariantes:
        por_dia.setdefault(a["dia"], []).append(a)

    hoje = date.today()
    celulas = [None] * primeiro_dia_semana
    for dia in range(1, dias_no_mes + 1):
        celulas.append({
            "dia": dia,
            "pessoas": por_dia.get(dia, []),
            "hoje": (dia, mes, ano) == (hoje.day, hoje.month, hoje.year),
        })
    while len(celulas) % 7:
        celulas.append(None)

    return [celulas[i:i + 7] for i in range(0, len(celulas), 7)]
