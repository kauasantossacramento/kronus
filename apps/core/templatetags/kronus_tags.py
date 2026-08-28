"""Kronus — filtros e tags de template."""
from django import template
from django.utils.safestring import mark_safe

from apps.core import utils
from apps.core.constants import StatusDia

register = template.Library()


# ==============================================================
# Documentos
# ==============================================================
@register.filter(name="cpf")
def cpf(valor):
    return utils.formatar_cpf(valor or "")


@register.filter(name="cpf_mascarado")
def cpf_mascarado(valor):
    return utils.mascarar_cpf(valor or "")


@register.filter(name="cnpj")
def cnpj(valor):
    return utils.formatar_cnpj(valor or "")


# ==============================================================
# Tempo
# ==============================================================
@register.filter(name="hhmm")
def hhmm(minutos, com_sinal=True):
    if minutos is None:
        return "--:--"
    return utils.minutos_para_hhmm(minutos, com_sinal=com_sinal)


@register.filter(name="hhmm_abs")
def hhmm_abs(minutos):
    if minutos is None:
        return "--:--"
    return utils.minutos_para_hhmm(minutos, com_sinal=False)


@register.filter(name="hora")
def hora(valor):
    """Formata datetime/time como HH:MM."""
    if valor is None:
        return "--:--"
    return valor.strftime("%H:%M")


# ==============================================================
# Integridade
# ==============================================================
@register.filter(name="hash_curto")
def hash_curto(valor):
    return utils.hash_curto(valor or "")


# ==============================================================
# UI
# ==============================================================
#: Classes Tailwind por status de dia (paleta da Secao 3.2).
CLASSES_STATUS = {
    StatusDia.COMPLETO: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    StatusDia.INCOMPLETO: "bg-amber-50 text-amber-700 ring-amber-600/20",
    StatusDia.FALTA: "bg-red-50 text-red-700 ring-red-600/20",
    StatusDia.JUSTIFICADO: "bg-blue-50 text-blue-700 ring-blue-600/20",
    StatusDia.ATESTADO: "bg-violet-50 text-violet-700 ring-violet-600/20",
    StatusDia.FOLGA: "bg-slate-100 text-slate-600 ring-slate-500/20",
    StatusDia.FERIADO: "bg-kronus-gold-50 text-kronus-gold-700 ring-kronus-gold-600/20",
    StatusDia.FERIAS: "bg-cyan-50 text-cyan-700 ring-cyan-600/20",
    StatusDia.AFASTAMENTO: "bg-slate-100 text-slate-600 ring-slate-500/20",
}

#: Ícone SVG (ver apps.core.templatetags.kronus_icons) por status.
ICONES_STATUS = {
    StatusDia.COMPLETO: "check_circulo",
    StatusDia.INCOMPLETO: "alerta",
    StatusDia.FALTA: "erro",
    StatusDia.JUSTIFICADO: "documento",
    StatusDia.ATESTADO: "saude",
    StatusDia.FOLGA: "lua",
    StatusDia.FERIADO: "estrela",
    StatusDia.FERIAS: "sol",
    StatusDia.AFASTAMENTO: "pausa",
}


@register.simple_tag(name="badge_status")
def badge_status(status, rotulo=""):
    """Selo de status do dia, com ícone SVG e cores do design system."""
    from apps.core.templatetags.kronus_icons import icone as render_icone

    classes = CLASSES_STATUS.get(status, "bg-slate-100 text-slate-600 ring-slate-500/20")
    svg = render_icone(ICONES_STATUS.get(status, "info"), classe="h-3.5 w-3.5")
    texto = rotulo or (dict(StatusDia.choices).get(status, status) or "")
    return mark_safe(
        f'<span class="inline-flex items-center gap-1.5 rounded-md px-2 py-1 '
        f'text-xs font-medium ring-1 ring-inset {classes}">{svg}{texto}</span>'
    )


@register.simple_tag(name="classe_saldo")
def classe_saldo(minutos):
    """
    Cores do banco de horas (Secao 8.4):
        verde   saldo positivo
        amarelo entre -2h e 0
        vermelho abaixo de -2h
    """
    if minutos is None:
        return "text-slate-500"
    if minutos > 0:
        return "text-emerald-600"
    if minutos >= -120:
        return "text-amber-600"
    return "text-red-600"


@register.filter(name="classe_saldo_cor")
def classe_saldo_cor(minutos):
    """
    Traduz um saldo em uma das cores do `stats_card`
    (padrao|sucesso|alerta|perigo), seguindo as faixas da Seção 8.4.
    """
    if minutos is None:
        return "padrao"
    if minutos > 0:
        return "sucesso"
    if minutos >= -120:
        return "alerta"
    return "perigo"


@register.filter(name="tem_prefixo")
def tem_prefixo(valor, prefixos):
    """
    O nome do campo começa com algum dos prefixos informados?

    O Django Template não expõe `startswith`, e agrupar dezenas de
    campos de configuração em seções temáticas exige exatamente isso.

        {% if campo.name|tem_prefixo:"tolerancia,intervalo" %}
    """
    nome = str(valor or "")
    return any(nome.startswith(p.strip()) for p in str(prefixos or "").split(",") if p.strip())


@register.filter(name="get_item")
def get_item(dicionario, chave):
    """Acesso a dicionario por chave variavel dentro do template."""
    if hasattr(dicionario, "get"):
        return dicionario.get(chave)
    return None


@register.simple_tag(takes_context=True)
def query_atual(context, **kwargs):
    """Preserva a querystring atual trocando apenas os parametros informados."""
    request = context["request"]
    params = request.GET.copy()
    for chave, valor in kwargs.items():
        if valor is None:
            params.pop(chave, None)
        else:
            params[chave] = valor
    return params.urlencode()
