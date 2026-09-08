from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import (Occupation, Article, Cabine, CabineAttendue, Categorie,
                     Emplacement, EtatCabine, ModeleCabine, Mouvement, MouvementCabine,
                     Reception, Stock, Zone)


class ChampNormalise(serializers.CharField):
    """CharField qui passe en majuscules AVANT l'exécution des validators.

    `Article.save()` et `Emplacement.save()` normalisent en majuscules. Si le
    UniqueValidator de DRF contrôle la valeur brute, « a001 » franchit la validation
    alors que « A001 » existe déjà : la contrainte d'unicité saute ensuite au save,
    et l'opérateur reçoit une erreur 500 au lieu d'un 400 explicite.
    """

    def to_internal_value(self, data):
        return super().to_internal_value(data).strip().upper()


class CategorieSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categorie
        fields = "__all__"


class CabineBreveSerializer(serializers.ModelSerializer):
    """Vue réduite d'une cabine, pour l'imbriquer dans la liste des emplacements."""
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)

    class Meta:
        model = Cabine
        fields = ["id", "numero", "chantier", "modele", "type_cabine",
                  "statut", "statut_libelle", "place"]


class EmplacementSerializer(serializers.ModelSerializer):
    code = ChampNormalise(
        max_length=64,
        validators=[UniqueValidator(queryset=Emplacement.objects.all(),
                                    message="Ce code d'emplacement existe déjà.")],
    )
    # `default=None` est indispensable : sans lui, DRF **retire purement et
    # simplement** la clé de la réponse quand la relation est nulle (SkipField).
    # Un emplacement sans zone renvoyait donc un objet sans `zone_cabine_nom`, et
    # tout code lisant ce champ recevait `undefined` au lieu de `null` — vérifié
    # sur les 5 emplacements du poste, dont aucun n'a encore de zone.
    zone_cabine_nom = serializers.CharField(source="zone_cabine.nom", read_only=True,
                                            default=None)
    mode_libelle = serializers.CharField(source="get_mode_places_display", read_only=True)
    illimite = serializers.BooleanField(read_only=True)
    cabines = serializers.SerializerMethodField()
    places_occupees = serializers.SerializerMethodField()
    places_libres = serializers.SerializerMethodField()
    nb_cabines = serializers.SerializerMethodField()
    # Renseignés sur la fiche d'un emplacement seulement (voir _sur_la_fiche) :
    # l'écran de gestion sait alors présenter « Supprimer » ou « Désactiver »
    # AVANT que l'opérateur ne clique, au lieu de le faire échouer après coup.
    suppression = serializers.SerializerMethodField()

    class Meta:
        model = Emplacement
        fields = "__all__"

    def _sur_la_fiche(self):
        """Vrai pour la consultation d'un emplacement isolé.

        Le diagnostic coûte trois comptages : le poser sur chaque ligne d'une liste
        de 50 emplacements ferait 150 requêtes pour une information qui ne sert
        qu'au moment d'ouvrir la fiche.
        """
        vue = self.context.get("view")
        return getattr(vue, "action", None) in ("retrieve", "create", "update",
                                                "partial_update")

    def get_suppression(self, obj):
        if not obj.pk or not self._sur_la_fiche():
            return None
        from .services import (BLOCAGE_STOCK, diagnostic_suppression, lignes_de_stock,
                               suppression_forcable)

        requete = self.context.get("request")
        utilisateur = getattr(requete, "user", None)
        motif, message = diagnostic_suppression(obj, utilisateur)
        detail = {
            "possible": motif is None,
            "motif": motif,
            "message": message,
            # Ce que CE compte peut forcer : la perte de traçabilité pour tous,
            # la suppression avec stock pour les seuls administrateurs.
            "forcable": bool(motif) and suppression_forcable(motif, utilisateur),
            "reserve_admin": motif == BLOCAGE_STOCK,
        }
        if motif == BLOCAGE_STOCK:
            # Ce qui sera sorti : l'écran de confirmation l'annonce ligne par ligne
            # plutôt que de faire signer un chèque en blanc.
            detail["stock"] = [
                {"ref": ligne.article.ref, "designation": ligne.article.designation,
                 "qte": float(ligne.qte)}
                for ligne in lignes_de_stock(obj)[:30]
            ]
        return detail

    def _occupations_actives(self, obj):
        """Occupations d'ici. Utilise le prefetch de la vue ; requête à défaut.

        Une cabine peut n'occuper qu'une place ici et se prolonger ailleurs.
        """
        actifs = getattr(obj, "occupations_actives", None)
        if actifs is None:
            actifs = list(obj.occupations.exclude(cabine__statut=Cabine.ENVOYE)
                          .select_related("cabine").order_by("place", "cabine__numero"))
        return actifs

    def get_cabines(self, obj):
        # Une cabine occupant deux places ici ne doit apparaître qu'une fois.
        vues, uniques = set(), []
        for occupation in self._occupations_actives(obj):
            if occupation.cabine_id not in vues:
                vues.add(occupation.cabine_id)
                uniques.append(occupation.cabine)
        return CabineBreveSerializer(uniques, many=True).data

    def get_nb_cabines(self, obj):
        return len({c.cabine_id for c in self._occupations_actives(obj)})

    def get_places_occupees(self, obj):
        if obj.illimite:
            return []
        return sorted(c.place for c in self._occupations_actives(obj) if c.place)

    def get_places_libres(self, obj):
        if obj.illimite:
            return []
        prises = {c.place for c in self._occupations_actives(obj) if c.place}
        return [code for code, _ in Cabine.PLACES if code not in prises]

    def validate_mode_places(self, value):
        """Changer de mode alors que des cabines sont là produirait un état incohérent.

        En « gmd » les cabines portent une place, en « illimite » aucune : basculer
        laisserait des cabines avec une place sur un emplacement qui n'en a plus, ou
        sans place sur un emplacement qui en exige une — et plus de trois cabines ne
        tiendraient de toute façon pas dans trois places.
        """
        if self.instance and value != self.instance.mode_places:
            presentes = (self.instance.occupations.exclude(cabine__statut=Cabine.ENVOYE).count())
            if presentes:
                raise serializers.ValidationError(
                    f"{presentes} cabine(s) occupent cet emplacement : videz-le avant "
                    "de changer son mode de rangement.")
        return value


