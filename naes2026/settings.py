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

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'website.apps.WebsiteConfig',

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
                'website.context_processors.chatbot',
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
# IA generativa — Gemini (google-genai)
# ---------------------------------------------------------------------------
# A chave vem SEMPRE do ambiente (.env local / env_variables do app.yaml).
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash-lite')
GEMINI_PRECO_ENTRADA_USD = 0.30 / 1_000_000   # por token
GEMINI_PRECO_SAIDA_USD = 2.50 / 1_000_000     # por token
GEMINI_COTACAO_BRL = 5.50
GEMINI_TIMEOUT_CHAT_MS = 20_000      # timeout de cada chamada do chat
GEMINI_TIMEOUT_ANALISE_MS = 8_000    # a análise roda no envio do pedido: timeout curto

# Produção com identidade de serviço (Vertex AI), sem API Key. Desligado por padrão.
GEMINI_USAR_VERTEX = os.environ.get('GEMINI_USAR_VERTEX', 'False') == 'True'
GOOGLE_CLOUD_PROJECT = os.environ.get('GOOGLE_CLOUD_PROJECT', '')
GOOGLE_CLOUD_LOCATION = os.environ.get('GOOGLE_CLOUD_LOCATION', 'global')

if TESTANDO:
    # Nenhum teste pode chamar a API de verdade, mesmo que o .env tenha a chave.
    GEMINI_API_KEY = ''
    GEMINI_USAR_VERTEX = False

IA_HABILITADA = bool(GEMINI_API_KEY) or GEMINI_USAR_VERTEX
