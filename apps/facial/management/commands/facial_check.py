"""
Kronus — diagnóstico do motor de reconhecimento facial.

O DeepFace instala **sem** os pesos do modelo e tenta baixá-los na
primeira chamada. Num servidor de produção sem saída para a internet,
isso transformaria a primeira batida do dia em erro. Este comando
verifica — e opcionalmente pré-carrega — tudo antes do deploy.

    python manage.py facial_check
    python manage.py facial_check --baixar
    python manage.py facial_check --testar
"""
import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.facial.providers import (
    ARQUIVOS_DE_PESO,
    DeepFaceProvider,
    diretorio_pesos,
    obter_provedor,
)


class Command(BaseCommand):
    help = "Verifica a disponibilidade do motor de reconhecimento facial."

    def add_arguments(self, parser):
        parser.add_argument(
            "--baixar",
            action="store_true",
            help="Baixa os pesos do modelo (exige acesso à internet).",
        )
        parser.add_argument(
            "--testar",
            action="store_true",
            help="Gera um embedding de teste para medir o tempo de resposta.",
        )
        parser.add_argument("--json", action="store_true", help="Saída em JSON.")

    def handle(self, *args, **opcoes):
        provedor = DeepFaceProvider()
        saude = provedor.verificar_saude()
        saude["provider_configurado"] = settings.FACE_PROVIDER
        saude["provider_efetivo"] = obter_provedor().nome
        saude["threshold"] = settings.FACE_RECOGNITION_THRESHOLD

        if opcoes["baixar"] and not saude["pesos_presentes"]:
            saude["download"] = self._baixar(provedor)
            saude.update(provedor.verificar_saude())

        if opcoes["testar"] and provedor.disponivel:
            saude["teste"] = self._testar(provedor)

        if opcoes["json"]:
            self.stdout.write(json.dumps(saude, indent=2, ensure_ascii=False))
            return

        self._relatar(saude)

    # -- ações -------------------------------------------------
    def _baixar(self, provedor):
        self.stdout.write(f"Baixando os pesos do modelo {provedor.modelo}...")
        try:
            from deepface import DeepFace

            inicio = time.perf_counter()
            DeepFace.build_model(provedor.modelo)
            return {"ok": True, "segundos": round(time.perf_counter() - inicio, 1)}
        except Exception as erro:
            self.stderr.write(self.style.ERROR(f"Falha no download: {erro}"))
            self.stdout.write(
                "\nAlternativa manual:\n"
                f"  1. baixe {ARQUIVOS_DE_PESO.get(provedor.modelo)} de\n"
                "     https://github.com/serengil/deepface_models/releases\n"
                f"  2. copie para {diretorio_pesos()}\n"
            )
            return {"ok": False, "erro": str(erro)}

    def _testar(self, provedor):
        import io

        from PIL import Image, ImageDraw

        imagem = Image.new("RGB", (224, 224), (222, 200, 180))
        desenho = ImageDraw.Draw(imagem)
        desenho.ellipse([52, 32, 172, 192], fill=(236, 210, 190))
        buffer = io.BytesIO()
        imagem.save(buffer, format="JPEG")

        inicio = time.perf_counter()
        try:
            vetor = provedor.gerar_embedding(buffer.getvalue())
            return {
                "ok": True,
                "dimensoes": int(vetor.shape[0]),
                "ms": int((time.perf_counter() - inicio) * 1000),
            }
        except Exception as erro:
            # Recusar uma imagem sintetica e o comportamento correto do
            # detector: significa que ele esta funcionando.
            return {"ok": False, "detalhe": str(erro)[:160], "ms": int((time.perf_counter() - inicio) * 1000)}

    # -- relatório ---------------------------------------------
    def _relatar(self, saude):
        marca = self.style.SUCCESS("OK") if saude["disponivel"] else self.style.ERROR("INDISPONIVEL")
        self.stdout.write(self.style.MIGRATE_HEADING("\nKronus - motor de reconhecimento facial"))
        self.stdout.write(f"  Status ................ {marca}")
        self.stdout.write(f"  Provider configurado .. {saude['provider_configurado']}")
        self.stdout.write(f"  Provider efetivo ...... {saude['provider_efetivo']}")
        self.stdout.write(f"  Modelo ................ {saude['modelo']}")
        self.stdout.write(f"  Detector .............. {saude['detector']}")
        self.stdout.write(f"  Threshold ............. {saude['threshold']}")
        self.stdout.write(f"  Biblioteca importavel . {saude['biblioteca_importavel']}")
        self.stdout.write(f"  Pesos presentes ....... {saude['pesos_presentes']}")
        self.stdout.write(f"  Pesos em .............. {saude['pesos_esperados_em']}")
        if saude["pesos_presentes"]:
            self.stdout.write(f"  Tamanho ............... {saude['pesos_bytes'] / 1e6:.1f} MB")
        if "teste" in saude:
            t = saude["teste"]
            self.stdout.write(f"  Teste de embedding .... {t}")

        if not saude["disponivel"]:
            self.stdout.write(
                self.style.WARNING(
                    "\n  O reconhecimento facial responde com erro explicito ate ser habilitado."
                )
            )
            if not saude["biblioteca_importavel"]:
                self.stdout.write("  Instale a stack: pip install -r requirements.txt")
            elif not saude["pesos_presentes"]:
                self.stdout.write("  Baixe os pesos:  manage.py facial_check --baixar")
        self.stdout.write("")
