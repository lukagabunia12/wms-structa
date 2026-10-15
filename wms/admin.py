import unicodedata
from datetime import datetime

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.admin.exceptions import NotRegistered
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group as GroupeDjango
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.db.models import Count, Max, Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from . import connexion, services_mp, services_remise
from .models import (ArticleMP, Cabine, Emplacement, FamilleMP, Groupe, MouvementCabine,
                     MouvementMP, Occupation, StockMP, Utilisateur, Zone)


#: Les trois phrases à recopier pour repartir de zéro. Elles sont ici, en clair :
#: l'écran les affiche, il n'y a rien de secret. Ce qu'on achète n'est pas le
#: secret, c'est le temps de lire ce qu'on est en train de faire.
MOT_CONFIRMER = "confirmer"
PHRASE_ENGAGEMENT = "Oui je suis d'accord et je comprends"

#: Les formats de date acceptés pour la deuxième phrase. Le jour même, écrit
#: comme on l'écrit en France d'abord, et comme l'écrivent les machines ensuite.
#: N'en accepter qu'un seul transformerait un garde-fou en devinette.
FORMATS_DATE = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"]


def _normaliser(texte):
    """Casse, accents, apostrophes et espaces en trop mis de côté.

    L'apostrophe compte : Word et les claviers de téléphone produisent une
    apostrophe typographique (’), le clavier du poste une apostrophe droite (').
    Refuser l'une des deux ferait échouer une phrase correctement recopiée.
    """
    texte = (texte or "").strip().replace("\u2019", "'").replace("\u02bc", "'")
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", texte)
                          if unicodedata.category(c) != "Mn")
    return " ".join(sans_accent.lower().split()).rstrip(".!")


def _date_du_jour_saisie(texte):
    """Vrai si `texte` est bien la date d'aujourd'hui, dans un format admis."""
    texte = (texte or "").strip()
    aujourdhui = timezone.localdate()
    for forme in FORMATS_DATE:
        try:
            if datetime.strptime(texte, forme).date() == aujourdhui:
                return True
        except ValueError:
            continue
    return False


#: Les anciens profils prêts à l'emploi. Ils sont devenus des GROUPES — la
#: migration 0030 les a créés et y a rangé les comptes qui en avaient
#: exactement les cases. La table reste ici : les tests s'en servent pour
#: fabriquer un compte « comme un cariste » sans passer par un groupe.
CABINES = {"cab_ranger", "cab_statut", "cab_envoyer", "cab_corriger"}
PROFILS = {
    "cariste": ("Cariste", Utilisateur.OPERATEUR, CABINES),
    "cariste_mp": ("Cariste + MP", Utilisateur.OPERATEUR, CABINES | {"mp"}),
    "mp": ("Matières premières", Utilisateur.OPERATEUR, {"mp"}),
    # Tout le quotidien, réglages compris — sans créer ni supprimer
    # d'emplacements, ni toucher au fichier de production : ces cases-là se
    # cochent à la main, pour qui doit les avoir.
    "gestionnaire": ("Gestionnaire", Utilisateur.OPERATEUR,
                     CABINES | {"mp", "mp_seuils", "empl_service", "empl_regler", "modeles"}),
    "lecture": ("Lecture seule", Utilisateur.LECTURE, set()),
}

#: Le nom court de chaque case, pour la colonne « droits » des listes.
NOMS_COURTS = {
    "cab_ranger": "ranger", "cab_statut": "statut", "cab_envoyer": "sortir",
    "cab_corriger": "corriger", "production": "import du fichier",
    "hors_fichier": "hors fichier", "mp": "MP", "mp_seuils": "seuils MP",
    "empl_service": "mise en service", "empl_regler": "réglage des emplacements",
    "empl_creer": "création d'emplacements", "modeles": "modèles",
}


def valeurs_profil(cle):
    """Le rôle et toutes les cases d'un profil, prêts pour `update()`."""
    _, role, droits = PROFILS[cle]
    return {"role": role, **{f"droit_{d}": d in droits for d in Utilisateur.DROITS}}


def resume_droits(cles):
    """« ranger, statut, MP » : les cases en noms courts, dans l'ordre de la fiche."""
    cles = set(cles)
    return ", ".join(NOMS_COURTS[d] for d in Utilisateur.DROITS if d in cles)


