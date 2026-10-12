"""Export de l'inventaire des cabines, une ligne par emplacement occupé.

Format retenu : un CSV qu'Excel ouvre d'un double-clic, sans réglage. Séparateur
point-virgule — ce qu'attend un Excel configuré en français ; encodage UTF-8
avec BOM — sans lui, Excel affiche « CabÃ¯ne » ; dates en jour/mois/année.

Pourquoi pas un `.xlsx` : il faudrait ajouter `openpyxl` aux dépendances, donc au
paquet d'installation hors ligne du poste serveur, pour un fichier qu'Excel
ouvre déjà. Pourquoi pas du SQL : les données SONT dans PostgreSQL — qui sait
écrire une requête n'a pas besoin de passer par l'application, et qui ne sait
pas n'en fera rien.

Une cabine posée à DEUX endroits donne DEUX lignes : c'est un inventaire par
emplacement, pas par cabine. Une cabine rangée nulle part en donne une, colonnes
de position vides — sinon elle disparaîtrait de l'inventaire, alors que c'est
précisément celle qu'on cherche.
"""
import csv
import io

from django.http import StreamingHttpResponse
from django.utils import timezone

#: L'ordre des colonnes est celui de la lecture : ce qu'est la cabine, puis où
#: elle est, puis depuis quand, puis ce que porte sa fiche papier.
COLONNES = [
    "N° cabine", "Type", "Chantier", "Modèle", "Statut", "Étape", "Rangement",
    "Rack", "Emplacement", "Place", "Zone",
    "Créée le", "Dernière activité", "Jours sans mouvement", "Envoyée le",
    "Revendeur", "Client", "Tissu BK", "Tissu AQ", "Fond de cabine",
]


#: Débuts de cellule qu'Excel prend pour une formule. Un client nommé
#: « =HYPERLINK(…) » ou une désignation « @SOMME(…) », recopiés tels quels du
#: fichier de production, s'exécutaient à l'ouverture de l'export.
_FORMULE = ("=", "+", "-", "@", "\t", "\r")


def cellule(valeur):
    """Une valeur sûre pour Excel : un texte qui commencerait comme une formule
    est précédé d'une apostrophe — Excel l'affiche alors comme du texte. Les
    nombres passent tels quels."""
    if isinstance(valeur, str) and valeur.startswith(_FORMULE):
        return "'" + valeur
    return valeur


def _date(valeur):
    """Une date lisible par un humain ET par Excel. Vide si absente."""
    if not valeur:
        return ""
    return timezone.localtime(valeur).strftime("%d/%m/%Y %H:%M")


def _jours_sans_mouvement(cabine):
    date = getattr(cabine, "derniere_activite_date", None) or cabine.date
    if not date:
        return ""
    return (timezone.now() - date).days


def _lignes_de(cabine):
    """Les lignes d'une cabine : une par emplacement occupé, une si elle n'en a aucun."""
    commun = [
        cabine.numero,
        cabine.get_type_cabine_display(),
        cabine.chantier,
        cabine.modele,
        cabine.get_statut_display(),
        cabine.etape_libelle,
        cabine.rangement_libelle,
    ]
    fin = [
        _date(cabine.date),
        _date(getattr(cabine, "derniere_activite_date", None)),
        _jours_sans_mouvement(cabine),
        _date(cabine.envoi_date),
        cabine.revendeur, cabine.client, cabine.tissu_bk, cabine.tissu_aq,
        cabine.fond_cabine,
    ]
    occupees = [o for o in cabine.occupations.all() if o.emplacement_id]
    if not occupees:
        return [commun + ["", "", "", ""] + fin]
    lignes = []
    for occupation in occupees:
        emplacement = occupation.emplacement
        zone = emplacement.zone_cabine.nom if emplacement.zone_cabine_id else emplacement.zone
        lignes.append(commun + [emplacement.rack, emplacement.code,
                                occupation.place, zone] + fin)
    return lignes


def _flux(cabines):
    """Produit le fichier ligne par ligne : la mémoire ne porte jamais tout le parc."""
    tampon = io.StringIO()
    graveur = csv.writer(tampon, delimiter=";", lineterminator="\r\n",
                         quoting=csv.QUOTE_MINIMAL)

    def vider():
        valeur = tampon.getvalue()
        tampon.seek(0)
        tampon.truncate(0)
        return valeur

    yield "﻿"                      # BOM : Excel lit alors l'UTF-8 sans se tromper
    graveur.writerow(COLONNES)
    yield vider()
    # `iterator` + `chunk_size` : les occupations restent préchargées (Django 4.1+),
    # sans quoi chaque cabine coûterait deux requêtes de plus.
    for cabine in cabines.iterator(chunk_size=200):
        for ligne in _lignes_de(cabine):
            graveur.writerow([cellule(v) for v in ligne])
        yield vider()


def reponse(cabines, prefixe="inventaire-cabines"):
    """La réponse HTTP complète : flux, type MIME et nom de fichier daté."""
    nom = f"{prefixe}-{timezone.localdate():%Y-%m-%d}.csv"
    r = StreamingHttpResponse(_flux(cabines), content_type="text/csv; charset=utf-8")
    r["Content-Disposition"] = f'attachment; filename="{nom}"'
    # Sans cet en-tête, le navigateur ne laisse pas le JavaScript lire le nom du
    # fichier et l'export arrive sous un nom généré au hasard.
    r["Access-Control-Expose-Headers"] = "Content-Disposition"
    return r


__all__ = ["COLONNES", "reponse"]
