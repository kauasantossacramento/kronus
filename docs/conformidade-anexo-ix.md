# Conformidade com o Anexo IX — Levantamento

> **Para que serve.** O art. 91 da Portaria MTP 671/2021 exige que o REP-P
> atenda ao art. 78 e aos requisitos do Anexo IX. O Atestado Técnico
> (art. 89) declara esse atendimento sob responsabilidade civil e
> criminal. Este documento é a apuração que sustenta — ou impede — aquela
> assinatura.
>
> **Data da apuração:** 28/08/2026
> **Versão apurada:** ramo `main`, deploy em produção de 28/08/2026
> **Quem apurou:** levantamento automatizado sobre o código-fonte, com
> verificação de cada item no arquivo e linha indicados.

---

## Resumo

| | Requisitos |
|---|---|
| ✅ Atendido | 10 |
| ⚠️ Atendido com ressalva | 1 |
| ❌ Não atendido | 2 |
| **Total** | **13** |

**Os dois itens não atendidos são de infraestrutura, não de software** —
requisitos 6 e 13, ambos sobre redundância e alta disponibilidade. A VPS
atual é uma máquina única. Isso está coerente com a decisão registrada de
que ela é provisória, para validar o serviço; mas **enquanto for assim, o
Atestado Técnico não pode ser assinado sem ressalva**.

---

## Requisito 1 — Identificação da organização e do trabalhador

**Estado: ✅ atendido**

| Elemento | Onde |
|---|---|
| Organização: CNPJ ou CPF, razão social, CEI/CAEPF/CNO | `apps/clientes/models.py` — `Empresa.cnpj`, `razao_social`, `cei_caepf` |
| Tipo do identificador (1=CNPJ, 2=CPF) | `Empresa.tipo_identificador_afd` |
| Trabalhador: CPF e nome | `apps/rh/models.py` — `Colaborador.cpf`, `nome_completo` |

Evidência automatizada: `tests/test_empregador_pf.py` verifica que o tipo
do identificador acompanha o documento e chega correto ao AFD e ao AEJ.

---

## Requisito 2 — Sincronismo com a Hora Legal Brasileira (máx. 30s)

**Estado: ✅ atendido**

O servidor sincroniza com os servidores estrato 1 do NTP.br
(`a.st1.ntp.br` a `d.st1.ntp.br`), ligados diretamente aos relógios
atômicos do Observatório Nacional.

- Configuração: `/etc/systemd/timesyncd.conf.d/hlb.conf` na VPS
- Justificativa registrada em `apps/ponto/services.py`, linhas 35–45

**Prova documental da fonte.** O sistema reporta, na própria VPS:

```
ServerName=a.st1.ntp.br
NTPMessage={ ... Stratum=1, Reference=ONBR, Ignored=no ... }
```

`Reference=ONBR` é o identificador do **Observatório Nacional**, e
`Stratum=1` significa ligado diretamente ao relógio atômico, sem
intermediário — exatamente a fonte que o Anexo IX nomeia.

**Verificação contínua.** `apps/ponto/relogio.py` mede o desvio real por
consulta NTP direta, e `apps/ponto/tasks.verificar_relogio` roda de hora
em hora, alertando o Master acima de **5 segundos** — folga deliberada
sobre os 30 da norma, porque alertar ao cruzar o limite legal seria
alertar quando já se está em descumprimento.

Isso cobre a parte do requisito que a configuração sozinha não cobre: a
norma exige **manter** o sincronismo. Se o `systemd-timesyncd` parar, o
relógio deriva e as batidas seguem sendo gravadas — com hora errada — sem
que nada acuse.

**Medição em produção (28/08/2026):**

| | |
|---|---|
| Fonte | `a.st1.ntp.br` |
| Estrato | 1 |
| Referência | `ONBR` (Observatório Nacional) |
| Desvio medido | **0,00022 s** |
| Limite legal | 30 s |

