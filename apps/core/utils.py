"""
Kronus — utilitarios de dominio.

Reune as funcoes puras usadas em todo o sistema:
    * validacao/formatacao de CPF e CNPJ
    * mascaramento de CPF (LGPD / exibicao no totem)
    * geracao do hash encadeado de registro de ponto (Portaria 671)
    * distancia geodesica (Haversine) para geofencing
    * helpers de requisicao (IP real, user agent)
"""
import hashlib
import math
import re
import secrets
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

# ==============================================================
# CPF
# ==============================================================
CPF_INVALIDOS = {str(i) * 11 for i in range(10)}


def apenas_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    """Valida CPF pelos dois digitos verificadores."""
    cpf = apenas_digitos(cpf)
    if len(cpf) != 11 or cpf in CPF_INVALIDOS:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11
        digito = 0 if digito == 10 else digito
        if digito != int(cpf[tamanho]):
            return False
    return True


def validar_cpf(valor: str) -> str:
    """Validator para uso em models/forms. Retorna o CPF normalizado."""
    cpf = apenas_digitos(valor)
    if not cpf_valido(cpf):
        raise ValidationError("CPF inválido.", code="cpf_invalido")
    return cpf


def formatar_cpf(cpf: str) -> str:
    """000.000.000-00"""
    cpf = apenas_digitos(cpf)
    if len(cpf) != 11:
        return cpf
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def mascarar_cpf(cpf: str) -> str:
    """
    ***.***.789-00 — formato exibido no totem e nos comprovantes.

    Oculta o **inicio e o meio**, deixando visiveis apenas os cinco
    ultimos caracteres. Isso basta para o colaborador se reconhecer na
    tela e para o RH distinguir homonimos, sem expor o documento.

    Mascarar so os tres primeiros digitos — como era antes — deixava
    oito dos onze a mostra. Num totem instalado em corredor, quem esta
    atras na fila le a tela.
    """
    cpf = apenas_digitos(cpf)
    if len(cpf) != 11:
        return "***"
    return f"***.***.{cpf[6:9]}-{cpf[9:]}"


# ==============================================================
# CNPJ
# ==============================================================
def cnpj_valido(cnpj: str) -> bool:
    cnpj = apenas_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_2 = [6] + pesos_1
    for pesos, pos in ((pesos_1, 12), (pesos_2, 13)):
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(pos))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(cnpj[pos]):
            return False
    return True


def validar_cnpj(valor: str) -> str:
    cnpj = apenas_digitos(valor)
    if not cnpj_valido(cnpj):
        raise ValidationError("CNPJ inválido.", code="cnpj_invalido")
    return cnpj


def formatar_cnpj(cnpj: str) -> str:
    """00.000.000/0000-00"""
    cnpj = apenas_digitos(cnpj)
    if len(cnpj) != 14:
        return cnpj
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


# ==============================================================
# PIS/PASEP
# ==============================================================
def pis_valido(pis: str) -> bool:
    pis = apenas_digitos(pis)
    if len(pis) != 11 or pis == pis[0] * 11:
        return False
    pesos = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(pis[i]) * pesos[i] for i in range(10))
    resto = soma % 11
    digito = 0 if resto < 2 else 11 - resto
    return digito == int(pis[10])


def validar_pis(valor: str) -> str:
    pis = apenas_digitos(valor)
    if pis and not pis_valido(pis):
        raise ValidationError("PIS/PASEP inválido.", code="pis_invalido")
    return pis


