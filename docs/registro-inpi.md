# Registro do Kronus no INPI e Atestado Técnico

> Documento operacional. Quem executa: responsável legal da KS TEC.
> Base legal: Portaria MTP 671/2021 (art. 89 e art. 91), Lei 9.609/1998,
> Lei 9.610/1998, Decreto 2.556/1998.

---

## 1. Por que isto não é opcional

> **Art. 91.** O REP-P deve possuir certificado de registro de programa de
> computador no Instituto Nacional da Propriedade Industrial, atender ao
> art. 78 e aos requisitos elencados no Anexo IX.

O Kronus é um REP-P. Sem o número de registro do INPI ele **não pode ser
comercializado como registrador eletrônico de ponto**, e nenhum cliente
pode usá-lo legalmente para marcar ponto — porque o art. 89, § 4º proíbe
o empregador de usar o sistema sem o Atestado Técnico, e o Atestado
Técnico (Anexo VII) tem um campo obrigatório chamado *"Número de registro
no INPI"*.

Ou seja: **o registro no INPI é o que destrava a venda.** Um fiscal que
pedir o Atestado e encontrar "N/A" nesse campo tem, ali mesmo, a prova de
que o sistema não atende à Portaria.

### Onde o número entra depois de emitido

| Lugar | Referência |
|---|---|
| Cabeçalho do AFD, registro tipo 1, campo 7 | Anexo V |
| Nome do arquivo AFD | item 19.3 |
| AEJ, registro tipo 02, campo `nrRep` | Anexo VI |
| Comprovante de registro de ponto | art. 79, VII |
| Atestado Técnico e Termo de Responsabilidade | Anexo VII |

No código, o valor vive em `REGISTRO_INPI` (`.env`). **Enquanto estiver
vazio, o Kronus emite documentos fiscais inválidos** — é o único item
pendente que bloqueia a operação comercial.

---

## 2. O que se registra (e o que não se registra)

Registra-se **o programa de computador** — o código-fonte do Kronus — em
nome da **KS TEC** (pessoa jurídica, CNPJ), na qualidade de titular.

O que **não** é este registro:

- **Não é marca.** O nome "Kronus" e o logotipo se protegem por registro
  de marca (INPI, mas outro processo, outra taxa, classe de Nice 42/9).
  São coisas independentes: dá para ter o software registrado e o nome
  não, e vice-versa. Para o art. 91, só o do programa importa.
- **Não é patente.** Software no Brasil se protege por direito autoral,
  não por patente.
- **Não é homologação técnica.** O INPI não analisa se o Kronus atende à
  Portaria 671. Ele só registra a autoria e a data. Quem atesta a
  conformidade é você mesmo, no Atestado Técnico da seção 6 — sob
  responsabilidade civil e criminal.

### Titularidade — decidir antes de peticionar

Se o código foi escrito por empregado ou prestador da KS TEC no exercício
do contrato, a titularidade é da empresa (Lei 9.609/98, art. 4º). Se
houve colaborador sem vínculo formal, **resolva por contrato de cessão
antes de registrar**: um titular errado no certificado é um vício que só
se corrige com novo processo.

Autores pessoas físicas podem ser nomeados no pedido mantendo a KS TEC
como titular — e vale nomear, porque é o que liga o certificado às
pessoas que assinam o Atestado Técnico.

---

## 3. Pré-requisitos

1. **Certificado digital ICP-Brasil** da KS TEC (e-CNPJ A1 ou A3) ou do
   responsável legal (e-CPF).
   > O sistema do INPI **não aceita** assinatura Gov.br nem ACOAB.
   > Só certificado qualificado ICP-Brasil.
2. **Cadastro no e-INPI** (login e senha) — em nome do CNPJ da KS TEC.
3. **Pacote documental do programa**, montado conforme a seção 4.

---

## 4. Preparar o pacote documental e gerar o hash

