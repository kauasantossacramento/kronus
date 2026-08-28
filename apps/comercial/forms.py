"""Kronus — formulario de solicitacao de demonstracao."""
from django import forms

from apps.comercial.models import SolicitacaoDemonstracao

CLASSE_CAMPO = (
    "block w-full rounded-lg border-0 bg-white/10 py-3 px-4 text-base "
    "text-white placeholder-white/50 ring-1 ring-inset ring-white/25 "
    "focus:ring-2 focus:ring-[var(--kronus-gold-400)] focus:bg-white/15"
)

PORTES = [
    ("", "Nº de colaboradores"),
    ("1-10", "Até 10"),
    ("11-50", "11 a 50"),
    ("51-200", "51 a 200"),
    ("200+", "Mais de 200"),
]


class FormularioDemonstracao(forms.ModelForm):
    """
    Pede o mínimo para abrir o ambiente e permitir o retorno comercial.

    Cada campo a mais aqui derruba conversão, então só entra o que tem
    uso concreto: nome e e-mail viram o login, WhatsApp é o canal de
    retorno, porte orienta a proposta.
    """

    # Campo-armadilha: robô preenche tudo que encontra; gente não vê.
    site = forms.CharField(required=False, widget=forms.HiddenInput)

    #: Logo opcional, enviada ja no pedido.
    #:
    #: Ver a propria marca no ambiente muda a demonstracao de "um sistema
    #: qualquer" para "o meu sistema". Quem nao tiver o arquivo a mao
    #: continua entrando — o lugar da logo mostra "sua logo aqui", que
    #: comunica a personalizacao sem exigir nada agora.
    logo = forms.ImageField(
        required=False,
        label="Logo da empresa (opcional)",
        widget=forms.ClearableFileInput(attrs={
            "class": "block w-full text-sm text-white/80",
            "accept": "image/*",
        }),
    )

    class Meta:
        model = SolicitacaoDemonstracao
        fields = ("nome", "empresa", "email", "whatsapp", "porte")
        widgets = {
            "nome": forms.TextInput(attrs={
                "class": CLASSE_CAMPO, "placeholder": "Seu nome",
                "autocomplete": "name",
            }),
            "empresa": forms.TextInput(attrs={
                "class": CLASSE_CAMPO, "placeholder": "Nome da empresa",
                "autocomplete": "organization",
            }),
            "email": forms.EmailInput(attrs={
                "class": CLASSE_CAMPO, "placeholder": "E-mail corporativo",
                "autocomplete": "email", "inputmode": "email",
            }),
            "whatsapp": forms.TextInput(attrs={
                "class": CLASSE_CAMPO, "placeholder": "WhatsApp com DDD",
                "autocomplete": "tel", "inputmode": "tel",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["porte"] = forms.ChoiceField(
            choices=PORTES, required=False,
            widget=forms.Select(attrs={"class": CLASSE_CAMPO}),
        )
        # WhatsApp obrigatorio: o e-mail da demonstracao cai em spam com
        # frequencia, e sem um segundo canal o interessado some entre o
        # cadastro e o retorno comercial.
        self.fields["whatsapp"].required = True

    def clean_site(self):
        if self.cleaned_data.get("site"):
            raise forms.ValidationError("Não foi possível concluir.")
        return ""

    def clean_email(self):
        email = (self.cleaned_data["email"] or "").strip().lower()

        from apps.accounts.models import CustomUser

        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Já existe uma conta com este e-mail. Entre pelo login "
                "ou use outro endereço."
            )
        return email

    def clean_whatsapp(self):
        bruto = self.cleaned_data.get("whatsapp") or ""
        digitos = "".join(c for c in bruto if c.isdigit())
        if not digitos:
            raise forms.ValidationError("Informe o WhatsApp com DDD.")
        if not 10 <= len(digitos) <= 13:
            raise forms.ValidationError("Informe DDD e número.")
        return digitos
