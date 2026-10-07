"""Export du stock des matières premières, une ligne par position.

Même format que l'inventaire des cabines (voir `export_inventaire`) : un CSV
qu'Excel ouvre d'un double-clic — point-virgule, UTF-8 avec BOM, dates en
jour/mois/année.

Une ligne par POSITION et non par code : c'est la forme d'un inventaire qu'on
recompte devant le rack. Un code présent à trois endroits donne trois lignes ;
le total par code se refait d'un tableau croisé. Un code sans stock, quand
l'écran les montre, donne une ligne sans position — il apparaît, à zéro.
"""
import csv
import io

from django.http import HttpResponse
from django.utils import timezone

COLONNES = [
    "Famille", "Code élément", "Désignation", "Fournisseur", "N° article",
    "Ancienne génération", "Emplacement", "Place", "Quantité",
    "Total du code", "Seuil d'alerte", "Sous le seuil",
]


def _lignes(articles):
    for a in articles:
        commun = [a["famille_libelle"], a["code"], a["designation"], a["fournisseur"],
                  a["numero"], "oui" if a["ancienne_generation"] else ""]
        fin = [a["en_stock"] or 0, a["seuil_reappro"] or "",
               "oui" if a.get("sous_seuil") else ""]
        if not a["positions"]:
            yield commun + ["", "", 0] + fin
        for p in a["positions"]:
            yield commun + [p["code_emplacement"], p["place"], p["quantite"]] + fin


def reponse(articles, prefixe="stock-mp"):
    """La réponse HTTP complète. Le stock MP tient en mémoire : quelques centaines de lignes."""
    tampon = io.StringIO()
    tampon.write("﻿")                 # BOM : Excel lit alors l'UTF-8 sans se tromper
    graveur = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    graveur.writerow(COLONNES)
    for ligne in _lignes(articles):
        graveur.writerow(ligne)
    nom = f"{prefixe}-{timezone.localdate():%Y-%m-%d}.csv"
    r = HttpResponse(tampon.getvalue(), content_type="text/csv; charset=utf-8")
    r["Content-Disposition"] = f'attachment; filename="{nom}"'
    r["Access-Control-Expose-Headers"] = "Content-Disposition"
    return r


__all__ = ["COLONNES", "reponse"]
