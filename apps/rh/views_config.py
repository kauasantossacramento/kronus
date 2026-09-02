"""
Kronus — configurações da empresa e personalização (Fase 4).

    /rh/configuracoes/                parâmetros de jornada e cálculo
    /rh/configuracoes/personalizacao/ logo, cores e tela do totem
    /rh/configuracoes/notificacoes/   quais avisos enviar
    /rh/configuracoes/integracao/     chaves de API

Alterar a tolerância ou o adicional noturno muda o **cálculo** de todos
os dias em aberto. Por isso a tela avisa e oferece o reprocessamento do
mês corrente — mudar o parâmetro sem recalcular deixaria o painel
mostrando números apurados por uma regra que já não vale.
"""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from apps.api.models import APIKey
from apps.clientes.forms import (
    ConfiguracaoEmpresaForm,
    OperacaoEmpresaForm,
    PersonalizacaoEmpresaForm,
)
from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.ponto.services import ConsolidacaoService
from apps.rh.models import Colaborador

logger = logging.getLogger("kronus.rh")

#: Campos cuja alteração muda o resultado do cálculo de jornada.
CAMPOS_QUE_AFETAM_CALCULO = {
    "inicio_do_controle",
    "tolerancia_atraso_min",
    "intervalo_minimo_min",
    "jornada_diaria_padrao_min",
    "hora_extra_percentual",
    "hora_extra_percentual_2",
    "limite_hora_extra_diaria_min",
    "adicional_noturno",
    "hora_ini_noturno",
    "hora_fim_noturno",
    "hora_noturna_reduzida",
    "modo_compensacao",
}


@rh_required
@empresa_ativa_required
def configuracoes(request):
    """Parâmetros de jornada, horas extras, adicional noturno e banco."""
    empresa = request.empresa_ativa
    config = empresa.configuracao

    form_config = ConfiguracaoEmpresaForm(request.POST or None, instance=config)
    form_operacao = OperacaoEmpresaForm(request.POST or None, instance=empresa)

    if request.method == "POST":
        if form_config.is_valid() and form_operacao.is_valid():
            alterados = set(form_config.changed_data) | set(form_operacao.changed_data)
            form_config.save()
            form_operacao.save()

            registrar_log(
                request=request,
                acao=LogAcesso.Acao.CONFIG,
                descricao=(
                    f"Configurações alteradas: {', '.join(sorted(alterados)) or 'nenhuma'}"
                ),
                objeto=empresa,
            )

            afeta_calculo = alterados & CAMPOS_QUE_AFETAM_CALCULO
            if afeta_calculo:
                messages.warning(
                    request,
                    "Você alterou parâmetros que mudam o cálculo de jornada "
                    f"({', '.join(sorted(afeta_calculo))}). Os dias já apurados "
                    "seguem com o cálculo antigo até serem reprocessados.",
                )
            else:
                messages.success(request, "Configurações salvas.")
            return redirect("rh:configuracoes")
        messages.error(request, "Corrija os campos destacados.")

    return render(
        request,
        "rh/configuracoes/empresa.html",
        {
            "titulo": "Configurações da empresa",
            "menu_ativo": "configuracoes",
            "form_config": form_config,
            "form_operacao": form_operacao,
            "empresa": empresa,
        },
    )


@rh_required
@empresa_ativa_required
def reprocessar_mes(request):
    """Recalcula o mês corrente após mudança de parâmetro."""
    if request.method != "POST":
        return redirect("rh:configuracoes")

    empresa = request.empresa_ativa
    hoje = timezone.localdate()
    inicio = hoje.replace(day=1)

    total = 0
    for colaborador in Colaborador.objects.filter(empresa=empresa, ativo=True):
        ConsolidacaoService.consolidar_periodo(colaborador, inicio, hoje)
        total += 1

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=f"Mês corrente reprocessado para {total} colaborador(es)",
        objeto=empresa,
    )
    messages.success(
        request,
        f"{total} colaborador(es) reprocessado(s) de {inicio:%d/%m} a {hoje:%d/%m}. "
        "Dias já fechados não foram alterados.",
    )
    return redirect("rh:configuracoes")


