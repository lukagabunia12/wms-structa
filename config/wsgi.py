import os
from pathlib import Path

from django.core.wsgi import get_wsgi_application

# Comme manage.py : sans cela, un déploiement WSGI (gunicorn, waitress) ignore .env et
# retombe silencieusement sur DJANGO_SECRET_KEY / ALLOWED_HOSTS / DJANGO_DB_PATH par défaut.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