#: Ce que dit la fiche d'un compte, au-dessus des cases.
AIDE_ROLES = (
    "<b>Opérateur</b> : il consulte tout, et fait ce que lui donnent son "
    "<b>groupe</b> et les cases cochées ci-dessous — rien d'autre.<br>"
    "<b>Lecture seule</b> : il consulte tout et ne modifie rien ; groupe et cases "
    "sont ignorés.<br>"
    "<b>Administrateur</b> : tout, plus « Repartir de zéro » ; groupe et cases "
    "sont ignorés.<br>"
    "Les cases ci-dessous sont ses droits <b>en plus</b> de ceux du groupe : "
    "laissez-les vides, il aura exactement les droits de son groupe.<br>"
    "Pour aller vite : dans la liste des comptes, cochez-en plusieurs et "
    "choisissez « Mettre dans le groupe … » dans « Action ».")

AIDE_GROUPE = (
    "Les cases sont celles de la fiche d'un compte. Chaque membre du groupe a ces "
    "droits ; sa propre fiche peut en ajouter, jamais en retirer.<br>"
    "Une case changée ici vaut aussitôt pour tous les membres.")

AIDE_ACCES = (
    "<b>Statut super-utilisateur</b> : accès complet à cette administration — "
    "comptes, groupes, emplacements, codes MP. C'est la case d'un responsable du WMS.<br>"
    "<b>Statut équipe</b> sans super-utilisateur n'ouvre que les pages cochées dans "
    "« Accès détaillé » : rarement utile.<br>"
    "Rien de cette section ne règle ce qu'on fait sur le téléphone : ce sont le "
    "groupe et les cases plus haut.")

#: Une section par groupe de cases, dans l'ordre de `Utilisateur.GROUPES_DROITS`.
#: La même pour la fiche d'un compte et celle d'un groupe : mêmes cases, même ordre.
SECTIONS_DROITS = tuple(
    (f"Droits — {groupe.lower()}", {"fields": tuple(f"droit_{c}" for c in cles)})
    for groupe, cles in Utilisateur.GROUPES_DROITS)


class FiltreDroit(admin.SimpleListFilter):
    """« Qui peut régler les emplacements ? » — droits effectifs : rôle, groupe et
    cases en plus compris."""

    title = "a le droit"
    parameter_name = "droit"

    def lookups(self, request, model_admin):
        return [(c, Utilisateur.libelle_droit(c).capitalize()) for c in Utilisateur.DROITS]

    def queryset(self, request, queryset):
        cle = self.value()
        if cle not in Utilisateur.DROITS:
            return queryset
        coche = Q(**{f"droit_{cle}": True}) | Q(**{f"groupe__droit_{cle}": True})
        return queryset.filter(Q(is_superuser=True) | Q(role=Utilisateur.ADMIN)
                               | (Q(role=Utilisateur.OPERATEUR) & coche))


#: Les permissions de Django dites en français : « Cabines — modifier » plutôt
#: que « wms | cabine | Can change cabine ». Django les nomme en anglais à leur
#: création, quelle que soit la langue de l'administration.
ACTIONS_DJANGO = {"add": "ajouter", "change": "modifier", "delete": "supprimer",
                  "view": "consulter"}


def libelle_permission(permission):
    action = permission.codename.split("_", 1)[0]
    modele = permission.content_type.model_class()
    nom = modele._meta.verbose_name_plural if modele else permission.content_type.model
    return f"{str(nom)[:1].upper()}{str(nom)[1:]} — {ACTIONS_DJANGO.get(action, permission.name)}"


# Les groupes de Django ne règlent que l'accès aux pages de cette
# administration, avec des permissions en anglais. Les laisser à côté des
# groupes du WMS, c'était deux « Groupes » dans le menu, et le mauvais choisi
# une fois sur deux.
try:
    admin.site.unregister(GroupeDjango)
except NotRegistered:
    pass