@rh_required
@empresa_ativa_required
def personalizacao(request):
    """
    White-label parcial (Seção 3.6): logo, cores e tela do totem.

    A marca Kronus e a assinatura KS TEC não são customizáveis — a tela
    deixa isso explícito para evitar a expectativa errada.
    """
    empresa = request.empresa_ativa
    form = PersonalizacaoEmpresaForm(
        request.POST or None, request.FILES or None, instance=empresa
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        registrar_log(
            request=request,
            acao=LogAcesso.Acao.CONFIG,
            descricao=f"Personalização visual alterada: {', '.join(form.changed_data)}",
            objeto=empresa,
        )
        # Avisa os totens da empresa para recarregarem a configuração.
        _avisar_totens(empresa)
        messages.success(request, "Personalização salva. Os totens serão atualizados.")
        return redirect("rh:personalizacao")

    return render(
        request,
        "rh/configuracoes/personalizacao.html",
        {
            "titulo": "Personalização",
            "menu_ativo": "configuracoes",
            "form": form,
            "empresa": empresa,
            "totens": empresa.totens.filter(ativo=True),
        },
    )


def _avisar_totens(empresa):
    """
    Faz os totens da empresa recarregarem a configuracao.

    Dois caminhos, de proposito:

    * **Versao da configuracao** — o totem compara no heartbeat (a cada
      30 s) e se recarrega. Funciona sempre, inclusive num totem que
      estava offline na hora da mudanca.
    * **WebSocket** — chega na hora, quando o canal esta de pe.

    O WebSocket sozinho perderia a mudanca de um tablet desconectado; a
    versao sozinha demoraria ate meio minuto. Juntos, e imediato quando
    da e confiavel quando nao da.
    """
    empresa.marcar_configuracao_alterada()

    try:
        from apps.totem.consumers import comandar_totem

        for totem in empresa.totens.filter(ativo=True):
            comandar_totem(totem, "totem.config_alterada")
    except Exception:
        # Canal fora do ar nao invalida a mudanca: o heartbeat resolve.
        logger.warning("Nao foi possivel avisar os totens pelo WebSocket.")


@rh_required
@empresa_ativa_required
def notificacoes(request):
    """Quais eventos geram aviso e para qual e-mail (Seção 8.7)."""
    empresa = request.empresa_ativa
    config = empresa.configuracao

    campos = [
        ("notif_esq_ponto", "Esquecimento de ponto", "Avisa o colaborador que não registrou a jornada completa."),
        ("notif_banco_negativo", "Banco de horas negativo", "Avisa RH e colaborador quando o saldo fica abaixo de -2h."),
        ("notif_comprovante_email", "Comprovante por e-mail", "Envia o comprovante ao colaborador a cada batida."),
        ("notif_totem_offline", "Totem offline", "Avisa quando um equipamento passa de 10 min sem sinal."),
    ]

    if request.method == "POST":
        for campo, _rotulo, _ajuda in campos:
            setattr(config, campo, request.POST.get(campo) == "on")
        config.email_notificacoes = (request.POST.get("email_notificacoes") or "").strip()
        config.save()

        registrar_log(
            request=request,
            acao=LogAcesso.Acao.CONFIG,
            descricao="Preferências de notificação alteradas",
            objeto=empresa,
        )
        messages.success(request, "Preferências de notificação salvas.")
        return redirect("rh:notificacoes_config")

    return render(
        request,
        "rh/configuracoes/notificacoes.html",
        {
            "titulo": "Notificações",
            "menu_ativo": "configuracoes",
            "config": config,
            "campos": [
                {"nome": c, "rotulo": r, "ajuda": a, "ativo": getattr(config, c)}
                for c, r, a in campos
            ],
        },
    )


@rh_required
@empresa_ativa_required
def integracao(request):
    """
    Chaves de API da empresa (Seção 7.4).

    A chave em texto plano aparece **uma única vez**, no momento da
    emissão. Depois só o hash permanece — se o cliente perder, emite
    outra; não há como recuperar.
    """
    empresa = request.empresa_ativa

    # A aba some quando o cliente nao pode integrar; a view barra
    # tambem, porque esconder um link nao impede quem digita a URL.
    if not empresa.cliente.pode_integrar:
        messages.error(
            request,
            "As integrações não estão habilitadas para esta conta. "
            "Fale com a KS TEC.",
        )
        return redirect("rh:configuracoes")

    chaves = APIKey.objects.filter(empresa=empresa).order_by("-created_at")
    chave_nova = None

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "emitir":
            nome = (request.POST.get("nome") or "").strip()
            if not nome:
                messages.error(request, "Dê um nome à integração.")
                return redirect("rh:integracao")

            if not empresa.cliente.plano.tem_api:
                messages.error(
                    request,
                    f"O plano {empresa.cliente.plano} não inclui acesso à API. "
                    "Fale com a KS TEC para contratar.",
                )
                return redirect("rh:integracao")

            _, chave_nova = APIKey.emitir(
                empresa=empresa,
                nome=nome,
                criada_por=request.user,
                somente_leitura=request.POST.get("somente_leitura") == "on",
                rate_limit_hora=empresa.cliente.plano.rate_limit_api_hora,
            )
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.SEGURANCA,
                descricao=f"Chave de API emitida: {nome}",
                objeto=empresa,
            )
            messages.success(
                request,
                "Chave emitida. Copie agora — ela não será exibida novamente.",
            )
            chaves = APIKey.objects.filter(empresa=empresa).order_by("-created_at")

        elif acao == "revogar":
            chave = get_object_or_404(
                APIKey, pk=request.POST.get("chave"), empresa=empresa
            )
            chave.revogar()
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.SEGURANCA,
                descricao=f"Chave de API revogada: {chave.nome}",
                objeto=empresa,
            )
            messages.warning(request, f"Chave '{chave.nome}' revogada.")
            return redirect("rh:integracao")

    return render(
        request,
        "rh/configuracoes/integracao.html",
        {
            "titulo": "Integrações",
            "menu_ativo": "configuracoes",
            "empresa": empresa,
            "chaves": chaves,
            "chave_nova": chave_nova,
            "plano_tem_api": empresa.cliente.plano.tem_api,
        },
    )


