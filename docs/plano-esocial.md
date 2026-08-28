# Plano de desenvolvimento — Integração eSocial (Kronus)

> **Para quem é este documento:** um agente de IA executando fase a fase.
> Cada fase tem objetivo, entregáveis, critérios de aceite e testes. Uma
> fase só é dada por concluída quando **todos** os critérios passam.
>
> **Modelo de certificado adotado:** cada empresa cliente envia o próprio
> certificado A1. Decisão do responsável pelo produto — procuração
> eletrônica por cliente foi descartada por custo operacional.
>
> **Referência normativa:** Manual de Orientação do Desenvolvedor do
> eSocial (MOS Dev) e Manual de Orientação do eSocial, leiaute S-1.3.

---

## 0. Fatos técnicos confirmados na fonte

Estes valores foram extraídos do MOS Dev. **Não os altere sem conferir a
versão vigente do manual** — são a origem da maior parte das rejeições.

### Transporte

| Item | Valor |
|---|---|
| Protocolo | SOAP 1.1, `Document/Literal` |
| Transporte | HTTPS/TLS com **autenticação mútua (mTLS)** |
| Tamanho máximo da mensagem SOAP | **750 KB** |
| Máximo de eventos por lote | **50** (código 611 rejeita o lote) |
| Fluxo | **assíncrono**: envia → recebe protocolo → consulta depois |

### Endpoints

```
# Produção
https://webservices.envio.esocial.gov.br/servicos/empregador/enviarloteeventos/WsEnviarLoteEventos.svc

# Produção Restrita (homologação)
https://webservices.producaorestrita.esocial.gov.br/servicos/empregador/enviarloteeventos/WsEnviarLoteEventos.svc

# Consulta ao resultado do processamento
https://webservices.consulta.esocial.gov.br/servicos/empregador/consultarloteeventos/WsConsultarLoteEventos.svc
```

Métodos: `EnviarLoteEventos`, `ConsultarLoteEventos`.

### Assinatura digital — especificação literal

O eSocial usa um subconjunto do XMLDSig. **O detalhe que mais derruba
implementação é o `URI` vazio**: assina-se o documento inteiro, não um
elemento por `Id`.

| Parâmetro | Valor exigido |
|---|---|
| Formato | Enveloped |
| Certificado | ICP-Brasil, **A1 ou A3**, chave de **2048 bits** |
| Cadeia | **EndCertOnly** — só o certificado final na assinatura |
| `CanonicalizationMethod` | `http://www.w3.org/TR/2001/REC-xml-c14n-20010315` |
| `SignatureMethod` | `http://www.w3.org/2001/04/xmldsig-more#rsa-sha256` |
| `DigestMethod` | `http://www.w3.org/2001/04/xmlenc#sha256` |
| `Reference URI` | **`""` (vazio)** |
| Transform 1 | `http://www.w3.org/2000/09/xmldsig#enveloped-signature` |
| Transform 2 | `http://www.w3.org/TR/2001/REC-xml-c14n-20010315` |
| `KeyInfo` | **apenas** `X509Data/X509Certificate` |

Estrutura resultante:

```xml
<?xml version="1.0" encoding="utf-8"?>
<eSocial xmlns="http://www.esocial.gov.br/schema/evt/...">
  <!-- XML do evento -->
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
    <SignedInfo>
      <CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
      <SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
      <Reference URI="">
        <Transforms>
          <Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>
          <Transform Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
        </Transforms>
        <DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
        <DigestValue>...</DigestValue>
      </Reference>
    </SignedInfo>
    <SignatureValue>...</SignatureValue>
    <KeyInfo>
      <X509Data>
        <X509Certificate>...</X509Certificate>
      </X509Data>
    </KeyInfo>
  </Signature>
</eSocial>
```

> A tag `<Signature>` é **irmã** do evento, dentro de `<eSocial>`, e vem
> depois dele.

### Identificador do evento

36 posições: `ID` + tipo de inscrição (1) + inscrição (14, completada com
zeros) + `AAAAMMDDHHMMSS` (14) + sequencial (5).

```
ID2333901700001892014020213424700001
```

---

## Fase 0 — Escopo, e o que o Kronus **não** deve enviar

