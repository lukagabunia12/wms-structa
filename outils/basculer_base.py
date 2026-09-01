"""Bascule le WMS entre SQLite et PostgreSQL, dans les deux sens.

Sert à répéter le passage sur serveur **depuis son propre poste** : on installe
PostgreSQL en local, on bascule, on éprouve l'application sur les vraies données,
et on revient à SQLite si quelque chose cloche. Sans cette marche arrière, on
n'essaie pas — on subit.

    python outils/basculer_base.py etat
    python outils/basculer_base.py postgresql --mot-de-passe SECRET
    set WMS_DB_PASSWORD=SECRET & python outils/basculer_base.py postgresql
    python outils/basculer_base.py sqlite

Les réglages PostgreSQL ne sont jamais perdus : en repassant sur SQLite ils sont
simplement mis en commentaire dans `.env`, prêts à resservir.

`.env` est sauvegardé avant chaque écriture — c'est le fichier qui décide où
partent les écritures de l'entrepôt, il ne se modifie pas à l'aveugle.
"""
import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ENV = RACINE / ".env"
sys.path.insert(0, str(RACINE))

DEBUT = "# --- Base de données (géré par outils/basculer_base.py) ---"
FIN = "# --- fin base de données ---"
CLES = ["DJANGO_DB_ENGINE", "DJANGO_DB_NAME", "DJANGO_DB_USER",
        "DJANGO_DB_PASSWORD", "DJANGO_DB_HOST", "DJANGO_DB_PORT"]


def lire():
    if not ENV.is_file():
        sys.exit("`.env` est absent. Lancez d'abord : python outils/preparer_env.py")
    return ENV.read_text(encoding="utf-8")


def sauvegarder():
    """Copie datée de `.env`, en gardant les dix dernières.

    `with_suffix()` produisait « .env.env.avant-… » sur un fichier nommé `.env`
    (dont le nom est entièrement un suffixe), et deux bascules dans la même
    seconde écrasaient la même copie : le nom est donc construit à la main, avec
    les millisecondes.
    """
    copie = ENV.parent / f".env.avant-{datetime.now():%Y%m%d-%H%M%S-%f}"
    shutil.copy2(ENV, copie)
    anciennes = sorted(ENV.parent.glob(".env.avant-*"))
    for vieille in anciennes[:-10]:
        vieille.unlink(missing_ok=True)
    return copie


def reglages_connus(texte):
    """Réglages PostgreSQL présents dans `.env`, actifs ou en commentaire."""
    trouves = {}
    for cle in CLES:
        m = re.search(rf"(?m)^\s*#?\s*({re.escape(cle)})=(.*)$", texte)
        if m and m.group(2).strip():
            trouves[cle] = m.group(2).strip()
    return trouves


def sans_bloc(texte):
    """Retire le bloc géré et toute ligne DJANGO_DB_* qui traînerait ailleurs."""
    texte = re.sub(rf"{re.escape(DEBUT)}.*?{re.escape(FIN)}\n?", "", texte, flags=re.S)
    for cle in CLES:
        texte = re.sub(rf"(?m)^\s*#?\s*{re.escape(cle)}=.*\n?", "", texte)
    return texte.rstrip("\n") + "\n"


def ecrire_bloc(texte, valeurs, actif):
    diese = "" if actif else "#"
    lignes = [DEBUT,
              f"# Profil actif : {'PostgreSQL' if actif else 'SQLite (fichier db.sqlite3)'}"]
    if not actif:
        lignes.append("# Réglages PostgreSQL conservés, prêts à resservir :")
    lignes += [f"{diese}{cle}={valeurs[cle]}" for cle in CLES if cle in valeurs]
    lignes.append(FIN)
    return sans_bloc(texte) + "\n" + "\n".join(lignes) + "\n"


def profil_actif(texte):
    return "postgresql" if re.search(r"(?m)^\s*DJANGO_DB_ENGINE=.*postgresql", texte) \
        else "sqlite"


