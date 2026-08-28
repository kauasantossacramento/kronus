"""Kronus — formulários de atestados, justificativas e afastamentos."""
from django import forms
from django.utils import timezone

from apps.clientes.forms import CLASSES_INPUT, EstiloTailwindMixin
from apps.rh.forms import FormEscopadoPorEmpresa
from apps.rh.models import Afastamento, Atestado, Justificativa

#: Extensões e tamanho aceitos no upload de comprovante (Seção 8.6).
EXTENSOES_ACEITAS = (".pdf", ".jpg", ".jpeg", ".png")
TAMANHO_MAXIMO_MB = 10


def validar_arquivo(arquivo):
    """Recusa arquivo grande demais ou de tipo inesperado."""
    if not arquivo:
        return arquivo
    nome = (arquivo.name or "").lower()
    if not nome.endswith(EXTENSOES_ACEITAS):
        raise forms.ValidationError(
            f"Formato não aceito. Envie {', '.join(EXTENSOES_ACEITAS)}."
        )
    if arquivo.size > TAMANHO_MAXIMO_MB * 1024 * 1024:
        raise forms.ValidationError(
            f"Arquivo acima de {TAMANHO_MAXIMO_MB} MB "
            f"({arquivo.size / 1024 / 1024:.1f} MB)."
        )
    return arquivo


class AtestadoForm(FormEscopadoPorEmpresa):
    """Upload de atestado médico (Seção 8.6)."""

    campos_escopados = {"colaborador": "colaborador_set"}

    class Meta:
        model = Atestado
        fields = (
            "colaborador",
            "arquivo",
            "data_inicio",
            "data_fim",
            "cid",
            "observacoes",
        )
        widgets = {
            "data_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_fim": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
            "cid": forms.TextInput(attrs={"placeholder": "Opcional — ex.: J11"}),
        }
        help_texts = {
            "cid": "Opcional. O CID é dado de saúde: só registre com o consentimento do colaborador.",
        }

    def clean_arquivo(self):
        return validar_arquivo(self.cleaned_data.get("arquivo"))

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("data_inicio"), dados.get("data_fim")

        if inicio and fim and fim < inicio:
            self.add_error("data_fim", "O fim não pode ser anterior ao início.")

        if inicio and inicio > timezone.localdate() + timezone.timedelta(days=1):
            self.add_error("data_inicio", "Atestado com início no futuro.")

        colaborador = dados.get("colaborador")
        if colaborador and inicio and fim:
            # Sobreposição indica lançamento duplicado — comum quando o
            # atestado chega pelo RH e pelo gestor ao mesmo tempo.
            conflitos = Atestado.objects.filter(
                colaborador=colaborador,
                data_inicio__lte=fim,
                data_fim__gte=inicio,
                deleted_at__isnull=True,
            )
            if self.instance.pk:
                conflitos = conflitos.exclude(pk=self.instance.pk)
            if conflitos.exists():
                self.add_error(
                    None,
                    "Já existe atestado deste colaborador cobrindo esse período.",
                )
        return dados


class AvaliacaoForm(EstiloTailwindMixin, forms.Form):
    """Aprovação ou rejeição, com parecer obrigatório na recusa."""

    decisao = forms.ChoiceField(
        label="Decisão",
        choices=[("aprovar", "Aprovar"), ("rejeitar", "Rejeitar")],
        widget=forms.RadioSelect,
    )
    parecer = forms.CharField(
        label="Parecer",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": CLASSES_INPUT}),
        help_text="Obrigatório ao rejeitar — o colaborador precisa saber o motivo.",
    )

    def clean(self):
        dados = super().clean()
        if dados.get("decisao") == "rejeitar" and not (dados.get("parecer") or "").strip():
            self.add_error("parecer", "Informe o motivo da rejeição.")
        return dados


class JustificativaForm(FormEscopadoPorEmpresa):
    """Justificativa de falta, atraso ou esquecimento de batida."""

    campos_escopados = {"colaborador": "colaborador_set"}

    class Meta:
        model = Justificativa
        fields = (
            "colaborador",
            "data",
            "tipo",
            "motivo",
            "arquivo_comprovante",
            "abona_dia",
        )
        widgets = {
            "data": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "motivo": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_arquivo_comprovante(self):
        return validar_arquivo(self.cleaned_data.get("arquivo_comprovante"))

    def clean_motivo(self):
        motivo = (self.cleaned_data.get("motivo") or "").strip()
        if len(motivo) < 10:
            raise forms.ValidationError(
                "Descreva o motivo — ele fica registrado na auditoria e no AEJ."
            )
        return motivo

    def clean(self):
        dados = super().clean()
        data = dados.get("data")
        if data and data > timezone.localdate():
            self.add_error("data", "Não é possível justificar um dia futuro.")
        return dados


class JustificativaColaboradorForm(JustificativaForm):
    """
    Versão usada pelo próprio colaborador (Seção 6.4).

    O colaborador não escolhe quem é nem se o dia será abonado — isso é
    decisão do RH na aprovação.
    """

    class Meta(JustificativaForm.Meta):
        fields = ("data", "tipo", "motivo", "arquivo_comprovante")


class AfastamentoForm(FormEscopadoPorEmpresa):
    """Férias, licenças e afastamentos (Seção 8.8)."""

    campos_escopados = {"colaborador": "colaborador_set"}

    class Meta:
        model = Afastamento
        fields = (
            "colaborador",
            "tipo",
            "data_inicio",
            "data_fim",
            "documento",
            "observacoes",
        )
        widgets = {
            "data_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_fim": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_documento(self):
        return validar_arquivo(self.cleaned_data.get("documento"))

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("data_inicio"), dados.get("data_fim")
        if inicio and fim and fim < inicio:
            self.add_error("data_fim", "O fim não pode ser anterior ao início.")
        return dados


class FechamentoForm(EstiloTailwindMixin, forms.Form):
    """Fechamento do período de apuração."""

    confirmar = forms.BooleanField(
        label="Confirmo a apuração do período",
        help_text=(
            "Após o fechamento, os dias do período deixam de ser recalculados "
            "automaticamente. Ajustes posteriores exigem reabertura."
        ),
    )
