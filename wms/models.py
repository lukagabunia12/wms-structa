"""Modèle de données WMS Structa.

Invariants métier (voir docs/inventaire-maquette-wms.md) :
- La vérité du stock est le journal des `Mouvement` ; `Stock` n'est qu'un cache reconstructible.
- Types de mouvement : ENTREE / SORTIE / AJUSTEMENT (valeur absolue). Le transfert = SORTIE + ENTREE.
- Les références orphelines sont assumées : les FK historiques sont en SET_NULL, jamais en CASCADE.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


class Utilisateur(AbstractUser):
    ADMIN, OPERATEUR, LECTURE = "admin", "operateur", "lecture"
    ROLES = [(ADMIN, "Administrateur"), (OPERATEUR, "Opérateur"), (LECTURE, "Lecture seule")]

    nom = models.CharField("nom affiché", max_length=150, blank=True)
    role = models.CharField(max_length=16, choices=ROLES, default=OPERATEUR)
    pin = models.CharField(max_length=32, blank=True)
    droit_mvt = models.BooleanField("mouvements", default=False)
    droit_mvt_corr = models.BooleanField("correction de mouvement", default=False)
    droit_inv = models.BooleanField("inventaire", default=False)
    droit_cab = models.BooleanField("cabines", default=False)
    droit_ref = models.BooleanField("référentiel", default=False)
    droit_data = models.BooleanField("données (import/reset)", default=False)
    droit_appro = models.BooleanField("appro", default=False)

    DROITS = ["mvt", "mvt_corr", "inv", "cab", "ref", "data", "appro"]

    def droits_effectifs(self):
        """Droits réellement applicables. Appliqué par wms.permissions.DroitWMS.

        `is_superuser` est inclus : un compte créé par `createsuperuser` a le rôle
        « operateur » par défaut et se retrouverait sinon sans aucun droit.
        """
        if self.is_superuser or self.role == self.ADMIN:
            return {c: True for c in self.DROITS}
        if self.role == self.LECTURE:
            # « Lecture seule » l'emporte sur les cases cochées individuellement.
            return {c: False for c in self.DROITS}
        return {c: getattr(self, f"droit_{c}") for c in self.DROITS}

    @property
    def est_administrateur(self):
        """Compte administrateur — au-delà des 7 droits fins.

        Certaines opérations exceptionnelles ne se règlent pas par une case à cocher :
        supprimer un emplacement qui porte encore du stock fait disparaître de la
        marchandise des totaux. C'est une décision d'exploitation, pas un geste de
        poste, et elle est réservée à ce niveau.
        """
        return bool(self.is_superuser or self.role == self.ADMIN)

    def __str__(self):
        return self.nom or self.username


class Categorie(models.Model):
    nom = models.CharField(max_length=120, unique=True)
    zone = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "catégorie"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Zone(models.Model):
    """Regroupement d'emplacements de cabines : « À ranger », « Sortie prod », etc.

    Librement créée par l'exploitation. L'ancien champ texte `Emplacement.zone`
    servait au volet articles ; il est conservé mais n'a pas de rôle ici.

    Le `role` situe la zone dans le processus : c'est lui qui permet de dire
    « en attente de départ » plutôt que « en C001·G ».
    """
    PRODUCTION, RANGEMENT, ENVOI = "production", "rangement", "envoi"
    ROLES = [(PRODUCTION, "Sortie de production"), (RANGEMENT, "Zone de rangement"),
             (ENVOI, "Zone d'envoi")]

    nom = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    role = models.CharField("rôle dans le processus", max_length=16, choices=ROLES,
                            default=RANGEMENT)
    ordre = models.PositiveIntegerField("ordre d'affichage", default=0)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "zone"
        ordering = ["ordre", "nom"]

    def save(self, *args, **kwargs):
        self.nom = (self.nom or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class Emplacement(models.Model):
    #: Mode de rangement des cabines, réglable emplacement par emplacement.
    #: « gmd » : trois places nommées, une cabine chacune (travée de rack).
    #: « illimite » : pas de place nommée, autant de cabines que nécessaire
    #: (zone tampon « à ranger », aire de sortie prod…).
    GMD, ILLIMITE = "gmd", "illimite"
    MODES_PLACES = [(GMD, "3 places (gauche, milieu, droite)"),
                    (ILLIMITE, "Capacité illimitée")]

    code = models.CharField(max_length=64, unique=True)
    zone = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=255, blank=True)
    staging = models.BooleanField("zone de réception (à ranger)", default=False)
    code_barre = models.CharField(max_length=128, blank=True)
    actif = models.BooleanField(default=True)
    zone_cabine = models.ForeignKey("Zone", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="emplacements", verbose_name="zone de cabines")
    mode_places = models.CharField("mode de rangement", max_length=16,
                                   choices=MODES_PLACES, default=GMD)

    #: Position dans la structure physique, renseignée par le générateur de racks.
    #: Le code seul ne suffit pas : « AC551 » ne dit pas à une machine que c'est le
    #: niveau 1 de la colonne 550 du rack AC. Sans ces trois champs, imprimer les
    #: étiquettes « par colonne » obligerait à redécouper le code à coups
    #: d'expressions régulières, et toute convention un peu différente casserait.
    #: Vides pour les emplacements créés à l'unité : ils s'impriment seuls.
    rack = models.CharField("rack", max_length=32, blank=True, default="")
    colonne = models.PositiveIntegerField("colonne", null=True, blank=True)
    niveau = models.PositiveIntegerField("niveau", null=True, blank=True)

    @property
    def illimite(self):
        return self.mode_places == self.ILLIMITE

    class Meta:
        verbose_name = "emplacement"
        ordering = ["code"]
        indexes = [models.Index(fields=["rack", "colonne", "niveau"],
                                name="emplacement_position_idx")]

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code


class Article(models.Model):
    ACTIF, DORMANT = "actif", "dormant"
    STATUTS = [(ACTIF, "Actif"), (DORMANT, "Dormant")]

    ref = models.CharField("référence", max_length=64, unique=True)
    ean = models.CharField(max_length=64, blank=True, default="")
    designation = models.CharField(max_length=255)
    categorie = models.ForeignKey(Categorie, null=True, blank=True, on_delete=models.SET_NULL, related_name="articles")
    emplacement_defaut = models.ForeignKey(
        Emplacement, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="articles_par_defaut")
    unite = models.CharField(max_length=32, default="pièce")
    stock_min = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    statut = models.CharField(max_length=16, choices=STATUTS, default=ACTIF)
    statut_ts = models.DateTimeField(null=True, blank=True)
    # Optionnels (non prioritaires)
    poids = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    longueur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    largeur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    hauteur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Réservés au futur module MRP/appro
    fournisseur = models.CharField(max_length=255, blank=True)
    prix = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    delai_cde_jours = models.PositiveIntegerField(null=True, blank=True)
    mini_cde = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        verbose_name = "article"
        ordering = ["ref"]
        constraints = [
            models.UniqueConstraint(fields=["ean"], condition=~models.Q(ean=""), name="ean_unique_si_present"),
        ]

    def save(self, *args, **kwargs):
        self.ref = (self.ref or "").strip().upper()
        # Normalisé comme `ref` : sans cela « 123 », « 123 » et « abc »/« ABC »
        # coexistent et contournent la contrainte d'unicité de l'EAN.
        self.ean = (self.ean or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ref} — {self.designation}"


class Stock(models.Model):
    """Cache du stock par (article, emplacement). Reconstructible via services.recalculer_stock()."""
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="lignes_stock")
    emplacement = models.ForeignKey(Emplacement, on_delete=models.PROTECT, related_name="lignes_stock")
    qte = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        verbose_name = "ligne de stock"
        # Sans ordre déterministe, la pagination DRF ne garantit pas la composition des
        # pages : une même ligne peut apparaître deux fois ou être omise.
        ordering = ["article__ref", "emplacement__code"]
        constraints = [models.UniqueConstraint(
            fields=["article", "emplacement"], name="stock_unique_article_emplacement")]

    def __str__(self):
        return f"{self.article.ref} @ {self.emplacement.code} = {self.qte}"


class Mouvement(models.Model):
    ENTREE, SORTIE, AJUSTEMENT = "IN", "OUT", "AJUST"
    TYPES = [(ENTREE, "Entrée"), (SORTIE, "Sortie"), (AJUSTEMENT, "Ajustement")]

    date = models.DateTimeField(auto_now_add=True)
    type = models.CharField(max_length=8, choices=TYPES)
    article = models.ForeignKey(Article, null=True, on_delete=models.SET_NULL, related_name="mouvements")
    emplacement = models.ForeignKey(Emplacement, null=True, on_delete=models.SET_NULL, related_name="mouvements")
    qte = models.DecimalField(max_digits=14, decimal_places=3)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mouvements")
    note = models.CharField(max_length=255, blank=True)
    commande = models.CharField(max_length=64, blank=True)
    annule = models.BooleanField(default=False)
    annulation = models.BooleanField(default=False)
    mouvement_source = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="contre_passations")

    class Meta:
        verbose_name = "mouvement"
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.get_type_display()} {self.qte} — {self.date:%d/%m/%Y %H:%M}"


class Reception(models.Model):
    numero = models.CharField(max_length=32, unique=True)
    date = models.DateTimeField(auto_now_add=True)
    article = models.ForeignKey(Article, null=True, on_delete=models.SET_NULL, related_name="receptions")
    emplacement = models.ForeignKey(Emplacement, null=True, on_delete=models.SET_NULL, related_name="receptions")
    qte = models.DecimalField(max_digits=14, decimal_places=3)
    commande = models.CharField(max_length=64, blank=True)
    commentaire = models.CharField(max_length=255, blank=True)
    staging = models.BooleanField(default=False)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="receptions")

    class Meta:
        verbose_name = "réception"
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.numero


class EtatCabine(models.Model):
    nom = models.CharField(max_length=64, unique=True)

    class Meta:
        verbose_name = "état de cabine"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Cabine(models.Model):
    NORMALE, EXPRESS, SALON, OCCASION = "normale", "express", "salon", "occasion"
    TYPES = [(NORMALE, "Normale"), (EXPRESS, "Express"),
             (SALON, "Salon"), (OCCASION, "Occasion")]

    #: Types qui circulent sans n° de chantier. Une cabine de salon ou d'occasion
    #: n'a pas de client tant qu'elle n'est pas vendue : exiger un chantier dès la
    #: création interdirait de la faire entrer en stock.
    #: L'exemption s'arrête là : sortir ou envoyer exige un chantier pour TOUS les
    #: types (voir services_cabines.sortir_emplacement) — c'est ce qui garantit
    #: qu'aucune cabine ne quitte l'entrepôt sans être rattachée à une commande.
    SANS_CHANTIER = {EXPRESS, SALON, OCCASION}

    #: Le statut dit l'ÉTAT de la cabine, jamais où elle est. « Rangé » et
    #: « Non rangé » n'en font délibérément pas partie : ils se déduisent de
    #: l'emplacement (voir `rangee`). Les stocker en double ouvrirait la porte à
    #: une cabine marquée « Rangé » qui n'est nulle part — et plus personne ne
    #: saurait laquelle des deux informations croire.
    #: « Levée de quarantaine » a été retiré : une quarantaine levée rend la cabine
    #: conforme, c'est-à-dire « Rien à signaler ». En faire un statut distinct
    #: créait un troisième état qui ne disait rien de plus sur la cabine, et
    #: laissait des cabines parfaitement saines marquées d'un libellé alarmant
    #: pendant des semaines. Le passage par la quarantaine reste lisible : il est
    #: écrit dans le journal, avec son motif et sa date.
    LIBRE, QUARANTAINE, ENVOYE = ("libre", "quarantaine", "envoye")
    STATUTS = [(LIBRE, "Rien à signaler"), (QUARANTAINE, "En quarantaine"),
               (ENVOYE, "Envoyée")]

    GAUCHE, MILIEU, DROITE = "G", "M", "D"
    PLACES = [(GAUCHE, "Gauche"), (MILIEU, "Milieu"), (DROITE, "Droite")]

    numero = models.CharField(
        max_length=16, unique=True,
        validators=[RegexValidator(r"^\d{2}_\d{2}_\d{2}$", "Format attendu : xx_xx_xx")])
    # Facultatif en base : une cabine express se range sans chantier. L'obligation est
    # portée par clean() pour les cabines normales, et par le service pour la sortie.
    chantier = models.CharField(max_length=6, blank=True, default="",
                                validators=[RegexValidator(r"^\d{6}$", "Le chantier doit comporter 6 chiffres.")])
    type_cabine = models.CharField("type", max_length=16, choices=TYPES, default=NORMALE)
    modele = models.CharField(max_length=120, blank=True)
    # Informations reprises de la fiche papier collée sur la cabine. Consultatives :
    # aucune règle logistique ne s'appuie dessus, aucun filtre dédié.
    revendeur = models.CharField(max_length=120, blank=True, default="")
    client = models.CharField(max_length=120, blank=True, default="")
    tissu_bk = models.CharField("tissu BK", max_length=32, blank=True, default="")
    tissu_aq = models.CharField("tissu AQ", max_length=32, blank=True, default="")
    fond_cabine = models.CharField("fond de cabine", max_length=64, blank=True, default="")
    date = models.DateTimeField(auto_now_add=True)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="cabines")
    statut = models.CharField(max_length=16, choices=STATUTS, default=LIBRE)
    statut_date = models.DateTimeField(null=True, blank=True)
    envoi_date = models.DateTimeField("date d'envoi", null=True, blank=True)

    class Meta:
        verbose_name = "cabine"
        ordering = ["-date"]
        # La contrainte d'unicité de place a suivi la position : elle porte
        # désormais sur `Occupation` — c'est elle qui rattache une cabine à une place.

    #: Étapes du processus, dans l'ordre du flux. Dérivées du statut et du rôle de la
    #: zone où la cabine se trouve : elles ne sont pas stockées, donc jamais désynchronisées.
    ETAPES = [
        ("production", "Sortie de production"),
        ("quarantaine", "En quarantaine"),
        ("rangement", "En stock"),
        ("envoi", "En attente de départ"),
        ("envoyee", "Envoyée"),
    ]

    @property
    def envoyee(self):
        return self.statut == self.ENVOYE

    # --- position : une liste d'emplacements, plus un champ ------------------
    #
    # Une cabine occupe UN emplacement dans l'immense majorité des cas, parfois
    # plusieurs. La position a donc quitté la cabine pour la table `Occupation`,
    # et tout ce qui suit s'en déduit. Rien n'est stocké en double : une cabine
    # ne peut pas être marquée « rangée » alors qu'elle n'est nulle part.

    @property
    def emplacements_occupes(self):
        """Les emplacements où la cabine se trouve, dans l'ordre d'enregistrement.

        Une cabine en occupe UN dans l'immense majorité des cas. Il arrive
        qu'elle en occupe plusieurs — un morceau rangé ailleurs faute de place —
        et le WMS doit alors pouvoir le dire au lieu de l'écraser.
        """
        return [o for o in self.occupations.all() if o.emplacement_id]

    @property
    def occupations_libres(self):
        """Lignes d'occupation encore vides — normalement zéro ou une.

        Une cabine neuve en porte exactement une : c'est là que sa première
        position s'écrira. Une fois rangée, elle n'en a plus, et ajouter un
        emplacement en crée une nouvelle.
        """
        return [o for o in self.occupations.all() if not o.emplacement_id]

    @property
    def rangee(self):
        """La cabine occupe-t-elle au moins un emplacement ?

        Il n'y a pas de nombre d'emplacements attendu : on n'en sait rien avant
        d'avoir déchargé. Une cabine est donc rangée dès qu'elle est quelque part,
        et le cariste ajoute un emplacement s'il en trouve un second.

        Une cabine envoyée n'est plus nulle part — `envoyer()` libère ses
        emplacements — donc elle ressort « Non rangée », ce qui est exact.
        """
        return bool(self.emplacements_occupes)

    @property
    def rangement_libelle(self):
        n = len(self.emplacements_occupes)
        if not n:
            return "Non rangé"
        return "Rangé" if n == 1 else f"Rangé · {n} emplacements"

    @property
    def etape(self):
        """Où en est la cabine dans le processus.

        Le statut l'emporte sur la position : la quarantaine est une voie parallèle qui
        bloque le flux, peu importe l'endroit où la cabine est rangée. Une cabine
        « conforme » tire son étape du rôle de la zone qui l'accueille.
        """
        if self.statut == self.ENVOYE:
            return "envoyee"
        if self.statut == self.QUARANTAINE:
            return "quarantaine"
        # L'étape suit le PREMIER emplacement occupé : c'est lui qui dit où la
        # cabine est engagée dans le flux. Nulle part, aucun engagement.
        premier = next(iter(self.emplacements_occupes), None)
        if premier is None:
            return "production"       # sortie de production, pas encore rangée
        zone = premier.emplacement.zone_cabine
        if zone and zone.role == Zone.ENVOI:
            return "envoi"
        if zone and zone.role == Zone.PRODUCTION:
            return "production"
        return "rangement"

    @property
    def etape_libelle(self):
        return dict(self.ETAPES).get(self.etape, self.etape)

    # --- commodités de lecture, en LECTURE SEULE -----------------------------
    #
    # `emplacement` et `place` étaient des champs de la cabine ; ils décrivent
    # maintenant son PREMIER emplacement occupé. Deux raisons de les garder :
    #
    # - pour une cabine à un seul emplacement — le cas courant — ils disent
    #   exactement ce qu'ils ont toujours dit ;
    # - étant des propriétés sans setter, toute tentative d'ÉCRITURE échoue
    #   bruyamment. Aucun code ne peut donc reposer par mégarde sur l'ancien
    #   modèle : il casse au premier essai, au lieu de ranger une cabine à moitié.
    #
    # Pour agir, on passe par les occupations. Pour tout dire, par `position`.

    @property
    def emplacement(self):
        occupation = next(iter(self.emplacements_occupes), None)
        return occupation.emplacement if occupation else None

    @property
    def emplacement_id(self):
        occupation = next(iter(self.emplacements_occupes), None)
        return occupation.emplacement_id if occupation else None

    @property
    def place(self):
        occupation = next(iter(self.emplacements_occupes), None)
        return occupation.place if occupation else ""

    @property
    def position(self):
        """Où se trouve la cabine, en une ligne.

        Un seul emplacement : « AC5601·G », comme avant. Plusieurs : les
        positions séparées par une virgule. N'écrire que la première pour une
        cabine qui se prolonge ailleurs enverrait le cariste chercher la moitié
        d'une cabine.
        """
        return ", ".join(o.position for o in self.emplacements_occupes)

    def clean(self):
        super().clean()
        # Express, salon et occasion circulent sans chantier ; les autres non.
        if self.type_cabine not in self.SANS_CHANTIER and not self.chantier:
            libres = ", ".join(libelle for code, libelle in self.TYPES if code in self.SANS_CHANTIER)
            raise ValidationError({
                "chantier": f"Le n° de chantier est obligatoire (sauf pour : {libres})."})
        # Les règles de cohérence entre place et emplacement ont suivi la position :
        # elles vivent sur `Occupation.clean()`, seul objet qui porte encore les deux.

    def save(self, *args, **kwargs):
        # Les validators de `numero` et `chantier` ne sont sinon appliqués que par
        # l'admin et les serializers DRF : `Cabine.objects.create()` laissait entrer
        # des numéros arbitraires (constaté à l'import de la maquette).
        neuve = self._state.adding
        self.clean_fields()
        self.clean()
        super().save(*args, **kwargs)
        # INVARIANT : une cabine porte toujours au moins une ligne d'occupation —
        # vide tant qu'elle n'est rangée nulle part. Sans elle, il n'y aurait
        # aucun endroit où écrire la première position. Posé ici plutôt que dans
        # le service : une cabine créée par l'admin, par un import ou par un test
        # doit tenir la même promesse.
        if neuve and not self.occupations.exists():
            Occupation.objects.create(cabine=self, numero=1)

    def __str__(self):
        return f"{self.numero} (chantier {self.chantier or '—'})"


class Occupation(models.Model):
    """Un emplacement occupé par une cabine.

    Une cabine occupe UN emplacement dans l'immense majorité des cas. Il arrive
    qu'elle en occupe plusieurs — un morceau posé ailleurs faute de place dans la
    travée. Tant que la position vivait sur la cabine, il fallait choisir : soit
    écraser la première position par la seconde, soit créer une deuxième fiche et
    perdre l'unité de la cabine. Cette table tranche : la cabine reste une, ses
    emplacements sont une liste.

    Rien n'est déclaré à l'avance : on ne sait pas avant de décharger si une
    cabine tiendra en un ou deux endroits. Un emplacement s'ajoute quand on en
    trouve un de plus.

    Une cabine porte toujours au moins une ligne — vide tant qu'elle n'est rangée
    nulle part. Le cas courant se comporte donc exactement comme avant.
    """
    GAUCHE, MILIEU, DROITE = "G", "M", "D"
    PLACES = [(GAUCHE, "Gauche"), (MILIEU, "Milieu"), (DROITE, "Droite")]

    cabine = models.ForeignKey("Cabine", on_delete=models.CASCADE, related_name="occupations")
    #: Rang d'enregistrement, 1..n. Le premier est celui qu'affichent les écrans
    #: qui ne montrent qu'une position.
    numero = models.PositiveSmallIntegerField("n°", default=1)
    #: Facultatif : « parois », « plateau »… Dit ce qu'on trouvera à cet endroit
    #: quand une cabine est répartie.
    libelle = models.CharField("contenu", max_length=60, blank=True, default="")
    emplacement = models.ForeignKey(Emplacement, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="occupations")
    place = models.CharField("place", max_length=1, choices=PLACES, blank=True, default="")

    class Meta:
        verbose_name = "emplacement occupé"
        verbose_name_plural = "emplacements occupés"
        ordering = ["cabine", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["cabine", "numero"],
                                    name="occupation_numerotee_une_fois_par_cabine"),
            # Une place (emplacement, G/M/D) ne porte qu'une cabine à la fois.
            # Reprise de l'ancienne contrainte de `Cabine`, au bon niveau. La
            # condition sur le statut n'est plus exprimable ici : `envoyer()`
            # libère les emplacements, ils ne réservent donc plus rien.
            models.UniqueConstraint(
                fields=["emplacement", "place"],
                condition=models.Q(emplacement__isnull=False) & ~models.Q(place=""),
                name="place_occupee_par_une_seule_cabine",
            ),
        ]

    def clean(self):
        super().clean()
        if self.place and not self.emplacement_id:
            raise ValidationError({"place": "Une place ne se définit qu'avec un emplacement."})
        # Un emplacement à capacité illimitée n'a pas de place nommée.
        if self.place and self.emplacement_id and self.emplacement.illimite:
            raise ValidationError({"place": (
                f"L'emplacement {self.emplacement.code} est à capacité illimitée : "
                "il n'a pas de place G/M/D.")})

    def __str__(self):
        return f"{self.cabine.numero} @ {self.position or 'nulle part'}"

    @property
    def range(self):
        return self.emplacement_id is not None

    @property
    def position(self):
        """« AC5601·G » en mode places, « AC5601 » seul en capacité illimitée."""
        if not self.emplacement_id:
            return ""
        return f"{self.emplacement.code}·{self.place}" if self.place else self.emplacement.code

    @property
    def libelle_court(self):
        """« Emplacement 2 », ou « Emplacement 2 — plateau » si le contenu est dit."""
        base = f"Emplacement {self.numero}"
        return f"{base} — {self.libelle}" if self.libelle else base


class MouvementCabine(models.Model):
    """Journal de vie d'une cabine : rangements, transferts, statuts, envoi.

    Répond au « par qui, quand » : l'utilisateur et la cabine sont en SET_NULL comme
    tout l'historique du projet, mais leurs libellés sont recopiés ici, sinon la
    suppression d'un compte effacerait la trace de l'auteur.
    """
    CREATION, RANGEMENT, TRANSFERT, RETRAIT, STATUT, ENVOI = (
        "creation", "rangement", "transfert", "retrait", "statut", "envoi")
    #: Deux types de correction de saisie. La SUPPRESSION s'écrit juste avant que la
    #: cabine ne disparaisse : `cabine` passe alors à NULL, mais le numéro, le chantier
    #: et l'auteur sont recopiés dans la ligne — le journal explique la disparition.
    CORRECTION, SUPPRESSION = "correction", "suppression"
    TYPES = [(CREATION, "Création"), (RANGEMENT, "Rangement"), (TRANSFERT, "Transfert"),
             (RETRAIT, "Sortie d'emplacement"), (STATUT, "Changement de statut"),
             (ENVOI, "Envoi"), (CORRECTION, "Correction de fiche"),
             (SUPPRESSION, "Suppression de la cabine")]

    cabine = models.ForeignKey(Cabine, null=True, on_delete=models.SET_NULL, related_name="historique")
    cabine_numero = models.CharField(max_length=16)
    chantier = models.CharField(max_length=6, blank=True, default="")
    date = models.DateTimeField(auto_now_add=True)
    type = models.CharField(max_length=16, choices=TYPES)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mouvements_cabine")
    utilisateur_nom = models.CharField(max_length=150, blank=True, default="")
    statut_avant = models.CharField(max_length=16, blank=True, default="")
    statut_apres = models.CharField(max_length=16, blank=True, default="")
    depuis = models.CharField("position avant", max_length=160, blank=True, default="")
    vers = models.CharField("position après", max_length=160, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "mouvement de cabine"
        verbose_name_plural = "mouvements de cabine"
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.cabine_numero} — {self.get_type_display()} — {self.date:%d/%m/%Y %H:%M}"
