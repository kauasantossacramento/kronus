"""
Kronus — validações de registro de ponto.

Cada função levanta `RegistroInvalido` com uma mensagem destinada ao
usuário final. As regras seguem a Seção 14 do plano.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.utils import distancia_haversine


class RegistroInvalido(Exception):
    """Impede a criação de um registro de ponto."""

    def __init__(self, mensagem: str, codigo: str = "invalido", detalhes: dict = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.detalhes = detalhes or {}


class ForaDaAreaAutorizada(RegistroInvalido):
    """Geofencing bloqueante (Seção 8.3)."""


def validar_colaborador_apto(colaborador):
    """O colaborador precisa estar ativo e com vínculo vigente."""
    if not colaborador.ativo:
        raise RegistroInvalido(
            "Colaborador inativo. Fale com o RH.", codigo="colaborador_inativo"
        )
    hoje = timezone.localdate()
    if colaborador.data_admissao and colaborador.data_admissao > hoje:
        raise RegistroInvalido(
            "A data de admissão deste colaborador ainda não chegou.",
            codigo="antes_da_admissao",
        )
    if colaborador.data_demissao and colaborador.data_demissao < hoje:
        raise RegistroInvalido(
            "Colaborador desligado. Registro não permitido.", codigo="desligado"
        )


def validar_empresa_operacional(empresa):
    if not empresa.ativo:
        raise RegistroInvalido("Empresa inativa.", codigo="empresa_inativa")
    cliente = empresa.cliente
    if cliente.suspenso:
        raise RegistroInvalido(
            "A assinatura desta empresa está suspensa. Fale com o suporte.",
            codigo="cliente_suspenso",
        )


def validar_intervalo_minimo(colaborador, momento=None, segundos=None):
    """
    Bloqueia batida repetida logo após a anterior.

    Protege contra o toque duplo no totem, o clique repetido no navegador
    e o reenvio de formulário — situações em que a segunda marcação é
    engano, não jornada. Uma entrada duplicada suja o pareamento do dia e
    obriga o RH a um ajuste manual, que é mais caro e mais frágil na
    auditoria do que evitar o problema.

    **O prazo é da empresa, não do sistema.** Cada operação tem um ritmo:
    numa fábrica com turno único, 10 minutos são seguros; num hospital
    com plantão fracionado, podem barrar marcação legítima. Por isso
    `ConfiguracaoEmpresa.minutos_entre_marcacoes` manda, e zero desliga
    a trava. O valor do settings é apenas o piso técnico, para o caso de
    a empresa não ter configuração.
    """
    from apps.ponto.models import RegistroPonto

    if segundos is None:
        config = getattr(colaborador.empresa, "config", None)
        minutos = getattr(config, "minutos_entre_marcacoes", None)
        if minutos is not None:
            if minutos == 0:
                return          # a empresa desligou a trava
            segundos = minutos * 60
        else:
            segundos = settings.INTERVALO_MINIMO_ENTRE_BATIDAS_SEGUNDOS

    momento = momento or timezone.now()

    ultimo = (
        RegistroPonto.objects.filter(colaborador=colaborador, cancelado=False)
        .order_by("-data_hora")
        .first()
    )
    if ultimo is None:
        return
    decorrido = (momento - ultimo.data_hora).total_seconds()
    if 0 <= decorrido < segundos:
        faltam = int(segundos - decorrido)
        if faltam >= 60:
            minutos = (faltam + 59) // 60
            texto = f"Aguarde {minutos} minuto{'s' if minutos != 1 else ''}"
        else:
            texto = f"Aguarde {faltam} segundo{'s' if faltam != 1 else ''}"
        raise RegistroInvalido(
            f"{texto} para registrar novamente. Seu último ponto foi às "
            f"{timezone.localtime(ultimo.data_hora):%H:%M}.",
            codigo="intervalo_minimo",
            detalhes={"segundos_restantes": faltam},
        )


def validar_geofencing(empresa, latitude, longitude):
    """
    Avalia a cerca virtual da empresa.

    Devolve `(fora_da_area, distancia_metros)`. Levanta
    `ForaDaAreaAutorizada` apenas quando a empresa configurou bloqueio;
    caso contrário o registro é aceito e sinalizado com a flag.
    """
    if not empresa.geofencing_ativo:
        return False, None
    if empresa.geofencing_lat is None or empresa.geofencing_lng is None:
        return False, None
    if latitude is None or longitude is None:
        if empresa.geofencing_bloqueia:
            raise ForaDaAreaAutorizada(
                "Não foi possível obter sua localização. Autorize o acesso ao GPS "
                "para registrar o ponto.",
                codigo="sem_geolocalizacao",
            )
        return True, None

    distancia = distancia_haversine(
        float(latitude),
        float(longitude),
        float(empresa.geofencing_lat),
        float(empresa.geofencing_lng),
    )
    fora = distancia > empresa.geofencing_raio
    if fora and empresa.geofencing_bloqueia:
        raise ForaDaAreaAutorizada(
            f"Você está a {int(distancia)} m do local autorizado "
            f"(limite: {empresa.geofencing_raio} m).",
            codigo="fora_da_area",
            detalhes={"distancia": int(distancia)},
        )
    return fora, distancia


def detectar_gps_suspeito(colaborador, latitude, longitude, precisao=None, momento=None):
    """
    Heurística antifraude para GPS fictício (Seção 8.3).

    Sinaliza — nunca bloqueia sozinha — quando:
      * a precisão informada é boa demais para ser real (< 1 m);
      * as coordenadas são exatamente idênticas às da última batida
        com precisão suspeita;
      * o deslocamento desde a última batida exigiria velocidade
        superior a 900 km/h (voo comercial).
    """
    from apps.ponto.models import RegistroPonto

    if latitude is None or longitude is None:
        return False

    if precisao is not None and 0 <= precisao < 1:
        return True

    momento = momento or timezone.now()
    anterior = (
        RegistroPonto.objects.filter(
            colaborador=colaborador, cancelado=False, latitude__isnull=False
        )
        .order_by("-data_hora")
        .first()
    )
    if anterior is None:
        return False

    horas = (momento - anterior.data_hora).total_seconds() / 3600
    if horas <= 0:
        return False
    metros = distancia_haversine(
        float(latitude), float(longitude), float(anterior.latitude), float(anterior.longitude)
    )
    velocidade_kmh = (metros / 1000) / horas
    return velocidade_kmh > 900


def validar_totem_autorizado(totem, colaborador):
    """
    Regra 12 da Seção 14: o colaborador só é reconhecido em totens da
    sua empresa ou do grupo vinculado.
    """
    if totem is None:
        return
    if not totem.ativo:
        raise RegistroInvalido("Totem inativo.", codigo="totem_inativo")
    empresas = totem.empresas_atendidas().values_list("pk", flat=True)
    if colaborador.empresa_id not in set(empresas):
        raise RegistroInvalido(
            "Este colaborador não está autorizado neste equipamento.",
            codigo="totem_nao_autorizado",
        )


def validar_data_hora(momento, tolerancia_futuro_minutos=5):
    """Impede registros no futuro (relógio do dispositivo adulterado)."""
    limite = timezone.now() + timedelta(minutes=tolerancia_futuro_minutos)
    if momento > limite:
        raise RegistroInvalido(
            "Data/hora do registro está no futuro. Verifique o relógio do dispositivo.",
            codigo="data_futura",
        )
