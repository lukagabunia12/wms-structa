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
    python outils/preparer_copie.py --avec-autorite # emporte l'autorité HTTPS

LE JOUR DE LA BASCULE, l'export doit être la DERNIÈRE écriture du poste : ce
qui serait saisi ensuite sur le PC ne partirait pas. Le script refuse donc
d'exporter tant que le WMS tourne sur ce poste (fermez sa fenêtre d'abord).

`--avec-autorite` emporte l'autorité de certification (`ac-structa.crt` et sa
clé), et elle seule : le serveur signe alors son propre certificat avec la même
autorité, et les téléphones qui l'ont déjà installée n'ont RIEN à refaire. La
clé de l'autorité permet de se faire passer pour n'importe quel site auprès de
ces téléphones : la copie doit voyager sur une clé chiffrée ou un partage
réservé, et être effacée une fois l'installation faite.
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from fnmatch import fnmatch
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
    "sauvegardes": "sauvegardes de ce poste : la base part par reprise/",
    "staticfiles": "fichiers statiques regroupés, refaits sur place",
}

#: Dossiers écartés par leur nom (rangements de Ranger-Le-Dossier.bat).
MOTIFS_DOSSIERS_EXCLUS = ["_archive_*", "WMS-Structa_a-copier_*"]

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
    # Les classeurs de production (clients, chantiers, montants) déposés à la
    # racine : ils s'importent par l'écran « Fichier de production », ils n'ont
    # pas à voyager. Ceux de docs/ partent.
    ("*.xlsx", "classeurs de production"),
    ("*.xlsm", "classeurs de production"),
]

#: Ce que `--avec-autorite` emporte de certificats/ — l'autorité seule. Le
#: certificat du serveur (wms.crt, wms.key) est refait sur place, pour ses
#: propres adresses.
AUTORITE = ["ac-structa.crt", "ac-structa.key", "ac-structa.mobileconfig"]

# Emporté malgré sa taille : tant que le port 8443 n'est pas ouvert, le tunnel
# est le SEUL chemin d'accès depuis les téléphones. Un serveur livré sans lui
# serait injoignable le matin du POC.
EMPORTES_MALGRE_LEUR_POIDS = ["cloudflared.exe"]

# Contrôle final : rien de tout cela ne doit exister dans la copie.
INTERDITS = [".env", "db.sqlite3", "certificats/ac-structa.key",
             "certificats/wms.key", ".venv"]


def dossier_exclu(nom):
    return nom in DOSSIERS_EXCLUS or any(fnmatch(nom, m) for m in MOTIFS_DOSSIERS_EXCLUS)


def exclus(nom, chemin_relatif):
    if dossier_exclu(nom):
        return True
    if fnmatch(nom.lower(), "*.xls[xm]") and chemin_relatif.parts[:1] == ("docs",):
        return False
    return any(fnmatch(nom, motif) for motif, _ in FICHIERS_EXCLUS)


