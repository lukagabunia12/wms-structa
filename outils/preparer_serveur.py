"""Contrôle de pré-vol avant d'ouvrir le WMS aux postes de l'entrepôt.

À lancer sur le serveur, après installation et avant la mise en service. Il
vérifie ce qui, en pratique, fait rater une mise en production : une clé secrète
d'exemple, le mode DEBUG resté actif, une base injoignable, un schéma en retard,
aucun compte administrateur, les bibliothèques du scanner absentes.

    python outils/preparer_serveur.py

Code de sortie 0 si tout est vert, 1 s'il reste un point bloquant. C'est ce code
que le script de démarrage teste avant de lancer le service.
"""
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

VERT, ORANGE, ROUGE = "OK   ", "ATTN ", "BLOC "
constats = []


def noter(niveau, titre, detail=""):
    constats.append((niveau, titre, detail))


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django
        django.setup()
    except Exception as e:
        print(f"{ROUGE} Django n'a pas pu démarrer : {e}")
        print("\nCause la plus fréquente : DJANGO_SECRET_KEY absente ou restée à sa "
              "valeur d'exemple dans .env. Lancez `python outils/preparer_env.py`.")
        return 1

    from django.conf import settings
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    # --- Configuration ------------------------------------------------------
    if settings.DEBUG:
        noter(ROUGE, "DJANGO_DEBUG est à True",
              "La page d'erreur exposerait la clé secrète et le mot de passe de la "
              "base à n'importe quel visiteur. Mettez False dans .env.")
    else:
        noter(VERT, "Mode production (DEBUG=False)")

    cle = settings.SECRET_KEY
    if len(cle) < 40 or cle in (settings.CLE_EXEMPLE, "dev-insecure-change-me"):
        noter(ROUGE, "Clé secrète faible", "Lancez `python outils/preparer_env.py`.")
    else:
        noter(VERT, f"Clé secrète personnalisée ({len(cle)} caractères)")

    hotes = settings.ALLOWED_HOSTS
    if "*" in hotes:
        noter(ORANGE, "DJANGO_ALLOWED_HOSTS = *",
              "Acceptable sur un réseau fermé. Sur une adresse fixe, listez les noms "
              "attendus : c'est une barrière de plus contre les requêtes égarées.")
    else:
        noter(VERT, "Hôtes autorisés : " + ", ".join(hotes))

    # --- Base de données ----------------------------------------------------
    reglages = settings.DATABASES["default"]
    moteur = reglages["ENGINE"].rsplit(".", 1)[-1]
    try:
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
            curseur.fetchone()
    except Exception as e:
        noter(ROUGE, f"Base {moteur} injoignable", str(e).strip().splitlines()[0])
        return rendu()

    if moteur == "sqlite3":
        noter(ORANGE, "Base SQLite",
              "Convient à un poste unique. Sur un serveur partagé par plusieurs "
              "postes qui écrivent en même temps, préférez PostgreSQL : voir "
              "docs/guide-deploiement.md.")
    else:
        noter(VERT, f"Base {moteur} sur {reglages.get('HOST') or 'local'}")

    try:
        executeur = MigrationExecutor(connection)
        restantes = executeur.migration_plan(executeur.loader.graph.leaf_nodes())
        if restantes:
            noter(ROUGE, f"{len(restantes)} migration(s) en attente",
                  "Lancez `python manage.py migrate` avant d'ouvrir le service.")
        else:
            noter(VERT, "Schéma de base à jour")
    except Exception as e:
        noter(ROUGE, "Plan de migration illisible", str(e))

    # --- Contenu ------------------------------------------------------------
    from wms.models import Emplacement, Utilisateur

    admins = Utilisateur.objects.filter(is_superuser=True).count() \
        + Utilisateur.objects.filter(role=Utilisateur.ADMIN).exclude(is_superuser=True).count()
    if admins:
        noter(VERT, f"{admins} compte(s) administrateur")
    else:
        noter(ROUGE, "Aucun compte administrateur",
              "Lancez `python manage.py createsuperuser`.")

    emplacements = Emplacement.objects.count()
    noter(VERT if emplacements else ORANGE,
          f"{emplacements} emplacement(s) au référentiel",
          "" if emplacements else "Rien à scanner tant qu'aucun emplacement n'existe.")

    # --- Autonomie du poste -------------------------------------------------
    vendor = RACINE / "wms" / "static" / "app" / "vendor"
    if all((vendor / n).is_file() for n in ("html5-qrcode.min.js", "qrcode.min.js")):
        noter(VERT, "Bibliothèques du scanner servies en local")
    else:
        noter(ORANGE, "Bibliothèques du scanner absentes",
              "Le scan caméra et l'impression des QR dépendront d'internet. "
              "Lancez une fois `python manage.py telecharger_libs`.")

    try:
        import waitress  # noqa: F401
        noter(VERT, "Serveur d'application waitress installé")
    except ImportError:
        noter(ORANGE, "waitress absent",
              "`manage.py runserver` est un outil de développement. "
              "Installez-le : pip install -r requirements.txt")

    dossier_logs = Path(getattr(settings, "DOSSIER_LOGS", RACINE / "logs"))
    try:
        dossier_logs.mkdir(parents=True, exist_ok=True)
        essai = dossier_logs / ".essai"
        essai.write_text("x", encoding="utf-8")
        essai.unlink()
        noter(VERT, f"Journaux inscriptibles ({dossier_logs})")
    except OSError as e:
        noter(ORANGE, "Journaux non inscriptibles",
              f"{dossier_logs} — un incident ne laissera aucune trace. {e}")

    return rendu()


def rendu():
    largeur = max(len(t) for _, t, _ in constats) + 2
    print()
    for niveau, titre, detail in constats:
        print(f"  {niveau} {titre.ljust(largeur)}{detail and '— ' + detail or ''}")
    bloquants = [t for n, t, _ in constats if n == ROUGE]
    attentions = [t for n, t, _ in constats if n == ORANGE]
    print()
    if bloquants:
        print(f"  {len(bloquants)} point(s) bloquant(s) : le service ne doit pas être "
              "ouvert aux postes en l'état.")
        return 1
    if attentions:
        print(f"  Prêt, avec {len(attentions)} point(s) d'attention ci-dessus.")
    else:
        print("  Prêt pour la mise en service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
