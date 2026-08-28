# Kronus — Plano Completo de Desenvolvimento

> **Plataforma de Ponto Eletrônico Digital com Reconhecimento Facial**
> **Domínio:** kronus.online
> Desenvolvido por **KS TEC Soluções de Tecnologia Ltda**
> Documento de referência para Claude Code — versão 1.1

---

## 1. VISÃO GERAL DO PROJETO

### 1.1 Nome do Produto
**Kronus** — Sistema de Registro Eletrônico de Ponto via Programa (REP-P)

**Origem do nome:** Kronos (Κρόνος) é o titã da mitologia grega associado ao tempo. A grafia "Kronus" é uma variação moderna, curta e memorável, que carrega a essência de controle e gestão do tempo — exatamente o propósito da plataforma.

**Domínio:** `kronus.online`

### 1.2 Tagline
*"O tempo sob controle."*

**Taglines alternativas para uso contextual:**
- Landing page hero: *"O tempo sob controle."*
- Meta description / SEO: *"Ponto eletrônico digital com reconhecimento facial. Conforme Portaria 671."*
- Totem idle screen (default): *"Seu tempo, registrado com precisão."*
- Rodapé: *"Kronus — Gestão inteligente de ponto eletrônico"*

### 1.3 Descrição
**Kronus** é uma plataforma SaaS multi-tenant de controle de ponto eletrônico digital em conformidade com a **Portaria 671/2021 do MTP**, classificada como **REP-P** (Registrador Eletrônico de Ponto via Programa). O sistema oferece registro de ponto via web (desktop/mobile), reconhecimento facial em totem físico, geolocalização, banco de horas, espelho de ponto com assinatura eletrônica, geração de AFD/AEJ e API REST para integração com sistemas externos.

### 1.4 Desenvolvedor
- **Empresa:** KS TEC Soluções de Tecnologia Ltda
- **CNPJ:** 62.501.281/0001-13
- **Site:** https://kstec.online
- **Logo KS TEC:** https://kstec.online/assets/ks-tec-logo.png
- **Localização:** Valença — BA, Brasil
- **Relação com o produto:** KS TEC é a empresa desenvolvedora. Kronus é o produto/marca comercial.

### 1.5 Arquitetura de Usuários (Multi-Tenant Hierárquico)

```
┌─────────────────────────────────────────────────────────┐
│                   MASTER (KS TEC)                       │
│  Administrador geral do software — vende o serviço      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌───────────────┐  ┌───────────────┐                   │
│  │  CLIENTE A    │  │  CLIENTE B    │  ...               │
│  │  (Assinatura) │  │  (Assinatura) │                   │
│  │               │  │               │                   │
│  │  ┌─────────┐  │  │  ┌─────────┐  │                   │
│  │  │Empresa 1│  │  │  │Empresa 1│  │                   │
│  │  │Empresa 2│  │  │  │Empresa 2│  │                   │
│  │  │   ...   │  │  │  │   ...   │  │                   │
│  │  └─────────┘  │  │  └─────────┘  │                   │
│  │               │  │               │                   │
│  │  Admin (RH)   │  │  Admin (RH)   │                   │
│  │  Colaboradores│  │  Colaboradores │                   │
│  └───────────────┘  └───────────────┘                   │
└─────────────────────────────────────────────────────────┘
```

**Papéis:**
- **Master:** KS TEC — gerencia clientes, assinaturas, equipamentos em comodato, suspensões
- **Cliente:** Empresa contratante do serviço — pode possuir múltiplas empresas vinculadas
- **Admin (RH):** Colaborador do RH do cliente — gerencia colaboradores, pontos, atestados, escalas, banco de horas
- **Colaborador:** Funcionário que registra ponto via web ou totem

---

## 2. STACK TECNOLÓGICA

### 2.1 Backend

| Componente | Tecnologia | Justificativa |
|---|---|---|
| Linguagem | **Python 3.12+** | Ecossistema robusto, bibliotecas de IA/ML |
| Framework Web | **Django 5.x** | Maturidade, ORM, admin, segurança, multi-tenant |
| API REST | **Django REST Framework (DRF) 3.15+** | Serializadores, autenticação token/JWT, throttling |
| Multi-Tenancy | **django-tenants** ou schema-based isolation | Isolamento de dados por cliente |
| Autenticação | **djangorestframework-simplejwt** | JWT para API; session para web |
| Task Queue | **Celery 5.x + Redis** | Jobs assíncronos (processamento facial, relatórios, emails) |
| Cache | **Redis 7.x** | Cache de sessões, rate-limiting, filas |
| Banco de Dados | **PostgreSQL 16+** | JSON fields, partitioning, full-text search |
| Storage | **MinIO** (self-hosted) ou **AWS S3** | Armazenamento de fotos faciais, atestados, logos |
| Reconhecimento Facial (Server) | **DeepFace** (wrapper com ArcFace backend) | 99.40% accuracy no LFW — superior à precisão humana (97.53%) |
| Detecção Facial (Server) | **RetinaFace** (via DeepFace) | Alta precisão mesmo com rostos pequenos ou parcialmente cobertos |
| Geração de PDF | **WeasyPrint** ou **ReportLab** | Espelho de ponto, comprovantes, AFD |
| Assinatura Digital | **python-pkcs11** + carimbo ICP-Brasil | Conformidade Portaria 671 |
| Geolocalização | **PostGIS** extension no PostgreSQL | Queries geoespaciais, geofencing |
| WebSockets | **Django Channels + Daphne** | Notificações real-time no totem e dashboard |

### 2.2 Frontend Web (Admin/Colaborador)

| Componente | Tecnologia | Justificativa |
|---|---|---|
| Linguagem | **HTML5, CSS3, JavaScript (ES6+)** | Universalidade |
| Framework CSS | **Tailwind CSS 3.x** | Utility-first, design system customizável, tree-shaking |
| Componentes UI | **Flowbite** (componentes Tailwind) | Modais, dropdowns, tabelas, formulários prontos |
| Ícones | **Heroicons** + **Lucide Icons** | Consistência com Tailwind |
| Gráficos | **Chart.js 4.x** ou **ApexCharts** | Dashboards de horas, relatórios visuais |
| Template Engine | **Django Templates (Jinja2-like)** | Renderização server-side, SEO da landing page |
| JS Interativo | **Alpine.js 3.x** | Reatividade leve sem SPA overhead |
| AJAX | **HTMX 2.x** | Partial page updates sem JS pesado |
| Tabelas | **DataTables** ou implementação custom com HTMX | Paginação, busca, ordenação |
| Notificações Toast | **Notyf** ou **Toastify** | Feedback visual leve |
| Date/Time Picker | **Flatpickr** | Leve, acessível, localizável (pt-BR) |

### 2.3 Frontend Totem (Reconhecimento Facial)

| Componente | Tecnologia | Justificativa |
|---|---|---|
| Detecção Facial (browser) | **face-api.js** (fork moderno: `modern-face-api`) | Detecção client-side, TinyFaceDetector ~190KB, roda em WebGL |
| Modelo de detecção | **TinyFaceDetector** | Otimizado para dispositivos de baixa performance |
| Modelo de landmarks | **face_landmark_68_tiny_model** (80KB) | Extremamente leve |
| Câmera | **getUserMedia API** | Acesso nativo à câmera do tablet |
| Comunicação | **Fetch API + WebSocket** | Envio de frame para server, recebimento de resultado |
| Offline Detection | **Navigator.onLine + Service Worker** | Detecção de queda de conexão |
| Cache Offline | **Service Worker + Cache API** | Cacheamento de assets estáticos para funcionar offline |
| Animações | **CSS Animations** (sem JS pesado) | Performance no Positivo Tab 7 |

**Fluxo de reconhecimento no totem:**
1. `face-api.js` (TinyFaceDetector) detecta presença de rosto no client-side
2. Captura frame da câmera (canvas → blob JPEG comprimido, ~50KB)
3. Envia frame via POST para endpoint Django `/api/v1/totem/recognize/`
4. Server usa DeepFace com ArcFace para comparar embedding contra banco de faces do grupo de equipamentos
5. Retorna resultado: identificado (nome, CPF mascarado) ou não-identificado (solicita CPF + nascimento)

### 2.4 Landing Page

| Componente | Tecnologia |
|---|---|
| Framework | **Django Templates + Tailwind CSS** |
| Animações | **AOS.js** (Animate on Scroll) — leve |
| Formulário de contato | **HTMX** + endpoint Django |
| SEO | **Meta tags, Open Graph, Schema.org** |

### 2.5 DevOps & Infraestrutura

| Componente | Tecnologia |
|---|---|
| Containerização | **Docker + Docker Compose** |
| Web Server | **Nginx** (proxy reverso + static files) |
| ASGI Server | **Daphne** (WebSockets) + **Gunicorn** (HTTP) |
| CI/CD | **GitHub Actions** |
| Monitoramento | **Sentry** (erros) + **Prometheus/Grafana** (métricas) |
| SSL | **Let's Encrypt / Certbot** |
| Hospedagem | **VPS Linux** (recomendado: 4 vCPU, 8GB RAM, SSD) |

---

## 3. IDENTIDADE VISUAL — KRONUS

### 3.1 Conceito Visual

A identidade do Kronus é construída sobre três pilares derivados da mitologia de Kronos (titã do tempo):

1. **Autoridade:** tons escuros e profundos (midnight blue, navy) — transmitem confiança e solidez
2. **Precisão:** dourado/âmbar como acento — remete à Era de Ouro de Kronos e ao valor do tempo
3. **Modernidade:** linhas limpas, tipografia geométrica, espaço generoso — software contemporâneo, não museu

**Símbolo conceitual do Kronus:**
- Um **ampulheta estilizada** ou **"K" com ponteiro de relógio** integrado — pode ser usado como favicon e ícone de app
- A ampulheta remete a Kronos (tempo) e é universalmente reconhecível
- Versões: cor (sobre claro), branco (sobre escuro), ícone puro (favicon/app)

### 3.2 Paleta de Cores (Design System)

