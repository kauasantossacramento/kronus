"""
Kronus — endpoints públicos de integração (Seção 7.2 do plano).

    GET  /api/v1/colaboradores/          lista e detalhe
    GET  /api/v1/departamentos/
    GET  /api/v1/cargos/
    GET  /api/v1/escalas/
    GET  /api/v1/pontos/                 marcações, com filtros de período
    POST /api/v1/pontos/registrar/       registra uma marcação
    GET  /api/v1/pontos/{uuid}/verificar/  reconfere a integridade do hash
    GET  /api/v1/banco-horas/            apuração diária
    GET  /api/v1/banco-horas/resumo/     totais por colaborador no período
    GET  /api/v1/atestados/
    GET  /api/v1/relatorios/afd/         arquivo fiscal (texto puro)
    GET  /api/v1/relatorios/aej/
    GET  /api/v1/relatorios/espelho/

**A regra que atravessa tudo:** nenhum queryset parte de
`Model.objects.all()`. Todos partem de `self.empresas()`, que é o
conjunto de empresas que a credencial apresentada alcança. Uma chave de
Empresa alcança uma; uma chave de Cliente alcança todas as empresas
daquele cliente. Não existe caminho para uma terceira.

**Somente leitura, com uma exceção.** As integrações consomem dados; o
único POST é o registro de ponto, e ele exige uma chave marcada como
escrita (`APIKeyEscrita`). Cadastro de colaborador e ajuste de marcação
continuam exclusivos do painel — são atos com responsabilidade
trabalhista, e o rastro de quem fez precisa apontar para uma pessoa.
"""
import logging

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.authentication import APIKeyAuthentication
from apps.api.permissions import APIKeyAutenticada, APIKeyEscrita
from apps.api.serializers_publicos import (
    AtestadoSerializer,
    BancoHorasSerializer,
    CargoSerializer,
    ColaboradorSerializer,
    DepartamentoSerializer,
    EscalaSerializer,
    ContaSerializer,
    EspelhoSerializer,
    RegistrarPontoSerializer,
    RegistroPontoSerializer,
    ResumoBancoHorasSerializer,
    VerificacaoHashSerializer,
)
from apps.api.throttling import PlanoRateThrottle
from apps.core.constants import StatusDia
from apps.core.utils import minutos_para_hhmm
from apps.ponto.models import BancoHoras, EscalaTrabalho, RegistroPonto
from apps.rh.models import Atestado, Cargo, Colaborador, Departamento

logger = logging.getLogger("kronus.api")


def _data(valor, rotulo):
    """Converte `YYYY-MM-DD` num `date`, com erro legível."""
    if not valor:
        return None
    from datetime import date

    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({rotulo: "Use o formato AAAA-MM-DD."})


class BaseAPIPublica(viewsets.ReadOnlyModelViewSet):
    """
    Base de todos os recursos públicos.

    Concentra três decisões para que nenhuma ViewSet possa esquecê-las:
    a credencial aceita, o escopo de empresas e o rate limit por plano.
    """

    authentication_classes = (APIKeyAuthentication,)
    permission_classes = (APIKeyAutenticada,)
    throttle_classes = (PlanoRateThrottle,)
    lookup_field = "uuid"
    lookup_url_kwarg = "uuid"

    def empresas(self):
        """As empresas que esta credencial alcança. Nunca vazio aqui —
        a permissão já barrou quem não tem escopo."""
        return getattr(self.request, "api_empresas", None)

    def filtrar_por_empresa(self, queryset, campo="empresa"):
        return queryset.filter(**{f"{campo}__in": self.empresas()})


# ══════════════════════════════════════════════════════════════
# Estrutura organizacional
# ══════════════════════════════════════════════════════════════
@extend_schema(tags=["Estrutura"])
class DepartamentoViewSet(BaseAPIPublica):
    serializer_class = DepartamentoSerializer
    #: So para o gerador do OpenAPI descobrir o model. O queryset real
    #: vem de `get_queryset`, sempre restrito as empresas da credencial.
    queryset = Departamento.objects.none()

    def get_queryset(self):
        # `total_colaboradores` ja e uma property do model — anotar com
        # esse nome colide no carregamento. A anotacao usa outro nome e
        # o serializer aponta para ela, evitando um COUNT por linha.
        queryset = Departamento.objects.select_related("empresa").annotate(
            colaboradores_ativos=Count(
                "colaboradores", filter=Q(colaboradores__ativo=True)
            )
        )
        queryset = self.filtrar_por_empresa(queryset)
        if self.request.query_params.get("ativo") == "false":
            return queryset.order_by("nome")
        return queryset.filter(ativo=True).order_by("nome")