@rh_required
@empresa_ativa_required
def slides_totem(request):
    """
    Tela de ociosidade do totem: várias imagens, em sequência.

    Uma tela ligada o dia inteiro na portaria é um canal que a empresa
    já tem e não usava — comunicado interno, campanha de segurança,
    aniversariantes. Antes havia uma imagem só.
    """
    from apps.clientes.models import SlideTotem

    empresa = request.empresa_ativa

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "adicionar":
            imagem = request.FILES.get("imagem")
            if imagem is None:
                messages.error(request, "Selecione uma imagem.")
                return redirect("rh:slides_totem")
            if imagem.size > 8 * 1024 * 1024:
                messages.error(
                    request,
                    "Imagem acima de 8 MB. O totem carrega isso a cada troca de "
                    "slide — comprima antes de enviar.",
                )
                return redirect("rh:slides_totem")

            ultima = empresa.slides.order_by("-ordem").first()
            SlideTotem.objects.create(
                empresa=empresa,
                imagem=imagem,
                legenda=(request.POST.get("legenda") or "")[:120],
                ordem=(ultima.ordem + 1) if ultima else 0,
                inicio_exibicao=request.POST.get("inicio") or None,
                fim_exibicao=request.POST.get("fim") or None,
            )
            _avisar_totens(empresa)
            messages.success(request, "Slide adicionado.")
            return redirect("rh:slides_totem")

        if acao == "remover":
            slide = get_object_or_404(
                SlideTotem, pk=request.POST.get("slide"), empresa=empresa
            )
            slide.delete()
            _avisar_totens(empresa)
            messages.warning(request, "Slide removido.")
            return redirect("rh:slides_totem")

        if acao == "reordenar":
            for indice, identificador in enumerate(request.POST.getlist("ordem")):
                SlideTotem.objects.filter(pk=identificador, empresa=empresa).update(
                    ordem=indice
                )
            _avisar_totens(empresa)
            messages.success(request, "Ordem atualizada.")
            return redirect("rh:slides_totem")

        if acao == "exibicao":
            empresa.slides_transicao = request.POST.get(
                "transicao", empresa.slides_transicao
            )
            try:
                empresa.slides_segundos = max(
                    3, min(120, int(request.POST.get("segundos", 8)))
                )
            except ValueError:
                pass
            # Conteudo do acervo: ligar/desligar e escolher quem manda
            # na tela quando a empresa tem slides proprios.
            empresa.telas_ambiente = bool(request.POST.get("telas_ambiente"))
            modo = request.POST.get("modo_slides")
            if modo in dict(empresa.ModoDosSlides.choices):
                empresa.modo_slides = modo
            empresa.save(update_fields=[
                "slides_transicao", "slides_segundos",
                "telas_ambiente", "modo_slides", "updated_at",
            ])
            # O conteudo montado fica em cache: sem descartar, a
            # escolha so valeria no proximo vencimento.
            from apps.clientes.ambiente_servico import esquecer

            esquecer(empresa.pk)
            _avisar_totens(empresa)
            messages.success(request, "Exibição atualizada.")
            return redirect("rh:slides_totem")

    from apps.clientes.models import Empresa

    return render(
        request,
        "rh/configuracoes/slides.html",
        {
            "titulo": "Tela de ociosidade",
            "menu_ativo": "configuracoes",
            "empresa": empresa,
            "slides": empresa.slides.order_by("ordem", "created_at"),
            "transicoes": Empresa.TransicaoSlide.choices,
        },
    )


