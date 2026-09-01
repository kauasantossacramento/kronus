"""
Frases da tela ociosa.

**O que deu errado nas duas primeiras versões.** A primeira era slogan de
cartaz — "feito é melhor que perfeito", "um passo de cada vez". A segunda
tentou consertar e virou conselho de calendário: "o dia acabou, vá com
calma", "um copo de água agora faz diferença". Frase que todo mundo já
leu não faz ninguém pensar em nada; vira ruído, e em duas semanas a tela
deixa de ser lida.

**O que mudou.** Frase assinada carrega peso que anônima não carrega: a
mesma ideia dita por Sêneca há dois mil anos lê diferente de um aviso de
mural. Onde não há citação, a linha original precisa dizer algo
**verdadeiro e um pouco inesperado** — e não repetir o que a pessoa já
sabe.

**Só autores em domínio público.** Citar quem morreu ontem num produto
comercial é problema de direito autoral, e o totem está na parede do
cliente. Sêneca, Marco Aurélio, Epicteto, Sócrates, Lao-Tsé, Confúcio e
Fernando Pessoa (1935) estão livres; contemporâneos não.

**Sobre as dicas de saúde.** Também refeitas. "Beba água" não muda o
comportamento de ninguém — quem não bebe já sabe que deveria. O que muda
é o dado que a pessoa não tinha: *por que* agora, *quanto*, ou *o que
acontece se não*.

    python manage.py semear_ambiente
    python manage.py semear_ambiente --recriar
"""
from django.core.management.base import BaseCommand

#: Segundos por imagem — e por frase, que troca junto.
#:
#: Vinte e cinco. Catorze ainda era pouco: a frase agora tem autor e
#: alguma densidade, e ler, entender e olhar a foto não cabe em catorze
#: segundos. Numa tela ligada o dia inteiro o custo de demorar é zero; o
#: de trocar cedo é a frase não ser lida por ninguém.
SEGUNDOS_POR_IMAGEM = 25

#: (tipo, texto, autor). Autor vazio = linha escrita para o Kronus.
MANHA = [
    ("motivacao",
     "Não é que temos pouco tempo — é que perdemos muito dele.", "Sêneca"),
    ("motivacao",
     "Você tem poder sobre a sua mente, não sobre os acontecimentos. "
     "Perceba isso e encontrará força.", "Marco Aurélio"),
    ("motivacao",
     "Não importa o quão devagar você vá, desde que não pare.", "Confúcio"),
    ("motivacao",
     "Uma jornada de mil milhas começa com um único passo.", "Lao-Tsé"),
    ("saudacao",
     "Bom dia. O que você faz nas próximas horas costuma decidir o resto.", ""),
    ("saudacao",
     "Bom dia. Alguém vai depender do seu trabalho hoje sem que você saiba.", ""),
    ("motivacao",
     "Comece pelo que está evitando. É quase sempre o que mais importa.", ""),
]

TARDE = [
    ("motivacao",
     "Não são os fatos que perturbam as pessoas, mas o julgamento que "
     "fazem deles.", "Epicteto"),
    ("motivacao",
     "Enquanto adiamos, a vida passa.", "Sêneca"),
    ("motivacao",
     "Tudo vale a pena se a alma não é pequena.", "Fernando Pessoa"),
    ("motivacao",
     "A qualidade da sua vida depende da qualidade dos seus pensamentos.",
     "Marco Aurélio"),
    ("saudacao",
     "Boa tarde. Cansaço no meio do dia não é fraqueza — é informação.", ""),
    ("motivacao",
     "Terminar uma coisa rende mais do que começar três.", ""),
    ("saudacao",
     "Boa tarde. A parte difícil do dia costuma já ter passado.", ""),
]

NOITE = [
    ("descanso",
     "Uma vida não examinada não vale a pena ser vivida.", "Sócrates"),
    ("descanso",
     "Nada acontece a alguém que essa pessoa não seja capaz de suportar.",
     "Marco Aurélio"),
    ("descanso",
     "Quem sabe o bastante já tem o suficiente.", "Lao-Tsé"),
    ("descanso",
     "Não é curta a vida que temos: nós é que a tornamos curta.", "Sêneca"),
    ("descanso",
     "Boa noite. O que ficou por fazer vai continuar existindo amanhã.", ""),
    ("descanso",
     "Trabalho bem feito inclui saber a hora de parar.", ""),
    ("descanso",
     "Boa noite. Você fez o que dava para fazer com o dia que teve.", ""),
]