# ==============================================================
# Hash de integridade — Portaria 671/2021
# ==============================================================
def gerar_hash_registro(
    *,
    colaborador_id: int,
    data_hora: datetime,
    nsr: int,
    salt_empresa: str,
    hash_anterior: str = "",
) -> str:
    """
    SHA-256 do registro de ponto.

    Composicao (Secao 4.2 do plano + regra 3 da Secao 14):
        colaborador_id + data_hora (ISO) + nsr + salt_empresa + hash_anterior

    A inclusao do `hash_anterior` forma uma cadeia (blockchain-like):
    alterar um registro antigo invalida todos os subsequentes, o que
    materializa a integridade sequencial exigida pela Portaria 671.

    **O horario e normalizado para UTC antes de entrar no hash.** Sem
    isso, o mesmo instante produz hashes diferentes conforme o offset
    do datetime recebido: quem grava passa um horario local
    (`2026-08-17T08:00:00-03:00`), mas o banco devolve sempre UTC
    (`2026-08-17T11:00:00+00:00`) — duas strings, dois hashes, um unico
    instante. O resultado seria uma verificacao de integridade que
    reprova registros legitimos, exatamente o oposto do que a Portaria
    671 exige dela. O hash tem que ser funcao do *fato*, nao da forma
    como o fato foi escrito.

    Datetimes ingenuos (sem tzinfo) sao interpretados no fuso corrente,
    que e o que o Django faria ao salvar o mesmo valor.
    """
    momento = data_hora
    if timezone.is_naive(momento):
        momento = timezone.make_aware(momento)
    base = "|".join(
        [
            str(colaborador_id),
            momento.astimezone(dt_timezone.utc).isoformat(),
            str(nsr),
            salt_empresa,
            hash_anterior or "",
            settings.HASH_SALT_GLOBAL,
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def gerar_hash_documento(conteudo: str) -> str:
    """Hash de integridade de espelho de ponto / relatorios (Secao 8.5)."""
    return hashlib.sha256(conteudo.encode("utf-8")).hexdigest()


def hash_curto(hash_completo: str, grupos: int = 4, tamanho: int = 4) -> str:
    """
    Converte um SHA-256 em codigo legivel para impressao:
        A1B2-C3D4-E5F6-7890
    """
    limpo = (hash_completo or "").upper()[: grupos * tamanho]
    return "-".join(limpo[i : i + tamanho] for i in range(0, len(limpo), tamanho))


def gerar_token(nbytes: int = 32) -> str:
    """Token opaco para totens e API keys."""
    return secrets.token_urlsafe(nbytes)


def hash_api_key(chave: str) -> str:
    """API keys nunca sao guardadas em texto plano (Secao 9)."""
    return hashlib.sha256(f"{chave}{settings.HASH_SALT_GLOBAL}".encode("utf-8")).hexdigest()


# ==============================================================
# Geolocalizacao — Haversine (Secao 8.3)
# ==============================================================
RAIO_TERRA_METROS = 6_371_000.0


def distancia_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia em metros entre duas coordenadas geograficas."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * RAIO_TERRA_METROS * math.asin(math.sqrt(a))


def dentro_do_raio(
    lat_ponto: float, lon_ponto: float, lat_centro: float, lon_centro: float, raio_m: float
) -> bool:
    return distancia_haversine(lat_ponto, lon_ponto, lat_centro, lon_centro) <= raio_m


# ==============================================================
# Tempo
# ==============================================================
def minutos_para_hhmm(minutos: int | float, com_sinal: bool = True) -> str:
    """
    Converte minutos (podendo ser negativos) em '+08:30' / '-01:15'.
    Usado no banco de horas e no espelho de ponto.
    """
    total = int(round(minutos))
    sinal = "-" if total < 0 else ("+" if com_sinal else "")
    total = abs(total)
    return f"{sinal}{total // 60:02d}:{total % 60:02d}"


def hhmm_para_minutos(texto: str) -> int:
    """Aceita '08:30', '8:30', '-01:15'."""
    texto = (texto or "").strip()
    negativo = texto.startswith("-")
    texto = texto.lstrip("+-")
    if ":" not in texto:
        return 0
    horas, minutos = texto.split(":")[:2]
    total = int(horas) * 60 + int(minutos)
    return -total if negativo else total


def combinar_data_hora(dia: date, hora) -> datetime:
    """Combina date + time respeitando virada de dia em jornadas noturnas."""
    return datetime.combine(dia, hora)


def intervalos_sobrepostos(ini_a, fim_a, ini_b, fim_b) -> timedelta:
    """Duracao da interseccao entre dois intervalos de tempo."""
    inicio = max(ini_a, ini_b)
    fim = min(fim_a, fim_b)
    return max(fim - inicio, timedelta(0))


# ==============================================================
# Rede local (desenvolvimento e testes de totem)
# ==============================================================
def detectar_ip_lan() -> str | None:
    """
    Descobre o IP desta maquina na rede local.

    Abre um socket UDP para um endereco externo e le o endereco local
    escolhido pelo sistema — **nenhum pacote e enviado**, o UDP nao faz
    handshake. E o jeito confiavel de descobrir qual interface o sistema
    usaria para sair, sem depender de `hostname` (que costuma devolver
    127.0.0.1 no Linux) nem de enumerar placas de rede.

    Devolve None quando nao ha rede.
    """
    import socket

    tentativa = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        tentativa.settimeout(0.5)
        tentativa.connect(("8.8.8.8", 80))
        ip = tentativa.getsockname()[0]
        return ip if not ip.startswith("127.") else None
    except OSError:
        return None
    finally:
        tentativa.close()


def ips_locais() -> list[str]:
    """Todos os IPv4 desta maquina, com o da rota padrao em primeiro."""
    import socket

    encontrados = []
    principal = detectar_ip_lan()
    if principal:
        encontrados.append(principal)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            # 169.254.x.x e APIPA: a placa nao conseguiu IP do DHCP.
            if ip not in encontrados and not ip.startswith(("127.", "169.254.")):
                encontrados.append(ip)
    except OSError:
        pass
    return encontrados


# ==============================================================
# Requisicao HTTP
# ==============================================================
def obter_ip(request) -> str | None:
    """IP real do cliente, considerando proxy reverso (Nginx)."""
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def obter_user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:500]


# ==============================================================
# Documento do empregador: CNPJ ou CPF
# ==============================================================
#: Codigos do campo `tipo_identificador` do AFD (Anexo V) e do AEJ.
TIPO_IDENTIFICADOR_CNPJ = "1"
TIPO_IDENTIFICADOR_CPF = "2"


def tipo_identificador(documento: str) -> str:
    """
    `1` para CNPJ, `2` para CPF, conforme os anexos da Portaria 671.

    Derivado do proprio documento, e nao de um campo separado: um campo
    "tipo de pessoa" ao lado do numero e uma segunda verdade que pode
    contradizer a primeira — e quem descobre a divergencia e o auditor,
    lendo um AFD que declara CNPJ e traz onze digitos.
    """
    return (
        TIPO_IDENTIFICADOR_CPF
        if len(apenas_digitos(documento)) == 11
        else TIPO_IDENTIFICADOR_CNPJ
    )


def validar_cnpj_ou_cpf(valor: str) -> str:
    """
    Aceita empregador pessoa juridica **ou** pessoa fisica.

    O empregador doméstico e o produtor rural pessoa fisica registram
    ponto e sao alcancados pela Portaria 671 como qualquer outro; exigir
    CNPJ deles deixaria essa faixa inteira de fora do sistema.
    """
    digitos = apenas_digitos(valor)
    if len(digitos) == 11:
        if not cpf_valido(digitos):
            raise ValidationError("CPF inválido.", code="cpf_invalido")
        return digitos
    if not cnpj_valido(digitos):
        raise ValidationError(
            "Informe um CNPJ válido (14 dígitos) ou um CPF válido (11 dígitos).",
            code="documento_invalido",
        )
    return digitos


def formatar_cnpj_ou_cpf(valor: str) -> str:
    digitos = apenas_digitos(valor)
    return formatar_cpf(digitos) if len(digitos) == 11 else formatar_cnpj(digitos)


#: Nomes dos meses, em portugues, sem depender do sistema operacional.
#:
#: `calendar.month_name` devolve o que o locale do SO disser — e o
#: servidor de producao roda em ingles. O resultado era "August De 2026"
#: na tela do colaborador: metade traduzida pelo template, metade vinda
#: do sistema.
#:
#: Poderia vir da traducao do Django, mas ai dependeria de os catalogos
#: estarem compilados no servidor. Uma lista de doze palavras que nunca
#: mudam nao precisa desse risco.
MESES_PT = (
    "",  # indice 0 nao existe: os meses vao de 1 a 12
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def nome_do_mes(mes: int, capitalizar: bool = True) -> str:
    """
    O nome do mes em portugues.

    `capitalizar` porque o mesmo nome serve a "Agosto de 2026" no titulo
    e a "agosto" no meio de uma frase — e capitalizar no template
    obrigaria cada tela a lembrar disso.
    """
    try:
        nome = MESES_PT[int(mes)]
    except (IndexError, TypeError, ValueError):
        return ""
    return nome.capitalize() if capitalizar else nome


def meses_do_ano(capitalizar: bool = True) -> list[tuple[int, str]]:
    """Os doze meses como `(numero, nome)`, para montar um select."""
    return [(i, nome_do_mes(i, capitalizar)) for i in range(1, 13)]