def etat(_=None):
    texte = lire()
    profil = profil_actif(texte)
    print(f"\n  Profil actif : {'PostgreSQL' if profil == 'postgresql' else 'SQLite'}")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django
        django.setup()
        from django.db import connection
        reglages = connection.settings_dict
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
            curseur.fetchone()
        cible = reglages.get("NAME") if connection.vendor != "sqlite" else reglages["NAME"]
        print(f"  Moteur       : {connection.vendor}")
        print(f"  Base         : {cible}"
              + (f" sur {reglages['HOST']}:{reglages['PORT'] or 5432}"
                 if connection.vendor != "sqlite" else ""))
        # Le compte de lignes est le seul repère fiable : deux bases peuvent
        # répondre toutes les deux, une seule contient le travail du jour.
        from wms.models import Cabine, Emplacement, MouvementCabine
        print(f"  Contenu      : {Emplacement.objects.count()} emplacements · "
              f"{Cabine.objects.count()} cabines · "
              f"{MouvementCabine.objects.count()} événements au journal\n")
    except Exception as e:
        print(f"  ÉTAT        : base injoignable — {str(e).splitlines()[0]}\n")
        return 1
    return 0


def vers_postgresql(args):
    texte = lire()
    valeurs = reglages_connus(texte)
    valeurs["DJANGO_DB_ENGINE"] = "django.db.backends.postgresql"
    for cle, valeur in (("DJANGO_DB_NAME", args.base), ("DJANGO_DB_USER", args.utilisateur),
                        ("DJANGO_DB_PASSWORD", args.mot_de_passe),
                        ("DJANGO_DB_HOST", args.hote), ("DJANGO_DB_PORT", str(args.port))):
        if valeur:
            valeurs[cle] = valeur
    manquants = [c for c in ("DJANGO_DB_NAME", "DJANGO_DB_USER", "DJANGO_DB_PASSWORD")
                 if not valeurs.get(c)]
    if manquants:
        sys.exit("Réglages manquants : " + ", ".join(manquants)
                 + "\nExemple : python outils/basculer_base.py postgresql "
                   "--base wms --utilisateur wms --mot-de-passe SECRET")

    try:
        import psycopg  # noqa: F401
    except ImportError:
        sys.exit("Le pilote PostgreSQL n'est pas installé.\n"
                 "  pip install -r requirements.txt")

    copie = sauvegarder()
    ENV.write_text(ecrire_bloc(texte, valeurs, actif=True), encoding="utf-8")
    print(f"\n  .env sauvegardé : {copie.name}")
    print(f"  Bascule sur PostgreSQL — base « {valeurs['DJANGO_DB_NAME']} » "
          f"sur {valeurs.get('DJANGO_DB_HOST', '127.0.0.1')}")
    print("  (le mot de passe est écrit dans .env, il n'est pas affiché ici)\n")
    print("  Suite :  python manage.py migrate")
    print("           python manage.py reprise_sql importer --depuis reprise\n")
    return 0


def vers_sqlite(_=None):
    texte = lire()
    valeurs = reglages_connus(texte)
    copie = sauvegarder()
    ENV.write_text(ecrire_bloc(texte, valeurs, actif=False), encoding="utf-8")
    print(f"\n  .env sauvegardé : {copie.name}")
    print("  Retour sur SQLite — fichier db.sqlite3, tel que vous l'aviez laissé.")
    if valeurs:
        print("  Les réglages PostgreSQL restent en commentaire dans .env.\n")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = p.add_subparsers(dest="action", required=True)
    sp.add_parser("etat", help="quelle base est active, et ce qu'elle contient")
    sp.add_parser("sqlite", help="revenir au fichier db.sqlite3")
    pg = sp.add_parser("postgresql", help="basculer sur PostgreSQL")
    pg.add_argument("--base", default="wms")
    pg.add_argument("--utilisateur", default="wms")
    # Le mot de passe peut venir de la variable d'environnement WMS_DB_PASSWORD
    # plutôt que de la ligne de commande : les arguments d'un processus sont
    # lisibles par n'importe quel compte du poste, l'environnement d'un
    # processus ne l'est pas. L'installateur passe par la variable.
    pg.add_argument("--mot-de-passe", dest="mot_de_passe",
                    default=os.environ.get("WMS_DB_PASSWORD", ""))
    pg.add_argument("--hote", default="127.0.0.1")
    pg.add_argument("--port", default="5432")
    args = p.parse_args()
    return {"etat": etat, "sqlite": vers_sqlite, "postgresql": vers_postgresql}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