@rh_required
@empresa_ativa_required
@require_POST
def recarregar_totens(request):
    """
    Manda os totens buscarem a configuração de novo.

    Existe porque nem toda mudança que afeta o quiosque passa pela tela
    de personalização — trocar a escala de um colaborador, por exemplo.
    E porque, no suporte, isto resolve metade dos casos sem alguém ir até
    o equipamento.

    **Não é mais uma recarga da página.** Recarregar derrubava a tela
    cheia, e o navegador não deixa reentrar sem gesto do usuário: o totem
    ficava com barra de endereço até alguém tocar na tela. O equipamento
    agora rebusca a configuração e aplica ao vivo.
    """
    empresa = request.empresa_ativa
    totens = empresa.totens.filter(ativo=True)
    for totem in totens:
        totem.solicitar_recarga()
    _avisar_totens(empresa)

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.CONFIG,
        descricao=f"Recarga solicitada para {totens.count()} totem(ns)",
        empresa=empresa,
    )
    messages.success(
        request,
        f"{totens.count()} totem(ns) vão atualizar a configuração assim que "
        "ficarem ociosos — atualizar no meio de um reconhecimento perderia "
        "a batida.",
    )
    return redirect(request.META.get("HTTP_REFERER") or "rh:equipamentos")


@rh_required
@empresa_ativa_required
def senha_totem(request):
    """
    Senha que abre o cadastro facial no proprio totem.

    Fica com o cliente, e nao so com a KS TEC, porque quem cadastra e
    quem esta na frente do equipamento — depender de nos para trocar uma
    senha de manutencao transformaria cada recadastro num chamado.

    A tela nunca mostra a senha atual: no banco ela vive com hash, e
    exibi-la exigiria guarda-la em texto puro. Diz apenas se existe.
    """
    cliente = request.empresa_ativa.cliente

    # A opcao e liberada pela KS TEC, por contrato. A tela existe para
    # definir a senha, e nao para ligar o recurso.
    if not cliente.cadastro_facial_no_totem:
        messages.error(
            request,
            "O cadastro facial pelo totem não está habilitado nesta conta. "
            "Fale com a KS TEC.",
        )
        return redirect("rh:configuracoes")

    if request.method == "POST":
        senha = request.POST.get("senha") or ""
        confirmacao = request.POST.get("confirmacao") or ""

        if len(senha) < 6:
            messages.error(request, "A senha precisa ter ao menos 6 caracteres.")
        elif senha != confirmacao:
            messages.error(request, "As senhas não coincidem.")
        else:
            cliente.definir_senha_totem(senha)
            registrar_log(
                request=request,
                acao=LogAcesso.Acao.CONFIGURACAO,
                descricao="Senha de manutenção do totem definida",
                objeto=cliente,
                empresa=request.empresa_ativa,
            )
            messages.success(
                request,
                "Senha definida. Use-a no totem para abrir o cadastro facial.",
            )
            return redirect("rh:senha_totem")

    return render(
        request,
        "rh/configuracoes/senha_totem.html",
        {"cliente": cliente, "tem_senha": bool(cliente.senha_totem)},
    )
