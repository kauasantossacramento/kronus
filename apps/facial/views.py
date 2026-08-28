"""
Kronus — cadastro biométrico facial (Seção 8.2 do plano).

    /facial/cadastro/<colaborador>/           tela de captura
    /facial/cadastro/<colaborador>/amostra/   recebe uma foto (JSON)
    /facial/cadastro/<colaborador>/consentir/ registra o consentimento LGPD
    /facial/cadastro/<colaborador>/excluir/   direito de exclusão (LGPD)

O consentimento vem **antes** da captura: dado biométrico é sensível sob
a LGPD e exige consentimento específico e destacado. Sem ele, a tela não
libera a câmera.
"""
import json
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from django.conf import settings

from apps.core.decorators import empresa_ativa_required, rh_required
from apps.core.models import LogAcesso
from apps.core.services import registrar_log
from apps.facial.models import FaceRegistro
from apps.facial.processors import ImagemInvalida
from apps.facial.providers import ErroReconhecimento
from apps.facial.services import FaceRecognitionService
from apps.rh.models import Colaborador

logger = logging.getLogger("kronus.facial")

#: Ângulos sugeridos, na ordem em que a tela os pede.
ROTEIRO_CAPTURA = [
    (FaceRegistro.Angulo.FRONTAL, "Olhe para a câmera", "Rosto centralizado e de frente."),
    (FaceRegistro.Angulo.ESQUERDA, "Vire levemente à esquerda", "Cerca de 20 graus."),
    (FaceRegistro.Angulo.DIREITA, "Vire levemente à direita", "Cerca de 20 graus."),
    (FaceRegistro.Angulo.CIMA, "Incline o queixo para cima", "Um pouco apenas."),
    (FaceRegistro.Angulo.BAIXO, "Incline o queixo para baixo", "Um pouco apenas."),
]


def _colaborador_no_escopo(request, colaborador_id) -> Colaborador:
    return get_object_or_404(
        Colaborador.objects.select_related("empresa", "empresa__config"),
        pk=colaborador_id,
        empresa=request.empresa_ativa,
    )


# ══════════════════════════════════════════════════════════════
# Tela de cadastro
# ══════════════════════════════════════════════════════════════
@rh_required
@empresa_ativa_required
def cadastro(request, colaborador_id):
    """Captura de 3 a 5 amostras por webcam."""
    colaborador = _colaborador_no_escopo(request, colaborador_id)
    servico = FaceRecognitionService()

    amostras = colaborador.registros_faciais.filter(ativo=True).order_by("created_at")

    return render(
        request,
        "facial/cadastro.html",
        {
            "titulo": f"Cadastro facial — {colaborador.nome_exibicao}",
            "menu_ativo": "colaboradores",
            "colaborador": colaborador,
            "amostras": amostras,
            "roteiro": [
                {"angulo": str(a), "titulo": t, "dica": d} for a, t, d in ROTEIRO_CAPTURA
            ],
            "minimo": settings.FACE_AMOSTRAS_MINIMAS,
            "maximo": settings.FACE_AMOSTRAS_MAXIMAS,
            "motor_disponivel": servico.disponivel,
            "motor_nome": servico.provedor.nome,
        },
    )


@rh_required
@empresa_ativa_required
@require_POST
def refazer_cadastro(request, colaborador_id):
    """
    Reinicia o cadastro facial do colaborador.

    Necessario quando a pessoa mudou de aparencia ou quando o cadastro
    original saiu ruim. Sem isso, a tela travava ao atingir o maximo de
    amostras e nao havia caminho de volta: fotos novas nunca alteravam
    o reconhecimento.
    """
    colaborador = _colaborador_no_escopo(request, colaborador_id)
    total = FaceRecognitionService().refazer_cadastro(colaborador)

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.ALTERACAO,
        descricao=(
            f"Cadastro facial reiniciado para {colaborador.nome_exibicao} "
            f"({total} amostra(s) aposentada(s))"
        ),
        objeto=colaborador,
    )
    messages.warning(
        request,
        f"Cadastro facial reiniciado. {total} amostra(s) foram desativadas — "
        "capture as novas para o colaborador voltar a ser reconhecido.",
    )
    return redirect("facial:cadastro", colaborador_id=colaborador.pk)


