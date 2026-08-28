"""
Kronus — verificacao do sincronismo com a Hora Legal Brasileira.

Anexo IX, requisito 2: o REP-P deve **manter** sincronismo com a HLB
disseminada pelo Observatorio Nacional, com variacao maxima de 30
segundos.

Configurar o NTP atende a metade do requisito. A outra metade e perceber
quando ele para de funcionar: se o `systemd-timesyncd` morrer, o relogio
comeca a derivar e nada acusa — as batidas continuam sendo gravadas, com
hora errada, e o problema so aparece quando alguem confere um espelho.

O limite de alerta e bem menor que os 30 segundos da norma. Alertar so ao
cruzar o limite legal seria alertar quando ja se esta em
descumprimento; o objetivo e agir antes.
"""
import logging
import subprocess

logger = logging.getLogger("kronus.ponto")

#: Acima disto, alerta. Folga deliberada sobre os 30s da norma.
DESVIO_ALERTA_SEGUNDOS = 5.0

#: Limite legal, para a mensagem dizer o quanto falta.
DESVIO_LEGAL_SEGUNDOS = 30.0


def estado_do_relogio() -> dict:
    """
    Le o estado do sincronismo do sistema.

    Devolve sempre um dicionario — nunca levanta. Uma falha ao *medir* o
    relogio nao pode derrubar nada; ela e, ela propria, o alerta.
    """
    resultado = {
        "sincronizado": None,
        "servidor": "",
        "desvio_segundos": None,
        "dentro_do_limite": None,
        "erro": "",
    }

    try:
        saida = subprocess.run(
            ["timedatectl", "show-timesync", "--all"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError) as erro:
        # Windows e containers sem systemd caem aqui. Nao e falha do
        # relogio: e ausencia da ferramenta de medicao.
        resultado["erro"] = f"não foi possível consultar: {erro}"
        return resultado

    dados = {}
    for linha in saida.splitlines():
        if "=" in linha:
            chave, _, valor = linha.partition("=")
            dados[chave.strip()] = valor.strip()

    resultado["servidor"] = dados.get("ServerName") or dados.get("ServerAddress", "")

    bruto = dados.get("NTPMessage", "")
    offset = None
    if "offset=" in bruto:
        try:
            # O systemd escreve `{ Leap=0, offset=+3.2ms, delay=... }`:
            # a virgula e a chave vem coladas no valor.
            texto = bruto.split("offset=")[1].split()[0].strip(",}")
            offset = _para_segundos(texto)
        except (IndexError, ValueError):
            offset = None

    if offset is None:
        try:
            estado = subprocess.run(
                ["timedatectl", "status"],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout
            resultado["sincronizado"] = "synchronized: yes" in estado.lower()
        except (OSError, subprocess.SubprocessError):
            pass
        resultado["erro"] = resultado["erro"] or "desvio não reportado pelo sistema"
        return resultado

    resultado["sincronizado"] = True
    resultado["desvio_segundos"] = abs(offset)
    resultado["dentro_do_limite"] = abs(offset) < DESVIO_ALERTA_SEGUNDOS
    return resultado


def _para_segundos(texto: str) -> float:
    """Converte '+1.234ms', '-5us', '2.5s' em segundos."""
    texto = texto.strip()
    for sufixo, fator in (("ms", 1e-3), ("us", 1e-6), ("ns", 1e-9), ("s", 1.0)):
        if texto.endswith(sufixo):
            return float(texto[: -len(sufixo)]) * fator
    return float(texto)
