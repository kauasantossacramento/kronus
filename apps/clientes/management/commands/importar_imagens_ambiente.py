"""
Traz imagens novas para o acervo da tela ociosa.

    python manage.py importar_imagens_ambiente            # so relata
    python manage.py importar_imagens_ambiente --confirmar
    python manage.py importar_imagens_ambiente --periodo noite --confirmar

**Acrescenta, nunca substitui.** O que o master subiu a mao, ou ajustou,
fica. Uma importacao que limpasse o acervo apagaria curadoria humana
para pôr resultado de busca no lugar — e a segunda vez que isso
acontecesse ninguem mais curaria nada.

**Respeita o teto por periodo.** Sem teto, rodar toda semana encheria o
disco e faria a tela repetir menos, mas custaria banda de totens em rede
fraca a cada atualizacao do Service Worker.
"""
from django.core.management.base import BaseCommand

#: Quantas imagens ativas cada periodo comporta.
#:
#: Seis a oito ja bastam para o rodizio nao ficar obvio numa tela que a
#: pessoa olha por segundos. Mais que isso e peso no cache do totem sem
#: ganho que alguem perceba.
TETO_POR_PERIODO = 8


class Command(BaseCommand):
    help = "Importa imagens do Pexels para a tela ociosa."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Sem isto, apenas mostra o que seria importado.",
        )
        parser.add_argument(
            "--periodo", default=None,
            help="Limita a um período (manha, tarde, noite).",
        )
        parser.add_argument(
            "--teto", type=int, default=TETO_POR_PERIODO,
            help=f"Máximo de imagens ativas por período (padrão {TETO_POR_PERIODO}).",
        )

    def handle(self, *args, **opcoes):
        from django.conf import settings
        from django.core.files.base import ContentFile

        from apps.clientes.ambiente import (
            ImagemAmbiente,
            Periodo,
            medir_claridade,
        )
        from apps.clientes.ambiente_servico import esquecer
        from apps.clientes import pexels

        if not getattr(settings, "PEXELS_API_KEY", ""):
            self.stdout.write(self.style.ERROR(
                "PEXELS_API_KEY não está configurada. Sem ela a busca "
                "automática não roda — o acervo continua com o que já tem."
            ))
            return

        periodos = (
            [opcoes["periodo"]] if opcoes["periodo"] else list(Periodo.values)
        )
        teto = max(1, opcoes["teto"])
        confirmar = opcoes["confirmar"]

        total_novas = 0
        for periodo in periodos:
            if periodo not in Periodo.values:
                self.stdout.write(self.style.WARNING(f"Período desconhecido: {periodo}"))
                continue

            existentes = ImagemAmbiente.objects.filter(periodo=periodo, ativo=True)
            faltam = teto - existentes.count()
            self.stdout.write(
                f"\n{periodo}: {existentes.count()} ativa(s), teto {teto}"
            )
            if faltam <= 0:
                self.stdout.write("  já está completo.")
                continue

            ja_temos = set(
                ImagemAmbiente.objects.filter(periodo=periodo)
                .exclude(id_externo="")
                .values_list("id_externo", flat=True)
            )
            candidatas = [
                c for c in pexels.buscar(periodo)
                if c["id_externo"] not in ja_temos
            ][:faltam]

            if not candidatas:
                self.stdout.write("  nada novo encontrado.")
                continue

            if not confirmar:
                for c in candidatas:
                    self.stdout.write(f"  [prévia] {c['termo']} — {c['titulo'][:50]}")
                total_novas += len(candidatas)
                continue

            for c in candidatas:
                dados = pexels.baixar(c["url_arquivo"])
                if not dados:
                    continue
                imagem = ImagemAmbiente(
                    periodo=periodo,
                    titulo=c["titulo"],
                    autor=c["autor"],
                    fonte=c["fonte"],
                    # Guardado mesmo sem exibir: a licenca dispensa
                    # credito, mas "de onde veio?" precisa ter resposta.
                    licenca="Pexels License",
                    id_externo=c["id_externo"],
                    # Medido aqui, uma vez: o tablet nao precisa refazer
                    # essa conta a cada troca de slide.
                    clara=medir_claridade(dados),
                )
                imagem.imagem.save(
                    f"pexels_{c['id_externo']}.jpg", ContentFile(dados), save=True
                )
                total_novas += 1
                self.stdout.write(f"  + {c['titulo'][:56]}")

        if confirmar:
            esquecer()
            self.stdout.write(self.style.SUCCESS(
                f"\n{total_novas} imagem(ns) adicionada(s) ao acervo."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"\n{total_novas} imagem(ns) seriam importadas. "
                "Repita com --confirmar."
            ))
