"""Modèle de données WMS Structa : les cabines, leurs emplacements, leur journal.

Invariants métier :
- une cabine est une ligne de `Cabine` ; où elle se trouve, c'est `Occupation` ;
- ce qui lui arrive s'écrit dans `MouvementCabine`, par `services_cabines` ;
- les références historiques sont en SET_NULL, jamais en CASCADE, et le journal
  recopie les libellés (numéro, position, auteur) : il reste lisible quand ce
  qu'il cite a disparu.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


class CasesDroits(models.Model):
    """Les cases de droits du WMS, communes au compte et au groupe.

    Une seule définition pour les deux fiches : un groupe porte exactement les
    cases que la fiche d'un compte, avec les mêmes noms et les mêmes
    explications. Deux listes recopiées finiraient par diverger, et une case
    du groupe ne commanderait plus rien.
    """

    # --- Les droits : une case par geste -------------------------------------
    #: Chaque case ouvre un geste, ou une famille de gestes qui vont ensemble,
    #: et rien d'autre. Elles ne valent que pour le rôle « Opérateur » :
    #: l'administrateur a tout, la lecture seule rien.
    #:
    #: Il y avait trois cases — cabines, référentiel, matières premières — qui
    #: ouvraient chacune un bloc entier : donner à quelqu'un le droit de
    #: condamner une place lui donnait aussi celui de supprimer un rack. La
    #: migration 0028 a reporté les anciennes cases sur les nouvelles, sauf
    #: « créer et supprimer des emplacements », que personne n'a reçu d'office.
    droit_cab_ranger = models.BooleanField(
        "entrer et ranger des cabines", default=False,
        help_text="Enregistrer une cabine annoncée par le fichier de production, la "
                  "ranger, la déplacer, lui ajouter un emplacement.")
    droit_cab_statut = models.BooleanField(
        "changer le statut d'une cabine", default=False,
        help_text="La mettre en quarantaine, lever la quarantaine. Sans cette case, "
                  "la question « quel est son état ? » qui suit un rangement est sautée.")
    droit_cab_envoyer = models.BooleanField(
        "sortir des cabines de l'entrepôt", default=False,
        help_text="Les envoyer sur chantier (en leur affectant le n° de chantier), et "
                  "remettre en stock une cabine revenue.")
    droit_cab_corriger = models.BooleanField(
        "corriger ou supprimer une fiche cabine", default=False,
        help_text="Changer le numéro, le chantier, le modèle d'une cabine mal saisie, "
                  "ou la supprimer.")
    droit_production = models.BooleanField(
        "importer le fichier de production", default=False,
        help_text="Remplacer la liste des cabines annoncées par la production "
                  "(écran « Fichier de production »).")
    droit_hors_fichier = models.BooleanField(
        "enregistrer une cabine absente du fichier de production", default=False,
        help_text="Avec un motif, écrit au journal. Demande aussi « entrer et ranger "
                  "des cabines ».")
    #: Une case à part pour les matières premières : l'équipe qui reçoit le
    #: verre n'est pas forcément celle qui range les cabines, et l'inverse.
    droit_mp = models.BooleanField(
        "entrer, sortir et déplacer des matières premières", default=False,
        help_text="Toutes les familles — vitrages, cartons… : entrée, sortie, changement "
                  "d'emplacement.")
    droit_mp_seuils = models.BooleanField(
        "régler les seuils d'alerte MP", default=False,
        help_text="Le stock sous lequel la cloche signale un code à recommander.")
    droit_empl_service = models.BooleanField(
        "mettre hors service, condamner une place", default=False,
        help_text="Mettre un emplacement hors service ou le remettre en service ; "
                  "condamner une place ou la rouvrir.")
    droit_empl_regler = models.BooleanField(
        "régler les emplacements", default=False,
        help_text="Leur code, ce qu'ils rangent (cabines ou matières premières), les "
                  "familles et codes MP qu'ils acceptent, leur description.")
    droit_empl_creer = models.BooleanField(
        "créer et supprimer des emplacements et des racks", default=False,
        help_text="Un emplacement ne se supprime de toute façon pas tant qu'une cabine "
                  "ou du stock MP y est posé.")
    droit_modeles = models.BooleanField(
        "régler la taille des modèles de cabine", default=False,
        help_text="Grand modèle — il prend tout l'emplacement — ou non.")


    #: Les droits, dans les groupes et l'ordre de la fiche du compte. La clé est
    #: le nom du champ sans « droit_ » : c'est elle que nomment les vues
    #: (`droit_ecriture`, `droits_par_action`) et l'écran (`peut('mp')`).
    GROUPES_DROITS = [
        ("Cabines", ["cab_ranger", "cab_statut", "cab_envoyer", "cab_corriger"]),
        ("Fichier de production", ["production", "hors_fichier"]),
        ("Matières premières", ["mp", "mp_seuils"]),
        ("Emplacements, racks et modèles",
         ["empl_service", "empl_regler", "empl_creer", "modeles"]),
    ]
    DROITS = [cle for _, cles in GROUPES_DROITS for cle in cles]

    @classmethod
    def libelle_droit(cls, cle):
        """Le nom de la case, tel que la fiche du compte l'affiche."""
        if cle not in cls.DROITS:
            return str(cle)
        return str(cls._meta.get_field(f"droit_{cle}").verbose_name)

    def cases_cochees(self):
        """Les clés des cases cochées sur CETTE fiche, dans l'ordre de la fiche."""
        return [c for c in self.DROITS if getattr(self, f"droit_{c}")]

    class Meta:
        abstract = True


