"""
Apaga os registros de ponto de uma empresa para recomecar os testes.

Existe porque durante a validacao o mesmo cenario e repetido varias
vezes, e limpar isso na mao erra em dois pontos que nao perdoam.

O primeiro e o NSR. Ele e sequencial **por empresa** e vive em
`Empresa.nsr_atual`; apagar os registros sem zerar o contador faz a
proxima batida nascer no numero seguinte ao ultimo apagado, com uma
lacuna que o AFD acusa e ninguem sabe explicar depois.

O segundo e o encadeamento. Cada registro guarda o hash do anterior, e o
primeiro de todos guarda vazio. Um registro novo depois da limpeza
precisa ser o primeiro de novo — o que so acontece se nada tiver sobrado
atras dele.

Nunca apaga sem copia: o despejo vai para um arquivo antes, porque
registro de ponto e prova trabalhista e um comando de teste nao pode ser
o motivo de ela sumir.

    python manage.py resetar_pontos --empresa 3            # so mostra
    python manage.py resetar_pontos --empresa 3 --confirmar
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Apaga os registros de ponto de uma empresa e zera o NSR."

    def add_arguments(self, parser):
        parser.add_argument(
            "--empresa", required=True,
            help="ID da empresa, ou parte da razao social.",
        )
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Sem isto, apenas mostra o que seria apagado.",
        )
        parser.add_argument(
            "--tentativas", action="store_true",
            help="Apaga tambem as tentativas de reconhecimento facial.",
        )
        parser.add_argument(
            "--destino", default=None,
            help="Pasta da copia de seguranca (padrao: BASE_DIR/backups).",
        )

    def handle(self, *args, **opcoes):
        from apps.clientes.models import Empresa
        from apps.facial.models import TentativaReconhecimento
        from apps.ponto.models import RegistroPonto

        empresa = self._empresa(Empresa, opcoes["empresa"])
        registros = RegistroPonto.objects.filter(empresa=empresa)
        tentativas = TentativaReconhecimento.objects.filter(empresa=empresa)

        total = registros.count()
        self.stdout.write(f"Empresa: {empresa.razao_social} (id {empresa.pk})")
        self.stdout.write(f"  registros de ponto : {total}")
        self.stdout.write(f"  NSR atual          : {empresa.nsr_atual}")
        self.stdout.write(f"  tentativas faciais : {tentativas.count()}"
                          + ("" if opcoes["tentativas"] else "  (nao serao apagadas)"))

        if total:
            primeiro = registros.order_by("data_hora").first()
            ultimo = registros.order_by("data_hora").last()
            self.stdout.write(
                f"  periodo            : {primeiro.data_hora:%d/%m/%Y %H:%M} "
                f"a {ultimo.data_hora:%d/%m/%Y %H:%M}"
            )

        # Ajuste manual aponta para o registro original. Apagar por baixo
        # deixaria o ajuste orfao — e um ajuste sem o registro que ele
        # corrige nao significa mais nada.
        from apps.ponto.models import AjustePonto

        ajustes = AjustePonto.objects.filter(registro_original__in=registros).count()
        if ajustes:
            raise CommandError(
                f"{ajustes} ajuste(s) manual(is) apontam para estes registros. "
                "Resolva-os antes: apagar deixaria o ajuste sem o que ele corrige."
            )

        if not opcoes["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "\nNada foi alterado. Repita com --confirmar para apagar."
            ))
            return

        if not total and not (opcoes["tentativas"] and tentativas.exists()):
            self.stdout.write(self.style.SUCCESS("Nada a apagar."))
            return

        caminho = self._guardar(registros, empresa, opcoes["destino"])
        if caminho:
            self.stdout.write(f"\nCopia de seguranca: {caminho}")

        with transaction.atomic():
            apagados, _ = registros.delete()
            if opcoes["tentativas"]:
                tentativas.delete()
            # Zerar aqui, e nao antes: se o delete falhar, o contador
            # continua batendo com o que sobrou no banco.
            empresa.nsr_atual = 0
            empresa.save(update_fields=["nsr_atual"])

        empresa.refresh_from_db()
        restantes = RegistroPonto.objects.filter(empresa=empresa).count()
        self.stdout.write(self.style.SUCCESS(
            f"\n{apagados} linha(s) apagada(s). Restam {restantes}. "
            f"NSR zerado ({empresa.nsr_atual}) — a proxima batida sera a de "
            f"numero 1, e abrira uma corrente nova."
        ))

    def _empresa(self, Empresa, referencia):
        if str(referencia).isdigit():
            empresa = Empresa.objects.filter(pk=int(referencia)).first()
            if empresa:
                return empresa
        achadas = list(Empresa.objects.filter(razao_social__icontains=referencia)[:5])
        if not achadas:
            raise CommandError(f"Nenhuma empresa encontrada para {referencia!r}.")
        if len(achadas) > 1:
            nomes = ", ".join(f"{e.pk}: {e.razao_social}" for e in achadas)
            raise CommandError(
                f"{referencia!r} casa com mais de uma empresa — use o id. {nomes}"
            )
        return achadas[0]

    def _guardar(self, registros, empresa, destino):
        """
        Despeja os registros antes de apagar.

        Em JSON, e nao em `dumpdata`: o arquivo serve para alguem ler e
        conferir o que havia ali, e nao para recarregar automaticamente.
        """
        if not registros.exists():
            return None

        pasta = Path(destino or (Path(settings.BASE_DIR) / "backups"))
        pasta.mkdir(parents=True, exist_ok=True)
        agora = timezone.localtime().strftime("%Y%m%d-%H%M%S")
        caminho = pasta / f"pontos-empresa{empresa.pk}-{agora}.json"

        linhas = [
            {
                "nsr": r.nsr,
                "colaborador": r.colaborador.nome_completo,
                "cpf": r.colaborador.cpf,
                "data_hora": r.data_hora.isoformat(),
                "tipo": r.tipo,
                "metodo": r.metodo,
                "hash_registro": r.hash_registro,
                "hash_anterior": r.hash_anterior,
                "confianca_face": r.confianca_face,
            }
            for r in registros.select_related("colaborador").order_by("nsr")
        ]
        caminho.write_text(
            json.dumps(
                {
                    "empresa": empresa.razao_social,
                    "empresa_id": empresa.pk,
                    "gerado_em": timezone.localtime().isoformat(),
                    "registros": linhas,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return caminho
