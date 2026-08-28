"""
Kronus — recalcula a cadeia de hashes de uma empresa.

    python manage.py recalcular_cadeia --empresa <cnpj>              # so confere
    python manage.py recalcular_cadeia --empresa <cnpj> --aplicar    # reescreve

**Leia antes de usar.** Este comando reescreve `hash_registro` e
`hash_anterior` de marcações já gravadas. O hash é a prova de que o
registro não foi alterado depois de criado (Portaria 671/2021); ao
recalculá-lo, essa prova é **substituída por uma nova**, e qualquer
adulteração anterior passa a ser indistinguível de um registro
legítimo. Não existe caso em que isso seja rotina.

O caso que o justifica é um só, e é o motivo desta ferramenta existir:
um **defeito do próprio sistema** fez os hashes serem calculados de uma
forma e verificados de outra. Até a Fase 5, `gerar_hash_registro`
serializava o horário como o recebia — os caminhos de gravação passam
horário local (`-03:00`), enquanto o banco devolve UTC. Mesmo instante,
duas strings, dois hashes. Todo registro criado assim reprova na
verificação, mesmo intacto.

O modo padrão apenas **confere** e classifica cada divergência:

    representacao_de_horario   bate se recalculado no horario local
                               -> é o defeito conhecido, seguro corrigir
    divergencia_real           não bate de nenhuma forma
                               -> pode ser adulteração; NÃO corrija sem
                                  investigar, e preserve o estado atual

`--aplicar` recusa-se a rodar se houver qualquer `divergencia_real`:
apagar a evidência de uma possível adulteração junto com a correção de
um bug é exatamente o que não se pode fazer.
"""
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.utils import apenas_digitos, gerar_hash_registro

logger = logging.getLogger("kronus.ponto")


