"""
Kronus — criacao do ambiente de demonstracao.

O ambiente e um `Cliente` de verdade, com `eh_demonstracao=True` e prazo.
Nao existe "modo demo" no resto do sistema: o visitante ve o produto que
vai contratar, e a conversao e apagar dois campos.

Os documentos (CNPJ e CPF) sao gerados com digito verificador valido mas
a partir de faixas reservadas a demonstracao, para que nenhum ambiente de
teste colida com uma empresa real nem produza um AFD com CNPJ de
terceiro.
"""
import logging
import random
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("kronus.comercial")

NOMES = [
    "Ana Beatriz Moreira", "Carlos Eduardo Lima", "Daniela Souza Rocha",
    "Eduardo Nunes Prado", "Fernanda Alves Pinto", "Gabriel Martins Reis",
    "Helena Castro Dias", "Igor Ramalho Costa", "Juliana Freitas Melo",
    "Lucas Andrade Vieira", "Mariana Teixeira Sá", "Nelson Barbosa Cruz",
]
CARGOS = [
    "Auxiliar administrativo", "Analista de suporte", "Vendedor",
    "Supervisor de equipe", "Assistente financeiro", "Recepcionista",
]


# ==============================================================
# Geradores de documento
# ==============================================================
def _digito(base: list[int], pesos: list[int]) -> int:
    soma = sum(d * p for d, p in zip(base, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def gerar_cpf() -> str:
    """CPF sinteticamente valido, para popular a demonstracao."""
    base = [random.randint(0, 9) for _ in range(9)]
    base.append(_digito(base, list(range(10, 1, -1))))
    base.append(_digito(base, list(range(11, 1, -1))))
    return "".join(map(str, base))


def gerar_cnpj() -> str:
    base = [random.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    base.append(_digito(base, pesos1))
    base.append(_digito(base, pesos2))
    return "".join(map(str, base))


def _plano_da_demonstracao(Plano):
    """
    Plano do ambiente de teste: o mais completo que estiver publicado.

    Quem experimenta precisa ver o produto inteiro — oferecer o plano
    basico esconderia justamente totem, facial e API, que sao o motivo de
    alguem pedir demonstracao.

    Se nao houver nenhum plano ativo, cria um plano interno em vez de
    estourar: a alternativa seria a capa devolver erro para o visitante
    por causa de uma configuracao do painel administrativo.
    """
    plano = (
        Plano.objects.filter(ativo=True)
        .order_by("-preco_mensal", "-max_colaboradores")
        .first()
    )
    if plano is not None:
        return plano

    plano, _ = Plano.objects.get_or_create(
        slug="demonstracao",
        defaults={
            "nome": "Demonstração",
            "descricao": "Plano interno usado pelos ambientes de teste.",
            "ativo": False,  # nao aparece na tabela de precos da capa
            "ordem": 99,
            "max_empresas": 1,
            "max_colaboradores": 25,
            "max_totems": 2,
            "tem_api": True,
            "tem_geofencing": True,
            "tem_totem": True,
            "tem_offline": True,
            "tem_banco_horas": True,
            "tem_webhook": True,
            "tem_portal_contador": True,
        },
    )
    return plano


# ==============================================================
# Criacao
# ==============================================================
@transaction.atomic
def criar_demonstracao(solicitacao, config=None) -> tuple[object, str]:
    """
    Cria Cliente, Empresa, usuario administrador e dados de exemplo.

    Devolve `(solicitacao, senha)`. A senha existe apenas aqui e no
    e-mail enviado em seguida — nao e persistida em lugar nenhum.
    """
    from apps.accounts.models import CustomUser
    from apps.clientes.models import Cliente
    from apps.comercial.models import ConfiguracaoComercial
    from apps.core.constants import TipoUsuario
    from apps.master.models import Plano

    config = config or ConfiguracaoComercial.carregar()
    agora = timezone.now()
    expira = agora + timedelta(hours=config.demo_horas)

    plano = _plano_da_demonstracao(Plano)

    cliente = Cliente.objects.create(
        razao_social=f"{solicitacao.empresa} (demonstração)",
        nome_fantasia=solicitacao.empresa[:200],
        cnpj=gerar_cnpj(),
        plano=plano,
        email_contato=solicitacao.email,
        telefone=solicitacao.whatsapp,
        responsavel=solicitacao.nome,
        eh_demonstracao=True,
        demo_expira_em=expira,
        observacoes=(
            f"Ambiente de demonstração criado automaticamente em "
            f"{agora:%d/%m/%Y %H:%M}. Origem: capa do site."
        ),
    )

    # Mesmo caminho do cadastro pelo Master: o cliente e, ele mesmo, uma
    # empresa. Duplicar a criacao aqui faria as duas divergirem com o
    # tempo.
    empresa = cliente.garantir_empresa_propria()

    senha = secrets.token_urlsafe(9)
    usuario = CustomUser.objects.create_user(
        email=solicitacao.email,
        password=senha,
        nome_completo=solicitacao.nome,
        tipo=TipoUsuario.CLIENTE,
        cliente=cliente,
        telefone=solicitacao.whatsapp,
    )
    usuario.empresas.add(empresa)

    _popular(empresa, config.demo_colaboradores_exemplo)

    solicitacao.cliente = cliente
    solicitacao.expira_em = expira
    solicitacao.save(update_fields=["cliente", "expira_em", "updated_at"])

    logger.info(
        "Demonstracao criada: cliente=%s empresa=%s expira=%s",
        cliente.pk, empresa.pk, expira.isoformat(),
    )
    return solicitacao, senha


def _popular(empresa, quantidade: int) -> None:
    """
    Cria colaboradores e algumas batidas, para que a demonstracao abra
    com tela cheia.

    Uma demonstracao vazia nao demonstra nada: quem entra ve tabelas sem
    linha e conclui que o sistema nao faz o que a capa prometeu.
    """
    from apps.rh.models import Colaborador

    hoje = timezone.localdate()
    escolhidos = random.sample(NOMES, min(quantidade, len(NOMES)))

    colaboradores = []
    for i, nome in enumerate(escolhidos):
        colaboradores.append(Colaborador.objects.create(
            empresa=empresa,
            cpf=gerar_cpf(),
            nome_completo=nome,
            cargo=random.choice(CARGOS),
            data_nascimento=hoje.replace(year=hoje.year - random.randint(22, 55)),
            data_admissao=hoje - timedelta(days=random.randint(60, 900)),
            ativo=True,
        ))

    _registrar_pontos(empresa, colaboradores)


def _registrar_pontos(empresa, colaboradores) -> None:
    """
    Gera batidas dos ultimos dias uteis pelo servico real de ponto.

    Usar o servico — e nao `Registro.objects.create` — e deliberado: as
    batidas da demonstracao passam pelo NSR e pela cadeia de hash como
    qualquer outra. Uma demonstracao cujo espelho nao fecha ou cujo AFD
    nao valida seria pior do que nenhuma.
    """
    from datetime import datetime, time

    from apps.core.constants import MetodoRegistro, TipoRegistro
    from apps.ponto.services import RegistroPontoService

    hoje = timezone.localdate()
    dias = [hoje - timedelta(days=d) for d in range(1, 8)]
    dias = [d for d in dias if d.weekday() < 5][:5]

    horarios = [
        (time(8, 0), TipoRegistro.ENTRADA),
        (time(12, 0), TipoRegistro.SAIDA),
        (time(13, 0), TipoRegistro.ENTRADA),
        (time(17, 0), TipoRegistro.SAIDA),
    ]

    for colaborador in colaboradores:
        for dia in dias:
            for hora, tipo in horarios:
                # Alguns minutos de variacao: batida cravada na hora cheia
                # nao existe na vida real e denuncia dado sintetico.
                deslocamento = timedelta(minutes=random.randint(-6, 9))
                momento = timezone.make_aware(
                    datetime.combine(dia, hora)
                ) + deslocamento
                try:
                    RegistroPontoService.registrar(
                        colaborador=colaborador,
                        metodo=MetodoRegistro.WEB,
                        tipo=tipo,
                        momento=momento,
                        observacao="Batida de demonstração",
                        # As batidas sao geradas em bloco, entao o
                        # intervalo minimo entre marcacoes nao se aplica:
                        # ele existe para conter duplo clique de gente,
                        # nao carga de dado de exemplo.
                        validar_intervalo=False,
                    )
                except Exception:
                    logger.debug("Batida de demonstracao ignorada", exc_info=True)
                    return


# ==============================================================
# Expiracao
# ==============================================================
def expirar_demonstracoes() -> int:
    """
    Suspende as demonstracoes vencidas. Idempotente.

    Suspende em vez de apagar: quem testou e voltou dois dias depois
    encontra o ambiente inteiro ao contratar, e o comercial enxerga o
    historico de quem experimentou.
    """
    from apps.clientes.models import Cliente
    from apps.comercial.models import SolicitacaoDemonstracao

    agora = timezone.now()
    vencidas = SolicitacaoDemonstracao.objects.filter(
        status=SolicitacaoDemonstracao.Status.ATIVA, expira_em__lte=agora,
    ).select_related("cliente")

    total = 0
    for solicitacao in vencidas:
        if solicitacao.cliente_id:
            Cliente.objects.filter(pk=solicitacao.cliente_id).update(
                suspenso=True,
                motivo_suspensao="Demonstração expirada",
                updated_at=agora,
            )
        solicitacao.status = SolicitacaoDemonstracao.Status.EXPIRADA
        solicitacao.save(update_fields=["status", "updated_at"])
        total += 1

    if total:
        logger.info("Demonstracoes expiradas: %s", total)
    return total
