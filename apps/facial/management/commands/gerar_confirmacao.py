"""
Calcula o vetor do segundo modelo para os cadastros que ja existem.

A conferencia da faixa de duvida compara a batida com a galeria do
modelo de confirmacao. Sem esses vetores ela nao tem com o que comparar
e se abstem — o reconhecimento volta a decidir com um modelo so,
exatamente na faixa onde ele decide pior.

Roda sobre as fotos guardadas, entao ninguem precisa voltar para a
frente da camera.

    python manage.py gerar_confirmacao            # so relata
    python manage.py gerar_confirmacao --confirmar
"""
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Gera os embeddings do modelo de confirmação para cadastros existentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Sem isto, apenas mostra quantos seriam calculados.",
        )
        parser.add_argument(
            "--empresa", default=None, help="Limita a uma empresa (id)."
        )

    def handle(self, *args, **opcoes):
        from apps.facial.models import FaceRegistro
        from apps.facial.providers import obter_provedor_confirmacao
        from apps.facial.services import FaceRecognitionService

        modelo = settings.FACE_MODELO_CONFIRMACAO
        amostras = FaceRegistro.objects.filter(ativo=True).select_related(
            "colaborador"
        )
        if opcoes["empresa"]:
            amostras = amostras.filter(
                colaborador__empresa_id=int(opcoes["empresa"])
            )

        faltando = [a for a in amostras if not a.embedding_confirmacao]
        sem_foto = [a for a in faltando if not a.imagem]
        refazer = [a for a in faltando if a.imagem]

        self.stdout.write(f"Modelo de confirmação : {modelo}")
        self.stdout.write(f"Amostras ativas       : {amostras.count()}")
        self.stdout.write(f"Sem vetor do 2º modelo: {len(faltando)}")
        if sem_foto:
            nomes = sorted({a.colaborador.nome_exibicao for a in sem_foto})
            self.stdout.write(self.style.WARNING(
                "  Sem foto guardada, precisam recadastrar: " + ", ".join(nomes)
            ))

        if not refazer:
            self.stdout.write(self.style.SUCCESS("\nNada a calcular."))
            return

        if not opcoes["confirmar"]:
            self.stdout.write(self.style.WARNING(
                f"\n{len(refazer)} amostra(s) seriam calculadas. "
                "Repita com --confirmar."
            ))
            return

        provedor = obter_provedor_confirmacao()
        if not provedor.disponivel:
            self.stdout.write(self.style.ERROR(
                f"Os pesos do modelo {modelo} não estão disponíveis neste "
                "servidor. Sem eles a conferência não roda."
            ))
            return

        feitas, falhas = 0, []
        tocados = set()
        for amostra in refazer:
            try:
                amostra.imagem.open("rb")
                dados = amostra.imagem.read()
                amostra.imagem.close()
                amostra.definir_embedding_confirmacao(
                    provedor.gerar_embedding(dados)
                )
                feitas += 1
                tocados.add(amostra.colaborador)
            except Exception as erro:
                falhas.append((amostra, f"{type(erro).__name__}: {erro}"))

        # O cache guarda a galeria pronta; sem invalidar, a conferencia
        # so passaria a valer no proximo vencimento.
        for colaborador in tocados:
            FaceRecognitionService.invalidar_cache(colaborador.empresa_id)

        self.stdout.write(self.style.SUCCESS(
            f"\n{feitas} amostra(s) calculada(s) em {len(tocados)} "
            f"colaborador(es)."
        ))
        for amostra, motivo in falhas:
            self.stdout.write(self.style.ERROR(
                f"  falhou: {amostra.colaborador.nome_exibicao} "
                f"({amostra.angulo}) — {motivo}"
            ))
        if falhas:
            self.stdout.write(self.style.WARNING(
                "As que falharam ficam sem conferência: nessas, a faixa de "
                "dúvida volta a decidir com um modelo só."
            ))
