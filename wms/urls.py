from rest_framework.routers import DefaultRouter
from django.urls import path
from . import views

router = DefaultRouter()
router.register("emplacements", views.EmplacementViewSet)
router.register("cabines", views.CabineViewSet)
router.register("cabines-attendues", views.CabineAttendueViewSet,
                basename="cabine-attendue")
router.register("modeles-cabine", views.ModeleCabineViewSet, basename="modele-cabine")
router.register("mouvements-cabine", views.MouvementCabineViewSet, basename="mouvement-cabine")

urlpatterns = [
    # Sonde de supervision : sans authentification, sans rien divulguer.
    path("sante/", views.sante),
    path("moi/", views.moi),
    # Empreinte de l'activité : ce que les écrans interrogent pour se tenir à jour.
    path("pouls/", views.pouls),
    path("referentiels-cabine/", views.referentiels_cabine),
] + router.urls