Este é o passo que a maioria erra, porque a lógica mudou: **o INPI não
guarda mais o seu código.** Você declara apenas um *hash* (resumo
criptográfico) e **guarda o arquivo original por conta própria**.

A consequência prática é dura e vale repetir: **se você perder o arquivo
que gerou o hash, o registro perde quase todo o valor probatório.** O
certificado passa a atestar que, em tal data, alguém registrou um hash de
algo que ninguém mais consegue exibir.

### 4.1 O que entra no pacote

Trechos do código-fonte e dados **suficientes para identificar e
caracterizar a originalidade** do programa. Na prática, para o Kronus:

- Código-fonte das partes que caracterizam o sistema — no mínimo o núcleo
  de conformidade: `apps/ponto/`, `apps/relatorios/` (AFD, AEJ, CRC-16),
  `apps/core/utils.py` (cadeia de hash), `apps/facial/`.
- Estrutura de diretórios do projeto.
- Modelo de dados (as migrations ou o diagrama).
- Um documento de descrição funcional curto: o que o programa faz,
  linguagem, plataforma, campo de aplicação.

**Não inclua segredos.** `.env`, chaves, senhas e certificados ficam de
fora — o pacote pode ser aberto em juízo.

### 4.2 Congelar a versão

Registre uma versão identificada, não "o repositório de hoje". Crie uma
tag e trabalhe a partir dela:

```bash
git tag -a inpi-v1.0.0 -m "Versao submetida ao INPI"
git push origin inpi-v1.0.0
```

### 4.3 Montar o arquivo e calcular o hash

```bash
# 1. Exporta a versao exata da tag, sem historico nem arquivos ignorados
git archive --format=zip --prefix=kronus-1.0.0/ inpi-v1.0.0 \
    -o kronus-inpi-1.0.0.zip

# 2. Calcula o resumo digital (o INPI recomenda SHA-512 ou mais recente)
sha512sum kronus-inpi-1.0.0.zip | tee kronus-inpi-1.0.0.sha512
```

No Windows/PowerShell:

```powershell
Get-FileHash .\kronus-inpi-1.0.0.zip -Algorithm SHA512 |
    Format-List Algorithm, Hash
```

O hash é o que vai no formulário. **Confira caractere por caractere** —
um dígito trocado produz um certificado que não corresponde ao seu
arquivo, e o erro só aparece anos depois, numa perícia.

### 4.4 Guarda do arquivo (obrigação sua, para sempre)

Guarde **o .zip exato** — não o repositório, não uma cópia
"equivalente". Um byte diferente muda o hash.

- Três cópias, em dois meios distintos, uma fora do escritório.
- Uma delas no backup da VPS já existente.
- Registre no controle interno: versão, tag, data, SHA-512, número do
  processo INPI.

Recomputar o hash uma vez por ano e conferir com o certificado é um
hábito barato que detecta corrupção silenciosa de mídia antes que seja
tarde.

---

## 5. Passo a passo do peticionamento

**Serviço: código 730** — Registro de programa de computador.

| # | Passo | Onde |
|---|---|---|
| 1 | Fazer login no **e-INPI** com o cadastro da KS TEC | e-INPI |
| 2 | Emitir a **GRU** com o código de serviço **730** | e-INPI |
| 3 | Pagar a GRU e **guardar o número** | banco |
| 4 | Baixar o formulário de **Declaração de Veracidade (DV)** — o link fica na própria GRU e também no formulário eletrônico | e-INPI |
| 5 | **Assinar a DV digitalmente** com o certificado ICP-Brasil | localmente |
| 6 | Acessar o **e-Software (e-RPC)** e preencher o formulário | e-Software |
| 7 | Inserir o **hash SHA-512** no campo próprio | e-Software |
| 8 | Anexar a **DV assinada** (e a procuração eletrônica, se houver representante) | e-Software |
| 9 | Enviar o pedido | e-Software |
| 10 | Acompanhar a publicação na **RPI** (semanal) e pelo **BuscaWeb**, com aviso por e-mail | RPI / BuscaWeb |

