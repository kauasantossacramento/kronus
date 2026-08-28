"""
Kronus — campos de formulario para documentos brasileiros.

Os models guardam apenas digitos (CPF com 11, CNPJ com 14, PIS com 11),
mas a interface usa mascaras. Estes campos aceitam a entrada mascarada,
normalizam para digitos e so entao validam — evitando que o
`MaxLengthValidator` do model recuse a mascara antes da limpeza.
"""
from django import forms

from apps.core.utils import apenas_digitos, cnpj_valido, cpf_valido, pis_valido


class DocumentoFormField(forms.CharField):
    """Base: remove tudo que nao for digito antes de validar."""

    validador = staticmethod(lambda valor: True)
    mensagem_invalido = "Documento inválido."
    tamanho = 11

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", self.tamanho + 6)  # espaço para a máscara
        super().__init__(**kwargs)

    def to_python(self, value):
        return apenas_digitos(super().to_python(value) or "")

    def validate(self, value):
        super().validate(value)
        if not value:
            return
        if not self.validador(value):
            raise forms.ValidationError(self.mensagem_invalido, code="documento_invalido")


class CPFFormField(DocumentoFormField):
    validador = staticmethod(cpf_valido)
    mensagem_invalido = "CPF inválido."
    tamanho = 11

    def __init__(self, **kwargs):
        kwargs.setdefault("label", "CPF")
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("placeholder", "000.000.000-00")
        self.widget.attrs.setdefault("inputmode", "numeric")


class CNPJFormField(DocumentoFormField):
    validador = staticmethod(cnpj_valido)
    mensagem_invalido = "CNPJ inválido."
    tamanho = 14

    def __init__(self, **kwargs):
        kwargs.setdefault("label", "CNPJ")
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("placeholder", "00.000.000/0000-00")
        self.widget.attrs.setdefault("inputmode", "numeric")


class PISFormField(DocumentoFormField):
    validador = staticmethod(pis_valido)
    mensagem_invalido = "PIS/PASEP inválido."
    tamanho = 11

    def __init__(self, **kwargs):
        kwargs.setdefault("label", "PIS/PASEP")
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("placeholder", "000.00000.00-0")
        self.widget.attrs.setdefault("inputmode", "numeric")