class Groupe(CasesDroits):
    """Un groupe de comptes qui font le même travail : Caristes, Réception MP…

    Ses cases sont celles de la fiche d'un compte. Un compte appartient à un
    groupe au plus ; il a les droits du groupe, plus les cases cochées sur sa
    propre fiche — les exceptions. Retirer une case au groupe la retire à tous
    ses membres d'un coup, sauf à qui l'a en exception.

    Ce ne sont PAS les groupes de Django (« Can add cabine »…) : ceux-là
    règlent l'accès aux pages de l'administration, en anglais, et ne disent
    rien de ce qu'un cariste peut faire sur son téléphone.
    """

    nom = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "groupe"
        verbose_name_plural = "groupes"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Utilisateur(AbstractUser, CasesDroits):
    ADMIN, OPERATEUR, LECTURE = "admin", "operateur", "lecture"
    ROLES = [(ADMIN, "Administrateur"), (OPERATEUR, "Opérateur"), (LECTURE, "Lecture seule")]

    nom = models.CharField("nom affiché", max_length=150, blank=True)
    role = models.CharField("rôle", max_length=16, choices=ROLES, default=OPERATEUR)
    pin = models.CharField(max_length=32, blank=True)
    #: PROTECT : supprimer un groupe en SET_NULL retirerait leurs droits à tous
    #: ses membres, en silence. L'administration refuse, et les nomme.
    groupe = models.ForeignKey(
        Groupe, null=True, blank=True, on_delete=models.PROTECT, related_name="membres",
        help_text="Ses droits viennent du groupe. Les cases cochées plus bas s'y "
                  "ajoutent : ce sont ses droits en plus.")

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
        groupe = self.groupe if self.groupe_id else None
        return {c: bool(getattr(self, f"droit_{c}")
                        or (groupe is not None and getattr(groupe, f"droit_{c}")))
                for c in self.DROITS}

    def droits_du_groupe(self):
        """Les clés que le groupe donne — vide sans groupe."""
        return self.groupe.cases_cochees() if self.groupe_id else []

    def droits_en_plus(self):
        """Les cases cochées sur la fiche que le groupe ne donne pas déjà."""
        du_groupe = set(self.droits_du_groupe())
        return [c for c in self.cases_cochees() if c not in du_groupe]

    def peut(self, droit):
        """Le compte a-t-il ce droit ? Un nom inconnu vaut « non » : une faute de
        frappe dans une vue ferme le geste au lieu de l'ouvrir à tous."""
        return bool(self.droits_effectifs().get(droit))

    @property
    def est_administrateur(self):
        """Compte administrateur — au-delà des cases à cocher.

        Il a toutes les cases, et une opération qu'aucune case n'ouvre :
        « Repartir de zéro », qui remet l'outil à neuf. Ce n'est pas un geste
        de poste, c'est une décision d'exploitation.
        """
        return bool(self.is_superuser or self.role == self.ADMIN)

    def __str__(self):
        return self.nom or self.username


