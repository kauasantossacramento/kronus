"""
Kronus — Settings compartilhados.

Plataforma de Ponto Eletronico Digital com Reconhecimento Facial (REP-P).
Conformidade: Portaria 671/2021 do MTP.

KS TEC Solucoes de Tecnologia Ltda — kstec.online
"""
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

# ==============================================================
# Caminhos
# ==============================================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent
APPS_DIR = BASE_DIR / "apps"

# ==============================================================
# Seguranca
# ==============================================================
SECRET_KEY = config("SECRET_KEY", default="insecure-dev-key-troque-em-producao")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

#: Origens confiaveis para CSRF. Necessario ao servir fora de localhost —
#: por exemplo, ao testar o totem em um tablet na rede local.
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# ==============================================================
# Aplicacoes
# ==============================================================
#: `apps.accounts` vem antes de `django.contrib.auth` de proposito: o Django
#: resolve comandos de management e templates pela ordem de INSTALLED_APPS
#: (o primeiro app vence), e e isso que faz o nosso `createsuperuser`
#: — que pergunta por e-mail OU CPF — substituir o comando padrao.
PRIORITY_APPS = [
    "apps.accounts",
]

DJANGO_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "channels",
]

LOCAL_APPS = [
    "apps.core",
    "apps.master",
    "apps.clientes",
    "apps.rh",
    "apps.ponto",
    "apps.facial",
    "apps.totem",
    "apps.api",
    "apps.relatorios",
    "apps.notificacoes",
    "apps.faturamento",
    "apps.landing",
    "apps.comercial",
]

INSTALLED_APPS = PRIORITY_APPS + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ==============================================================
# Middleware
# ==============================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # -- Kronus --------------------------------------------------
    "apps.core.middleware.TenantMiddleware",
    "apps.core.middleware.TimezoneMiddleware",
    "apps.core.middleware.AuditoriaMiddleware",
    # Por ultimo de proposito: escreve cabecalhos na resposta ja pronta,
    # inclusive nas geradas pelos middlewares acima. Fica inerte quando
    # o settings nao define CSP_* (dev e teste).
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ==============================================================
# Templates
# ==============================================================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.marca",
                "apps.core.context_processors.tenant",
                "apps.core.context_processors.aparencia",
                "apps.core.context_processors.ajuda_da_tela",
            ],
        },
    },
]

# ==============================================================
# Banco de Dados
# ==============================================================
DB_ENGINE = config("DB_ENGINE", default="postgres")

if DB_ENGINE == "sqlite":
    # Bootstrap local sem Docker. Producao SEMPRE PostgreSQL 16+.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "kronus_dev.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="kronus"),
            "USER": config("DB_USER", default="kronus"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
            "CONN_MAX_AGE": 60,
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==============================================================
# Autenticacao
# ==============================================================
AUTH_USER_MODEL = "accounts.CustomUser"

AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.CPFAuthBackend",
    "apps.accounts.backends.EmailAuthBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

#: Argon2 primeiro (Secao 9 do plano). O primeiro da lista e o usado
#: para novas senhas; os demais continuam validando as antigas, e o
#: Django reescreve o hash no proximo login bem-sucedido — a migracao
#: acontece sozinha, sem forcar ninguem a trocar de senha.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "landing:index"

SESSION_COOKIE_AGE = 60 * 60 * 8  # 8h
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ==============================================================
# Internacionalizacao
# ==============================================================
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Bahia"
USE_I18N = True
USE_TZ = True

# ==============================================================
# Arquivos estaticos e midia
# ==============================================================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

if config("USE_S3", default=False, cast=bool):
    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="kronus")
    AWS_S3_ENDPOINT_URL = config("AWS_S3_ENDPOINT_URL", default=None)
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True

# ==============================================================
# Cache / Redis
# ==============================================================
USE_REDIS = config("USE_REDIS", default=True, cast=bool)
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

if USE_REDIS:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "kronus-locmem",
        }
    }