Evidência automatizada: `tests/test_relogio.py`, com a saída real da VPS
como fixture — um formato suposto passaria no teste e falharia no
servidor.

---

## Requisito 3 — Coletor exibe relógio não-analógico com hora, minuto e segundo

**Estado: ✅ atendido**

O totem exibe relógio digital atualizado a cada segundo.

- `apps/totem/templates/totem/index.html` — elemento `data-relogio`
- `apps/totem/static/totem/js/ui-controller.js`, linha 75 —
  `toLocaleTimeString('pt-BR')`, que inclui segundos

A topbar do painel web também traz relógio digital com segundos
(`templates/components/topbar.html`).

---

## Requisito 4 — Marcações oriundas de coletor on-line

**Estado: ✅ atendido**

Toda marcação passa por `RegistroPontoService.registrar`
(`apps/ponto/services.py`), executada no servidor. O coletor não grava
nada localmente: ele envia e aguarda a confirmação.

O texto da norma permite o modo off-line como exceção — não o exige.
Operar exclusivamente on-line é a leitura mais restritiva e, portanto,
conforme.

---

## Requisito 5 — Registro off-line enviado ao voltar on-line

**Estado: ✅ atendido**

O totem registra a marcação localmente quando a conexão cai e a envia
assim que ela volta.

| Peça | Onde |
|---|---|
| Fila no coletor | `apps/totem/static/totem/js/fila-offline.js` |
| Recepção no servidor | `apps/ponto/sincronizacao.py` |
| Endpoints | `/api/v1/totem/colaboradores-offline/` e `/api/v1/totem/sincronizar/` |

**Três garantias que o desenho oferece:**

1. **A marcação é gravada antes de qualquer tentativa de envio.** Gravar
   depois perderia a batida se o aparelho desligasse no meio.
2. **Nada sai da fila sem confirmação do servidor.** Recusa fica na fila,
   marcada e visível — apagar em silêncio perderia o registro de que
   alguém trabalhou.
3. **Reenvio não duplica.** Cada marcação carrega um identificador
   próprio, com restrição de unicidade *na tabela* — verificar antes de
   inserir perderia a corrida entre dois envios simultâneos.

**Hora da marcação e hora da gravação são registradas separadamente**, e
o AFD declara `offline = 1` nesses registros. Usar a hora da chegada
seria registrar que a pessoa bateu o ponto quando a internet voltou; e
declarar "0" seria informar ao fiscal uma origem que não é a verdadeira.

**Identificação sem conexão sem expor CPF.** A lista que fica no tablet
não traz CPF em claro — traz uma derivação PBKDF2 com sal por
equipamento. Conferir uma digitação custa uma derivação; varrer o espaço
de CPFs custaria isso vezes um bilhão. Rotacionar o token do totem
invalida a lista inteira, que é o comportamento desejado quando um
equipamento é perdido.

**Verificação de ponta a ponta.** `ferramentas/prova_offline.py` sobe o
servidor, abre o navegador, derruba a rede, registra a marcação,
**recarrega a página**, restaura a rede e confere no banco. Não é mock: a
promessa é forte demais para ser verificada simulando o `fetch`. Rodada
em 28/08/2026, com o resultado esperado — batida gravada, marcada como
offline, sem duplicata no reenvio.

---

## Requisito 6 — ARP com redundância, alta disponibilidade e confiabilidade

**Estado: ❌ não atendido (infraestrutura) / ✅ atendido (conteúdo)**

O requisito tem duas partes. O **conteúdo** exigido está todo gravado; a
**característica da infraestrutura** não.

### 6.1 — Inclusão/alteração de dados do empregador
✅ `LogAcesso` grava ação, usuário, data/hora, objeto e IP
(`apps/core/models.py`, `Acao.CRIACAO` / `ALTERACAO` / `CONFIG`).