class Zone(models.Model):
    """Regroupement d'emplacements de cabines : « À ranger », « Sortie prod », etc.

    Se règle dans l'administration. Le `role` situe la zone dans le processus :
    c'est lui qui permet de dire « en attente de départ » plutôt que « en C001·G ».
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
    #: « gd » : deux places nommées, une cabine chacune (rang de rack) — ou une
    #: seule cabine qui prend l'emplacement entier, si c'est un grand modèle.
    #: « illimite » : pas de place nommée, autant de cabines que nécessaire
    #: (zone tampon « à ranger », aire de sortie prod…).
    GD, ILLIMITE = "gd", "illimite"
    MODES_PLACES = [(GD, "2 places (gauche, droite)"),
                    (ILLIMITE, "Capacité illimitée")]

    code = models.CharField(max_length=64, unique=True)
    #: Libellé libre, d'avant les zones : les écrans ne l'affichent qu'à défaut
    #: de `zone_cabine`.
    zone = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=255, blank=True)
    staging = models.BooleanField("zone de réception (à ranger)", default=False)
    actif = models.BooleanField(default=True)
    #: Pourquoi cet emplacement est hors service, depuis quand et par qui. Un
    #: booleen seul laisse la question sans reponse : devant un rack a moitie
    #: vide, « pourquoi AC550 ne prend rien ? » n'a alors que la memoire de
    #: quelqu'un pour reponse, et personne n'ose le remettre en service.
    motif_inactif = models.CharField("motif d'inactivité", max_length=255,
                                     blank=True, default="")
    actif_le = models.DateTimeField("activé/désactivé le", null=True, blank=True)
    actif_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="emplacements_actives", verbose_name="activé/désactivé par")
    #: PROTECT : supprimer une zone en SET_NULL « débranchait » ses emplacements
    #: en silence, et l'étape « attente de départ » se vidait sans que personne
    #: comprenne pourquoi. L'administration refuse désormais, et nomme les
    #: emplacements à rattacher ailleurs d'abord.
    zone_cabine = models.ForeignKey("Zone", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="emplacements", verbose_name="zone de cabines")
    mode_places = models.CharField("mode de rangement", max_length=16,
                                   choices=MODES_PLACES, default=GD)

    #: Ce que l'emplacement range : des cabines, ou des matières premières. Les
    #: deux mondes ne se mélangent pas — une palette de cartons posée là où le
    #: WMS attend une cabine fausse les deux stocks à la fois.
    #:
    #: Un emplacement MP a toujours TROIS places, gauche, milieu, droite : c'est
    #: la largeur d'une lisse de rack pour des palettes ou des chevalets. Le
    #: `mode_places` ne le concerne pas — il décrit le rangement des cabines, et
    #: reste tel quel pour le jour où l'emplacement y reviendrait.
    #:
    #: Ce qu'il accepte se règle ensuite, du plus large au plus fin :
    #: - `familles` vide : toutes les familles ; sinon, celles-là seulement ;
    #: - `codes_acceptes` vide : tous les codes de ces familles ; sinon, ces
    #:   codes-là seulement — et ils appartiennent aux familles acceptées.
    #:
    #: Un code de famille à la place de l'usage (« vitrage ») est un raccourci :
    #: « matières premières, cette famille seulement ». `save()` le traduit.
    CABINES, MP = "cabines", "mp"
    USAGES = [(CABINES, "Cabines"), (MP, "Matières premières")]
    #: Les raccourcis d'avant les familles réglables : un emplacement « de
    #: vitrages » est un emplacement MP qui n'accepte que les vitrages.
    MP_CARTON, MP_VITRAGE = "carton", "vitrage"
    usage = models.CharField("ce qu'il range", max_length=16, choices=USAGES,
                             default=CABINES, db_index=True)

    familles = models.ManyToManyField(
        "FamilleMP", blank=True, related_name="emplacements",
        verbose_name="familles acceptées",
        help_text="Vide : toutes les familles de matières premières. Sinon, seules "
                  "celles-ci y entrent.")

    #: Les codes qu'un emplacement MP accepte. VIDE : tous ceux de ses familles —
    #: c'est le cas ordinaire, et il le reste tant qu'on ne réserve pas
    #: l'emplacement à un ou plusieurs codes.
    #:
    #: Une réservation ne déplace rien : un code déjà posé qui n'en fait plus
    #: partie peut toujours sortir ou changer d'emplacement, il ne peut plus y
    #: ENTRER. Elle se règle par `services_mp.regler_codes`, qui vérifie la
    #: famille ; l'administration passe par la même règle.
    codes_acceptes = models.ManyToManyField(
        "ArticleMP", blank=True, related_name="emplacements_reserves",
        verbose_name="codes acceptés",
        help_text="Vide : tous les codes de ses familles. Sinon, seuls ces codes y entrent.")

    @property
    def est_mp(self):
        """Emplacement de matières premières ?"""
        return self.usage != self.CABINES

    def codes_familles(self):
        """Les codes des familles acceptées, dans l'ordre d'affichage — [] : toutes.

        Lit le préchargement de la vue quand il existe : le plan d'un rack en
        demande pour chaque case."""
        if not self.pk or not self.est_mp:
            return []
        return [f.code for f in sorted(self.familles.all(), key=lambda f: (f.ordre, f.nom))]

    def accepte_famille(self, code):
        """Cette famille entre-t-elle ici ? Toujours, s'il n'en restreint aucune."""
        familles = self.codes_familles()
        return not familles or code in familles

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

    def clean(self):
        """Ce que range l'emplacement ne change que s'il est vide — y compris par
        l'administration, qui ne passe ni par l'écran ni par l'API.

        La règle est celle du réglage en nombre (`services_mp.bilan_usage`) :
        une seule définition, la même phrase partout.

        Le code est normalisé ICI, avant le contrôle d'unicité : « ac550 »
        passait le contrôle de l'administration (la base porte « AC550 »), puis
        `save()` le mettait en majuscules et la contrainte sautait en erreur 500.
        """
        super().clean()
        self.code = (self.code or "").strip().upper()
        if not self.pk:
            return
        avant = Emplacement.objects.filter(pk=self.pk).first()
        if avant is None or (avant.usage, avant.mode_places) == (self.usage, self.mode_places):
            return
        from . import services_mp     # import tardif : services_mp importe ce module
        choix = (self.usage if self.usage != self.CABINES
                 else ("cabines-illimite" if self.mode_places == self.ILLIMITE else "cabines-gd"))
        if choix != services_mp.choix_de(avant):
            refus = services_mp.refus_changement_usage(avant, choix)
            if refus:
                raise ValidationError({"usage": refus})

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        # Le raccourci : un code de famille à la place de l'usage.
        famille_seule = None
        if self.usage not in (self.CABINES, self.MP):
            famille_seule, self.usage = self.usage, self.MP
            if not FamilleMP.objects.filter(code=famille_seule).exists():
                raise ValidationError({"usage": f"Usage inconnu : « {famille_seule} »."})
        super().save(*args, **kwargs)
        if famille_seule:
            self.familles.set(FamilleMP.objects.filter(code=famille_seule))

    def __str__(self):
        return self.code


class Cabine(models.Model):
    NORMALE, EXPRESS, SALON, OCCASION = "normale", "express", "salon", "occasion"
    TYPES = [(NORMALE, "Normale"), (EXPRESS, "Express"),
             (SALON, "Salon"), (OCCASION, "Occasion")]

    #: Types qui circulent sans n° de chantier. Une cabine de salon ou d'occasion
    #: n'a pas de client tant qu'elle n'est pas vendue : exiger un chantier dès la
    #: création interdirait de la faire entrer en stock.
    #: L'exemption s'arrête là : l'envoi exige un chantier pour TOUS les types
    #: (voir services_cabines.envoyer) — c'est ce qui garantit qu'aucune cabine
    #: ne quitte l'entrepôt sans être rattachée à une commande.
    SANS_CHANTIER = {EXPRESS, SALON, OCCASION}

    #: Le statut dit l'ÉTAT de la cabine, jamais où elle est. « Rangé » et
    #: « Non rangé » n'en font délibérément pas partie : ils se déduisent de
    #: l'emplacement (voir `rangee`). Les stocker en double ouvrirait la porte à
    #: une cabine marquée « Rangé » qui n'est nulle part — et plus personne ne
    #: saurait laquelle des deux informations croire.
    #: « Levée de quarantaine » a été retiré : une quarantaine levée rend la cabine
    #: conforme — c'est exactement ce que dit « Conforme ». En faire un statut distinct
    #: créait un troisième état qui ne disait rien de plus sur la cabine, et
    #: laissait des cabines parfaitement saines marquées d'un libellé alarmant
    #: pendant des semaines. Le passage par la quarantaine reste lisible : il est
    #: écrit dans le journal, avec son motif et sa date.
    LIBRE, QUARANTAINE, ENVOYE = ("libre", "quarantaine", "envoye")
    #: Le CODE stocké ne bouge pas — « libre » reste « libre » en base, et tout
    #: l'historique déjà écrit reste lisible. Seul le libellé affiché change :
    #: « Conforme » est le mot du terrain, celui de la fiche de contrôle.
    STATUTS = [(LIBRE, "Conforme"), (QUARANTAINE, "En quarantaine"),
               (ENVOYE, "Envoyée")]

    #: Deux places, plus trois. Un emplacement tenait trois cabines quand les
    #: modèles étaient plus petits ; il en tient deux aujourd'hui, et une seule
    #: quand c'est un grand modèle — voir `ModeleCabine`. « Milieu » a disparu :
    #: le garder « au cas où » aurait laissé l'écran proposer une place qui
    #: n'existe pas, et un cariste y aurait rangé une cabine.
    GAUCHE, DROITE = "G", "D"
    PLACES = [(GAUCHE, "Gauche"), (DROITE, "Droite")]

    #: Le dernier groupe va de 1 à 3 chiffres. Il en exigeait exactement deux, et
    #: refusait donc les 94 cabines « 25_49_400 » du fichier de production : une
    #: semaine qui dépasse 99 cabines existe, la règle ne le prévoyait pas. Les
    #: deux premiers groupes restent stricts — ce sont l'année et la semaine.
    MOTIF_NUMERO = r"^\d{2}_\d{2}_\d{1,3}$"

    #: Un chantier s'écrit « 251213 ». Il se décline en lots quand la commande
    #: part en plusieurs fois : « 251213-1 », « 251213-2 ». Les deux formes
    #: viennent du fichier de production — au premier import, 110 lignes sur
    #: 2 264 portaient un lot. N'accepter que six chiffres les rejetait toutes,
    #: et obligeait à retaper à la main un numéro que le fichier donnait déjà.
    #: Le lot tient sur deux chiffres : le fichier n'en a jamais montré plus d'un,
    #: et « 251213-100 » n'a pas de sens pour une commande de cabines. Il commence
    #: à 1 — « 251213-0 » est une faute de frappe, autant la refuser à la porte
    #: plutôt que de créer un lot fantôme à côté du vrai.
    MOTIF_CHANTIER = r"^\d{6}(-[1-9]\d?)?$"
    AIDE_CHANTIER = ("Six chiffres, éventuellement suivis du lot : "
                     "251213 ou 251213-1.")
    #: 9 = 6 chiffres + tiret + 2 chiffres. Une seule constante, pour que les
    #: trois champs qui stockent un chantier ne divergent pas.
    TAILLE_CHANTIER = 9

    numero = models.CharField(
        max_length=16, unique=True,
        validators=[RegexValidator(MOTIF_NUMERO, "Format attendu : xx_xx_xx (jusqu'à 3 chiffres à la fin)")])
    # Facultatif en base : une cabine express se range sans chantier. L'obligation est
    # portée par clean() pour les cabines normales, et par le service pour la sortie.
    chantier = models.CharField(max_length=TAILLE_CHANTIER, blank=True, default="",
                                validators=[RegexValidator(MOTIF_CHANTIER, AIDE_CHANTIER)])
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

    @property
    def prend_tout_l_emplacement(self):
        """Cette cabine occupe-t-elle l'emplacement entier ?

        Lu à chaque rangement plutôt que stocké sur la cabine : la taille est une
        propriété du MODÈLE, et le jour où un modèle est reclassé, les cabines
        déjà en stock doivent suivre. Une copie sur la fiche aurait figé la règle
        au moment de l'entrée.
        """
        return ModeleCabine.est_grand(self.modele)

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


class ModeleCabine(models.Model):
    """La taille d'un modèle de cabine, et rien d'autre.

    Deux cabines tiennent dans un emplacement — une seule si c'est un grand
    modèle. La liste des grands modèles ne peut pas vivre dans le code : le
    catalogue bouge, et « COLLAB » était déjà annoncé comme grand modèle avant
    d'apparaître dans un fichier de production. Elle se règle donc à l'écran.

    Un modèle inconnu compte pour NORMAL. C'est le choix qui laisse ranger : un
    modèle nouveau apparaît dans l'écran des modèles au premier import, marqué
    normale, et se corrige d'une touche. L'inverse — refuser tout modèle non
    déclaré — bloquerait l'entrepôt un lundi matin sur une ligne de tableur.

    `cle` sert aux comparaisons, `nom` à l'affichage. Le fichier écrit
    « XL (2modules) » avec une minuscule au milieu : chercher sur le nom tel
    quel ferait de « XL (2MODULES) » un second modèle, réglé séparément.
    """

    nom = models.CharField("modèle", max_length=120)
    cle = models.CharField("clé de comparaison", max_length=120, unique=True)
    grand = models.BooleanField("prend tout l'emplacement", default=False)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)
    modifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="modeles_regles", verbose_name="réglé par")

    class Meta:
        verbose_name = "modèle de cabine"
        verbose_name_plural = "modèles de cabine"
        ordering = ["nom"]

    @staticmethod
    def normaliser(nom):
        """« xl (2modules) » et « XL  (2MODULES) » désignent le même modèle."""
        return " ".join(str(nom or "").split()).upper()

    def save(self, *args, **kwargs):
        self.nom = " ".join(str(self.nom or "").split())
        self.cle = self.normaliser(self.nom)
        super().save(*args, **kwargs)

    @classmethod
    def grands(cls):
        """Les clés des modèles qui prennent tout l'emplacement."""
        return set(cls.objects.filter(grand=True).values_list("cle", flat=True))

    @classmethod
    def est_grand(cls, nom):
        cle = cls.normaliser(nom)
        if not cle:
            return False
        return cls.objects.filter(cle=cle, grand=True).exists()

    def __str__(self):
        return f"{self.nom} — {'tout l’emplacement' if self.grand else 'une place'}"