```css
:root {
  /* ══════════════════════════════════════════════════
     KRONUS DESIGN SYSTEM — Cores
     Inspiração: Kronos (titã do tempo), noite cósmica,
     Era de Ouro, precisão temporal
     ══════════════════════════════════════════════════ */

  /* ── Primárias: Midnight Blue (autoridade, profundidade, tempo) ── */
  --kronus-primary-50:  #EFF6FF;   /* Backgrounds sutis, hover leve */
  --kronus-primary-100: #DBEAFE;   /* Backgrounds de cards secundários */
  --kronus-primary-200: #BFDBFE;   /* Borders, dividers */
  --kronus-primary-300: #93C5FD;   /* Tags, badges informativos */
  --kronus-primary-400: #60A5FA;   /* Links secundários */
  --kronus-primary-500: #1E3A5F;   /* COR PRINCIPAL — Midnight Blue */
  --kronus-primary-600: #172E4A;   /* Botões primários, headers, sidebar */
  --kronus-primary-700: #0F2035;   /* Hover de botões, backgrounds escuros */
  --kronus-primary-800: #0A1628;   /* Navbar, elementos premium */
  --kronus-primary-900: #060E1A;   /* Backgrounds ultra-escuros */

  /* ── Acento: Âmbar Dourado (Era de Ouro, destaque, premium) ── */
  --kronus-gold-50:     #FFFBEB;   /* Backgrounds de alertas suaves */
  --kronus-gold-100:    #FEF3C7;   /* Badges, highlights */
  --kronus-gold-200:    #FDE68A;   /* Bordas de destaque */
  --kronus-gold-300:    #FCD34D;   /* Ícones de destaque */
  --kronus-gold-400:    #FBBF24;   /* CTAs secundários, estrelas, badges premium */
  --kronus-gold-500:    #D4A017;   /* COR DE ACENTO PRINCIPAL — Ouro */
  --kronus-gold-600:    #B8860B;   /* Hover de elementos dourados */
  --kronus-gold-700:    #92690A;   /* Texto dourado sobre fundo escuro */

  /* ── Status / Feedback ── */
  --kronus-success:     #10B981;   /* Emerald — ponto OK, online, sucesso */
  --kronus-warning:     #F59E0B;   /* Amber — alerta, banco negativo */
  --kronus-danger:      #EF4444;   /* Vermelho — erro, suspensão, falta */
  --kronus-info:        #3B82F6;   /* Azul — informativo, notificação */

  /* ── Neutros ── */
  --kronus-gray-50:     #F8FAFC;   /* Background geral (light mode) */
  --kronus-gray-100:    #F1F5F9;   /* Cards, surfaces */
  --kronus-gray-200:    #E2E8F0;   /* Borders, separadores */
  --kronus-gray-300:    #CBD5E1;   /* Inputs disabled, placeholders */
  --kronus-gray-400:    #94A3B8;   /* Texto terciário */
  --kronus-gray-500:    #64748B;   /* Texto secundário */
  --kronus-gray-600:    #475569;   /* Texto de corpo */
  --kronus-gray-700:    #334155;   /* Texto enfatizado */
  --kronus-gray-800:    #1E293B;   /* Títulos */
  --kronus-gray-900:    #0F172A;   /* Texto principal (headings) */

  /* ── Totem (Dark Theme exclusivo) ── */
  --totem-bg:           #060E1A;   /* Fundo ultra-escuro (quase preto-azulado) */
  --totem-surface:      #0F2035;   /* Cards, áreas elevadas */
  --totem-text:         #F8FAFC;   /* Texto claro principal */
  --totem-text-muted:   #94A3B8;   /* Texto secundário */
  --totem-glow:         #D4A017;   /* Glow dourado ao detectar rosto */
  --totem-glow-idle:    #1E3A5F;   /* Glow azul sutil no idle */
  --totem-success:      #10B981;   /* Verde sucesso */
  --totem-success-glow: #065F46;   /* Glow verde no sucesso */
  --totem-camera-border:#1E3A5F;   /* Borda do frame da câmera */
  --totem-camera-bg:    #0A1628;   /* Fundo atrás da câmera */
  --totem-gold-accent:  #FBBF24;   /* Detalhes dourados (ponteiro, ícones) */
}
```

**Regra de uso das cores:**
- **Midnight Blue** (`--kronus-primary-500` a `700`): sidebar, headers, navbar, botões primários, backgrounds de seções
- **Dourado** (`--kronus-gold-400` a `600`): CTAs secundários, ícones de destaque, badges "premium", separadores decorativos, glow do totem, hover especiais
- **Neutros com tom azulado** (Slate): todo o restante da interface — o tom frio dos neutros harmoniza com o midnight blue
- **NUNCA usar dourado para texto longo** — apenas acentos, ícones, badges e micro-interações
- **Totem:** 100% dark theme — midnight blue profundo com acentos dourados

### 3.3 Tipografia

| Uso | Fonte | Peso | Fallback |
|---|---|---|---|
| Logo "KRONUS" | **Outfit** | 700 (Bold) | `system-ui, sans-serif` |
| Títulos (h1-h3) | **Outfit** | 600, 700 | `system-ui, sans-serif` |
| Corpo de texto | **Inter** | 400, 500 | `system-ui, sans-serif` |
| Mono (CPF, horários, relógio) | **JetBrains Mono** | 400, 500 | `ui-monospace, monospace` |
| Totem — nome do colaborador | **Outfit** | 700 | `sans-serif` |
| Totem — relógio digital | **JetBrains Mono** | 700 | `monospace` |
| Tagline | **Inter** | 300 (Light) | `sans-serif` |

**Por que Outfit?** É uma fonte geométrica moderna (Google Fonts, gratuita), com personalidade forte nas letras K, R, O — perfeita para a marca "KRONUS". Ela é visualmente distinta sem ser extravagante, transmitindo tecnologia e autoridade. O "K" da Outfit tem ângulos afiados que remetem a ponteiros de relógio.

### 3.4 Logo do Kronus

**Composição da marca:**
```
┌──────────────────────────────────────┐
│                                      │
│    ⏳  KRONUS                         │  ← Ícone (ampulheta/K) + wordmark
│                                      │
│    Variações:                        │
│    1. Horizontal: ícone + "KRONUS"   │
│    2. Stacked: ícone em cima         │
│    3. Ícone solo (favicon, app)      │
│    4. Wordmark solo (contextos       │
│       onde o ícone é redundante)     │
│                                      │
│    Cores de aplicação:               │
│    • Midnight Blue sobre fundo claro │
│    • Branco sobre fundo escuro       │
│    • Dourado sobre midnight blue     │
│      (versão premium/especial)       │
│                                      │
└──────────────────────────────────────┘
```

**CSS para renderizar o wordmark no código:**
```css
.kronus-logo-text {
  font-family: 'Outfit', sans-serif;
  font-weight: 700;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--kronus-primary-500);
}
.kronus-logo-text.light {
  color: #FFFFFF;
}
.kronus-logo-text.gold {
  color: var(--kronus-gold-500);
}
```

### 3.5 Logos no Sistema

**Logo Kronus:**
- Login, topo da sidebar, landing page hero, totem (canto inferior), comprovantes PDF
- Versão midnight blue (fundo claro) e versão branca (fundo escuro)
- No totem: wordmark "KRONUS" em branco, opacidade 70%, canto inferior esquerdo

**Logo KS TEC (desenvolvedora):**
- **URL:** `https://kstec.online/assets/ks-tec-logo.png`
- **Versão branca (CSS):** `filter: brightness(0) invert(1);`
- **Onde aparece:**
  - Rodapé de todas as telas: `"Desenvolvido por"` + logo KS TEC (versão pequena, 16-20px height)
  - Tela offline do totem (junto com logo Kronus)
  - Landing page: rodapé `"Uma solução KS TEC"`
  - Espelho de ponto PDF: rodapé discreto
- **Regra:** a logo KS TEC é sempre **menor e secundária** em relação à logo Kronus — é a assinatura do desenvolvedor, não a marca principal

### 3.6 Personalização por Cliente (White-Label Parcial)

