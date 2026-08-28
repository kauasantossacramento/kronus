# Índice de Sessões — Kronus (kronus.online)

Registro acumulativo das sessões de desenvolvimento, conforme o
**Protocolo de Relatório de Sessão** (Seção 17 do plano).
Cada sessão gera um arquivo novo; nenhum relatório é sobrescrito.

---

## Sessões

| # | Data | Fase | Foco | Relatório |
|---|---|---|---|---|
| 001 | 2026-08-27 | Fase 1 — Fundação | Setup, modelagem (21 models), autenticação CPF/e-mail, multi-tenancy, CRUDs Master e RH, design system e templates base | [SESSION_LOG_2026-08-27_001.md](SESSION_LOG_2026-08-27_001.md) |
| 002 | 2026-08-27 | Fase 2 — Core de Ponto | NSR e hash encadeado, cálculo de jornada e banco de horas, escalas, comprovante e espelho, ajustes manuais; marca e ícones em SVG; correção do `createsuperuser` | [SESSION_LOG_2026-08-27_002.md](SESSION_LOG_2026-08-27_002.md) |
| 003 | 2026-08-27 | Fase 3 — Facial e Totem | Arquitetura de provedores de reconhecimento, cadastro facial com consentimento LGPD, 4 endpoints do totem, máquina de estados de 5 telas, Service Worker, WebSockets e monitoramento de equipamento | [SESSION_LOG_2026-08-27_003.md](SESSION_LOG_2026-08-27_003.md) |
| 004 | 2026-08-27 | Fase 4 — Admin RH | AFD e AEJ com layout declarativo, atestados e justificativas com reprocessamento, fechamento mensal e assinatura eletrônica, relatórios gerenciais, portal do contador, configurações; intranet HTTPS e captura de foto pelo sistema | [SESSION_LOG_2026-08-27_004.md](SESSION_LOG_2026-08-27_004.md) |
| 005 | 2026-08-27 | Fase 5 — Master e API | API REST pública (7 recursos + relatórios fiscais), rate limiting por plano, webhooks com HMAC e retentativa, gestão de totens e comodato, grupos de totens; **correção de defeito de conformidade no hash de integridade** | [SESSION_LOG_2026-08-27_005.md](SESSION_LOG_2026-08-27_005.md) |
| 006 | 2026-08-27 | Fase 6 — Polimento | Exportação para folha (3 layouts), importação de colaboradores com conferência prévia, guia público da API, equipamentos na visão do RH; **cabeçalhos de segurança que estavam configurados e inertes**, Argon2 e guardas de arranque em produção | [SESSION_LOG_2026-08-27_006.md](SESSION_LOG_2026-08-27_006.md) |

---

## Status consolidado das fases

| Fase | Escopo (Seção 11 do plano) | Status | Progresso | Última atualização |
|---|---|---|---|---|
| Fase 1 | Fundação | ✅ Concluída | 100% | Sessão 001 |
| Fase 2 | Core de Ponto | ✅ Concluída | 100% | Sessão 002 |
| Fase 3 | Reconhecimento Facial e Totem | ✅ Concluída e validada | 95% | Sessão 003 |
| Fase 4 | Admin RH Completo | ✅ Concluída | 95% | Sessão 004 |
| Fase 5 | Painel Master e API | ✅ Concluída | 100% | Sessão 006 |
| Fase 6 | Landing Page e Polimento | ✅ Concluída¹ | 95% | Sessão 006 |
| Fase 7 | Melhorias Pós-Lançamento | 🔄 Parcial | 40% | Sessão 006 |

> ¹ Sete dos oito itens da Fase 6 entregues. **Deploy em produção não foi
> executado** — não há servidor acessível desta máquina. A configuração está
> validada (`check --deploy` sem issues) e a produção passou a recusar o
> arranque com `SECRET_KEY` de desenvolvimento.

> Os percentuais das fases ainda abertas refletem a base já construída
> (modelagem, permissões, templates) e itens adiantados fora de ordem —
> a detecção de GPS fictício, por exemplo, era da Fase 7 e foi entregue
> junto com o geofencing. Detalhamento nas notas de rodapé de cada relatório.

---

## Cobertura de testes

| Sessão | Testes acumulados | Novos na sessão |
|---|---|---|
| 001 | 72 | 72 |
| 002 | 163 | 91 |
| 003 | 274 | 111 |
| 004 | 354 | 80 |
| 005 | 441 | 87 |
| 006 | 498 | 57 |

---

## Próxima sessão

**Fase 7 — Melhorias Pós-Lançamento.** Pendências priorizadas no
[relatório 006](SESSION_LOG_2026-08-27_006.md).

Antes de qualquer funcionalidade nova, os **dois débitos de conformidade**
valem mais: as larguras do AFD/AEJ contra o Anexo oficial, e os layouts de
folha contra uma importação em homologação. São os únicos itens abertos que
podem gerar problema com fiscalização ou pagamento errado.

Depois deles, o item de maior valor da Fase 7 é o **liveness detection**: hoje
o totem aceita uma foto de celular apontada para a câmera — a vulnerabilidade
conhecida mais séria do produto, documentada desde a Fase 3.

**Débito de conformidade que atravessa a Fase 4:** o AFD e o AEJ geram,
validam e passam em 39 testes, mas as **larguras dos campos** não puderam
ser conferidas contra o Anexo oficial da Portaria 671/2021 — o layout está
publicado em imagens e páginas fechadas. A estrutura está declarada em
`apps/relatorios/afd.py` para que a correção seja pontual, a ressalva
aparece na tela de geração e no header `X-Kronus-Layout` da API.
**Conferir com o contador antes da primeira fiscalização.**

**Achado da sessão 005, já corrigido:** o hash de integridade era calculado
sobre a representação do horário, não sobre o instante — registros gravados
em horário local (totem e ponto web) reprovavam na verificação exigida pela
Portaria 671. Corrigido em `gerar_hash_registro`, com 4 testes de regressão
e o comando `manage.py recalcular_cadeia` para reparar bases afetadas.

**Achado da sessão 006:** o `SecurityHeadersMiddleware` nunca esteve em
`MIDDLEWARE`. O `production.py` declarava a CSP completa e apontava para ele,
mas o middleware jamais rodou — configuração aplicada a lugar nenhum, que é
pior que ausência porque aparenta proteção. Ligado e coberto por testes.

---

## Como ler estes relatórios

Cada `SESSION_LOG_YYYY-MM-DD_NNN.md` segue o formato da Seção 17.2 do plano:
fase atual, o que foi feito, arquivos tocados, decisões técnicas com
justificativa, problemas e resoluções, testes realizados, pendências
priorizadas e status das fases.
