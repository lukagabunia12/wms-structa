"""Application des droits fins de `Utilisateur` à l'API.

Avant ce module, la seule barrière était `IsAuthenticated` : un compte « lecture seule »
pouvait écrire du stock, créer et supprimer des articles. Les 7 droits du modèle
(`droit_mvt`, `droit_inv`, …) étaient déclarés, éditables dans l'admin, et ignorés.

Principe : la **lecture** reste ouverte à tout compte authentifié ; chaque **écriture**
exige le droit correspondant, déclaré par la vue via `droit_ecriture` (un seul droit pour
toute la vue) ou `droits_par_action` (un droit par action).
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class DroitWMS(BasePermission):
    """Remplace IsAuthenticated : même exigence d'authentification, plus les droits fins."""

    message = "Votre compte n'a pas le droit nécessaire pour cette opération."

    def has_permission(self, request, view):
        utilisateur = request.user
        if not (utilisateur and utilisateur.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True

        requis = self.droit_requis(view)
        if not requis:
            return True
        return bool(utilisateur.droits_effectifs().get(requis))

    @staticmethod
    def droit_requis(view):
        """Droit exigé pour l'écriture en cours, ou None si la vue n'en déclare aucun."""
        par_action = getattr(view, "droits_par_action", None)
        if par_action:
            return par_action.get(getattr(view, "action", None))
        return getattr(view, "droit_ecriture", None)


class EstAdministrateur(BasePermission):
    """Écriture réservée aux comptes administrateurs, au-delà des 7 droits fins.

    L'import du fichier de production réécrit les caractéristiques de milliers de
    cabines d'un coup. Ce n'est pas un geste de poste : aucune case à cocher ne
    l'ouvre, seul le rôle « Administrateur » (ou un superutilisateur) y donne
    accès. La lecture reste ouverte — l'écran d'entrée a besoin d'y lire la
    cabine qu'il pré-remplit.
    """

    message = ("L'import du fichier de production est réservé aux comptes "
               "administrateurs.")

    def has_permission(self, request, view):
        utilisateur = request.user
        if not (utilisateur and utilisateur.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(utilisateur, "est_administrateur", False))