### 6.2 — Ajuste do relógio
⚠️ **Não aplicável na forma descrita.** O texto pressupõe um relógio
ajustado por pessoa, como no REP-C. Aqui o relógio é do sistema
operacional e se ajusta por NTP, sem intervenção humana — não há
"responsável pelo ajuste" a registrar. Vale declarar isso expressamente
no Atestado, em vez de deixar o campo silenciosamente vazio.

### 6.3 — Inserção, alteração e exclusão de empregado
✅ `LogAcesso` com `Acao.CRIACAO` / `ALTERACAO` / `EXCLUSAO`, registrando
usuário, data/hora e objeto.

### 6.4 — Eventos sensíveis
✅ `EventoTotem` (`apps/totem/models.py`) registra os eventos do
equipamento com código próprio: online, offline, reconhecimento bem
sucedido e malsucedido, registro por CPF, erro do aplicativo e ações
administrativas.

### 6.5 — Marcação de ponto
✅ Todos os campos exigidos, em `apps/ponto/models.py`:

| Exigido | Campo |
|---|---|
| CPF | via `colaborador.cpf` |
| Data e hora da marcação | `data_hora` (com fuso — `USE_TZ`) |
| Fuso da marcação | preservado no `DateTimeField` e emitido em ISO 8601 no AFD |
| Data e hora da gravação | `created_at` |
| Identificador do coletor | `totem` |
| Hash SHA-256 | `hash_registro`, encadeado a `hash_anterior` |

### NSR por estabelecimento, sequencial, iniciando em 1
✅ `models.UniqueConstraint(fields=["empresa", "nsr"])`
(`apps/ponto/models.py:276`). A sequência é por empresa, como a norma
determina.

### ❌ Redundância e alta disponibilidade
A base roda em **uma única VPS**, sem réplica, sem failover. Há backup
diário automatizado, o que atende "confiabilidade", mas **não**
"redundância" nem "alta disponibilidade".

**O que falta:** réplica de leitura do PostgreSQL em outra máquina, ou
banco gerenciado com replicação; e um segundo nó de aplicação. É decisão
de infraestrutura e custo, não de código.

---

## Requisito 7 — Dados da ARP não podem ser apagados ou alterados

**Estado: ✅ atendido**

Três camadas independentes:

1. **Exclusão bloqueada no modelo.** `RegistroPonto.delete()` levanta
   exceção (`apps/ponto/models.py:312`): *"Registros de ponto não podem
   ser excluídos. Utilize o cancelamento por ajuste."*
2. **Cancelamento em vez de exclusão.** O campo `cancelado` anula o
   efeito preservando o registro e o NSR — a Portaria anula, não apaga.
3. **Cadeia de hash.** Cada registro carrega o SHA-256 do anterior;
   alterar um invalida todos os seguintes. `RegistroPontoService.verificar_cadeia`
   detecta a divergência.

Evidência automatizada: os testes da cadeia de integridade, incluindo
regressão que falha se a normalização de fuso for revertida.

---

## Requisito 8 — Passos da marcação de ponto

**Estado: ✅ atendido**

| Passo | Onde |
|---|---|
| 8.1 Identificação inequívoca | Reconhecimento facial (ArcFace, limiar 0,60) com alternativa por CPF + data de nascimento |
| 8.2 Data e hora confiáveis | Hora do servidor, sincronizada com o ON; `validators.validar_data_hora` recusa marcação no futuro |
| 8.3 Gravação na ARP | `RegistroPontoService.registrar`, em transação com o consumo do NSR |
| 8.4 Comprovante | `apps/relatorios/` — comprovante com os campos do art. 79 |

---

## Requisito 9 — Comprovante impresso (densidade e altura)

**Estado: ✅ atendido por não se aplicar**

O comprovante é entregue em formato eletrônico (PDF e tela). O requisito
condiciona-se a *"caso seja adotado o formato impresso"*.

