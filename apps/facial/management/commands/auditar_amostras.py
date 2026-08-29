"""
Encontra amostras faciais que nao combinam com as demais do titular.

Existe por um caso de producao. Um colaborador tinha cinco amostras; a
quinta, capturada tres minutos depois das outras, estava a 0,70 delas —
distancia de pessoa diferente. Como o reconhecimento fica com a menor
distancia entre as amostras, aquela captura passou a aceitar rostos que
nao eram do titular, e um visitante teve ponto registrado no nome dele.

O cadastro agora recusa amostra incoerente na entrada. Este comando
cuida do que ja estava gravado antes disso.

    python manage.py auditar_amostras            # so relata
    python manage.py auditar_amostras --desativar
"""
import itertools

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.facial.models import FaceRegistro


def distancia(a, b) -> float:
    na = float(np.linalg.norm(a)) or 1e-9
    nb = float(np.linalg.norm(b)) or 1e-9
    return 1.0 - float(a @ b) / (na * nb)


class Command(BaseCommand):
    help = "Audita a coerencia entre as amostras faciais de cada colaborador."

    def add_arguments(self, parser):
        parser.add_argument(
            "--desativar", action="store_true",
            help="Desativa as amostras divergentes (por padrao apenas relata).",
        )
        parser.add_argument(
            "--limite", type=float, default=None,
            help="Distancia mediana acima da qual a amostra e divergente.",
        )

    def handle(self, *args, **opcoes):
        limite = opcoes["limite"] or settings.FACE_DISTANCIA_MAXIMA_AMOSTRA
        desativar = opcoes["desativar"]

        por_colaborador = {}
        for registro in FaceRegistro.objects.filter(ativo=True).select_related(
            "colaborador"
        ):
            por_colaborador.setdefault(registro.colaborador, []).append(registro)

        total_suspeitas = 0
        for colaborador, registros in sorted(
            por_colaborador.items(), key=lambda par: par[0].nome_completo
        ):
            # Com menos de tres amostras nao ha maioria para discordar de
            # uma: apontar a divergente seria escolher no par.
            if len(registros) < 3:
                continue

            vetores = [r.obter_embedding() for r in registros]

            # Amostras das OUTRAS pessoas da mesma empresa. Uma captura
            # pode combinar com as irmas dentro do limite e ainda assim
            # ficar perto de um colega — e essa e a que aproxima duas
            # pessoas no reconhecimento, porque vale a menor distancia.
            alheias = [
                r.obter_embedding()
                for r in FaceRegistro.objects.filter(
                    ativo=True, colaborador__empresa=colaborador.empresa
                ).exclude(colaborador=colaborador)
            ]

            suspeitas = []
            for i, (registro, vetor) in enumerate(zip(registros, vetores)):
                irmas = [distancia(vetor, v) for j, v in enumerate(vetores) if j != i]
                mediana = sorted(irmas)[len(irmas) // 2]
                if mediana > limite:
                    suspeitas.append((registro, mediana, "diverge das irmãs"))
                    continue

                if not alheias:
                    continue
                perto_alheia = min(distancia(vetor, v) for v in alheias)
                if perto_alheia < min(irmas):
                    suspeitas.append((
                        registro, perto_alheia,
                        "mais parecida com outra pessoa do que com as irmãs",
                    ))

            if not suspeitas:
                continue

            # Nunca deixar o colaborador sem cadastro: se quase tudo e
            # suspeito, o problema e o cadastro inteiro, e refaze-lo e
            # decisao de quem opera — nao deste comando.
            if len(suspeitas) > len(registros) - 2:
                self.stdout.write(self.style.WARNING(
                    f"{colaborador.nome_completo}: {len(suspeitas)} de "
                    f"{len(registros)} amostras divergem entre si. O cadastro "
                    f"inteiro precisa ser refeito — nada foi alterado."
                ))
                continue

            total_suspeitas += len(suspeitas)
            self.stdout.write(self.style.WARNING(colaborador.nome_completo))
            for registro, valor, motivo in suspeitas:
                self.stdout.write(
                    f"  amostra #{registro.pk} ({registro.angulo}) "
                    f"{valor:.3f} — {motivo}"
                )
                if desativar:
                    registro.ativo = False
                    registro.save(update_fields=["ativo", "updated_at"])

            if desativar:
                from apps.facial.services import FaceRecognitionService
                FaceRecognitionService().consolidar_cadastro(colaborador)
                self.stdout.write(self.style.SUCCESS(
                    "  desativadas; media e cache do colaborador refeitos"
                ))

        if not total_suspeitas:
            self.stdout.write(self.style.SUCCESS(
                "Nenhuma amostra divergente."
            ))
        elif not desativar:
            self.stdout.write(
                f"\n{total_suspeitas} amostra(s) divergente(s). "
                f"Rode com --desativar para retira-las."
            )
