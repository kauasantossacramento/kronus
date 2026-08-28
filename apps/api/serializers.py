"""Kronus — serializers da API REST."""
from rest_framework import serializers

from apps.core.utils import apenas_digitos, cpf_valido, mascarar_cpf


# ══════════════════════════════════════════════════════════════
# Totem — entrada
# ══════════════════════════════════════════════════════════════
class ReconhecimentoSerializer(serializers.Serializer):
    """Frame enviado pelo totem para identificação facial."""

    image = serializers.CharField(
        help_text="JPEG em base64, com ou sem o prefixo data URI.",
        write_only=True,
        trim_whitespace=True,
    )
    totem_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Identificador do equipamento. Informativo — o escopo real vem do token.",
    )
    registrar_ponto = serializers.BooleanField(
        default=True,
        help_text="Quando falso, apenas identifica sem gravar a batida.",
    )


class PunchCPFSerializer(serializers.Serializer):
    """
    Fallback do totem: CPF + data de nascimento.

    A data de nascimento é o segundo fator — sem ela, conhecer o CPF de
    um colega bastaria para bater o ponto no lugar dele.
    """

    cpf = serializers.CharField(max_length=14)
    data_nascimento = serializers.DateField(
        input_formats=["%Y-%m-%d", "%d/%m/%Y", "%d%m%Y"]
    )
    totem_id = serializers.CharField(required=False, allow_blank=True)

    def validate_cpf(self, valor):
        digitos = apenas_digitos(valor)
        if not cpf_valido(digitos):
            raise serializers.ValidationError("CPF inválido.")
        return digitos


class HeartbeatSerializer(serializers.Serializer):
    """Sinal de vida do equipamento, a cada 30 segundos."""

    versao = serializers.CharField(required=False, allow_blank=True, max_length=20)
    bateria = serializers.IntegerField(required=False, min_value=0, max_value=100)
    registros_pendentes = serializers.IntegerField(required=False, min_value=0)


# ══════════════════════════════════════════════════════════════
# Totem — saída
# ══════════════════════════════════════════════════════════════
class ColaboradorTotemSerializer(serializers.Serializer):
    """
    Dados exibidos na tela de sucesso do totem.

    O CPF sai **mascarado**: a tela fica visível a quem estiver na fila,
    e o documento completo não precisa aparecer ali (Seção 6.5.1).
    """

    nome = serializers.CharField(source="nome_exibicao")
    primeiro_nome = serializers.CharField()
    cpf_mascarado = serializers.SerializerMethodField()
    foto = serializers.SerializerMethodField()
    matricula = serializers.CharField(allow_blank=True)

    def get_cpf_mascarado(self, obj):
        return mascarar_cpf(obj.cpf)

    def get_foto(self, obj):
        if obj.foto_perfil:
            return obj.foto_perfil.url
        return None


class RegistroTotemSerializer(serializers.Serializer):
    """Confirmação da batida devolvida ao totem."""

    nsr = serializers.IntegerField()
    tipo = serializers.CharField()
    tipo_exibicao = serializers.CharField(source="get_tipo_display")
    hora = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()
    codigo_verificacao = serializers.CharField()

    def get_hora(self, obj):
        from django.utils import timezone

        return timezone.localtime(obj.data_hora).strftime("%H:%M:%S")

    def get_data(self, obj):
        from django.utils import timezone

        return timezone.localtime(obj.data_hora).strftime("%d/%m/%Y")


class ConfigTotemSerializer(serializers.Serializer):
    """
    Configuração que o totem busca ao iniciar (Seção 7.3).

    Traz a identidade visual da empresa e os parâmetros de interface —
    é o que permite personalizar o quiosque sem republicar o app.
    """

    identificador = serializers.CharField()
    empresa = serializers.SerializerMethodField()
    interface = serializers.SerializerMethodField()

    def get_empresa(self, totem):
        empresa = totem.empresa
        return {
            "nome": empresa.nome_exibicao,
            "logo": empresa.logo.url if empresa.logo else None,
            "idle_screen": (
                empresa.idle_screen_img.url if empresa.idle_screen_img else None
            ),
            "mensagem_boas_vindas": empresa.msg_boas_vindas,
            "cor_primaria": empresa.cor_primaria,
            "cor_secundaria": empresa.cor_secundaria,
            "fuso_horario": empresa.fuso_horario,
        }

    def get_interface(self, totem):
        return {
            "permite_fallback_cpf": totem.permite_fallback_cpf,
            "segundos_tela_sucesso": totem.segundos_tela_sucesso,
            "segundos_countdown_offline": totem.segundos_countdown_offline,
            "liveness": totem.empresa.configuracao.liveness_no_totem,
        }