class ArticleSerializer(serializers.ModelSerializer):
    categorie_nom = serializers.CharField(source="categorie.nom", read_only=True,
                                          default=None)
    # Annotations posées par ArticleViewSet.get_queryset ; absentes après une création,
    # d'où le getattr plutôt qu'un champ lié directement.
    total_stock = serializers.SerializerMethodField()
    nb_emplacements = serializers.SerializerMethodField()
    ref = ChampNormalise(
        max_length=64, required=False,
        validators=[UniqueValidator(queryset=Article.objects.all(),
                                    message="Cette référence existe déjà.")],
    )
    ean = ChampNormalise(max_length=64, required=False, allow_blank=True, default="")

    class Meta:
        model = Article
        fields = "__all__"

    def get_total_stock(self, obj):
        total = getattr(obj, "total_stock", None)
        return float(total) if total is not None else 0.0

    def get_nb_emplacements(self, obj):
        return getattr(obj, "nb_emplacements", 0) or 0

    def validate_ean(self, value):
        """L'unicité de l'EAN est une contrainte conditionnelle (ignorée si vide).

        DRF ne construit pas de validator pour ce type de contrainte : sans ce
        contrôle, un EAN en doublon remonte en IntegrityError (500) au lieu d'un 400.
        """
        ean = (value or "").strip().upper()
        if not ean:
            return ean
        doublons = Article.objects.filter(ean=ean)
        if self.instance is not None:
            doublons = doublons.exclude(pk=self.instance.pk)
        if doublons.exists():
            raise serializers.ValidationError("Cet EAN est déjà utilisé par un autre article.")
        return ean


class StockSerializer(serializers.ModelSerializer):
    article_ref = serializers.CharField(source="article.ref", read_only=True, default=None)
    emplacement_code = serializers.CharField(source="emplacement.code", read_only=True,
                                             default=None)

    class Meta:
        model = Stock
        fields = ["id", "article", "article_ref", "emplacement", "emplacement_code", "qte"]


class MouvementSerializer(serializers.ModelSerializer):
    # Les FK de l'historique sont en SET_NULL : après la suppression d'un article ou
    # d'un emplacement, ces deux clés disparaissaient de la réponse au lieu de valoir
    # null, et le journal affichait une case vide sans dire pourquoi.
    article_ref = serializers.CharField(source="article.ref", read_only=True, default=None)
    emplacement_code = serializers.CharField(source="emplacement.code", read_only=True,
                                             default=None)

    class Meta:
        model = Mouvement
        fields = "__all__"


class ReceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reception
        fields = "__all__"


class EtatCabineSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtatCabine
        fields = "__all__"


class ZoneSerializer(serializers.ModelSerializer):
    nb_emplacements = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = "__all__"

    def get_nb_emplacements(self, obj):
        return obj.emplacements.count()


