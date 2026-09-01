# HTTPS sur le réseau interne

## Pourquoi c'est nécessaire

Les navigateurs mobiles **refusent l'accès à la caméra hors HTTPS**. Ce n'est pas
un réglage du WMS : c'est une règle du navigateur, qu'aucune application ne peut
contourner. Sans certificat, le bouton « Activer la caméra » ne peut pas s'ouvrir
et les opérateurs doivent saisir les codes à la main — ce qui vide l'essentiel de
l'intérêt du scan.

Le WMS le détecte et bascule tout seul en saisie manuelle ; mais autant régler le
problème.

## Démarrer

**Double-clic sur `Demarrer-WMS-HTTPS.bat`.** Au premier lancement il fabrique
les certificats, ouvre le port 8443 dans le pare-feu (profils Domaine et Privé
seulement), démarre le serveur et affiche les adresses à donner aux téléphones :

```
  Le WMS est en HTTPS. Adresses à donner aux téléphones :
      https://192.168.1.42:8443
```

Rien d'autre à installer côté serveur : la terminaison TLS n'utilise que la
bibliothèque standard de Python. Seule la fabrication des certificats demande un
module (`cryptography`), installé automatiquement au premier lancement.

## L'étape à ne pas sauter : installer l'autorité sur les téléphones

Sans cela, le navigateur affiche **un avertissement de sécurité à chaque
ouverture**. Les opérateurs prennent l'habitude de le contourner — et c'est
précisément l'habitude qu'on ne veut pas installer dans un entrepôt.

Le fichier à transmettre est **`certificats\ac-structa.crt`**. Envoyez-le par mail
ou déposez-le sur un partage ; il ne contient aucun secret, seule la clé privée
(`ac-structa.key`, qui reste sur le serveur) en est un.

### iPhone / iPad

1. Ouvrir le fichier `ac-structa.crt` depuis Mail ou Fichiers → **Autoriser**.
2. **Réglages → Général → VPN et gestion de l'appareil** → toucher le profil
   « Autorite interne WMS Structa » → **Installer** (trois fois).
3. **L'étape oubliée neuf fois sur dix :** Réglages → Général → **Informations**
   → **Réglages de confiance de certificat** → activer l'interrupteur en face de
   « Autorite interne WMS Structa ».

Sans l'étape 3, iOS installe le certificat mais **ne lui fait pas confiance** :
l'avertissement continue d'apparaître, et la caméra reste bloquée.

### Android

1. Ouvrir `ac-structa.crt` depuis les téléchargements, ou :
   **Paramètres → Sécurité → Chiffrement et identifiants → Installer un
   certificat → Certificat CA**.
2. Accepter l'avertissement, nommer le certificat.

Selon la version d'Android, le certificat s'installe dans le magasin
« utilisateur ». Chrome l'accepte ; certaines applications non.

### Vérifier

Ouvrez `https://<adresse>:8443` sur le téléphone. Le cadenas doit être **fermé et
sans avertissement**, et le bouton « Activer la caméra » doit ouvrir la vidéo.

## Ce que les certificats couvrent

Le certificat serveur est émis pour **toutes les adresses IPv4 de la machine** au
moment de sa création, plus `localhost` et le nom d'hôte. C'est nécessaire : les
navigateurs refusent un certificat qui ne mentionne pas l'adresse exacte tapée
dans la barre — et les opérateurs tapent une adresse IP.

**Si l'adresse de la machine change, le certificat ne couvre plus rien.** Le
lanceur le détecte au démarrage et le refait tout seul. Manuellement :

```bat
.venv\Scripts\python.exe outils\certificat_https.py --etat      rem ce qui existe
.venv\Scripts\python.exe outils\certificat_https.py --refaire   rem le refaire
```

**Fixez l'adresse IP de la machine** (ou une réservation DHCP) : c'est ce qui
évite d'avoir à recommencer.

## Durées de validité

| Élément | Durée | Pourquoi |
|---|---|---|
| Autorité `ac-structa` | 10 ans | On ne réinstalle pas un certificat sur vingt téléphones tous les ans. |
| Certificat serveur | **397 jours** | Apple refuse tout certificat serveur de plus de 398 jours, avec une erreur de confiance illisible. |

Au bout d'un an, relancer `certificat_https.py --refaire` : le nouveau certificat
est signé par la **même autorité**, donc **rien à refaire sur les téléphones**.
C'est tout l'intérêt d'avoir une autorité plutôt qu'un certificat auto-signé.

## Comment ça marche

```
  Téléphone  --HTTPS 8443-->  outils/proxy_https.py  --HTTP 8000-->  waitress + Django
                              (terminaison TLS)          (boucle locale)
```

Le serveur d'application est lié à **127.0.0.1** : le port 8000 n'est joignable
d'aucune autre machine. Seul le port 8443, chiffré, sort sur le réseau.

Le terminateur pose lui-même l'entête `X-Forwarded-Proto: https` sur **chaque**
requête, et **écrase** toute valeur venant du client — sans quoi n'importe qui
pourrait annoncer une connexion protégée sur un flux en clair. Django lit cet
entête via `DJANGO_DERRIERE_PROXY`, le réglage qui servait déjà pour le tunnel
Cloudflare : le cas est le même.

## Dépannage

| Symptôme | Cause |
|---|---|
| Avertissement de sécurité sur le téléphone | L'autorité n'est pas installée, ou — sur iPhone — pas **approuvée** (Informations → Réglages de confiance). |
| « Votre connexion n'est pas privée » avec l'IP dans le message | L'adresse de la machine a changé. `certificat_https.py --refaire`. |
| La caméra ne s'ouvre toujours pas | Vérifier que l'adresse commence bien par `https://` et que le cadenas est fermé. En `http://`, le navigateur bloque, quoi qu'on fasse. |
| « Le serveur WMS ne répond pas sur 127.0.0.1:8000 » | Le serveur d'application s'est arrêté. Lancer `Demarrer-WMS.bat` seul pour voir l'erreur. |
| « CSRF verification failed » sur `/admin/` | Origine non déclarée. Le lanceur les calcule seul ; si vous démarrez à la main, ajouter `https://<ip>:8443` à `DJANGO_CSRF_ORIGINS`. |
| Les autres postes ne joignent pas le serveur | Le port 8443 n'est pas ouvert. Relancer le `.bat` **en administrateur**. |
