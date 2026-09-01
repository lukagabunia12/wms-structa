import os
from pathlib import Path

from django.core.asgi import get_asgi_application

# Voir config/wsgi.py : le .env doit être chargé aussi hors de manage.py.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_asgi_application()
