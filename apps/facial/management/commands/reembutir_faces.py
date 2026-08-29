"""
Recalcula os embeddings faciais a partir das fotos ja guardadas.

Embedding e especifico do modelo: trocar de ArcFace para Facenet512
invalida tudo o que estava gravado — os vetores antigos continuam la,
com 512 posicoes, e o sistema os compara alegremente contra vetores do
modelo novo. O resultado nao e erro: e reconhecimento aleatorio.

Como as fotos de cadastro ficam guardadas, da para refazer sem pedir que
ninguem volte na frente da camera. Quem nao tem foto (empresa que apaga
apos o encoding) precisa recadastrar, e o comando diz quem e.

    python manage.py reembutir_faces                 # so relata
    python manage.py reembutir_faces --confirmar
"""
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Recalcula os embeddings faciais com o modelo configurado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Sem isto, apenas mostra o que seria refeito.",
        )
        parser.add_argument(
            "--empresa", default=None,
            help="Limita a uma empresa (id).",
        )

    def handle(self, *args, **opcoes):
        from apps.facial.models import FaceRegistro
        from apps.facial.services import FaceRecognitionService

        modelo = settings.DEEPFACE_MODEL
        amostras = FaceRegistro.objects.filter(ativo=True).select_related(
            "colaborador", "colaborador__empresa"
        )
        if opcoes["empresa"]:
            amostras = amostras.filter(
                colaborador__empresa_id=int(opcoes["empresa"])
            )

        desatualizadas = [a for a in amostras if a.modelo != modelo]
        sem_foto = [a for a in desatualizadas if not a.imagem]

        self.stdout.write(f"Modelo configurado : {modelo}")
        self.stdout.write(f"Amostras ativas    : {amostras.count()}")
        self.stdout.write(f"De outro modelo    : {len(desatualizadas)}")
        self.stdout.write(f"Sem foto guardada  : {len(sem_foto)}")

        if sem_foto:
            nomes = sorted({a.colaborador.nome_exibicao for a in sem_foto})
            self.stdout.write(self.style.WARNING(
                "  Precisam recadastrar (a foto nao foi guardada): "
                + ", ".join(nomes)
            ))

        refazer = [a for a in desatualizadas if a.imagem]
        if not refazer:
            self.stdout.write(self.style.SUCCESS("\nNada a recalcular."))
            return

        if not opcoes["confirmar"]:
            self.stdout.write(self.style.WARNING(
                f"\n{len(refazer)} amostra(s) seriam recalculadas. "
                "Repita com --confirmar."
            ))
            return

        servico = FaceRecognitionService()
        provedor = servico.provedor
        refeitas, falhas = 0, []
        tocados = set()

        for amostra in refazer:
            try:
                amostra.imagem.open("rb")
                dados = amostra.imagem.read()
                amostra.imagem.close()
                vetor = provedor.gerar_embedding(dados)
            except Exception as erro:
                falhas.append((amostra, f"{type(erro).__name__}: {erro}"))
                continue

            amostra.definir_embedding(vetor, salvar=False)
            amostra.modelo = modelo
            amostra.save(update_fields=["embedding", "modelo", "updated_at"])
            refeitas += 1
            tocados.add(amostra.colaborador)

        # A media do colaborador tambem e do modelo antigo, e o cache
        # guarda os vetores prontos: os dois precisam ser refeitos, ou o
        # trabalho acima nao chega ao reconhecimento.
        for colaborador in tocados:
            servico.consolidar_cadastro(colaborador)

        self.stdout.write(self.style.SUCCESS(
            f"\n{refeitas} amostra(s) recalculada(s) em "
            f"{len(tocados)} colaborador(es)."
        ))
        for amostra, motivo in falhas:
            self.stdout.write(self.style.ERROR(
                f"  falhou: {amostra.colaborador.nome_exibicao} "
                f"({amostra.angulo}) — {motivo}"
            ))
        if falhas:
            self.stdout.write(self.style.WARNING(
                "As amostras que falharam continuam com o vetor antigo, que "
                "NAO serve para o modelo novo. Desative-as ou recadastre."
            ))
