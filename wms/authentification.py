"""Connexion insensible à la casse de l'identifiant.

Pourquoi ce module existe : sur un téléphone, le clavier met une majuscule à la
première lettre de tout champ de texte. Un cariste dont le compte s'appelle
« enzo » tape donc « Enzo » sans même le voir — et Django, dont les
identifiants sont sensibles à la casse, répond « identifiants incorrects ».
L'erreur est invisible à l'œil : les deux chaînes se ressemblent à l'écran.

Le champ de saisie a bien été corrigé pour ne plus capitaliser, mais cela ne
couvre pas tout : un compte créé « Enzo » dans l'administration et tapé « enzo »
à la main échoue aussi, et une correction côté navigateur ne protège pas les
navigateurs qui ignorent l'attribut.

Ce backend ne relâche AUCUNE autre vérification : le mot de passe reste vérifié
par Django, le compte désactivé reste refusé, et le temps de hachage est
consommé même quand l'identifiant n'existe pas — sans quoi la durée de la
réponse dirait quels comptes existent.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class IdentifiantInsensibleALaCasse(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        Utilisateur = get_user_model()
        if username is None:
            username = kwargs.get(Utilisateur.USERNAME_FIELD)
        if username is None or password is None:
            return None

        nom = username.strip()
        # Correspondance exacte d'abord : si deux comptes ne diffèrent que par la
        # casse — « Enzo » et « enzo » —, celui qui a été tapé exactement gagne.
        # Sans cette priorité, la connexion deviendrait imprévisible.
        candidats = list(Utilisateur.objects.filter(username=nom))
        if not candidats:
            candidats = list(Utilisateur.objects.filter(username__iexact=nom))
        # Ambiguïté réelle (plusieurs comptes, aucune correspondance exacte) : on
        # refuse plutôt que de choisir à la place de l'administrateur.
        if len(candidats) != 1:
            if not candidats:
                # Hacher quand même : sinon la réponse est plus rapide pour un
                # identifiant inconnu, ce qui permet de les énumérer.
                Utilisateur().set_password(password)
            return None

        utilisateur = candidats[0]
        if utilisateur.check_password(password) and self.user_can_authenticate(utilisateur):
            return utilisateur
        return None