**Objetivo:** decidir quais eventos são responsabilidade do sistema de
ponto, e registrar a decisão antes de escrever código.

O eSocial é, em essência, uma obrigação da folha de pagamento. Um sistema
de ponto contribui com uma fatia. **Enviar mais do que a fatia cria
conflito com o sistema de folha do cliente** — dois emissores mandando o
mesmo evento produzem duplicidade e retificação em cascata.

### Escopo proposto

| Evento | Nome | Por que é do Kronus |
|---|---|---|
| **S-1050** | Tabela de Horários/Turnos de Trabalho | As escalas já vivem no Kronus; é o evento que descreve jornada |
| **S-2230** | Afastamento Temporário | O Kronus já registra atestados, férias e licenças |
| **S-2206** | Alteração de Contrato de Trabalho | Só quando a mudança for **de jornada**, referenciando o código do S-1050 |

### Fora de escopo (justificar por escrito ao cliente)

- **S-1200** (remuneração), **S-1210** (pagamentos), **S-2299/S-2399**
  (desligamento): são da folha. O Kronus **alimenta** a folha com horas
  via exportação, mas não transmite.
- **S-1010** (rubricas), **S-1020** (lotações): cadastro da folha.
- **S-2210** (CAT), **S-2220** (monitoramento da saúde): SST, outro
  domínio.

### Entregáveis

- `docs/esocial-escopo.md` com a tabela acima, o motivo de cada exclusão
  e a **cláusula de conflito**: o cliente declara, na contratação, quem
  transmite S-1050 e S-2230 — Kronus ou o sistema de folha. Nunca os dois.

### Critérios de aceite

- [ ] Documento revisado e aprovado pelo responsável pelo produto
- [ ] Cláusula de conflito incorporada ao fluxo de ativação do cliente

---

## Fase 1 — Custódia do certificado A1 do cliente

**Objetivo:** receber, guardar e usar o `.pfx`/`.p12` do cliente sem
transformá-lo num passivo.

> **Leia isto antes de escrever qualquer linha.** Um A1 é a identidade
> jurídica da empresa. Quem tem o arquivo e a senha pode assinar
> contrato, nota fiscal e declaração fiscal em nome dela. Este é, com
> folga, o item mais sensível do Kronus — mais do que a biometria, porque
> o dano não tem limite e não é reversível. Trate cada decisão desta fase
> como decisão de segurança, não de conveniência.

### Entregáveis

**`apps/esocial/models.py`**

```
CertificadoDigital
  empresa            OneToOne
  arquivo_cifrado    BinaryField    # o .pfx, cifrado
  senha_cifrada      BinaryField    # a senha do .pfx, cifrada
  titular_cnpj       CharField      # extraído do certificado, não digitado
  titular_nome       CharField
  emissor            CharField
  valido_de          DateTimeField
  valido_ate         DateTimeField
  impressao_digital  CharField      # SHA-256 do DER, para auditoria
  enviado_em / enviado_por
  ativo              BooleanField
```

**`apps/esocial/cofre.py`** — cifra e decifra.

- Chave mestra em `ESOCIAL_CHAVE_COFRE` (`.env`), **nunca no banco**.
  Backup do banco vazado não pode bastar para usar os certificados.
- AES-GCM (`cryptography.hazmat`), nonce por registro, dados associados
  = id da empresa (impede trocar o blob de uma empresa por outro).
- `carregar(empresa)` devolve um objeto em memória e **nunca** escreve o
  `.pfx` decifrado em disco. Se uma biblioteca exigir caminho de arquivo,
  usar arquivo temporário com permissão `0600`, em `tmpfs`, apagado em
  `finally`.

**Validação no upload** — recusar e explicar, nunca aceitar em silêncio:

1. Abre com a senha informada (senha errada → erro claro).
2. Extrai o CNPJ do titular e **compara com o CNPJ da empresa**. Divergiu,
   recusa: certificado de outra empresa é erro de operação, não detalhe.
3. Confere validade (não expirado, não futuro).
4. Confere que é ICP-Brasil e que a chave tem 2048 bits.
5. Registra na auditoria: quem enviou, quando, impressão digital.

**Consentimento** — a tela de upload exige aceite explícito, com texto que
diz o que o Kronus fará com o certificado, e o registro do aceite (quem,
quando, IP, versão do texto).