# ==============================================================
# Channels (WebSockets — heartbeat do totem, dashboard real-time)
# ==============================================================
if USE_REDIS:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# ==============================================================
# Celery
# ==============================================================
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# ==============================================================
# Django REST Framework
# ==============================================================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    # Secao 7.4 do plano — Rate limiting
    "DEFAULT_THROTTLE_RATES": {
        "api_key": "1000/hour",
        "totem_recognize": "600/hour",
        "totem_heartbeat": "3000/hour",
        # Cadastro no proprio totem: um operador cadastrando cinco poses
        # de varias pessoas seguidas cabe folgado; um script tentando
        # senha, nao.
        "totem_manutencao": "300/hour",
        "colaborador": "100/hour",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Kronus API",
    "DESCRIPTION": "API REST do Kronus — Ponto Eletronico Digital (REP-P, Portaria 671/2021).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Assets servidos do proprio dominio, nao de CDN. A CSP permite CDN
    # para `script-src`, mas nao para `style-src` — o resultado era a
    # pagina de documentacao carregando o JS e perdendo todo o CSS.
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "CONTACT": {"name": "KS TEC", "url": "https://kstec.online"},
    "SCHEMA_PATH_PREFIX": "/api/v1",
    # Tres modelos tem um campo `tipo` com conjuntos de choices
    # diferentes. Sem nomear, o gerador inventa nomes como
    # "Tipo32eEnum" — que aparecem no client gerado pelo integrador e
    # nao dizem nada. Nomear e barato e o nome vai para a documentacao.
    "ENUM_NAME_OVERRIDES": {
        "TipoRegistroEnum": "apps.core.constants.TipoRegistro.choices",
        "TipoEscalaEnum": "apps.core.constants.TipoEscala.choices",
        "StatusDiaEnum": "apps.core.constants.StatusDia.choices",
        "MetodoRegistroEnum": "apps.core.constants.MetodoRegistro.choices",
    },
}

# ==============================================================
# CORS
# ==============================================================
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())

# ==============================================================
# E-mail
# ==============================================================
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.hostinger.com")
EMAIL_PORT = config("EMAIL_PORT", default=465, cast=int)

#: 465 fala SSL desde o primeiro byte; 587 comeca em claro e sobe para
#: TLS com STARTTLS. Sao mutuamente exclusivos no Django, e marcar os
#: dois levanta erro na inicializacao — melhor derivar da porta do que
#: deixar duas chaves que podem discordar entre si.
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=EMAIL_PORT == 465, cast=bool)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=not EMAIL_USE_SSL, cast=bool)
if EMAIL_USE_SSL:
    EMAIL_USE_TLS = False

EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="dpo@kstec.online")

#: Nunca no repositorio. Vive no `.env` do servidor, que nao e versionado
#: — uma senha de e-mail no git vaza para todo clone, para sempre, e
#: continua valida depois de o arquivo ser removido.
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

#: Remetente padrao de tudo o que o sistema manda: senha provisoria,
#: redefinicao, espelho de ponto fechado, aviso de fechamento.
#:
#: Configuravel porque a caixa pode mudar; com valor de fabrica porque
#: um sistema que nao manda e-mail por falta de configuracao falha em
#: silencio — a pessoa espera a senha que nunca chega.
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="Kronus <dpo@kstec.online>"
)
SERVER_EMAIL = config("SERVER_EMAIL", default=EMAIL_HOST_USER)

