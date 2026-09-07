from rest_framework.routers import DefaultRouter
from django.urls import path
from . import views

router = DefaultRouter()
router.register("categories", views.CategorieViewSet)
router.register("emplacements", views.EmplacementViewSet)
router.register("articles", views.ArticleViewSet)
router.register("stock", views.StockViewSet, basename="stock")
router.register("mouvements", views.MouvementViewSet, basename="mouvement")
router.register("receptions", views.ReceptionViewSet)
router.register("cabines", views.CabineViewSet)
router.register("cabines-attendues", views.CabineAttendueViewSet,
                basename="cabine-attendue")
router.register("zones", views.ZoneViewSet)
router.register("mouvements-cabine", views.MouvementCabineViewSet, basename="mouvement-cabine")
router.register("etats-cabine", views.EtatCabineViewSet)
router.register("operations", views.OperationsViewSet, basename="operations")

urlpatterns = [
    # Sonde de supervision : sans authentification, sans rien divulguer.
    path("sante/", views.sante),
    path("tableau-de-bord/", views.tableau_de_bord),
    path("moi/", views.moi),
    # Empreinte de l'activité : ce que les écrans interrogent pour se tenir à jour.
    path("pouls/", views.pouls),
    path("referentiels-cabine/", views.referentiels_cabine),
    path("suivi-processus/", views.suivi_processus),
] + router.urls
