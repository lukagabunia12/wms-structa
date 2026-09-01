from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (Occupation, Article, Cabine, Categorie, Emplacement, EtatCabine,
                     Mouvement, MouvementCabine, Reception, Stock, Utilisateur, Zone)


#: Ce que coche « Compte de cariste » : le droit de manipuler les cabines, et
#: rien d'autre. C'est exactement le profil que l'interface simplifie — trois
#: gestes, pas de référentiel.
PROFIL_CARISTE = {"role": Utilisateur.OPERATEUR, "droit_cab": True}

#: Gestionnaire : cariste, plus le référentiel (emplacements, racks, zones,
#: étiquettes). Pas l'import/export de données, réservé à l'administrateur.
PROFIL_GESTIONNAIRE = {"role": Utilisateur.OPERATEUR, "droit_cab": True, "droit_ref": True}


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    list_display = ("username", "nom", "role", "profil", "is_active")
    list_filter = ("role", "is_active", "droit_cab", "droit_ref")
    search_fields = ("username", "nom")
    actions = ["faire_caristes", "faire_gestionnaires"]

    fieldsets = UserAdmin.fieldsets + (
        ("WMS", {"fields": ("nom", "role", "pin", "droit_mvt", "droit_mvt_corr",
                            "droit_inv", "droit_cab", "droit_ref", "droit_data", "droit_appro")}),
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
                "(emplacements, racks, zones, étiquettes).<br>"
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


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("ref", "designation", "categorie", "unite", "stock_min", "statut")
    search_fields = ("ref", "ean", "designation")
    list_filter = ("categorie", "statut")


@admin.register(Emplacement)
class EmplacementAdmin(admin.ModelAdmin):
    list_display = ("code", "zone", "staging", "actif")
    search_fields = ("code", "zone")


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("article", "emplacement", "qte")
    search_fields = ("article__ref", "emplacement__code")


@admin.register(Mouvement)
class MouvementAdmin(admin.ModelAdmin):
    list_display = ("date", "type", "article", "emplacement", "qte", "utilisateur", "annule")
    list_filter = ("type", "annule")
    search_fields = ("article__ref", "emplacement__code", "commande")


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

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("occupations__emplacement")

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


admin.site.register(Categorie)
admin.site.register(Reception)
admin.site.register(EtatCabine)
admin.site.site_header = "Administration WMS Structa"