#: Dicas de saúde, por período.
#:
#: Refeitas porque "beba água" não muda o comportamento de ninguém: quem
#: não bebe já sabe que deveria. O que muda é o dado que a pessoa não
#: tinha — por que agora, quanto, ou o que acontece se não.
SAUDE_MANHA = [
    "Você acorda desidratado: são sete a oito horas sem beber nada.",
    "Café em jejum acelera a queda de energia das 10h. Coma antes.",
    "Ajuste a cadeira agora. Depois de sentar, ninguém ajusta.",
    "Tela abaixo da linha dos olhos multiplica a carga sobre o pescoço.",
    "Quinze minutos de sol pela manhã regulam o sono da noite seguinte.",
    "Alongue os ombros antes de começar: eles travam sem avisar.",
]

SAUDE_TARDE = [
    "A cada hora sentado, dois minutos em pé. A circulação depende disso.",
    "Vista cansada é músculo travado: olhe vinte segundos para longe.",
    "O sono depois do almoço é fisiológico. Caminhar resolve; café adia.",
    "Sede já é sinal de atraso — o corpo avisa depois de começar a faltar.",
    "Castanhas seguram a tarde melhor do que o terceiro café.",
    "Dor de ombro no fim do dia costuma ser altura de mesa, não esforço.",
    "Respirar fundo cinco vezes baixa a frequência cardíaca de verdade.",
]

SAUDE_NOITE = [
    "A cafeína leva cerca de seis horas para cair pela metade no corpo.",
    "Jantar pesado atrapalha o sono mais do que dormir tarde.",
    "Luz de tela atrasa o sono. Desligue meia hora antes de deitar.",
    "Alongue as pernas antes de sair: quem passou o dia em pé sente amanhã.",
    "Acordar sempre no mesmo horário ajuda mais do que dormir até tarde.",
    "O corpo se recupera durante o sono, e recupera melhor hidratado.",
]


class Command(BaseCommand):
    help = "Cria as frases da tela ociosa."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recriar", action="store_true",
            help="Apaga as frases existentes antes de criar.",
        )

    def handle(self, *args, **opcoes):
        from apps.clientes.ambiente import FraseAmbiente, Periodo
        from apps.clientes.ambiente_servico import esquecer

        if opcoes["recriar"]:
            # `delete()` do BaseModel e soft delete e devolve um int; o
            # do Django devolve uma tupla. Contar antes funciona nos dois
            # casos e nao depende de qual esta em uso.
            apagadas = FraseAmbiente.objects.count()
            FraseAmbiente.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"{apagadas} frase(s) apagada(s)."))

        blocos = [
            (Periodo.MANHA, MANHA, SAUDE_MANHA),
            (Periodo.TARDE, TARDE, SAUDE_TARDE),
            (Periodo.NOITE, NOITE, SAUDE_NOITE),
        ]

        criadas = 0
        for periodo, frases, saude in blocos:
            for tipo, texto, autor in frases:
                _, novo = FraseAmbiente.objects.get_or_create(
                    periodo=periodo, texto=texto,
                    defaults={"tipo": tipo, "autor": autor},
                )
                criadas += 1 if novo else 0
            for texto in saude:
                _, novo = FraseAmbiente.objects.get_or_create(
                    periodo=periodo, texto=texto,
                    defaults={"tipo": FraseAmbiente.Tipo.SAUDE},
                )
                criadas += 1 if novo else 0

        # O tempo de tela das empresas que ja existiam.
        #
        # Mudar o `default` do modelo so vale para empresa nova: quem ja
        # estava cadastrado tem o valor antigo gravado e continuaria
        # trocando rapido demais para ler a frase.
        #
        # So mexe em quem esta num dos valores que ja foram padrao: uma
        # empresa que escolheu 6 ou 40 escolheu, e sobrescrever seria
        # desfazer decisao de outra pessoa.
        from apps.clientes.models import Empresa

        ajustadas = Empresa.objects.filter(
            slides_segundos__in=[8, 14]
        ).update(slides_segundos=SEGUNDOS_POR_IMAGEM)
        if ajustadas:
            self.stdout.write(self.style.SUCCESS(
                f"{ajustadas} empresa(s) passaram para "
                f"{SEGUNDOS_POR_IMAGEM}s por imagem."
            ))

        esquecer()
        total = FraseAmbiente.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"{criadas} frase(s) nova(s). Total no acervo: {total}."
        ))
