# Manual do Kronus

> Sistema de ponto eletrônico da KS TEC. Este manual cobre as três formas
> de usar o sistema — quem administra a plataforma, quem administra uma
> empresa e quem bate o ponto — além do totem.
>
> **As imagens são capturas do sistema real**, geradas por
> `ferramentas/capturar_telas.py`. Quando uma tela muda, basta rodar a
> ferramenta de novo: o manual não envelhece sozinho.
>
> Cada tela aparece em duas versões: **computador** e **celular**. O
> sistema é o mesmo nos dois; o que muda é o arranjo.

---

## Índice

1. [Antes de começar](#1-antes-de-começar)
2. [Os três papéis](#2-os-três-papéis)
3. [Entrar no sistema](#3-entrar-no-sistema)
4. [Administrador da empresa e RH](#4-administrador-da-empresa-e-rh)
5. [Colaborador](#5-colaborador)
6. [Totem](#6-totem)
7. [Master — KS TEC](#7-master--ks-tec)
8. [Ajuda dentro do sistema](#8-ajuda-dentro-do-sistema)
9. [Documentos fiscais](#9-documentos-fiscais)

---

## 1. Antes de começar

### O que o Kronus é

Um **REP-P** — Registrador Eletrônico de Ponto via Programa, na
classificação da Portaria MTP 671/2021. Na prática: o sistema registra a
jornada, calcula o que é hora extra e o que é falta, e emite os
documentos que a fiscalização do trabalho pede.

### O que ele não faz

Não calcula folha de pagamento. Ele **alimenta** a folha: exporta as
horas apuradas no formato que o sistema contábil espera.

### Três coisas que valem saber desde o início

| | |
|---|---|
| **Marcação não se apaga** | A Portaria manda anular, não excluir. Uma correção fica registrada como correção, com autor e motivo. |
| **Cada empresa tem seu endereço** | `kronus.online/sua-empresa` — com a logo e as cores dela. É por aí que a equipe entra. |
| **O rosto não é guardado** | O que fica é um vetor matemático, do qual não se reconstrói a foto. |

---

## 2. Os três papéis

Quem entra no sistema vê coisas diferentes conforme o papel.

| Papel | Alcance | O que faz |
|---|---|---|
| **Master (KS TEC)** | Toda a plataforma | Cadastra clientes, define planos, acompanha custos e assinaturas |
| **Administrador do Cliente** | Todas as empresas da conta | Tudo do RH, mais plano, faturas e criação de usuários |
| **Administrador RH** | Só as empresas marcadas | Colaboradores, ponto, escalas, fechamento, relatórios |
| **Contador** | Só as empresas marcadas | Somente leitura: baixa espelhos e arquivos fiscais |
| **Colaborador** | Só a si mesmo | Bate ponto, consulta saldo, assina o espelho |

A distinção que importa: o **Administrador do Cliente é o dono da conta**
— vê tudo e mexe no dinheiro. O **Admin RH** é operacional e vive dentro
de uma ou mais empresas específicas. O **Contador** é acesso externo de
leitura, que se entrega ao escritório de contabilidade sem risco.

---

## 3. Entrar no sistema

### Página de acesso da empresa

Cada empresa tem um endereço próprio, com a marca dela.

| Computador | Celular |
|---|---|
| ![Entrar](prints/publico__accounts_login_pc.png) | ![Entrar no celular](prints/publico__accounts_login_cel.png) |

**Você entra com e-mail ou CPF** — os dois funcionam, contanto que
estejam no seu cadastro. A senha do primeiro acesso é provisória e o
sistema pede a troca.

> **Instalar como aplicativo.** Na primeira visita pelo celular, o
> sistema oferece adicionar o Kronus à tela inicial. Instalado, ele abre
> sem a barra do navegador e continua abrindo mesmo com a conexão
> instável.

### Página inicial pública

| Computador | Celular |
|---|---|
| ![Página inicial](prints/publico__landing_index_pc.png) | ![Página inicial no celular](prints/publico__landing_index_cel.png) |

---

## 4. Administrador da empresa e RH

### 4.1 Painel

A primeira tela responde "como está hoje": quem bateu ponto, quem está
pendente, o que espera aprovação.

| Computador | Celular |
|---|---|
| ![Painel do RH](prints/rh__rh_dashboard_pc.png) | ![Painel no celular](prints/rh__rh_dashboard_cel.png) |

Os cartões do topo mostram **hoje**. Os gráficos mostram o mês. Os avisos
em destaque — colaborador sem cadastro facial, totem offline — são coisas
que travam a operação se ficarem paradas.

### 4.2 Colaboradores

| Computador | Celular |
|---|---|
| ![Colaboradores](prints/rh__rh_colaborador_lista_pc.png) | ![Colaboradores no celular](prints/rh__rh_colaborador_lista_cel.png) |

#### Cadastrar uma pessoa

| Computador | Celular |
|---|---|
| ![Novo colaborador](prints/rh__rh_colaborador_criar_pc.png) | ![Novo colaborador no celular](prints/rh__rh_colaborador_criar_cel.png) |

Quatro campos decidem o funcionamento:

| Campo | Por que importa |
|---|---|
| **CPF** | Identifica a pessoa no AFD e no totem |
| **Data de nascimento** | Segundo fator do registro por CPF — sem ela correta, a pessoa não consegue usar a alternativa quando o rosto falhar |
| **Data de admissão** | Define desde quando há jornada a apurar |
| **Escala** | Sem ela o sistema não sabe o que é hora extra |

> **Desligar não apaga.** O cadastro sai da operação mas os registros de
> ponto permanecem — a lei exige guardá-los por cinco anos.

#### Cadastro facial

Feito na ficha da pessoa. O que decide a qualidade do reconhecimento pelos
próximos anos é o momento do cadastro:

**Funciona bem**
- Cadastrar **como a pessoa costuma chegar ao trabalho**, inclusive com os óculos de grau de uso diário
- Luz vinda de frente, rosto inteiro no quadro
- Expressão neutra, olhos visíveis

**Não funciona**
- **Óculos escuros ou lente espelhada** — a região dos olhos é a de maior peso
- Boné, capuz ou máscara cobrindo o rosto
- Contraluz: janela ou lâmpada atrás da pessoa

> **Trocar de armação não atrapalha.** O que é reconhecido é a geometria
> do rosto — distância entre os olhos, formato do nariz, contorno do
> queixo —, não a armação.

### 4.3 Qualidade do reconhecimento

O rosto muda devagar: barba, óculos novos, cabelo. A distância entre o
rosto do dia e o cadastro sobe sem que nada acuse — e enquanto fica abaixo
do limiar, o ponto é registrado normalmente.

| Computador | Celular |
|---|---|
| ![Qualidade do reconhecimento](prints/rh__rh_qualidade_facial_pc.png) | ![Qualidade no celular](prints/rh__rh_qualidade_facial_cel.png) |

A coluna **margem consumida** responde "quanto falta para parar de
funcionar". Quem está em **atenção** ou **crítica** deve refazer o
cadastro facial antes de virar reclamação na fila do totem.

O sistema também avisa por conta própria: uma varredura semanal manda
notificação ao RH quando alguém entra na faixa de risco.

### 4.4 Personalização

Logo, cores e a tela do totem — o que a sua equipe vê.

| Computador | Celular |
|---|---|
| ![Personalização](prints/rh__rh_personalizacao_pc.png) | ![Personalização no celular](prints/rh__rh_personalizacao_cel.png) |

| Ajuste | Onde aparece |
|---|---|
| **Logo** | Página de acesso, aplicativo instalado, totem e topo dos PDFs |
| **Logo branca** | Marque quando a logo sumir num fundo escuro — a opção é **separada** para o totem e para a tela de acesso |
| **Cores** | Botões e destaques em todas as telas da empresa |
| **Cor de fundo do login** | Só a página de acesso |
| **Frase do totem** | Substitui a frase padrão do Kronus |

> Os totens ativos recarregam sozinhos ao salvar. Ninguém precisa
> reiniciar o tablet.

### 4.5 Slides do totem

Uma tela ligada o dia inteiro na portaria é um canal que a empresa já tem:
comunicado interno, campanha de segurança, aniversariantes do mês.

| Computador | Celular |
|---|---|
| ![Slides](prints/rh__rh_slides_totem_pc.png) | ![Slides no celular](prints/rh__rh_slides_totem_cel.png) |

Até 8 MB por imagem — o totem baixa o arquivo a cada troca de slide.

### 4.6 Equipamentos

| Computador | Celular |
|---|---|
| ![Equipamentos](prints/rh__rh_equipamentos_pc.png) | ![Equipamentos no celular](prints/rh__rh_equipamentos_cel.png) |

**Online** significa que o totem deu sinal de vida nos últimos minutos.
Cada equipamento tem número de patrimônio e uma etiqueta com QR para
conferir a procedência.

### 4.7 Integração e webhooks

Para quem vai ligar o Kronus a outro sistema.

| Integração | Webhooks |
|---|---|
| ![Integração](prints/rh__rh_integracao_pc.png) | ![Webhooks](prints/rh__rh_webhooks_pc.png) |

---

## 5. Colaborador

### 5.1 Registrar ponto

| Computador | Celular |
|---|---|
| ![Registrar ponto](prints/colaborador__ponto_registrar_pc.png) | ![Registrar ponto no celular](prints/colaborador__ponto_registrar_cel.png) |

O sistema já sabe qual é a próxima batida esperada — entrada, saída para
intervalo, retorno, saída. Você confirma.

Cada marcação gera um **comprovante** com número sequencial e código de
verificação, que fica disponível para consulta.

### 5.2 Meus pontos

| Computador | Celular |
|---|---|
| ![Meus pontos](prints/colaborador__ponto_meus_pontos_pc.png) | ![Meus pontos no celular](prints/colaborador__ponto_meus_pontos_cel.png) |

Aqui ficam as marcações do mês, o saldo do banco de horas e os
comprovantes. **Se faltar uma batida**, peça a correção pelo próprio
sistema: ela vai para a aprovação do RH e fica registrada como correção,
com autor e motivo.

### 5.3 Espelho de ponto

| Computador | Celular |
|---|---|
| ![Meus espelhos](prints/colaborador__ponto_meus_espelhos_pc.png) | ![Espelhos no celular](prints/colaborador__ponto_meus_espelhos_cel.png) |

O espelho é o documento do mês. Ao final do período o RH fecha, e você
confere e assina.

---

## 6. Totem

O totem é um tablet fixo, normalmente na portaria ou na recepção.

### Como funciona para quem bate

1. A pessoa se aproxima e o totem acorda
2. A câmera reconhece o rosto
3. A batida é registrada e o comprovante aparece na tela

**Se o rosto não for reconhecido**, o totem oferece digitar o CPF e a data
de nascimento. Essa saída existe porque o reconhecimento facial falha por
motivos banais — barba nova, contraluz, câmera suja — e sem alternativa a
pessoa ficaria impedida de registrar o ponto.

### Instalar o totem

O totem funciona no navegador, mas fica melhor em tela cheia, sem a barra
de endereço — uma barra de navegador convida o colaborador a sair da
página.

| Situação | O que fazer |
|---|---|
| O navegador oferece instalar | Toque em **Instalar** no convite |
| Android sem o convite | Menu **⋮** → *Instalar aplicativo* |
| iPad ou iPhone | **Compartilhar** → *Adicionar à Tela de Início* |
| Nada disso funciona | Toque em **Tela cheia** — o botão fica no canto superior direito e reaparece sempre que a tela cheia sair |

> **Diagnóstico.** Se a instalação não for oferecida e você quiser saber
> por quê, abra `/totem/<token>/diagnostico/` no próprio equipamento: a
> página verifica cada critério e diz qual falhou.

### Etiqueta de patrimônio

Cada totem tem uma etiqueta com o número de patrimônio (`KST-AAAA-NNNNN`),
um código de verificação e um QR. Apontar a câmera para o QR abre uma
página pública que confirma a procedência do equipamento — sem exibir
nenhum dado de colaborador ou de marcação.

---

## 7. Master — KS TEC

Esta seção é de uso interno da KS TEC.

### 7.1 Painel

| Computador | Celular |
|---|---|
| ![Painel Master](prints/master__master_dashboard_pc.png) | ![Painel Master no celular](prints/master__master_dashboard_cel.png) |

Os números somam **todos os clientes** — é a visão da plataforma, não de
uma empresa.

### 7.2 Clientes

| Lista | Cadastro |
|---|---|
| ![Clientes](prints/master__master_cliente_lista_pc.png) | ![Novo cliente](prints/master__master_cliente_criar_pc.png) |

No celular:

| Lista | Cadastro |
|---|---|
| ![Clientes no celular](prints/master__master_cliente_lista_cel.png) | ![Novo cliente no celular](prints/master__master_cliente_criar_cel.png) |

**O contratante é, ele mesmo, uma empresa.** Ao criar o cliente, o sistema
já cria a empresa correspondente — com o mesmo CNPJ, razão social e
endereço. As demais empresas do cliente são filiais ou outros CNPJs do
grupo, vinculadas depois.

**Aceita CPF no lugar do CNPJ**: empregador doméstico e produtor rural
pessoa física registram ponto como qualquer outro, e o AFD identifica o
tipo corretamente.

### 7.3 Empresas

| Computador | Celular |
|---|---|
| ![Empresas](prints/master__master_empresa_lista_pc.png) | ![Empresas no celular](prints/master__master_empresa_lista_cel.png) |

O endereço embaixo do nome é a **página de acesso** daquela empresa.
**Personalizar** abre logo, cores e a tela do totem, sem precisar entrar
como o cliente.

### 7.4 Planos

| Computador | Celular |
|---|---|
| ![Planos](prints/master__master_plano_lista_pc.png) | ![Planos no celular](prints/master__master_plano_lista_cel.png) |

O plano define limites (empresas, colaboradores, totens), preço e quais
recursos estão liberados. **Totens adicionais** podem ser contratados
avulso, inclusive em plano que não inclui nenhum.

### 7.5 Totens

| Computador | Celular |
|---|---|
| ![Totens](prints/master__master_totem_lista_pc.png) | ![Totens no celular](prints/master__master_totem_lista_cel.png) |

O número de patrimônio e o token de acesso são gerados pelo sistema —
ninguém digita. Marque **em comodato** no cadastro quando o equipamento
for da KS TEC; contrato e datas ficam na tela de comodato.

### 7.6 Comercial e demonstrações

| Configuração | Demonstrações |
|---|---|
| ![Configuração comercial](prints/master__master_comercial_config_pc.png) | ![Demonstrações](prints/master__master_comercial_demos_pc.png) |

O WhatsApp e o e-mail que aparecem na capa se configuram aqui — trocar um
telefone não exige deploy.

A **demonstração** cria um ambiente completo em segundos, com um
colaborador de exemplo e batidas suficientes para o espelho, o banco de
horas e o AFD terem o que mostrar. O ambiente é um cliente de verdade,
marcado com prazo: **converter é limpar a marca**, sem migrar nada.

Pode ser criada pela capa (o visitante preenche) ou aqui pelo painel
(quando o contato veio por telefone ou visita).

### 7.7 Assinaturas e custos

| Assinaturas | Custos e margem |
|---|---|
| ![Assinaturas](prints/master__master_assinaturas_pc.png) | ![Custos](prints/master__master_custos_pc.png) |

A receita bruta sozinha parece margem — e não é. Cada boleto compensado,
cada nota emitida e a própria hospedagem saem dela. A tela de custos
mostra os dois lados.

> Com a tabela de custos zerada, **tudo aparece como lucro**. Preencha as
> taxas em Gateway.

### 7.8 Gateway de pagamento

| Computador | Celular |
|---|---|
| ![Gateway](prints/master__master_gateway_pc.png) | ![Gateway no celular](prints/master__master_gateway_cel.png) |

Credenciais do ASAAS e a tabela de custos por transação.

> **Sem o token do webhook**, qualquer um poderia forjar uma confirmação
> de pagamento. Por isso o webhook recusa tudo enquanto ele não estiver
> configurado.

### 7.9 Usuários

| Lista | Cadastro |
|---|---|
| ![Usuários](prints/master__master_usuarios_pc.png) | ![Novo usuário](prints/master__master_usuario_criar_pc.png) |

O Master cria usuários em qualquer conta. **A senha não é escolhida por
quem cria**: o sistema gera uma provisória, exibe uma vez e obriga a
troca no primeiro acesso — assim não existe momento em que duas pessoas
conhecem a mesma senha.

Basta **e-mail ou CPF**; os dois funcionam para entrar.

### 7.10 Auditoria e logs

| Auditoria | Logs de acesso |
|---|---|
| ![Auditoria](prints/master__master_auditoria_pc.png) | ![Logs](prints/master__master_log_lista_pc.png) |

Tudo o que foi feito, por quem e quando, em todos os clientes. O registro
é imutável por construção.

---

## 8. Ajuda dentro do sistema

Em toda tela há um botão **?** no canto inferior direito.

- **Clique** para ver o que aquela tela faz e o que costuma dar errado
- Onde houver, **Ver o passo a passo** inicia um roteiro guiado que
  escurece a tela e aponta para cada parte
- Na primeira visita de cada tela a ajuda abre sozinha; depois disso, só
  por clique

---

## 9. Documentos fiscais

| Documento | O que é | Onde |
|---|---|---|
| **Comprovante** | Recibo de cada marcação, com número e código de verificação | Ponto → após bater |
| **Espelho de ponto** | O mês do colaborador, para conferência e assinatura | Ponto → Espelho |
| **AFD** | Arquivo Fonte de Dados — o que o Auditor-Fiscal pede | Relatórios → AFD e AEJ |
| **AEJ** | Arquivo Eletrônico de Jornada | Relatórios → AFD e AEJ |

Os arquivos seguem o leiaute dos Anexos V e VI da Portaria 671/2021,
incluindo o hash SHA-256 encadeado que permite a um auditor verificar, por
fora do sistema, que nenhum registro foi alterado.

**Verificação pública.** Qualquer pessoa com o código de um comprovante
pode conferir sua autenticidade em `kronus.online/verificar/`, sem
precisar de acesso ao sistema.

---

## Como atualizar este manual

As imagens são geradas do sistema real:

```bash
python ferramentas/capturar_telas.py
```

A ferramenta renderiza cada tela pelo próprio Django, fotografa em
computador e celular, e grava em `docs/prints/`. Quando uma tela muda,
rode de novo — o texto ao redor é que precisa de revisão humana.
