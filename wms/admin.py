import unicodedata
from datetime import datetime

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from . import connexion, services_mp, services_remise
from .models import (ArticleMP, Cabine, Emplacement, MouvementCabine, MouvementMP,
                     Occupation, StockMP, Utilisateur, Zone)


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


#: Les profils prêts à l'emploi, appliqués depuis la liste des comptes
#: (« Action »). Chacun fixe le rôle et TOUTES les cases : appliquer « Cariste »
#: à un gestionnaire lui retire bien le reste. Une action qui ne ferait que
#: cocher laisserait les droits d'avant en place, sans le dire.
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

#: Le nom court de chaque case, pour la colonne « droits » de la liste.
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


#: Ce que dit la fiche d'un compte, au-dessus des cases.
AIDE_ROLES = (
    "<b>Opérateur</b> : il consulte tout, et fait ce qui est coché ci-dessous — "
    "rien d'autre.<br>"
    "<b>Lecture seule</b> : il consulte tout et ne modifie rien ; les cases sont "
    "ignorées.<br>"
    "<b>Administrateur</b> : toutes les cases, plus « Repartir de zéro » ; les cases "
    "sont ignorées.<br>"
    "Pour aller vite : dans la liste des comptes, cochez-en un ou plusieurs et "
    "choisissez un profil (Cariste, Gestionnaire…) dans « Action ».")

#: Une section par groupe de cases, dans l'ordre de `Utilisateur.GROUPES_DROITS`.
SECTIONS_DROITS = tuple(
    (f"Droits — {groupe.lower()}", {"fields": tuple(f"droit_{c}" for c in cles)})
    for groupe, cles in Utilisateur.GROUPES_DROITS)


class FiltreDroit(admin.SimpleListFilter):
    """« Qui peut régler les emplacements ? » — droits effectifs, rôle compris."""

    title = "a le droit"
    parameter_name = "droit"

    def lookups(self, request, model_admin):
        return [(c, Utilisateur.libelle_droit(c).capitalize()) for c in Utilisateur.DROITS]

    def queryset(self, request, queryset):
        cle = self.value()
        if cle not in Utilisateur.DROITS:
            return queryset
        return queryset.filter(Q(is_superuser=True) | Q(role=Utilisateur.ADMIN)
                               | Q(role=Utilisateur.OPERATEUR, **{f"droit_{cle}": True}))


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    list_display = ("username", "nom", "role", "profil", "is_active")
    list_filter = ("role", "is_active", FiltreDroit)
    search_fields = ("username", "nom")
    actions = ["profil_cariste", "profil_cariste_mp", "profil_mp", "profil_gestionnaire",
               "profil_lecture"]

    #: Le WMS d'abord, juste sous l'identifiant : c'est ce qu'on vient régler.
    #: Les sections de Django — identité, accès à l'administration, dates —
    #: suivent.
    fieldsets = UserAdmin.fieldsets[:1] + (
        ("WMS", {"fields": ("nom", "role", "pin"), "description": AIDE_ROLES}),
    ) + SECTIONS_DROITS + UserAdmin.fieldsets[1:]

    class Media:
        css = {"all": ("admin/wms/comptes.css",)}

    #: Les champs du WMS dès la création. Sans eux, créer un cariste demandait
    #: DEUX écrans : le compte d'abord, puis rouvrir la fiche pour cocher ses
    #: droits — et un compte créé sans droit ne peut rien faire, ce qui se
    #: découvre sur le téléphone du cariste, pas ici.
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("WMS", {"fields": ("nom", "role"), "description": AIDE_ROLES}),
    ) + SECTIONS_DROITS

    @admin.display(description="droits")
    def profil(self, obj):
        """Ce que la personne peut faire, en une ligne : le nom du profil quand
        ses cases en forment un, sinon la liste courte de ses cases."""
        if obj.est_administrateur:
            return "Administrateur — tout"
        if obj.role == Utilisateur.LECTURE:
            return "Lecture seule"
        actifs = {d for d, oui in obj.droits_effectifs().items() if oui}
        if not actifs:
            return "Aucun droit"
        for nom, role, droits in PROFILS.values():
            if role == Utilisateur.OPERATEUR and actifs == droits:
                return nom
        return "Sur mesure : " + ", ".join(NOMS_COURTS[d] for d in Utilisateur.DROITS
                                           if d in actifs)

    def _appliquer(self, request, queryset, cle):
        """Pose un profil sur les comptes cochés — jamais sur un administrateur.

        Un administrateur coché par mégarde avec ses opérateurs perdrait son
        rôle, et avec lui l'accès à « Repartir de zéro » : il est laissé tel
        quel, et le message le dit. Son rôle se change sur sa fiche.
        """
        nom = PROFILS[cle][0]
        gardes = queryset.filter(Q(role=Utilisateur.ADMIN) | Q(is_superuser=True))
        n_gardes = gardes.count()
        n = queryset.exclude(pk__in=gardes.values("pk")).update(**valeurs_profil(cle))
        message = f"{n} compte(s) passé(s) au profil « {nom} »."
        if n_gardes:
            message += (f" {n_gardes} administrateur(s) laissé(s) tel(s) quel(s) : "
                        "leur rôle se change sur leur fiche.")
        self.message_user(request, message)

    # `permissions=["change"]` : sans lui, Django propose les actions à qui peut
    # seulement CONSULTER la liste — et un compte en lecture se donnait des droits.
    @admin.action(description="Profil « Cariste » — cabines", permissions=["change"])
    def profil_cariste(self, request, queryset):
        self._appliquer(request, queryset, "cariste")

    @admin.action(description="Profil « Cariste + MP » — cabines et matières premières",
                  permissions=["change"])
    def profil_cariste_mp(self, request, queryset):
        self._appliquer(request, queryset, "cariste_mp")

    @admin.action(description="Profil « Matières premières » — entrer, sortir, déplacer",
                  permissions=["change"])
    def profil_mp(self, request, queryset):
        self._appliquer(request, queryset, "mp")

    @admin.action(description="Profil « Gestionnaire » — tout le quotidien, réglages compris",
                  permissions=["change"])
    def profil_gestionnaire(self, request, queryset):
        self._appliquer(request, queryset, "gestionnaire")

    @admin.action(description="Profil « Lecture seule »", permissions=["change"])
    def profil_lecture(self, request, queryset):
        self._appliquer(request, queryset, "lecture")