**Ciclo de vida** — A1 vale 1 ano. Alertar em D-30, D-15, D-7 e D-1, e
bloquear o envio com mensagem clara quando expirar. Certificado vencido
descoberto no dia do prazo legal é um incidente evitável.

**Remoção** — o cliente pode excluir o certificado a qualquer momento;
a exclusão apaga os bytes (não marca flag) e fica na auditoria.

### Critérios de aceite

- [ ] `.pfx` decifrado nunca toca disco não volátil (teste que verifica)
- [ ] Blob cifrado de uma empresa não decifra no contexto de outra
- [ ] Upload com CNPJ divergente é recusado com mensagem específica
- [ ] Upload com senha errada é recusado sem stack trace vazando
- [ ] Certificado expirado bloqueia o envio e dispara notificação
- [ ] Auditoria registra upload, uso e exclusão
- [ ] `ESOCIAL_CHAVE_COFRE` ausente impede subir a aplicação (falha alta)

### Testes

- Fixture com A1 **autoassinado de teste** (gerado no próprio teste, nunca
  um certificado real versionado)
- Round-trip cifra/decifra; adulteração de 1 byte falha a autenticação GCM
- Tentativa de decifrar com id de empresa trocado falha

---

## Fase 2 — Assinatura XMLDSig

**Objetivo:** produzir assinatura aceita pelo eSocial. Esta é a fase com
maior chance de erro silencioso: um XML mal canonicalizado é sintaticamente
válido e é rejeitado só no servidor.

### Entregáveis

**`apps/esocial/assinatura.py`**

```python
def assinar(xml_evento: bytes, certificado) -> bytes:
    """Assina conforme a seção 0 deste plano. Enveloped, URI vazio."""
```

Implementar com `signxml` (recomendado) ou `lxml` + `cryptography`. Se
usar `signxml`, fixar explicitamente todos os parâmetros — os padrões da
biblioteca **não** coincidem com o exigido pelo eSocial.

Regras que não podem ser esquecidas:

- `Reference URI=""` — documento inteiro.
- Transforms na ordem: `enveloped-signature`, depois `C14N`.
- `KeyInfo` **só** com `X509Data/X509Certificate`. Nada de `KeyValue`,
  nada de cadeia — `EndCertOnly`.
- `<Signature>` inserida como **último filho de `<eSocial>`**, irmã do
  evento.
- Sem declaração de `standalone`; encoding `utf-8`.
- **Nenhuma reformatação depois de assinar.** Um `pretty_print`, um
  espaço a mais, uma quebra de linha — o digest muda e o eSocial rejeita.
  Serializar uma vez e transportar os mesmos bytes.

### Critérios de aceite

- [ ] Assinatura gerada é **verificável** pela própria biblioteca contra o
      certificado (teste de ida e volta)
- [ ] Alterar 1 byte do evento invalida a verificação
- [ ] Os 6 URIs de algoritmo conferem literalmente com a tabela da seção 0
      (teste que compara strings, não "contém")
- [ ] `KeyInfo` contém exatamente um `X509Certificate` e nada mais
- [ ] Reserializar o XML assinado **não** altera os bytes

### Testes

Teste de regressão com vetor fixo: certificado de teste determinístico,
evento fixo, assinatura esperada. Protege contra atualização de biblioteca
que mude canonicalização silenciosamente.

---

## Fase 3 — Geração dos XML dos eventos

**Objetivo:** produzir S-1050, S-2230 e S-2206 válidos contra o XSD, a
partir dos dados que já existem no Kronus.

### Entregáveis

- `apps/esocial/xsd/` — XSDs oficiais do leiaute S-1.3, versionados no
  repositório (com um `README` dizendo de onde vieram e quando).
- `apps/esocial/eventos/base.py` — `ideEvento` (`indRetif`, `nrRecibo`,
  `tpAmb`, `procEmi=1`, `verProc=<versão do Kronus>`), `ideEmpregador`,
  e o gerador do `Id` de 36 posições.
- `apps/esocial/eventos/s1050.py`, `s2230.py`, `s2206.py`.
- **Validação contra o XSD antes de assinar**, sempre. Rejeitar cedo é
  barato; rejeitar no servidor consome cota diária.