O PDF é gerado em formato de bobina/A6
(`apps/relatorios/templates/relatorios/comprovante.html`) e, se impresso,
usa fonte com altura muito superior a 3 mm. **Se a KS TEC passar a
oferecer impressora térmica, este item precisa de medição real** — não de
suposição.

---

## Requisito 10 — Campos do registro na ARP

**Estado: ✅ atendido**

Os oito campos exigidos estão gravados (ver 6.5) e são emitidos no AFD
conforme o Anexo V, validado contra o texto publicado no DOU:

- Registro tipo 7, 137 caracteres
- NSR (9), tipo (1), data/hora da marcação (24, ISO 8601 com fuso),
  CPF (12), data/hora da gravação (24), coletor (2), indicador off-line
  (1), hash SHA-256 (64)

---

## Requisito 11 — Geração do AFD

**Estado: ✅ atendido**

`apps/relatorios/afd.py` — `AFDGenerator`. Layout conferido contra o
texto do DOU, incluindo CRC-16/KERMIT nos registros que o exigem e o hash
oficial do arquivo, reproduzível por um auditor sem acesso ao sistema.

> Nota sobre o texto da norma: o Anexo IX menciona *"em conformidade com
> o Anexo I"*, mas o layout do AFD está no **Anexo V**. A implementação
> segue o Anexo V, que é o que traz o leiaute.

---

## Requisito 12 — AFD por intervalo temporal

**Estado: ✅ atendido**

`AFDGenerator(empresa, data_inicio, data_fim)` — o intervalo é parâmetro
obrigatório. A tela de relatórios fiscais expõe a seleção de período.

---

## Requisito 13 — Alta disponibilidade de todos os equipamentos e programas

**Estado: ❌ não atendido**

Mesma limitação do requisito 6: máquina única, sem redundância. Os
serviços têm reinício automático (`systemd`) e há monitoramento de totem
off-line, mas **uma falha da VPS interrompe o registro de ponto de todos
os clientes**.

**O que falta:** segundo nó de aplicação com balanceamento, e banco com
réplica. É custo de infraestrutura.

---

## Conclusão e o que fazer antes de assinar o Atestado

**Nove dos treze requisitos estão plenamente atendidos, com evidência
verificável.** Os quatro restantes se dividem em dois grupos:

### Bloqueiam o Atestado sem ressalva

| # | Requisito | O que falta | Natureza |
|---|---|---|---|
| 6 | Redundância e alta disponibilidade da ARP | Réplica do banco e segundo nó | Infraestrutura |
| 13 | Alta disponibilidade do conjunto | Idem | Infraestrutura |

### Resolvido durante esta apuração

| # | O que era | O que foi feito |
|---|---|---|
| 2 | Sem verificação do desvio | Medição por consulta NTP direta, de hora em hora, com alerta ao Master acima de 5s |
| 5 | Sem registro off-line, e o plano anunciava o recurso | Fila no coletor, envio ao reconectar, verificação ponta a ponta |

### Ordem sugerida

1. **Registrar o programa no INPI** (art. 91) — ver
   [`registro-inpi.md`](registro-inpi.md).
2. **Resolver a infraestrutura** — enquanto a VPS for única, os
   requisitos 6 e 13 não são atendidos. Duas saídas honestas:
   - migrar para infraestrutura redundante antes de assinar; ou
   - assinar declarando a limitação, e assumir o risco de a fiscalização
     considerá-la descumprimento.

> **Recomendação.** Não assine o Atestado Técnico declarando atendimento
> integral enquanto 6 e 13 não estiverem resolvidos. O documento tem
> responsabilidade criminal, e a limitação é verificável por qualquer
> auditor que pergunte quantos servidores existem.

---

## Como refazer esta apuração

Cada item acima aponta arquivo e, quando útil, linha. A apuração deve ser
refeita a cada mudança relevante — e, obrigatoriamente, **antes de cada
emissão de Atestado Técnico para um novo cliente**, porque o documento
declara o estado do sistema naquele momento, não no momento em que este
levantamento foi escrito.