@extend_schema(tags=["Estrutura"])
class CargoViewSet(BaseAPIPublica):
    serializer_class = CargoSerializer
    queryset = Cargo.objects.none()

    def get_queryset(self):
        return self.filtrar_por_empresa(
            Cargo.objects.select_related("empresa")
        ).order_by("nome")


@extend_schema(tags=["Estrutura"])
class EscalaViewSet(BaseAPIPublica):
    serializer_class = EscalaSerializer
    queryset = EscalaTrabalho.objects.none()

    def get_queryset(self):
        return self.filtrar_por_empresa(
            EscalaTrabalho.objects.select_related("empresa")
        ).order_by("nome")


# ══════════════════════════════════════════════════════════════
# Colaboradores
# ══════════════════════════════════════════════════════════════
@extend_schema(
    tags=["Colaboradores"],
    parameters=[
        OpenApiParameter("cpf", str, description="Filtra por CPF (só dígitos)."),
        OpenApiParameter("matricula", str, description="Filtra por matrícula."),
        OpenApiParameter(
            "ativo", bool, description="Padrão: só ativos. Use `false` para incluir desligados."
        ),
        OpenApiParameter("departamento", str, description="UUID do departamento."),
        OpenApiParameter(
            "admitido_apos", str, description="Admissão a partir de (AAAA-MM-DD)."
        ),
        OpenApiParameter("busca", str, description="Trecho do nome."),
    ],
)
class ColaboradorViewSet(BaseAPIPublica):
    """
    Cadastro dos colaboradores.

    **Só ativos, por padrão.** Uma folha que consome esta API e recebe
    desligados silenciosamente pagaria gente que saiu. Quem precisa do
    histórico pede explicitamente `?ativo=false`.
    """

    serializer_class = ColaboradorSerializer
    queryset = Colaborador.objects.none()

    def get_queryset(self):
        parametros = self.request.query_params
        queryset = self.filtrar_por_empresa(
            Colaborador.objects.select_related("empresa", "departamento", "escala")
        )

        if parametros.get("ativo") != "false":
            queryset = queryset.filter(ativo=True)

        if cpf := parametros.get("cpf"):
            from apps.core.utils import apenas_digitos

            queryset = queryset.filter(cpf=apenas_digitos(cpf))

        if matricula := parametros.get("matricula"):
            queryset = queryset.filter(matricula=matricula)

        if departamento := parametros.get("departamento"):
            queryset = queryset.filter(departamento__uuid=departamento)

        if admitido := _data(parametros.get("admitido_apos"), "admitido_apos"):
            queryset = queryset.filter(data_admissao__gte=admitido)

        if busca := parametros.get("busca"):
            queryset = queryset.filter(
                Q(nome_completo__icontains=busca) | Q(nome_social__icontains=busca)
            )

        return queryset.order_by("nome_completo")


