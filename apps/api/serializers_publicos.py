"""
Kronus — serializers da API REST pública (Seção 7.2 do plano).

Estes serializers alimentam integrações externas: ERPs, sistemas de
folha, BI. Duas regras atravessam todos eles:

1. **Nada de dado sensível sem necessidade.** O CPF sai completo (a
   folha precisa dele), mas o embedding facial nunca sai — é dado
   biométrico, e a API não tem finalidade que o justifique.

2. **Minutos, não strings de hora.** A API entrega `minutos_trabalhados:
   480` e também `horas_trabalhadas: "08:00"`. O número é para calcular;
   a string é para exibir. Entregar só a string obrigaria cada
   integração a reparsear.
"""
from rest_framework import serializers

from apps.core.utils import formatar_cpf, minutos_para_hhmm
from apps.ponto.models import BancoHoras, EscalaTrabalho, RegistroPonto
from apps.rh.models import Atestado, Cargo, Colaborador, Departamento


class EmpresaResumoSerializer(serializers.Serializer):
    """Identificação da empresa embutida nos recursos."""

    uuid = serializers.UUIDField(read_only=True)
    razao_social = serializers.CharField(read_only=True)
    nome_fantasia = serializers.CharField(read_only=True)
    cnpj = serializers.CharField(read_only=True)


# ══════════════════════════════════════════════════════════════
# Estrutura organizacional
# ══════════════════════════════════════════════════════════════
class DepartamentoSerializer(serializers.ModelSerializer):
    empresa = serializers.UUIDField(source="empresa.uuid", read_only=True)
    total_colaboradores = serializers.IntegerField(
        source="colaboradores_ativos", read_only=True
    )

    class Meta:
        model = Departamento
        fields = (
            "uuid", "empresa", "nome", "descricao", "centro_custo",
            "ativo", "total_colaboradores", "created_at", "updated_at",
        )
        read_only_fields = fields


class CargoSerializer(serializers.ModelSerializer):
    empresa = serializers.UUIDField(source="empresa.uuid", read_only=True)

    class Meta:
        model = Cargo
        fields = (
            "uuid", "empresa", "nome", "cbo", "descricao",
            "salario_base", "ativo", "created_at", "updated_at",
        )
        read_only_fields = fields


class EscalaSerializer(serializers.ModelSerializer):
    empresa = serializers.UUIDField(source="empresa.uuid", read_only=True)
    tipo_exibicao = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = EscalaTrabalho
        fields = (
            "uuid", "empresa", "nome", "descricao", "tipo", "tipo_exibicao",
            "tolerancia_min", "carga_diaria_min", "carga_semanal_min",
            "exige_intervalo", "intervalo_min", "jornada_config",
            "data_referencia", "ativa", "created_at", "updated_at",
        )
        read_only_fields = fields