class Occupation(models.Model):
    """Un emplacement occupé par une cabine.

    Une cabine occupe UN emplacement dans l'immense majorité des cas. Il arrive
    qu'elle en occupe plusieurs — un morceau posé ailleurs faute de place dans la
    l'emplacement. Tant que la position vivait sur la cabine, il fallait
    choisir : soit
    écraser la première position par la seconde, soit créer une deuxième fiche et
    perdre l'unité de la cabine. Cette table tranche : la cabine reste une, ses
    emplacements sont une liste.

    Rien n'est déclaré à l'avance : on ne sait pas avant de décharger si une
    cabine tiendra en un ou deux endroits. Un emplacement s'ajoute quand on en
    trouve un de plus.

    Une cabine porte toujours au moins une ligne — vide tant qu'elle n'est rangée
    nulle part. Le cas courant se comporte donc exactement comme avant.
    """
    #: Les places STOCKABLES, qui ne sont pas les places CHOISISSABLES. « T »
    #: n'apparaît dans aucun écran de choix : personne ne décide qu'une cabine
    #: prend tout l'emplacement, c'est son modèle qui le décide. Mais il faut
    #: l'écrire quelque part, et une place nommée le dit mieux qu'une place vide
    #: — laquelle veut déjà dire « emplacement à capacité illimitée ».
    #: La contrainte d'unicité (emplacement, place) fait le reste : deux cabines
    #: ne peuvent pas prendre le même emplacement entier.
    GAUCHE, DROITE, ENTIER = "G", "D", "T"
    #: Le code stocké reste « T » — l'historique déjà écrit doit rester lisible.
    #: Seul le libellé a changé : le mot d'avant ne fait pas partie du
    #: vocabulaire de la maison, c'est « emplacement » qu'on dit devant le rack.
    PLACES = [(GAUCHE, "Gauche"), (DROITE, "Droite"), (ENTIER, "Tout l'emplacement")]

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
            # Une place (emplacement, gauche/droite) ne porte qu'une cabine à la fois.
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
        # Un emplacement de matières premières ne porte pas de cabine — y compris
        # par l'administration, où ce formulaire se remplit à la main.
        if self.emplacement_id and self.emplacement.est_mp:
            raise ValidationError({"emplacement": (
                f"{self.emplacement.code} range des matières premières : pas de "
                "cabine.")})
        if self.place and not self.emplacement_id:
            raise ValidationError({"place": "Une place ne se définit qu'avec un emplacement."})
        # Un emplacement à capacité illimitée n'a pas de place nommée.
        if self.place and self.emplacement_id and self.emplacement.illimite:
            raise ValidationError({"place": (
                f"L'emplacement {self.emplacement.code} est à capacité illimitée : "
                "il n'a pas de place gauche ou droite.")})

    def __str__(self):
        return f"{self.cabine.numero} @ {self.position or 'nulle part'}"

    @property
    def range(self):
        return self.emplacement_id is not None

    @property
    def position(self):
        """« AC5601·G » quand la cabine partage l'emplacement, « AC5601 » seul
        quand elle le prend en entier — ou en capacité illimitée.

        Le suffixe « ·T » n'apparaît nulle part. Il ne désigne pas un endroit, il
        dit « partout » : « AC550·T » se lisait comme un code de rack qui n'existe
        sur aucune étiquette, et on le cherchait. L'étendue se dit sur la fiche de
        l'emplacement — « Tout l'emplacement » — là où elle a un sens.
        """
        if not self.emplacement_id:
            return ""
        if not self.place or self.place == self.ENTIER:
            return self.emplacement.code
        return f"{self.emplacement.code}·{self.place}"

    @property
    def libelle_court(self):
        """« Emplacement 2 », ou « Emplacement 2 — plateau » si le contenu est dit."""
        base = f"Emplacement {self.numero}"
        return f"{base} — {self.libelle}" if self.libelle else base