# ══════════════════════════════════════════════════════════════
# Registros de ponto
# ══════════════════════════════════════════════════════════════
@extend_schema(
    tags=["Ponto"],
    parameters=[
        OpenApiParameter("colaborador", str, description="UUID do colaborador."),
        OpenApiParameter("cpf", str, description="CPF do colaborador (só dígitos)."),
        OpenApiParameter("data_inicio", str, description="AAAA-MM-DD, inclusive."),
        OpenApiParameter("data_fim", str, description="AAAA-MM-DD, inclusive."),
        OpenApiParameter("nsr_maior_que", int, description="Paginação incremental por NSR."),
        OpenApiParameter(
            "incluir_cancelados", bool,
            description="Padrão: cancelados aparecem, marcados com `cancelado: true`."
        ),
    ],
)
class RegistroPontoViewSet(BaseAPIPublica):
    """
    Marcações de ponto.

    **`nsr_maior_que` é o caminho recomendado para sincronizar.** O NSR
    é sequencial e imutável por empresa; guardar o último NSR recebido e
    pedir os seguintes é mais barato e mais confiável do que paginar por
    data — uma marcação inserida com data retroativa (ajuste do RH) não
    escapa da sincronização, porque o NSR dela é novo.

    **Cancelados aparecem.** Uma marcação cancelada continua existindo
    na Portaria 671: ela é anulada, não apagada. Omiti-la faria a
    integração ver um buraco no NSR e suspeitar de adulteração.
    """

    serializer_class = RegistroPontoSerializer
    queryset = RegistroPonto.objects.none()
    permission_classes = (APIKeyEscrita,)

    def get_queryset(self):
        parametros = self.request.query_params
        queryset = self.filtrar_por_empresa(
            RegistroPonto.objects.select_related("colaborador", "empresa", "totem")
        )

        if colaborador := parametros.get("colaborador"):
            queryset = queryset.filter(colaborador__uuid=colaborador)

        if cpf := parametros.get("cpf"):
            from apps.core.utils import apenas_digitos

            queryset = queryset.filter(colaborador__cpf=apenas_digitos(cpf))

        if inicio := _data(parametros.get("data_inicio"), "data_inicio"):
            queryset = queryset.filter(data_hora__date__gte=inicio)

        if fim := _data(parametros.get("data_fim"), "data_fim"):
            queryset = queryset.filter(data_hora__date__lte=fim)

        if nsr := parametros.get("nsr_maior_que"):
            try:
                queryset = queryset.filter(nsr__gt=int(nsr))
            except ValueError:
                raise ValidationError({"nsr_maior_que": "Informe um número inteiro."})

        if parametros.get("incluir_cancelados") == "false":
            queryset = queryset.filter(cancelado=False)

        return queryset.order_by("nsr")

    # -- registro ------------------------------------------------
    @extend_schema(
        request=RegistrarPontoSerializer,
        responses={201: RegistroPontoSerializer},
        summary="Registra uma marcação de ponto",
    )
    @action(detail=False, methods=["post"], url_path="registrar")
    def registrar(self, request):
        """
        Cria uma marcação pelo mesmo service que o totem e o app usam.

        Nada aqui grava direto no banco: passa por
        `RegistroPontoService.registrar`, que reserva o NSR, encadeia o
        hash e dispara a consolidação. Um caminho paralelo quebraria a
        cadeia e invalidaria o AFD.
        """
        entrada = RegistrarPontoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data

        colaborador = (
            Colaborador.objects.select_related("empresa")
            .filter(uuid=dados["colaborador"], empresa__in=self.empresas())
            .first()
        )
        if colaborador is None:
            # Mesmo 404 para "não existe" e "existe em outro cliente":
            # distinguir permitiria descobrir UUIDs válidos alheios.
            raise NotFound("Colaborador não encontrado nesta conta.")

        if not colaborador.ativo:
            return Response(
                {"codigo": "colaborador_inativo",
                 "mensagem": "Colaborador desligado não registra ponto."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        data_hora = dados.get("data_hora") or timezone.now()
        if data_hora > timezone.now() + timezone.timedelta(minutes=5):
            # 5 min de folga para relógio dessincronizado do cliente;
            # além disso é marcação futura, que a Portaria não admite.
            return Response(
                {"codigo": "data_futura",
                 "mensagem": "Não é possível registrar marcação no futuro."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        from apps.core.constants import MetodoRegistro
        from apps.ponto.services import RegistroPontoService

        try:
            registro = RegistroPontoService.registrar(
                colaborador=colaborador,
                momento=data_hora,
                tipo=dados.get("tipo"),
                metodo=MetodoRegistro.API,
                latitude=dados.get("latitude"),
                longitude=dados.get("longitude"),
                observacao=dados.get("observacao", ""),
                request=request,
            )
        except Exception as erro:
            logger.warning("Registro por API recusado: %s", erro)
            return Response(
                {"codigo": "recusado", "mensagem": str(erro)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(
            RegistroPontoSerializer(registro).data, status=status.HTTP_201_CREATED
        )

    # -- verificação ---------------------------------------------
    @extend_schema(
        summary="Reconfere o hash de uma marcação",
        responses={200: VerificacaoHashSerializer},
    )
    @action(detail=True, methods=["get"], url_path="verificar")
    def verificar(self, request, uuid=None):
        """
        Recalcula o hash da marcação e compara com o gravado.

        Serve para uma auditoria externa confirmar, sem acesso ao banco,
        que o registro não foi adulterado depois de gravado.
        """
        registro = self.get_object()
        from apps.core.utils import gerar_hash_registro

        recalculado = gerar_hash_registro(
            colaborador_id=registro.colaborador_id,
            data_hora=registro.data_hora,
            nsr=registro.nsr,
            salt_empresa=registro.empresa.salt_registro,
            hash_anterior=registro.hash_anterior or "",
        )
        integro = recalculado == registro.hash_registro

        return Response({
            "uuid": str(registro.uuid),
            "nsr": registro.nsr,
            "hash_gravado": registro.hash_registro,
            "hash_recalculado": recalculado,
            "integro": integro,
            "mensagem": (
                "Registro íntegro." if integro else
                "DIVERGÊNCIA: o conteúdo do registro não corresponde ao hash gravado."
            ),
        })


# ══════════════════════════════════════════════════════════════
# Banco de horas
# ══════════════════════════════════════════════════════════════
@extend_schema(
    tags=["Banco de horas"],
    parameters=[
        OpenApiParameter("colaborador", str, description="UUID do colaborador."),
        OpenApiParameter("cpf", str, description="CPF do colaborador."),
        OpenApiParameter("data_inicio", str, description="AAAA-MM-DD."),
        OpenApiParameter("data_fim", str, description="AAAA-MM-DD."),
        OpenApiParameter("status", str, description="normal, falta, atestado, incompleto…"),
    ],
)
class BancoHorasViewSet(BaseAPIPublica):
    """Apuração diária consolidada."""

    serializer_class = BancoHorasSerializer
    queryset = BancoHoras.objects.none()

    def get_queryset(self):
        parametros = self.request.query_params
        queryset = self.filtrar_por_empresa(
            BancoHoras.objects.select_related("colaborador", "empresa"),
        )

        if colaborador := parametros.get("colaborador"):
            queryset = queryset.filter(colaborador__uuid=colaborador)

        if cpf := parametros.get("cpf"):
            from apps.core.utils import apenas_digitos

            queryset = queryset.filter(colaborador__cpf=apenas_digitos(cpf))

        if inicio := _data(parametros.get("data_inicio"), "data_inicio"):
            queryset = queryset.filter(data__gte=inicio)

        if fim := _data(parametros.get("data_fim"), "data_fim"):
            queryset = queryset.filter(data__lte=fim)

        if situacao := parametros.get("status"):
            queryset = queryset.filter(status=situacao)

        return queryset.order_by("colaborador__nome_completo", "data")

    @extend_schema(
        summary="Totais por colaborador no período",
        responses={200: ResumoBancoHorasSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="resumo")
    def resumo(self, request):
        """
        Agrega o período por colaborador — o formato que a folha consome.

        `saldo_anterior` é o acumulado no dia imediatamente anterior ao
        período; `saldo_final` é o acumulado no último dia dele. A folha
        precisa dos dois para saber quanto o mês *movimentou*, não só
        onde parou.
        """
        inicio = _data(request.query_params.get("data_inicio"), "data_inicio")
        fim = _data(request.query_params.get("data_fim"), "data_fim")
        if not inicio or not fim:
            raise ValidationError(
                {"detail": "Informe data_inicio e data_fim (AAAA-MM-DD)."}
            )
        if inicio > fim:
            raise ValidationError({"detail": "data_inicio é posterior a data_fim."})

        base = self.filtrar_por_empresa(
            BancoHoras.objects.select_related("colaborador")
        ).filter(data__gte=inicio, data__lte=fim)

        if colaborador := request.query_params.get("colaborador"):
            base = base.filter(colaborador__uuid=colaborador)

        agregado = (
            base.values(
                "colaborador__uuid", "colaborador__cpf",
                "colaborador__nome_completo", "colaborador__nome_social",
                "colaborador_id",
            )
            .annotate(
                minutos_trabalhados=Sum("minutos_trabalhados"),
                minutos_esperados=Sum("minutos_esperados"),
                minutos_extras=Sum("minutos_extras"),
                minutos_noturnos=Sum("minutos_noturnos"),
                minutos_atraso=Sum("minutos_atraso"),
                saldo_periodo=Sum("saldo_dia"),
                dias_falta=Count("pk", filter=Q(status=StatusDia.FALTA)),
                dias_atestado=Count("pk", filter=Q(status=StatusDia.ATESTADO)),
                dias_incompletos=Count("pk", filter=Q(status=StatusDia.INCOMPLETO)),
            )
            .order_by("colaborador__nome_completo")
        )

        linhas = []
        for item in agregado:
            colaborador_id = item["colaborador_id"]
            anterior = (
                BancoHoras.objects.filter(colaborador_id=colaborador_id, data__lt=inicio)
                .order_by("-data")
                .values_list("saldo_acumulado", flat=True)
                .first()
            ) or 0
            final = (
                BancoHoras.objects.filter(
                    colaborador_id=colaborador_id, data__gte=inicio, data__lte=fim
                )
                .order_by("-data")
                .values_list("saldo_acumulado", flat=True)
                .first()
            ) or anterior

            linhas.append({
                "colaborador": item["colaborador__uuid"],
                "colaborador_cpf": item["colaborador__cpf"],
                "colaborador_nome": (
                    item["colaborador__nome_social"] or item["colaborador__nome_completo"]
                ),
                "data_inicio": inicio,
                "data_fim": fim,
                "minutos_trabalhados": item["minutos_trabalhados"] or 0,
                "minutos_esperados": item["minutos_esperados"] or 0,
                "minutos_extras": item["minutos_extras"] or 0,
                "minutos_noturnos": item["minutos_noturnos"] or 0,
                "minutos_atraso": item["minutos_atraso"] or 0,
                "saldo_anterior": anterior,
                "saldo_periodo": item["saldo_periodo"] or 0,
                "saldo_final": final,
                "saldo_final_formatado": minutos_para_hhmm(final),
                "dias_falta": item["dias_falta"],
                "dias_atestado": item["dias_atestado"],
                "dias_incompletos": item["dias_incompletos"],
            })

        return Response(ResumoBancoHorasSerializer(linhas, many=True).data)


# ══════════════════════════════════════════════════════════════
# Atestados
# ══════════════════════════════════════════════════════════════
@extend_schema(tags=["Atestados"])
class AtestadoViewSet(BaseAPIPublica):
    serializer_class = AtestadoSerializer
    queryset = Atestado.objects.none()

    def get_queryset(self):
        parametros = self.request.query_params
        queryset = self.filtrar_por_empresa(
            Atestado.objects.select_related("colaborador", "empresa")
        )

        if colaborador := parametros.get("colaborador"):
            queryset = queryset.filter(colaborador__uuid=colaborador)

        if situacao := parametros.get("status"):
            queryset = queryset.filter(status=situacao)

        if inicio := _data(parametros.get("data_inicio"), "data_inicio"):
            queryset = queryset.filter(data_fim__gte=inicio)

        if fim := _data(parametros.get("data_fim"), "data_fim"):
            queryset = queryset.filter(data_inicio__lte=fim)

        return queryset.order_by("-data_inicio")


# ══════════════════════════════════════════════════════════════
# Relatórios fiscais
# ══════════════════════════════════════════════════════════════
class BaseRelatorioAPI(APIView):
    """
    Entrega dos arquivos fiscais pela API.

    Os arquivos saem em **texto puro ISO-8859-1**, byte a byte iguais ao
    que a tela do RH gera — o mesmo gerador, o mesmo layout. Se a API
    produzisse um AFD diferente do baixado no painel, teríamos dois
    "originais" e nenhuma forma de dizer qual foi entregue ao fiscal.
    """

    authentication_classes = (APIKeyAuthentication,)
    permission_classes = (APIKeyAutenticada,)
    throttle_classes = (PlanoRateThrottle,)

    def empresa_do_pedido(self, request):
        """
        Resolve a empresa do relatório.

        Relatório fiscal é sempre de **uma** empresa: o AFD é por CNPJ,
        e a numeração de NSR é por empresa. Uma chave de cliente com
        várias empresas precisa dizer qual.
        """
        empresas = getattr(request, "api_empresas", None)
        uuid_pedido = request.query_params.get("empresa")

        if uuid_pedido:
            empresa = empresas.filter(uuid=uuid_pedido).first()
            if empresa is None:
                raise NotFound("Empresa não encontrada nesta conta.")
            return empresa

        if empresas.count() == 1:
            return empresas.first()

        raise ValidationError({
            "empresa": (
                "Esta chave alcança várias empresas. Informe ?empresa=<uuid> "
                "— o arquivo fiscal é sempre de um único CNPJ."
            )
        })

    def periodo(self, request):
        inicio = _data(request.query_params.get("data_inicio"), "data_inicio")
        fim = _data(request.query_params.get("data_fim"), "data_fim")
        if not inicio or not fim:
            raise ValidationError(
                {"detail": "Informe data_inicio e data_fim (AAAA-MM-DD)."}
            )
        if inicio > fim:
            raise ValidationError({"detail": "data_inicio é posterior a data_fim."})
        return inicio, fim

    @staticmethod
    def _resposta_texto(conteudo: str, nome: str):
        resposta = HttpResponse(
            conteudo.encode("iso-8859-1", errors="replace"),
            content_type="text/plain; charset=iso-8859-1",
        )
        resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        # Aviso de conformidade também aqui: quem consome pela API não
        # vê o alerta que está na tela do RH.
        resposta["X-Kronus-Layout"] = "nao-conferido-com-anexo-oficial"
        return resposta


@extend_schema(
    tags=["Relatórios"],
    parameters=[
        OpenApiParameter("empresa", str, description="UUID da empresa (obrigatório se a chave alcança várias)."),
        OpenApiParameter("data_inicio", str, required=True),
        OpenApiParameter("data_fim", str, required=True),
    ],
    responses={200: {"type": "string", "format": "binary"}},
    summary="AFD — Arquivo Fonte de Dados (Portaria 671/2021)",
)
class AFDAPIView(BaseRelatorioAPI):
    def get(self, request):
        from apps.relatorios.afd import AFDGenerator

        empresa = self.empresa_do_pedido(request)
        inicio, fim = self.periodo(request)
        gerador = AFDGenerator(empresa, inicio, fim)
        nome = f"AFD_{empresa.cnpj}_{inicio:%Y%m%d}_{fim:%Y%m%d}.txt"
        return self._resposta_texto(gerador.gerar(), nome)


@extend_schema(
    tags=["Relatórios"],
    parameters=[
        OpenApiParameter("empresa", str),
        OpenApiParameter("data_inicio", str, required=True),
        OpenApiParameter("data_fim", str, required=True),
    ],
    responses={200: {"type": "string", "format": "binary"}},
    summary="AEJ — Arquivo Eletrônico de Jornada",
)
class AEJAPIView(BaseRelatorioAPI):
    def get(self, request):
        from apps.relatorios.aej import AEJGenerator

        empresa = self.empresa_do_pedido(request)
        inicio, fim = self.periodo(request)
        gerador = AEJGenerator(empresa, inicio, fim)
        nome = f"AEJ_{empresa.cnpj}_{inicio:%Y%m%d}_{fim:%Y%m%d}.txt"
        return self._resposta_texto(gerador.gerar(), nome)


@extend_schema(
    tags=["Relatórios"],
    parameters=[
        OpenApiParameter("colaborador", str, required=True, description="UUID."),
        OpenApiParameter("ano", int, required=True),
        OpenApiParameter("mes", int, required=True),
    ],
    responses={200: EspelhoSerializer},
    summary="Espelho de ponto em JSON",
)
class EspelhoAPIView(BaseRelatorioAPI):
    """
    Espelho de ponto como dados, não como PDF.

    Uma integração quer as linhas para montar o próprio documento; o PDF
    continua disponível no painel, onde é assinado pelo colaborador.
    """

    def get(self, request):
        from apps.relatorios.generators import EspelhoPontoGenerator

        uuid_colaborador = request.query_params.get("colaborador")
        if not uuid_colaborador:
            raise ValidationError({"colaborador": "Informe o UUID do colaborador."})

        try:
            ano = int(request.query_params.get("ano", 0))
            mes = int(request.query_params.get("mes", 0))
        except ValueError:
            raise ValidationError({"detail": "ano e mes devem ser números."})
        if not (1 <= mes <= 12) or ano < 2000:
            raise ValidationError({"detail": "Informe ano (>= 2000) e mes (1-12)."})

        colaborador = (
            Colaborador.objects.select_related("empresa")
            .filter(uuid=uuid_colaborador, empresa__in=request.api_empresas)
            .first()
        )
        if colaborador is None:
            raise NotFound("Colaborador não encontrado nesta conta.")

        contexto = EspelhoPontoGenerator(colaborador, ano, mes).contexto()

        return Response({
            "colaborador": {
                "uuid": str(colaborador.uuid),
                "cpf": colaborador.cpf,
                "nome": colaborador.nome_exibicao,
                "matricula": colaborador.matricula,
            },
            "ano": ano,
            "mes": mes,
            "hash_documento": contexto["hash_documento"],
            "codigo_verificacao": contexto["codigo_verificacao"],
            "totais": contexto["totais"],
            # `resumo["dias"]` traz os objetos BancoHoras do periodo — o
            # mesmo conteudo que ja vai em "linhas", em forma de model.
            # Fica de fora: e redundante e nao serializa.
            "resumo": {
                chave: valor
                for chave, valor in contexto["resumo"].items()
                if chave != "dias"
            },
            "linhas": [self._linha(linha) for linha in contexto["linhas"]],
        })

    @staticmethod
    def _linha(linha):
        """
        Traduz uma linha do gerador para o formato da API.

        O gerador monta o espelho para **impressao** — quatro colunas
        fixas, horarios ja formatados, campos vazios de preenchimento.
        A API entrega a lista real de marcacoes com o NSR de cada uma,
        que e o que uma integracao consegue reconciliar com `/pontos/`.
        """
        banco = linha["banco"]
        marcacoes = [
            {"hora": horario.strftime("%H:%M"), "nsr": nsr}
            for horario, nsr in zip(linha["marcacoes"], linha["nsrs"])
        ]
        return {
            "data": linha["data"].isoformat(),
            "dia_semana": linha["dia_semana"],
            "marcacoes": marcacoes,
            "minutos_trabalhados": banco.minutos_trabalhados if banco else 0,
            "minutos_esperados": banco.minutos_esperados if banco else 0,
            "minutos_extras": banco.minutos_extras if banco else 0,
            "minutos_noturnos": banco.minutos_noturnos if banco else 0,
            "saldo_minutos": banco.saldo_dia if banco else 0,
            "saldo": linha["saldo"],
            "status": linha["status"],
            "observacao": banco.observacao if banco else "",
        }


# ══════════════════════════════════════════════════════════════
# Metadados da conta
# ══════════════════════════════════════════════════════════════
@extend_schema(
    tags=["Conta"],
    summary="Identifica a credencial e mostra a cota restante",
    responses={200: ContaSerializer},
)
class ContaAPIView(APIView):
    """
    `GET /api/v1/conta/` — o primeiro endpoint que uma integração chama.

    Diz *quem* a chave é, *o que* ela alcança e *quanto* pode consumir.
    Sem isso, o desenvolvedor da integração descobre a cota estourando
    o limite em produção.
    """

    authentication_classes = (APIKeyAuthentication,)
    permission_classes = (APIKeyAutenticada,)
    throttle_classes = (PlanoRateThrottle,)

    def get(self, request):
        api_key = getattr(request, "api_key", None)
        cliente = getattr(request, "api_cliente", None) or (
            api_key.empresa.cliente if api_key else None
        )
        plano = getattr(cliente, "plano", None)

        return Response({
            "credencial": {
                "tipo": "empresa" if api_key else "cliente",
                "nome": api_key.nome if api_key else getattr(cliente, "razao_social", ""),
                "prefixo": api_key.prefixo if api_key else None,
                "somente_leitura": api_key.somente_leitura if api_key else False,
            },
            "cliente": {
                "uuid": str(cliente.uuid) if cliente else None,
                "razao_social": getattr(cliente, "razao_social", ""),
                "suspenso": getattr(cliente, "suspenso", False),
            },
            "plano": {
                "nome": getattr(plano, "nome", None),
                "recursos": plano.recursos_habilitados if plano else [],
            },
            "limite_hora": PlanoRateThrottle.limite_por_hora(request),
            "empresas": [
                {
                    "uuid": str(empresa.uuid),
                    "cnpj": empresa.cnpj,
                    "razao_social": empresa.razao_social,
                    "nome_fantasia": empresa.nome_fantasia,
                }
                for empresa in request.api_empresas
            ],
        })