# ==============================================================
# Kronus — configuracoes de produto (Secoes 1 e 3 do plano)
# ==============================================================
KRONUS = {
    "APP_NAME": config("APP_NAME", default="Kronus"),
    "APP_URL": config("APP_URL", default="https://kronus.online"),
    "TAGLINE": "O tempo sob controle.",
    "TAGLINE_TOTEM": "Sistema Inteligente de Controle de Ponto Eletrônico",
    "TAGLINE_RODAPE": "Kronus — Gestao inteligente de ponto eletronico",
    "META_DESCRIPTION": (
        "Ponto eletronico digital com reconhecimento facial. Conforme Portaria 671."
    ),
    "DESENVOLVEDORA": config(
        "KSTEC_RAZAO_SOCIAL", default="KS TEC Solucoes de Tecnologia Ltda"
    ),
    "DESENVOLVEDORA_CNPJ": config("KSTEC_CNPJ", default="62.501.281/0001-13"),
    # Numero de registro do programa no INPI. Vai no campo 7 do
    # cabecalho do AFD e no nome do arquivo (Portaria 671/2021, Anexo V,
    # itens 7 e 19.3). Nasce vazio de proposito: enquanto o registro nao
    # existir, um campo em branco declara a pendencia; preencher com um
    # numero inventado seria declarar registro inexistente.
    "REGISTRO_INPI": config("REGISTRO_INPI", default=""),
    # Versao e e-mail vao no registro 08 do AEJ (identificacao do PTRP),
    # onde ambos sao campos obrigatorios.
    "VERSAO": config("KRONUS_VERSAO", default="1.0"),
    "EMAIL_SUPORTE": config("EMAIL_SUPORTE", default="suporte@kstec.online"),
    "DESENVOLVEDORA_SITE": config("KSTEC_SITE_URL", default="https://kstec.online"),
    # Servida por nos. Vinha de kstec.online, o que deixava a assinatura
    # quebrada justamente no totem sem internet — o equipamento que o
    # plano promete funcionar offline.
    "DESENVOLVEDORA_LOGO": config(
        "KSTEC_LOGO_URL", default=f"{STATIC_URL}img/ks-tec-logo.png"
    ),
}

# -- Reconhecimento facial (Secao 8.2) -------------------------
#: Trocado de ArcFace para Facenet512 apos medicao com duas pessoas
#: reais cadastradas no proprio totem — as mesmas fotos, os tres
#: caminhos, a mesma deteccao (MTCNN, recorte conferido):
#:
#:     modelo                    pior legitimo   melhor impostor
#:     ArcFace (base)                    0,601             0,141
#:     ArcFace (normalizacao propria)    0,648             0,146
#:     Facenet512                        0,464             0,617
#:
#: Com ArcFace as duas faixas se sobrepoem: a pose "esquerda" de duas
#: pessoas diferentes ficava a 0,141 — mais perto do que duas poses da
#: mesma pessoa. Nenhum limiar separa isso, e foi a causa dos falsos
#: positivos relatados; o que se via como "limiar mal escolhido" era o
#: modelo nao discriminando neste conjunto de imagens.
#:
#: O Facenet512 separa com folga de 0,15 entre as duas faixas.
DEEPFACE_MODEL = config("DEEPFACE_MODEL", default="Facenet512")

#: DESVIO DELIBERADO DO PLANO — detector.
#:
#: A Secao 2.1 indica RetinaFace. Medicao propria (LFW, benchmark citado
#: no proprio plano, CPU do ambiente de desenvolvimento):
#:
#:     retinaface  ~9.900 ms/imagem   <- inviabiliza o alvo de "< 2 s"
#:     mtcnn         ~460 ms/imagem   <- dentro do alvo
#:     sem detector  ~290 ms/imagem   (so o ArcFace)
#:
#: O gargalo e a deteccao, nao o embedding. O MTCNN manteve a acuracia
#: (99,5% em 435 pares) com 21x menos tempo. Em servidor com GPU o
#: RetinaFace volta a ser viavel — dai continuar configuravel.
DEEPFACE_DETECTOR = config("DEEPFACE_DETECTOR", default="mtcnn")