**Prazos.** A publicação ocorre em até 10 dias contados do pedido, e o
processo é automatizado — o certificado sai em cerca de **7 dias úteis**
quando não há exigência. Se houver exigência, ela é publicada na RPI e o
prazo para cumprir corre da publicação: **acompanhe a RPI toda semana até
o certificado sair**, porque perder uma exigência arquiva o pedido.

**Custo.** Consulte a *Tabela de Retribuições* vigente do INPI para o
serviço 730. Existe valor reduzido para MEI, ME, EPP, pessoa física,
ICTs e entidades sem fins lucrativos — se a KS TEC se enquadrar, marque
isso na emissão da GRU, porque não dá para corrigir depois sem refazer.

**Sigilo.** Como só o hash é declarado, o código não é publicado. O
registro é válido por 50 anos e vale nos 176 países da Convenção de
Berna.

### Depois do certificado

1. Preencher `REGISTRO_INPI` no `.env` da VPS.
2. Reiniciar os serviços (`kronus-deploy` ou `systemctl restart kronus`).
3. **Reemitir o AFD de teste e conferir** que o número aparece no
   cabeçalho, no nome do arquivo e no comprovante.
4. Emitir o Atestado Técnico (seção 6) para cada cliente ativo.

> **Novas versões.** O registro cobre a versão registrada. Alteração que
> mude substancialmente o programa pede novo registro. Correção de bug
> não. Na dúvida, o critério prático: se você mudaria o número de versão
> antes do primeiro ponto, registre de novo.

---

## 6. O Atestado Técnico e Termo de Responsabilidade

Documento **distinto** do registro no INPI, exigido pelo **art. 89**. É a
KS TEC declarando formalmente que o Kronus cumpre a Portaria.

### 6.1 Regras que invalidam o documento se descumpridas

| Regra | Fonte |
|---|---|
| Emitido conforme o **modelo do Anexo VII** | art. 89, § 1º |
| **Documento eletrônico** com **assinatura eletrônica qualificada** (Lei 14.063/2020, art. 4º, III), **pertencente exclusivamente à pessoa física** | art. 89, § 2º |
| Formato **PDF** | art. 89, § 3º |
| Assinado pelo **responsável técnico** *e* pelo **responsável legal** | art. 89, caput |
| **Um por empresa usuária** — traz os dados do destinatário | Anexo VII |
| Redigido em **português** | art. 92, § único |
| O empregador **guarda** e apresenta à Inspeção do Trabalho | art. 89, §§ 3º e 4º |

Dois pontos são fáceis de errar:

1. **"pertencente exclusivamente à pessoa física"** — não vale assinar
   com o e-CNPJ da KS TEC. Tem que ser e-CPF do responsável técnico e
   e-CPF do responsável legal. Se for a mesma pessoa nos dois papéis,
   ela assina nas duas qualidades.
2. **Não é um documento genérico.** O Anexo VII exige a razão social e o
   CNPJ da empresa destinatária. Um atestado "ao portador" não cumpre o
   art. 89 — **gere um por cliente**, no momento da contratação.

### 6.2 Conteúdo exato (modelo do Anexo VII)

Cabeçalho fixo:

> Na qualidade de responsável técnico e de responsável legal da empresa
> **(razão social)**, **(CNPJ nº)**, os signatários abaixo, em atenção ao
> art. 18 da Portaria SEPRT/ME nº 671/2021, atestam e declaram que o
> equipamento e/ou programa identificados abaixo estão em conformidade
> com a Portaria SEPRT nº 671/2021.

Campos de identificação, com o valor do Kronus:

| Campo do Anexo VII | Valor para o Kronus |
|---|---|
| Tipo do REP/PTRP | `REP-P` |
| Marca Equipamento | `N/A` |
| Modelo Equipamento | `N/A` |
| Certificado de conformidade | `N/A` *(só REP-C)* |
| Número de fabricação | `N/A` *(só REP-C)* |
| **Número de registro no INPI** | **o número do certificado** |
| Identificador do Programa | `Kronus` |
| Versão do Programa | a versão registrada — ex. `1.0.0` |
| Assinatura Eletrônica | `N/A` *(somente REP-C)* |
| Chave pública | `N/A` *(somente REP-C)* |
| Algoritmo de criptografia assimétrica | `N/A` *(somente REP-C)* |
| Algoritmo de hash | `N/A` *(somente REP-C)* |

> Os quatro últimos campos são exigidos pelo art. 89, § 5º **apenas para
> o REP-C**. Como o Kronus é REP-P, vão como `N/A`. Preenchê-los com o
> SHA-256 da cadeia de integridade seria declarar algo que a norma não
> pediu, num documento com responsabilidade criminal — não faça.

Declaração de ciência, texto fixo:

> Declaramos ainda, que estamos cientes das consequências legais, cíveis
> e criminais, quanto à falsa declaração, falso atestado e falsidade
> ideológica. Reiteramos ao usuário que este documento deve ficar
> disponível para pronta apresentação para a Inspeção do Trabalho.

Destinatário e assinaturas:

```
Empresa/Pessoa Destinatária:
Razão Social: (razão social da empresa cliente)
CNPJ/CPF:     (CNPJ da empresa cliente)

___________________________________________
Nome e CPF do Responsável Legal

___________________________________________
Nome e CPF do Responsável Técnico
```

### 6.3 Sequência correta

O Atestado só pode ser emitido **depois** do certificado do INPI — sem o
número, o campo obrigatório fica vazio.

```
registro no INPI  →  numero no .env  →  Atestado por cliente  →  venda
```

### 6.4 Sugestão de automação (não implementada)

Vale gerar o Atestado a partir do cadastro do cliente no próprio Kronus,
com os dados do destinatário preenchidos e a versão do programa lida do
sistema — o PDF sai pronto para as duas assinaturas qualificadas. Isso
elimina a classe de erro mais provável: CNPJ do destinatário digitado
errado num documento com responsabilidade criminal.

---

## 7. Ordem de execução

- [ ] Resolver titularidade do código (cessão, se houver colaborador externo)
- [ ] Obter/confirmar certificado ICP-Brasil (e-CNPJ da KS TEC + e-CPF dos signatários)
- [ ] Criar cadastro no e-INPI
- [ ] Criar a tag `inpi-v1.0.0` e gerar o `.zip`
- [ ] Calcular o SHA-512 e arquivar as três cópias
- [ ] Emitir e pagar a GRU 730 (verificar direito ao valor reduzido)
- [ ] Assinar a Declaração de Veracidade
- [ ] Peticionar no e-Software com o hash e a DV
- [ ] Acompanhar a RPI semanalmente até o certificado
- [ ] Preencher `REGISTRO_INPI` no `.env` e reiniciar os serviços
- [ ] Conferir o número no AFD (cabeçalho + nome do arquivo), no AEJ e no comprovante
- [ ] Emitir o Atestado Técnico para cada cliente, com as duas assinaturas qualificadas

---

## Fontes

- [INPI — Guia Básico de Programa de Computador](https://www.gov.br/inpi/pt-br/servicos/programas-de-computador/guia-basico)
- [INPI — Guia completo de programa de computador](https://www.gov.br/inpi/pt-br/servicos/programas-de-computador/guia-completo-de-programa-de-computador)
- [INPI — Manual do Usuário e-Software](https://www.gov.br/inpi/pt-br/servicos/programas-de-computador/arquivos/manual/manual-e-software-2022.pdf)
- [INPI — Perguntas frequentes: Programas de Computador](https://www.gov.br/inpi/pt-br/acesso-a-informacao/perguntas-frequentes/programas-de-computador)
- Portaria MTP nº 671, de 8 de novembro de 2021 — arts. 78, 79, 89, 91, 92; Anexos V, VI, VII, IX
