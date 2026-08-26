"""
Django settings for the CodeNova GST fraud-ring detection prototype.

Everything environment-specific is read from environment variables so the same
image runs under docker-compose and on a bare laptop. See `.env.example` at the
repository root for the full list.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load a .env sitting next to docker-compose.yml (one level above `backend/`).
# In Docker the variables are injected by compose instead and this is a no-op.
load_dotenv(BASE_DIR.parent / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend,0.0.0.0").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "corsheaders",
    # local
    "core",
    "fraud_engine",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# PostgreSQL is the real target (and what docker-compose starts). USE_SQLITE is
# an escape hatch so `manage.py test` runs on a machine with no Postgres.
if env_bool("USE_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "fraud_db"),
            "USER": os.getenv("POSTGRES_USER", "fraud_user"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "fraud_pass"),
            "HOST": os.getenv("POSTGRES_HOST", "postgres"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # NOTE: list views that need a client-controlled ?page_size= set
    # `pagination_class = StandardPagination` on themselves (see core/views.py).
    # It cannot be wired up here: rest_framework.generics reads
    # DEFAULT_PAGINATION_CLASS while its own module body is executing, so
    # pointing this at a class in an app module that imports generics is a
    # circular import.
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    # Only authenticated officers can use the API. Token auth (not session/CSRF)
    # because the client is a React SPA talking cross-origin, not a browser
    # form: a bearer token in the Authorization header needs no CSRF dance.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

# The React dev server talks to Django cross-origin. Credentials are carried in
# an Authorization header (token auth), not cookies, so this stays safe even
# fully open for local development.
CORS_ALLOW_ALL_ORIGINS = True

# ---------------------------------------------------------------------------
# Project-specific knobs
# ---------------------------------------------------------------------------
# Where the committed pretrained risk model lives.
MODEL_ARTIFACT_DIR = BASE_DIR / "fraud_engine" / "models_artifacts"

# Longest circular-trade chain we look for. Real ITC rings are short; bounding
# this keeps cycle enumeration cheap and predictable.
MAX_RING_SIZE = 6

# The score at or above which an alert counts as "high risk".
#
# This is a policy choice, not a constant: it trades officer time against
# missed rings, and a department should be able to move it. It used to be the
# literal 70 hardcoded in two different files. Every detection run records the
# threshold in force when it ran, and so does every ledger block, so a past
# decision can always be read back against the policy that produced it.
RISK_THRESHOLD = float(os.getenv("RISK_THRESHOLD", "70"))

# ---------------------------------------------------------------------------
# Email - case reports to the supervisor
# ---------------------------------------------------------------------------
# With no EMAIL_HOST set, mail is printed to the backend console instead of
# being sent. That keeps the whole report workflow demonstrable before any
# credentials exist, and makes a missing configuration obvious rather than
# silent.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@localhost"
)
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend",
)

# Who is copied on every case report, in addition to the officer who issued it.
# Comma-separated. Anyone in the SUPERVISOR_GROUP_NAME group who has an email
# address on their account is added to this automatically.
REPORT_SUPERVISOR_EMAILS = os.getenv("REPORT_SUPERVISOR_EMAILS", "")
SUPERVISOR_GROUP_NAME = os.getenv("SUPERVISOR_GROUP_NAME", "Supervisors")