# ══════════════════════════════════════════════════════════════
# Colaboradores
# ══════════════════════════════════════════════════════════════
class ColaboradorSerializer(serializers.ModelSerializer):
    """
    Dados cadastrais do colaborador.

    `face_registrada` diz *se* há biometria; o vetor em si nunca é
    exposto. Não há finalidade legítima para uma integração externa
    receber dado biométrico (LGPD, Art. 11).
    """

    empresa = serializers.UUIDField(source="empresa.uuid", read_only=True)
    cpf_formatado = serializers.SerializerMethodField()
    departamento = serializers.CharField(source="departamento.nome", read_only=True, default=None)
    departamento_uuid = serializers.UUIDField(source="departamento.uuid", read_only=True, default=None)
    escala = serializers.CharField(source="escala.nome", read_only=True, default=None)
    escala_uuid = serializers.UUIDField(source="escala.uuid", read_only=True, default=None)

    class Meta:
        model = Colaborador
        fields = (
            "uuid", "empresa", "cpf", "cpf_formatado", "nome_completo", "nome_social",
            "data_nascimento", "email", "telefone", "matricula", "cargo",
            "departamento", "departamento_uuid", "escala", "escala_uuid",
            "data_admissao", "data_demissao", "ativo",
            "pis_pasep", "ctps", "ctps_serie",
            "face_registrada", "permite_ponto_web",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_cpf_formatado(self, obj) -> str:
        return formatar_cpf(obj.cpf)


# ══════════════════════════════════════════════════════════════
# Registros de ponto
# ══════════════════════════════════════════════════════════════
class RegistroPontoSerializer(serializers.ModelSerializer):
    """
    Uma marcação de ponto, com as evidências que sustentam a Portaria 671.

    `hash_registro` e `nsr` saem completos: são o que permite a uma
    auditoria externa reconferir a integridade sem acesso ao banco.
    """

    empresa = serializers.UUIDField(source="empresa.uuid", read_only=True)
    colaborador = serializers.UUIDField(source="colaborador.uuid", read_only=True)
    colaborador_cpf = serializers.CharField(source="colaborador.cpf", read_only=True)
    colaborador_nome = serializers.CharField(source="colaborador.nome_exibicao", read_only=True)
    tipo_exibicao = serializers.CharField(source="get_tipo_display", read_only=True)
    metodo_exibicao = serializers.CharField(source="get_metodo_display", read_only=True)
    totem = serializers.CharField(source="totem.identificador", read_only=True, default=None)
    codigo_verificacao = serializers.CharField(read_only=True)

    class Meta:
        model = RegistroPonto
        fields = (
            "uuid", "empresa", "colaborador", "colaborador_cpf", "colaborador_nome",
            "data_hora", "tipo", "tipo_exibicao", "metodo", "metodo_exibicao",
            "nsr", "hash_registro", "hash_anterior", "codigo_verificacao",
            "latitude", "longitude", "precisao_gps", "fora_area", "suspeita_fraude",
            "totem", "confianca_face", "cancelado", "observacao",
            "created_at",
        )
        read_only_fields = fields


class RegistrarPontoSerializer(serializers.Serializer):
    """
    Entrada do registro via API (`POST /pontos/registrar/`).

    O `colaborador` vem por UUID, nunca por id sequencial: expor ids
    incrementais numa API pública permite enumerar a base.
    """

    colaborador = serializers.UUIDField(
        help_text="UUID do colaborador (não o id sequencial)."
    )
    tipo = serializers.ChoiceField(
        choices=[
            ("entrada", "Entrada"),
            ("intervalo_inicio", "Saída para intervalo"),
            ("intervalo_fim", "Retorno do intervalo"),
            ("saida", "Saída"),
        ],
        required=False,
        help_text="Omitido, o sistema deduz pela sequência do dia.",
    )
    data_hora = serializers.DateTimeField(
        required=False,
        help_text="Omitido, usa o instante da requisição. Não aceita futuro.",
    )
    latitude = serializers.DecimalField(
        max_digits=10, decimal_places=7, required=False, allow_null=True
    )
    longitude = serializers.DecimalField(
        max_digits=10, decimal_places=7, required=False, allow_null=True
    )
    observacao = serializers.CharField(required=False, allow_blank=True, max_length=255)


# ══════════════════════════════════════════════════════════════
# Banco de horas
# ══════════════════════════════════════════════════════════════
class BancoHorasSerializer(serializers.ModelSerializer):
    """
    Apuração de um dia.

    Cada total sai em minutos (para cálculo) e em HH:MM (para exibição).
    """

    colaborador = serializers.UUIDField(source="colaborador.uuid", read_only=True)
    colaborador_cpf = serializers.CharField(source="colaborador.cpf", read_only=True)
    colaborador_nome = serializers.CharField(source="colaborador.nome_exibicao", read_only=True)
    status_exibicao = serializers.CharField(source="get_status_display", read_only=True)

    horas_trabalhadas = serializers.SerializerMethodField()
    horas_esperadas = serializers.SerializerMethodField()
    horas_extras = serializers.SerializerMethodField()
    horas_noturnas = serializers.SerializerMethodField()
    saldo = serializers.SerializerMethodField()
    saldo_acumulado_formatado = serializers.SerializerMethodField()

    class Meta:
        model = BancoHoras
        fields = (
            "uuid", "colaborador", "colaborador_cpf", "colaborador_nome", "data",
            "minutos_trabalhados", "horas_trabalhadas",
            "minutos_esperados", "horas_esperadas",
            "minutos_extras", "horas_extras",
            "minutos_noturnos", "horas_noturnas",
            "minutos_intervalo", "minutos_atraso", "minutos_saida_antecipada",
            "saldo_dia", "saldo", "saldo_acumulado", "saldo_acumulado_formatado",
            "status", "status_exibicao", "compensado", "fechado", "observacao",
        )
        read_only_fields = fields

    def get_horas_trabalhadas(self, obj) -> str:
        return minutos_para_hhmm(obj.minutos_trabalhados, com_sinal=False)

    def get_horas_esperadas(self, obj) -> str:
        return minutos_para_hhmm(obj.minutos_esperados, com_sinal=False)

    def get_horas_extras(self, obj) -> str:
        return minutos_para_hhmm(obj.minutos_extras, com_sinal=False)

    def get_horas_noturnas(self, obj) -> str:
        return minutos_para_hhmm(obj.minutos_noturnos, com_sinal=False)

    def get_saldo(self, obj) -> str:
        return minutos_para_hhmm(obj.saldo_dia)

    def get_saldo_acumulado_formatado(self, obj) -> str:
        return minutos_para_hhmm(obj.saldo_acumulado)


class ResumoBancoHorasSerializer(serializers.Serializer):
    """Totais de um colaborador num período."""

    colaborador = serializers.UUIDField()
    colaborador_cpf = serializers.CharField()
    colaborador_nome = serializers.CharField()
    data_inicio = serializers.DateField()
    data_fim = serializers.DateField()
    minutos_trabalhados = serializers.IntegerField()
    minutos_esperados = serializers.IntegerField()
    minutos_extras = serializers.IntegerField()
    minutos_noturnos = serializers.IntegerField()
    minutos_atraso = serializers.IntegerField()
    saldo_anterior = serializers.IntegerField()
    saldo_periodo = serializers.IntegerField()
    saldo_final = serializers.IntegerField()
    saldo_final_formatado = serializers.CharField()
    dias_falta = serializers.IntegerField()
    dias_atestado = serializers.IntegerField()
    dias_incompletos = serializers.IntegerField()


# ══════════════════════════════════════════════════════════════
# Atestados
# ══════════════════════════════════════════════════════════════
class AtestadoSerializer(serializers.ModelSerializer):
    """
    Atestado médico.

    O **CID não é exposto** na API: é dado de saúde (LGPD, Art. 5º, II),
    e nenhuma integração de folha precisa dele para calcular o abono.
    O que importa lá fora é o período e o status.
    """

    colaborador = serializers.UUIDField(source="colaborador.uuid", read_only=True)
    colaborador_cpf = serializers.CharField(source="colaborador.cpf", read_only=True)
    colaborador_nome = serializers.CharField(source="colaborador.nome_exibicao", read_only=True)
    status_exibicao = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Atestado
        fields = (
            "uuid", "colaborador", "colaborador_cpf", "colaborador_nome",
            "data_inicio", "data_fim", "dias",
            "status", "status_exibicao", "avaliado_em",
            "created_at", "updated_at",
        )
        read_only_fields = fields


# ══════════════════════════════════════════════════════════════
# Espelho de ponto (resposta do endpoint de relatório)
# ══════════════════════════════════════════════════════════════
class MarcacaoEspelhoSerializer(serializers.Serializer):
    hora = serializers.CharField()
    nsr = serializers.IntegerField()


class LinhaEspelhoSerializer(serializers.Serializer):
    data = serializers.DateField()
    dia_semana = serializers.CharField()
    marcacoes = MarcacaoEspelhoSerializer(many=True)
    minutos_trabalhados = serializers.IntegerField()
    minutos_esperados = serializers.IntegerField()
    minutos_extras = serializers.IntegerField()
    minutos_noturnos = serializers.IntegerField()
    saldo_minutos = serializers.IntegerField()
    saldo = serializers.CharField()
    status = serializers.CharField(allow_blank=True)
    observacao = serializers.CharField(allow_blank=True)


class EspelhoSerializer(serializers.Serializer):
    """
    Contrato do `GET /relatorios/espelho/`.

    Declarado explicitamente porque a view é um `APIView` que monta o
    dicionário à mão — sem isto o endpoint sairia do schema, e uma
    integração não teria como saber o formato sem chamar em produção.
    """

    colaborador = serializers.DictField()
    ano = serializers.IntegerField()
    mes = serializers.IntegerField()
    hash_documento = serializers.CharField()
    codigo_verificacao = serializers.CharField()
    totais = serializers.DictField()
    resumo = serializers.DictField()
    linhas = LinhaEspelhoSerializer(many=True)


class ContaSerializer(serializers.Serializer):
    """Contrato do `GET /conta/` — identificação da credencial."""

    credencial = serializers.DictField()
    cliente = serializers.DictField()
    plano = serializers.DictField()
    limite_hora = serializers.IntegerField()
    empresas = serializers.ListField(child=serializers.DictField())


class VerificacaoHashSerializer(serializers.Serializer):
    """Contrato do `GET /pontos/{uuid}/verificar/`."""

    uuid = serializers.UUIDField()
    nsr = serializers.IntegerField()
    hash_gravado = serializers.CharField()
    hash_recalculado = serializers.CharField()
    integro = serializers.BooleanField()
    mensagem = serializers.CharField()