def _peut(request, droit):
    """La case du WMS, pour le compte connecté à l'administration."""
    peut = getattr(request.user, "peut", None)
    return bool(peut and peut(droit))


class EmplacementForm(forms.ModelForm):
    """Les codes acceptés passent ici par la règle de l'écran : un emplacement
    de vitrages n'accepte que des vitrages, un emplacement de cabines aucun.

    `Emplacement.clean()` ne peut pas le vérifier — les codes sont une table de
    liaison, écrite APRÈS l'emplacement —, d'où ce formulaire."""

    class Meta:
        model = Emplacement
        fields = "__all__"

    def clean(self):
        donnees = super().clean()
        refus = services_mp.refus_codes_famille(
            donnees.get("usage", getattr(self.instance, "usage", Emplacement.CABINES)),
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
    list_display = ("code", "rack", "usage", "zone_cabine", "mode_places", "staging", "actif")
    list_filter = ("actif", "usage", "mode_places", "zone_cabine")
    search_fields = ("code", "rack", "description")
    filter_horizontal = ("codes_acceptes",)

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


class ArticleMPForm(forms.ModelForm):
    """Un code réservé sur des emplacements ne change pas de famille et ne se
    retire pas en silence : ces emplacements n'accepteraient plus RIEN — ni
    lui, d'une autre famille ou retiré, ni les autres, qu'ils refusent."""

    class Meta:
        model = ArticleMP
        fields = "__all__"

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


@admin.register(ArticleMP)
class ArticleMPAdmin(admin.ModelAdmin):
    """La base des codes vitrages et cartons : c'est ici qu'elle se complète.

    Un code ne se supprime pas une fois servi — le stock et le journal le
    citent (PROTECT). Le décocher « actif » le retire des propositions.
    """
    list_display = ("code", "famille", "designation", "fournisseur", "numero",
                    "colisage", "seuil_reappro", "ancienne_generation", "actif")
    list_filter = ("famille", "fournisseur", "ancienne_generation", "actif")
    form = ArticleMPForm
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
