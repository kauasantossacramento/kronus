# Kronus

> **O tempo sob controle.**
> Plataforma SaaS multi-tenant de ponto eletrônico digital com reconhecimento facial.
> REP-P em conformidade com a **Portaria 671/2021 do MTP**.

**Domínio:** [kronus.online](https://kronus.online)
**Desenvolvido por:** KS TEC Soluções de Tecnologia Ltda — CNPJ 62.501.281/0001-13

---

## Estado do desenvolvimento

O projeto é construído em 7 fases, definidas na Seção 11 do
[plano de desenvolvimento](KRONUS_PLANO_DESENVOLVIMENTO%20(1).md).
O andamento detalhado fica em [`SESSION_INDEX.md`](SESSION_INDEX.md).

| Fase | Escopo | Status |
|---|---|---|
| 1 — Fundação | Setup, modelagem, autenticação, multi-tenancy, CRUDs, templates base | ✅ Concluída |
| 2 — Core de Ponto | Registro web, cálculo de horas, banco de horas, espelho, NSR e hash | ✅ Concluída |
| 3 — Facial e Totem | DeepFace/ArcFace, face-api.js, estados do totem, offline | ✅ Concluída |
| 4 — Admin RH | Dashboard, atestados, justificativas, relatórios, AFD/AEJ | ✅ Concluída ¹ |
| 5 — Master e API | Totens, comodato, planos, API REST pública, webhooks | 🔄 Parcial |
| 6 — Landing e Polimento | Landing completa, notificações, import/export, deploy | 🔄 Parcial |
| 7 — Pós-lançamento | Liveness, anti-fake GPS, portal do contador, eSocial | 🔄 Parcial |

> **¹ AFD e AEJ:** a estrutura segue a Portaria 671/2021 e é validada por 39
> testes (NSR contínuo, trailer consistente, tamanho fixo de linha), mas as
> **larguras dos campos** ainda precisam ser conferidas contra o Anexo oficial.
> Ver `apps/relatorios/afd.py` e o [relatório 004](SESSION_LOG_2026-08-27_004.md).
>
> O motor facial foi validado contra o LFW. A medição corrigiu dois parâmetros
> do plano: threshold **0,60** (0,68 gerava falsos positivos) e detector
> **MTCNN** (RetinaFace leva 9,9 s em CPU). Ver o
> [relatório 003](SESSION_LOG_2026-08-27_003.md).

---

## Stack

**Backend:** Python 3.12+ · Django 5.x · DRF · Celery · Redis · PostgreSQL 16 · Channels
**Frontend:** Django Templates · Tailwind CSS · Alpine.js · HTMX
**Facial:** DeepFace (ArcFace) + RetinaFace no servidor; face-api.js (TinyFaceDetector) no totem
**Infra:** Docker · Nginx · Gunicorn + Daphne · WhiteNoise · MinIO/S3

---

## Como rodar

### Opção A — Docker (recomendada)

```bash
cp .env.example .env      # ajuste SECRET_KEY e DB_PASSWORD
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python scripts/seed_data.py
```

### Opção B — Windows nativo (Seção 16.3 do plano)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-base.txt      # sem a stack de visão computacional
copy .env.example .env

# Bootstrap sem Docker: no .env, use DB_ENGINE=sqlite e USE_REDIS=False
python manage.py migrate
python scripts/seed_data.py
python manage.py runserver
```

> **Produção é sempre PostgreSQL + Redis.** O modo SQLite/LocMem existe apenas
> para levantar o ambiente local sem Docker.

Para o reconhecimento facial (Fase 3): `pip install -r requirements.txt`.

### Tailwind

```bash
npm install
npm run watch:css     # gera static/css/main.css
```

Em `DEBUG=True` o sistema usa o Tailwind Play CDN e dispensa essa etapa.

---

## Acessos do seed

| Papel | Login | Senha |
|---|---|---|
| Master (KS TEC) | `admin@kstec.online` | `kronus2026` |
| Admin do cliente | `marina@grupoaurora.com.br` | `kronus2026` |
| Admin RH | `rh.supermercados@grupoaurora.com.br` | `kronus2026` |

---

## Mapa de rotas

| Rota | Descrição |
|---|---|
| `/` | Landing page pública |
| `/accounts/login/` | Login unificado (CPF ou e-mail) |
| `/accounts/colaborador/` | Login mobile-first do colaborador |
| `/app/` | Roteador por papel após o login |
| `/rh/` | Painel do Admin RH |
| `/master/` | Painel Master (KS TEC) |
| `/ponto/registrar/` | Registro de ponto web (geolocalização, comprovante) |
| `/ponto/meus-pontos/` | Histórico mensal do colaborador |
| `/rh/registros/` | Marcações da empresa, com ajuste manual |
| `/rh/banco-horas/` | Painel de saldos |
| `/rh/espelhos/` | Emissão de espelho de ponto |
| `/rh/escalas/` | Escalas de trabalho |
| `/rh/atestados/` | Atestados com aprovação |
| `/rh/justificativas/` | Justificativas e abonos |
| `/rh/fechamento/` | Fechamento mensal |
| `/rh/configuracoes/` | Jornada, personalização, notificações, API |
| `/relatorios/fiscais/` | **AFD e AEJ** (Portaria 671) |
| `/relatorios/gerenciais/` | Horas extras, atrasos, faltas |
| `/relatorios/contador/` | Portal do contador (somente leitura) |
| `/ponto/espelhos/` | Espelhos e assinatura eletrônica |
| `/totem/<token>/` | Interface de quiosque do totem |
| `/totem/<token>/diagnostico/` | Página técnica do equipamento (suporte) |
| `/facial/cadastro/<id>/` | Cadastro biométrico com consentimento LGPD |
| `/api/v1/totem/recognize/` | Reconhecimento facial e registro de ponto |
| `/api/v1/totem/punch-cpf/` | Fallback por CPF + data de nascimento |
| `/api/v1/docs/` | Documentação Swagger da API |
| `/django-admin/` | Admin do Django (uso interno) |

---

## Testes

```bash
python manage.py test tests --settings=config.settings.test
```

354 testes cobrindo utilitários de domínio, autenticação, isolamento
multi-tenant, CRUD do RH, NSR e hash encadeado, cálculo de jornada,
banco de horas, reconhecimento facial, endpoints do totem, arquivos
fiscais (AFD/AEJ) e o fluxo de aprovação e fechamento.

## Testar o totem em um tablet

```bash
python manage.py intranet
```

Detecta o IP da máquina, gera um certificado autoassinado e sobe o servidor
em HTTPS — necessário porque a câmera (`getUserMedia`) só funciona em
contexto seguro. O comando imprime a URL de cada totem cadastrado.

## Reconhecimento facial

```bash
python manage.py facial_check            # diagnóstico do motor
python manage.py facial_check --baixar   # pré-carrega os pesos do ArcFace
python manage.py facial_check --testar   # mede o tempo de um embedding
```

O motor é selecionado por `FACE_PROVIDER` (`auto`, `deepface`,
`deterministico`, `indisponivel`). Sem a stack instalada ou sem os pesos,
o sistema recusa o reconhecimento com mensagem acionável — e o totem
continua registrando ponto pelo fallback de CPF.

## Criando um usuário Master

```bash
python manage.py createsuperuser
```

O identificador de acesso pode ser um **e-mail** ou um **CPF** (aceita máscara).
O comando valida no próprio prompt e cria o usuário já com o papel Master.

---

## Estrutura

```
config/          settings (base/dev/prod/test), urls, asgi, wsgi, celery
apps/core/       models base, mixins, middleware de tenant, permissões, utils
apps/accounts/   CustomUser, backends CPF/e-mail, login e recuperação
apps/master/     painel KS TEC: clientes, empresas, planos, logs
apps/clientes/   Cliente, Empresa, ConfiguracaoEmpresa
apps/rh/         Colaborador, Departamento, Cargo, Atestado, Justificativa
apps/ponto/      RegistroPonto, BancoHoras, EscalaTrabalho, FechamentoMensal
apps/facial/     FaceRegistro, TentativaReconhecimento
apps/totem/      Totem, GrupoTotem, EventoTotem, interface de quiosque
apps/api/        APIKey, telemetria e URLs da API v1
apps/relatorios/ espelho de ponto, AFD, AEJ, exportações
apps/notificacoes/ Notificacao, Webhook, Lead
apps/landing/    landing page pública
```

---

## Conformidade

- **Portaria 671/2021 (REP-P):** NSR sequencial por empresa, hash SHA-256 encadeado,
  registros imutáveis, AFD e AEJ, comprovante e espelho de ponto.
- **LGPD:** embeddings faciais não reversíveis, consentimento explícito, direito de
  exclusão e expurgo automático 30 dias após o desligamento.
- **CLT:** tolerância de 5 min (Art. 58 §1º), intervalo intrajornada (Art. 71),
  adicional noturno com hora reduzida de 52min30s (Art. 73).

---

*© 2026 KS TEC Soluções de Tecnologia Ltda.*
