"""Fabrique le dossier à copier sur le poste serveur.

Copier le projet « tel quel » sur un autre poste ne marche pas, et échoue de
façon trompeuse : l'application démarre, puis se comporte mal.

- `.venv` contient des chemins absolus et des binaires du poste d'origine ;
- `.env` porte la clé secrète et le mot de passe de la base. Deux postes qui
  partagent une clé secrète, c'est une session forgée sur l'un qui vaut sur
  l'autre ;
- `certificats/` est émis pour les adresses IP du poste d'origine : ailleurs,
  il ne prouve rien ;
- `db.sqlite3` n'est plus la base d'exploitation depuis le passage sur
  PostgreSQL. L'emporter, c'est risquer de travailler des semaines dans une
  copie morte.

Ce script produit donc un dossier qui ne contient que ce qui doit voyager, et
vérifie ensuite qu'aucun fichier interdit ne s'y trouve.

    python outils/preparer_copie.py                 # dossier + archive .zip
    python outils/preparer_copie.py --sans-donnees  # sans exporter les données
    python outils/preparer_copie.py --sans-zip
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Dossiers entiers qui ne partent jamais, et la raison de chacun.
DOSSIERS_EXCLUS = {
    ".venv": "environnement Python du poste d'origine (chemins absolus)",
    ".git": "historique de version, inutile au serveur",
    "__pycache__": "code compilé, refait tout seul",
    "certificats": "certificat émis pour les adresses IP de l'autre poste",
    "logs": "journaux du poste d'origine",
    "_a_supprimer": "mise au rebut",
    "_sauvegarde-avant-maj-claude": "ancienne sauvegarde",
    "node_modules": "dépendances JavaScript, non utilisées ici",
}

# Motifs de fichiers exclus.
FICHIERS_EXCLUS = [
    (".env", "clé secrète et mot de passe de la base — refaits à l'installation"),
    (".env.avant-*", "sauvegardes de .env"),
    ("db.sqlite3", "ancienne base : les données partent par reprise/"),
    ("db.sqlite3.*", "copies de l'ancienne base"),
    ("*.pyc", "code compilé"),
    ("*.log", "journaux"),
    ("*.tgz", "archives de travail"),
    # Les archives des copies precedentes vivent a la racine du projet. Sans
    # cette ligne, chaque copie emporte la precedente : la taille double a
    # chaque tour.
    ("*.zip", "archives des copies precedentes"),
]

# Emporté malgré sa taille : tant que le port 8443 n'est pas ouvert, le tunnel
# est le SEUL chemin d'accès depuis les téléphones. Un serveur livré sans lui
# serait injoignable le matin du POC.
EMPORTES_MALGRE_LEUR_POIDS = ["cloudflared.exe"]

# Contrôle final : rien de tout cela ne doit exister dans la copie.
INTERDITS = [".env", "db.sqlite3", "certificats/ac-structa.key",
             "certificats/wms.key", ".venv"]


def exclus(nom, chemin_relatif):
    if nom in DOSSIERS_EXCLUS:
        return True
    from fnmatch import fnmatch
    return any(fnmatch(nom, motif) for motif, _ in FICHIERS_EXCLUS)


def exporter_donnees(python):
    """Écrit reprise/ depuis la base active. Rend True si des données suivent."""
    print("  Export des données depuis la base active…")
    r = subprocess.run([python, "manage.py", "reprise_sql", "exporter", "--vers", "reprise"],
                       cwd=str(RACINE), capture_output=True, text=True)
    if r.returncode != 0:
        print("\n  L'export a échoué — la copie se fera SANS données.")
        for ligne in [x for x in r.stderr.splitlines() if x.strip()][-4:]:
            print("    " + ligne)
        print("  Le serveur démarrera alors sur une base vierge.\n")
        return False
    for ligne in r.stdout.splitlines():
        if ligne.strip():
            print("    " + ligne.strip())
    return True


def copier(destination):
    """Copie l'arborescence en appliquant les exclusions. Rend le nombre de fichiers."""
    nombre = 0
    for dossier, sous_dossiers, fichiers in os.walk(RACINE):
        courant = Path(dossier)
        relatif = courant.relative_to(RACINE)
        # Élaguer sur place : os.walk ne descend pas dans ce qu'on retire de
        # `sous_dossiers`. Filtrer après coup copierait quand même .venv, qui
        # pèse plus que tout le reste du projet réuni.
        sous_dossiers[:] = [d for d in sous_dossiers if d not in DOSSIERS_EXCLUS]
        cible = destination / relatif
        cible.mkdir(parents=True, exist_ok=True)
        for fichier in fichiers:
            if exclus(fichier, relatif / fichier):
                continue
            shutil.copy2(courant / fichier, cible / fichier)
            nombre += 1
    # Les dossiers devenus vides après filtrage n'apportent rien.
    for dossier, sous_dossiers, fichiers in list(os.walk(destination, topdown=False)):
        p = Path(dossier)
        if p != destination and not any(p.iterdir()):
            p.rmdir()
    return nombre