class OccupationSerializer(serializers.ModelSerializer):
    """Un emplacement occupé. Toujours rendu avec sa cabine, jamais seul."""
    emplacement_code = serializers.SerializerMethodField()
    zone_nom = serializers.SerializerMethodField()
    position = serializers.CharField(read_only=True)
    range = serializers.BooleanField(read_only=True)
    libelle_court = serializers.CharField(read_only=True)

    class Meta:
        model = Occupation
        fields = ["id", "numero", "libelle", "libelle_court", "emplacement",
                  "emplacement_code", "place", "position", "range", "zone_nom"]
        read_only_fields = ["emplacement", "place"]

    def get_emplacement_code(self, obj):
        return obj.emplacement.code if obj.emplacement_id else None

    def get_zone_nom(self, obj):
        if obj.emplacement_id and obj.emplacement.zone_cabine_id:
            return obj.emplacement.zone_cabine.nom
        return None


class CabineSerializer(serializers.ModelSerializer):
    # Déduits du modèle, en lecture seule : l'écran affiche « Rangé »/« Non rangé »
    # sans que personne ait à le saisir, donc sans risque de contredire l'emplacement.
    rangee = serializers.BooleanField(read_only=True)
    rangement_libelle = serializers.CharField(read_only=True)
    emplacement_code = serializers.SerializerMethodField()
    zone_nom = serializers.SerializerMethodField()
    position = serializers.CharField(read_only=True)
    occupations = OccupationSerializer(many=True, read_only=True)
    nb_emplacements = serializers.SerializerMethodField()
    place = serializers.SerializerMethodField()
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    type_libelle = serializers.CharField(source="get_type_cabine_display", read_only=True)
    envoyee = serializers.BooleanField(read_only=True)
    etape = serializers.CharField(read_only=True)
    etape_libelle = serializers.CharField(read_only=True)
    zone_role = serializers.SerializerMethodField()
    derniere_activite = serializers.SerializerMethodField()
    jours_immobile = serializers.SerializerMethodField()
    # Renseigné sur la fiche d'une cabine seulement : la liste n'a pas à payer le
    # comptage d'historique pour 50 lignes dont une seule sera ouverte.
    suppression = serializers.SerializerMethodField()
    statut_motif = serializers.SerializerMethodField()

    class Meta:
        model = Cabine
        fields = "__all__"
        # Position et statut ne se modifient que par les opérations dédiées
        # (ranger / sortir / statut / envoyer), qui écrivent l'historique. Exposés en
        # écriture, un simple PATCH annulerait un envoi et laisserait la fiche sans trace.
        read_only_fields = ["statut", "statut_date", "envoi_date",
                            "utilisateur", "date"]
        # DRF dérive un UniqueTogetherValidator de la contrainte
        # `place_occupee_par_une_seule_cabine`, et ce validateur exige des champs
        # modifiables : sur (emplacement, place) qui sont en lecture seule, tout PATCH
        # levait une AssertionError (erreur 500). L'unicité reste garantie par la
        # contrainte en base et contrôlée avec un message clair dans services_cabines.
        validators = []

    def get_suppression(self, obj):
        """Ce que l'opérateur perdra en supprimant — annoncé AVANT le clic."""
        vue = self.context.get("view")
        if not obj.pk or getattr(vue, "action", None) != "retrieve":
            return None
        from .services_cabines import diagnostic_suppression

        motif, message = diagnostic_suppression(obj)
        return {
            "possible": motif is None,
            "motif": motif,
            "message": message,
            # Une cabine mal saisie doit pouvoir disparaître : aucun motif n'est
            # définitivement bloquant, ils appellent seulement une confirmation.
            "forcable": motif is not None,
        }

    def get_statut_motif(self, obj):
        """Pourquoi la cabine est dans cet état, d'après le dernier changement.

        Le motif est écrit au journal, pas sur la cabine : c'est la bonne place —
        il en faut un par changement, pas un seul écrasé à chaque fois. Mais au
        moment de confirmer la sortie d'une cabine en quarantaine, « bloquée :
        rayure sur la paroi » est exactement ce qu'il faut avoir sous les yeux.
        Comme `suppression`, il n'est calculé que sur la fiche.
        """
        vue = self.context.get("view")
        if not obj.pk or getattr(vue, "action", None) != "retrieve":
            return None
        from .models import MouvementCabine

        dernier = (obj.historique.filter(type=MouvementCabine.STATUT,
                                         statut_apres=obj.statut)
                   .order_by("-date").values_list("note", flat=True).first())
        return (dernier or "").strip()

    @staticmethod
    def _premier_pose(obj):
        """Premier emplacement occupé. Les champs hérités décrivent celui-là.

        `emplacement_code`, `place`, `zone_nom` datent d'avant et sont lus par des
        écrans qui ne montrent qu'une position. Les faire porter sur le premier
        emplacement garde ces écrans exacts pour le cas courant — une cabine, un
        emplacement — sans prétendre décrire les autres : `position` et
        `occupations` disent la vérité complète.
        """
        return next(iter(obj.emplacements_occupes), None)

    def get_emplacement_code(self, obj):
        premier = self._premier_pose(obj)
        return premier.emplacement.code if premier else None

    def get_place(self, obj):
        premier = self._premier_pose(obj)
        return premier.place if premier else ""

    def get_nb_emplacements(self, obj):
        """Combien d'emplacements la cabine occupe. Un, sauf exception."""
        return len(obj.emplacements_occupes)

    def get_zone_nom(self, obj):
        premier = self._premier_pose(obj)
        if premier and premier.emplacement.zone_cabine_id:
            return premier.emplacement.zone_cabine.nom
        return None

    def get_zone_role(self, obj):
        premier = self._premier_pose(obj)
        if premier and premier.emplacement.zone_cabine_id:
            return premier.emplacement.zone_cabine.role
        return None

    def _derniere(self, obj):
        """Date du dernier événement. Annotée par la vue pour éviter une requête par ligne."""
        date = getattr(obj, "derniere_activite_date", None)
        if date is None:
            dernier = obj.historique.order_by("-date").values_list("date", flat=True).first()
            date = dernier or obj.date
        return date

    def get_derniere_activite(self, obj):
        date = self._derniere(obj)
        return date.isoformat() if date else None

    def get_jours_immobile(self, obj):
        """Ancienneté dans l'étape courante, pour repérer les cabines qui stagnent."""
        date = self._derniere(obj)
        if not date:
            return None
        return (timezone.now() - date).days

    def validate(self, attrs):
        """Reprend la règle de Cabine.clean() au niveau DRF.

        Sans ce contrôle, la ValidationError levée par le modèle dans perform_create
        n'est pas une exception DRF : elle remonte en erreur 500 au lieu d'un 400
        rattaché au champ « chantier ».

        La liste des types dispensés vient de `Cabine.SANS_CHANTIER`, jamais d'une
        copie : elle en contenait un seul quand le modèle en comptait déjà trois, et
        toute cabine salon ou occasion était refusée ici alors que le modèle
        l'acceptait.
        """
        def defaut(champ, sinon):
            return attrs.get(champ, getattr(self.instance, champ, sinon))
        if defaut("type_cabine", Cabine.NORMALE) not in Cabine.SANS_CHANTIER \
                and not defaut("chantier", ""):
            libres = ", ".join(libelle for code, libelle in Cabine.TYPES if code in Cabine.SANS_CHANTIER)
            raise serializers.ValidationError({
                "chantier": f"Le n° de chantier est obligatoire (sauf pour : {libres})."})
        return attrs


