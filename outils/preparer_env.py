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
"""
import re
import secrets
import sys
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
        return re.sub(rf"(?m)^{re.escape(cle)}=.*$", f"{cle}={val}", texte)
    return texte.rstrip("\n") + f"\n{cle}={val}\n"


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


if __name__ == "__main__":
    sys.exit(main("--verifier" in sys.argv))