> `tpAmb`: `1` = produção, `2` = produção restrita. **Derivar do ambiente
> configurado, jamais de constante no código** — o erro clássico é
> homologar com `2` e subir para produção ainda mandando `2`.

### Mapeamento a definir (e documentar)

| Dado no Kronus | Campo do evento |
|---|---|
| `Escala` / horários | S-1050 `dadosHorContratual`, `horarioIntervalo` |
| `Atestado` | S-2230 `infoAfastamento`, `codMotAfast`, datas |
| Férias | S-2230 com o código de motivo próprio |
| Mudança de jornada | S-2206 referenciando `codHorContrat` do S-1050 |

A tabela de `codMotAfast` é do MOS. **Não invente códigos**: mapeie os
tipos de atestado do Kronus para os códigos oficiais numa tabela
explícita e falhe quando não houver correspondência, em vez de escolher
um genérico.

### Critérios de aceite

- [ ] Todo XML gerado valida contra o XSD oficial
- [ ] `Id` tem exatamente 36 posições e o formato da seção 0
- [ ] `tpAmb` vem do ambiente, com teste que prova
- [ ] Tipo de afastamento sem mapeamento levanta erro nomeado, não envia

---

## Fase 4 — Montagem do lote

**Objetivo:** empacotar eventos em lotes válidos.

### Entregáveis

`apps/esocial/lote.py` — monta `envioLoteEventos` com `ideEmpregador`,
`ideTransmissor` e os eventos assinados.

Restrições obrigatórias:

- **Máximo 50 eventos por lote** — exceder é rejeição 611 do lote inteiro.
- **Máximo 750 KB** por mensagem SOAP — dividir por tamanho **também**,
  não só por contagem. Cinquenta eventos grandes estouram o limite antes
  de estourar a contagem.
- Um lote só carrega eventos do **mesmo grupo** e do **mesmo empregador**.
- Não misturar grupos durante o envio de eventos periódicos.

### Critérios de aceite

- [ ] Lote com 51 eventos é dividido em dois, automaticamente
- [ ] Lote que ultrapassaria 750 KB é dividido por tamanho
- [ ] Teste com evento artificialmente grande prova a divisão por bytes
- [ ] Lote nunca mistura empregadores

---

## Fase 5 — Transporte SOAP com mTLS

**Objetivo:** transmitir e receber o protocolo.

> O mesmo A1 é usado **duas vezes**: para assinar o XML e para autenticar
> a conexão TLS. São usos independentes — funcionar um não implica
> funcionar o outro, e a mensagem de erro quando o mTLS falha costuma ser
> genérica.

### Entregáveis

`apps/esocial/transporte.py`

- Cliente SOAP 1.1 `Document/Literal` (`zeep`, ou `requests` com envelope
  montado à mão — para dois métodos, o envelope manual tem menos
  superfície de surpresa).
- mTLS: `requests` com `cert=(pem_cert, pem_key)` a partir do A1
  decifrado em memória. Se a biblioteca exigir arquivo, seguir a regra da
  Fase 1 (tmpfs, `0600`, `finally`).
- Timeouts explícitos, e **retry só para falha de rede** — nunca para
  rejeição de negócio. Reenviar um evento recusado por regra é como
  bater na mesma porta mais forte.
- Toda requisição e resposta gravadas (XML enviado, XML recebido, código
  HTTP, duração). Sem isso, uma rejeição no dia do prazo vira adivinhação.

### Critérios de aceite

- [ ] Envio contra Produção Restrita retorna protocolo
- [ ] Falha de mTLS produz erro **distinto** de falha de assinatura
- [ ] Timeout não deixa o evento em estado ambíguo
- [ ] Requisição e resposta persistidas e consultáveis na interface

---

## Fase 6 — Consulta do resultado

**Objetivo:** buscar recibos e erros; o envio é assíncrono e sem esta
fase não se sabe o que aconteceu.

### Entregáveis

- `ConsultarLoteEventos` pelo protocolo.
- Task Celery periódica que consulta lotes pendentes com **espera
  crescente** (30s, 1min, 5min, 15min...). Sem isso a cota diária de
  solicitações é queimada em minutos (erro 405: limite diário).
