"""Frein aux essais de mot de passe.

Pourquoi ce module existe : la vue de DRF qui délivre les jetons (`/api/token/`)
ignore le quota anonyme réglé dans `settings.py`, et l'administration n'en a
aucun. Rien n'empêchait donc d'essayer des milliers de mots de passe sur un
compte — à la main depuis le Wi-Fi de l'entrepôt, ou à la machine dès que
l'application est publiée par le tunnel.

Le frein compte les échecs dans le cache, sur une fenêtre de quinze minutes :

- par compte ET par adresse : dix échecs, et ce compte est refusé depuis cette
  adresse jusqu'à la fin de la fenêtre. Un collègue qui se trompe sur son
  téléphone ne bloque pas le même compte ailleurs ;
- par adresse, tous comptes confondus : trente échecs, et l'adresse est
  refusée. On n'essaie pas un mot de passe sur cent comptes ;
- jamais par adresse quand c'est celle de la machine elle-même : derrière un
  proxy mal réglé, tous les clients la partageraient, et un seul maladroit
  bloquerait l'entrepôt entier. Le compteur par compte reste actif.

Le refus vaut même avec le bon mot de passe : c'est ce qui rend la devinette
inutile. Il dit combien de minutes attendre, pour qu'un opérateur bloqué ne
cherche pas une panne.

Branchements : le moteur d'authentification (`wms.authentification`) consulte
`attente()` avant de vérifier le mot de passe — toutes les portes d'entrée y
passent — et le signal `user_login_failed` alimente le compteur. La vue de
jeton et le formulaire de l'administration consultent `attente()` eux aussi,
pour répondre en clair plutôt que « identifiants incorrects ».
"""
import ipaddress
import math
import time

from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django.core.cache import cache
from django.dispatch import receiver

PREFIXE = "wms-connexion"


def _fenetre():
    return max(1, int(getattr(settings, "CONNEXION_FENETRE_MINUTES", 15))) * 60


def adresse(request):
    """L'adresse du client telle que le serveur d'application la connaît."""
    if request is None:
        return ""
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _locale(ip):
    """Vrai pour la machine elle-même, ou une adresse illisible."""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return True


def _cles(request, identifiant):
    ip = adresse(request)
    nom = (identifiant or "").strip().lower()
    cles = [(f"{PREFIXE}:compte:{ip}:{nom}",
             int(getattr(settings, "CONNEXION_ESSAIS_PAR_COMPTE", 10)))]
    if not _locale(ip):
        cles.append((f"{PREFIXE}:adresse:{ip}",
                     int(getattr(settings, "CONNEXION_ESSAIS_PAR_ADRESSE", 30))))
    return cles


def attente(request, identifiant):
    """Secondes à attendre avant le prochain essai ; 0 si l'essai est permis."""
    maintenant = time.time()
    reste = 0
    for cle, maximum in _cles(request, identifiant):
        compteur = cache.get(cle)
        if compteur and compteur["n"] >= maximum and compteur["fin"] > maintenant:
            reste = max(reste, compteur["fin"] - maintenant)
    return int(math.ceil(reste))


def noter_echec(request, identifiant):
    """Un essai de plus. La fenêtre part du premier échec et ne glisse pas."""
    maintenant = time.time()
    for cle, _maximum in _cles(request, identifiant):
        compteur = cache.get(cle)
        if not compteur or compteur["fin"] <= maintenant:
            compteur = {"n": 0, "fin": maintenant + _fenetre()}
        compteur["n"] += 1
        cache.set(cle, compteur, timeout=max(1, int(compteur["fin"] - maintenant) + 1))


def effacer(request, identifiant):
    """Une connexion réussie remet à zéro le compteur de CE compte depuis cette
    adresse — jamais celui de l'adresse : sinon un compte connu servirait à
    relancer la devinette sur les autres entre deux essais."""
    cache.delete(_cles(request, identifiant)[0][0])


def message(secondes):
    minutes = max(1, int(math.ceil(secondes / 60)))
    return (f"Trop d'essais de connexion. Réessayez dans {minutes} minute"
            f"{'s' if minutes > 1 else ''}, ou demandez à l'administrateur du "
            "WMS de vérifier le mot de passe.")


@receiver(user_login_failed, dispatch_uid="wms-connexion-echec")
def _sur_echec(sender, credentials, request=None, **kwargs):
    noter_echec(request, (credentials or {}).get("username", ""))
