"""
Kronus — geração de documentos.

`ComprovanteGenerator`   comprovante de registro de ponto (Portaria 671)
`EspelhoPontoGenerator`  espelho de ponto mensal com hash de integridade

Ambos renderizam um template Django e convertem para PDF com WeasyPrint.

**Import tardio do WeasyPrint:** a biblioteca depende do GTK, que não
existe por padrão no Windows (Seção 16.2 do plano). Importá-la no topo
do módulo derrubaria o projeto inteiro em máquinas de desenvolvimento.
Aqui ela é carregada só na hora de gerar o PDF, e `pdf_disponivel()`
permite às views oferecerem a versão HTML quando o PDF não é possível.
"""
import calendar
import logging
from datetime import date, timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.utils import gerar_hash_documento, hash_curto, minutos_para_hhmm

logger = logging.getLogger("kronus.relatorios")


class PDFIndisponivel(RuntimeError):
    """WeasyPrint não pôde ser carregado neste ambiente."""


def pdf_disponivel() -> bool:
    """Informa se este ambiente consegue gerar PDF."""
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:
        return False


def html_para_pdf(html: str, base_url: str = None) -> bytes:
    """Converte HTML em PDF. Levanta `PDFIndisponivel` se faltar o WeasyPrint."""
    try:
        from weasyprint import HTML
    except Exception as exc:  # GTK ausente, típico do Windows sem MSYS2
        raise PDFIndisponivel(
            "Geração de PDF indisponível neste ambiente: o WeasyPrint requer "
            "as bibliotecas GTK/Pango. Em produção (contêiner Linux) elas já "
            "estão instaladas."
        ) from exc

    buffer = BytesIO()
    HTML(string=html, base_url=base_url).write_pdf(buffer)
    return buffer.getvalue()


# ══════════════════════════════════════════════════════════════
# Comprovante de registro de ponto
# ══════════════════════════════════════════════════════════════
class ComprovanteGenerator:
    """
    Comprovante entregue ao trabalhador a cada batida.

    Conteúdo exigido pela Portaria 671 (Seção 8.1 do plano): identificação
    do empregador e do empregado, data/hora, NSR e código de verificação
    derivado do hash do registro.
    """

    template = "relatorios/comprovante.html"

    def __init__(self, registro):
        self.registro = registro

    def contexto(self) -> dict:
        registro = self.registro
        empresa = registro.empresa
        colaborador = registro.colaborador
        return {
            "registro": registro,
            "empresa": empresa,
            "colaborador": colaborador,
            "momento": timezone.localtime(registro.data_hora),
            "codigo_verificacao": hash_curto(registro.hash_registro),
            "emitido_em": timezone.localtime(),
        }

    def render_html(self) -> str:
        return render_to_string(self.template, self.contexto())

    def render_pdf(self) -> bytes:
        return html_para_pdf(self.render_html())

    def nome_arquivo(self) -> str:
        momento = timezone.localtime(self.registro.data_hora)
        return (
            f"comprovante_{self.registro.colaborador.cpf}_"
            f"{momento:%Y%m%d_%H%M%S}_nsr{self.registro.nsr}.pdf"
        )

    def salvar(self):
        """Gera o PDF e o anexa ao registro."""
        conteudo = self.render_pdf()
        self.registro.comprovante_pdf.save(
            self.nome_arquivo(), ContentFile(conteudo), save=False
        )
        # `comprovante_pdf` está entre os poucos campos mutáveis de um
        # registro de ponto — ver RegistroPonto.CAMPOS_MUTAVEIS.
        self.registro.save(update_fields=["comprovante_pdf", "updated_at"])
        return self.registro.comprovante_pdf