class PlaceCondamnee(models.Model):
    """Une place hors service dans un emplacement par ailleurs utilisable.

    Le cas qui l'a fait naître : un pilier devant la gauche de AC550. La droite
    reçoit toujours une cabine. Désactiver l'emplacement entier aurait retiré du
    stock une place saine, et personne n'aurait su laquelle des deux posait
    problème.

    Le motif est OBLIGATOIRE, comme pour une quarantaine et pour la même raison :
    une place condamnée sans raison écrite reste condamnée des mois, parce que
    plus personne ne sait s'il y avait un obstacle ou une erreur de manipulation.

    Une cabine déjà posée là n'est jamais déplacée par le WMS : le service refuse
    de condamner une place occupée et dit quelle cabine s'y trouve. Écrire une
    position que personne n'a vérifiée devant le rack serait pire que le refus.
    """

    #: Les places condamnables sont celles qu'on peut choisir : gauche et droite.
    #: « Tout l'emplacement » n'en est pas une — c'est ce que prend un grand
    #: modèle, et pour le retirer du stock on désactive l'emplacement.
    #: « Milieu » n'existe que sur un emplacement de matières premières : le
    #: service le refuse ailleurs (voir `services_cabines.condamner_place`).
    PLACES = [(Occupation.GAUCHE, "Gauche"), ("M", "Milieu"),
              (Occupation.DROITE, "Droite")]

    emplacement = models.ForeignKey(Emplacement, on_delete=models.CASCADE,
                                    related_name="places_condamnees")
    place = models.CharField(max_length=2, choices=PLACES)
    motif = models.CharField(max_length=255)
    cree_le = models.DateTimeField("condamnée le", auto_now_add=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="places_condamnees", verbose_name="condamnée par")

    class Meta:
        verbose_name = "place condamnée"
        verbose_name_plural = "places condamnées"
        ordering = ["emplacement__code", "place"]
        constraints = [models.UniqueConstraint(fields=["emplacement", "place"],
                                               name="place_condamnee_unique")]

    def __str__(self):
        return f"{self.emplacement.code}·{self.place} — {self.motif}"


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
    # Photographie du chantier au moment du mouvement. Même taille que le champ
    # d'origine : plus court, PostgreSQL refuserait d'écrire « 251213-1 » et le
    # mouvement échouerait après que la cabine a bougé.
    chantier = models.CharField(max_length=Cabine.TAILLE_CHANTIER, blank=True, default="")
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