@rh_required
@empresa_ativa_required
@require_POST
def receber_amostra(request, colaborador_id):
    """
    Recebe uma foto da webcam e devolve o resultado do processamento.

    A resposta é JSON para a tela orientar o operador em tempo real:
    "aproxime-se", "apenas uma pessoa", "melhore a iluminação".
    """
    colaborador = _colaborador_no_escopo(request, colaborador_id)

    if not colaborador.consentimento_biometrico:
        return JsonResponse(
            {
                "ok": False,
                "codigo": "sem_consentimento",
                "mensagem": (
                    "Registre o consentimento do colaborador antes de capturar "
                    "os dados biométricos (LGPD)."
                ),
            },
            status=403,
        )

    total_ativas = colaborador.registros_faciais.filter(ativo=True).count()
    if total_ativas >= settings.FACE_AMOSTRAS_MAXIMAS:
        return JsonResponse(
            {
                "ok": False,
                "codigo": "limite_amostras",
                "mensagem": f"Limite de {settings.FACE_AMOSTRAS_MAXIMAS} amostras atingido.",
            },
            status=400,
        )

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"ok": False, "codigo": "payload_invalido", "mensagem": "Requisição inválida."},
            status=400,
        )

    servico = FaceRecognitionService()

    try:
        registro = servico.cadastrar_amostra(
            colaborador,
            payload.get("image"),
            angulo=payload.get("angulo", FaceRegistro.Angulo.FRONTAL),
        )
    except (ImagemInvalida, ErroReconhecimento) as erro:
        return JsonResponse(
            {"ok": False, "codigo": erro.codigo, "mensagem": erro.mensagem}, status=422
        )

    total = servico.consolidar_cadastro(colaborador)

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.ALTERACAO,
        descricao=(
            f"Amostra facial ({registro.get_angulo_display()}) cadastrada para "
            f"{colaborador.nome_exibicao}"
        ),
        objeto=colaborador,
    )

    return JsonResponse(
        {
            "ok": True,
            "amostra_id": registro.pk,
            "angulo": registro.angulo,
            "angulo_exibicao": registro.get_angulo_display(),
            "qualidade": registro.qualidade,
            "total_amostras": total,
            "minimo": settings.FACE_AMOSTRAS_MINIMAS,
            "completo": total >= settings.FACE_AMOSTRAS_MINIMAS,
        }
    )


@rh_required
@empresa_ativa_required
@require_POST
def registrar_consentimento(request, colaborador_id):
    """
    Consentimento explícito para tratamento de dado biométrico.

    A LGPD trata biometria como dado sensível (Art. 11): exige
    consentimento específico e destacado, não uma cláusula genérica no
    contrato de trabalho.
    """
    colaborador = _colaborador_no_escopo(request, colaborador_id)
    colaborador.registrar_consentimento_biometrico()

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.SEGURANCA,
        descricao=f"Consentimento biométrico registrado — {colaborador.nome_exibicao}",
        objeto=colaborador,
        metadados={"base_legal": "LGPD Art. 11, I — consentimento específico"},
    )
    messages.success(
        request,
        f"Consentimento registrado. Já é possível capturar as amostras de "
        f"{colaborador.primeiro_nome}.",
    )
    return redirect("facial:cadastro", colaborador_id=colaborador.pk)


@rh_required
@empresa_ativa_required
@require_POST
def excluir_amostra(request, colaborador_id, amostra_id):
    """Descarta uma amostra ruim e recalcula o embedding médio."""
    colaborador = _colaborador_no_escopo(request, colaborador_id)
    amostra = get_object_or_404(
        FaceRegistro, pk=amostra_id, colaborador=colaborador
    )
    amostra.delete()

    servico = FaceRecognitionService()
    total = servico.consolidar_cadastro(colaborador)

    messages.info(request, f"Amostra removida. Restam {total} amostra(s).")
    return redirect("facial:cadastro", colaborador_id=colaborador.pk)


@rh_required
@empresa_ativa_required
@require_POST
def excluir_biometria(request, colaborador_id):
    """
    Direito de exclusão da LGPD (Art. 18, VI).

    Apaga o embedding e todas as amostras. O colaborador volta a
    registrar o ponto pelo fallback de CPF, sem prejuízo à jornada.
    """
    colaborador = _colaborador_no_escopo(request, colaborador_id)

    FaceRecognitionService().remover_cadastro(colaborador)
    colaborador.consentimento_biometrico = False
    colaborador.consentimento_biometrico_em = None
    colaborador.save(
        update_fields=[
            "consentimento_biometrico",
            "consentimento_biometrico_em",
            "updated_at",
        ]
    )

    registrar_log(
        request=request,
        acao=LogAcesso.Acao.EXCLUSAO,
        descricao=f"Dados biométricos excluídos — {colaborador.nome_exibicao}",
        objeto=colaborador,
        metadados={"base_legal": "LGPD Art. 18, VI — eliminação de dados"},
    )
    messages.success(
        request,
        f"Dados biométricos de {colaborador.nome_exibicao} excluídos. "
        "O registro de ponto segue disponível pelo CPF.",
    )
    return redirect("rh:colaborador_detalhe", pk=colaborador.pk)