- Persistir por evento: `nrRecibo` (sucesso) ou lista de ocorrências
  (código, descrição, localização).
- Traduzir os códigos mais comuns para linguagem que o RH entende, sem
  esconder o código original.

> A consulta por período exige data-fim de **pelo menos uma hora antes**
> do momento atual. Não é sugestão: é regra do serviço.

### Critérios de aceite

- [ ] Recibo persistido e visível na interface
- [ ] Erro exibe código + descrição oficial + explicação em português claro
- [ ] Backoff comprovado por teste (não consulta em intervalo fixo curto)
- [ ] Perda de conexão no meio da consulta não perde o protocolo

---

## Fase 7 — Máquina de estados, retificação e exclusão

**Objetivo:** garantir que nada seja enviado duas vezes e que erros
tenham conserto.

### Entregáveis

Estados por evento:

```
RASCUNHO → ASSINADO → ENVIADO → (AGUARDANDO_RETORNO)
             ├→ ACEITO   (nrRecibo)
             ├→ REJEITADO (ocorrências) → corrigir → novo envio
             └→ ERRO_TECNICO → reenvio seguro
```

- **Idempotência:** um evento com `nrRecibo` **nunca** é reenviado.
  Constraint no banco, não só verificação no código.
- **Retificação:** `indRetif=2` + `nrRecibo` do evento original. Nunca
  reenviar como original.
- **Exclusão:** evento **S-3000** para eventos não periódicos enviados
  por engano.
- Transição de estado registrada com quem, quando e por quê.

### Critérios de aceite

- [ ] Reenvio de evento aceito é impedido pelo banco (teste com constraint)
- [ ] Retificação carrega `indRetif=2` e o recibo original
- [ ] Nenhuma transição sem autor e data
- [ ] Concorrência: dois workers pegando o mesmo evento não enviam dois

---

## Fase 8 — Interface no Kronus

**Objetivo:** o cliente opera sozinho; o master enxerga tudo.

### Entregáveis

**Para a empresa** (`/rh/esocial/`)

- Envio do certificado A1, com o texto de consentimento e o estado da
  validade em destaque.
- Painel: eventos pendentes, enviados, aceitos, rejeitados.
- Rejeição mostra o que corrigir e um botão para reenviar depois de
  corrigido.
- Chave para ligar/desligar a transmissão — respeitando a cláusula de
  conflito da Fase 0.

**Para o master** (`/master/esocial/`)

- Visão de todos os clientes: quem tem certificado, quem está perto de
  vencer, taxa de rejeição por cliente.
- **Nunca** exibir, baixar ou logar o conteúdo do certificado.

### Critérios de aceite

- [ ] Empresa A não enxerga nada da empresa B (teste multi-tenant)
- [ ] Certificado não aparece em log, em resposta de API nem no admin
- [ ] Tela de rejeição é compreensível para quem não é técnico

---

## Fase 9 — Homologação em Produção Restrita

**Objetivo:** provar o ciclo completo antes de tocar em dado real.

> A Produção Restrita limita **1.000 vínculos por empregador**. É
> suficiente para homologar; não serve como ambiente de carga.

### Roteiro

1. Cadastrar a KS TEC (ou um cliente-piloto voluntário) na Produção
   Restrita.
2. Certificado A1 real do CNPJ de teste — a Produção Restrita exige
   certificado válido, não aceita autoassinado.
3. Enviar, nesta ordem: **S-1050** → **S-2206** → **S-2230**.
4. Exercitar deliberadamente os caminhos ruins:
   - evento com campo obrigatório faltando → confirmar a rejeição legível
   - lote com 51 eventos → confirmar a divisão automática
   - certificado vencido → confirmar o bloqueio
   - retificação de evento aceito → confirmar `indRetif=2`
   - exclusão via S-3000
5. Registrar cada protocolo, recibo e ocorrência em
   `docs/esocial-homologacao.md`.

### Critérios de aceite

- [ ] Os três eventos aceitos, com recibo
- [ ] Retificação aceita
- [ ] Exclusão aceita
- [ ] Todos os caminhos de erro produzem mensagem acionável
- [ ] Evidências arquivadas com data, protocolo e recibo

---

## Fase 10 — Produção

**Objetivo:** ativar com o menor raio de dano possível.

