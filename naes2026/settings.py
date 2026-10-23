from pathlib import Path
import os
import sys
from django.contrib.messages import constants as messages
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# True durante "manage.py test" (desliga Debug Toolbar e a chave do Gemini).
TESTANDO = 'test' in sys.argv

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only-key-change-in-production')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '*').split(',') if h.strip()]

# Origens confiáveis para o CSRF (obrigatório no App Engine, que serve via HTTPS).
# Ex.: CSRF_TRUSTED_ORIGINS=https://naes2026-500619.rj.r.appspot.com
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()
]

if not DEBUG:
    # O App Engine termina o HTTPS no balanceador e repassa a requisição em
    # HTTP com o cabeçalho X-Forwarded-Proto: é por ele que o Django sabe que
    # a conexão original era segura.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # Requisições internas do App Engine (/_ah/warmup etc.) chegam sem HTTPS.
    SECURE_REDIRECT_EXEMPT = [r'^_ah/']
    # HSTS começa curto (1 hora). Depois de confirmar que tudo funciona só em
    # HTTPS, dá para aumentar pela variável de ambiente (ex.: 31536000 = 1 ano).
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '3600'))
    # Decisão consciente (ver docs/deploy.md): includeSubDomains e preload são
    # difíceis de desfazer e os subdomínios de appspot.com não são do projeto.
    SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'website.apps.WebsiteConfig',
    'ia.apps.IaConfig',
    'assistente.apps.AssistenteConfig',
    'telegram_bot.apps.TelegramBotConfig',

    'crispy_forms',
    'crispy_bootstrap5',
    'django_filters',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'naes2026.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'website.context_processors.perfil',
            ],
        },
    },
]

WSGI_APPLICATION = 'naes2026.wsgi.application'

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    import dj_database_url  # type: ignore[import]
    DATABASES = {'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# O primeiro carrega o usuário já com os perfis Cliente/Administrador
# (2 consultas a menos por página). O ModelBackend continua na lista para que
# as sessões abertas antes desta mudança não sejam derrubadas.
AUTHENTICATION_BACKENDS = [
    'website.backends.BackendComPerfil',
    'django.contrib.auth.backends.ModelBackend',
]

if TESTANDO:
    # O PBKDF2 é lento de propósito; nos testes, cada login/create_user
    # pagaria esse custo. MD5 aqui é só para a suíte rodar rápido.
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'static_gcloud'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'index'
LOGOUT_REDIRECT_URL = 'index'

# O Bootstrap usa "danger" (e não "error") para a cor vermelha dos toasts.
MESSAGE_TAGS = {messages.ERROR: 'danger'}

# Django Debug Toolbar — apenas em desenvolvimento (DEBUG=True).
# Em produção (App Engine, DEBUG=False) nada disto é importado/instalado.
# Também fica de fora em "manage.py test", para não interferir nos testes.
if DEBUG and not TESTANDO:
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.insert(1, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = ['127.0.0.1']

# ---------------------------------------------------------------------------
# IA generativa — Gemini (google-genai). Ver app "ia" e a skill integracao-ia.
# ---------------------------------------------------------------------------
# A chave vem SEMPRE do ambiente (.env local / env_variables do app.yaml).
# Modelo, temperatura, limite de tokens, timeout e cota ficam na
# ConfiguracaoIA (banco), editável em IA → Configuração.
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
# Produção com identidade de serviço (Vertex AI), sem API Key. Desligado por padrão.
GEMINI_USAR_VERTEX = os.environ.get('GEMINI_USAR_VERTEX', 'False') == 'True'
GOOGLE_CLOUD_PROJECT = os.environ.get('GOOGLE_CLOUD_PROJECT', '')
GOOGLE_CLOUD_LOCATION = os.environ.get('GOOGLE_CLOUD_LOCATION', 'global')

# Só para a ESTIMATIVA de custo mostrada em Requisições da IA.
GEMINI_PRECO_ENTRADA_USD = 0.30 / 1_000_000   # por token
GEMINI_PRECO_SAIDA_USD = 2.50 / 1_000_000     # por token
GEMINI_COTACAO_BRL = 5.50

if TESTANDO:
    # Nenhum teste pode chamar a API de verdade, mesmo que o .env tenha a chave.
    GEMINI_API_KEY = ''
    GEMINI_USAR_VERTEX = False

# ---------------------------------------------------------------------------
# Bot do Telegram (webhook). Ver app "telegram_bot" e docs/deploy.md.
# ---------------------------------------------------------------------------
# Token e segredo SÓ no ambiente; nunca no banco, em templates, logs ou URLs.
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_WEBHOOK_SECRET = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
TELEGRAM_BOT_USERNAME = os.environ.get('TELEGRAM_BOT_USERNAME', '').lstrip('@')
TELEGRAM_TIMEOUT_SEGUNDOS = 10
# Limites por remetente, contados no banco (o App Engine pode ter várias
# instâncias: um contador em memória não serviria).
TELEGRAM_LIMITE_POR_MINUTO = 20
TELEGRAM_LIMITE_POR_DIA = 200
TELEGRAM_TENTATIVAS_VINCULO_POR_HORA = 5
TELEGRAM_CODIGO_VALIDADE_MINUTOS = 15

if TESTANDO:
    # Nenhum teste pode falar com o Telegram de verdade.
    TELEGRAM_BOT_TOKEN = ''
    TELEGRAM_WEBHOOK_SECRET = ''
