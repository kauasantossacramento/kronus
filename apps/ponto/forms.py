"""Kronus — formulários do módulo de ponto."""
from datetime import time

from django import forms

from apps.clientes.forms import CLASSES_INPUT, EstiloTailwindMixin
from apps.core.constants import DIAS_SEMANA, TipoEscala, TipoRegistro
from apps.ponto.models import EscalaTrabalho
from apps.rh.forms import FormEscopadoPorEmpresa


class EscalaTrabalhoForm(FormEscopadoPorEmpresa):
    """
    Cadastro de escala com montagem visual da jornada.

    O `jornada_config` é um JSONField flexível (Seção 4.2 do plano), mas
    pedir JSON cru ao usuário de RH seria inviável. Este formulário expõe
    quatro horários por dia da semana e serializa o JSON por baixo.
    """

    class Meta:
        model = EscalaTrabalho
        fields = (
            "nome",
            "descricao",
            "tipo",
            "tolerancia_min",
            "carga_diaria_min",
            "carga_semanal_min",
            "exige_intervalo",
            "intervalo_min",
            "data_referencia",
            "ativa",
        )
        widgets = {
            "data_referencia": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        help_texts = {
            "data_referencia": "Primeiro dia trabalhado do ciclo (12x36, 6x1, plantão).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = (self.instance.jornada_config or {}).get("dias", {}) if self.instance else {}

        for indice, rotulo in DIAS_SEMANA:
            do_dia = config.get(str(indice)) or {}
            trabalha = bool(do_dia)

            self.fields[f"dia_{indice}_trabalha"] = forms.BooleanField(
                label=rotulo,
                required=False,
                initial=trabalha,
                widget=forms.CheckboxInput(
                    attrs={
                        "class": "h-4 w-4 rounded border-slate-300 "
                        "text-[var(--kronus-primary-600)] "
                        "focus:ring-[var(--kronus-primary-500)]"
                    }
                ),
            )
            for campo, rotulo_campo, padrao in (
                ("entrada", "Entrada", "08:00"),
                ("intervalo_inicio", "Saída intervalo", "12:00"),
                ("intervalo_fim", "Retorno intervalo", "13:00"),
                ("saida", "Saída", "17:00"),
            ):
                self.fields[f"dia_{indice}_{campo}"] = forms.TimeField(
                    label=rotulo_campo,
                    required=False,
                    initial=do_dia.get(campo) or (padrao if trabalha else None),
                    widget=forms.TimeInput(
                        attrs={"type": "time", "class": CLASSES_INPUT}, format="%H:%M"
                    ),
                )

    # -- montagem do JSON --------------------------------------
    @property
    def dias_montados(self):
        """Itera os campos por dia, para o template renderizar a grade."""
        for indice, rotulo in DIAS_SEMANA:
            yield {
                "indice": indice,
                "rotulo": rotulo,
                "trabalha": self[f"dia_{indice}_trabalha"],
                "entrada": self[f"dia_{indice}_entrada"],
                "intervalo_inicio": self[f"dia_{indice}_intervalo_inicio"],
                "intervalo_fim": self[f"dia_{indice}_intervalo_fim"],
                "saida": self[f"dia_{indice}_saida"],
            }

    def clean(self):
        dados = super().clean()
        tipo = dados.get("tipo")

        if tipo in (TipoEscala.ESCALA_12X36, TipoEscala.PLANTAO) and not dados.get(
            "data_referencia"
        ):
            self.add_error(
                "data_referencia",
                "Escalas cíclicas precisam da data de referência do primeiro plantão.",
            )

        dias = {}
        total_semanal = 0
        for indice, rotulo in DIAS_SEMANA:
            if not dados.get(f"dia_{indice}_trabalha"):
                dias[str(indice)] = None
                continue

            entrada = dados.get(f"dia_{indice}_entrada")
            saida = dados.get(f"dia_{indice}_saida")
            if not entrada or not saida:
                self.add_error(
                    f"dia_{indice}_entrada",
                    f"Informe entrada e saída para {rotulo.lower()}.",
                )
                continue

            do_dia = {
                "entrada": entrada.strftime("%H:%M"),
                "saida": saida.strftime("%H:%M"),
            }
            ini_int = dados.get(f"dia_{indice}_intervalo_inicio")
            fim_int = dados.get(f"dia_{indice}_intervalo_fim")
            if ini_int and fim_int:
                if fim_int <= ini_int:
                    self.add_error(
                        f"dia_{indice}_intervalo_fim",
                        "O retorno do intervalo deve ser posterior à saída.",
                    )
                do_dia["intervalo_inicio"] = ini_int.strftime("%H:%M")
                do_dia["intervalo_fim"] = fim_int.strftime("%H:%M")

            dias[str(indice)] = do_dia
            total_semanal += self._minutos(entrada, saida, ini_int, fim_int)

        config = dict(self.instance.jornada_config or {})
        config["dias"] = dias
        config["carga_semanal_min"] = total_semanal
        if tipo == TipoEscala.ESCALA_12X36:
            config.setdefault("padrao_12x36", {"entrada": "07:00", "saida": "19:00"})
        self.instance.jornada_config = config

        if total_semanal and not self.errors:
            dados["carga_semanal_min"] = total_semanal
        return dados

    @staticmethod
    def _minutos(entrada: time, saida: time, ini_int, fim_int) -> int:
        def em_minutos(t):
            return t.hour * 60 + t.minute

        total = em_minutos(saida) - em_minutos(entrada)
        if total <= 0:  # jornada que vira o dia
            total += 24 * 60
        if ini_int and fim_int:
            total -= max(em_minutos(fim_int) - em_minutos(ini_int), 0)
        return max(total, 0)


class VinculoEscalaForm(forms.Form):
    """Vincula uma escala a vários colaboradores de uma vez."""

    colaboradores = forms.ModelMultipleChoiceField(
        label="Colaboradores",
        queryset=None,
        widget=forms.SelectMultiple(attrs={"class": CLASSES_INPUT, "size": 12}),
    )

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.rh.models import Colaborador

        self.fields["colaboradores"].queryset = Colaborador.objects.filter(
            empresa=empresa, ativo=True
        ).order_by("nome_completo")


class AjustePontoForm(EstiloTailwindMixin, forms.Form):
    """
    Ajuste manual de marcação (regra 1 da Seção 14).

    Nunca edita o registro original: inclui, cancela ou substitui — sempre
    com justificativa obrigatória e trilha de auditoria.
    """

    acao = forms.ChoiceField(
        label="Ação",
        choices=[
            ("inclusao", "Incluir marcação"),
            ("cancelamento", "Cancelar marcação"),
            ("substituicao", "Substituir marcação"),
        ],
        widget=forms.Select(attrs={"class": CLASSES_INPUT}),
    )
    data_hora = forms.DateTimeField(
        label="Data e hora",
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": CLASSES_INPUT},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"],
    )
    tipo = forms.ChoiceField(
        label="Tipo de marcação",
        required=False,
        choices=[("", "---")] + list(TipoRegistro.choices),
        widget=forms.Select(attrs={"class": CLASSES_INPUT}),
    )
    justificativa = forms.CharField(
        label="Justificativa",
        widget=forms.Textarea(attrs={"rows": 3, "class": CLASSES_INPUT}),
        help_text="Obrigatória e registrada na auditoria — Portaria 671/2021.",
        min_length=10,
    )

    def clean(self):
        dados = super().clean()
        acao = dados.get("acao")
        if acao in ("inclusao", "substituicao"):
            if not dados.get("data_hora"):
                self.add_error("data_hora", "Informe a data e hora da marcação.")
            if not dados.get("tipo"):
                self.add_error("tipo", "Informe o tipo da marcação.")
        return dados


class FiltroPeriodoForm(forms.Form):
    """Filtro de período reutilizado nas telas de ponto e banco de horas."""

    inicio = forms.DateField(
        label="De",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": CLASSES_INPUT}),
    )
    fim = forms.DateField(
        label="Até",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": CLASSES_INPUT}),
    )
    colaborador = forms.ModelChoiceField(
        label="Colaborador",
        required=False,
        queryset=None,
        empty_label="Todos",
        widget=forms.Select(attrs={"class": CLASSES_INPUT}),
    )

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.rh.models import Colaborador

        self.fields["colaborador"].queryset = Colaborador.objects.filter(
            empresa=empresa
        ).order_by("nome_completo")
