"""
Kronus — verificação pública de documentos.

    /verificar/            formulário
    /verificar/<codigo>/   resultado

**Por que é público.** O código de verificação impresso num espelho de
ponto ou num comprovante só tem valor se puder ser conferido por quem
recebe o papel — o contador, o advogado, o auditor-fiscal. Exigir login
tornaria o código decorativo.

**O que é exposto, e o que não é.** A página confirma que *um documento
com aquele conteúdo existe* e mostra o mínimo para identificá-lo: nome
parcial, CPF mascarado, período e data de emissão. Não mostra as
marcações, nem o saldo, nem o nome completo — quem tem o papel na mão já
tem esses dados; quem não tem não deve obtê-los adivinhando códigos.

O código é derivado de um SHA-256 e tem 16 dígitos hexadecimais
(`A1B2-C3D4-E5F6-7890`). São 2^64 combinações; somado ao limite de
tentativas, varrer o espaço não é um caminho viável.
"""
import logging

from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.utils import mascarar_cpf, obter_ip

logger = logging.getLogger("kronus.relatorios")

#: Tentativas por IP por hora. Sem isso, o código viraria alvo de
#: varredura — e cada acerto revelaria a existência de um documento.
LIMITE_TENTATIVAS = 20
JANELA_SEGUNDOS = 3600


def _excedeu_limite(request) -> bool:
    chave = f"kronus:verificar:{obter_ip(request) or 'desconhecido'}"
    tentativas = cache.get(chave, 0) + 1
    cache.set(chave, tentativas, JANELA_SEGUNDOS)
    return tentativas > LIMITE_TENTATIVAS


def _normalizar(codigo: str) -> str:
    """Aceita com ou sem hífen, em qualquer caixa."""
    return "".join(c for c in (codigo or "").upper() if c.isalnum())


def _primeiro_nome(nome: str) -> str:
    """
    "João da Silva Souza" → "João S."

    Suficiente para quem tem o documento confirmar que bate; insuficiente
    para quem está pescando.
    """
    partes = [p for p in (nome or "").split() if len(p) > 2]
    if not partes:
        return "—"
    if len(partes) == 1:
        return partes[0]
    return f"{partes[0]} {partes[-1][0]}."


def _buscar(codigo: str):
    """
    Procura o código entre espelhos e comprovantes.

    Compara o código **derivado** de cada hash em vez de guardar o código
    numa coluna: assim não existe um índice de códigos para vazar, e o
    valor conferido é sempre recalculado a partir do documento.
    """
    from apps.ponto.models import FechamentoMensal, RegistroPonto

    espelhos = FechamentoMensal.objects.filter(
        fechado=True, hash_documento__isnull=False
    ).exclude(hash_documento="").select_related("colaborador", "empresa")

    for espelho in espelhos.iterator():
        if _normalizar(espelho.codigo_verificacao) == codigo:
            return "espelho", espelho

    marcacoes = RegistroPonto.objects.select_related(
        "colaborador", "empresa"
    ).order_by("-data_hora")

    for registro in marcacoes.iterator():
        if _normalizar(registro.codigo_verificacao) == codigo:
            return "comprovante", registro

    return None, None


def verificar(request, codigo=None):
    """Formulário e resultado da conferência."""
    codigo_bruto = codigo or request.GET.get("codigo") or request.POST.get("codigo")

    if request.method == "POST" and codigo_bruto:
        return redirect("relatorios:verificar_codigo", codigo=_normalizar(codigo_bruto))

    contexto = {
        "titulo": "Verificar documento",
        "codigo": codigo_bruto or "",
    }

    if not codigo_bruto:
        return render(request, "relatorios/verificar.html", contexto)

    normalizado = _normalizar(codigo_bruto)
    if len(normalizado) != 16:
        contexto["erro"] = (
            "O código tem 16 caracteres, no formato A1B2-C3D4-E5F6-7890."
        )
        return render(request, "relatorios/verificar.html", contexto)

    if _excedeu_limite(request):
        logger.warning(
            "Limite de verificações excedido para %s", obter_ip(request)
        )
        contexto["erro"] = (
            "Muitas consultas seguidas. Aguarde alguns minutos e tente novamente."
        )
        return render(request, "relatorios/verificar.html", contexto, status=429)

    tipo, documento = _buscar(normalizado)

    if documento is None:
        contexto["nao_encontrado"] = True
        return render(request, "relatorios/verificar.html", contexto)

    if tipo == "espelho":
        # A conferência de verdade: o hash gravado ainda corresponde ao
        # conteúdo? Se o espelho foi alterado depois de assinado, aqui
        # aparece.
        from apps.relatorios.generators import EspelhoPontoGenerator

        atual = EspelhoPontoGenerator(
            documento.colaborador, documento.ano, documento.mes
        ).contexto()["hash_documento"]
        integro = atual == documento.hash_documento

        contexto["resultado"] = {
            "tipo": "Espelho de ponto",
            "referencia": f"{documento.mes:02d}/{documento.ano}",
            "pessoa": _primeiro_nome(documento.colaborador.nome_exibicao),
            "cpf": mascarar_cpf(documento.colaborador.cpf),
            "empresa": documento.empresa.nome_exibicao,
            "emitido_em": documento.fechado_em or documento.updated_at,
            "assinado": documento.assinado,
            "assinado_em": documento.assinado_em,
            "integro": integro,
            "hash": documento.hash_documento,
        }
    else:
        from apps.core.utils import gerar_hash_registro

        recalculado = gerar_hash_registro(
            colaborador_id=documento.colaborador_id,
            data_hora=documento.data_hora,
            nsr=documento.nsr,
            salt_empresa=documento.empresa.salt_registro,
            hash_anterior=documento.hash_anterior or "",
        )
        contexto["resultado"] = {
            "tipo": "Comprovante de marcação",
            "referencia": (
                f"NSR {documento.nsr} · "
                f"{timezone.localtime(documento.data_hora):%d/%m/%Y %H:%M}"
            ),
            "pessoa": _primeiro_nome(documento.colaborador.nome_exibicao),
            "cpf": mascarar_cpf(documento.colaborador.cpf),
            "empresa": documento.empresa.nome_exibicao,
            "emitido_em": documento.created_at,
            "cancelado": documento.cancelado,
            "integro": recalculado == documento.hash_registro,
            "hash": documento.hash_registro,
        }

    return render(request, "relatorios/verificar.html", contexto)