O admin do cliente poderá configurar:
- **Logo da empresa:** upload (exibida no totem, interface do colaborador, espelho de ponto)
- **Cor primária:** hex — aplicada via CSS custom properties na interface do colaborador e totem (substitui `--kronus-primary-500/600`)
- **Cor secundária:** hex — complementar (substitui `--kronus-gold-500`)
- **Imagem de tela cheia do totem (idle screen):** upload de imagem vertical (proporção 9:16 ou 10:16 para tablets 7")
- **Mensagem de boas-vindas do totem:** texto customizável (default: "Registre seu ponto")

**Elementos NÃO customizáveis** (sempre presentes):
- Marca "Kronus" no login e na sidebar (versão small)
- Rodapé "Desenvolvido por KS TEC" + logo KS TEC em todas as telas
- Wordmark "KRONUS" no canto inferior do totem

---

## 4. MODELAGEM DO BANCO DE DADOS

### 4.1 Diagrama Entidade-Relacionamento (principais entidades)

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────────┐
│   Plano       │ 1───N │     Cliente      │ 1───N │     Empresa      │
│──────────────│       │──────────────────│       │──────────────────│
│ id            │       │ id               │       │ id               │
│ nome          │       │ razao_social     │       │ razao_social     │
│ max_empresas  │       │ cnpj             │       │ cnpj             │
│ max_colab     │       │ plano_id (FK)    │       │ cliente_id (FK)  │
│ max_totems    │       │ ativo            │       │ logo             │
│ preco_mensal  │       │ suspenso         │       │ cor_primaria     │
│ tem_api       │       │ data_cadastro    │       │ cor_secundaria   │
│ tem_geofencing│       │ ultimo_acesso    │       │ idle_screen_img  │
│ tem_totem     │       │ api_key          │       │ msg_boas_vindas  │
│ tem_offline   │       │ api_key_ativa    │       │ fuso_horario     │
└──────────────┘       └──────────────────┘       │ modo_compensacao │
                                                   │ permite_ver_ponto│
                                                   │ geofencing_ativo │
                                                   │ geofencing_lat   │
                                                   │ geofencing_lng   │
                                                   │ geofencing_raio  │
                                                   └──────────────────┘
                                                            │
                              ┌──────────────────────────────┤
                              │                              │
                    ┌─────────┴────────┐          ┌──────────┴─────────┐
                    │   Departamento   │          │   EscalaTrabalho   │
                    │──────────────────│          │────────────────────│
                    │ id               │          │ id                 │
                    │ nome             │          │ nome               │
                    │ empresa_id (FK)  │          │ empresa_id (FK)    │
                    └──────────────────┘          │ tipo (fixa/flex/   │
                              │                   │       escala/12x36)│
                              │                   │ tolerancia_min     │
                    ┌─────────┴────────┐          │ jornada_config     │
                    │   Colaborador    │          │ (JSONField)        │
                    │──────────────────│          └────────────────────┘
                    │ id               │                    │
                    │ user (FK User)   │────────────────────┘
                    │ empresa_id (FK)  │
                    │ departamento (FK)│
                    │ cpf (unique)     │
                    │ nome_completo    │
                    │ data_nascimento  │
                    │ email            │
                    │ telefone         │
                    │ cargo            │
                    │ matricula        │
                    │ data_admissao    │
                    │ data_demissao    │
                    │ ativo            │
                    │ escala_id (FK)   │
                    │ foto_perfil      │
                    │ face_embedding   │ ← Vetor 128/512 dims (binary)
                    │ face_registrada  │ ← bool
                    │ pis_pasep        │
                    │ ctps             │
                    └──────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────┴──────┐ ┌─────┴──────┐ ┌──────┴──────────┐
    │ RegistroPonto  │ │  Atestado  │ │  FaceRegistro   │
    │────────────────│ │────────────│ │─────────────────│
    │ id             │ │ id         │ │ id              │
    │ colaborador(FK)│ │ colab (FK) │ │ colaborador(FK) │
    │ empresa_id(FK) │ │ empresa(FK)│ │ imagem          │
    │ data_hora      │ │ arquivo    │ │ embedding(bin)  │
    │ tipo (entrada/ │ │ data_ini   │ │ data_registro   │
    │  saida/intervI/│ │ data_fim   │ │ ativo           │
    │  intervF)      │ │ cid        │ │ angulo          │
    │ metodo (facial/│ │ obs        │ └─────────────────┘
    │  web/cpf/api)  │ │ aprovado   │
    │ latitude       │ │ aprovado_p │
    │ longitude      │ └────────────┘
    │ ip_address     │
    │ user_agent     │
    │ totem_id (FK)  │ (nullable — null se web)
    │ foto_momento   │ (foto no ato — anti-fraude)
    │ confianca_face │ (% de confiança do match)
    │ hash_registro  │ (SHA-256 — integridade)
    │ nsr            │ (Número Sequencial de Registro)
    │ comprovante_pdf│
    └────────────────┘

    ┌──────────────────┐       ┌──────────────────────┐
    │  Totem           │       │  GrupoTotem          │
    │──────────────────│       │──────────────────────│
    │ id               │       │ id                   │
    │ identificador    │       │ nome                 │
    │ empresa_id (FK)  │       │ cliente_id (FK)      │
    │ grupo_id (FK)    │       │ descricao            │
    │ modelo_tablet    │       └──────────────────────┘
    │ serial_tablet    │
    │ em_comodato      │
    │ data_instalacao  │
    │ ultimo_heartbeat │
    │ ativo            │
    │ token_acesso     │ ← Token único por totem
    │ versao_firmware  │
    └──────────────────┘

    ┌──────────────────┐       ┌──────────────────────┐
    │  BancoHoras      │       │  Justificativa       │
    │──────────────────│       │──────────────────────│
    │ id               │       │ id                   │
    │ colaborador (FK) │       │ colaborador (FK)     │
    │ empresa_id (FK)  │       │ data                 │
    │ data             │       │ tipo (falta/atraso/  │
    │ horas_trabalhadas│       │   saida_antecipada)  │
    │ horas_esperadas  │       │ motivo               │
    │ saldo_dia        │       │ aprovada             │
    │ saldo_acumulado  │       │ aprovada_por (FK)    │
    │ compensado       │       │ arquivo_comprovante  │
    └──────────────────┘       └──────────────────────┘

    ┌──────────────────┐       ┌──────────────────────┐
    │  LogAcesso       │       │  ConfiguracaoEmpresa │
    │──────────────────│       │──────────────────────│
    │ id               │       │ id                   │
    │ usuario (FK User)│       │ empresa_id (FK)      │
    │ cliente_id (FK)  │       │ tolerancia_atraso_min│
    │ ip               │       │ intervalo_minimo_min │
    │ user_agent       │       │ hora_extra_percentual│
    │ data_hora        │       │ adicional_noturno    │
    │ acao             │       │ hora_ini_noturno     │
    └──────────────────┘       │ hora_fim_noturno     │
                               │ modo_compensacao     │
                               │ (bool)               │
                               │ fecha_banco_dia      │
                               │ exporta_formato      │
                               │ (json/csv/afd)       │
                               │ notif_esq_ponto      │
                               │ (bool)               │
                               │ anti_fake_gps (bool) │
                               └──────────────────────┘
```

### 4.2 Observações sobre a Modelagem
- **face_embedding:** armazenado como `BinaryField` no PostgreSQL. O vetor numérico (128 ou 512 dimensões dependendo do modelo ArcFace) é serializado com `numpy.tobytes()` e deserializado com `numpy.frombuffer()`. Índice vetorial opcional com **pgvector** para busca por similaridade em larga escala.
- **hash_registro:** cada `RegistroPonto` recebe um SHA-256 composto por `colaborador_id + data_hora + nsr + salt_empresa`, garantindo integridade e não-repúdio conforme Portaria 671.
- **nsr:** Número Sequencial de Registro — auto-incrementado por empresa, exigido pela Portaria 671 para geração do AFD.
- **JSONField para jornada_config:** permite escalas complexas (12x36, 6x1, horários alternados) sem rigidez de schema.

---

## 5. ESTRUTURA DO PROJETO DJANGO

```
kronus-platform/
├── manage.py
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── nginx/
│   └── nginx.conf
│
├── config/                         # Configurações Django
│   ├── __init__.py
│   ├── settings/
│   │   ├── base.py                 # Settings compartilhados
│   │   ├── development.py
│   │   ├── production.py
│   │   └── test.py
│   ├── urls.py                     # URL raiz
│   ├── asgi.py
│   ├── wsgi.py
│   └── celery.py
│
├── apps/
│   ├── core/                       # App base — models compartilhados, mixins
│   │   ├── models.py               # BaseModel (timestamps, soft-delete)
│   │   ├── mixins.py               # TenantMixin, AuditMixin
│   │   ├── middleware.py           # TenantMiddleware, TimezoneMiddleware
│   │   ├── permissions.py          # IsMaster, IsClientAdmin, IsRHAdmin, IsColaborador
│   │   ├── utils.py                # CPF validator, hash generator
│   │   └── decorators.py
│   │
│   ├── accounts/                   # Autenticação e usuários
│   │   ├── models.py               # CustomUser (email OR cpf login)
│   │   ├── views.py                # Login, logout, password reset
│   │   ├── serializers.py
│   │   ├── backends.py             # CPFAuthBackend, EmailAuthBackend
│   │   ├── urls.py
│   │   └── templates/accounts/
│   │       ├── login.html
│   │       ├── login_colaborador.html
│   │       ├── password_reset.html
│   │       └── profile.html
│   │
│   ├── master/                     # Painel Master (KS TEC)
│   │   ├── models.py               # Plano, LogAcessoMaster
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── templates/master/
│   │       ├── dashboard.html
│   │       ├── clientes/
│   │       │   ├── lista.html
│   │       │   ├── detalhe.html
│   │       │   ├── criar.html
│   │       │   └── editar.html
│   │       ├── empresas/
│   │       │   ├── lista.html
│   │       │   └── vincular.html
│   │       ├── totems/
│   │       │   ├── lista.html
│   │       │   ├── comodato.html
│   │       │   └── grupos.html
│   │       ├── planos/
│   │       │   ├── lista.html
│   │       │   └── editar.html
│   │       └── logs/
│   │           └── acessos.html
│   │
│   ├── clientes/                   # Gestão de Clientes
│   │   ├── models.py               # Cliente, Empresa, ConfiguracaoEmpresa
│   │   ├── views.py
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   └── templates/clientes/
│   │
│   ├── rh/                         # Painel Admin RH da empresa
│   │   ├── models.py               # Colaborador, Departamento, Cargo
│   │   ├── views.py
│   │   ├── forms.py
│   │   ├── urls.py
│   │   ├── filters.py              # Filtros avançados
│   │   └── templates/rh/
│   │       ├── dashboard.html
│   │       ├── colaboradores/
│   │       │   ├── lista.html
│   │       │   ├── detalhe.html
│   │       │   ├── criar.html
│   │       │   ├── editar.html
│   │       │   ├── importar.html    # Import CSV/TXT
│   │       │   └── cadastro_facial.html
│   │       ├── pontos/
│   │       │   ├── registros.html
│   │       │   ├── espelho.html
│   │       │   ├── ajuste.html       # Ajuste manual
│   │       │   └── fechamento.html
│   │       ├── banco_horas/
│   │       │   ├── painel.html
│   │       │   ├── devedores.html
│   │       │   └── compensacao.html
│   │       ├── atestados/
│   │       │   ├── lista.html
│   │       │   ├── upload.html
│   │       │   └── aprovar.html
│   │       ├── escalas/
│   │       │   ├── lista.html
│   │       │   └── criar.html
│   │       ├── relatorios/
│   │       │   ├── geral.html
│   │       │   ├── horas_extras.html
│   │       │   ├── atrasos.html
│   │       │   ├── faltas.html
│   │       │   ├── afd.html          # Download AFD
│   │       │   └── aej.html          # Download AEJ
│   │       ├── justificativas/
│   │       │   ├── lista.html
│   │       │   └── aprovar.html
│   │       ├── configuracoes/
│   │       │   ├── empresa.html
│   │       │   ├── personalizacao.html # Logo, cores, idle screen
│   │       │   ├── notificacoes.html
│   │       │   └── integracao.html    # API keys
│   │       └── equipamentos/
│   │           ├── totems.html
│   │           └── grupos.html
│   │
│   ├── ponto/                      # Core — registro de ponto
│   │   ├── models.py               # RegistroPonto, BancoHoras, EscalaTrabalho
│   │   ├── views.py                # Bater ponto web
│   │   ├── services.py             # Lógica de negócio (cálculo horas, banco)
│   │   ├── calculators.py          # HorasExtrasCalculator, BancoHorasCalculator
│   │   ├── validators.py           # Validações de jornada
│   │   ├── serializers.py
│   │   ├── signals.py              # Post-save: calcular banco, gerar hash
│   │   ├── urls.py
│   │   ├── tasks.py                # Celery tasks (fechamento mensal, notificações)
│   │   └── templates/ponto/
│   │       ├── bater_ponto.html     # Interface web do colaborador
│   │       ├── meus_pontos.html     # Histórico do colaborador
│   │       ├── comprovante.html     # Template do comprovante
│   │       └── espelho_pdf.html     # Template para WeasyPrint
│   │
│   ├── facial/                     # Reconhecimento facial
│   │   ├── models.py               # FaceRegistro
│   │   ├── views.py                # API endpoints para totem
│   │   ├── services.py             # FaceRecognitionService (DeepFace wrapper)
│   │   ├── processors.py           # Pré-processamento de imagem
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   ├── tasks.py                # Async face encoding
│   │   └── templates/facial/
│   │       └── cadastro.html        # Webcam capture para cadastro
│   │
│   ├── totem/                      # Interface do totem
│   │   ├── views.py                # View do totem (serve a página)
│   │   ├── consumers.py            # WebSocket consumer para heartbeat
│   │   ├── urls.py
│   │   ├── middleware.py           # TotemTokenAuth
│   │   ├── static/totem/
│   │   │   ├── js/
│   │   │   │   ├── totem-app.js          # App principal do totem
│   │   │   │   ├── face-detector.js      # Wrapper face-api.js
│   │   │   │   ├── camera-manager.js     # Gerenciamento de câmera
│   │   │   │   ├── offline-handler.js    # Detecção de conexão
│   │   │   │   ├── ui-controller.js      # Estados da UI
│   │   │   │   └── models/              # Modelos face-api.js
│   │   │   │       ├── tiny_face_detector_model-weights_manifest.json
│   │   │   │       ├── tiny_face_detector_model-shard1
│   │   │   │       ├── face_landmark_68_tiny_model-weights_manifest.json
│   │   │   │       ├── face_landmark_68_tiny_model-shard1
│   │   │   │       ├── face_recognition_model-weights_manifest.json
│   │   │   │       └── face_recognition_model-shard1
│   │   │   ├── css/
│   │   │   │   └── totem.css             # Estilos exclusivos do totem
│   │   │   └── sw.js                     # Service Worker
│   │   └── templates/totem/
│   │       ├── index.html                # Página única do totem
│   │       └── offline.html              # Página offline
│   │
│   ├── api/                        # API REST pública
│   │   ├── views.py
│   │   ├── serializers.py
│   │   ├── urls.py                 # /api/v1/...
│   │   ├── authentication.py       # APIKeyAuth
│   │   ├── throttling.py
│   │   ├── permissions.py
│   │   └── docs.py                 # drf-spectacular (OpenAPI/Swagger)
│   │
│   ├── relatorios/                 # Geração de relatórios
│   │   ├── generators.py           # EspelhoPontoGenerator, AFDGenerator, AEJGenerator
│   │   ├── exporters.py            # PDF, XLSX, CSV exporters
│   │   ├── views.py
│   │   └── templates/relatorios/
│   │       ├── espelho_ponto.html   # Template WeasyPrint
│   │       ├── comprovante.html
│   │       └── folha_resumo.html
│   │
│   ├── notificacoes/               # Sistema de notificações
│   │   ├── models.py               # Notificacao
│   │   ├── services.py             # Email, push, in-app
│   │   ├── tasks.py                # Notificações agendadas
│   │   └── templates/notificacoes/
│   │       └── email/
│   │           ├── esquecimento_ponto.html
│   │           ├── ponto_registrado.html
│   │           └── banco_negativo.html
│   │
│   └── landing/                    # Landing page pública
│       ├── views.py
│       ├── urls.py
│       └── templates/landing/
│           ├── index.html
│           ├── funcionalidades.html
│           ├── planos.html
│           └── contato.html
│
├── static/                         # Arquivos estáticos globais
│   ├── css/
│   │   ├── main.css                # Tailwind compilado
│   │   └── components.css          # Componentes customizados
│   ├── js/
│   │   ├── main.js
│   │   ├── alpine-components.js
│   │   └── htmx-extensions.js
│   ├── img/
│   │   ├── logo-kstec.png
│   │   ├── logo-kstec-white.png
│   │   ├── favicon.ico
│   │   ├── og-image.png
│   │   └── illustrations/          # SVGs para landing page
│   └── fonts/
│       ├── Inter/
│       └── JetBrainsMono/
│
├── templates/                      # Templates globais
│   ├── base.html                   # Layout base (sidebar, topbar)
│   ├── base_auth.html              # Layout para login/registro
│   ├── base_totem.html             # Layout do totem (fullscreen)
│   ├── base_landing.html           # Layout da landing
│   ├── components/
│   │   ├── sidebar.html
│   │   ├── topbar.html
│   │   ├── breadcrumb.html
│   │   ├── pagination.html
│   │   ├── modal_confirm.html
│   │   ├── toast.html
│   │   ├── stats_card.html
│   │   ├── table.html
│   │   └── footer_kstec.html       # Rodapé "Desenvolvido por KS TEC"
│   ├── errors/
│   │   ├── 404.html
│   │   ├── 500.html
│   │   └── 403.html
│   └── emails/
│       └── base_email.html
│
├── media/                          # Uploads (em produção: S3/MinIO)
│   ├── logos/
│   ├── atestados/
│   ├── faces/
│   ├── idle_screens/
│   └── comprovantes/
│
├── scripts/                        # Scripts de manutenção
│   ├── seed_data.py                # Dados de teste
│   ├── generate_afd.py
│   └── face_benchmark.py
│
└── tests/
    ├── test_ponto.py
    ├── test_facial.py
    ├── test_banco_horas.py
    ├── test_api.py
    └── test_totem.py
```

---

## 6. TELAS E INTERFACES — DETALHAMENTO

### 6.1 LANDING PAGE (`/`)

**Objetivo:** Apresentar o Kronus, converter visitantes em leads.

**Seções (scroll vertical):**
1. **Hero:** Headline "Ponto inteligente. Gestão simplificada." + Subheadline + CTA "Solicitar Demonstração" + Mockup do sistema em tela de computador e totem
2. **Funcionalidades:** Grid 3 colunas com ícones — Reconhecimento Facial, Geolocalização, Banco de Horas, Espelho de Ponto, API de Integração, Multi-Empresa
3. **Como Funciona:** 3 steps ilustrados — "1. Cadastre → 2. Registre → 3. Gerencie"
4. **Totem:** Foto/render do totem com overlay explicativo — "Reconhecimento facial em menos de 2 segundos"
5. **Conformidade Legal:** Badge "REP-P Portaria 671/2021" + bullets de conformidade
6. **Planos:** Cards comparativos (Essencial / Profissional / Enterprise)
7. **Depoimentos:** Carrossel (futuro)
8. **CTA Final:** Formulário de contato (nome, email, telefone, empresa, nº colaboradores)
9. **Rodapé:** Logo KS TEC + links + "Desenvolvido por KS TEC Soluções de Tecnologia"

**Cores da landing:**
- Background: `--kronus-gray-50` (slate claro) alternando com `white`
- CTAs: `--kronus-primary-600` (midnight blue) com hover `--kronus-gold-500` (dourado)
- Detalhes / ícones: `--kronus-gold-400` (âmbar dourado)
- Texto: `--kronus-gray-800` / `--kronus-gray-600`
- Seções escuras (depoimentos, CTA final): fundo `--kronus-primary-700` com texto branco e acentos dourados

---

### 6.2 TELA DE LOGIN DO COLABORADOR (`/ponto/login`)

**Layout:** Centralizado, card sobre fundo gradiente sutil (indigo-50 → white)

**Campos:**
- Toggle: "CPF" / "E-mail" (switch)
- Campo CPF (com máscara `___.___.___-__`) ou Email
- Campo Senha
- Checkbox "Lembrar-me"
- Link "Esqueci minha senha"
- Botão "Entrar" (indigo-600)

**Elementos visuais:**
- Logo da empresa do colaborador (se identificável via subdomain ou seleção)
- Rodapé: Logo KS TEC (branca, versão small)

---

### 6.3 TELA DE BATER PONTO WEB (`/ponto/registrar`)

**Layout:** Mobile-first, card centralizado

**Elementos:**
- Relógio digital grande (HH:MM:SS) — atualizado em real-time
- Data por extenso: "Quinta-feira, 27 de agosto de 2026"
- Nome do colaborador + CPF mascarado (***.___.___-XX)
- Botão grande circular: **"REGISTRAR PONTO"** (animação pulse)
  - Cor dinâmica conforme tipo esperado:
    - Entrada: `--kronus-primary-600` (midnight blue)
    - Saída intervalo: `--kronus-warning` (amber)
    - Retorno intervalo: `--kronus-info` (blue)
    - Saída: `--kronus-success` (emerald)
- Após registro:
  - Animação de check (✓)
  - Toast: "Ponto registrado com sucesso!"
  - Info: tipo (Entrada/Saída), horário, geolocalização capturada
  - Link: "Ver comprovante (PDF)"
- Resumo do dia: tabela simples com registros do dia
- Se empresa autorizar: link "Ver meus registros" → histórico

**Geolocalização:**
- Solicita permissão via `navigator.geolocation`
- Se `geofencing_ativo` na empresa: valida se coordenadas estão dentro do raio
- Se fora: exibe aviso "Você está fora da área autorizada" + bloqueia ou registra com flag

---

### 6.4 TELA "MEUS PONTOS" DO COLABORADOR (`/ponto/meus-pontos`)

*Visível apenas se `empresa.permite_ver_ponto == True`*

**Layout:** Tabela responsiva com filtro de período

**Conteúdo:**
- Filtro por mês/ano (Flatpickr)
- Tabela: Data | Entrada | Saída Intervalo | Retorno | Saída | Total Horas | Status
- Status: ✅ Completo | ⚠️ Incompleto | ❌ Falta | 📋 Justificado
- Saldo de banco de horas (card resumo)
- Botão "Solicitar Justificativa" → modal com upload de comprovante
- Download: "Espelho de Ponto (PDF)" do mês

---

### 6.5 INTERFACE DO TOTEM — DETALHAMENTO COMPLETO

**Dispositivo alvo:** Positivo Tab 7 Vision (7", 1024x600, 3GB RAM, Android)
**Orientação:** Vertical (portrait) — fullscreen, sem barra de navegação (kiosk mode)
**URL:** `https://kronus.online/totem/{token_totem}/`

#### 6.5.1 Estados da Interface

**ESTADO 1 — IDLE (Ociosidade)**
```
┌──────────────────────────────┐
│                              │
│                              │
│   ┌──────────────────────┐   │
│   │                      │   │
│   │   IMAGEM FULLSCREEN  │   │
│   │   da empresa          │   │
│   │   (idle_screen_img)   │   │
│   │                      │   │
│   │   Proporção 9:16     │   │
│   │   ou logo centrada   │   │
│   │   em fundo escuro    │   │
│   │                      │   │
│   └──────────────────────┘   │
│                              │
│   ┌──────────────────────┐   │
│   │  ⏱ HH:MM:SS         │   │ ← Relógio translúcido, fonte grande
│   │  📅 27/08/2026       │   │
│   └──────────────────────┘   │
│                              │
│   ┌────────────────┐         │
│   │ 🔵 KS TEC logo │         │ ← Logo KS TEC pequena, branca, canto inferior
│   └────────────────┘         │
└──────────────────────────────┘
```
- A imagem de idle é configurada pelo admin da empresa
- Se não houver imagem: exibe logo da empresa centralizada sobre fundo `--totem-bg`
- O relógio é overlay translúcido na parte inferior
- Logo KS TEC branca, opacidade 60%, canto inferior direito
- **Saída do idle:** face-api.js roda em loop lento (1 frame/3s) detectando presença de rosto. Ao detectar um rosto, transita para Estado 2

**ESTADO 2 — CÂMERA ATIVA (Reconhecimento)**
```
┌──────────────────────────────┐
│  ┌──────────────────────┐    │
│  │     Logo Empresa     │    │ ← Logo da empresa, pequena, topo
│  └──────────────────────┘    │
│                              │
│  ┌──────────────────────┐    │
│  │ ╔══════════════════╗ │    │
│  │ ║                  ║ │    │
│  │ ║   FEED CÂMERA    ║ │    │ ← Frame da câmera
│  │ ║                  ║ │    │    Borda: glow pulsante indigo
│  │ ║   [Oval guide]   ║ │    │    Guia oval: onde posicionar o rosto
│  │ ║                  ║ │    │
│  │ ╚══════════════════╝ │    │
│  └──────────────────────┘    │
│                              │
│  ┌──────────────────────┐    │
│  │  🔍 Identificando... │    │ ← Spinner ou animação de scan
│  │  Posicione o rosto   │    │
│  └──────────────────────┘    │
│                              │
│  ⏱ HH:MM:SS                 │
│                              │
│  ┌────────────────┐          │
│  │ KS TEC         │          │
│  └────────────────┘          │
└──────────────────────────────┘
```
- Câmera frontal ativa via `getUserMedia({ video: { facingMode: 'user', width: 640, height: 480 } })`
- Borda animada (glow CSS com `box-shadow` pulsante `--totem-glow`)
- face-api.js (TinyFaceDetector) roda em loop rápido (~5 FPS)
- Ao detectar rosto com confiança > 0.7:
  - Captura frame (canvas → JPEG blob, quality 0.7, max 640px)
  - Envia para API: `POST /api/v1/totem/recognize/` com `Authorization: Token {token_totem}`
  - Payload: `{ "image": base64_jpeg, "totem_id": "xxx" }`

**ESTADO 3 — IDENTIFICADO (Sucesso)**
```
┌──────────────────────────────┐
│                              │
│  ┌──────────────────────┐    │
│  │     ✅ SUCESSO       │    │ ← Animação de check (Lottie ou CSS)
│  │                      │    │    Fundo verde gradiente
│  └──────────────────────┘    │
│                              │
│  ┌──────────────────────┐    │
│  │  ┌────────────────┐  │    │
│  │  │   Foto do       │  │    │ ← Foto do cadastro, circular
│  │  │   colaborador   │  │    │
│  │  └────────────────┘  │    │
│  │                      │    │
│  │  JOÃO DA SILVA       │    │ ← Nome completo, fonte grande, bold
│  │  CPF: ***.456.789-00 │    │ ← CPF mascarado, fonte mono
│  │                      │    │
│  │  ── Entrada ──       │    │ ← Tipo de registro
│  │  08:02:15            │    │ ← Horário, fonte extra-grande
│  │  27/08/2026          │    │
│  │                      │    │
│  │  "Bom trabalho! 💪"  │    │ ← Mensagem motivacional
│  └──────────────────────┘    │
│                              │
│  Retornando em 5s...         │ ← Countdown para idle
│                              │
│  KS TEC                      │
└──────────────────────────────┘
```
- Exibido por 5 segundos, depois retorna ao Estado 1
- Mensagens motivacionais rotativas:
  - "Bom trabalho! 💪"
  - "Excelente dia de trabalho!"
  - "Seu ponto foi registrado com sucesso!"
  - "Tenha um ótimo dia!"
  - "Trabalho registrado. Até a próxima!"
- Animação suave de entrada (fade-in + scale)

**ESTADO 4 — NÃO IDENTIFICADO (Fallback CPF)**
```
┌──────────────────────────────┐
│                              │
│  ┌──────────────────────┐    │
│  │  ⚠️ Não identificado │    │ ← Ícone warning, fundo amber
│  │  Use o teclado       │    │
│  └──────────────────────┘    │
│                              │
│  ┌──────────────────────┐    │
│  │  CPF:                │    │
│  │  ┌────────────────┐  │    │ ← Input numérico grande, com máscara
│  │  │ ___.___.__-__  │  │    │
│  │  └────────────────┘  │    │
│  │                      │    │
│  │  Data de Nascimento: │    │
│  │  ┌────────────────┐  │    │ ← Input data, numérico
│  │  │ __/__/____     │  │    │
│  │  └────────────────┘  │    │
│  │                      │    │
│  │  ┌────────────────┐  │    │
│  │  │ REGISTRAR      │  │    │ ← Botão grande verde
│  │  └────────────────┘  │    │
│  │                      │    │
│  │  ┌────────────────┐  │    │
│  │  │ VOLTAR         │  │    │ ← Botão cancelar
│  │  └────────────────┘  │    │
│  └──────────────────────┘    │
│                              │
│  ⏱ HH:MM:SS                 │
│  KS TEC                      │
└──────────────────────────────┘
```
- Teclado numérico nativo do Android (inputmode="numeric")
- Ao enviar: `POST /api/v1/totem/punch-cpf/` com `{ "cpf": "...", "data_nascimento": "...", "totem_id": "..." }`
- Se dados batem: transita para Estado 3 (sucesso)
- Se não: exibe "Dados inválidos. Tente novamente." + permanece no Estado 4
- Timeout de 30s sem interação → retorna ao idle

**ESTADO 5 — OFFLINE**
```
┌──────────────────────────────┐
│                              │
│  ┌──────────────────────┐    │
│  │                      │    │
│  │   Logo da Empresa    │    │ ← Logo da empresa, grande, centralizada
│  │                      │    │
│  └──────────────────────┘    │
│                              │
│  ┌──────────────────────┐    │
│  │  📡 Sem conexão      │    │ ← Ícone + texto
│  │                      │    │
│  │  Reconectando em     │    │
│  │  01:47               │    │ ← Countdown de 2 minutos
│  │                      │    │
│  │  ████████░░ 80%      │    │ ← Barra de progresso
│  └──────────────────────┘    │
│                              │
│  ┌──────────────────────┐    │
│  │   Logo KS TEC        │    │ ← Logo KS TEC, branca
│  │   kstec.online       │    │
│  └──────────────────────┘    │
│                              │
└──────────────────────────────┘
```
- Detectado via `navigator.onLine` + `window.addEventListener('offline', ...)`
- Também: heartbeat ping a cada 30s para `/api/v1/totem/heartbeat/` — se falhar 2x consecutivas = offline
- Countdown de 2 minutos com `setInterval`
- Ao final do countdown: `location.reload()` — recarrega a página
- Se reconectar antes: evento `online` → retorna ao idle

#### 6.5.2 Otimizações para Positivo Tab 7 Vision (3GB RAM)

1. **face-api.js com TinyFaceDetector** (190KB) em vez de SSD MobileNet (5.4MB)
2. **Detecção idle a 1 frame cada 3 segundos** (não contínuo)
3. **Detecção ativa a 5 FPS** (não 30 FPS) — `setInterval` de 200ms
4. **Canvas redimensionado para 320x240** para detecção (não resolução nativa da câmera)
5. **Compressão JPEG quality 0.7** antes do envio (reduz payload ~60%)
6. **Reconhecimento facial no SERVER** (DeepFace + ArcFace) — o tablet apenas DETECTA rosto e envia frame
7. **Service Worker** cacheia assets estáticos (CSS, JS, fontes, models face-api, logos)
8. **Nenhum framework JS pesado** — vanilla JS + CSS puro (sem React/Vue/Angular)
9. **CSS `will-change` e `transform: translateZ(0)`** para hardware acceleration nas animações
10. **Lazy loading** de fontes e imagens não-críticas
11. **Preconnect** para o domínio da API: `<link rel="preconnect" href="https://api.kronus.online">`
12. **Debounce** no envio de frames — no mínimo 2s entre envios para o servidor

#### 6.5.3 Service Worker do Totem

```javascript
// sw.js — Cache Strategy: Cache First para assets, Network First para API
const CACHE_NAME = 'kronus-totem-v1';  // kronus.online
const STATIC_ASSETS = [
  '/totem/offline.html',
  '/static/totem/css/totem.css',
  '/static/totem/js/totem-app.js',
  '/static/totem/js/face-detector.js',
  '/static/totem/js/camera-manager.js',
  '/static/totem/js/offline-handler.js',
  '/static/totem/js/models/tiny_face_detector_model-weights_manifest.json',
  '/static/totem/js/models/tiny_face_detector_model-shard1',
  // ... demais models e assets
  '/static/img/logo-kstec-white.png',
];
```

---

### 6.6 DASHBOARD DO ADMIN RH (`/rh/dashboard`)

**Layout:** Sidebar esquerda + conteúdo principal

**Sidebar:**
- Logo da empresa (topo)
- Menu:
  - 📊 Dashboard
  - 👥 Colaboradores
  - ⏱ Registros de Ponto
  - 📋 Espelho de Ponto
  - 🏦 Banco de Horas
  - 📅 Escalas de Trabalho
  - 📝 Justificativas
  - 🏥 Atestados
  - 📈 Relatórios
  - ⚙️ Configurações
  - 📡 Equipamentos (Totems)
  - 🔗 Integrações (API)
- Rodapé sidebar: "KS TEC" + logo pequena

**Conteúdo do Dashboard:**
- **Linha 1 — Cards de resumo:**
  - Colaboradores ativos (nº)
  - Registros hoje (nº)
  - Atrasos hoje (nº, cor warning)
  - Faltas hoje (nº, cor danger)
- **Linha 2 — Gráficos:**
  - Gráfico de barras: Registros por dia (últimos 30 dias)
  - Gráfico de pizza: Status dos pontos de hoje (completos / incompletos / ausentes)
- **Linha 3 — Tabelas:**
  - "Últimos registros" — tempo real (WebSocket)
  - "Colaboradores com banco negativo" — destaques em vermelho
  - "Justificativas pendentes" — badge com contador
- **Linha 4 — Alertas:**
  - Colaboradores que esqueceram de bater ponto
  - Totems offline
  - Atestados pendentes de aprovação

---

### 6.7 DASHBOARD DO MASTER (KS TEC) (`/master/dashboard`)

**Layout:** Sidebar escura (slate-900) + conteúdo

**Cards de resumo:**
- Total de clientes ativos
- Total de empresas vinculadas
- Total de colaboradores na plataforma
- Total de totems ativos
- Receita mensal estimada (clientes × plano)

**Tabelas:**
- Clientes: Nome | CNPJ | Plano | Empresas | Colaboradores | Totems | Status | Último Acesso | Ações
- Totems em comodato: ID | Modelo | Serial | Cliente | Empresa | Grupo | Status | Último Heartbeat

**Ações sobre clientes:**
- Criar novo cliente
- Editar dados
- Vincular/desvincular empresas
- Suspender/reativar
- Ver logs de acesso
- Gerar/regenerar API key
- Gerenciar totems em comodato

**Gestão de Totems:**
- Criar grupos de totems
- Vincular totem a empresa
- Vincular totem a grupo
- Definir colaboradores autorizados por totem/grupo
- Monitorar heartbeat (online/offline)
- Registrar comodato (data, modelo, serial, cliente)

---

## 7. API REST — ENDPOINTS

### 7.1 Autenticação

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/api/v1/auth/token/` | Obter JWT (login) — aceita CPF ou email + senha |
| POST | `/api/v1/auth/token/refresh/` | Refresh JWT |
| POST | `/api/v1/auth/token/verify/` | Verificar JWT |

### 7.2 Endpoints Públicos da API (com API Key)

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/v1/colaboradores/` | Listar colaboradores da empresa |
| GET | `/api/v1/colaboradores/{id}/` | Detalhe do colaborador |
| GET | `/api/v1/pontos/` | Listar registros de ponto (filtros: data, colaborador) |
| GET | `/api/v1/pontos/{id}/` | Detalhe de um registro |
| POST | `/api/v1/pontos/registrar/` | Bater ponto via API (requer auth do colaborador) |
| GET | `/api/v1/banco-horas/` | Consultar banco de horas |
| GET | `/api/v1/banco-horas/{colaborador_id}/` | Banco de horas de um colaborador |
| GET | `/api/v1/escalas/` | Listar escalas de trabalho |
| GET | `/api/v1/relatorios/espelho/` | Gerar espelho de ponto (params: mês, ano, colaborador) |
| GET | `/api/v1/relatorios/afd/` | Download do AFD |
| GET | `/api/v1/relatorios/aej/` | Download do AEJ |
| GET | `/api/v1/departamentos/` | Listar departamentos |
| GET | `/api/v1/atestados/` | Listar atestados |

### 7.3 Endpoints do Totem (Token de Totem)

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/api/v1/totem/recognize/` | Enviar frame para reconhecimento facial |
| POST | `/api/v1/totem/punch-cpf/` | Bater ponto via CPF + data nascimento |
| POST | `/api/v1/totem/heartbeat/` | Heartbeat do totem (a cada 30s) |
| GET | `/api/v1/totem/config/` | Obter configurações (logo, cores, idle_screen) |

### 7.4 Autenticação da API

- **API Key:** Header `X-API-Key: {chave}` — gerada pelo Master ou pelo Admin RH
- **Totem Token:** Header `Authorization: Token {token_totem}` — token único por totem
- **JWT:** Header `Authorization: Bearer {jwt}` — para operações de colaborador

**Rate Limiting:**
- API Key: 1000 req/hora (ajustável por plano)
- Totem: 600 req/hora (10/min para recognize, heartbeat ilimitado)
- Colaborador JWT: 100 req/hora

---

## 8. FUNCIONALIDADES DETALHADAS

### 8.1 Conformidade com Portaria 671/2021 (REP-P)

| Requisito | Implementação |
|---|---|
| **Identificação de empregador/empregado** | CNPJ da empresa + CPF do colaborador em cada registro |
| **NSR (Número Sequencial de Registro)** | Auto-incremento por empresa, campo `nsr` em `RegistroPonto` |
| **Comprovante de Registro de Ponto** | PDF gerado automaticamente (WeasyPrint) com CPF, data/hora, NSR, assinatura eletrônica |
| **AFD (Arquivo Fonte de Dados)** | Gerado conforme layout do Anexo V da Portaria — exportação em TXT |
| **AEJ (Arquivo Eletrônico de Jornada)** | Gerado para consulta da jornada tratada |
| **Integridade dos registros** | Hash SHA-256 por registro + logs imutáveis |
| **Assinatura eletrônica** | Hash criptográfico com carimbo de tempo |
| **Espelho de ponto** | Gerado com hash code para verificação de autenticidade |
| **Não-repúdio** | Reconhecimento facial + geolocalização + IP + User Agent |
| **Disponibilização ao trabalhador** | Comprovante disponível via app/web + email (se configurado) |

### 8.2 Reconhecimento Facial — Pipeline

```
CADASTRO:
1. Admin RH acessa "Cadastro Facial" do colaborador
2. Webcam captura 3-5 fotos do colaborador em ângulos diferentes
3. Fotos enviadas para o server
4. DeepFace (ArcFace) gera embedding 512-dim para cada foto
5. Embedding médio é salvo no campo face_embedding do Colaborador
6. Fotos originais são armazenadas em /media/faces/{empresa_id}/{colab_id}/

RECONHECIMENTO (Totem):
1. face-api.js (TinyFaceDetector) detecta rosto no browser
2. Frame capturado → JPEG base64 → POST /api/v1/totem/recognize/
3. Server recebe, decodifica imagem
4. DeepFace.represent() gera embedding do frame
5. Compara (distância cosseno) contra todos os embeddings dos colaboradores
   vinculados ao grupo de totems desse equipamento
6. Threshold de confiança: 0.68 (ArcFace cosine distance)
   - < 0.68 = MATCH → retorna dados do colaborador + registra ponto
   - >= 0.68 = NO MATCH → retorna "não identificado"
7. Tempo esperado: < 2s (com cache de embeddings em Redis)
```

### 8.3 Geolocalização e Geofencing

- **Captura:** `navigator.geolocation.getCurrentPosition()` com `enableHighAccuracy: true`
- **Armazenamento:** latitude e longitude em `RegistroPonto`
- **Geofencing:** se `empresa.geofencing_ativo == True`:
  - Calcula distância entre ponto do colaborador e `(geofencing_lat, geofencing_lng)` com fórmula de Haversine
  - Se distância > `geofencing_raio` (em metros): bloqueia ou registra com flag `fora_area`
- **Anti-fake GPS:** detecção de mock locations via headers e heurísticas (velocidade impossível entre pontos, precisão suspeita)

### 8.4 Banco de Horas e Compensação

- **Cálculo automático diário:** Celery task às 23:59 calcula saldo do dia para cada colaborador
- **Fórmula:** `saldo_dia = horas_trabalhadas - horas_esperadas`
- **Acumulado:** `saldo_acumulado = soma(saldo_dia)` do período
- **Modo compensação** (configurável por empresa):
  - **Ativo:** horas extras compensam horas faltantes automaticamente
  - **Inativo:** horas extras e débitos são tratados separadamente
- **Visualização:** painel com cores:
  - Verde: saldo positivo
  - Amarelo: saldo entre -2h e 0
  - Vermelho: saldo < -2h
- **Horas extras:** percentuais configuráveis (50%, 70%, 100%) por faixa horária
- **Adicional noturno:** cálculo automático (22h-5h, +20%, hora noturna = 52min30s)

### 8.5 Espelho de Ponto

- Gerado mensalmente (manualmente ou automaticamente)
- **Dados:** todos os registros do colaborador no mês
- **Cálculos:** horas normais, extras (por %), noturnas, faltas, atrasos, banco de horas
- **Hash de integridade:** SHA-256 do conteúdo, exibido no documento
- **Formatos:** PDF (WeasyPrint), XLSX, CSV
- **Assinatura:** aceite digital pelo colaborador (checkbox + timestamp) ou selfie
- **Layout:** cabeçalho com dados da empresa + colaborador, tabela dia-a-dia, resumo inferior

### 8.6 Atestados Médicos

- Upload pelo Admin RH: PDF, JPG, PNG (max 10MB)
- Campos: colaborador, data início, data fim, CID (opcional), observações
- Workflow: upload → pendente → aprovado/rejeitado pelo gestor
- Impacto: dias cobertos pelo atestado são marcados como "justificados" no espelho
- Armazenamento: MinIO/S3 com acesso restrito

### 8.7 Notificações

| Evento | Canal | Destinatário |
|---|---|---|
| Esquecimento de ponto | Email + in-app | Colaborador |
| Ponto registrado | In-app (opcional email) | Colaborador |
| Banco de horas negativo | Email + dashboard | Admin RH + Colaborador |
| Atestado pendente | Dashboard + email | Admin RH |
| Totem offline > 10min | Email + dashboard | Admin RH + Master |
| Justificativa pendente | Dashboard | Admin RH |
| Assinatura de espelho pendente | Email | Colaborador |
| Tentativa de fraude (fake GPS) | Dashboard + email | Admin RH |

### 8.8 Funcionalidades Adicionais (Inspiradas em Sistemas Comerciais)

| Funcionalidade | Descrição |
|---|---|
| **Importação de colaboradores** | Upload CSV/TXT com dados dos colaboradores |
| **Exportação para folha de pagamento** | Layouts pré-configurados (Domínio, Metadados, etc.) + custom |
| **Escalas de trabalho flexíveis** | Fixa, flexível, 12x36, 6x1, 5x2, plantão, customizada |
| **Tolerância configurável** | Minutos de tolerância para atraso (padrão CLT: 5 min) |
| **Intervalo intrajornada** | Controle de intervalo mínimo obrigatório |
| **Período de afastamento** | Férias, licença, afastamento INSS — auto-preenche espelho |
| **Feriados** | Cadastro de feriados nacionais, estaduais e municipais |
| **Dashboard do colaborador** | Visualização limitada dos próprios dados (se autorizado) |
| **Auditoria completa** | Log de todas as ações (quem fez, quando, o quê, IP) |
| **Multi-fuso horário** | Suporte a empresas com filiais em fusos diferentes |
| **Assinatura eletrônica do espelho** | Aceite digital com timestamp + hash |
| **Comprovante por e-mail** | Envio automático do comprovante após cada batida |
| **Portal do contador** | Acesso restrito para escritório de contabilidade |
| **Liveness detection (anti-spoofing)** | Verificação de "rosto vivo" no totem — detecção de foto impressa |
| **Detecção de GPS fictício** | Anti-fake GPS no registro web mobile |
| **Relatórios gerenciais** | Horas extras por departamento, custo estimado, ranking atrasos |
| **Integração eSocial** | Exportação de dados conforme layout eSocial |
| **Webhook de eventos** | Notificação para sistemas externos via webhook (ponto registrado, etc.) |

---

## 9. SEGURANÇA

| Medida | Implementação |
|---|---|
| **HTTPS obrigatório** | Certificado SSL em todos os endpoints |
| **CSRF Protection** | Django middleware padrão |
| **XSS Protection** | Templates auto-escaped + CSP headers |
| **SQL Injection** | ORM do Django (parametrized queries) |
| **Rate Limiting** | DRF throttling + Redis |
| **Senhas** | PBKDF2 (Django default) ou Argon2 |
| **JWT** | Tokens com expiração curta (15min access, 7d refresh) |
| **API Keys** | Hash armazenado, nunca texto plano |
| **LGPD** | Consentimento para dados biométricos, política de privacidade, direito de exclusão |
| **Dados faciais** | Armazenados como embeddings numéricos (não são reversíveis para imagem) |
| **Isolamento multi-tenant** | Schema PostgreSQL separado por cliente ou row-level security |
| **Backup** | Automatizado diário (PostgreSQL pg_dump + S3) |
| **Logs imutáveis** | Append-only para registros de ponto — sem UPDATE/DELETE |

---

## 10. CONFORMIDADE LGPD

- **Dados biométricos** (reconhecimento facial) são dados sensíveis sob a LGPD
- **Consentimento explícito** do colaborador antes do cadastro facial
- Termos de uso e política de privacidade acessíveis
- **Direito de exclusão:** colaborador pode solicitar exclusão dos dados faciais
- **Minimização:** embeddings armazenados, não fotos brutas (configurável — fotos podem ser deletadas após encoding)
- **Acesso restrito:** dados faciais acessíveis apenas por roles autorizados
- **Retenção:** política de retenção configurável (ex: 5 anos após desligamento, conforme legislação trabalhista)
- **DPO:** possibilidade de configurar contato do Encarregado de Dados

---

## 11. FASES DE DESENVOLVIMENTO

### Fase 1 — Fundação (Semanas 1-4)
- [ ] Setup do projeto Django com docker-compose
- [ ] Modelagem e migrations do banco de dados
- [ ] Sistema de autenticação (CPF + email)
- [ ] Multi-tenancy (Cliente → Empresa → Colaborador)
- [ ] CRUD de clientes, empresas, colaboradores
- [ ] Sistema de permissões (Master, Admin RH, Colaborador)
- [ ] Templates base (sidebar, topbar, componentes Tailwind)

### Fase 2 — Core de Ponto (Semanas 5-8)
- [ ] Registro de ponto web (desktop + mobile)
- [ ] Geolocalização no registro
- [ ] Cálculo de horas trabalhadas
- [ ] Espelho de ponto (geração PDF)
- [ ] Banco de horas automático
- [ ] Escalas de trabalho (CRUD + vinculação)
- [ ] Comprovante de registro (PDF)
- [ ] NSR e hash de integridade

### Fase 3 — Reconhecimento Facial e Totem (Semanas 9-14)
- [ ] Setup DeepFace + ArcFace no backend
- [ ] Endpoint de cadastro facial (upload + encoding)
- [ ] Endpoint de reconhecimento (`/api/v1/totem/recognize/`)
- [ ] Interface do totem (HTML/CSS/JS puro)
- [ ] Integração face-api.js (TinyFaceDetector)
- [ ] Estados do totem (idle, câmera, sucesso, fallback, offline)
- [ ] Service Worker + cache offline
- [ ] Heartbeat + detecção de conexão
- [ ] Fallback CPF + data nascimento
- [ ] Testes em Positivo Tab 7 Vision

### Fase 4 — Admin RH Completo (Semanas 15-18)
- [ ] Dashboard com gráficos e métricas
- [ ] Gestão de atestados (upload, aprovação)
- [ ] Justificativas e abonos
- [ ] Ajustes manuais de ponto
- [ ] Fechamento mensal
- [ ] Relatórios (horas extras, atrasos, faltas)
- [ ] Geração AFD/AEJ
- [ ] Personalização (logo, cores, idle screen)
- [ ] Configurações da empresa (tolerância, compensação, etc.)

### Fase 5 — Painel Master e API (Semanas 19-22)
- [ ] Dashboard Master (KS TEC)
- [ ] Gestão de totems e comodato
- [ ] Grupos de totems
- [ ] Gestão de planos e assinaturas
- [ ] API REST pública com documentação Swagger
- [ ] Sistema de API Keys
- [ ] Webhooks
- [ ] Rate limiting

### Fase 6 — Landing Page e Polimento (Semanas 23-25)
- [ ] Landing page completa
- [ ] Notificações (email + in-app)
- [ ] Importação/exportação de dados
- [ ] Exportação para folha de pagamento
- [ ] Testes end-to-end
- [ ] Otimização de performance
- [ ] Documentação da API
- [ ] Deploy em produção

### Fase 7 — Melhorias Pós-Lançamento (Contínuo)
- [ ] Liveness detection (anti-spoofing)
- [ ] Detecção de GPS fictício
- [ ] Portal do contador
- [ ] Integração eSocial
- [ ] App nativo (PWA avançado)
- [ ] Dashboard de sentimentos (funcionalidade premium)

---

## 12. CONFIGURAÇÃO DO AMBIENTE DE DESENVOLVIMENTO

### 12.1 Docker Compose

```yaml
# docker-compose.yml
services:
  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - db
      - redis

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: kronus
      POSTGRES_USER: kronus
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  celery:
    build: .
    command: celery -A config worker -l info
    env_file:
      - .env
    depends_on:
      - redis
      - db

  celery-beat:
    build: .
    command: celery -A config beat -l info
    env_file:
      - .env
    depends_on:
      - redis
      - db

volumes:
  postgres_data:
```

### 12.2 Requirements principais

```
# requirements.txt
Django>=5.1,<6.0
djangorestframework>=3.15
djangorestframework-simplejwt>=5.3
django-cors-headers>=4.3
django-filter>=24.0
django-extensions>=3.2
django-storages>=1.14
django-redis>=5.4
celery>=5.4
redis>=5.0
psycopg2-binary>=2.9
Pillow>=10.2
deepface>=0.0.93
numpy>=1.26
opencv-python-headless>=4.9
WeasyPrint>=62.0
openpyxl>=3.1
python-decouple>=3.8
gunicorn>=22.0
daphne>=4.1
channels>=4.1
channels-redis>=4.2
drf-spectacular>=0.27    # OpenAPI/Swagger
whitenoise>=6.6          # Static files
sentry-sdk>=1.40
boto3>=1.34              # S3/MinIO
```

---

## 13. VARIÁVEIS DE AMBIENTE

```env
# .env.example
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_NAME=kronus
DB_USER=kronus
DB_PASSWORD=your-db-password
DB_HOST=db
DB_PORT=5432

# Redis
REDIS_URL=redis://redis:6379/0

# Celery
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# Storage (S3/MinIO)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=kronus
AWS_S3_ENDPOINT_URL=http://minio:9000

# DeepFace
DEEPFACE_MODEL=ArcFace
DEEPFACE_DETECTOR=retinaface
FACE_RECOGNITION_THRESHOLD=0.68

# Email
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=

# Sentry
SENTRY_DSN=

# App
APP_URL=https://kronus.online
KSTEC_LOGO_URL=https://kstec.online/assets/ks-tec-logo.png
```

---

## 14. REGRAS DE NEGÓCIO IMPORTANTES

1. **Um registro de ponto NÃO pode ser editado.** Apenas ajustes manuais com justificativa e log de auditoria.
2. **O NSR é sequencial e imutável** — nunca pode haver gaps ou repetições por empresa.
3. **O hash de cada registro inclui o registro anterior** (chain), garantindo integridade sequencial.
4. **O espelho de ponto, uma vez assinado pelo colaborador, não pode ser alterado.**
5. **Dados faciais (embeddings) são deletados 30 dias após desligamento** (configurável).
6. **O totem funciona mesmo sem identificar o rosto** — o fallback CPF + nascimento está sempre disponível.
7. **A tolerância de atraso padrão é de 5 minutos** (Art. 58, §1º CLT), mas é configurável por empresa.
8. **O intervalo intrajornada mínimo é de 1 hora** para jornadas > 6h (Art. 71 CLT), configurável.
9. **O modo compensação, quando ativo, zera o banco de horas mensalmente** (ou no período acordado).
10. **API keys podem ser revogadas a qualquer momento** pelo Master ou Admin RH.
11. **Um colaborador não pode bater dois pontos em menos de 1 minuto** (proteção anti-duplo).
12. **Cada totem pertence a uma empresa e opcionalmente a um grupo** — um colaborador só é reconhecido em totems da sua empresa (ou grupo vinculado).

---

## 15. GLOSSÁRIO

| Termo | Definição |
|---|---|
| **REP-P** | Registrador Eletrônico de Ponto via Programa — categoria da Portaria 671/2021 para sistemas de ponto em software/nuvem |
| **AFD** | Arquivo Fonte de Dados — arquivo TXT com todos os registros brutos de ponto |
| **AEJ** | Arquivo Eletrônico de Jornada — arquivo com jornada tratada (após ajustes) |
| **NSR** | Número Sequencial de Registro — identificador único sequencial por empresa |
| **Espelho de Ponto** | Relatório mensal detalhado da jornada de cada colaborador |
| **Embedding** | Vetor numérico que representa as características de um rosto (128 ou 512 dimensões) |
| **Geofencing** | Cerca virtual geográfica — define área autorizada para registro de ponto |
| **Comodato** | Empréstimo de equipamento (totem) ao cliente durante a vigência do contrato |
| **Idle Screen** | Tela de ociosidade do totem — exibida quando não há ninguém interagindo |
| **Liveness Detection** | Técnica anti-fraude que verifica se o rosto é real (não foto/vídeo) |
| **LGPD** | Lei Geral de Proteção de Dados Pessoais (Lei 13.709/2018) |

---

## 16. AMBIENTE DE DESENVOLVIMENTO WINDOWS

A stack de produção (seção 2.5) é Linux-native, mas o desenvolvimento pode ser feito integralmente no Windows com as seguintes abordagens:

### 16.1 Abordagem Recomendada: Docker Desktop + WSL2

Tudo roda dentro de containers Linux — **zero adaptação necessária.** Instalar:
1. **WSL2** com Ubuntu 22.04+: `wsl --install -d Ubuntu`
2. **Docker Desktop** com backend WSL2 habilitado
3. **VS Code** com extensão Remote - WSL
4. Clonar o repositório dentro do filesystem WSL (`/home/user/kronus/`, não em `/mnt/c/`)
5. `docker-compose up` — todos os serviços sobem idênticos ao Linux

### 16.2 Abordagem Alternativa: Desenvolvimento Nativo Windows

| Componente | Adaptação necessária |
|---|---|
| **Python 3.12+** | Instalador oficial Windows — funciona normalmente |
| **Django** | Funciona nativamente no Windows sem alterações |
| **PostgreSQL** | Instalador Windows oficial ou via Docker |
| **Redis** | Sem build oficial Windows — usar Docker (`docker run -p 6379:6379 redis:7-alpine`) ou Memurai (fork Windows) |
| **Celery** | Rodar com `celery -A config worker --pool=solo -l info` (prefork não funciona no Windows) |
| **Gunicorn** | **Não funciona no Windows.** Usar `python manage.py runserver` para desenvolvimento. Gunicorn é apenas produção (Linux) |
| **Daphne** | Funciona no Windows normalmente |
| **Nginx** | Não necessário para dev. O `runserver` do Django serve static files. Para simular proxy, usar Docker |
| **DeepFace** | Funciona no Windows. Requer: `pip install deepface` + `pip install tf-keras` ou `pip install onnxruntime` |
| **OpenCV** | `pip install opencv-python-headless` funciona no Windows |
| **WeasyPrint** | Requer instalação manual do GTK3 no Windows (via MSYS2 ou all-in-one installer) |
| **Node.js / Tailwind** | Funciona nativamente no Windows |
| **Let's Encrypt** | N/A — apenas produção |
| **GitHub Actions** | N/A — roda na nuvem do GitHub |
| **Sentry / Prometheus** | Via Docker ou usar o SaaS do Sentry (sentry.io) |

### 16.3 Script de Setup Windows (PowerShell)

```powershell
# Pré-requisitos: Python 3.12+, Node.js 20+, Docker Desktop
# Instalar dentro de um virtualenv:

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Instalar dependências front-end
npm install -D tailwindcss @tailwindcss/forms
npx tailwindcss init

# Banco de dados (via Docker)
docker run -d --name kronus-db -p 5432:5432 -e POSTGRES_DB=kronus -e POSTGRES_USER=kronus -e POSTGRES_PASSWORD=dev123 postgres:16-alpine

# Redis (via Docker)
docker run -d --name kronus-redis -p 6379:6379 redis:7-alpine

# Migrations
python manage.py migrate
python manage.py createsuperuser

# Dev server
python manage.py runserver

# Celery (em outro terminal, com --pool=solo no Windows)
celery -A config worker --pool=solo -l info
```

### 16.4 Notas sobre DeepFace no Windows
- **TensorFlow backend:** `pip install tensorflow` — binários oficiais para Windows
- **ONNX backend (recomendado, mais leve):** `pip install onnxruntime` — funciona sem GPU
- **Com GPU NVIDIA:** `pip install onnxruntime-gpu` + CUDA Toolkit 11.8+
- O primeiro carregamento do modelo ArcFace faz download automático (~120MB)
- Para dev sem GPU, o reconhecimento leva ~0.5-1s por frame (aceitável para testes)

---

## 17. PROTOCOLO DE RELATÓRIO DE SESSÃO (CLAUDE CODE)

### 17.1 Objetivo
Ao final de cada sessão de desenvolvimento com o Claude Code, o assistente deverá gerar um relatório estruturado de progresso. Isso garante continuidade entre sessões e rastreabilidade do desenvolvimento.

### 17.2 Formato do Relatório de Sessão

O relatório deve ser gerado ao final de cada sessão e salvo como arquivo `SESSION_LOG_YYYY-MM-DD_NNN.md` na raiz do projeto:

```markdown
# Relatório de Sessão — Kronus (kronus.online)
**Data:** YYYY-MM-DD
**Sessão:** #NNN
**Duração aproximada:** X horas

## Fase Atual
[Nome da fase conforme seção 11 do plano]

## O que foi feito nesta sessão
- [ x ] Descrição detalhada do item concluído
- [ x ] Outro item concluído
- [ x ] ...

## Arquivos criados/modificados
| Arquivo | Ação | Descrição |
|---|---|---|
| `apps/ponto/models.py` | Criado | Models RegistroPonto, BancoHoras |
| `apps/ponto/views.py` | Modificado | Adicionado endpoint de registro |

## Decisões técnicas tomadas
- [Decisão] Justificativa breve
- ...

## Problemas encontrados
- [Problema] Como foi resolvido (ou se ficou pendente)

## Testes realizados
- Descrição do teste + resultado (passou/falhou)

## Pendências para a próxima sessão
- [ ] Item pendente 1 — prioridade (alta/média/baixa)
- [ ] Item pendente 2
- [ ] ...

## Status das Fases
| Fase | Status | Progresso |
|---|---|---|
| Fase 1 — Fundação | ✅ Concluída | 100% |
| Fase 2 — Core de Ponto | 🔄 Em andamento | 60% |
| Fase 3 — Reconhecimento Facial | ⏳ Não iniciada | 0% |
| Fase 4 — Admin RH | ⏳ Não iniciada | 0% |
| Fase 5 — Master e API | ⏳ Não iniciada | 0% |
| Fase 6 — Landing e Polimento | ⏳ Não iniciada | 0% |
| Fase 7 — Melhorias | ⏳ Não iniciada | 0% |

## Observações
- Notas adicionais, lembretes, ou contexto relevante para a próxima sessão
```

### 17.3 Regras do Protocolo
1. **Obrigatório:** o Claude Code DEVE gerar este relatório ao final de CADA sessão, sem necessidade de solicitação do desenvolvedor.
2. **Acumulativo:** cada sessão gera um arquivo novo (nunca sobrescreve o anterior).
3. **Progressivo:** o "Status das Fases" deve refletir o progresso real, atualizando os percentuais.
4. **Pendências claras:** a lista de pendências deve ser específica o suficiente para que qualquer sessão futura possa retomar sem contexto adicional.
5. **Antes de encerrar:** o Claude Code deve perguntar "Deseja que eu gere o relatório de sessão?" — caso o desenvolvedor encerre abruptamente, o relatório é gerado com base no que foi feito até aquele ponto.
6. **Arquivo de índice:** manter um `SESSION_INDEX.md` com links para todos os relatórios de sessão, atualizado a cada nova sessão.
7. **Referência cruzada:** o relatório deve referenciar os itens do plano de desenvolvimento (seção 11) pelos seus identificadores de fase e checklist.

---

## 18. REFERÊNCIAS TÉCNICAS

- **Portaria 671/2021 MTP:** https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/legislacao/portarias/2021/portaria-mtp-no-671-de-8-de-novembro-de-2021
- **DeepFace (GitHub):** https://github.com/serengil/deepface
- **face-api.js (GitHub):** https://github.com/justadudewhohacks/face-api.js
- **modern-face-api (fork atualizado):** https://github.com/SujalXplores/modern-face-api
- **Django REST Framework:** https://www.django-rest-framework.org/
- **Tailwind CSS:** https://tailwindcss.com/
- **Flowbite (componentes):** https://flowbite.com/
- **HTMX:** https://htmx.org/
- **Alpine.js:** https://alpinejs.dev/
- **CLT — Jornada de Trabalho:** Art. 58 a 75

---

*Documento gerado para uso interno de desenvolvimento.*
*© 2026 KS TEC Soluções de Tecnologia Ltda. Todos os direitos reservados.*
