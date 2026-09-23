from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from . import services_cabines, services_emplacements
from .models import (Cabine, CabineAttendue, Emplacement, ModeleCabine, MouvementCabine,
                     Occupation)


class ChampNormalise(serializers.CharField):
    """CharField qui passe en majuscules AVANT l'exécution des validators.

    `Emplacement.save()` normalise le code en majuscules. Si le UniqueValidator
    de DRF contrôle la valeur brute, « ac550 » franchit la validation alors que
    « AC550 » existe déjà : la contrainte d'unicité saute ensuite au save, et
    l'opérateur reçoit une erreur 500 au lieu d'un 400 explicite.
    """

    def to_internal_value(self, data):
        return super().to_internal_value(data).strip().upper()


class CabineBreveSerializer(serializers.ModelSerializer):
    """Vue réduite d'une cabine, pour l'imbriquer dans la liste des emplacements.

    `place` n'y figure pas, et c'est délibéré. C'est une PROPRIÉTÉ de `Cabine`
    qui relit ses occupations : la vue précharge celles de l'emplacement, pas
    celles des cabines imbriquées, si bien que chaque ligne de la liste
    déclenchait sa propre requête — mesuré, et c'est l'écran le plus ouvert de
    la journée.

    Elle était en plus FAUSSE pour une cabine occupant deux emplacements : la
    propriété rend la place de la première occupation, qui peut être celle d'un
    autre emplacement. La liste de A-02 annonçait « gauche » pour une cabine
    posée à droite ici. La place d'une cabine DANS un emplacement donné se lit
    par l'action `places/`, qui la tient de l'occupation elle-même.
    """
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)

    class Meta:
        model = Cabine
        fields = ["id", "numero", "chantier", "modele", "type_cabine",
                  "statut", "statut_libelle"]


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
    places_libres = serializers.SerializerMethodField()
    nb_cabines = serializers.SerializerMethodField()
    # Renseignés sur la fiche d'un emplacement seulement (voir _sur_la_fiche) :
    # l'écran de gestion sait alors présenter « Supprimer » ou « Désactiver »
    # AVANT que l'opérateur ne clique, au lieu de le faire échouer après coup.
    suppression = serializers.SerializerMethodField()
    actif_par_nom = serializers.SerializerMethodField()
    places_condamnees = serializers.SerializerMethodField()

    class Meta:
        model = Emplacement
        fields = "__all__"
        #: `actif` ne s'écrit PAS par le PATCH ordinaire. Il a ses règles —
        #: motif obligatoire, refus tant qu'une cabine est là — et elles vivent
        #: dans `services_cabines.changer_activation`, atteint par l'action
        #: `/activation/`. Une case à cocher dans le formulaire les contournait
        #: toutes : décocher puis « Enregistrer » retirait du stock un
        #: emplacement occupé, sans motif et sans un mot.
        read_only_fields = ["actif", "motif_inactif", "actif_le", "actif_par"]

    def get_actif_par_nom(self, obj):
        """Qui a mis l'emplacement en service ou hors service.

        Même secours que partout ailleurs : le nom affiché, ou l'identifiant
        quand personne n'a renseigné de nom.
        """
        u = obj.actif_par
        return (u.nom or u.username) if u else ""

    def get_places_condamnees(self, obj):
        """Les places hors service : [{place, motif, cree_le, cree_par}].

        Sur la fiche seulement, comme `suppression` : la liste des emplacements
        en ferait une requête par ligne.
        """
        if not self._sur_la_fiche():
            return None
        return [{"place": p.place,
                 "libelle": p.get_place_display(),
                 "motif": p.motif,
                 "cree_le": p.cree_le,
                 "cree_par": ((p.cree_par.nom or p.cree_par.username)
                              if p.cree_par_id else "")}
                for p in obj.places_condamnees.select_related("cree_par")]

    def _sur_la_fiche(self):
        """Vrai pour la consultation d'un emplacement isolé.

        Le diagnostic coûte une requête : le poser sur chaque ligne d'une liste
        de 50 emplacements en ferait 50 pour une information qui ne sert qu'au
        moment d'ouvrir la fiche.
        """
        vue = self.context.get("view")
        # `activation` et `place` renvoient la fiche complète : c'est elle que
        # l'écran redessine juste après le geste. Sans elles dans cette liste,
        # il se redessinait sans les condamnations qu'il venait de poser.
        return getattr(vue, "action", None) in ("retrieve", "create", "update",
                                                "partial_update", "activation",
                                                "place")

    def get_suppression(self, obj):
        """Supprimable ou non, et pourquoi — l'écran le dit AVANT le clic."""
        if not obj.pk or not self._sur_la_fiche():
            return None
        refus = services_emplacements.diagnostic_suppression(obj)
        return {"possible": not refus, "message": refus}

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

    def get_places_libres(self, obj):
        if obj.illimite:
            return []
        prises = {c.place for c in self._occupations_actives(obj) if c.place}
        return [code for code, _ in Cabine.PLACES if code not in prises]

    def validate_mode_places(self, value):
        """Changer de mode alors que des cabines sont là produirait un état incohérent.

        En « deux places » les cabines portent une place, en « illimité » aucune :
        basculer laisserait des cabines avec une place sur un emplacement qui n'en
        a plus, ou sans place sur un emplacement qui en exige une — et plus de
        deux cabines ne tiendraient de toute façon pas dans deux places.
        """
        if self.instance and value != self.instance.mode_places:
            presentes = (self.instance.occupations.exclude(cabine__statut=Cabine.ENVOYE).count())
            if presentes:
                raise serializers.ValidationError(
                    f"{presentes} cabine(s) occupent cet emplacement : videz-le avant "
                    "de changer son mode de rangement.")
        return value


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
    derniere_activite = serializers.SerializerMethodField()
    jours_immobile = serializers.SerializerMethodField()
    # Renseigné sur la fiche d'une cabine seulement : la liste n'a pas à payer le
    # comptage d'historique pour 50 lignes dont une seule sera ouverte.
    suppression = serializers.SerializerMethodField()
    # Rendu en liste AUSSI, contrairement à `suppression` : c'est justement en
    # liste qu'il évite d'ouvrir les fiches une par une.
    quarantaine = serializers.SerializerMethodField()

    class Meta:
        model = Cabine
        fields = "__all__"
        # Position et statut ne se modifient que par les opérations dédiées
        # (ranger / statut / envoyer / reprendre), qui écrivent l'historique. Exposés en
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
        # Une cabine mal saisie doit pouvoir disparaître : aucun motif n'est
        # définitivement bloquant, ils appellent seulement une confirmation.
        motif, message = services_cabines.diagnostic_suppression(obj)
        return {"possible": motif is None, "message": message}

    def get_quarantaine(self, obj):
        """La dernière quarantaine de cette cabine : pourquoi, quand, par qui.

        `active` dit si elle court encore. Une quarantaine LEVÉE est rendue
        aussi : savoir ce qui avait bloqué une cabine est une question qu'on se
        pose devant le rack, et la réponse n'était nulle part — sinon enfouie
        dans l'historique.

        Deux chemins, pour une raison de coût :

        - en liste et à l'export, seul le motif est renseigné. Il vient de
          l'annotation `quarantaine_motif` (voir `CabineViewSet._parc_annote`),
          donc d'une seule sous-requête pour toute la page. La date et l'auteur
          y coûteraient deux sous-requêtes de plus pour une ligne de liste qui
          n'en a pas besoin ;
        - ailleurs — la fiche, et la réponse d'une opération — la requête
          complète, sur un seul objet : elle rend aussi la date et l'auteur, que
          la fiche affiche.

        Rend `None` si cette cabine n'a jamais été mise en quarantaine.
        """
        if not obj.pk:
            return None
        active = obj.statut == Cabine.QUARANTAINE
        en_liste = getattr(self.context.get("view"), "action", None) in ("list", "export")
        if en_liste and hasattr(obj, "quarantaine_motif"):
            motif = (obj.quarantaine_motif or "").strip()
            if not (motif or active):
                return None
            return {"motif": motif, "date": None, "par": None, "active": active}

        dernier = (obj.historique
                   .filter(type=MouvementCabine.STATUT,
                           statut_apres=Cabine.QUARANTAINE)
                   .order_by("-date").first())
        if dernier is None:
            return None
        # `utilisateur_nom` est une colonne du mouvement, pas une jointure : le
        # nom y est recopié à l'écriture, exprès, pour qu'un compte supprimé
        # n'efface pas qui a fait quoi.
        return {"motif": (dernier.note or "").strip(), "date": dernier.date,
                "par": dernier.utilisateur_nom or "", "active": active}

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
    """Un modèle et sa taille — une place, ou tout l'emplacement.

    `nb_attendues` et `nb_en_stock` disent combien de cabines la bascule
    concerne : régler « QUATTRO » sur grand modèle touche 404 lignes du fichier
    de production, et c'est une information qu'on veut AVANT de toucher le
    bouton, pas après."""

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
