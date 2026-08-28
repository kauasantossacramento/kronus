"""Kronus — formularios de Cliente, Empresa e ConfiguracaoEmpresa."""
from django import forms

from apps.clientes.models import Cliente, ConfiguracaoEmpresa, Empresa
from apps.core.form_fields import CNPJFormField

CLASSES_INPUT = (
    "block w-full rounded-lg border-0 py-2 px-3 text-slate-900 shadow-sm "
    "ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 "
    "focus:ring-2 focus:ring-inset focus:ring-[var(--kronus-primary-500)] sm:text-sm"
)
CLASSES_CHECK = (
    "h-4 w-4 rounded border-slate-300 text-[var(--kronus-primary-600)] "
    "focus:ring-[var(--kronus-primary-500)]"
)


class EstiloTailwindMixin:
    """Aplica as classes do design system a todos os widgets do form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", CLASSES_CHECK)
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault(
                    "class",
                    "block w-full text-sm text-slate-600 file:mr-4 file:rounded-lg "
                    "file:border-0 file:bg-slate-100 file:px-4 file:py-2 "
                    "file:text-sm file:font-medium file:text-slate-700",
                )
            else:
                widget.attrs.setdefault("class", CLASSES_INPUT)


class ClienteForm(EstiloTailwindMixin, forms.ModelForm):
    cnpj = CNPJFormField()

    class Meta:
        model = Cliente
        fields = (
            "razao_social",
            "nome_fantasia",
            "cnpj",
            "plano",
            "email_contato",
            "telefone",
            "responsavel",
            "cep",
            "logradouro",
            "numero",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "data_inicio_contrato",
            "data_fim_contrato",
            "dia_vencimento",
            "dpo_nome",
            "dpo_email",
            "ativo",
            "observacoes",
        )
        widgets = {
            "data_inicio_contrato": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "data_fim_contrato": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }


class EmpresaForm(EstiloTailwindMixin, forms.ModelForm):
    cnpj = CNPJFormField()

    class Meta:
        model = Empresa
        fields = (
            "cliente",
            "razao_social",
            "nome_fantasia",
            "cnpj",
            "inscricao_estadual",
            "cei_caepf",
            "cep",
            "logradouro",
            "numero",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "fuso_horario",
            "ativo",
        )


class PersonalizacaoEmpresaForm(EstiloTailwindMixin, forms.ModelForm):
    """
    White-label parcial (Secao 3.6): logo, cores e tela de ociosidade.

    A marca Kronus e a assinatura KS TEC nao sao customizaveis.
    """

    class Meta:
        model = Empresa
        fields = (
            "logo",
            "logo_altura_px",
            "logo_deslocamento_px",
            "logo_css",
            "cor_primaria",
            "cor_secundaria",
            "msg_boas_vindas",
            "msg_sucesso_ponto",
            "som_confirmacao",
        )
        widgets = {
            "cor_primaria": forms.TextInput(
                attrs={"type": "color", "class": "h-10 w-20 rounded border-slate-300"}
            ),
            "cor_secundaria": forms.TextInput(
                attrs={"type": "color", "class": "h-10 w-20 rounded border-slate-300"}
            ),
            "logo_css": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "filter: brightness(0) invert(1);",
                    "style": "font-family: ui-monospace, monospace; font-size: .8rem",
                }
            ),
        }


class OperacaoEmpresaForm(EstiloTailwindMixin, forms.ModelForm):
    """Parametros operacionais que vivem na propria Empresa."""

    class Meta:
        model = Empresa
        fields = (
            "fuso_horario",
            "modo_compensacao",
            "permite_ver_ponto",
            "geofencing_ativo",
            "geofencing_lat",
            "geofencing_lng",
            "geofencing_raio",
            "geofencing_bloqueia",
        )


class ConfiguracaoEmpresaForm(EstiloTailwindMixin, forms.ModelForm):
    class Meta:
        model = ConfiguracaoEmpresa
        exclude = ("empresa", "uuid", "created_at", "updated_at", "deleted_at")
        widgets = {
            "hora_ini_noturno": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "hora_fim_noturno": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
