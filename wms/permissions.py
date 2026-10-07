"""Application des droits fins de `Utilisateur` à l'API.

Deux droits : « cabines » (ranger, changer un statut, envoyer…) et « référentiel »
(emplacements, racks, modèles). Au-delà, le rôle administrateur.

Principe : la **lecture** reste ouverte à tout compte authentifié ; chaque **écriture**
exige le droit correspondant, déclaré par la vue via `droit_ecriture` (un seul droit pour
toute la vue) ou `droits_par_action` (un droit par action).

Les deux se combinent : `droits_par_action` nomme les exceptions, `droit_ecriture`
couvre tout le reste. C'est le cas des matières premières — entrer, sortir et
déplacer demandent la case « matières premières », régler un seuil d'alerte
demande le référentiel. Une action ajoutée plus tard sans y penser tombe alors
sous le droit de la vue, au lieu de s'ouvrir à tous les comptes par omission.
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
        """Droit exigé pour l'écriture en cours, ou None si la vue n'en déclare aucun.

        L'action d'abord, la vue ensuite : une vue qui ne déclare que
        `droits_par_action` laisse ouvertes les actions qu'elle ne nomme pas,
        comme avant ; une vue qui déclare aussi `droit_ecriture` les ferme.
        """
        par_action = getattr(view, "droits_par_action", None) or {}
        action = getattr(view, "action", None)
        if action in par_action:
            return par_action[action]
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
