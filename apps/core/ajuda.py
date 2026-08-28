"""
Kronus — conteudo de ajuda por tela.

Um sistema de ponto e operado por gente que nao escolheu usa-lo: o RH
recebeu a tarefa, o colaborador tem que bater o ponto. Quem nao escolheu
a ferramenta nao vai procurar documentacao — a ajuda precisa estar na
propria tela, no momento da duvida.

O conteudo mora em Python, e nao no banco, por dois motivos: ele muda
junto com a tela (e portanto pertence ao mesmo commit), e assim o texto
entra na revisao de codigo como qualquer outra coisa que o usuario le.

Cada entrada e indexada pelo **nome da rota** (`request.resolver_match`),
que e estavel — o caminho da URL muda, o nome nao.

Estrutura:
    titulo    o que e esta tela, em uma linha
    resumo    para que ela serve, em duas ou tres
    itens     lista de "o que da para fazer aqui"
    passos    roteiro guiado (opcional), cada passo com `alvo` (seletor
              CSS) e `texto`. Sem `alvo`, o passo aparece centralizado.
    atencao   o que costuma dar errado (opcional)
"""

AJUDA = {
    # ══════════════════════════════════════════════════════════
    # Master — KS TEC
    # ══════════════════════════════════════════════════════════
    "master:dashboard": {
        "titulo": "Painel da KS TEC",
        "resumo": (
            "Visão geral da plataforma inteira: quantos clientes existem, "
            "quantas empresas, colaboradores e totens em operação, e quanto "
            "a operação fatura por mês."
        ),
        "itens": [
            "Os cartões do topo somam <strong>todos os clientes</strong> — é a visão da KS TEC, não de uma empresa.",
            "<strong>Clientes recentes</strong> mostra quem entrou por último; clique no nome para abrir a ficha.",
            "<strong>Distribuição por plano</strong> ajuda a ver se a base está concentrada num plano só.",
        ],
        "passos": [
            {"texto": "Este é o painel da KS TEC. Tudo aqui é sobre a plataforma como um todo — os painéis dos clientes são outros."},
            {"alvo": ".grid .card", "texto": "Os números do topo respondem 'como está a operação hoje'."},
            {"alvo": "aside nav", "texto": "O menu à esquerda separa o que é da plataforma (clientes, planos, custos) do que é operacional."},
        ],
    },
    "master:cliente_lista": {
        "titulo": "Clientes",
        "resumo": (
            "Os contratantes da plataforma. Cada cliente tem seu plano, suas "
            "empresas e seus usuários."
        ),
        "itens": [
            "<strong>Novo cliente</strong> cria o contratante e já cria a empresa dele — o contratante é, ele mesmo, uma empresa.",
            "Use os filtros para achar por situação ou plano.",
            "<strong>Editar</strong> abre os dados cadastrais; a ficha do cliente traz assinatura, empresas e usuários.",
        ],
        "atencao": (
            "Suspender um cliente interrompe o acesso mas <strong>não apaga "
            "nada</strong>: os registros de ponto precisam ser guardados por "
            "cinco anos."
        ),
    },
    "master:empresa_lista": {
        "titulo": "Empresas",
        "resumo": (
            "As empresas de todos os clientes. Um cliente pode ter várias — "
            "matriz e filiais, ou CNPJs diferentes do mesmo grupo."
        ),
        "itens": [
            "O endereço embaixo do nome é a <strong>página de acesso da empresa</strong>: é por ali que os colaboradores entram.",
            "<strong>Personalizar</strong> abre logo, cores e a tela do totem.",
            "<strong>Editar</strong> abre CNPJ, endereço e o endereço de acesso.",
        ],
    },
    "master:custos": {
        "titulo": "Custos e margem",
        "resumo": (
            "Quanto entrou, quanto saiu e o que sobrou. A receita bruta "
            "sozinha parece margem — cada boleto compensado, cada nota "
            "emitida e a própria hospedagem saem dela."
        ),
        "itens": [
            "O custo é recalculado pela tabela vigente, não congelado — assim o histórico não mente quando a tabela muda.",
            "A série de 12 meses mostra a tendência; um mês isolado não diz se a operação melhora ou piora.",
        ],
        "atencao": (
            "Com a tabela de custos zerada, <strong>tudo aparece como "
            "lucro</strong>. Preencha as taxas em Gateway."
        ),
    },
    "master:comercial_demos": {
        "titulo": "Demonstrações",
        "resumo": (
            "Quem pediu demonstração, o que aconteceu e quem virou cliente. "
            "O ambiente de teste é um cliente de verdade, marcado com prazo."
        ),
        "itens": [
            "<strong>Criar demonstração</strong> gera o ambiente na hora, para quando o contato veio por telefone ou visita.",
            "<strong>+24h</strong> prorroga; <strong>Converter</strong> tira a marca de demonstração e o ambiente vira cliente.",
            "Converter não migra nada: o ambiente já era um cliente comum.",
        ],
    },
    "master:gateway": {
        "titulo": "Gateway de pagamento",
        "resumo": (
            "Credenciais do ASAAS e a tabela de custos por transação. "
            "Enquanto a cobrança automática estiver desligada, nenhuma fatura "
            "é emitida — os planos seguem funcionando."
        ),
        "atencao": (
            "Sem o <strong>token do webhook</strong>, qualquer um poderia "
            "forjar uma confirmação de pagamento. Por isso o webhook recusa "
            "tudo enquanto ele não estiver configurado."
        ),
    },
    "master:auditoria": {
        "titulo": "Auditoria",
        "resumo": (
            "Tudo o que foi feito no sistema, por quem e quando — em todos "
            "os clientes. É o registro que responde 'quem alterou isso?'."
        ),
        "itens": [
            "Filtre por cliente, por ação ou por período.",
            "O registro é imutável por construção: nada aqui pode ser editado ou apagado.",
        ],
    },

    # ══════════════════════════════════════════════════════════
    # RH e administrador da empresa
    # ══════════════════════════════════════════════════════════
    "rh:dashboard": {
        "titulo": "Painel do RH",
        "resumo": (
            "O dia de hoje na sua empresa: quem bateu ponto, quem está "
            "pendente, e o que espera aprovação."
        ),
        "itens": [
            "Os cartões do topo mostram <strong>hoje</strong>; os gráficos mostram o mês.",
            "Atestados e justificativas pendentes aparecem com contador no menu — eles travam o fechamento se ficarem parados.",
        ],
        "passos": [
            {"texto": "Este é o painel da sua empresa. Tudo aqui é da empresa selecionada no topo."},
            {"alvo": "aside nav", "texto": "O menu segue a rotina: cadastrar pessoas, acompanhar o ponto, fechar o mês, emitir documentos."},
            {"alvo": "header", "texto": "No topo você troca de empresa, quando administra mais de uma."},
        ],
    },
    "rh:colaborador_lista": {
        "titulo": "Colaboradores",
        "resumo": (
            "As pessoas que batem ponto nesta empresa. Cada uma precisa de "
            "CPF, data de nascimento, admissão e escala."
        ),
        "itens": [
            "A <strong>escala</strong> define a jornada esperada — sem ela, o sistema não sabe o que é hora extra.",
            "O <strong>cadastro facial</strong> é feito na ficha da pessoa, e pode ser refeito quando o rosto mudar.",
            "Desligar não apaga: os registros de ponto precisam ser guardados.",
        ],
        "atencao": (
            "A data de nascimento é o segundo fator do registro por CPF no "
            "totem. Sem ela correta, a pessoa não consegue usar a alternativa "
            "quando o rosto não for reconhecido."
        ),
    },
    "rh:qualidade_facial": {
        "titulo": "Qualidade do reconhecimento",
        "resumo": (
            "Quanto da margem cada pessoa já consumiu. O rosto muda devagar — "
            "barba, óculos, cabelo — e a distância sobe sem que nada acuse."
        ),
        "itens": [
            "Enquanto a margem existe, o ponto é registrado normalmente. O problema só aparece quando ela acaba.",
            "Quem está em <strong>atenção</strong> ou <strong>crítica</strong> deve refazer o cadastro facial.",
            "São necessários alguns reconhecimentos para a avaliação ter base — quem bate pouco não aparece.",
        ],
    },
    "rh:personalizacao": {
        "titulo": "Personalização",
        "resumo": (
            "Logo, cores e a tela do totem. Vale na página de acesso da sua "
            "equipe, no aplicativo instalado e no equipamento."
        ),
        "itens": [
            "Marque <strong>logo branca</strong> quando a sua logo sumir num fundo escuro — a opção é separada para o totem e para a tela de acesso.",
            "Os totens ativos recarregam sozinhos ao salvar; ninguém precisa reiniciar o tablet.",
        ],
    },
    "rh:equipamentos": {
        "titulo": "Equipamentos",
        "resumo": "Os totens instalados na sua empresa e o estado de cada um.",
        "itens": [
            "<strong>Online</strong> significa que o equipamento deu sinal de vida nos últimos minutos.",
            "Cada totem tem um número de patrimônio e uma etiqueta com QR para conferir a procedência.",
        ],
    },

    # ══════════════════════════════════════════════════════════
    # Colaborador
    # ══════════════════════════════════════════════════════════
    "ponto:registrar": {
        "titulo": "Registrar ponto",
        "resumo": "Sua marcação de entrada, saída e intervalo.",
        "itens": [
            "O sistema já sabe qual é a próxima batida esperada — você só confirma.",
            "Cada marcação gera um <strong>comprovante</strong>, que fica disponível para consulta.",
            "Marcação registrada não é apagada. Correção existe, e fica registrada como correção.",
        ],
    },
    "ponto:meus_pontos": {
        "titulo": "Meus pontos",
        "resumo": "Suas marcações, o saldo do banco de horas e os comprovantes.",
        "itens": [
            "Se faltar uma batida, peça a correção pelo próprio sistema — ela vai para a aprovação do RH.",
            "O <strong>espelho de ponto</strong> é o documento do mês, que você assina ao final.",
        ],
    },
}