#: DESVIO DELIBERADO DO PLANO — threshold.
#:
#: A Secao 8.2 indica 0,68. Medicao propria no LFW mostrou que esse valor
#: produz FALSOS POSITIVOS — uma pessoa reconhecida como outra:
#:
#:     threshold   falso pos.   falso neg.   (435 pares, 10 pessoas)
#:        0.60         0            2
#:        0.65         2            0
#:        0.68         5            0        <- valor do plano
#:
#: Num REP-P a assimetria e decisiva: falso NEGATIVO faz o colaborador
#: usar o fallback por CPF (inconveniente); falso POSITIVO registra ponto
#: no nome de outra pessoa (fraude, com consequencia trabalhista).
#: 0,60 zerou os falsos positivos nas duas amostras medidas.
#: Medido em producao, e nao herdado do plano.
#:
#: Historico curto: 0,68 (plano) -> 0,60 -> 0,55 -> 0,45. Cada corte veio
#: de um falso positivo real, e o ultimo tem numero:
#:
#:     visitante aceito como o titular          0,4929
#:     o proprio titular, no mesmo dia          0,516 e 0,523
#:
#: O impostor ficou MAIS PERTO do que a pessoa certa. Isso nao e limiar
#: mal escolhido: e um cadastro que nao discrimina, feito com as poses
#: espalhadas (0,18 a 0,51 entre si) e numa camera diferente da que
#: registra o ponto.
#:
#: 0,45, e o numero vem do uso real — nao mais de fotos de cadastro
#: comparadas entre si.
#:
#: Vinte e cinco tentativas num dia, com seis pessoas cadastradas:
#:
#:     reconhecimentos legitimos    0,11 a 0,40
#:     ---------------------------- vao limpo -------------------------
#:     falsos positivos             0,505 · 0,512 · 0,516
#:     recusas corretas             0,52 a 0,65
#:
#: O limiar anterior, 0,52, tinha sido calibrado comparando as fotos do
#: cadastro umas com as outras. Capturas ao vivo se comportam diferente:
#: as legitimas ficam mais perto do que aquela medicao sugeria, e as de
#: quem se parece com alguem ficam logo acima de 0,50. Os dois falsos
#: positivos do dia caem exatamente nessa faixa — passaram por menos de
#: dois centesimos.
#:
#: 0,45 fica no meio do vao: rejeita os tres casos ruins e nao encosta
#: em nenhum acerto (o pior legitimo foi 0,40).
#:
#: A dupla confirmacao nao pega este caso, e vale dizer por que: ela
#: derruba o acerto de UM quadro por acaso, e um rosto parecido nao e
#: acaso — ele se repete no quadro seguinte. Contra semelhanca
#: persistente, quem decide e o limiar.
FACE_RECOGNITION_THRESHOLD = config("FACE_RECOGNITION_THRESHOLD", default=0.45, cast=float)

#: Distancia abaixo da qual duas capturas sao, na pratica, a mesma
#: pessoa.
#:
#: Serve para um erro de operacao, e nao para semelhanca: escolher o
#: colaborador errado na lista e cadastrar o rosto de quem esta na
#: frente. Bem abaixo do limiar de reconhecimento de proposito — a
#: verificacao por pose precisa ser rara, ou vira ruido que ensina o
#: operador a ignorar o aviso.
FACE_DISTANCIA_MESMA_PESSOA = config(
    "FACE_DISTANCIA_MESMA_PESSOA", default=0.25, cast=float
)

#: Espalhamento maximo entre as poses de um cadastro saudavel.
#:
#: Acima disso o cadastro e fraco: as capturas nao concordam entre si o
#: bastante para sustentar uma identificacao. Nao bloqueia — avisa, e o
#: aviso chega a quem cadastrou, que e quem pode refazer na hora.
FACE_ESPALHAMENTO_ACEITAVEL = config(
    "FACE_ESPALHAMENTO_ACEITAVEL", default=0.45, cast=float
)

#: Margem exigida sobre o segundo colocado, quando ha mais de uma pessoa.
#:
#: Aceitar o mais proximo sem olhar o segundo transforma duas pessoas
#: parecidas num sorteio: quem estiver um milesimo mais perto leva o
#: ponto. Sem folga clara, o totem prefere pedir o CPF — errar para o
#: lado do incomodo, e nao para o lado da fraude.
FACE_MARGEM_MINIMA = config("FACE_MARGEM_MINIMA", default=0.10, cast=float)

#: Abaixo disto, aceita na hora — sem segunda opiniao.
#:
#: A faixa onde o reconhecimento legitimo se concentra: medido em
#: producao, os acertos ficam entre 0,11 e 0,40, e a maioria abaixo de
#: 0,30. Quem cai aqui nao precisa de conferencia, e pagar por ela
#: tornaria lento o caso comum.
FACE_ACEITE_DIRETO = config("FACE_ACEITE_DIRETO", default=0.30, cast=float)

