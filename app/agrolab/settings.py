"""Configuración de AgroLab. Todo lo sensible viene de variables de entorno (.env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(nombre, defecto=False):
    return os.environ.get(nombre, str(defecto)).lower() in ("1", "true", "yes", "si")


# --- Seguridad básica -------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "solo-para-desarrollo-local"
    else:
        raise RuntimeError("Falta DJANGO_SECRET_KEY en el entorno (.env)")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")]

INSTALLED_APPS = [
    # Sin django.contrib.admin: el panel de Django no se instala (menos superficie de ataque).
    # Las funciones de administración van en vistas propias protegidas por rol (/gestion/).
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "agrolab.urls"
WSGI_APPLICATION = "agrolab.wsgi.application"

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
                "core.context_processors.rol",
            ],
        },
    },
]

# --- Base de datos ----------------------------------------------------------
# En Docker: PostgreSQL. Sin POSTGRES_HOST (tests locales): SQLite.
if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["POSTGRES_HOST"],
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ["POSTGRES_USER"],
            "PASSWORD": os.environ["POSTGRES_PASSWORD"],
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "dev.sqlite3"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Contraseñas: hash PBKDF2-SHA256 de Django (por defecto) + validadores ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

# --- Sesiones y cookies -----------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # nginx termina TLS
SESSION_COOKIE_SECURE = env_bool("COOKIES_SECURE", True)
CSRF_COOKIE_SECURE = env_bool("COOKIES_SECURE", True)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60  # 1 hora
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# --- Archivos ---------------------------------------------------------------
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 2 * 1024 * 1024))  # 2 MiB
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

# --- Reglas del caso --------------------------------------------------------
MAX_TRABAJOS_ACTIVOS = int(os.environ.get("MAX_TRABAJOS_ACTIVOS", 3))  # regla de negocio (cuota)
WORKER_POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", 1))
WORKER_DEMORA_SECONDS = float(os.environ.get("WORKER_DEMORA_SECONDS", 2))  # para ver los estados en la demo
WORKER_TIMEOUT_SECONDS = int(os.environ.get("WORKER_TIMEOUT_SECONDS", 120))  # trabajo "huérfano"

# --- Logs a stdout (docker compose logs) -----------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"}},
    "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["stdout"], "level": "INFO"},
    "loggers": {"django": {"handlers": ["stdout"], "level": "WARNING", "propagate": False}},
}
