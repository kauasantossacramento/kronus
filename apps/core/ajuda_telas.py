"""
Kronus — ajuda das demais telas.

Separado de `ajuda.py` por tamanho: o conteudo cresce a cada tela
documentada, e um arquivo unico de mil linhas esconderia o mecanismo no
meio do texto. Aqui fica so o texto; a logica continua la.
"""

TELAS = {
    # ══════════════════════════════════════════════════════════
    # Rotina do ponto
    # ══════════════════════════════════════════════════════════
    "rh:registro_lista": {
        "titulo": "Registros de ponto",
        "resumo": (
            "Todas as marcações da empresa, dia a dia. É aqui que se confere "
            "o que aconteceu e se corrige o que faltou."
        ),
        "itens": [
            "Filtre por colaborador, período ou tipo de marcação.",
            "Cada linha traz o <strong>NSR</strong> — a numeração sequencial exigida pela Portaria — e o método usado (facial, CPF, web).",
            "<strong>Ajustar</strong> não apaga a marcação: cria uma correção ligada à original, com autor e motivo.",
        ],
        "atencao": (
            "Marcação registrada <strong>nunca é excluída</strong>. A Portaria "
            "manda anular, não apagar — e a cadeia de hash denunciaria "
            "qualquer alteração."
        ),
    },
    "rh:ajuste_novo": {
        "titulo": "Ajuste de ponto",
        "resumo": (
            "Correção de uma marcação que faltou, sobrou ou saiu no horário "
            "errado."
        ),
        "itens": [
            "O <strong>motivo é obrigatório</strong>: é ele que justifica a correção numa fiscalização.",
            "O ajuste entra na trilha de auditoria com o seu nome e a data.",
            "A marcação original continua no arquivo, marcada como cancelada.",
        ],
    },
    "rh:espelho_lista": {
        "titulo": "Espelho de ponto",
        "resumo": (
            "O documento do mês de cada colaborador: jornada prevista, "
            "marcações, saldo e assinatura."
        ),
        "itens": [
            "Gere o espelho depois de conferir os registros e resolver os pendentes.",
            "O colaborador confere e assina pelo próprio sistema.",
            "O PDF traz a identificação da empresa e o número de registro do REP-P.",
        ],
        "passos": [
            {"texto": "O espelho é o fecho do mês: consolida o que foi apurado e vai para a assinatura do colaborador."},
            {"alvo": "table", "texto": "Cada linha é um colaborador. Confira quem ainda tem pendência antes de gerar."},
        ],
    },
    "rh:banco_horas": {
        "titulo": "Banco de horas",
        "resumo": (
            "O saldo de cada colaborador — quanto trabalhou além ou aquém da "
            "jornada prevista."
        ),
        "itens": [
            "O saldo é recalculado a partir das marcações e da escala; ele não é digitado.",
            "<strong>Recalcular</strong> refaz a apuração do período, útil depois de corrigir escalas ou marcações.",
            "Dias já fechados não são alterados pelo recálculo.",
        ],
        "atencao": (
            "Saldo negativo persistente costuma indicar <strong>escala "
            "errada</strong>, não falta — confira a jornada antes de cobrar a "
            "pessoa."
        ),
    },
    "rh:fechamento": {
        "titulo": "Fechamento mensal",
        "resumo": (
            "Encerra o período: consolida as horas, trava as alterações e "
            "libera o espelho para assinatura."
        ),
        "itens": [
            "Resolva <strong>atestados e justificativas pendentes</strong> antes de fechar — depois, corrigir exige reabrir.",
            "O fechamento é por colaborador: dá para fechar quem está pronto e deixar o resto.",
            "<strong>Reabrir</strong> existe, fica registrado, e deve ser exceção.",
        ],
        "passos": [
            {"texto": "Fechar o mês é o último passo da rotina. Antes dele, três coisas precisam estar resolvidas."},
            {"texto": "Marcações faltantes corrigidas por ajuste; atestados avaliados; justificativas respondidas."},
            {"alvo": "table", "texto": "Aqui você vê quem está pronto e quem ainda tem pendência."},
        ],
    },
    "rh:exportar_folha": {
        "titulo": "Exportar para a folha",
        "resumo": (
            "Leva as horas apuradas para o sistema de folha de pagamento. O "
            "Kronus não calcula folha — ele alimenta quem calcula."
        ),
        "itens": [
            "Escolha o período fechado e o formato aceito pelo seu sistema contábil.",
            "Exporte depois do fechamento: antes disso os números ainda mudam.",
        ],
        "atencao": (
            "Confira o primeiro arquivo com o contador antes de confiar na "
            "rotina — cada sistema de folha tem particularidades de layout."
        ),
    },

    # ══════════════════════════════════════════════════════════
    # Cadastros de apoio
    # ══════════════════════════════════════════════════════════
    "rh:escala_lista": {
        "titulo": "Escalas de trabalho",
        "resumo": (
            "A jornada esperada de cada grupo de pessoas. Sem escala, o "
            "sistema não sabe o que é hora extra nem o que é falta."
        ),
        "itens": [
            "Uma escala serve a vários colaboradores; vincule pela ficha da pessoa ou em lote.",
            "Mudança de escala vale dali para frente — dias já apurados mantêm o cálculo antigo até serem reprocessados.",
        ],
    },
    "rh:departamento_lista": {
        "titulo": "Departamentos",
        "resumo": "Organizam os colaboradores e os relatórios por área.",
        "itens": [
            "Servem para filtrar relatórios e agrupar o fechamento.",
            "Não afetam o cálculo da jornada — isso é a escala.",
        ],
    },
    "rh:cargo_lista": {
        "titulo": "Cargos",
        "resumo": "Os cargos usados no cadastro de colaboradores.",
        "itens": [
            "Padronizar o cargo evita o mesmo posto escrito de cinco formas nos relatórios.",
        ],
    },
    "rh:colaborador_criar": {
        "titulo": "Novo colaborador",
        "resumo": "Cadastro de quem vai bater ponto nesta empresa.",
        "itens": [
            "<strong>CPF</strong> identifica a pessoa no AFD e no totem.",
            "<strong>Data de nascimento</strong> é o segundo fator do registro por CPF — sem ela correta, a pessoa não consegue usar a alternativa quando o rosto falhar.",
            "<strong>Escala</strong> define a jornada esperada; sem ela não há como apurar hora extra.",
        ],
    },
    "rh:importar_colaboradores": {
        "titulo": "Importar colaboradores",
        "resumo": (
            "Cadastro em lote a partir de uma planilha — para quando são "
            "dezenas de pessoas."
        ),
        "itens": [
            "Baixe o <strong>modelo</strong> e preencha sem mudar os cabeçalhos.",
            "A importação valida CPF e datas antes de gravar: a linha com erro é recusada e apontada, e o resto entra.",
            "O cadastro facial não vem pela planilha — é feito depois, pessoa por pessoa.",
        ],
    },

    # ══════════════════════════════════════════════════════════
    # Aprovações
    # ══════════════════════════════════════════════════════════
    "rh:atestado_lista": {
        "titulo": "Atestados",
        "resumo": "Atestados enviados pelos colaboradores, aguardando avaliação.",
        "itens": [
            "Aprovar abona as faltas do período coberto; recusar mantém a falta.",
            "Atestado pendente <strong>trava o fechamento</strong> do mês daquela pessoa.",
        ],
        "atencao": (
            "O CID é <strong>dado de saúde</strong> pela LGPD: só quem precisa "
            "avaliar tem acesso, e o acesso fica registrado."
        ),
    },
    "rh:justificativa_lista": {
        "titulo": "Justificativas",
        "resumo": (
            "Pedidos de correção enviados pelos colaboradores — a batida que "
            "faltou, o horário errado."
        ),
        "itens": [
            "Aprovar cria o ajuste automaticamente, com o motivo informado.",
            "Recusar devolve ao colaborador com a sua explicação.",
        ],
    },
    "rh:afastamento_lista": {
        "titulo": "Afastamentos",
        "resumo": (
            "Férias, licenças e demais períodos em que não há jornada a "
            "cumprir."
        ),
        "itens": [
            "Dias de afastamento não geram falta nem entram no banco de horas.",
            "Registre antes do fechamento: depois, o período precisa ser reaberto.",
        ],
    },

    # ══════════════════════════════════════════════════════════
    # Relatórios e documentos fiscais
    # ══════════════════════════════════════════════════════════
    "relatorios:fiscais": {
        "titulo": "Relatórios fiscais",
        "resumo": (
            "AFD e AEJ — os arquivos que o Auditor-Fiscal do Trabalho pede "
            "numa inspeção."
        ),
        "itens": [
            "<strong>AFD</strong> é o arquivo das marcações, no leiaute do Anexo V da Portaria 671/2021.",
            "<strong>AEJ</strong> é o arquivo da jornada apurada, no leiaute do Anexo VI.",
            "Os dois são gerados por período; escolha o intervalo pedido pelo fiscal.",
        ],
        "atencao": (
            "O AFD carrega o <strong>número de registro do REP-P no "
            "INPI</strong>. Sem ele preenchido, o arquivo sai sem uma "
            "informação obrigatória."
        ),
    },
    "relatorios:gerenciais": {
        "titulo": "Relatórios gerenciais",
        "resumo": (
            "Números para decisão: horas extras por área, atrasos, faltas, "
            "absenteísmo."
        ),
        "itens": [
            "São relatórios de gestão, não documentos fiscais.",
            "Exporte em CSV para cruzar com outros dados.",
        ],
    },
    "relatorios:portal_contador": {
        "titulo": "Portal do contador",
        "resumo": (
            "Acesso de leitura para o escritório de contabilidade baixar o que "
            "precisa, sem poder alterar nada."
        ),
        "itens": [
            "O contador vê espelhos e arquivos fiscais das empresas liberadas.",
            "Nenhuma ação de escrita: é seguro entregar o acesso.",
        ],
    },
    "relatorios:verificar": {
        "titulo": "Verificação de documento",
        "resumo": (
            "Confere a autenticidade de um comprovante pelo código impresso "
            "nele — sem precisar de login."
        ),
        "itens": [
            "Serve para o fiscal, para o colaborador e para quem receber o documento.",
            "A verificação recalcula o hash: um documento alterado não confere.",
        ],
    },

    # ══════════════════════════════════════════════════════════
    # Configurações
    # ══════════════════════════════════════════════════════════
    "rh:configuracoes": {
        "titulo": "Configurações da empresa",
        "resumo": (
            "Tolerâncias, adicional noturno, regras de jornada e o endereço de "
            "acesso da sua equipe."
        ),
        "itens": [
            "A <strong>tolerância</strong> define quantos minutos de atraso não viram desconto.",
            "O <strong>adicional noturno</strong> segue a CLT por padrão; altere só com orientação do contador.",
        ],
        "atencao": (
            "Alterar tolerância ou percentuais muda o <strong>cálculo da "
            "jornada</strong>. Dias já apurados mantêm o cálculo antigo até "
            "serem reprocessados; dias fechados nunca são alterados."
        ),
    },
    "rh:notificacoes_config": {
        "titulo": "Notificações",
        "resumo": "O que o sistema avisa, para quem e por qual canal.",
        "itens": [
            "Avisos de esquecimento de ponto reduzem correção no fim do mês.",
            "Alertas de totem offline chegam a quem puder agir.",
        ],
    },
    "rh:webhooks": {
        "titulo": "Webhooks",
        "resumo": (
            "Envia eventos do Kronus para outro sistema no momento em que "
            "acontecem."
        ),
        "itens": [
            "Cada entrega é registrada, com o que foi enviado e a resposta recebida.",
            "Entregas que falham são retentadas automaticamente.",
        ],
    },
    "rh:integracao": {
        "titulo": "Integração",
        "resumo": "Chave de API para outro sistema consultar o Kronus.",
        "itens": [
            "A chave é exibida <strong>uma única vez</strong>; guarde-a no momento em que aparecer.",
            "Regenerar invalida a anterior na hora.",
        ],
    },
    "rh:slides_totem": {
        "titulo": "Slides do totem",
        "resumo": (
            "Imagens exibidas em sequência enquanto ninguém está usando o "
            "equipamento."
        ),
        "itens": [
            "Uma tela ligada o dia inteiro na portaria é um canal que a empresa já tem: comunicado, campanha, aniversariantes.",
            "Até 8 MB por imagem — o totem baixa o arquivo a cada troca de slide.",
        ],
    },

    # ══════════════════════════════════════════════════════════
    # Colaborador
    # ══════════════════════════════════════════════════════════
    "ponto:solicitar_justificativa": {
        "titulo": "Pedir correção",
        "resumo": (
            "Quando faltou uma batida ou o horário saiu errado, o pedido vai "
            "para o RH avaliar."
        ),
        "itens": [
            "Explique o que aconteceu: o motivo é o que o RH usa para decidir.",
            "Aprovado, o ajuste é criado com o seu pedido registrado junto.",
        ],
    },
    "ponto:meus_espelhos": {
        "titulo": "Meus espelhos",
        "resumo": "Os documentos mensais da sua jornada, para conferir e assinar.",
        "itens": [
            "Confira antes de assinar: depois, mudanças exigem reabertura pelo RH.",
            "Se algo estiver errado, peça a correção antes de assinar.",
        ],
    },

    # ══════════════════════════════════════════════════════════
    # Master — telas restantes
    # ══════════════════════════════════════════════════════════
    "master:plano_lista": {
        "titulo": "Planos",
        "resumo": "O que cada plano inclui: limites, preço e recursos liberados.",
        "itens": [
            "Os limites são verificados na hora de cadastrar — o cliente não passa do contratado sem trocar de plano.",
            "<strong>Totens adicionais</strong> podem ser vendidos avulso, inclusive em plano que não inclui nenhum.",
        ],
    },
    "master:totem_lista": {
        "titulo": "Totens",
        "resumo": "Todos os equipamentos, de todos os clientes.",
        "itens": [
            "O número de patrimônio e o token de acesso são gerados pelo sistema — ninguém digita.",
            "Cada totem tem etiqueta com QR para conferir a procedência.",
            "<strong>Em comodato</strong> marca que o equipamento é da KS TEC.",
        ],
    },
    "master:assinaturas": {
        "titulo": "Assinaturas",
        "resumo": "Quem paga, quanto, e quem atrasou.",
        "itens": [
            "As faturas vêm do gateway; o Kronus mantém o espelho local.",
            "<strong>Sincronizar</strong> reenvia a assinatura ao gateway depois de mudar plano ou adicionais.",
        ],
    },
    "master:usuarios": {
        "titulo": "Usuários",
        "resumo": "Todos os usuários, de todas as contas.",
        "itens": [
            "A senha não é escolhida por quem cria: o sistema gera uma provisória e obriga a troca no primeiro acesso.",
            "Basta <strong>e-mail ou CPF</strong> — os dois servem para entrar.",
        ],
        "atencao": (
            "Desativar é melhor do que excluir: apagar deixaria logs e ajustes "
            "de ponto sem autor."
        ),
    },
    "master:usuario_criar": {
        "titulo": "Novo usuário",
        "resumo": "Criação de acesso em qualquer conta da plataforma.",
        "itens": [
            "Informe <strong>e-mail ou CPF</strong> — ao menos um; os dois servem para entrar.",
            "<strong>Admin RH</strong> precisa de pelo menos uma empresa marcada; o Admin do Cliente acessa todas.",
            "A senha provisória aparece uma única vez, na tela seguinte.",
        ],
    },
    "master:cliente_criar": {
        "titulo": "Novo cliente",
        "resumo": "Cadastro de um contratante da plataforma.",
        "itens": [
            "O contratante <strong>já nasce com a empresa dele</strong>: mesmo documento, razão social e endereço.",
            "Aceita <strong>CPF</strong> no lugar do CNPJ — empregador doméstico e produtor rural pessoa física registram ponto como qualquer outro.",
        ],
    },
    "master:empresa_editar": {
        "titulo": "Editar empresa",
        "resumo": "Dados cadastrais e o endereço de acesso da equipe.",
        "itens": [
            "O <strong>endereço de acesso</strong> é o `kronus.online/<endereço>` por onde os colaboradores entram.",
            "<strong>CEI/CAEPF</strong> vai no cabeçalho do AFD — obrigatório na prática para empregador pessoa física.",
        ],
    },
    "master:comercial_config": {
        "titulo": "Configuração comercial",
        "resumo": (
            "O contato exibido na capa e as regras da demonstração automática."
        ),
        "itens": [
            "Trocar o WhatsApp aqui não exige deploy.",
            "Desligar a demonstração faz a capa oferecer apenas o contato direto.",
        ],
    },
    "master:log_lista": {
        "titulo": "Logs de acesso",
        "resumo": "Quem entrou, quando, de onde — e o que tentou sem sucesso.",
        "itens": [
            "Tentativas de login malsucedidas aparecem aqui: sequências repetidas merecem atenção.",
        ],
    },
    "master:empresa_personalizacao": {
        "titulo": "Personalização da empresa",
        "resumo": (
            "Logo, cores e a tela do totem de um cliente — sem precisar entrar "
            "como ele."
        ),
        "itens": [
            "A mesma tela existe no painel do cliente; esta serve para a implantação.",
            "Os totens ativos recarregam sozinhos ao salvar.",
        ],
    },
}