class CabineAttendue(models.Model):
    """Spécifications des cabines à venir, importées du fichier de production.

    Cette table ne dit PAS ce qui est en stock : elle dit ce qu'on ATTEND, et à
    quoi chaque cabine ressemble. Une cabine entre en stock quand elle arrive
    physiquement ; l'opérateur saisit alors son numéro, et tout le reste vient
    d'ici — plus besoin de lire la fiche papier collée dessus.

    Deux niveaux de champs, délibérément :

    - **explicites** : ceux qu'une requête cherche ou qu'une `Cabine` reprend à
      l'entrée. Ils ont leur colonne, leur index, leur validateur.
    - **`specifications`** : le reste de la ligne, colonne par colonne, tel quel.
      Le fichier de production compte 67 colonnes tenues à la main ; en figer 45
      dans le schéma imposerait une migration à chaque colonne ajoutée ou
      renommée. Rien dans la logique du WMS ne s'appuie dessus : c'est de la
      donnée à afficher. Voir `docs/requetes-sql.sql` pour l'interroger en SQL.

    Le montant net produit n'est jamais importé. L'entrepôt n'en a aucun usage,
    et le compte de test est partagé entre tous les testeurs.
    """

    numero = models.CharField(
        "n° de cabine", max_length=16, unique=True,
        validators=[RegexValidator(Cabine.MOTIF_NUMERO,
                                   "Format attendu : xx_xx_xx (jusqu'à 3 chiffres à la fin)")])
    #: Colonne « NUM UNIQUE » du fichier : un compteur de production (1133), ou
    #: une référence fournisseur (AF-3164). Trois formats y cohabitent, il ne peut
    #: donc pas servir de clé — mais on le cherche, il est parfois le seul repère
    #: dont l'atelier dispose.
    num_unique = models.CharField("n° unique production", max_length=32, blank=True,
                                  default="", db_index=True)

    chantier = models.CharField(max_length=Cabine.TAILLE_CHANTIER, blank=True, default="",
                                validators=[RegexValidator(Cabine.MOTIF_CHANTIER,
                                            Cabine.AIDE_CHANTIER)])
    #: Le chantier tel que le classeur l'écrit, conservé même quand il est
    #: enregistrable — c'est lui qu'on cherche quand l'atelier cite une référence
    #: fournisseur. Il reste utile pour les formes que le WMS ne sait pas stocker
    #: (une lettre, un espace) : `chantier` est alors vide, l'écran d'import le
    #: signale et l'opérateur saisit le numéro à l'entrée de la cabine.
    chantier_brut = models.CharField("chantier tel qu'écrit", max_length=32, blank=True,
                                     default="")

    gamme = models.CharField(max_length=60, blank=True, default="")
    modele = models.CharField(max_length=120, blank=True, default="")
    quantite = models.PositiveSmallIntegerField("quantité", default=1)
    semaine_production = models.CharField("semaine de production", max_length=16,
                                          blank=True, default="")
    jour = models.CharField(max_length=16, blank=True, default="")
    semaine_estimee = models.CharField("semaine estimée", max_length=16, blank=True,
                                       default="")

    revendeur = models.CharField(max_length=120, blank=True, default="")
    client = models.CharField(max_length=120, blank=True, default="")
    tissu_bk = models.CharField("tissu BK", max_length=32, blank=True, default="")
    tissu_aq = models.CharField("tissu AQ", max_length=32, blank=True, default="")
    tissu_ext = models.CharField("tissu extérieur", max_length=32, blank=True, default="")
    fond_cabine = models.CharField("fond de cabine", max_length=64, blank=True, default="")

    specifications = models.JSONField("spécifications", default=dict, blank=True)

    fichier = models.CharField("fichier d'origine", max_length=200, blank=True, default="")
    importe_le = models.DateTimeField("importé le", auto_now=True)
    importe_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="imports_cabines", verbose_name="importé par")

    class Meta:
        verbose_name = "cabine attendue"
        verbose_name_plural = "cabines attendues"
        ordering = ["numero"]

    def save(self, *args, **kwargs):
        self.numero = (self.numero or "").strip()
        # `full_clean` n'est pas appelé par `save()` : sans cela un numéro hors
        # format entrerait en base par l'import, et le WMS refuserait ensuite la
        # cabine qu'il a lui-même annoncée.
        self.clean_fields()
        super().save(*args, **kwargs)

    @property
    def chantier_a_saisir(self):
        """Vrai dès qu'il n'y a pas de chantier utilisable pour cette cabine.

        Deux cas, et non un seul : le classeur portait une forme que le WMS ne
        sait pas stocker, ou il ne portait rien du tout. La version précédente ne
        regardait que la première — une ligne sans chantier n'affichait donc aucun
        champ à l'entrée, et la création échouait sur un 400 sans que l'écran ait
        jamais proposé de le saisir. C'est le seul endroit où la saisie manuelle
        d'un chantier reste ouverte : partout ailleurs, il vient du fichier.
        """
        return not self.chantier

    def champs_cabine(self):
        """Les champs à recopier dans la `Cabine` créée à l'entrée.

        Un seul endroit décide de cette correspondance : l'écran d'entrée et le
        service d'import la lisaient sinon chacun de leur côté, et un champ ajouté
        ici était oublié là.
        """
        return {
            "numero": self.numero,
            "chantier": self.chantier,
            "modele": self.modele,
            "revendeur": self.revendeur,
            "client": self.client,
            "tissu_bk": self.tissu_bk,
            "tissu_aq": self.tissu_aq,
            "fond_cabine": self.fond_cabine,
        }

    def __str__(self):
        return f"{self.numero} — attendue (chantier {self.chantier or self.chantier_brut or '—'})"


