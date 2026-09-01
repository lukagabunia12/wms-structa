"""Importe les données de la maquette (wms.json) dans la base WMS."""
import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from wms.models import (Article, Cabine, Categorie, Emplacement, EtatCabine,
                        Mouvement, MouvementCabine, Reception, Stock)
from wms.services import generer_numero_reception

TYPE_MAP = {"IN": "IN", "OUT": "OUT", "ADJUST": "AJUST", "AJUST": "AJUST"}


def STATUT_MAP(statut, etat):
    """Traduit le couple (statut, etat) de la maquette vers un statut du modèle actuel.

    Même correspondance que la migration de reprise 0004 : la maquette portait un libellé
    libre (« Quarantaine ») et un drapeau "sortie".
    """
    if (statut or "").strip().lower() == "sortie":
        return Cabine.ENVOYE
    t = (etat or "").strip().lower()
    if "lev" in t:
        return Cabine.LIBRE
    if "quarantaine" in t:
        return Cabine.QUARANTAINE
    if "charg" in t:
        # « Chargé » a été retiré du vocabulaire : une cabine chargée est prête à
        # partir sans l'être encore. « Levée de quarantaine » est l'état subsistant
        # le plus proche ; le rangement, lui, se déduit de l'emplacement.
        return Cabine.LIBRE
    if "envoy" in t:
        return Cabine.ENVOYE
    return Cabine.LIBRE


class Command(BaseCommand):
    help = "Importe les données de la maquette (fichier wms.json) dans la base."

    def add_arguments(self, parser):
        parser.add_argument("chemin", help="Chemin vers wms.json")
        parser.add_argument("--purge", action="store_true", help="Vide les tables WMS avant import")

    def _dec(self, v):
        try:
            return Decimal(str(v if v not in (None, "") else 0))
        except Exception:
            # Silencieux auparavant : une quantité illisible devenait 0 sans trace.
            self.stderr.write(f"  quantité illisible, 0 retenu : {v!r}")
            return Decimal("0")

    @transaction.atomic
    def handle(self, *args, **o):
        p = Path(o["chemin"])
        if not p.exists():
            raise CommandError(f"Fichier introuvable : {p}")
        d = json.loads(p.read_text(encoding="utf-8"))
        d = d.get("data", d)

        if o["purge"]:
            for M in (Stock, Mouvement, Reception, Cabine, Article, Emplacement, Categorie, EtatCabine):
                M.objects.all().delete()

        cat, emp, art = {}, {}, {}
        for c in d.get("categories", []):
            cat[c["id"]] = Categorie.objects.create(
                nom=(c.get("nom") or c.get("nm") or "?")[:120], zone=c.get("zone", "") or "")
        for brut in d.get("locations", []):
            emp[brut["id"]] = Emplacement.objects.create(
                code=(brut.get("code") or brut["id"])[:64], zone=brut.get("zone", "") or "",
                description=brut.get("description", "") or "", staging=bool(brut.get("staging")))
        for a in d.get("articles", []):
            art[a["id"]] = Article.objects.create(
                ref=(a.get("ref") or f"IMP{len(art)+1:04d}")[:64], ean=(a.get("ean") or "")[:64],
                designation=(a.get("designation") or "?")[:255], categorie=cat.get(a.get("categorieId")),
                emplacement_defaut=emp.get(a.get("emplacementId")), unite=(a.get("unite") or "pièce")[:32],
                stock_min=self._dec(a.get("stockMin")))
        for m in d.get("mouvements", []):
            mv = Mouvement.objects.create(type=TYPE_MAP.get(m.get("type"), "IN"), article=art.get(m.get("articleId")),
                                          emplacement=emp.get(m.get("locationId")), qte=self._dec(m.get("qte")),
                                          note=(m.get("note") or "")[:255], commande=(m.get("commande") or "")[:64])
            dt = parse_datetime(m.get("date") or "")
            if dt:
                Mouvement.objects.filter(pk=mv.pk).update(date=dt)

        # Reprise de stock : le journal de la maquette est partiel (quelques mouvements
        # pour des centaines d'articles) alors que son tableau `stock` fait foi. Importer
        # l'un sans l'autre laissait le cache incohérent avec le journal — un
        # `recalculer_stock()` après import écrasait le stock réel (invariant n°1 cassé).
        # On matérialise donc chaque ligne importée par un AJUSTEMENT (valeur absolue),
        # créé après les mouvements antidatés pour être rejoué en dernier.
        n_reprises = 0
        for s in d.get("stock", []):
            A, E = art.get(s.get("articleId")), emp.get(s.get("locationId"))
            if not (A and E):
                continue
            qte = self._dec(s.get("qte"))
            Mouvement.objects.create(type=Mouvement.AJUSTEMENT, article=A, emplacement=E,
                                     qte=qte, note="Reprise de stock (import maquette)")
            Stock.objects.update_or_create(article=A, emplacement=E, defaults={"qte": qte})
            n_reprises += 1
        for r in d.get("receptions", []):
            Reception.objects.create(numero=generer_numero_reception(), article=art.get(r.get("articleId")),
                                     emplacement=emp.get(r.get("locationId")), qte=self._dec(r.get("qte")),
                                     commande=(r.get("commande") or "")[:64],
                                     commentaire=(r.get("commentaire") or "")[:255],
                                     staging=bool(r.get("staging")))
        etats = {"Quarantaine"} | {c["etat"] for c in d.get("cabines", []) if c.get("etat")}
        for nom in etats:
            EtatCabine.objects.get_or_create(nom=nom[:64])
        n_cab, n_cab_ignorees = 0, 0
        for c in d.get("cabines", []):
            cab = Cabine(numero=(c.get("numero") or "")[:16], chantier=(c.get("chantier") or "")[:6],
                         modele=(c.get("modele") or "")[:120],
                         statut=STATUT_MAP(c.get("statut"), c.get("etat")))
            # La position vit sur l'occupation : elle est posée juste après le save.
            emplacement_cabine = emp.get(c.get("locationId"))
            try:
                # `Cabine.save()` valide désormais les formats (numero xx_xx_xx, chantier
                # 6 chiffres). Avant, `objects.create()` n'exécutait aucun validator et
                # les cabines invalides entraient en base malgré ce bloc « ignorée ».
                cab.save()
                # `Cabine.save()` a déjà créé la ligne d'occupation n° 1. On lui
                # pose sa position ; en créer une seconde violerait la contrainte
                # d'unicité (cabine, numéro).
                if emplacement_cabine is not None:
                    cab.occupations.filter(numero=1).update(emplacement=emplacement_cabine)
                MouvementCabine.objects.create(
                    cabine=cab, cabine_numero=cab.numero, chantier=cab.chantier,
                    type=MouvementCabine.CREATION, statut_apres=cab.statut,
                    note="Import maquette" + (f" (état d'origine : {c['etat']})" if c.get("etat") else ""))
                n_cab += 1
            except Exception as e:
                n_cab_ignorees += 1
                self.stderr.write(f"  cabine ignorée ({c.get('numero')}): {e}")

        resume = (f"Import OK : {len(cat)} catégories, {len(emp)} emplacements, {len(art)} articles, "
                  f"{Stock.objects.count()} lignes de stock ({n_reprises} reprises), "
                  f"{Mouvement.objects.count()} mouvements, "
                  f"{Reception.objects.count()} réceptions, {n_cab} cabines")
        resume += f", {n_cab_ignorees} cabines ignorées." if n_cab_ignorees else "."
        self.stdout.write(self.style.SUCCESS(resume))
