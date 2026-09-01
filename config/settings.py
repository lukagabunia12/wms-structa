"""Configuration Django — WMS Structa.

Deux modes assumés, pilotés par le seul fichier `.env` :

- **Poste de développement** : `DJANGO_DEBUG=True`. Traces d'erreur complètes,
  CORS ouvert, statiques servis par Django. Jamais sur un poste de production.
- **Exploitation** (défaut) : `DJANGO_DEBUG=False`. Aucune trace exposée, cookies
  durcis, hôtes autorisés explicites. C'est le mode attendu dès que l'application
  est ouverte à d'autres postes, *a fortiori* derrière un tunnel Cloudflare.

Le défaut est volontairement le mode le plus sûr : un oubli de configuration
dégrade le confort, jamais la sécurité.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# `.env` est lu s'il existe et si python-dotenv est installé. Sans lui, les
# variables d'environnement du système font foi (cas d'un service Windows).
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - dépendance optionnelle
    pass


def _bool(nom, defaut=False):
    """Lit un booléen d'environnement en acceptant les écritures courantes.

    L'ancienne lecture (`== "True"`) faisait passer « true », « 1 » ou « TRUE »
    pour False : on pouvait croire DEBUG actif — ou inactif — à tort.
    """
    brut = os.environ.get(nom)
    if brut is None:
        return defaut
    return brut.strip().lower() in ("1", "true", "vrai", "oui", "yes", "on")


def _liste(nom, defaut=""):
    return [v.strip() for v in os.environ.get(nom, defaut).split(",") if v.strip()]


CLE_EXEMPLE = "changez-moi-en-production"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")

# Défaut = production. Un poste de développement pose explicitement DJANGO_DEBUG=True.
DEBUG = _bool("DJANGO_DEBUG", False)

# La clé secrète signe les jetons et les sessions. Laissée à sa valeur d'exemple en
# exploitation, n'importe qui connaissant le projet peut forger une session
# d'administrateur : on refuse de démarrer plutôt que de tourner en apparence.
if not DEBUG and SECRET_KEY in (CLE_EXEMPLE, "dev-insecure-change-me", ""):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY n'a pas été personnalisée dans .env. Générez-en une avec :\n"
        "    python -c \"from django.core.management.utils import get_random_secret_key as k; print(k())\"\n"
        "puis collez le résultat dans .env, ligne DJANGO_SECRET_KEY=…"
    )

ALLOWED_HOSTS = _liste("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "wms",
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
ASGI_APPLICATION = "config.asgi.application"

# --- Base de données --------------------------------------------------------
# SQLite par défaut (un fichier, zéro administration). Pour passer sur un vrai
# serveur SQL — PostgreSQL, MySQL/MariaDB — il suffit de renseigner ces variables
# dans `.env` : aucune ligne de code à changer.
#     DJANGO_DB_ENGINE=django.db.backends.postgresql
#     DJANGO_DB_NAME=wms   DJANGO_DB_USER=wms   DJANGO_DB_PASSWORD=…
#     DJANGO_DB_HOST=192.168.x.x   DJANGO_DB_PORT=5432
# (le pilote correspondant est à installer : `pip install psycopg[binary]`
#  pour PostgreSQL, `pip install mysqlclient` pour MySQL/MariaDB.)
DB_ENGINE = os.environ.get("DJANGO_DB_ENGINE", "django.db.backends.sqlite3")

if DB_ENGINE.endswith("sqlite3"):
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
            # SQLite verrouille toute la base pendant une écriture. Sans délai
            # d'attente, deux opérateurs qui rangent une cabine en même temps
            # produisent un « database is locked ». 20 s couvrent largement
            # l'écriture d'un mouvement.
            "OPTIONS": {"timeout": 20},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": os.environ.get("DJANGO_DB_NAME", "wms"),
            "USER": os.environ.get("DJANGO_DB_USER", ""),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ.get("DJANGO_DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DJANGO_DB_PORT", ""),
            # Connexions réutilisées 60 s : sur un serveur SQL distant, ouvrir une
            # connexion par requête double le temps de réponse au poste.
            "CONN_MAX_AGE": int(os.environ.get("DJANGO_DB_CONN_MAX_AGE", "60")),
        }
    }

AUTH_USER_MODEL = "wms.Utilisateur"

# La casse de l'identifiant ne doit pas décider d'une connexion : le clavier d'un
# téléphone met une majuscule à la première lettre, et « Enzo » n'est pas « enzo »
# pour Django. Voir wms/authentification.py — aucune autre vérification n'est
# relâchée.
AUTHENTICATION_BACKENDS = ["wms.authentification.IdentifiantInsensibleALaCasse"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Le WMS tourne sur un poste de l'entrepôt, sans serveur web devant lui : Django
# doit continuer à servir /static/ même en DEBUG=False, sinon l'interface se charge
# sans style ni JavaScript (page blanche). À passer à False le jour où un Nginx /
# IIS sert `staticfiles/` directement.
SERVIR_STATIQUES = _bool("DJANGO_SERVIR_STATIQUES", True)

# --- Durcissement en exploitation -------------------------------------------
if not DEBUG:
    # Cloudflare (ou tout reverse-proxy) termine le TLS et transmet l'entête.
    # Sans cette ligne, Django croit la requête en clair et boucle sur la
    # redirection HTTPS. À laisser à False en réseau interne sans proxy.
    if _bool("DJANGO_DERRIERE_PROXY", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        SECURE_SSL_REDIRECT = _bool("DJANGO_FORCER_HTTPS", True)
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True
        SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    X_FRAME_OPTIONS = "DENY"
    SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_HEURES", "12")) * 3600

# Origines de confiance pour le POST (admin Django derrière un nom de domaine).
# Ex. : DJANGO_CSRF_ORIGINS=https://wms.structa.fr
CSRF_TRUSTED_ORIGINS = _liste("DJANGO_CSRF_ORIGINS")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # DroitWMS = IsAuthenticated + application des droits fins de Utilisateur en écriture.
    "DEFAULT_PERMISSION_CLASSES": ["wms.permissions.DroitWMS"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Seul `/api/token/` est joignable sans compte : ce quota borne les essais de
    # mot de passe, ce qui compte dès que l'application est publiée sur internet.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("DJANGO_QUOTA_ANONYME", "30/min")},
}

# CORS : ouvert seulement en développement. En exploitation, l'interface est servie
# par le même serveur que l'API — aucune origine tierce n'a de raison d'appeler.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = _liste("DJANGO_CORS_ORIGINS")

# --- Journalisation ---------------------------------------------------------
# En DEBUG=False, une erreur serveur ne s'affiche nulle part : sans ce fichier,
# un incident au poste ne laisse aucune trace exploitable le lendemain.
DOSSIER_LOGS = Path(os.environ.get("DJANGO_LOG_DIR", BASE_DIR / "logs"))
try:
    DOSSIER_LOGS.mkdir(parents=True, exist_ok=True)
    _fichier_log = str(DOSSIER_LOGS / "wms.log")
except OSError:  # dossier non inscriptible : on se rabat sur la console seule
    _fichier_log = None

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "horodate": {"format": "{asctime} {levelname} {name} — {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "horodate"},
        **({"fichier": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": _fichier_log,
            "maxBytes": 2_000_000,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "horodate",
        }} if _fichier_log else {}),
    },
    "root": {
        "handlers": ["console"] + (["fichier"] if _fichier_log else []),
        "level": "INFO" if DEBUG else "WARNING",
    },
}