#: Modelo que da a segunda opiniao na faixa de duvida.
#:
#: Arquitetura diferente da principal de proposito. Dois modelos
#: parecidos erram junto — o que se quer aqui e um erro nao
#: correlacionado: se dois modelos treinados de formas diferentes
#: apontam a mesma pessoa, a chance de ser semelhanca fisica cai muito.
#:
#: So roda entre FACE_ACEITE_DIRETO e o limiar. Abaixo, aceita direto;
#: acima, recusa direto. A faixa de duvida e estreita, entao o custo em
#: tempo aparece em poucas batidas.
FACE_MODELO_CONFIRMACAO = config("FACE_MODELO_CONFIRMACAO", default="ArcFace")

#: Folga que o segundo modelo precisa dar ao primeiro colocado.
#:
#: Relativa, e nao absoluta: exigir uma distancia maxima do segundo
#: modelo obrigaria a calibrar um limiar novo, e limiar mal calibrado foi
#: exatamente o que produziu os falsos positivos. Perguntar "voce
#: tambem aponta esta pessoa, com folga?" nao precisa de calibracao.
FACE_MARGEM_CONFIRMACAO = config(
    "FACE_MARGEM_CONFIRMACAO", default=0.06, cast=float
)

#: Chave da API do Pexels, para o acervo da tela ociosa.
#:
#: Por variavel de ambiente, e nao no codigo: chave em repositorio vaza
#: no primeiro clone, e quem clona nem precisa ter ma intencao para
#: usa-la sem querer. Vazia desliga a busca automatica — o acervo
#: continua funcionando com o que ja foi importado e com o que o master
#: subir a mao.
PEXELS_API_KEY = config("PEXELS_API_KEY", default="")

#: Acima desta distancia, o reconhecimento e "fraco" e cobra folga extra.
#:
#: Abaixo do piso vale so a margem fixa. Acima, a exigencia cresce com a
#: fraqueza: um reconhecimento a 0,20 se basta; um a 0,44 esta na
#: sobreposicao entre titular e sosia e precisa provar que o segundo
#: colocado ficou para tras.
#:
#: Calibrado contra a galeria real, nao escolhido a mao: 0,34 com fator
#: 2,0 zerou os aceites errados (era um, a 0,3667) mantendo os 87
#: acertos, e sem recusar o caso legitimo de 0,30 com segundo a 0,38.
FACE_PISO_DE_RISCO = config("FACE_PISO_DE_RISCO", default=0.34, cast=float)

#: Quanto a exigencia cresce por ponto de distancia acima do piso.
FACE_FATOR_DE_RISCO = config("FACE_FATOR_DE_RISCO", default=2.0, cast=float)

#: Folga ate o segundo colocado que dispensa o segundo quadro.
#:
#: A dupla confirmacao custa caro: medido numa batida real, 4,7 s entre
#: um quadro e o outro — e 10 s ou mais quando um quadro se perde no
#: meio. Entre os dois envios o totem reacumula estabilidade, espera o
#: debounce e paga outra ida ao servidor. Numa fila, isso faz o totem
#: parecer mais lento que anotar o ponto no papel.
#:
#: Ela e dispensada so quando nao ha o que confirmar: reconhecimento
#: abaixo de FACE_ACEITE_DIRETO **e** segundo colocado a esta folga. So
#: a confianca nao bastaria — um sosia pode dar leitura confiante, e o
#: que separa os dois e a distancia ate ele, nao a confianca em si.
#:
#: 0,20 e a mesma folga que o autoaprendizado exige para gravar uma
#: referencia permanente. Se ela basta para mudar o cadastro, basta para
#: gravar uma batida.
FACE_FOLGA_SEM_CONFIRMAR = config(
    "FACE_FOLGA_SEM_CONFIRMAR", default=0.20, cast=float
)

