"""
Liga o autoaprendizado nas empresas que ja existem.

O `default=True` do modelo so vale para empresa nova: quem ja estava
cadastrado nasceu com `False` gravado no banco, e uma mudanca de default
nao reescreve linha existente. Sem este comando, o padrao novo valeria
so para quem chegasse depois.

    python manage.py ativar_aprendizado            # so relata
    python manage.py ativar_aprendizado --confirmar
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ativa o aprendizado facial nas empresas existentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Sem isto, apenas mostra quantas seriam alteradas.",
        )
        parser.add_argument("--empresa", default=None, help="Limita a uma empresa (id).")

    def handle(self, *args, **opcoes):
        from apps.clientes.models import Empresa

        desligadas = Empresa.objects.filter(aprendizado_facial=False)
        if opcoes["empresa"]:
            desligadas = desligadas.filter(pk=int(opcoes["empresa"]))

        total = desligadas.count()
        self.stdout.write(f"Empresas com aprendizado desligado: {total}")
        for e in desligadas:
            self.stdout.write(f"  {e.nome_exibicao}")

        if not total:
            self.stdout.write(self.style.SUCCESS("\nNada a fazer."))
            return

        if not opcoes["confirmar"]:
            self.stdout.write(self.style.WARNING(
                f"\n{total} empresa(s) seriam alteradas. Repita com --confirmar."
            ))
            return

        alteradas = desligadas.update(aprendizado_facial=True)
        self.stdout.write(self.style.SUCCESS(
            f"\n{alteradas} empresa(s) agora aprendem com as batidas."
        ))
