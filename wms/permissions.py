"""Application des droits de `Utilisateur` à l'API.

Un droit par case de la fiche du compte : entrer et ranger des cabines, en
changer le statut, régler les emplacements, en créer et en supprimer… La liste
fait foi dans `Utilisateur.GROUPES_DROITS`. Au-delà des cases, le rôle
administrateur — qui les a toutes.

Principe : la **lecture** reste ouverte à tout compte authentifié ; chaque **écriture**
exige le droit correspondant, déclaré par la vue via `droit_ecriture` (un droit pour
toute la vue) ou `droits_par_action` (un droit par action).

Les deux se combinent : `droits_par_action` nomme les exceptions, `droit_ecriture`
couvre tout le reste. Une action ajoutée plus tard sans y penser tombe alors sous
le droit de la vue ; une vue qui ne déclare rien n'écrit que pour les
administrateurs. Rien ne s'ouvre à tous les comptes par omission. Une action qui
n'écrit rien mais passe par un POST (lire une photo) s'ouvre en nommant `None`.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

#: Une vue qui ne dit rien de ses écritures. Fermée par défaut : une action
#: ajoutée sans case réfléchie ne s'ouvre qu'aux administrateurs, au lieu de
#: s'ouvrir à tous les comptes. `None`, dit explicitement, reste « ouvert ».
NON_DECLARE = object()


class DroitWMS(BasePermission):
    """Remplace IsAuthenticated : même exigence d'authentification, plus les droits."""

    message = "Votre compte n'a pas le droit nécessaire pour cette opération."

    def has_permission(self, request, view):
        utilisateur = request.user
        if not (utilisateur and utilisateur.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True

        requis = self.droit_requis(view)
        if requis is None:
            return True
        if requis is NON_DECLARE:
            if getattr(utilisateur, "est_administrateur", False):
                return True
            self.message = ("Cette opération n'est rattachée à aucune case : elle est "
                            "réservée aux administrateurs du WMS.")
            return False
        if utilisateur.peut(requis):
            return True
        # Le refus nomme la case qui manque : « pas le droit nécessaire » laisse
        # l'administrateur deviner laquelle cocher.
        self.message = ("Votre compte n'a pas le droit « "
                        f"{utilisateur.libelle_droit(requis)} ». Demandez-le à "
                        "l'administrateur du WMS.")
        return False

    @staticmethod
    def droit_requis(view):
        """La case exigée pour l'écriture en cours ; `None` si la vue la dit
        ouverte ; `NON_DECLARE` si elle n'en dit rien.

        L'action d'abord, la vue ensuite. Une action que ni `droits_par_action`
        ni `droit_ecriture` ne nomment n'est pas ouverte pour autant : elle est
        réservée aux administrateurs.
        """
        par_action = getattr(view, "droits_par_action", None) or {}
        action = getattr(view, "action", None)
        if action in par_action:
            return par_action[action]
        return getattr(view, "droit_ecriture", NON_DECLARE)