# --- Matières premières : vitrages et cartons --------------------------------
#
# Trois tables, sur le modèle des cabines : la BASE des codes (ce qui peut
# exister), le STOCK (ce qui est là, place par place) et le JOURNAL (ce qui
# s'est passé). Le stock ne s'écrit que par `services_mp`, qui écrit le journal
# dans la même transaction.


def normaliser_code_mp(texte):
    """« vitr.8 », « VITR 8 », « Vitr-8 » → « VITR8 ».

    Ce qu'on tape au poste ne ressemble jamais tout à fait au code de la base :
    un point oublié, un x minuscule, une espace. On compare donc des clés
    réduites aux lettres et aux chiffres, en majuscules. Le signe « × » vaut
    « X » : il apparaît quand une dimension est recopiée d'un document.
    """
    import unicodedata
    texte = str(texte or "").replace("×", "X")
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return "".join(c for c in texte.upper() if c.isalnum())


class FamilleMP(models.Model):
    """Une famille de matières premières : Vitrage, Carton — et celles qu'on ajoute.

    Elle se crée dans l'administration. Son CODE est ce que retiennent les
    codes MP et le journal : il ne change plus une fois créé. Tout le reste —
    nom, pluriel, couleur — se change à volonté, l'écran suit.
    """

    code = models.SlugField(
        "code", max_length=16, unique=True,
        help_text="Court, en minuscules, sans espace ni accent : « quincaillerie ». "
                  "Il ne change plus une fois créé : le stock et le journal le citent.")
    nom = models.CharField("nom", max_length=60, help_text="Au singulier : « Vitrage ».")
    pluriel = models.CharField(
        "au pluriel", max_length=60,
        help_text="« Vitrages ». Il sert aux titres et aux quantités : « 3 vitrages ».")
    exemple = models.CharField(
        "exemple de recherche", max_length=80, blank=True, default="",
        help_text="Écrit en gris dans le champ de recherche : « Ex. vitr.445 ou 445 ».")
    couleur = models.CharField(
        max_length=7, default="#5B6B7A",
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Une couleur au format #RRVVBB.")],
        help_text="La couleur de sa pastille, sur le plan des racks et dans les listes.")
    ordre = models.PositiveIntegerField("ordre d'affichage", default=0)
    actif = models.BooleanField(
        "active", default=True,
        help_text="Décochée : elle n'est plus proposée pour un nouveau code. Ce qui "
                  "existe reste, et se range comme avant.")

    class Meta:
        verbose_name = "famille MP"
        verbose_name_plural = "familles MP"
        ordering = ["ordre", "nom"]

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().lower()

    def __str__(self):
        return self.nom


class ArticleMP(models.Model):
    """Un code élément de matière première : un vitrage ou un carton.

    C'est la base dans laquelle on pioche à l'entrée : le code se choisit dans
    une liste qui se resserre à mesure qu'on tape, il ne s'invente pas. Un code
    tapé à la main finit toujours par exister en deux orthographes, et le stock
    se coupe en deux sans que personne s'en aperçoive.

    `ancienne_generation` ne bloque rien : du stock d'ancienne génération reste
    à écouler, et il faut pouvoir le ranger et le sortir. L'écran demande
    seulement de CONFIRMER une entrée — c'est là que l'erreur se fait, en
    prenant le code voisin dans la liste.
    """

    #: Les deux familles livrées. Les autres se créent dans l'administration
    #: (`FamilleMP`) : le champ ci-dessous en porte le code.
    VITRAGE, CARTON = "vitrage", "carton"

    code = models.CharField("code élément", max_length=64, unique=True)
    famille = models.CharField(max_length=16, help_text="Le code d'une famille MP.")
    designation = models.CharField("désignation", max_length=200, blank=True, default="")
    fournisseur = models.CharField(max_length=60, blank=True, default="")
    #: Le n° de l'article dans le fichier des matières premières (« 434 »).
    #: On le cite au téléphone ; il se cherche donc comme le code.
    numero = models.CharField("n° article", max_length=20, blank=True, default="")
    #: Les autres noms du même élément, séparés par « · » : réf. fournisseur,
    #: libellé fournisseur, marquage peint sur la palette. Tous se cherchent.
    references = models.CharField("autres références", max_length=255, blank=True,
                                  default="")
    #: Quantité d'une palette pleine. Proposée d'une touche à l'entrée, jamais
    #: écrite d'office : une palette entamée existe aussi.
    colisage = models.PositiveIntegerField(null=True, blank=True)
    #: Le seuil d'alerte : quand le stock total du code passe EN DESSOUS, la
    #: cloche des écrans le signale. Vide : pas d'alerte pour ce code. Le nom
    #: du champ date du fichier d'origine (« seuil de réappro ») ; c'est la
    #: même chose, dite comme on la règle au poste.
    seuil_reappro = models.PositiveIntegerField(
        "seuil d'alerte", null=True, blank=True,
        help_text="Alerte quand le stock total du code passe en dessous. Vide : pas d'alerte.")
    ancienne_generation = models.BooleanField("ancienne génération", default=False)
    #: Un code retiré de la base ne se propose plus à l'entrée. Il n'est pas
    #: supprimé : le journal et le stock restant le citent encore.
    actif = models.BooleanField(default=True)

    cle = models.CharField("clé de recherche", max_length=64, db_index=True,
                           editable=False, default="")
    cle_references = models.CharField(max_length=300, editable=False, default="")
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "code MP"
        verbose_name_plural = "codes MP (base vitrages et cartons)"
        ordering = ["famille", "code"]

    def clean(self):
        """Le code normalisé AVANT le contrôle d'unicité de l'administration.

        Sans cela, « vitr.445x2072.bp » passait le contrôle — la base porte
        « VITR.445X2072.BP » — puis `save()` le mettait en majuscules et la
        contrainte d'unicité sautait en erreur 500 au lieu d'un message clair.
        """
        super().clean()
        self.code = " ".join(str(self.code or "").split()).upper()
        if self.famille and not FamilleMP.objects.filter(code=self.famille).exists():
            raise ValidationError({"famille": f"Famille inconnue : « {self.famille} »."})

    def save(self, *args, **kwargs):
        self.code = " ".join(str(self.code or "").split()).upper()
        self.cle = normaliser_code_mp(self.code)
        self.cle_references = "|".join(
            normaliser_code_mp(r) for r in str(self.references or "").split("·")
            if normaliser_code_mp(r))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code


