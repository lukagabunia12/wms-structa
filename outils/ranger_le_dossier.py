# -*- coding: utf-8 -*-
"""Range le dossier du projet : archive ce qui a servi, efface ce qui se refait.

Le dossier accumule, et c'est normal : des versions précédentes de documents,
des captures d'écran de recette, un paquet serveur fabriqué il y a un mois, des
roues Python remplacées par les suivantes. Rien de tout cela n'est faux — c'est
simplement du passé, et il finit par cacher le présent.

**Cet outil ne supprime rien d'irremplaçable.** Il DÉPLACE dans un dossier
d'archive daté, où tout reste lisible et d'où tout se ramène d'un glisser. Il ne
supprime que ce que Python refabrique tout seul (`__pycache__`).

Deux choses qu'il ne touche jamais, et il faut savoir pourquoi :

- `db.sqlite3` : c'est l'ancienne base, remplacée par PostgreSQL, mais c'est
  aussi le filet de `Revenir-SQLite.bat`. Tant que ce bouton existe, le fichier
  a une raison d'être là ;
- `certificats/` et `.env` : ils portent des secrets, ils ne bougent pas.

    python outils/ranger_le_dossier.py            (montre le plan, ne fait rien)
    python outils/ranger_le_dossier.py --ranger   (déplace, après confirmation)
"""
import shutil
import sys
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

#: Ce qui part à l'archive : (chemin, pourquoi). Le « pourquoi » est affiché —
#: on ne range pas un dossier sur la foi d'une liste qu'on ne comprend pas.
#:
#: La liste est EXPLICITE, sans jokers. Un `*.png` balaierait aussi les captures
#: dont la documentation se sert, et personne ne s'en apercevrait avant
#: d'ouvrir un guide troué.
A_ARCHIVER = [
    ("docs/_a_supprimer",
     "versions précédentes des documents PRO (214, 215, 216, 218, et les "
     "premières versions de 220, 225, 226) — remplacées par celles de docs/"),
    ("docs/Archive",
     "une version antérieure du PRO225, remplacée"),
    ("Claude outputs",
     "captures d'écran et fichiers de travail produits pendant les mises au "
     "point — la documentation a les siennes dans docs/captures/"),
    ("WMS-Structa_serveur.zip",
     "paquet du poste serveur fabriqué le 25 août ; Preparer-Copie.bat en "
     "refait un à jour en une minute"),
    ("reprise",
     "export de reprise du jour de la bascule vers PostgreSQL (141 objets, "
     "contre plusieurs milliers aujourd'hui) — un point de retour périmé"),
    ("paquets/psycopg-3.3.4-py3-none-any.whl",
     "remplacée par la 3.3.5, présente à côté"),
    ("paquets/psycopg_binary-3.3.4-cp314-cp314-win_amd64.whl",
     "remplacée par la 3.3.5, présente à côté"),
    # Le volet « articles », retiré en septembre 2026. Plus rien n'importe ces
    # fichiers, mais laissés en place, les trois tests seraient relus par
    # `manage.py test` — et échoueraient sur des tables qui n'existent plus.
    ("wms/services.py",
     "moteur de stock du volet articles, retiré — remplacé par services_emplacements.py"),
    ("wms/management/commands/importer_maquette.py",
     "import de la maquette d'origine : un seul usage, fait en juillet"),
    ("wms/management/commands/reinitialiser.py",
     "remise à zéro sans sauvegarde sur PostgreSQL — remplacée par « Repartir de "
     "zéro » dans l'administration, qui sauvegarde d'abord"),
    ("wms/tests/test_import.py", "tests de l'import de la maquette, retiré"),
    ("wms/tests/test_mouvements.py", "tests du moteur de stock, retiré"),
    ("wms/tests/test_reinitialiser.py", "tests de la commande reinitialiser, retirée"),
    ("docs/inventaire-maquette-wms.md",
     "inventaire de la maquette Node.js d'origine et de son volet articles"),
    ("docs/CE-QUI-CHANGE_2026-09-09.md",
     "notes de la livraison du 9 septembre : elles décrivent un onglet « Repartir "
     "de zéro » qui n'existe plus"),
]