@admin.register(Groupe)
class GroupeAdmin(admin.ModelAdmin):
    list_display = ("nom", "droits", "nb_membres", "description")
    search_fields = ("nom", "description")
    readonly_fields = ("comptes_du_groupe",)
    fieldsets = (
        (None, {"fields": ("nom", "description"), "description": AIDE_GROUPE}),
    ) + SECTIONS_DROITS + (
        ("Membres", {"fields": ("comptes_du_groupe",)}),
    )

    class Media:
        css = {"all": ("admin/wms/comptes.css",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(nb=Count("membres"))

    @admin.display(description="membres", ordering="nb")
    def nb_membres(self, obj):
        return obj.nb

    @admin.display(description="droits")
    def droits(self, obj):
        return resume_droits(obj.cases_cochees()) or "Aucun droit"

    @admin.display(description="comptes du groupe")
    def comptes_du_groupe(self, obj):
        if obj is None or not obj.pk:
            return "Enregistrez le groupe, puis rangez-y des comptes."
        membres = list(obj.membres.order_by("username"))
        if not membres:
            return ("Aucun compte. Dans la liste des comptes, cochez-les et choisissez "
                    f"« Mettre dans le groupe « {obj.nom} » » ; ou choisissez le groupe "
                    "sur la fiche du compte.")
        return format_html_join(
            ", ", '<a href="{}">{}</a>',
            ((reverse("admin:wms_utilisateur_change", args=[u.pk]),
              f"{u.username} ({u.nom})" if u.nom else u.username) for u in membres))


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    list_display = ("username", "nom", "role", "groupe", "profil", "is_active")
    list_filter = ("role", "groupe", "is_active", FiltreDroit)
    list_select_related = ("groupe",)
    search_fields = ("username", "nom")
    filter_horizontal = ("user_permissions",)
    readonly_fields = ("droits_recus",)
    actions = ["retirer_du_groupe", "profil_lecture"]

    #: Le WMS d'abord, juste sous l'identifiant : c'est ce qu'on vient régler.
    #: Puis l'identité, l'accès à l'administration, les dates. Les groupes de
    #: Django n'y sont plus : ceux du WMS les remplacent (voir plus haut).
    fieldsets = UserAdmin.fieldsets[:1] + (
        ("WMS", {"fields": ("nom", "role", "groupe", "droits_recus", "pin"),
                 "description": AIDE_ROLES}),
    ) + SECTIONS_DROITS + (
        UserAdmin.fieldsets[1],
        ("Accès à l'administration", {"fields": ("is_active", "is_staff", "is_superuser"),
                                      "description": AIDE_ACCES}),
        ("Accès détaillé à l'administration (avancé)",
         {"fields": ("user_permissions",), "classes": ("collapse",)}),
        UserAdmin.fieldsets[3],
    )

    class Media:
        css = {"all": ("admin/wms/comptes.css",)}

    #: Les champs du WMS dès la création. Sans eux, créer un cariste demandait
    #: DEUX écrans : le compte d'abord, puis rouvrir la fiche pour cocher ses
    #: droits — et un compte créé sans droit ne peut rien faire, ce qui se
    #: découvre sur le téléphone du cariste, pas ici.
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("WMS", {"fields": ("nom", "role", "groupe"), "description": AIDE_ROLES}),
    ) + SECTIONS_DROITS

    def formfield_for_manytomany(self, db_field, request=None, **kwargs):
        champ = super().formfield_for_manytomany(db_field, request, **kwargs)
        if champ is not None and db_field.name == "user_permissions":
            champ.label_from_instance = libelle_permission
        return champ

    @admin.display(description="droits reçus du groupe")
    def droits_recus(self, obj):
        if obj is None or not obj.pk or not obj.groupe_id:
            return "Aucun groupe : seules les cases cochées plus bas comptent."
        cles = obj.droits_du_groupe()
        if not cles:
            return f"Le groupe « {obj.groupe} » ne donne aucun droit."
        return f"« {obj.groupe} » : " + ", ".join(Utilisateur.libelle_droit(c) for c in cles)

    @admin.display(description="droits")
    def profil(self, obj):
        """Ce que la personne peut faire, en une ligne : son groupe, et ce qu'elle
        a en plus ; sans groupe, la liste courte de ses cases."""
        if obj.est_administrateur:
            return "Administrateur — tout"
        if obj.role == Utilisateur.LECTURE:
            return "Lecture seule"
        en_plus = obj.droits_en_plus()
        if obj.groupe_id:
            return "Ceux du groupe" + (" + " + resume_droits(en_plus) if en_plus else "")
        if not en_plus:
            return "Aucun droit"
        return "Sur mesure : " + resume_droits(en_plus)

    def get_actions(self, request):
        """Une action par groupe existant : « Mettre dans le groupe « Caristes » »."""
        actions = super().get_actions(request)
        if not self.has_change_permission(request):
            return actions
        for groupe in Groupe.objects.order_by("nom"):
            nom = f"groupe_{groupe.pk}"
            actions[nom] = (self._action_groupe(groupe.pk), nom,
                            f"Mettre dans le groupe « {groupe.nom} »")
        return actions

    @staticmethod
    def _action_groupe(pk):
        def mettre(modeladmin, request, queryset):
            groupe = Groupe.objects.filter(pk=pk).first()
            if groupe is None:
                modeladmin.message_user(request, "Ce groupe n'existe plus.", messages.ERROR)
                return
            modeladmin._mettre_dans(request, queryset, groupe)
        return mettre

    def _sans_administrateurs(self, queryset):
        """Les comptes à changer, et le nombre d'administrateurs laissés tels quels.

        Un administrateur coché par mégarde avec ses opérateurs perdrait son
        rôle, et avec lui l'accès à « Repartir de zéro » : il est laissé tel
        quel, et le message le dit. Son rôle se change sur sa fiche.
        """
        gardes = queryset.filter(Q(role=Utilisateur.ADMIN) | Q(is_superuser=True))
        return queryset.exclude(pk__in=gardes.values("pk")), gardes.count()

    def _message(self, request, texte, n_gardes):
        if n_gardes:
            texte += (f" {n_gardes} administrateur(s) laissé(s) tel(s) quel(s) : "
                      "leur rôle se change sur leur fiche.")
        self.message_user(request, texte)

    def _mettre_dans(self, request, queryset, groupe):
        """Le groupe, le rôle « Opérateur », et AUCUNE case en plus : passer un
        gestionnaire chez les caristes lui retire bien le reste. Une action qui
        garderait ses cases laisserait ses droits d'avant, sans le dire."""
        a_changer, n_gardes = self._sans_administrateurs(queryset)
        n = a_changer.update(groupe=groupe, role=Utilisateur.OPERATEUR,
                             **{f"droit_{d}": False for d in Utilisateur.DROITS})
        self._message(request, f"{n} compte(s) mis dans le groupe « {groupe} » : ils en ont "
                               "les droits, et leurs droits en plus ont été retirés.", n_gardes)

    # `permissions=["change"]` : sans lui, Django propose les actions à qui peut
    # seulement CONSULTER la liste — et un compte en lecture se donnait des droits.
    @admin.action(description="Retirer de leur groupe (ils gardent leurs droits en plus)",
                  permissions=["change"])
    def retirer_du_groupe(self, request, queryset):
        n = queryset.exclude(groupe=None).update(groupe=None)
        self.message_user(request, f"{n} compte(s) retiré(s) de leur groupe.")

    @admin.action(description="Passer en « Lecture seule »", permissions=["change"])
    def profil_lecture(self, request, queryset):
        a_changer, n_gardes = self._sans_administrateurs(queryset)
        n = a_changer.update(groupe=None, **valeurs_profil("lecture"))
        self._message(request, f"{n} compte(s) passé(s) en « Lecture seule ».", n_gardes)


def _peut(request, droit):
    """La case du WMS, pour le compte connecté à l'administration."""
    peut = getattr(request.user, "peut", None)
    return bool(peut and peut(droit))


class EmplacementForm(forms.ModelForm):
    """Les familles et les codes acceptés passent ici par la règle de l'écran :
    un emplacement qui n'accepte que les vitrages n'est réservé qu'à des
    vitrages, un emplacement de cabines à rien.

    `Emplacement.clean()` ne peut pas le vérifier — familles et codes sont des
    tables de liaison, écrites APRÈS l'emplacement —, d'où ce formulaire."""

    class Meta:
        model = Emplacement
        fields = "__all__"

    def clean(self):
        donnees = super().clean()
        usage = donnees.get("usage", getattr(self.instance, "usage", Emplacement.CABINES))
        familles = [f.code for f in donnees.get("familles") or []]
        if usage == Emplacement.CABINES and familles:
            self.add_error("familles", "Un emplacement de cabines n'accepte pas de familles "
                                       "MP : videz « familles acceptées ».")
        refus = services_mp.refus_codes_familles(usage, familles,
                                                 donnees.get("codes_acceptes") or [])
        if refus:
            self.add_error("codes_acceptes", refus)
        return donnees


@admin.register(Emplacement)
class EmplacementAdmin(admin.ModelAdmin):
    """L'administration suit les cases du WMS, en plus des permissions de Django.

    Sans cela, un compte « équipe » à qui l'on aurait donné la permission
    Django de créer ou de régler des emplacements le faisait ici sans la case.

    Et l'on n'y SUPPRIME aucun emplacement, superutilisateur compris : la
    suppression vit dans l'application — sur la fiche, pour une sélection ou
    un rack entier —, avec ses refus (une cabine ou du stock MP encore posé),
    sa confirmation et sa ligne au journal du serveur. Celle de Django les
    contournait toutes, et détachait en silence les cabines rangées.
    """
    form = EmplacementForm
    #: Hors service et retour en service passent par l'application : motif
    #: obligatoire, refus tant qu'une cabine ou du stock est posé, trace au
    #: journal. Une case « actif » décochée ici retirait du stock un
    #: emplacement occupé, sans motif — et avec la seule case « régler ».
    readonly_fields = ("actif", "motif_inactif", "actif_le", "actif_par")
    list_display = ("code", "rack", "ce_qu_il_range", "zone_cabine", "mode_places", "staging",
                    "actif")
    list_filter = ("actif", "usage", "familles", "mode_places", "zone_cabine")
    search_fields = ("code", "rack", "description")
    filter_horizontal = ("familles", "codes_acceptes")

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("familles")

    @admin.display(description="ce qu'il range", ordering="usage")
    def ce_qu_il_range(self, obj):
        return services_mp.libelle_usage(obj)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and _peut(request, "empl_creer")

    def has_change_permission(self, request, obj=None):
        return (super().has_change_permission(request, obj)
                and _peut(request, "empl_regler"))

    # Ni bouton, ni action groupée, ni page de suppression. La permission de
    # Django, elle, reste ce qu'elle est : c'est elle qui permet à la page de
    # suppression d'une ZONE de nommer les emplacements qui la retiennent.
    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def delete_view(self, request, object_id, extra_context=None):
        raise PermissionDenied("Un emplacement se supprime dans l'application (fiche, "
                               "sélection ou rack), pas dans l'administration.")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(request, object_id, form_url,
                                   {**(extra_context or {}), "show_delete": False})


def choix_familles():
    """Les familles proposées pour un code : les actives, plus celle du code s'il
    en porte une qui ne l'est plus — sinon sa fiche ne s'enregistrerait plus."""
    return [(f.code, f.nom) for f in FamilleMP.objects.order_by("ordre", "nom")]


class ArticleMPForm(forms.ModelForm):
    """Un code réservé sur des emplacements ne change pas de famille et ne se
    retire pas en silence : ces emplacements n'accepteraient plus RIEN — ni
    lui, d'une autre famille ou retiré, ni les autres, qu'ils refusent."""

    class Meta:
        model = ArticleMP
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # La famille se CHOISIT dans la liste. Déclarée ici et pas sur la classe :
        # la liste modifiable n'a pas ce champ, et un champ déclaré y serait
        # exigé sur chaque ligne. Une nouvelle fiche ne propose que les actives.
        if "famille" in self.fields:
            choix = (choix_familles() if self.instance.pk
                     else [(f.code, f.nom) for f in FamilleMP.objects.filter(actif=True)])
            self.fields["famille"] = forms.ChoiceField(
                label="famille", choices=choix,
                help_text="Les familles se créent dans « Familles MP ».")

    def clean(self):
        donnees = super().clean()
        if not self.instance.pk:
            return donnees
        if "famille" in donnees and donnees["famille"] != self.instance.famille:
            # Du stock posé : un carton deviendrait un vitrage, sur un
            # emplacement de cartons qui ne l'accepterait plus.
            poses = sorted(set(StockMP.objects.filter(article=self.instance)
                               .values_list("emplacement__code", flat=True)))
            if poses:
                self.add_error("famille", "Ce code a du stock posé sur "
                                          f"{services_mp.liste_codes(poses)} : sortez-le "
                                          "avant de changer sa famille.")
        reserves = sorted(self.instance.emplacements_reserves.values_list("code", flat=True))
        if not reserves:
            return donnees
        ou = services_mp.liste_codes(reserves)
        # `self.instance` porte encore les valeurs d'avant : le formulaire ne
        # les y recopie qu'après `clean()`.
        if "famille" in donnees and donnees["famille"] != self.instance.famille:
            self.add_error("famille", f"Ce code est réservé sur {ou} : retirez-le de leurs "
                                      "codes acceptés avant de changer sa famille.")
        if "actif" in donnees and not donnees["actif"] and self.instance.actif:
            self.add_error("actif", f"Ce code est réservé sur {ou} : retirez-le de leurs "
                                    "codes acceptés avant de le retirer de la base.")
        return donnees


class FiltreFamille(admin.SimpleListFilter):
    title = "famille"
    parameter_name = "famille"

    def lookups(self, request, model_admin):
        return choix_familles()

    def queryset(self, request, queryset):
        return queryset.filter(famille=self.value()) if self.value() else queryset


@admin.register(FamilleMP)
class FamilleMPAdmin(admin.ModelAdmin):
    """Les familles de matières premières. Vitrage et Carton sont livrées ; les
    autres s'ajoutent ici, et l'application les propose aussitôt — réglage des
    emplacements, entrée de stock, filtres."""

    list_display = ("nom", "pluriel", "code", "pastille", "ordre", "nb_codes", "actif")
    list_editable = ("ordre", "actif")
    search_fields = ("nom", "pluriel", "code")
    fields = ("nom", "pluriel", "code", "exemple", "couleur", "ordre", "actif")

    def get_readonly_fields(self, request, obj=None):
        # Le code est ce que citent les codes MP et le journal : il ne change plus.
        return ("code",) if obj and obj.pk else ()

    def get_changeform_initial_data(self, request):
        return {"ordre": (FamilleMP.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1}

    @admin.display(description="couleur")
    def pastille(self, obj):
        return format_html('<span style="display:inline-block;width:14px;height:14px;'
                           'border-radius:4px;background:{};vertical-align:middle"></span> {}',
                           obj.couleur, obj.couleur)

    @admin.display(description="codes MP")
    def nb_codes(self, obj):
        return ArticleMP.objects.filter(famille=obj.code).count()

    def has_delete_permission(self, request, obj=None):
        """Une famille citée — par un code MP, le journal ou un emplacement — ne se
        supprime pas : on la désactive. Supprimée, ses emplacements
        n'auraient plus de famille, c'est-à-dire qu'ils les accepteraient TOUTES."""
        if obj is not None and (ArticleMP.objects.filter(famille=obj.code).exists()
                                or MouvementMP.objects.filter(famille=obj.code).exists()
                                or obj.emplacements.exists()):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(ArticleMP)
class ArticleMPAdmin(admin.ModelAdmin):
    """La base des codes vitrages et cartons : c'est ici qu'elle se complète.

    Un code ne se supprime pas une fois servi — le stock et le journal le
    citent (PROTECT). Le décocher « actif » le retire des propositions.
    """
    list_display = ("code", "nom_famille", "designation", "fournisseur", "numero",
                    "colisage", "seuil_reappro", "ancienne_generation", "actif")
    list_filter = (FiltreFamille, "fournisseur", "ancienne_generation", "actif")
    form = ArticleMPForm

    @admin.display(description="famille", ordering="famille")
    def nom_famille(self, obj):
        return services_mp.nom_famille(obj.famille, self._infos)

    def changelist_view(self, request, extra_context=None):
        # Les noms des familles lus une fois pour toute la page, pas une fois par ligne.
        self._infos = services_mp.infos_familles()
        return super().changelist_view(request, extra_context)

    _infos = None
    #: Le seuil d'alerte se règle aussi d'ici, ligne par ligne : quarante codes
    #: d'un écran, sans ouvrir quarante fiches. L'application le règle en
    #: nombre — le même seuil pour une sélection.
    list_editable = ("seuil_reappro", "ancienne_generation", "actif")

    def get_changelist_form(self, request, **kwargs):
        # La liste modifiable passe par la même règle que la fiche : sans
        # cela, décocher « actif » ici contournerait `ArticleMPForm.clean`.
        return super().get_changelist_form(request, form=ArticleMPForm, **kwargs)
    search_fields = ("code", "designation", "references", "numero")
    fieldsets = (
        (None, {"fields": ("code", "famille", "designation", "ancienne_generation", "actif")}),
        ("Références", {"fields": ("fournisseur", "numero", "references"),
                        "description": "Les autres noms du même élément, séparés par « · » : "
                                       "ils se cherchent comme le code."}),
        ("Quantités", {"fields": ("colisage", "seuil_reappro")}),
    )


class LectureSeuleAdmin(admin.ModelAdmin):
    """Consultable, jamais modifiable à la main : le stock bouge par l'application,
    qui écrit le journal. Corrigé ici, un chiffre changerait sans que personne
    sache pourquoi."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMP)
class StockMPAdmin(LectureSeuleAdmin):
    list_display = ("article", "emplacement", "place", "quantite", "entre_le", "modifie_le")
    list_filter = ("article__famille", "place", "emplacement__rack")
    search_fields = ("article__code", "emplacement__code")
    list_select_related = ("article", "emplacement")


@admin.register(MouvementMP)
class MouvementMPAdmin(LectureSeuleAdmin):
    list_display = ("date", "type", "article_code", "origine", "position", "quantite",
                    "reste", "utilisateur_nom", "note")
    list_filter = ("type", "famille")
    search_fields = ("article_code", "position", "origine", "utilisateur_nom", "note")


class OccupationInline(admin.TabularInline):
    """Les emplacements occupés se règlent depuis la cabine."""
    model = Occupation
    extra = 0
    fields = ("numero", "libelle", "emplacement", "place")


@admin.register(Cabine)
class CabineAdmin(admin.ModelAdmin):
    list_display = ("numero", "chantier", "type_cabine", "statut", "ou", "modele")
    search_fields = ("numero", "chantier", "modele")
    list_filter = ("statut", "type_cabine", "occupations__emplacement__zone_cabine")
    inlines = [OccupationInline]
    #: Ajoute le bouton « Repartir de zéro » en haut de la liste. Sans lui, la
    #: page existe mais personne ne la trouve — et une fonction qu'on ne trouve
    #: qu'en tapant son adresse finit par être remplacée par un `DELETE` à la
    #: main dans la base, ce qui est exactement ce qu'on veut éviter.
    change_list_template = "admin/wms/cabine/change_list.html"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("occupations__emplacement")

    def get_urls(self):
        return [
            path("remise-a-zero/",
                 self.admin_site.admin_view(self.remise_a_zero),
                 name="wms_cabine_remise_a_zero"),
        ] + super().get_urls()

    def remise_a_zero(self, request):
        """Repartir de zéro — tout l'outil, ou ce qu'on coche. Trois phrases, et
        une sauvegarde d'abord.

        Elle était un onglet de l'application, à deux doigts des gestes
        quotidiens. Elle est ici : dans l'administration, derrière un second
        mot de passe, et réservée aux comptes administrateurs.

        Tout est coché à l'ouverture : l'outil revient à neuf, il ne reste que
        les comptes. On décoche ce qu'on garde. Rien n'est effacé sans que les
        TROIS phrases soient exactes, ni sans sauvegarde : le service écrit
        d'abord un fichier rechargeable, et n'efface qu'ensuite.
        """
        if not getattr(request.user, "est_administrateur", False):
            # Un compte « équipe » suffit pour entrer dans l'administration ;
            # il ne suffit pas pour vider l'entrepôt.
            messages.error(request, "Repartir de zéro est réservé aux comptes "
                                    "administrateurs du WMS.")
            return HttpResponseRedirect(reverse("admin:wms_cabine_changelist"))

        saisies = {
            "confirmation": request.POST.get("confirmation", ""),
            "date_du_jour": request.POST.get("date_du_jour", ""),
            "engagement": request.POST.get("engagement", ""),
        }
        manques = {}
        # À l'ouverture, tout est coché : c'est la remise à neuf qu'on demande.
        cochees = list(services_remise.CLES)
        if request.method == "POST":
            cochees = [c for c in services_remise.CLES if request.POST.get(f"partie_{c}")]
            refus = services_remise.controler(cochees)
            if refus:
                manques["parties"] = refus
            if _normaliser(saisies["confirmation"]) != _normaliser(MOT_CONFIRMER):
                manques["confirmation"] = (
                    f"Recopiez exactement : {MOT_CONFIRMER}")
            if not _date_du_jour_saisie(saisies["date_du_jour"]):
                manques["date_du_jour"] = (
                    "Ce n'est pas la date d'aujourd'hui. Attendu : "
                    f"{timezone.localdate():%d/%m/%Y}")
            if _normaliser(saisies["engagement"]) != _normaliser(PHRASE_ENGAGEMENT):
                manques["engagement"] = (
                    f"Recopiez la phrase entière : {PHRASE_ENGAGEMENT}")

            if not manques:
                try:
                    bilan = services_remise.remettre_a_zero(parties=cochees,
                                                            utilisateur=request.user)
                except OSError as erreur:
                    # La sauvegarde passe avant tout effacement : si elle n'a
                    # pas pu s'écrire, rien n'a été effacé, et la page le dit.
                    messages.error(request, f"Sauvegarde impossible ({erreur}) : rien n'a "
                                            "été effacé.")
                except DatabaseError:
                    # Un geste en cours sur un poste tenait une des tables : la
                    # transaction est annulée avant la sauvegarde, rien n'est parti.
                    messages.error(request, "La remise à zéro n'a pas pu prendre la main sur "
                                            "la base — un geste était en cours sur un poste. "
                                            "Rien n'a été effacé : réessayez dans un instant.")
                else:
                    messages.warning(
                        request,
                        f"Remise à zéro faite : {bilan['resume']}. "
                        f"Sauvegarde écrite dans {bilan['sauvegarde']} — "
                        "rechargeable avec « manage.py loaddata ».")
                    return HttpResponseRedirect(
                        reverse("admin:wms_cabine_remise_a_zero"))

        etat = services_remise.etat()
        contexte = {
            **self.admin_site.each_context(request),
            "title": "Repartir de zéro",
            "parties": services_remise.presenter(cochees, etat),
            "comptes": etat["comptes"],
            "mot_confirmer": MOT_CONFIRMER,
            "phrase_engagement": PHRASE_ENGAGEMENT,
            "date_attendue": f"{timezone.localdate():%d/%m/%Y}",
            "saisies": saisies,
            "manques": manques,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/wms/cabine/remise_a_zero.html",
                                contexte)

    @admin.display(description="position")
    def ou(self, obj):
        """La position vit sur les occupations : une cabine peut en avoir plusieurs."""
        return obj.position or "—"


@admin.register(MouvementCabine)
class MouvementCabineAdmin(admin.ModelAdmin):
    list_display = ("date", "cabine_numero", "type", "statut_avant", "statut_apres",
                    "depuis", "vers", "utilisateur_nom")
    list_filter = ("type",)
    search_fields = ("cabine_numero", "chantier", "utilisateur_nom")
    # Journal : consultable, jamais modifiable à la main.
    readonly_fields = [f.name for f in MouvementCabine._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("nom", "ordre", "actif")
    list_editable = ("ordre", "actif")


class ConnexionAdministration(AdminAuthenticationForm):
    """La connexion à l'administration, avec le frein aux essais de mot de passe.

    Le refus lui-même vient du moteur d'authentification ; ce formulaire le
    consulte d'abord pour dire « trop d'essais, réessayez dans N minutes » au
    lieu d'un « identifiants incorrects » qui ferait douter du bon mot de passe.
    """

    def clean(self):
        reste = connexion.attente(self.request, self.cleaned_data.get("username") or "")
        if reste:
            raise forms.ValidationError(connexion.message(reste), code="trop_d_essais")
        return super().clean()


admin.site.site_header = "Administration WMS Structa"
admin.site.login_form = ConnexionAdministration
#: L'accueil de l'administration porte un lien vers « Repartir de zéro » pour les
#: administrateurs : la page vit sous « Cabines » pour des raisons d'adresse,
#: mais elle remet à zéro tout l'outil, et personne ne la chercherait là.
admin.site.index_template = "admin/wms/index.html"