class Command(BaseCommand):
    help = "Confere e (opcionalmente) recalcula a cadeia de hashes de uma empresa."

    def add_arguments(self, parser):
        parser.add_argument(
            "--empresa", required=True,
            help="CNPJ da empresa (com ou sem máscara).",
        )
        parser.add_argument(
            "--aplicar", action="store_true",
            help="Reescreve os hashes. Sem esta flag, o comando apenas confere.",
        )

    def handle(self, *args, **opcoes):
        from apps.clientes.models import Empresa
        from apps.ponto.models import RegistroPonto

        cnpj = apenas_digitos(opcoes["empresa"])
        empresa = Empresa.objects.filter(cnpj=cnpj).first()
        if empresa is None:
            raise CommandError(f"Empresa com CNPJ {cnpj} não encontrada.")

        registros = list(
            RegistroPonto.objects.filter(empresa=empresa).order_by("nsr")
        )
        if not registros:
            self.stdout.write(self.style.WARNING("Nenhuma marcação para esta empresa."))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n{empresa.razao_social} — {len(registros)} marcação(ões)\n"
            )
        )

        laudo = self._conferir(empresa, registros)
        self._imprimir_laudo(laudo)

        if not opcoes["aplicar"]:
            if laudo["divergentes"]:
                self.stdout.write(
                    "\nPara corrigir as divergências de representação de horário:\n"
                    f"  python manage.py recalcular_cadeia --empresa {cnpj} --aplicar"
                )
            return

        if laudo["suspeitas"]:
            raise CommandError(
                f"{len(laudo['suspeitas'])} registro(s) divergem de forma não "
                "explicada pelo defeito de horário (NSR "
                f"{', '.join(str(n) for n in laudo['suspeitas'][:10])}). "
                "Isso pode ser adulteração. Investigue antes — recalcular "
                "agora apagaria a evidência."
            )

        if not laudo["divergentes"]:
            self.stdout.write(self.style.SUCCESS("\nCadeia íntegra. Nada a fazer."))
            return

        self._aplicar(empresa, registros)

    # ══════════════════════════════════════════════════════════
    def _conferir(self, empresa, registros):
        """
        Percorre a cadeia e classifica cada divergência.

        A conferência usa o `hash_anterior` **gravado**, não o
        recalculado: queremos saber se cada registro, isoladamente,
        confere com o que ele mesmo declara — senão uma única
        divergência no início contaminaria o laudo inteiro.
        """
        from django.utils import timezone

        ok, divergentes, suspeitas = 0, [], []

        for registro in registros:
            esperado = gerar_hash_registro(
                colaborador_id=registro.colaborador_id,
                data_hora=registro.data_hora,
                nsr=registro.nsr,
                salt_empresa=empresa.salt_registro,
                hash_anterior=registro.hash_anterior or "",
            )
            if esperado == registro.hash_registro:
                ok += 1
                continue

            # Reproduz o calculo antigo: horario local, string crua.
            antigo = self._hash_legado(
                registro, empresa, timezone.localtime(registro.data_hora)
            )
            if antigo == registro.hash_registro:
                divergentes.append(registro.nsr)
            else:
                suspeitas.append(registro.nsr)

        return {"ok": ok, "divergentes": divergentes, "suspeitas": suspeitas}

    @staticmethod
    def _hash_legado(registro, empresa, momento):
        """O calculo anterior a correcao — serializava o horario como veio."""
        import hashlib

        base = "|".join([
            str(registro.colaborador_id),
            momento.isoformat(),
            str(registro.nsr),
            empresa.salt_registro,
            registro.hash_anterior or "",
            settings.HASH_SALT_GLOBAL,
        ])
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _imprimir_laudo(self, laudo):
        self.stdout.write(f"  íntegros ................. {laudo['ok']}")
        self.stdout.write(
            self.style.WARNING(
                f"  representação de horário . {len(laudo['divergentes'])}"
            )
            if laudo["divergentes"]
            else "  representação de horário . 0"
        )
        if laudo["suspeitas"]:
            self.stdout.write(
                self.style.ERROR(
                    f"  DIVERGÊNCIA REAL ......... {len(laudo['suspeitas'])}  "
                    f"(NSR {', '.join(str(n) for n in laudo['suspeitas'][:10])})"
                )
            )
            self.stdout.write(
                self.style.ERROR(
                    "\n  Estes não são explicados pelo defeito conhecido. "
                    "Trate como possível adulteração."
                )
            )
        else:
            self.stdout.write("  divergência real ......... 0")

    @transaction.atomic
    def _aplicar(self, empresa, registros):
        """
        Reescreve a cadeia inteira, do NSR 1 em diante.

        Usa `queryset.update()` de proposito: `RegistroPonto.save()`
        proibe alterar `hash_registro` (regra 1 da Secao 14), e essa
        proibicao deve continuar valendo para todo o resto do sistema.
        Este comando e a unica excecao, e ela e explicita.
        """
        from apps.core.models import LogAcesso
        from apps.ponto.models import RegistroPonto

        anterior = ""
        alterados = 0

        for registro in registros:
            novo = gerar_hash_registro(
                colaborador_id=registro.colaborador_id,
                data_hora=registro.data_hora,
                nsr=registro.nsr,
                salt_empresa=empresa.salt_registro,
                hash_anterior=anterior,
            )
            if novo != registro.hash_registro or (registro.hash_anterior or "") != anterior:
                RegistroPonto.objects.filter(pk=registro.pk).update(
                    hash_registro=novo, hash_anterior=anterior
                )
                alterados += 1
            anterior = novo

        LogAcesso.objects.create(
            empresa=empresa,
            acao=LogAcesso.Acao.SEGURANCA,
            descricao=(
                f"Cadeia de hashes recalculada: {alterados} de {len(registros)} "
                "marcações reescritas (correção do defeito de representação de "
                "horário no cálculo do hash)."
            ),
            metadados={
                "registros_totais": len(registros),
                "registros_alterados": alterados,
                "motivo": "correcao_representacao_horario",
            },
        )
        logger.warning(
            "Cadeia recalculada para %s: %s registros alterados.",
            empresa.cnpj, alterados,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{alterados} marcação(ões) reescritas. "
                "A operação ficou registrada no log de segurança."
            )
        )
