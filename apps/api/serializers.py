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
    quadros = serializers.ListField(
        child=serializers.CharField(trim_whitespace=True),
        required=False,
        allow_empty=True,
        max_length=8,
        write_only=True,
        help_text=(
            "Sequência de quadros para a prova de vida, em base64. "
            "O último é o usado no reconhecimento."
        ),
    )
    desafio = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Gesto pedido ao colaborador, devolvido para conferência.",
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

    # Por que o equipamento avisa que esta degradado em vez de so o
    # console do navegador saber: um totem sem detector de rosto continua
    # de pe, bonito e aceitando CPF — e ninguem descobre que o
    # reconhecimento morreu ate o RH reclamar. O suporte precisa ver isso
    # do painel, sem ir ate o tablet.
    degradado = serializers.CharField(
        required=False, allow_blank=True, max_length=200
    )


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

        # Slides vigentes hoje. O `idle_screen_img` antigo entra como
        # primeiro slide quando ainda existe, para que quem ja usava a
        # imagem unica nao perca a configuracao.
        slides = [
            {"url": slide.imagem.url, "legenda": slide.legenda}
            for slide in empresa.slides.order_by("ordem", "created_at")
            if slide.vigente
        ]
        if not slides and empresa.idle_screen_img:
            slides = [{"url": empresa.idle_screen_img.url, "legenda": ""}]

        return {
            "nome": empresa.nome_exibicao,
            "logo": empresa.logo.url if empresa.logo else None,
            "logo_altura_px": empresa.logo_altura_px,
            "logo_deslocamento_px": empresa.logo_deslocamento_px,
            # Ja resolvido para a tela do totem: o JS nao precisa
            # saber quais opcoes existem nem em que ordem aplicar.
            "logo_css": empresa.css_da_logo("totem"),
            "slogan": empresa.slogan_totem,
            "assinatura_altura_px": empresa.assinatura_altura_px,
            "msg_boas_vindas_px": empresa.msg_boas_vindas_px,
            "slogan_px": empresa.slogan_px,
            "msg_sucesso_px": empresa.msg_sucesso_px,
            "tentativas_antes_do_cpf": empresa.tentativas_antes_do_cpf,
            # Mantido por compatibilidade com totens que ainda nao
            # atualizaram o app.
            "idle_screen": slides[0]["url"] if slides else None,
            "slides": slides,
            "slides_transicao": empresa.slides_transicao,
            "slides_segundos": empresa.slides_segundos,
            "mensagem_boas_vindas": empresa.msg_boas_vindas,
            "mensagem_sucesso": empresa.msg_sucesso_ponto,
            "som_confirmacao": empresa.som_confirmacao,
            "cor_primaria": empresa.cor_primaria,
            "cor_secundaria": empresa.cor_secundaria,
            "fuso_horario": empresa.fuso_horario,
        }

    def get_interface(self, totem):
        config = totem.empresa.configuracao
        return {
            "permite_fallback_cpf": totem.permite_fallback_cpf,
            "segundos_tela_sucesso": totem.segundos_tela_sucesso,
            "segundos_countdown_offline": totem.segundos_countdown_offline,
            "liveness": config.exigir_liveness,
            # Quantos quadros o totem deve enviar quando a prova de vida
            # esta ligada. Vem do servidor para que ajustar a exigencia
            # nao dependa de republicar o app do quiosque.
            "liveness_quadros": 4 if config.exigir_liveness else 0,
            "minutos_entre_marcacoes": config.minutos_entre_marcacoes,
            # O totem so mostra a porta de manutencao quando ela existe.
            # Um caminho que aparece e recusa ensina que ele esta ali.
            "cadastro_facial_no_totem": (
                totem.empresa.cliente.cadastro_no_totem_disponivel
            ),
        }


# ══════════════════════════════════════════════════════════════
# Manutencao no totem — cadastro facial no proprio equipamento
# ══════════════════════════════════════════════════════════════
class EntrarManutencaoSerializer(serializers.Serializer):
    """Senha de manutencao digitada na tela do totem."""

    senha = serializers.CharField(max_length=128, trim_whitespace=False)


class ConsentimentoTotemSerializer(serializers.Serializer):
    """Consentimento LGPD colhido no proprio totem."""

    colaborador_id = serializers.IntegerField()
    # Caixa marcada na tela. Exigida como `True` — um consentimento que
    # aceita `False` nao e consentimento, e o registro ficaria mentindo.
    aceite = serializers.BooleanField()


class AmostraTotemSerializer(serializers.Serializer):
    """Captura facial feita no totem, em modo de manutencao."""

    colaborador_id = serializers.IntegerField()
    imagem = serializers.CharField()
    angulo = serializers.CharField(max_length=20, required=False, allow_blank=True)
