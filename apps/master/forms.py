"""Kronus — formularios do painel Master."""
from django import forms
from django.utils.text import slugify

from apps.accounts.models import CustomUser
from apps.clientes.models import Cliente, Empresa
from apps.core.constants import TipoUsuario
from apps.master.models import Plano
from apps.totem.models import GrupoTotem, Totem

CLASSES_INPUT = (
    "block w-full rounded-lg border-0 py-2 px-3 text-slate-900 shadow-sm "
    "ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 "
    "focus:ring-2 focus:ring-inset focus:ring-[var(--kronus-primary-500)] sm:text-sm"
)
CLASSES_CHECK = (
    "h-4 w-4 rounded border-slate-300 text-[var(--kronus-primary-600)] "
    "focus:ring-[var(--kronus-primary-500)]"
)


class PlanoForm(forms.ModelForm):
    class Meta:
        model = Plano
        fields = (
            "nome",
            "slug",
            "descricao",
            "ordem",
            "destaque",
            "max_empresas",
            "max_colaboradores",
            "max_totems",
            "preco_mensal",
            "preco_por_colaborador",
            "tem_api",
            "tem_geofencing",
            "tem_totem",
            "tem_offline",
            "tem_banco_horas",
            "tem_webhook",
            "tem_portal_contador",
            "tem_esocial",
            "rate_limit_api_hora",
            "ativo",
        )
        widgets = {
            "descricao": forms.Textarea(attrs={"class": CLASSES_INPUT, "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, campo in self.fields.items():
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs.setdefault("class", CLASSES_CHECK)
            else:
                campo.widget.attrs.setdefault("class", CLASSES_INPUT)
        self.fields["slug"].required = False

    def clean_slug(self):
        valor = self.cleaned_data.get("slug")
        if valor:
            return valor
        return slugify(self.data.get("nome", ""))[:60]


class TotemForm(forms.ModelForm):
    """
    Cadastro do equipamento pela KS TEC.

    O `token_acesso` **não** está entre os campos: ele é gerado no
    `save()` do model e nunca digitado. Um token escolhido a mão seria
    adivinhavel, e ele é a única credencial que separa a URL do quiosque
    do resto da internet.
    """

    class Meta:
        model = Totem
        fields = (
            "identificador",
            "apelido",
            "empresa",
            "grupo",
            "local_instalacao",
            "modelo_tablet",
            "serial_tablet",
            "versao_firmware",
            "permite_fallback_cpf",
            "segundos_tela_sucesso",
            "segundos_countdown_offline",
            "observacoes",
            "ativo",
        )
        widgets = {
            "observacoes": forms.Textarea(attrs={"class": CLASSES_INPUT, "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs.setdefault("class", CLASSES_CHECK)
            else:
                campo.widget.attrs.setdefault("class", CLASSES_INPUT)

        self.fields["empresa"].queryset = (
            Empresa.objects.filter(ativo=True)
            .select_related("cliente")
            .order_by("cliente__razao_social", "razao_social")
        )
        self.fields["grupo"].queryset = GrupoTotem.objects.filter(
            ativo=True
        ).select_related("cliente").order_by("cliente__razao_social", "nome")
        self.fields["grupo"].required = False
        self.fields["identificador"].help_text = (
            "Código legível colado no equipamento, ex.: TOTEM-RECEPCAO-01."
        )

    def clean_identificador(self):
        # Maiusculas e sem espaco: o identificador vai impresso na
        # etiqueta do tablet e é lido em voz alta no suporte.
        valor = (self.cleaned_data.get("identificador") or "").strip().upper()
        return valor.replace(" ", "-")

    def clean(self):
        dados = super().clean()
        empresa = dados.get("empresa")
        grupo = dados.get("grupo")

        if grupo and empresa and grupo.cliente_id != empresa.cliente_id:
            # Um grupo atravessa empresas do mesmo cliente, nunca
            # clientes diferentes: isso vazaria colaboradores de uma
            # conta para o totem de outra (regra 12 da Seção 14).
            raise forms.ValidationError(
                {"grupo": "O grupo pertence a outro cliente."}
            )

        if empresa is not None:
            plano = getattr(empresa.cliente, "plano", None)
            if plano is not None and plano.max_totems:
                existentes = Totem.objects.filter(
                    empresa__cliente=empresa.cliente, ativo=True
                )
                if self.instance.pk:
                    existentes = existentes.exclude(pk=self.instance.pk)
                if existentes.count() >= plano.max_totems:
                    raise forms.ValidationError(
                        f"O plano {plano.nome} permite {plano.max_totems} "
                        f"totem(ns); o cliente já usa {existentes.count()}."
                    )
        return dados


class ComodatoForm(forms.ModelForm):
    """
    Dados do contrato de comodato do equipamento.

    Separado do `TotemForm` de propósito: o cadastro técnico do totem
    (quem instala) e o registro do comodato (quem assina o contrato)
    acontecem em momentos diferentes e por pessoas diferentes.
    """

    class Meta:
        model = Totem
        fields = (
            "em_comodato",
            "data_instalacao",
            "data_devolucao",
            "contrato_comodato",
            "serial_tablet",
            "modelo_tablet",
        )
        widgets = {
            "data_instalacao": forms.DateInput(
                attrs={"type": "date", "class": CLASSES_INPUT}, format="%Y-%m-%d"
            ),
            "data_devolucao": forms.DateInput(
                attrs={"type": "date", "class": CLASSES_INPUT}, format="%Y-%m-%d"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs.setdefault("class", CLASSES_CHECK)
            else:
                campo.widget.attrs.setdefault("class", CLASSES_INPUT)

    def clean(self):
        dados = super().clean()
        instalacao = dados.get("data_instalacao")
        devolucao = dados.get("data_devolucao")

        if instalacao and devolucao and devolucao < instalacao:
            raise forms.ValidationError(
                {"data_devolucao": "A devolução é anterior à instalação."}
            )

        if dados.get("em_comodato") and not instalacao:
            raise forms.ValidationError(
                {"data_instalacao": "Informe a data de instalação do comodato."}
            )
        return dados


class GrupoTotemForm(forms.ModelForm):
    """
    Grupo de totens compartilhados entre empresas do mesmo cliente.

    Caso real: um grupo econômico com três CNPJs no mesmo prédio e um
    totem na portaria. Sem o grupo, cada CNPJ precisaria do seu próprio
    equipamento na mesma porta.
    """

    class Meta:
        model = GrupoTotem
        fields = ("cliente", "nome", "descricao", "empresas", "ativo")
        widgets = {
            "empresas": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, campo in self.fields.items():
            if nome == "empresas":
                continue
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs.setdefault("class", CLASSES_CHECK)
            else:
                campo.widget.attrs.setdefault("class", CLASSES_INPUT)

        self.fields["empresas"].queryset = Empresa.objects.filter(
            ativo=True
        ).select_related("cliente").order_by("cliente__razao_social", "razao_social")
        self.fields["empresas"].required = False

    def clean(self):
        dados = super().clean()
        cliente = dados.get("cliente")
        empresas = dados.get("empresas")

        if cliente and empresas:
            invasoras = [e for e in empresas if e.cliente_id != cliente.pk]
            if invasoras:
                nomes = ", ".join(e.razao_social for e in invasoras[:3])
                raise forms.ValidationError({
                    "empresas": (
                        f"Estas empresas pertencem a outro cliente: {nomes}. "
                        "Um grupo de totens nunca atravessa contas."
                    )
                })
        return dados


class UsuarioMasterForm(forms.ModelForm):
    """
    Cadastro de usuário pelo Master, em qualquer conta.

    **A senha não está entre os campos** — nem na criação, nem na
    edição. Quem cria recebe uma provisória gerada pelo sistema e é
    obrigado a trocá-la; assim não existe momento em que o operador da
    KS TEC conhece a senha em uso de um cliente, e o rastro de autoria
    continua valendo.
    """

    class Meta:
        model = CustomUser
        fields = (
            "username",
            "nome_completo",
            "email",
            "tipo",
            "cliente",
            "empresas",
            "is_active",
        )
        widgets = {"empresas": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, campo in self.fields.items():
            if nome == "empresas":
                continue
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs.setdefault("class", CLASSES_CHECK)
            else:
                campo.widget.attrs.setdefault("class", CLASSES_INPUT)

        self.fields["cliente"].queryset = Cliente.objects.order_by("razao_social")
        self.fields["cliente"].required = False
        self.fields["empresas"].queryset = Empresa.objects.select_related(
            "cliente"
        ).order_by("cliente__razao_social", "razao_social")
        self.fields["empresas"].required = False
        self.fields["username"].help_text = (
            "E-mail ou CPF — é com este valor que a pessoa entra no sistema."
        )

    def clean(self):
        dados = super().clean()
        tipo = dados.get("tipo")
        cliente = dados.get("cliente")
        empresas = dados.get("empresas")

        # Um usuário sem conta só faz sentido para o Master. Qualquer
        # outro papel sem cliente vira um acesso órfão: entra no sistema
        # e não enxerga nada, o que aparece no suporte como "meu login
        # não funciona".
        if tipo != TipoUsuario.MASTER and cliente is None:
            raise forms.ValidationError(
                {"cliente": "Informe o cliente ao qual este usuário pertence."}
            )
        if tipo == TipoUsuario.MASTER and cliente is not None:
            raise forms.ValidationError(
                {"cliente": "Usuário Master não pertence a um cliente."}
            )

        if empresas and cliente:
            invasoras = [e for e in empresas if e.cliente_id != cliente.pk]
            if invasoras:
                nomes = ", ".join(e.razao_social for e in invasoras[:3])
                raise forms.ValidationError({
                    "empresas": (
                        f"Estas empresas são de outro cliente: {nomes}. "
                        "Vincular atravessaria contas."
                    )
                })

        if tipo == TipoUsuario.RH and not empresas:
            raise forms.ValidationError({
                "empresas": "Um Admin RH precisa de ao menos uma empresa."
            })
        return dados
