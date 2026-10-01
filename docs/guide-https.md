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

**Double-clic sur `Demarrer-WMS.bat`** — le seul lanceur, qui démarre toujours en
HTTPS (l'ancien `Demarrer-WMS-HTTPS.bat` y est fusionné). La **première fois**,
le lancer par clic droit → **Exécuter en tant qu'administrateur** : c'est ce qui
ouvre le port 8443 dans le pare-feu (profils Domaine et Privé seulement) et
inscrit l'autorité dans Windows. Ensuite, un double-clic suffit.

Il prépare l'environnement et la base, fabrique les certificats s'ils manquent
— et les refait seul si l'adresse du PC a changé ou s'ils arrivent en fin de
validité —, démarre le serveur, ouvre le WMS dans le navigateur et affiche les
adresses à donner aux téléphones :

```
  Le WMS est en HTTPS. Adresses à donner aux téléphones :
      https://192.168.1.42:8443
```

Rien d'autre à installer côté serveur : la terminaison TLS n'utilise que la
bibliothèque standard de Python. Seule la fabrication des certificats demande un
module (`cryptography`), installé automatiquement au premier lancement.

Pour arrêter le WMS : fermer sa fenêtre. Relancé alors qu'il tourne déjà, le
lanceur le dit et ouvre simplement le navigateur. Si le serveur d'application
tombe, la fenêtre l'annonce et le WMS s'arrête en entier — le port 8443 ne
répond jamais « dans le vide » à des téléphones qui croiraient le WMS en marche.

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

Depuis Android 11, toucher le fichier dans les téléchargements ne l'installe
plus (« installez-le depuis les paramètres ») : on passe par les Paramètres.

1. Mettre `ac-structa.crt` sur le téléphone : pièce jointe d'un mail →
   **Télécharger**, ou câble USB vers le dossier *Download*.
2. **Samsung :** Paramètres → Sécurité et confidentialité → Autres paramètres de
   sécurité → **Installer depuis le stockage** → **Certificat CA**.
   **Autres marques :** Paramètres → Sécurité et confidentialité → Autres
   paramètres de sécurité → Chiffrement et identifiants → **Installer un
   certificat** → **Certificat CA**.
   Menu introuvable : taper « certificat » dans la recherche des Paramètres.
3. **Installer quand même**, choisir `ac-structa.crt`, confirmer avec le code du
   téléphone. Android exige un verrouillage d'écran pour installer un certificat.
4. Fermer complètement Chrome (le glisser hors des applications récentes), puis
   le rouvrir sur `https://<adresse>:8443` : sinon il garde l'avertissement vu
   avant l'installation.

Le certificat s'installe dans le magasin « utilisateur » : Chrome l'accepte ;
certaines applications non. La notification « Le réseau peut être surveillé »
qui peut suivre est normale.

### Vérifier

Ouvrez `https://<adresse>:8443` sur le téléphone. Le cadenas doit être **fermé et
sans avertissement**, et le bouton « Activer la caméra » doit ouvrir la vidéo.

## Et sans rien installer sur les téléphones ?

Pas avec ce certificat-ci. Un téléphone ne fait confiance qu'aux autorités qu'il
connaît : une autorité fabriquée par nous doit lui être présentée, une fois, à
la main. Et aucune autorité publique n'a le droit de certifier une adresse
`192.168.x.x` ni un nom interne — c'est une règle commune à toutes.

Trois façons d'y arriver quand même :

| Solution | Ce qu'il faut | Contrepartie |
|---|---|---|
| **Un nom de domaine STRUCTA** (ex. `wms.structa.fr`) pointé vers l'IP fixe interne, avec un certificat public gratuit (Let's Encrypt) | l'accès à la zone DNS de `structa.fr` — une décision du service informatique | renouvellement automatique obligatoire : 90 jours aujourd'hui, 45 jours d'ici 2028. Rien n'est ouvert sur internet : la preuve passe par le DNS. |
| **Une gestion des appareils (MDM)**, si les téléphones de l'entreprise y sont inscrits | l'outil de gestion du parc | l'autorité est poussée sur tous les téléphones, sans geste |
| **Le tunnel** `Demarrer-WMS-Tunnel.bat` | rien | adresse **publique**, différente à chaque lancement, via un service tiers : seul le mot de passe protège les données. Un dépannage, pas une exploitation. |