def controler(destination):
    """Aucun fichier interdit ne doit avoir survécu. Rend la liste des fautifs."""
    fautifs = []
    for interdit in INTERDITS:
        if (destination / interdit).exists():
            fautifs.append(interdit)
    # Ceinture et bretelles : une recherche large, au cas où un motif serait
    # passé à côté d'un fichier place ailleurs qu'attendu.
    for chemin in destination.rglob("*"):
        if chemin.is_file() and (chemin.name == ".env" or chemin.suffix in (".key", ".pem")):
            fautifs.append(str(chemin.relative_to(destination)))
    return sorted(set(fautifs))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vers", default=None,
                   help="dossier de destination (défaut : à côté du projet)")
    p.add_argument("--sans-donnees", action="store_true", dest="sans_donnees",
                   help="ne pas exporter les données de la base")
    p.add_argument("--sans-zip", action="store_true", dest="sans_zip",
                   help="laisser le dossier, sans en faire une archive")
    args = p.parse_args()

    horodatage = datetime.now().strftime("%Y%m%d-%H%M")
    destination = Path(args.vers) if args.vers else \
        RACINE.parent / f"WMS-Structa_a-copier_{horodatage}"
    if destination.exists():
        sys.exit(f"{destination} existe déjà. Choisissez un autre nom avec --vers.")
    # Une destination placée DANS le projet ferait copier la copie en train de
    # se faire : os.walk descendrait dedans, et le dossier grossirait jusqu'à
    # saturer le disque.
    if RACINE == destination or RACINE in destination.resolve().parents:
        sys.exit(f"{destination} est à l'intérieur du projet.\n"
                 "Choisissez un dossier situé ailleurs : la copie s'y recopierait "
                 "elle-même sans fin.")

    print("\n  Préparation de la copie pour le poste serveur")
    print(f"  Source      : {RACINE}")
    print(f"  Destination : {destination}\n")

    if not args.sans_donnees:
        python = RACINE / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            python = RACINE / ".venv" / "bin" / "python"
        if python.is_file():
            exporter_donnees(str(python))
        else:
            print("  .venv introuvable : copie sans export de données.\n")

    nombre = copier(destination)
    print(f"\n  {nombre} fichier(s) copié(s).")

    fautifs = controler(destination)
    if fautifs:
        print("\n  ANOMALIE : des fichiers qui ne devaient pas partir sont présents :")
        for f in fautifs:
            print("    " + f)
        print("\n  La copie est supprimée : elle exposerait des secrets.")
        shutil.rmtree(destination, ignore_errors=True)
        return 1
    print("  Contrôle : aucun secret dans la copie (ni .env, ni clé privée).")

    tunnel = destination / "cloudflared.exe"
    if tunnel.is_file():
        print(f"  cloudflared.exe emporté ({tunnel.stat().st_size / (1024*1024):.0f} Mo) : "
              f"accès par tunnel possible sans ouvrir le pare-feu.")
    else:
        print("  cloudflared.exe absent : sans lui, le serveur n'est joignable "
              "qu'une fois le port 8443 ouvert.")

    if (destination / "paquets").is_dir():
        roues = len(list((destination / "paquets").glob("*.whl")))
        print(f"  Dossier paquets/ emporté ({roues} roues) : "
              f"le serveur installera sans internet.")
    else:
        print("  Pas de dossier paquets/ : le serveur devra atteindre internet.")
        print("  Pour l'éviter : python outils/preparer_paquets.py, puis relancer ici.")

    if not args.sans_zip:
        print("\n  Création de l'archive…")
        archive = shutil.make_archive(str(destination), "zip",
                                      root_dir=str(destination.parent),
                                      base_dir=destination.name)
        taille = Path(archive).stat().st_size / (1024 * 1024)
        # « 0 Mo » sur une archive de 400 ko donne l'impression d'un échec.
        mesure = f"{taille:.0f} Mo" if taille >= 10 else f"{taille:.1f} Mo"
        print(f"  Archive : {archive}  ({mesure})")

    print("\n  Sur le poste serveur :")
    print("   1. installer Python et PostgreSQL (voir docs/guide-serveur.md)")
    print("   2. copier ce dossier où il doit rester")
    print("   3. double-cliquer Installer-WMS.bat\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