### Roteiro

1. **Chave de ambiente** — trocar endpoint e `tpAmb` por configuração.
   Teste automatizado que falha se `tpAmb` não acompanhar o endpoint.
2. **Um cliente piloto**, com poucos colaboradores e ciente do piloto.
3. **Primeiro envio acompanhado**: uma pessoa olhando o retorno, não
   agendado de madrugada.
4. **Abrir para os demais em ondas**, não todos de uma vez.
5. **Plano de contingência documentado**: se o Kronus não transmitir, o
   cliente usa o Portal Web do eSocial — que é a contingência oficial
   prevista no manual. O cliente precisa saber disso **antes** de
   precisar.

### Critérios de aceite

- [ ] Impossível apontar para produção com `tpAmb=2` (teste prova)
- [ ] Piloto com ciclo completo aceito em produção
- [ ] Contingência escrita e entregue ao cliente
- [ ] Rollback: desligar a transmissão não perde evento pendente

---

## Fase 11 — Operação contínua

**Objetivo:** o que mantém a integração viva depois da euforia da entrega.

- **Vencimento de certificado**: alertas D-30/15/7/1 (Fase 1) mais
  relatório semanal ao master.
- **Mudança de leiaute**: o eSocial versiona (hoje S-1.3) e publica notas
  técnicas. Designar um responsável por acompanhar a área de documentação
  técnica; XSD desatualizado rejeita tudo, de uma vez, sem aviso.
- **Painel de saúde**: taxa de rejeição por cliente e por código. Um pico
  num código específico costuma ser mudança de regra, não erro do cliente.
- **Cota diária**: monitorar o erro 405. Bater na cota é sintoma de laço
  de reenvio, quase nunca de volume real.
- **Retenção**: guardar XML enviado e recibo pelo prazo legal. O recibo é
  a prova de cumprimento da obrigação.

---

## Ordem de execução e dependências

```
Fase 0  escopo
   ↓
Fase 1  custódia do A1  ─────┐
   ↓                          │
Fase 2  assinatura  ←─────────┘
   ↓
Fase 3  XML dos eventos
   ↓
Fase 4  lote
   ↓
Fase 5  transporte mTLS
   ↓
Fase 6  consulta do retorno
   ↓
Fase 7  máquina de estados
   ↓
Fase 8  interface
   ↓
Fase 9  Produção Restrita
   ↓
Fase 10 produção (piloto → ondas)
   ↓
Fase 11 operação
```

As fases 2 e 3 podem correr em paralelo (a assinatura não depende do
conteúdo do evento). Todo o resto é sequencial: cada fase precisa da
anterior funcionando para ser testável de verdade.

---

## Nota sobre infraestrutura

A VPS atual (1 vCPU) é provisória, para validar o serviço. Ainda assim, o
desenho desta integração não deve depender de folga de CPU:

- Assinatura e transporte vivem **no worker Celery**, nunca no ciclo da
  requisição web. Assinar em RSA-2048 num vCPU compartilhado com o
  reconhecimento facial é a receita para uma página que trava.
- A consulta com espera crescente (Fase 6) já protege contra laço de
  polling — que seria o maior consumidor de CPU desta integração.
- O envio é assíncrono por natureza do eSocial; não há caminho quente.

Quando a VPS crescer, nada aqui precisa mudar — o que muda é a
concorrência do worker.

---

## Fontes

- [eSocial — Documentação Técnica: Manual de Orientação do Desenvolvedor v1.10](https://www.gov.br/esocial/pt-br/documentacao-tecnica/manuais/manualorientacaodesenvolvedoresocialv1-10.pdf)
- [eSocial — MOS S-1.3 consolidado](https://www.gov.br/esocial/pt-br/documentacao-tecnica/manuais/mos-s-1-3-consolidada-ate-a-no-s-1-3-11-2026-retificada.pdf)
- [eSocial — Novas URL para transmissão dos dados de produção](https://www.gov.br/esocial/pt-br/noticias/divulgadas-novas-url-para-transmissao-dos-dados-de-producao-do-esocial)
- [eSocial — Ambiente de Produção Restrita](https://www.gov.br/esocial/pt-br/acesso-ao-sistema/ambiente-de-producao-restrita)
