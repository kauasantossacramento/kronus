"""
Kronus — cadastro biometrico facial.

Cada `FaceRegistro` guarda uma foto do cadastro e o embedding gerado a
partir dela. O embedding **medio** dos registros ativos fica em
`rh.Colaborador.face_embedding` (Secao 8.2 do plano).

LGPD (Secao 10): dados biometricos sao sensiveis. O embedding e um vetor
numerico nao reversivel para imagem; as fotos originais podem ser
descartadas apos o encoding conforme configuracao da empresa.
"""
import numpy as np
from django.db import models

from apps.core.models import BaseModel


class FaceRegistro(BaseModel):
    """Uma amostra facial do colaborador."""

    class Angulo(models.TextChoices):
        FRONTAL = "frontal", "Frontal"
        ESQUERDA = "esquerda", "Perfil esquerdo"
        DIREITA = "direita", "Perfil direito"
        CIMA = "cima", "Levemente acima"
        BAIXO = "baixo", "Levemente abaixo"

    colaborador = models.ForeignKey(
        "rh.Colaborador",
        on_delete=models.CASCADE,
        related_name="registros_faciais",
        verbose_name="Colaborador",
    )
    imagem = models.ImageField(
        "Imagem", upload_to="faces/amostras/%Y/%m/", null=True, blank=True
    )
    embedding = models.BinaryField(
        "Embedding", null=True, blank=True, editable=False,
        help_text="Vetor ArcFace (512 dims) serializado com numpy.tobytes()."
    )
    angulo = models.CharField(
        "Ângulo", max_length=10, choices=Angulo.choices, default=Angulo.FRONTAL
    )
    modelo = models.CharField("Modelo", max_length=30, default="ArcFace")
    detector = models.CharField("Detector", max_length=30, default="retinaface")
    qualidade = models.FloatField(
        "Qualidade da amostra", null=True, blank=True,
        help_text="Score de nitidez/enquadramento calculado no pré-processamento."
    )
    ativo = models.BooleanField("Ativo", default=True, db_index=True)

    class Meta:
        verbose_name = "Registro facial"
        verbose_name_plural = "Registros faciais"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["colaborador", "ativo"])]

    def __str__(self):
        return f"{self.colaborador.nome_exibicao} — {self.get_angulo_display()}"

    def obter_embedding(self):
        if not self.embedding:
            return None
        return np.frombuffer(bytes(self.embedding), dtype=np.float32)

    def definir_embedding(self, vetor, salvar: bool = True):
        vetor = np.asarray(vetor, dtype=np.float32)
        self.embedding = vetor.tobytes()
        if salvar:
            self.save(update_fields=["embedding", "updated_at"])


class TentativaReconhecimento(BaseModel):
    """
    Registro de cada tentativa de reconhecimento no totem.

    Serve a tres propositos: metrica de qualidade do modelo, auditoria
    antifraude e diagnostico de suporte.
    """

    class Resultado(models.TextChoices):
        IDENTIFICADO = "identificado", "Identificado"
        NAO_IDENTIFICADO = "nao_identificado", "Não identificado"
        SEM_ROSTO = "sem_rosto", "Nenhum rosto detectado"
        MULTIPLOS_ROSTOS = "multiplos_rostos", "Múltiplos rostos"
        ERRO = "erro", "Erro no processamento"
        LIVENESS_FALHA = "liveness_falha", "Falha na prova de vida"

    totem = models.ForeignKey(
        "totem.Totem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tentativas_reconhecimento",
        verbose_name="Totem",
    )
    empresa = models.ForeignKey(
        "clientes.Empresa",
        on_delete=models.CASCADE,
        related_name="tentativas_reconhecimento",
        verbose_name="Empresa",
    )
    colaborador = models.ForeignKey(
        "rh.Colaborador",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tentativas_reconhecimento",
        verbose_name="Colaborador identificado",
    )
    resultado = models.CharField(
        "Resultado", max_length=20, choices=Resultado.choices, db_index=True
    )
    distancia = models.FloatField(
        "Distância cosseno", null=True, blank=True,
        help_text="Abaixo do threshold configurado indica correspondência."
    )
    confianca = models.FloatField("Confiança (%)", null=True, blank=True)
    tempo_processamento_ms = models.PositiveIntegerField(
        "Tempo de processamento (ms)", null=True, blank=True
    )
    candidatos_avaliados = models.PositiveIntegerField("Candidatos avaliados", default=0)
    imagem = models.ImageField(
        "Frame recebido", upload_to="faces/tentativas/%Y/%m/", null=True, blank=True
    )
    ip = models.GenericIPAddressField("IP", null=True, blank=True)

    class Meta:
        verbose_name = "Tentativa de reconhecimento"
        verbose_name_plural = "Tentativas de reconhecimento"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["empresa", "-created_at"]),
            models.Index(fields=["totem", "-created_at"]),
            models.Index(fields=["resultado", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_resultado_display()} — {self.created_at:%d/%m/%Y %H:%M:%S}"