# ══════════════════════════════════════════════════════════════
# Espelho de ponto
# ══════════════════════════════════════════════════════════════
class EspelhoPontoGenerator:
    """
    Espelho de ponto mensal (Seção 8.5 do plano).

    Traz o dia a dia com marcações e totais, o resumo do período e um
    **hash de integridade** exibido como código de verificação — é ele
    que permite conferir depois que o documento não foi adulterado.
    """

    template = "relatorios/espelho_ponto.html"

    def __init__(self, colaborador, ano: int, mes: int):
        self.colaborador = colaborador
        self.ano = ano
        self.mes = mes
        self._contexto = None

    # -- período ------------------------------------------------
    @property
    def data_inicio(self) -> date:
        return date(self.ano, self.mes, 1)

    @property
    def data_fim(self) -> date:
        ultimo_dia = calendar.monthrange(self.ano, self.mes)[1]
        return date(self.ano, self.mes, ultimo_dia)

    # -- dados --------------------------------------------------
    def linhas(self) -> list[dict]:
        """Uma linha por dia do mês, com as marcações e os totais."""
        from apps.ponto.models import BancoHoras, RegistroPonto

        bancos = {
            b.data: b
            for b in BancoHoras.objects.filter(
                colaborador=self.colaborador,
                data__gte=self.data_inicio,
                data__lte=self.data_fim,
            )
        }
        registros_por_dia: dict[date, list] = {}
        consulta = (
            RegistroPonto.objects.filter(
                colaborador=self.colaborador,
                cancelado=False,
                data_hora__date__gte=self.data_inicio,
                data_hora__date__lte=self.data_fim,
            )
            .order_by("data_hora")
        )
        for registro in consulta:
            dia = timezone.localtime(registro.data_hora).date()
            registros_por_dia.setdefault(dia, []).append(registro)

        linhas = []
        dia = self.data_inicio
        while dia <= self.data_fim:
            banco = bancos.get(dia)
            marcacoes = registros_por_dia.get(dia, [])
            horarios = [timezone.localtime(r.data_hora) for r in marcacoes]
            # O espelho impresso tem quatro colunas fixas de marcação;
            # preenchemos aqui para o template não precisar de aritmética.
            colunas = [h.strftime("%H:%M") for h in horarios[:4]]
            colunas += [""] * (4 - len(colunas))
            linhas.append(
                {
                    "data": dia,
                    "dia_semana": dia.strftime("%a"),
                    "marcacoes": horarios,
                    "colunas": colunas,
                    "excedentes": [h.strftime("%H:%M") for h in horarios[4:]],
                    "nsrs": [r.nsr for r in marcacoes],
                    "banco": banco,
                    "trabalhado": minutos_para_hhmm(
                        banco.minutos_trabalhados if banco else 0, com_sinal=False
                    ),
                    "esperado": minutos_para_hhmm(
                        banco.minutos_esperados if banco else 0, com_sinal=False
                    ),
                    "extras": minutos_para_hhmm(
                        banco.minutos_extras if banco else 0, com_sinal=False
                    ),
                    "noturnas": minutos_para_hhmm(
                        banco.minutos_noturnos if banco else 0, com_sinal=False
                    ),
                    "saldo": minutos_para_hhmm(banco.saldo_dia if banco else 0),
                    "status": banco.status if banco else "",
                }
            )
            dia += timedelta(days=1)
        return linhas

    def contexto(self) -> dict:
        if self._contexto is not None:
            return self._contexto

        from apps.ponto.services import ConsolidacaoService

        resumo = ConsolidacaoService.resumo_periodo(
            self.colaborador, self.data_inicio, self.data_fim
        )
        linhas = self.linhas()

        self._contexto = {
            "colaborador": self.colaborador,
            "empresa": self.colaborador.empresa,
            "ano": self.ano,
            "mes": self.mes,
            "data_inicio": self.data_inicio,
            "data_fim": self.data_fim,
            "linhas": linhas,
            "resumo": resumo,
            "totais": {
                "trabalhado": minutos_para_hhmm(
                    resumo["minutos_trabalhados"], com_sinal=False
                ),
                "esperado": minutos_para_hhmm(
                    resumo["minutos_esperados"], com_sinal=False
                ),
                "extras": minutos_para_hhmm(resumo["minutos_extras"], com_sinal=False),
                "noturnas": minutos_para_hhmm(
                    resumo["minutos_noturnos"], com_sinal=False
                ),
                "atraso": minutos_para_hhmm(resumo["minutos_atraso"], com_sinal=False),
                "saldo_anterior": minutos_para_hhmm(resumo["saldo_anterior"]),
                "saldo_periodo": minutos_para_hhmm(resumo["saldo_periodo"]),
                "saldo_final": minutos_para_hhmm(resumo["saldo_final"]),
            },
            "emitido_em": timezone.localtime(),
        }
        self._contexto["hash_documento"] = self.calcular_hash()
        self._contexto["codigo_verificacao"] = hash_curto(
            self._contexto["hash_documento"]
        )
        return self._contexto

    def calcular_hash(self) -> str:
        """
        Hash do conteúdo factual do espelho — CPF, período e a sequência
        de marcações com seus NSRs. Independe da diagramação, de modo
        que reimprimir o documento produz o mesmo código.
        """
        contexto = self._contexto or {}
        partes = [
            self.colaborador.cpf,
            self.colaborador.empresa.cnpj,
            f"{self.ano}-{self.mes:02d}",
        ]
        for linha in contexto.get("linhas", []):
            marcacoes = ",".join(m.strftime("%H:%M:%S") for m in linha["marcacoes"])
            nsrs = ",".join(str(n) for n in linha["nsrs"])
            partes.append(f"{linha['data'].isoformat()}|{marcacoes}|{nsrs}")
        return gerar_hash_documento("\n".join(partes))

    # -- saída --------------------------------------------------
    def render_html(self) -> str:
        return render_to_string(self.template, self.contexto())

    def render_pdf(self) -> bytes:
        return html_para_pdf(self.render_html())

    def nome_arquivo(self) -> str:
        return (
            f"espelho_{self.colaborador.cpf}_{self.ano}{self.mes:02d}.pdf"
        )

    def salvar_em(self, fechamento):
        """Anexa o PDF e o hash a um `FechamentoMensal`."""
        contexto = self.contexto()
        conteudo = self.render_pdf()
        fechamento.espelho_pdf.save(
            self.nome_arquivo(), ContentFile(conteudo), save=False
        )
        fechamento.hash_documento = contexto["hash_documento"]
        fechamento.save(update_fields=["espelho_pdf", "hash_documento", "updated_at"])
        return fechamento