# O restante do conteudo vive em `ajuda_telas.py`. A separacao e por
# tamanho: o texto cresce a cada tela documentada, e um arquivo unico
# esconderia o mecanismo no meio do conteudo.
from apps.core.ajuda_telas import TELAS as _DEMAIS  # noqa: E402

AJUDA.update(_DEMAIS)


#: Ajuda usada quando a tela ainda nao tem texto proprio.
#:
#: Existir e melhor do que o botao sumir em algumas telas: um botao que
#: aparece e desaparece ensina a nao procurar por ele.
PADRAO = {
    "titulo": "Ajuda",
    "resumo": (
        "Esta tela ainda não tem um guia próprio. Se ficou com dúvida sobre "
        "algo aqui, fale com a KS TEC — a dúvida vira conteúdo desta ajuda."
    ),
    "itens": [],
}


def para_rota(nome_da_rota: str) -> dict:
    """
    Conteudo da ajuda para a rota indicada.

    Indexado pelo nome da rota, e nao pelo caminho: o caminho muda com
    refatoracao de URL, o nome nao.
    """
    conteudo = dict(AJUDA.get(nome_da_rota) or PADRAO)
    conteudo.setdefault("itens", [])
    conteudo.setdefault("passos", [])
    conteudo.setdefault("atencao", "")
    conteudo["tem_conteudo"] = nome_da_rota in AJUDA
    conteudo["rota"] = nome_da_rota
    return conteudo


def cobertura() -> dict:
    """Quantas telas ja tem ajuda — usado no teste que acompanha o avanco."""
    return {"telas_com_ajuda": len(AJUDA), "rotas": sorted(AJUDA)}
