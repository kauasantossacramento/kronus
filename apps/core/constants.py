"""
Kronus — enumeracoes compartilhadas.

Ficam aqui (e nao nos apps de dominio) para evitar importacoes circulares:
`core` e importado por todos os demais apps.
"""
from django.db import models


class TipoUsuario(models.TextChoices):
    """Papeis da arquitetura multi-tenant hierarquica (Secao 1.5 do plano)."""

    MASTER = "master", "Master (KS TEC)"
    CLIENTE = "cliente", "Administrador do Cliente"
    RH = "rh", "Administrador RH"
    COLABORADOR = "colaborador", "Colaborador"
    CONTADOR = "contador", "Contador"  # Portal do contador (Secao 8.8)


class TipoRegistro(models.TextChoices):
    """Tipos de batida de ponto."""

    ENTRADA = "entrada", "Entrada"
    INTERVALO_INICIO = "intervalo_inicio", "Saída para intervalo"
    INTERVALO_FIM = "intervalo_fim", "Retorno do intervalo"
    SAIDA = "saida", "Saída"


#: Sequencia canonica de batidas em uma jornada com intervalo.
SEQUENCIA_JORNADA = [
    TipoRegistro.ENTRADA,
    TipoRegistro.INTERVALO_INICIO,
    TipoRegistro.INTERVALO_FIM,
    TipoRegistro.SAIDA,
]


class MetodoRegistro(models.TextChoices):
    """Como a batida chegou ao sistema."""

    FACIAL = "facial", "Reconhecimento facial (totem)"
    WEB = "web", "Web (navegador)"
    CPF = "cpf", "CPF + data de nascimento (totem)"
    API = "api", "API REST"
    MANUAL = "manual", "Ajuste manual (RH)"
    IMPORTACAO = "importacao", "Importação de arquivo"


class StatusDia(models.TextChoices):
    """Status consolidado de um dia no espelho de ponto."""

    COMPLETO = "completo", "Completo"
    INCOMPLETO = "incompleto", "Incompleto"
    FALTA = "falta", "Falta"
    JUSTIFICADO = "justificado", "Justificado"
    ATESTADO = "atestado", "Atestado médico"
    FOLGA = "folga", "Folga / DSR"
    FERIADO = "feriado", "Feriado"
    FERIAS = "ferias", "Férias"
    AFASTAMENTO = "afastamento", "Afastamento"


class TipoEscala(models.TextChoices):
    """Modelos de jornada suportados (Secao 8.8)."""

    FIXA = "fixa", "Fixa"
    FLEXIVEL = "flexivel", "Flexível"
    ESCALA_12X36 = "12x36", "12x36"
    ESCALA_6X1 = "6x1", "6x1"
    ESCALA_5X2 = "5x2", "5x2"
    PLANTAO = "plantao", "Plantão"
    CUSTOMIZADA = "customizada", "Customizada"


class StatusAprovacao(models.TextChoices):
    PENDENTE = "pendente", "Pendente"
    APROVADO = "aprovado", "Aprovado"
    REJEITADO = "rejeitado", "Rejeitado"


class TipoJustificativa(models.TextChoices):
    FALTA = "falta", "Falta"
    ATRASO = "atraso", "Atraso"
    SAIDA_ANTECIPADA = "saida_antecipada", "Saída antecipada"
    ESQUECIMENTO = "esquecimento", "Esquecimento de batida"
    INTERVALO = "intervalo", "Intervalo irregular"
    OUTRO = "outro", "Outro"


class TipoAfastamento(models.TextChoices):
    FERIAS = "ferias", "Férias"
    LICENCA_MATERNIDADE = "licenca_maternidade", "Licença-maternidade"
    LICENCA_PATERNIDADE = "licenca_paternidade", "Licença-paternidade"
    INSS = "inss", "Afastamento INSS"
    LICENCA_NAO_REMUNERADA = "licenca_nao_remunerada", "Licença não remunerada"
    SUSPENSAO = "suspensao", "Suspensão"
    OUTRO = "outro", "Outro"


class ModoCompensacao(models.TextChoices):
    """Como o saldo do banco de horas e tratado (Secao 8.4)."""

    ATIVO = "ativo", "Compensação automática"
    INATIVO = "inativo", "Extras e débitos separados"


#: Dias da semana no padrao ISO usado no `jornada_config` das escalas.
DIAS_SEMANA = [
    (0, "Segunda-feira"),
    (1, "Terça-feira"),
    (2, "Quarta-feira"),
    (3, "Quinta-feira"),
    (4, "Sexta-feira"),
    (5, "Sábado"),
    (6, "Domingo"),
]

#: Mensagens motivacionais rotativas do totem (Estado 3 — Secao 6.5.1).
MENSAGENS_TOTEM = [
    "Bom trabalho!",
    "Excelente dia de trabalho!",
    "Seu ponto foi registrado com sucesso!",
    "Tenha um ótimo dia!",
    "Trabalho registrado. Até a próxima!",
]

#: Adicional noturno — Art. 73 CLT (Secao 8.4).
HORA_INICIO_NOTURNO_PADRAO = 22  # 22h
HORA_FIM_NOTURNO_PADRAO = 5  # 5h
ADICIONAL_NOTURNO_PERCENTUAL_PADRAO = 20  # +20%
MINUTOS_HORA_NOTURNA = 52.5  # hora noturna reduzida = 52min30s
