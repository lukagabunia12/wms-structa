"""Prépare (ou répare) le fichier `.env` avant le démarrage du WMS.

Volontairement sans Django : `config/settings.py` refuse maintenant de démarrer
en exploitation tant que la clé secrète est restée à sa valeur d'exemple. Ce
script doit donc pouvoir tourner AVANT que Django ne soit chargé.

Ce qu'il garantit :
- `.env` existe (copié depuis `.env.example` s'il manque) ;
- `DJANGO_SECRET_KEY` est une vraie clé aléatoire, jamais celle du dépôt ;
- `DJANGO_DEBUG` vaut False (le mode DEBUG expose la configuration complète —
  clé secrète comprise — sur la page d'erreur de n'importe quel visiteur).

Il n'écrase jamais un réglage déjà personnalisé : relançable sans risque.

    python outils/preparer_env.py            # prépare / répare
    python outils/preparer_env.py --verifier  # diagnostic seul, n'écrit rien
    python outils/preparer_env.py --poser WMS_NOMS=wms.structa.fr

`--poser` écrit un réglage (l'installateur s'en sert pour le nom de domaine et
le dossier des sauvegardes) ; une valeur vide retire la ligne. Il refuse les
valeurs que `.env` ne saurait pas relire telles quelles, plutôt que d'écrire un
réglage que Django comprendrait de travers.
"""
import re
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ENV = RACINE / ".env"
EXEMPLE = RACINE / ".env.example"
CLES_FAIBLES = {"changez-moi-en-production", "dev-insecure-change-me", ""}


def valeur(texte, cle):
    m = re.search(rf"(?m)^{re.escape(cle)}=(.*)$", texte)
    return m.group(1).strip() if m else None


def poser(texte, cle, val):
    """Remplace la ligne si elle existe, l'ajoute sinon."""
    if re.search(rf"(?m)^{re.escape(cle)}=", texte):
        # Une fonction et non une chaîne de remplacement : une valeur qui
        # contient « \\ » (un partage réseau, un chemin Windows) serait sinon
        # interprétée par re.sub.
        return re.sub(rf"(?m)^{re.escape(cle)}=.*$", lambda _m: f"{cle}={val}", texte)
    return texte.rstrip("\n") + f"\n{cle}={val}\n"


def retirer(texte, cle):
    return re.sub(rf"(?m)^{re.escape(cle)}=.*\n?", "", texte)


def probleme_valeur(valeur):
    """Pourquoi cette valeur ne peut pas être écrite telle quelle dans `.env`,
    ou None. python-dotenv — qui relit `.env` pour Django — coupe une valeur à
    « espace + # » (commentaire), ôte les espaces des bords et les guillemets,
    et remplace « ${…} » par une variable d'environnement."""
    if valeur != valeur.strip():
        return "commence ou finit par une espace"
    if re.search(r"\s#", valeur):
        return "contient « # » précédé d'une espace (lu comme un commentaire)"
    if valeur[:1] in ("'", '"'):
        return "commence par un guillemet"
    if "${" in valeur:
        return "contient « ${ »"
    if "\n" in valeur or "\r" in valeur:
        return "contient un retour à la ligne"
    return None


def sauvegarder_env():
    """Copie datée de `.env` avant écriture — les dix dernières sont gardées,
    comme le fait outils/basculer_base.py."""
    if not ENV.is_file():
        return None
    copie = ENV.parent / f".env.avant-{datetime.now():%Y%m%d-%H%M%S-%f}"
    shutil.copy2(ENV, copie)
    for vieille in sorted(ENV.parent.glob(".env.avant-*"))[:-10]:
        vieille.unlink(missing_ok=True)
    return copie


def poser_reglages(reglages):
    """Écrit {CLE: valeur} dans `.env` (valeur vide : ligne retirée). Rend la
    liste des refus — vide si tout est écrit."""
    erreurs = []
    for cle, val in reglages.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", cle):
            erreurs.append(f"Nom de réglage invalide : {cle}")
            continue
        motif = probleme_valeur(val) if val else None
        if motif:
            erreurs.append(f"{cle} : la valeur {motif}. Choisissez-en une autre.")
    if erreurs:
        return erreurs
    if not ENV.exists():
        main()
    texte = ENV.read_text(encoding="utf-8")
    nouveau = texte
    for cle, val in reglages.items():
        nouveau = poser(nouveau, cle, val) if val else retirer(nouveau, cle)
    if nouveau != texte:
        sauvegarder_env()
        ENV.write_text(nouveau, encoding="utf-8")
    return []


def main(verifier_seulement=False):
    if not ENV.exists():
        if verifier_seulement:
            print("MANQUANT : .env n'existe pas.")
            return 1
        ENV.write_text(EXEMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print("  .env créé depuis .env.example")

    texte = ENV.read_text(encoding="utf-8")
    avant = texte
    remarques = []

    cle = valeur(texte, "DJANGO_SECRET_KEY")
    if cle is None or cle in CLES_FAIBLES or len(cle) < 40:
        remarques.append("clé secrète faible ou d'exemple")
        texte = poser(texte, "DJANGO_SECRET_KEY", secrets.token_urlsafe(64))

    debug = (valeur(texte, "DJANGO_DEBUG") or "").strip().lower()
    if debug in ("true", "1", "vrai", "oui", "yes", "on"):
        remarques.append("DJANGO_DEBUG était à True")
        texte = poser(texte, "DJANGO_DEBUG", "False")

    if verifier_seulement:
        if remarques:
            print("À CORRIGER : " + " ; ".join(remarques))
            print("Lancez : python outils/preparer_env.py")
            return 1
        print("OK — .env est correctement configuré pour l'exploitation.")
        return 0

    if texte != avant:
        ENV.write_text(texte, encoding="utf-8")
        print("  .env corrigé : " + " ; ".join(remarques))
    else:
        print("  .env déjà correct")
    return 0


def principal(argv):
    if "--poser" in argv:
        reglages = {}
        for i, arg in enumerate(argv):
            if arg == "--poser" and i + 1 < len(argv):
                cle, egal, val = argv[i + 1].partition("=")
                if not egal:
                    print(f"--poser attend CLE=VALEUR, pas « {argv[i + 1]} »")
                    return 2
                reglages[cle.strip()] = val
        erreurs = poser_reglages(reglages)
        for e in erreurs:
            print("  REFUS : " + e)
        if not erreurs:
            for cle, val in reglages.items():
                print(f"  .env : {cle}={val}" if val else f"  .env : {cle} retiré")
        return 1 if erreurs else 0
    return main("--verifier" in argv)


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
