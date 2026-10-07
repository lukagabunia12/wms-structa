import unicodedata
from datetime import datetime

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from . import services_cabines, services_mp
from .models import (ArticleMP, Cabine, Emplacement, MouvementCabine, MouvementMP,
                     Occupation, StockMP, Utilisateur, Zone)


#: Les trois phrases à recopier pour vider le stock. Elles sont ici, en clair :
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


#: Ce que coche « Compte de cariste » : le droit de manipuler les cabines, et
#: rien d'autre. C'est exactement le profil que l'interface simplifie — trois
#: gestes, pas de référentiel.
PROFIL_CARISTE = {"role": Utilisateur.OPERATEUR, "droit_cab": True}

#: Gestionnaire : cariste, plus le référentiel (emplacements, racks, modèles,
#: étiquettes). Pas l'import/export de données, réservé à l'administrateur.
PROFIL_GESTIONNAIRE = {"role": Utilisateur.OPERATEUR, "droit_cab": True, "droit_ref": True}


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    list_display = ("username", "nom", "role", "profil", "is_active")
    list_filter = ("role", "is_active", "droit_cab", "droit_ref", "droit_mp")
    search_fields = ("username", "nom")
    actions = ["faire_caristes", "faire_gestionnaires"]

    fieldsets = UserAdmin.fieldsets + (
        ("WMS", {"fields": ("nom", "role", "pin", "droit_cab", "droit_ref", "droit_mp")}),
    )

    #: Les champs du WMS dès la création. Sans eux, créer un cariste demandait
    #: DEUX écrans : le compte d'abord, puis rouvrir la fiche pour cocher le
    #: droit « cabines » — et un compte créé sans ce droit ne peut rien faire,
    #: ce qui se découvre sur le téléphone du cariste, pas ici.
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("WMS", {
            "fields": ("nom", "role", "droit_cab", "droit_ref", "droit_mp"),
            "description": (
                "Pour un <b>cariste</b> : rôle « Opérateur » et la case "
                "<b>cabines</b> cochée — rien d'autre.<br>"
                "Pour un <b>gestionnaire</b> : ajouter la case <b>référentiel</b> "
                "(emplacements, racks, modèles, étiquettes).<br>"
                "Pour entrer et sortir des vitrages et des cartons : la case "
                "<b>matières premières</b>, seule ou avec les autres.<br>"
                "Le rôle « Administrateur » donne tous les droits, les cases "
                "individuelles n'ont alors plus d'effet."),
        }),
    )

    @admin.display(description="profil")
    def profil(self, obj):
        """Ce que la personne voit réellement dans l'application."""
        if obj.est_administrateur:
            return "Administrateur"
        if obj.role == Utilisateur.LECTURE:
            return "Lecture seule"
        droits = obj.droits_effectifs()
        if droits.get("ref"):
            return "Gestionnaire"
        if droits.get("cab"):
            return "Cariste + MP" if droits.get("mp") else "Cariste"
        if droits.get("mp"):
            return "Matières premières"
        return "Aucun droit"

    @admin.action(description="Faire de ces comptes des caristes")
    def faire_caristes(self, request, queryset):
        n = queryset.update(**PROFIL_CARISTE)
        self.message_user(request, f"{n} compte(s) passé(s) en cariste.")

    @admin.action(description="Faire de ces comptes des gestionnaires")
    def faire_gestionnaires(self, request, queryset):
        n = queryset.update(**PROFIL_GESTIONNAIRE)
        self.message_user(request, f"{n} compte(s) passé(s) en gestionnaire.")


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
    form = EmplacementForm
    list_display = ("code", "rack", "usage", "zone_cabine", "mode_places", "staging", "actif")
    list_filter = ("actif", "usage", "mode_places", "zone_cabine")
    search_fields = ("code", "rack", "description")
    filter_horizontal = ("codes_acceptes",)


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
        """Vide le stock des cabines — trois phrases, et une sauvegarde d'abord.

        Elle était un onglet de l'application, à deux doigts des gestes
        quotidiens. Elle est ici : dans l'administration, derrière un second
        mot de passe, et réservée aux comptes administrateurs.

        Rien n'est effacé sans que les TROIS phrases soient exactes. Et rien
        n'est effacé sans sauvegarde : le service écrit d'abord un fichier
        rechargeable, et n'efface qu'ensuite.
        """
        if not getattr(request.user, "est_administrateur", False):
            # Un compte « équipe » suffit pour entrer dans l'administration ;
            # il ne suffit pas pour vider l'entrepôt.
            messages.error(request, "Vider le stock est réservé aux comptes "
                                    "administrateurs du WMS.")
            return HttpResponseRedirect(reverse("admin:wms_cabine_changelist"))

        saisies = {
            "confirmation": request.POST.get("confirmation", ""),
            "date_du_jour": request.POST.get("date_du_jour", ""),
            "engagement": request.POST.get("engagement", ""),
        }
        manques = {}
        if request.method == "POST":
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
                bilan = services_cabines.vider_le_stock(utilisateur=request.user)
                messages.warning(
                    request,
                    f"Stock vidé : {bilan['cabines']} cabine(s) et "
                    f"{bilan['journal']} ligne(s) de journal effacées. "
                    f"Sauvegarde écrite dans {bilan['sauvegarde']} — "
                    "rechargeable avec « manage.py loaddata ».")
                return HttpResponseRedirect(
                    reverse("admin:wms_cabine_remise_a_zero"))

        contexte = {
            **self.admin_site.each_context(request),
            "title": "Repartir de zéro",
            "etat": services_cabines.etat_du_stock(),
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


admin.site.site_header = "Administration WMS Structa"