#: Ce qui s'efface vraiment : Python le refabrique au premier lancement.
A_EFFACER = ["__pycache__"]

#: Ce qu'on ne touche pas, et la raison — affichée elle aussi, pour que
#: personne ne « finisse le ménage » à la main en croyant bien faire.
INTOUCHABLES = [
    ("db.sqlite3", "ancienne base, mais c'est le filet de Revenir-SQLite.bat"),
    ("certificats/", "clé privée de l'autorité : elle ne quitte pas la machine"),
    (".env", "mots de passe et clé secrète du serveur"),
    ("cloudflared.exe", "utilisé par Demarrer-WMS-Tunnel.bat"),
    ("paquets/ (le reste)", "installation hors ligne du serveur"),
]


def taille(chemin):
    if chemin.is_file():
        return chemin.stat().st_size
    return sum(f.stat().st_size for f in chemin.rglob("*") if f.is_file())


def lisible(octets):
    for unite in ("o", "Ko", "Mo", "Go"):
        if octets < 1024 or unite == "Go":
            return f"{octets:.0f} {unite}" if unite == "o" else f"{octets:.1f} {unite}"
        octets /= 1024


def caches():
    """Les `__pycache__` du projet, sauf ceux de l'environnement virtuel."""
    return [d for d in RACINE.rglob("__pycache__")
            if d.is_dir() and ".venv" not in d.parts]


def main():
    ranger = "--ranger" in sys.argv
    archive = RACINE / f"_archive_{date.today():%Y-%m-%d}"

    print("\n  " + "-" * 66)
    print("   Rangement du dossier WMS Structa")
    print("  " + "-" * 66)
    print(f"   Dossier : {RACINE}")
    print(f"   Archive : {archive.name}{'' if ranger else '  (rien ne sera déplacé)'}\n")

    trouves, total = [], 0
    for relatif, pourquoi in A_ARCHIVER:
        source = RACINE / relatif
        if not source.exists():
            continue
        poids = taille(source)
        total += poids
        trouves.append((source, relatif, poids))
        print(f"   → {relatif}")
        print(f"     {lisible(poids):>9}  {pourquoi}")

    vieux_caches = caches()
    poids_caches = sum(taille(d) for d in vieux_caches)
    if vieux_caches:
        print(f"\n   × {len(vieux_caches)} dossiers __pycache__ ({lisible(poids_caches)})")
        print("     effacés : Python les refabrique au premier lancement")

    if not trouves and not vieux_caches:
        print("   Rien à ranger : le dossier est déjà propre.\n")
        return 0

    print(f"\n   Total libéré : {lisible(total + poids_caches)}")
    print("\n   Laissés en place, et pourquoi :")
    for quoi, pourquoi in INTOUCHABLES:
        print(f"     · {quoi:22} {pourquoi}")

    if not ranger:
        print("\n   Rien n'a été déplacé. Pour ranger pour de bon :")
        print("     python outils/ranger_le_dossier.py --ranger\n")
        return 0

    reponse = input("\n   Déplacer tout cela dans l'archive ? (oui/non) ").strip().lower()
    if reponse not in ("oui", "o", "yes", "y"):
        print("   Rien n'a été déplacé.\n")
        return 0

    archive.mkdir(exist_ok=True)
    for source, relatif, _ in trouves:
        cible = archive / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        # Un rangement relancé le même jour ne doit pas écraser le précédent :
        # on numérote plutôt que de perdre ce qui était déjà là.
        if cible.exists():
            suffixe = 2
            while (archive / f"{relatif}-{suffixe}").exists():
                suffixe += 1
            cible = archive / f"{relatif}-{suffixe}"
        shutil.move(str(source), str(cible))
        print(f"   déplacé : {relatif}")

    for dossier in vieux_caches:
        shutil.rmtree(dossier, ignore_errors=True)
    if vieux_caches:
        print(f"   effacé : {len(vieux_caches)} dossiers __pycache__")

    print(f"\n   Terminé. Tout est dans {archive.name}, rien n'est perdu.")
    print("   Vérifiez que l'application démarre, puis supprimez ce dossier")
    print("   quand vous serez tranquille.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