#: Exigir que dois quadros seguidos apontem a MESMA pessoa.
#:
#: A defesa mais forte contra a confusao entre pessoas parecidas. Um
#: acerto por acaso vem de um quadro especifico — angulo, sombra,
#: movimento — e nao se repete no quadro seguinte; um reconhecimento
#: verdadeiro se repete. Custa cerca de um segundo a mais e derruba o
#: falso positivo de um quadro isolado.
#:
#: Quando os dois quadros discordam, os dois sao descartados: uma troca
#: de nome entre um quadro e outro e o sistema dizendo que nao sabe.
FACE_DUPLA_CONFIRMACAO = config(
    "FACE_DUPLA_CONFIRMACAO", default=True, cast=bool
)

#: Janela para o segundo quadro chegar.
#:
#: Curta: e a mesma pessoa parada na frente da camera. Longa demais,
#: confirmaria com o rosto de quem entrou na fila depois.
FACE_SEGUNDOS_CONFIRMACAO = config(
    "FACE_SEGUNDOS_CONFIRMACAO", default=8, cast=int
)

#: Distancia mediana acima da qual uma amostra nao e do mesmo rosto.
#:
#: Medido no cadastro real de producao, com as cinco poses que o roteiro
#: pede (frontal, esquerda, direita, cima, baixo):
#:
#:     amostras legitimas da MESMA pessoa   mediana 0,38 a 0,48
#:     amostra contaminada (outro rosto)    mediana 0,70
#:
#: 0,62 fica entre as duas faixas. O primeiro valor que usei, 0,55,
#: caiu perto demais da variacao legitima entre poses e recusou uma
#: captura boa — as poses "cima" e "baixo" sao naturalmente distantes
#: da frontal, e isso e o cadastro funcionando, nao falhando.
FACE_DISTANCIA_MAXIMA_AMOSTRA = config(
    "FACE_DISTANCIA_MAXIMA_AMOSTRA", default=0.62, cast=float
)

#: Motor de reconhecimento — ver apps.facial.providers.obter_provedor.
#:   auto           DeepFace se instalado, senao recusa com erro explicito
#:   deepface       forca o motor de producao
#:   deterministico motor de teste (nao reconhece rostos; compara bytes)
#:   indisponivel   desliga o reconhecimento facial
FACE_PROVIDER = config("FACE_PROVIDER", default="auto")

#: Numero de amostras exigidas no cadastro facial (Secao 8.2: 3 a 5).
FACE_AMOSTRAS_MINIMAS = config("FACE_AMOSTRAS_MINIMAS", default=3, cast=int)
#: Sete, e nao cinco. O cadastro supervisionado ocupa cinco poses; as
#: aprendidas precisam de espaco proprio, senao cada uma que entra
#: aposenta uma do cadastro original — que e justamente a referencia que
#: alguem conferiu.
FACE_AMOSTRAS_MAXIMAS = config("FACE_AMOSTRAS_MAXIMAS", default=7, cast=int)

#: Guardar o frame recebido pelo totem em tentativas malsucedidas.
#: Ajuda no suporte, mas e dado biometrico — desligado por padrao (LGPD).
FACE_GUARDAR_FRAME_TENTATIVA = config(
    "FACE_GUARDAR_FRAME_TENTATIVA", default=False, cast=bool
)

# -- Conformidade / Regras de negocio (Secao 14) ---------------
HASH_SALT_GLOBAL = config("HASH_SALT_GLOBAL", default="kronus-salt-dev")
FACE_RETENTION_DAYS_AFTER_TERMINATION = config(
    "FACE_RETENTION_DAYS_AFTER_TERMINATION", default=30, cast=int
)
INTERVALO_MINIMO_ENTRE_BATIDAS_SEGUNDOS = 60  # Regra 11
TOLERANCIA_ATRASO_PADRAO_MIN = 5  # Regra 7 — Art. 58 par. 1 CLT
INTERVALO_INTRAJORNADA_MINIMO_MIN = 60  # Regra 8 — Art. 71 CLT

# ==============================================================
# Logging
# ==============================================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {module}:{lineno} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "kronus": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
