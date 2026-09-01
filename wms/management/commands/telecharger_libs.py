"""Télécharge une fois pour toutes les deux bibliothèques front du WMS.

Pourquoi : `app.html` les chargeait depuis deux CDN (jsdelivr, cdnjs). Sur un
réseau d'entrepôt fermé — ou simplement quand la ligne tombe — la caméra du
scanner et l'impression des étiquettes QR cessent de fonctionner, sans message
utile. Une fois cette commande passée, les fichiers sont servis par Django et
l'application n'a plus besoin d'internet.

    python manage.py telecharger_libs

À rejouer seulement pour changer de version (`--forcer`).
"""
import ssl
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

#: (nom local, URL, taille plancher attendue). La taille évite d'enregistrer une
#: page d'erreur du proxy (quelques centaines d'octets) à la place de la librairie.
LIBS = [
    ("html5-qrcode.min.js",
     "https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js",
     100_000),
    ("qrcode.min.js",
     "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js",
     10_000),
]


class Command(BaseCommand):
    help = ("Télécharge les bibliothèques JavaScript (lecture QR, génération QR) "
            "dans wms/static/app/vendor/, pour un fonctionnement sans internet.")

    def add_arguments(self, parseur):
        parseur.add_argument("--forcer", action="store_true",
                             help="retélécharge même si le fichier est déjà présent")

    def handle(self, *args, **options):
        dossier = Path(__file__).resolve().parents[2] / "static" / "app" / "vendor"
        dossier.mkdir(parents=True, exist_ok=True)
        contexte = ssl.create_default_context()
        ecrits = 0

        for nom, url, plancher in LIBS:
            cible = dossier / nom
            if cible.is_file() and not options["forcer"]:
                self.stdout.write(f"  déjà présent : {nom}")
                continue
            self.stdout.write(f"  téléchargement : {nom} …")
            try:
                requete = urllib.request.Request(url, headers={"User-Agent": "WMS-Structa"})
                with urllib.request.urlopen(requete, timeout=30, context=contexte) as r:
                    contenu = r.read()
            except Exception as e:
                raise CommandError(
                    f"Échec du téléchargement de {nom} ({e}).\n"
                    "Ce poste doit avoir accès à internet le temps de cette commande. "
                    "À défaut, copiez les deux fichiers à la main dans "
                    f"{dossier}."
                )
            if len(contenu) < plancher:
                raise CommandError(
                    f"{nom} ne fait que {len(contenu)} octets : ce n'est pas la "
                    "librairie attendue (proxy ou portail captif ?).")
            cible.write_bytes(contenu)
            ecrits += 1

        self.stdout.write(self.style.SUCCESS(
            f"OK — {ecrits} fichier(s) écrit(s) dans {dossier}. "
            "Redémarrez le serveur : l'application n'a plus besoin d'internet."))
