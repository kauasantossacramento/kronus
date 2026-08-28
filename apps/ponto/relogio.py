"""
Kronus — verificacao do sincronismo com a Hora Legal Brasileira.

Anexo IX, requisito 2: o REP-P deve **manter** sincronismo com a HLB
disseminada pelo Observatorio Nacional, com variacao maxima de 30
segundos.

Configurar o NTP atende a metade do requisito. A outra metade e perceber
quando ele para de funcionar: se o `systemd-timesyncd` morrer, o relogio
comeca a derivar e nada acusa — as batidas continuam sendo gravadas, com
hora errada, e o problema so aparece quando alguem confere um espelho.

A medicao e feita em duas frentes, porque uma sozinha nao responde:

  · `timedatectl` diz **com quem** o sistema esta sincronizado. E ali que
    aparece `Reference=ONBR` e `Stratum=1` — a prova documental de que a
    fonte e o Observatorio Nacional, e nao um servidor qualquer.

  · uma consulta NTP direta diz **qual e o desvio agora**. O systemd nao
    publica o offset em formato legivel, e derivar isso dos carimbos que
    ele imprime nao funciona: eles vem com resolucao de um segundo, que e
    grosseira demais para a pergunta.
"""
import logging
import socket
import struct
import subprocess
import time

logger = logging.getLogger("kronus.ponto")

#: Acima disto, alerta. Folga deliberada sobre os 30s da norma: alertar
#: so ao cruzar o limite legal seria alertar quando ja se esta em
#: descumprimento.
DESVIO_ALERTA_SEGUNDOS = 5.0

#: Limite legal, para a mensagem dizer o quanto de folga restava.
DESVIO_LEGAL_SEGUNDOS = 30.0

#: Estrato 1 do NTP.br, ligados aos relogios atomicos do ON.
SERVIDORES_HLB = ("a.st1.ntp.br", "b.st1.ntp.br", "c.st1.ntp.br")

#: Diferenca entre a epoca do NTP (1900) e a do Unix (1970), em segundos.
EPOCA_NTP = 2_208_988_800


def medir_desvio(servidor: str, tempo_limite: float = 5.0) -> float | None:
    """
    Desvio do relogio local em relacao ao servidor NTP, em segundos.

    Implementacao direta em vez de biblioteca: sao quinze linhas, e
    acrescentar dependencia para um pacote de 48 bytes seria
    desproporcional.

    Devolve `None` quando o servidor nao responde — o que e informacao,
    nao erro: rede fora tambem impede manter o sincronismo.
    """
    pacote = b"\x1b" + 47 * b"\0"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(tempo_limite)
            envio = time.time()
            sock.sendto(pacote, (servidor, 123))
            dados, _ = sock.recvfrom(48)
            chegada = time.time()
    except (OSError, socket.timeout):
        return None

    if len(dados) < 48:
        return None

    # Campos 40..47: TransmitTimestamp, quando o servidor respondeu.
    segundos, fracao = struct.unpack("!II", dados[40:48])
    do_servidor = segundos - EPOCA_NTP + fracao / 2**32

    # Metade do tempo de ida e volta compensa a latencia da rede; sem
    # isso, uma conexao lenta apareceria como relogio atrasado.
    meio_caminho = (envio + chegada) / 2
    return do_servidor - meio_caminho


def fonte_configurada() -> dict:
    """
    Com quem o sistema diz estar sincronizado.

    `Reference=ONBR` e `Stratum=1` sao a prova documental de que a fonte
    e o Observatorio Nacional — exatamente o que o Anexo IX nomeia.
    """
    info = {"servidor": "", "estrato": None, "referencia": "", "ignorado": None}
    try:
        saida = subprocess.run(
            ["timedatectl", "show-timesync", "--all"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        # Windows e containers sem systemd caem aqui. Nao e falha do
        # relogio: e ausencia da ferramenta que descreve a configuracao.
        return info

    dados = {}
    for linha in saida.splitlines():
        chave, _, valor = linha.partition("=")
        dados[chave.strip()] = valor.strip()

    info["servidor"] = dados.get("ServerName") or dados.get("ServerAddress", "")

    mensagem = dados.get("NTPMessage", "")
    for campo, chave in (("Stratum=", "estrato"), ("Reference=", "referencia")):
        if campo in mensagem:
            info[chave] = mensagem.split(campo)[1].split(",")[0].strip(" }")
    if "Ignored=" in mensagem:
        info["ignorado"] = mensagem.split("Ignored=")[1].split(",")[0].strip(" }") == "yes"

    if info["estrato"] is not None:
        try:
            info["estrato"] = int(info["estrato"])
        except ValueError:
            info["estrato"] = None
    return info


def estado_do_relogio() -> dict:
    """
    Estado completo: fonte configurada e desvio medido agora.

    Devolve sempre um dicionario — nunca levanta. Uma falha ao *medir* o
    relogio nao pode derrubar nada; ela e, ela propria, o alerta.
    """
    estado = {
        "servidor": "",
        "estrato": None,
        "referencia": "",
        "fonte_e_o_on": False,
        "desvio_segundos": None,
        "dentro_do_limite": None,
        "erro": "",
    }
    estado.update(fonte_configurada())

    # `ONBR` e o identificador do Observatorio Nacional; estrato 1
    # significa ligado diretamente ao relogio atomico, sem intermediario.
    estado["fonte_e_o_on"] = (
        estado["referencia"].upper().startswith("ONBR") or estado["estrato"] == 1
    )

    for servidor in (estado["servidor"], *SERVIDORES_HLB):
        if not servidor:
            continue
        desvio = medir_desvio(servidor)
        if desvio is not None:
            estado["desvio_segundos"] = abs(desvio)
            estado["dentro_do_limite"] = abs(desvio) < DESVIO_ALERTA_SEGUNDOS
            estado["servidor_medido"] = servidor
            return estado

    estado["erro"] = "nenhum servidor da HLB respondeu"
    return estado