class StockMP(models.Model):
    """Ce qu'il y a, maintenant, sur une place d'un emplacement MP.

    Une ligne par code et par place : deux palettes du même carton posées sur la
    même place n'en font qu'une, dont la quantité s'additionne. Plusieurs codes
    peuvent partager une place — une palette sur une autre, deux paquets de
    verre sur le même chevalet.

    PROTECT des deux côtés : supprimer un emplacement ou un code qui porte du
    stock le ferait disparaître sans trace. Le service refuse avant, et le dit.
    """

    GAUCHE, MILIEU, DROITE = "G", "M", "D"
    PLACES = [(GAUCHE, "Gauche"), (MILIEU, "Milieu"), (DROITE, "Droite")]

    emplacement = models.ForeignKey(Emplacement, on_delete=models.PROTECT,
                                    related_name="stock_mp")
    place = models.CharField(max_length=1, choices=PLACES)
    article = models.ForeignKey(ArticleMP, on_delete=models.PROTECT, related_name="stock")
    quantite = models.PositiveIntegerField("quantité")
    entre_le = models.DateTimeField("entré le", auto_now_add=True)
    modifie_le = models.DateTimeField("dernier mouvement", auto_now=True)

    class Meta:
        verbose_name = "ligne de stock MP"
        verbose_name_plural = "stock MP"
        ordering = ["emplacement__code", "place", "article__code"]
        constraints = [
            models.UniqueConstraint(fields=["emplacement", "place", "article"],
                                    name="stock_mp_un_code_par_place"),
            # Une ligne à zéro n'a pas de sens : elle s'efface à la dernière sortie.
            models.CheckConstraint(condition=models.Q(quantite__gt=0),
                                   name="stock_mp_quantite_positive"),
        ]

    @property
    def position(self):
        return f"{self.emplacement.code}·{self.place}"

    def __str__(self):
        return f"{self.article.code} × {self.quantite} @ {self.position}"


class MouvementMP(models.Model):
    """Journal des matières premières : chaque entrée, chaque sortie, chaque
    changement d'emplacement.

    Comme le journal des cabines, il recopie ce qu'il cite — code, position,
    auteur — pour rester lisible quand le code ou l'emplacement a disparu.
    `reste` dit ce qui restait à cette place après le geste : un écart
    d'inventaire se remonte alors ligne par ligne, sans rien recalculer.

    Un changement d'emplacement est UNE ligne, et non une sortie suivie d'une
    entrée : `emplacement`, `position` et `reste` disent où le stock est
    arrivé, `origine` et `reste_origine` d'où il est parti. Écrit en deux
    lignes, il compterait comme une consommation dans « ce qui est sorti ce
    mois-ci », et la palette déplacée passerait pour une palette utilisée.
    """

    ENTREE, SORTIE, TRANSFERT = "entree", "sortie", "transfert"
    TYPES = [(ENTREE, "Entrée"), (SORTIE, "Sortie"),
             (TRANSFERT, "Changement d'emplacement")]

    date = models.DateTimeField(auto_now_add=True)
    type = models.CharField(max_length=16, choices=TYPES)
    article = models.ForeignKey(ArticleMP, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="mouvements")
    article_code = models.CharField("code élément", max_length=64)
    famille = models.CharField(max_length=16)
    emplacement = models.ForeignKey(Emplacement, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="mouvements_mp")
    position = models.CharField(max_length=80)
    quantite = models.PositiveIntegerField("quantité")
    reste = models.PositiveIntegerField("reste à cette place")
    #: Changement d'emplacement seulement : la position de départ, et ce qui y
    #: restait de ce code après le geste.
    origine = models.CharField("depuis", max_length=80, blank=True, default="")
    reste_origine = models.PositiveIntegerField("reste au départ", null=True, blank=True)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mouvements_mp")
    utilisateur_nom = models.CharField(max_length=150, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "mouvement MP"
        verbose_name_plural = "mouvements MP"
        ordering = ["-date", "-id"]

    def __str__(self):
        ou = f"{self.origine} → {self.position}" if self.origine else self.position
        return (f"{self.get_type_display()} {self.quantite} × {self.article_code} "
                f"— {ou} — {self.date:%d/%m/%Y %H:%M}")
