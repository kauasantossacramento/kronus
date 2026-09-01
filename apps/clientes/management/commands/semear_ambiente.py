"""
Frases iniciais da tela ociosa.

Escritas aqui, e nao copiadas da internet: frase de terceiro tem autoria
como qualquer outra obra, e um totem comercial exibindo texto alheio sem
licenca e o mesmo problema das imagens — so que menos visivel.

O master edita, remove e acrescenta pelo painel. Isto e so o ponto de
partida, para a tela nao nascer vazia.

    python manage.py semear_ambiente
    python manage.py semear_ambiente --recriar
"""
from django.core.management.base import BaseCommand

MANHA = [
    ("saudacao", "Bom dia! Que seja um bom começo."),
    ("saudacao", "Bom dia. Um passo de cada vez."),
    ("saudacao", "Bom dia — o dia começa aqui."),
    ("motivacao", "Comece pelo que é mais importante."),
    ("motivacao", "Feito é melhor que perfeito."),
    ("motivacao", "Um dia de cada vez, bem feito."),
    ("motivacao", "O que você faz hoje constrói o amanhã."),
]

TARDE = [
    ("saudacao", "Boa tarde!"),
    ("saudacao", "Boa tarde — metade do caminho já foi."),
    ("motivacao", "Respire fundo. Continue."),
    ("motivacao", "O ritmo importa mais que a pressa."),
    ("motivacao", "Uma pausa curta rende a tarde inteira."),
    ("saudacao", "Boa tarde. Você está indo bem."),
]

NOITE = [
    ("descanso", "Boa noite. Descanse bem."),
    ("descanso", "O dia acabou. Vá com calma."),
    ("descanso", "Bom descanso — amanhã é outro dia."),
    ("descanso", "Boa noite. Obrigado pelo seu dia."),
    ("descanso", "Hora de desacelerar."),
    ("descanso", "Durma bem. O resto espera."),
]

# Entram em qualquer periodo, misturadas com a saudacao.
SAUDE = [
    "Beba água. Seu corpo agradece.",
    "Um copo de água agora faz diferença.",
    "Levante e alongue por um minuto.",
    "Descanse os olhos: olhe para longe por 20 segundos.",
    "Uma fruta é um bom lanche.",
    "Coma devagar. Faz bem à digestão.",
    "Ajuste a postura — ombros relaxados.",
    "Respire fundo três vezes.",
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
            apagadas = FraseAmbiente.objects.all().delete()[0]
            self.stdout.write(self.style.WARNING(f"{apagadas} frase(s) apagada(s)."))

        criadas = 0
        blocos = [
            (Periodo.MANHA, MANHA),
            (Periodo.TARDE, TARDE),
            (Periodo.NOITE, NOITE),
        ]
        for periodo, frases in blocos:
            for tipo, texto in frases:
                _, novo = FraseAmbiente.objects.get_or_create(
                    periodo=periodo, texto=texto,
                    defaults={"tipo": tipo},
                )
                criadas += 1 if novo else 0

        # A dica de saude vale nos tres periodos: cadastrada uma vez por
        # periodo para que o sorteio de cada um a alcance.
        for periodo, _ in blocos:
            for texto in SAUDE:
                _, novo = FraseAmbiente.objects.get_or_create(
                    periodo=periodo, texto=texto,
                    defaults={"tipo": FraseAmbiente.Tipo.SAUDE},
                )
                criadas += 1 if novo else 0

        esquecer()
        total = FraseAmbiente.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"{criadas} frase(s) nova(s). Total no acervo: {total}."
        ))
        self.stdout.write(
            "As imagens são adicionadas pelo painel do Master, com autor, "
            "fonte e licença — ver Master, secao Tela ociosa."
        )
