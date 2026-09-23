import unicodedata
from datetime import datetime

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from . import services_cabines
from .models import Cabine, Emplacement, MouvementCabine, Occupation, Utilisateur, Zone


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
    list_filter = ("role", "is_active", "droit_cab", "droit_ref")
    search_fields = ("username", "nom")
    actions = ["faire_caristes", "faire_gestionnaires"]

    fieldsets = UserAdmin.fieldsets + (
        ("WMS", {"fields": ("nom", "role", "pin", "droit_cab", "droit_ref")}),
    )

    #: Les champs du WMS dès la création. Sans eux, créer un cariste demandait
    #: DEUX écrans : le compte d'abord, puis rouvrir la fiche pour cocher le
    #: droit « cabines » — et un compte créé sans ce droit ne peut rien faire,
    #: ce qui se découvre sur le téléphone du cariste, pas ici.
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("WMS", {
            "fields": ("nom", "role", "droit_cab", "droit_ref"),
            "description": (
                "Pour un <b>cariste</b> : rôle « Opérateur » et la case "
                "<b>cabines</b> cochée — rien d'autre.<br>"
                "Pour un <b>gestionnaire</b> : ajouter la case <b>référentiel</b> "
                "(emplacements, racks, modèles, étiquettes).<br>"
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
            return "Cariste"
        return "Aucun droit"

    @admin.action(description="Faire de ces comptes des caristes")
    def faire_caristes(self, request, queryset):
        n = queryset.update(**PROFIL_CARISTE)
        self.message_user(request, f"{n} compte(s) passé(s) en cariste.")

    @admin.action(description="Faire de ces comptes des gestionnaires")
    def faire_gestionnaires(self, request, queryset):
        n = queryset.update(**PROFIL_GESTIONNAIRE)
        self.message_user(request, f"{n} compte(s) passé(s) en gestionnaire.")


@admin.register(Emplacement)
class EmplacementAdmin(admin.ModelAdmin):
    list_display = ("code", "rack", "zone_cabine", "mode_places", "staging", "actif")
    list_filter = ("actif", "mode_places", "zone_cabine")
    search_fields = ("code", "rack", "description")


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