# ══════════════════════════════════════════════════════════════
# Telas restantes
# ══════════════════════════════════════════════════════════════
TELAS.update({
    "notificacoes:lista": {
        "titulo": "Notificações",
        "resumo": "O que o sistema quis te avisar, do mais recente ao mais antigo.",
        "itens": [
            "Alertas de totem offline, atestado pendente e esquecimento de ponto chegam aqui.",
            "Clique no aviso para ir direto ao que ele trata.",
        ],
    },
    "faturamento:minha_assinatura": {
        "titulo": "Minha assinatura",
        "resumo": (
            "Seu plano, o que ele inclui, as faturas e os adicionais "
            "contratados."
        ),
        "itens": [
            "O valor mostrado já soma os adicionais — totens além do incluído no plano.",
            "Faturas em aberto trazem link de pagamento, linha digitável e Pix.",
            "<strong>Precisa de mais totens?</strong> Contrate aqui mesmo; a liberação é imediata.",
        ],
    },
    "faturamento:planos": {
        "titulo": "Planos",
        "resumo": "O que cada plano inclui e o que muda ao trocar.",
        "itens": [
            "Trocar de plano vale a partir da próxima fatura.",
            "Reduzir o plano exige estar dentro dos limites do novo — o sistema avisa se não estiver.",
        ],
    },
    "master:grupo_totem_lista": {
        "titulo": "Grupos de totens",
        "resumo": (
            "Permitem que um totem atenda colaboradores de mais de uma "
            "empresa do mesmo cliente."
        ),
        "itens": [
            "Útil quando empresas do grupo dividem a mesma portaria.",
            "A empresa do próprio totem entra sempre, mesmo sem estar no grupo.",
            "Um grupo nunca atravessa clientes diferentes — isso vazaria biometria entre contas.",
        ],
    },
    "ponto:comprovante": {
        "titulo": "Comprovante",
        "resumo": (
            "O recibo da sua marcação, com número sequencial e código de "
            "verificação."
        ),
        "itens": [
            "Guarde ou imprima: é a prova de que a batida foi registrada.",
            "O código pode ser conferido por qualquer pessoa em kronus.online/verificar/, sem login.",
        ],
    },
    "accounts:perfil": {
        "titulo": "Meu perfil",
        "resumo": "Seus dados de acesso e a troca de senha.",
        "itens": [
            "Você entra com <strong>e-mail ou CPF</strong> — os dois funcionam.",
            "Trocar a senha encerra as outras sessões abertas.",
        ],
    },
})
