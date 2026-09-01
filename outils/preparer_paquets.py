"""Constitue le dossier `paquets/` : toutes les dépendances, en local.

À lancer **une fois, sur un poste qui a accès à internet** — typiquement le
poste de développement. Le dossier produit voyage avec le projet ; le poste
serveur installe alors sans réseau du tout.

Pourquoi ce détour plutôt qu'un `pip install` sur le serveur : un réseau
d'entreprise filtre souvent PyPI. On ne s'en aperçoit qu'au moment de
l'installation, sur place, sans solution de repli. Le dossier `paquets/`
supprime la question.

    python outils/preparer_paquets.py            # dépendances de base
    python outils/preparer_paquets.py --avec-ocr  # + reconnaissance de texte

Contrainte à connaître : une roue Python porte la version de l'interpréteur
dans son nom. Le dossier est donc lié au couple (version de Python, Windows
64 bits) du poste qui l'a fabriqué. `version.txt` garde cette empreinte, et
l'installateur refuse de continuer si elle ne correspond pas — plutôt que de
laisser pip répondre « no matching distribution », message qui envoie chercher
un dossier vide.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PAQUETS = RACINE / "paquets"
MARQUE = PAQUETS / "version.txt"


def version_python():
    return f"{sys.version_info[0]}.{sys.version_info[1]}"


def telecharger(fichier_requirements, dossier):
    """Télécharge un jeu de dépendances, et rend True si tout s'est bien passé."""
    commande = [sys.executable, "-m", "pip", "download",
                "-r", str(fichier_requirements), "-d", str(dossier)]
    print(f"    {fichier_requirements.name} …", flush=True)
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if resultat.returncode != 0:
        derniere = [x for x in resultat.stderr.splitlines() if x.strip()]
        print("\n  Échec du téléchargement :")
        for ligne in derniere[-6:]:
            print("    " + ligne)
        return False
    return True


def poids(dossier):
    total = sum(f.stat().st_size for f in dossier.glob("*") if f.is_file())
    return total / (1024 * 1024)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--avec-ocr", action="store_true", dest="avec_ocr",
                   help="ajoute la reconnaissance de texte (~100 Mo de plus)")
    p.add_argument("--refaire", action="store_true",
                   help="vide le dossier avant de le reconstituer")
    args = p.parse_args()

    if args.refaire and PAQUETS.exists():
        shutil.rmtree(PAQUETS)
        print("  Dossier paquets/ vidé.")
    PAQUETS.mkdir(exist_ok=True)

    print(f"\n  Constitution de paquets/ pour Python {version_python()} "
          f"({sys.platform})\n")

    jeux = [RACINE / "requirements.txt"]
    if args.avec_ocr:
        jeux.append(RACINE / "requirements-ocr.txt")

    for fichier in jeux:
        if not fichier.is_file():
            print(f"  Introuvable : {fichier.name} — ignoré.")
            continue
        if not telecharger(fichier, PAQUETS):
            print("\n  Rien n'est garanti complet : corrigez, puis relancez.")
            print("  Ce poste a-t-il bien accès à internet ?\n")
            return 1

    # pip lui-même : sans sa roue, `pip install --upgrade pip --no-index`
    # échoue sur le poste serveur et fait échouer toute l'installation pour
    # une mise à jour qui n'était même pas nécessaire.
    subprocess.run([sys.executable, "-m", "pip", "download", "pip",
                    "-d", str(PAQUETS)], capture_output=True, text=True)

    MARQUE.write_text(version_python() + "\n", encoding="utf-8")

    roues = sorted(PAQUETS.glob("*.whl"))
    archives = sorted(PAQUETS.glob("*.tar.gz"))
    print(f"\n  {len(roues)} roue(s) et {len(archives)} archive(s) — "
          f"{poids(PAQUETS):.0f} Mo dans paquets/")
    if archives:
        print("\n  Attention : les fichiers .tar.gz ne sont pas des roues toutes")
        print("  faites — pip devra les compiler sur le poste serveur, ce qui")
        print("  demande des outils de compilation. Concernés :")
        for a in archives[:5]:
            print("    " + a.name)
    print(f"\n  Ce dossier ne vaut que pour Python {version_python()} sous "
          f"Windows 64 bits.")
    print("  Il part avec le projet : Preparer-Copie.bat l'emporte.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