def wms_en_marche():
    """Vrai si le WMS tourne sur ce poste (port HTTPS ou 8000 répond)."""
    sys.path.insert(0, str(RACINE / "outils"))
    import certificat_https as C
    for port in (C.port_https(), 8000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
    return False


def exporter_donnees(python):
    """Écrit reprise/ depuis la base active. Rend True si l'export a réussi.

    L'ancien dossier reprise/ est effacé AVANT : un export qui échouait laissait
    l'ancien en place, et le serveur importait sans broncher les données d'une
    répétition vieille de plusieurs semaines — son manifeste de comptages
    était cohérent avec lui-même.
    """
    print("  Export des données depuis la base active…")
    ancien = RACINE / "reprise"
    if ancien.exists():
        shutil.rmtree(ancien)
    r = subprocess.run([python, "manage.py", "reprise_sql", "exporter", "--vers", "reprise"],
                       cwd=str(RACINE), capture_output=True, text=True)
    if r.returncode != 0:
        print("\n  L'export a échoué : AUCUNE copie n'est faite.")
        for ligne in [x for x in r.stderr.splitlines() if x.strip()][-4:]:
            print("    " + ligne)
        print("\n  Pour une copie volontairement sans données (base vierge sur le")
        print("  serveur) : Preparer-Copie.bat --sans-donnees\n")
        return False
    for ligne in r.stdout.splitlines():
        if ligne.strip():
            print("    " + ligne.strip())
    return True


def copier(destination, avec_autorite=False, sans_donnees=False):
    """Copie l'arborescence en appliquant les exclusions. Rend le nombre de fichiers.

    `sans_donnees` écarte aussi `reprise/` : un export resté là d'une copie
    précédente serait parti dans une copie annoncée « sans données » — toute
    la base d'alors, mots de passe chiffrés et jetons compris, dans l'archive
    d'une simple mise à jour du code."""
    nombre = 0
    for dossier, sous_dossiers, fichiers in os.walk(RACINE):
        courant = Path(dossier)
        relatif = courant.relative_to(RACINE)
        # Élaguer sur place : os.walk ne descend pas dans ce qu'on retire de
        # `sous_dossiers`. Filtrer après coup copierait quand même .venv, qui
        # pèse plus que tout le reste du projet réuni.
        sous_dossiers[:] = [d for d in sous_dossiers if not dossier_exclu(d)
                            and not (sans_donnees and relatif == Path(".") and d == "reprise")]
        cible = destination / relatif
        cible.mkdir(parents=True, exist_ok=True)
        for fichier in fichiers:
            if exclus(fichier, relatif / fichier):
                continue
            shutil.copy2(courant / fichier, cible / fichier)
            nombre += 1
    if avec_autorite:
        cible = destination / "certificats"
        cible.mkdir(parents=True, exist_ok=True)
        for nom in AUTORITE:
            source = RACINE / "certificats" / nom
            if source.is_file():
                shutil.copy2(source, cible / nom)
                nombre += 1
    # Les dossiers devenus vides après filtrage n'apportent rien.
    for dossier, sous_dossiers, fichiers in list(os.walk(destination, topdown=False)):
        p = Path(dossier)
        if p != destination and not any(p.iterdir()):
            p.rmdir()
    return nombre


def controler(destination, avec_autorite=False):
    """Aucun fichier interdit ne doit avoir survécu. Rend la liste des fautifs."""
    permis = {"certificats/ac-structa.key"} if avec_autorite else set()
    fautifs = []
    for interdit in INTERDITS:
        if interdit not in permis and (destination / interdit).exists():
            fautifs.append(interdit)
    # Ceinture et bretelles : une recherche large, au cas où un motif serait
    # passé à côté d'un fichier place ailleurs qu'attendu.
    for chemin in destination.rglob("*"):
        relatif = chemin.relative_to(destination).as_posix()
        if relatif in permis:
            continue
        if chemin.is_file() and (chemin.name == ".env" or chemin.suffix in (".key", ".pem")):
            fautifs.append(relatif)
    return sorted(set(fautifs))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vers", default=None,
                   help="dossier de destination (défaut : à côté du projet)")
    p.add_argument("--sans-donnees", action="store_true", dest="sans_donnees",
                   help="ne pas exporter les données de la base")
    p.add_argument("--sans-zip", action="store_true", dest="sans_zip",
                   help="laisser le dossier, sans en faire une archive")
    p.add_argument("--avec-autorite", action="store_true", dest="avec_autorite",
                   help="emporter l'autorité de certification : les téléphones "
                        "n'auront rien à réinstaller")
    p.add_argument("--pendant-service", action="store_true", dest="pendant_service",
                   help="exporter même si le WMS tourne (répétition seulement)")
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
        if wms_en_marche() and not args.pendant_service:
            print("  Le WMS tourne sur ce poste : l'export doit être la DERNIÈRE écriture,")
            print("  sinon ce qui serait saisi après ne partirait pas sur le serveur.")
            print("  Fermez la fenêtre « WMS Structa - serveur », puis relancez.\n")
            return 1
        python = RACINE / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            python = RACINE / ".venv" / "bin" / "python"
        if not python.is_file():
            print("  .venv introuvable : impossible d'exporter les données.")
            print("  Pour une copie sans données : --sans-donnees\n")
            return 1
        if not exporter_donnees(str(python)):
            return 1

    nombre = copier(destination, avec_autorite=args.avec_autorite,
                    sans_donnees=args.sans_donnees)
    print(f"\n  {nombre} fichier(s) copié(s).")

    fautifs = controler(destination, avec_autorite=args.avec_autorite)
    if fautifs:
        print("\n  ANOMALIE : des fichiers qui ne devaient pas partir sont présents :")
        for f in fautifs:
            print("    " + f)
        print("\n  La copie est supprimée : elle exposerait des secrets.")
        shutil.rmtree(destination, ignore_errors=True)
        return 1
    if args.avec_autorite:
        print("  Contrôle : ni .env, ni clé du serveur. L'autorité de certification est")
        print("  emportée, AVEC SA CLÉ : les téléphones n'auront rien à réinstaller.")
    else:
        print("  Contrôle : ni .env, ni clé privée dans la copie.")
    if not args.sans_donnees:
        print("  La copie contient TOUTE la base (comptes, mots de passe chiffrés,")
        print("  jetons de connexion) : clé USB chiffrée ou partage réservé, et à")
        print("  effacer une fois le serveur installé.")

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
    if not args.sans_donnees:
        print("  À partir de maintenant, ne saisissez plus rien sur ce poste : ce")
        print("  serait perdu. Une fois le serveur en service, empêchez ce poste de")
        print("  redémarrer le WMS par habitude — ajoutez à son fichier .env :")
        print("      WMS_REMPLACE_PAR=https://wms.structa.fr:4443\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