class ModeleCabineSerializer(serializers.ModelSerializer):
    """Un modèle et sa taille. `nb_attendues` et `nb_en_stock` disent combien de
    cabines la bascule concerne : régler « QUATTRO » sur grand modèle touche 404
    lignes du fichier de production, et c'est une information qu'on veut AVANT
    de toucher le bouton, pas après."""

    nb_attendues = serializers.IntegerField(read_only=True, required=False)
    nb_en_stock = serializers.IntegerField(read_only=True, required=False)
    regle_par = serializers.CharField(source="modifie_par.nom", read_only=True,
                                      default="")

    class Meta:
        model = ModeleCabine
        fields = ["id", "nom", "cle", "grand", "modifie_le", "regle_par",
                  "nb_attendues", "nb_en_stock"]
        read_only_fields = ["cle", "modifie_le"]


class MouvementCabineSerializer(serializers.ModelSerializer):
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)
    statut_avant_libelle = serializers.SerializerMethodField()
    statut_apres_libelle = serializers.SerializerMethodField()

    class Meta:
        model = MouvementCabine
        fields = "__all__"

    def _libelle_statut(self, code):
        return dict(Cabine.STATUTS).get(code, code or "")

    def get_statut_avant_libelle(self, obj):
        return self._libelle_statut(obj.statut_avant)

    def get_statut_apres_libelle(self, obj):
        return self._libelle_statut(obj.statut_apres)


class CabineAttendueSerializer(serializers.ModelSerializer):
    """Une cabine annoncée par la production, pas encore en stock.

    `chantier_a_saisir` est rendu au front : c'est lui qui décide d'afficher
    « chantier à saisir » plutôt qu'un champ vide sans explication.
    """

    chantier_a_saisir = serializers.BooleanField(read_only=True)
    champs_cabine = serializers.SerializerMethodField()
    importe_par_nom = serializers.SerializerMethodField()

    class Meta:
        model = CabineAttendue
        fields = "__all__"
        read_only_fields = ["importe_le", "importe_par", "fichier"]

    def get_champs_cabine(self, obj):
        """Ce que l'écran d'entrée recopie. Calculé par le modèle, jamais par le front :
        deux définitions de la même correspondance finiraient par diverger."""
        return obj.champs_cabine()

    def get_importe_par_nom(self, obj):
        u = obj.importe_par
        return (u.nom or u.username) if u else ""
