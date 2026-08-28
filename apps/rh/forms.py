"""Kronus — formularios do painel RH."""
from django import forms

from apps.clientes.forms import EstiloTailwindMixin
from apps.core.form_fields import CPFFormField, PISFormField
from apps.rh.models import Cargo, Colaborador, Departamento


class FormEscopadoPorEmpresa(EstiloTailwindMixin, forms.ModelForm):
    """
    Base dos formularios do RH.

    Recebe `empresa` do construtor, fixa o tenant do objeto e restringe
    os selects relacionados as opcoes daquela empresa — impedindo que um
    POST forjado aponte para dados de outro cliente.
    """

    campos_escopados: dict[str, str] = {}

    def __init__(self, *args, empresa=None, **kwargs):
        self.empresa = empresa
        super().__init__(*args, **kwargs)
        if empresa is not None:
            for campo, related_name in self.campos_escopados.items():
                if campo in self.fields:
                    self.fields[campo].queryset = getattr(empresa, related_name).filter(
                        deleted_at__isnull=True
                    )

    def save(self, commit=True):
        objeto = super().save(commit=False)
        if self.empresa is not None and not objeto.empresa_id:
            objeto.empresa = self.empresa
        if commit:
            objeto.save()
            self.save_m2m()
        return objeto


class DepartamentoForm(FormEscopadoPorEmpresa):
    campos_escopados = {"responsavel": "colaborador_set"}

    class Meta:
        model = Departamento
        fields = ("nome", "descricao", "responsavel", "centro_custo", "ativo")


class CargoForm(FormEscopadoPorEmpresa):
    class Meta:
        model = Cargo
        fields = ("nome", "cbo", "descricao", "salario_base", "ativo")


class ColaboradorForm(FormEscopadoPorEmpresa):
    campos_escopados = {
        "departamento": "departamento_set",
        "cargo_ref": "cargo_set",
        "escala": "escalatrabalho_set",
    }

    cpf = CPFFormField()
    pis_pasep = PISFormField()

    criar_acesso = forms.BooleanField(
        label="Criar credenciais de acesso web",
        required=False,
        initial=False,
        help_text="Gera um usuário para o colaborador bater ponto pelo navegador.",
    )

    class Meta:
        model = Colaborador
        fields = (
            "nome_completo",
            "nome_social",
            "cpf",
            "data_nascimento",
            "email",
            "telefone",
            "matricula",
            "cargo",
            "cargo_ref",
            "departamento",
            "escala",
            "data_admissao",
            "data_demissao",
            "pis_pasep",
            "ctps",
            "ctps_serie",
            "foto_perfil",
            "permite_ponto_web",
            "ativo",
            "observacoes",
        )
        widgets = {
            "data_nascimento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_admissao": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_demissao": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_cpf(self):
        """O CPF é único dentro da empresa (a mesma pessoa pode ter
        vínculo em outra empresa do mesmo cliente)."""
        valor = self.cleaned_data.get("cpf", "")
        duplicado = Colaborador.objects.filter(empresa=self.empresa, cpf=valor)
        if self.instance.pk:
            duplicado = duplicado.exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise forms.ValidationError("Já existe um colaborador com este CPF na empresa.")
        return valor

    def clean(self):
        dados = super().clean()
        admissao = dados.get("data_admissao")
        demissao = dados.get("data_demissao")
        if admissao and demissao and demissao < admissao:
            self.add_error(
                "data_demissao", "A demissão não pode ser anterior à admissão."
            )
        if dados.get("criar_acesso") and not dados.get("email"):
            self.add_error(
                "email", "Informe um e-mail para criar as credenciais de acesso."
            )
        return dados


class ImportacaoColaboradoresForm(forms.Form):
    """Importacao em massa via CSV/TXT (Secao 8.8)."""

    arquivo = forms.FileField(
        label="Arquivo CSV ou TXT",
        help_text=(
            "Colunas esperadas: nome_completo, cpf, data_nascimento, email, "
            "matricula, cargo, departamento, data_admissao."
        ),
    )
    delimitador = forms.ChoiceField(
        label="Delimitador",
        choices=[(";", "Ponto e vírgula (;)"), (",", "Vírgula (,)"), ("\t", "Tabulação")],
        initial=";",
    )
    criar_departamentos = forms.BooleanField(
        label="Criar departamentos inexistentes", required=False, initial=True
    )
    atualizar_existentes = forms.BooleanField(
        label="Atualizar colaboradores já cadastrados (mesmo CPF)",
        required=False,
        initial=False,
    )