## Mettre le WMS sur l'écran d'accueil

Une icône **WMS Structa** sur le téléphone, qui ouvre le WMS en plein écran, sans
barre d'adresse. Le raccourci retient l'adresse exacte : c'est l'**IP fixe** qui le
rend durable — si l'adresse du serveur changeait, toutes les icônes seraient à
refaire.

**Avant :** l'autorité est installée sur le téléphone (section précédente) et le
cadenas est fermé. Sur une page en avertissement de sécurité, Chrome ne propose
pas l'installation.

### Android (Chrome)

1. Ouvrir `https://<adresse>:8443` dans **Chrome**.
2. Menu **⋮** en haut à droite → **Ajouter à l'écran d'accueil**.
3. Choisir **Installer** (et non « Créer un raccourci »), puis confirmer.

Plus court : une fois connecté, écran **Plus** → carte « Sur l'écran d'accueil » →
**Installer sur ce téléphone**. Le bouton apparaît quand Chrome indique qu'il sait
installer le WMS ; sinon la carte rappelle les trois gestes ci-dessus.

Si Chrome ne propose que « Créer un raccourci », le prendre : l'icône fonctionne,
le WMS s'ouvre alors dans un onglet Chrome au lieu du plein écran.

### iPhone (Safari)

1. Ouvrir `https://<adresse>:8443` dans **Safari**.
2. iOS 26 : toucher **…** à droite de la barre d'adresse, puis **Partager**.
   Versions précédentes : toucher directement le bouton **Partager** (carré fléché).
3. **Sur l'écran d'accueil** → **Ajouter**. Laisser activée l'option qui l'ouvre
   comme une app web : c'est le réglage proposé d'office depuis iOS 26.

L'écran **Plus** du WMS rappelle ces gestes sur l'iPhone : Safari ne laisse
aucune page proposer elle-même son installation.

### Après la création

- **Se connecter une fois dans l'icône.** Sur iPhone, l'app web garde sa propre
  session, à part de Safari : le compte peut être redemandé à la première ouverture.
- Ouvert depuis l'icône, le WMS ne propose plus rien dans l'écran Plus : c'est le
  signe que le raccourci est le bon.
- **iPhone et caméra :** iOS peut redemander l'autorisation de la caméra à
  chaque ouverture de l'app web. C'est un comportement connu d'iOS, pas du WMS :
  un appui sur « Autoriser » suffit.

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
| « Le serveur WMS ne répond pas sur 127.0.0.1:8000 » | Le serveur d'application s'est arrêté : son message d'erreur est dans la fenêtre de `Demarrer-WMS.bat`. |
| « Le port 8000 est déjà pris sur ce PC » | Un WMS démarré par l'ancien lanceur tourne encore (fenêtre « WMS Structa - serveur »). La fermer, puis relancer `Demarrer-WMS.bat`. |
| « CSRF verification failed » sur `/admin/` | Origine non déclarée. Le lanceur les calcule seul ; si vous démarrez à la main, ajouter `https://<ip>:8443` à `DJANGO_CSRF_ORIGINS`. |
| Les autres postes ne joignent pas le serveur | Le port 8443 n'est pas ouvert. Relancer le `.bat` **en administrateur**. |
| Chrome ne propose pas « Installer » | Cadenas pas fermé (autorité absente), ou page ouverte en `http://`. Sinon, « Créer un raccourci » convient. |
| L'icône ouvre une page d'erreur | L'adresse du serveur a changé depuis la création du raccourci : refaire le raccourci sur la nouvelle adresse. |
