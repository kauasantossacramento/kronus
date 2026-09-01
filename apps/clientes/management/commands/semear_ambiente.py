"""
Frases iniciais da tela ociosa.

Escritas aqui, e nao copiadas da internet: frase de terceiro tem autoria
como qualquer outra obra, e um totem comercial exibindo texto alheio sem
licenca e o mesmo problema das imagens — so que menos visivel.

**Sobre as dicas de saude.** A primeira versao trazia coisas como "uma
fruta e um bom lanche", e o retorno foi justo: generico demais. Conselho
que todo mundo ja ouviu nao muda comportamento nenhum — vira ruido, e
depois de duas semanas ninguem le mais a tela.

O que ficou tem tres coisas que a versao anterior nao tinha:

  1. e **especifico** — diz o quanto, ou quando, ou quanto tempo;
  2. da o **motivo**, porque o porque e o que faz lembrar depois;
  3. cabe no **momento** — e algo que da para fazer ali, de pe, no
     minuto seguinte a bater o ponto.

O master edita, remove e acrescenta pelo painel. Isto e so o ponto de
partida, para a tela nao nascer vazia.

    python manage.py semear_ambiente
    python manage.py semear_ambiente --recriar
"""
from django.core.management.base import BaseCommand

#: Saudacao e reflexao, por periodo.
#:
#: A primeira versao era slogan — "feito e melhor que perfeito", "um
#: passo de cada vez". Frase de cartaz motivacional envelhece em dois
#: dias: quem passa ali todo dia ja leu, e ler de novo nao acrescenta
#: nada.
#:
#: O que fica tem de dizer algo **verdadeiro e um pouco inesperado**,
#: em vez de repetir o que todo mundo ja sabe. E curta o bastante para
#: ser lida de passagem, em pe, a alguns metros da tela.
MANHA = [
    ("saudacao", "Bom dia. O dia ainda não decidiu nada — você decide."),
    ("saudacao", "Bom dia. Começar já é metade."),
    ("saudacao", "Bom dia. Alguém aqui vai precisar de você hoje."),
    ("motivacao", "As primeiras horas costumam decidir como o resto vai ser."),
    ("motivacao", "Faça primeiro o que você está evitando. O resto fica leve."),
    ("motivacao", "Nem todo dia precisa ser excepcional. Alguns só precisam ser bem feitos."),
    ("motivacao", "O trabalho de hoje alguém vai receber amanhã."),
    ("motivacao", "Pressa e ritmo são coisas diferentes. Escolha o ritmo."),
]

TARDE = [
    ("saudacao", "Boa tarde. A parte difícil geralmente já passou."),
    ("saudacao", "Boa tarde. Metade do caminho é um bom lugar para respirar."),
    ("motivacao", "Cansaço não é falta de vontade. É pedido de pausa."),
    ("motivacao", "Quem não para no meio do dia paga no fim dele."),
    ("motivacao", "O que rende à tarde raramente é a pressa."),
    ("motivacao", "Terminar uma coisa vale mais que começar três."),
    ("saudacao", "Boa tarde. Você chegou até aqui."),
]

NOITE = [
    ("descanso", "Boa noite. O que ficou hoje continua existindo amanhã."),
    ("descanso", "Trabalho bem feito também é saber a hora de parar."),
    ("descanso", "Boa noite. Obrigado pelo seu dia."),
    ("descanso", "Descansar não é pausa do trabalho. Faz parte dele."),
    ("descanso", "O dia acabou. Deixe-o acabar."),
    ("descanso", "Durma bem. Amanhã começa outro, e não é este."),
    ("descanso", "Boa noite. Você fez o que dava para fazer hoje."),
]

#: Dicas de saude, por periodo.
#:
#: Separadas por periodo de proposito: "evite cafe agora" faz sentido as
#: 17h e nao faz as 7h, e "alongue antes de comecar" e o contrario.
#: Repetir a mesma lista nos tres horarios era parte do que deixava tudo
#: com cara de frase de calendario.
SAUDE_MANHA = [
    "Beba água antes do café. Você acordou desidratado.",
    "Dois minutos de alongamento agora evitam a dor de ombro das 15h.",
    "Café com comida sustenta; café sozinho cobra o preço às 10h.",
    "Se for sentar por horas, ajuste a cadeira antes. Depois você esquece.",
    "A tela na altura dos olhos poupa seu pescoço o dia inteiro.",
    "Tomou sol hoje? 15 minutos de manhã ajudam a dormir à noite.",
]

SAUDE_TARDE = [
    "A cada hora sentado, levante por 2 minutos. Sua circulação agradece.",
    "Vista cansada? Olhe 20 segundos para algo distante a cada 20 minutos.",
    "Almoce longe da tela. A digestão e a atenção melhoram juntas.",
    "Sono depois do almoço é normal. Caminhar 5 minutos resolve melhor que café.",
    "Beba água antes de sentir sede — a sede já é sinal de atraso.",
    "Um punhado de castanhas rende mais que o terceiro café.",
    "Ombro doendo? Costuma ser a altura da mesa, não o esforço.",
    "Levante os braços e respire fundo. Trinta segundos bastam.",
]

SAUDE_NOITE = [
    "Café depois das 17h ainda está no seu corpo na hora de dormir.",
    "Jantar leve dorme melhor que jantar completo.",
    "Tela desligada 30 minutos antes de deitar melhora o sono de verdade.",
    "Alongue as pernas antes de sair. O corpo agradece amanhã.",
    "Dormiu mal? Acordar no mesmo horário ajuda mais que dormir até tarde.",
    "Água à noite também conta. O corpo se recupera hidratado.",
]


class Command(BaseCommand):
    help = "Cria as frases iniciais da tela ociosa."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recriar", action="store_true",
            help="Apaga as frases existentes antes de criar.",
        )

    def handle(self, *args, **opcoes):
        from apps.clientes.ambiente import FraseAmbiente, Periodo
        from apps.clientes.ambiente_servico import esquecer

        if opcoes["recriar"]:
            # `delete()` do BaseModel e soft delete e devolve um int;
            # o do Django devolve uma tupla. Contar antes funciona nos
            # dois casos e nao depende de qual esta em uso.
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
            for tipo, texto in frases:
                _, novo = FraseAmbiente.objects.get_or_create(
                    periodo=periodo, texto=texto, defaults={"tipo": tipo},
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
        # estava cadastrado tem 8 gravado no banco, e continuaria
        # trocando de imagem a cada 8 segundos — que e o que estava
        # rapido demais para ler a frase.
        #
        # So mexe em quem esta no valor antigo: uma empresa que escolheu
        # 6 ou 20 escolheu, e sobrescrever isso seria desfazer decisao
        # de outra pessoa.
        from apps.clientes.models import Empresa

        ajustadas = Empresa.objects.filter(slides_segundos=8).update(
            slides_segundos=14
        )
        if ajustadas:
            self.stdout.write(self.style.SUCCESS(
                f"{ajustadas} empresa(s) passaram de 8s para 14s por imagem."
            ))

        esquecer()
        total = FraseAmbiente.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"{criadas} frase(s) nova(s). Total no acervo: {total}."
        ))
        self.stdout.write(
            "As imagens são adicionadas pelo painel do Master, com autor, "
            "fonte e licença — ver Master, secao Tela ociosa."
        )
