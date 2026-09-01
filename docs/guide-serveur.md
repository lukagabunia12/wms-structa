# Installer le WMS sur un autre poste

Ce guide sert à monter le WMS sur le PC qui fera office de serveur, à partir
d'une copie du projet. Compter **une demi-heure**, dont vingt minutes de
téléchargement.

Le principe : rien n'est bricolé à la main sur le serveur. On prépare une copie
propre ici, on l'emporte, on double-clique un fichier là-bas.

---

## 1. À télécharger sur le poste serveur, avant tout

Deux logiciels, tous deux gratuits, tous deux à installer avec les droits
administrateur.

### Python

<https://www.python.org/downloads/windows/>

**La version doit être la même que sur le poste actuel.** Le dossier de
dépendances hors ligne (`paquets/`) est fabriqué pour une version précise de
Python ; une autre version le rend inutilisable, et l'installation s'arrête en
le disant.

Pour connaître la version du poste actuel, double-cliquer `Quelle-Base.bat`, ou
dans une invite de commandes, depuis le dossier du projet :

```
.venv\Scripts\python.exe --version
```

Pendant l'installation, deux choix comptent :

- **cocher « Add python.exe to PATH »** sur le premier écran ;
- choisir **« Install for all users »** (bouton « Customize installation », puis
  la case « Install Python for all users »).

Le second n'est pas cosmétique. Par défaut, l'installeur pose Python dans le
profil de la personne connectée. Or `Installer-WMS.bat` tourne en
**administrateur**, et sur un poste du domaine l'élévation bascule souvent sur
un autre compte — pour lequel ce Python-là n'existe pas. L'installation répond
alors « Python introuvable » sur un poste où Python est parfaitement installé.

> Ne pas prendre Python depuis le Microsoft Store : ce paquet-là ne sait pas
> créer d'environnement de projet, et l'échec est déroutant (« python » répond,
> mais rien ne s'installe).

**Si l'installation dit malgré tout que Python est introuvable**, double-cliquer
`Trouver-Python.bat` : il affiche tous les interpréteurs présents sur le poste,
sous quel compte tourne la fenêtre, et lequel serait retenu. Si Python est bien
là mais dans un profil inaccessible, on peut passer son chemin directement :

```
Installer-WMS.bat -Python "C:\Users\<compte>\AppData\Local\Programs\Python\Python314\python.exe"
```

### PostgreSQL

<https://www.postgresql.org/download/windows/>

Version 16 ou plus récente. Pendant l'installation :

- **cocher « Command Line Tools »** — c'est ce composant qui fournit `psql`,
  dont l'installateur du WMS a besoin ;
- **noter le mot de passe du compte `postgres`** qui est demandé. Il sera
  redemandé une fois, à l'installation du WMS, et il n'existe aucun moyen de le
  retrouver ensuite.

Rien d'autre n'est à télécharger. Tout le reste voyage dans la copie.

---

## 2. Sur le poste actuel : préparer la copie

**a. Constituer les dépendances hors ligne** — une seule fois, et à refaire
seulement si `requirements.txt` change :

```
Preparer-Paquets.bat
```

Ce poste a internet, le serveur ne l'aura peut-être pas ; ce dossier supprime
la question. Sans lui, l'installation sur le serveur dépend de l'accès à PyPI,
ce que le réseau de l'entreprise filtre souvent — et on ne le découvre que sur
place.

**b. Fabriquer la copie** :

```
Preparer-Copie.bat
```

Produit, à côté du dossier du projet, `WMS-Structa_a-copier_<date>\` et son
archive `.zip`.

Ce qui **part** : le code, les dépendances hors ligne, et les données de
l'entrepôt (exportées au passage dans `reprise\`).

Ce qui **ne part pas**, et pourquoi :

| Écarté | Raison |
|---|---|
| `.venv\` | contient les chemins et les binaires de ce poste-ci |
| `.env` | porte la clé secrète et le mot de passe de la base — une clé partagée entre deux postes, c'est une session forgée sur l'un qui vaut sur l'autre |
| `certificats\` | émis pour les adresses IP de ce poste ; ailleurs, ils ne prouvent rien |
| `db.sqlite3` | ancienne base, remplacée par PostgreSQL ; l'emporter, c'est risquer de travailler dans une copie morte |
| `logs\` | journaux de ce poste |

Le script vérifie ensuite qu'aucun de ces fichiers n'a échappé au filtre, et
détruit la copie plutôt que de laisser partir un secret.

---

## 3. Copier

Clé USB ou dossier partagé, peu importe. Poser le dossier là où il doit
**rester** : le WMS s'installe à l'endroit où il se trouve, le déplacer ensuite
oblige à réinstaller.

Un emplacement raisonnable : `C:\WMS-Structa\`.

Éviter le Bureau, `Téléchargements` et OneDrive : un dossier synchronisé
verrouille des fichiers au mauvais moment et fait échouer des écritures sans
message clair.

---

## 4. Sur le poste serveur : installer

Double-cliquer :

```
Installer-WMS.bat
```

Répondre **Oui** à la demande de droits administrateur. Ils servent à deux
choses seulement : ouvrir le port dans le pare-feu, et inscrire l'autorité de
certification. Sans eux, l'installation se termine quand même, mais les
téléphones ne joindront pas le serveur.

Deux mots de passe sont demandés :

1. celui à **donner** au compte applicatif `wms` — vous le choisissez, il est
   écrit dans `.env` et vous n'aurez plus à le retenir ;
2. celui du compte **`postgres`**, choisi pendant l'installation de PostgreSQL.

Ni l'un ni l'autre n'est affiché ni écrit dans le journal.

Le script enchaîne : environnement Python, dépendances, `.env`, base de données,
schéma, reprise des données, certificat HTTPS, pare-feu, puis un contrôle de
pré-vol qui dit ce qui reste à faire.

Tout est consigné dans `logs\installation.log` — à lire en cas d'échec, la
console se ferme souvent avant qu'on ait lu le message.

---

## 4 bis. Si le port 8443 n'est pas encore ouvert

C'est le cas tant que le prestataire n'a pas traité la demande. Le POC peut
démarrer quand même, par un tunnel : `cloudflared` ouvre une connexion
**sortante**, comme un navigateur, donc aucune règle de pare-feu n'est
nécessaire.

Installer en le disant, pour que le script saute le pare-feu et le certificat
local — inutiles dans ce mode :

```
Installer-WMS.bat -Tunnel
```

Puis, pour démarrer :

```
Demarrer-WMS-Tunnel.bat
```

Une adresse `https://xxxxx.trycloudflare.com` s'affiche, avec son QR code dans
une page qui s'ouvre toute seule : les caristes scannent l'écran. Rien à
installer sur les téléphones — le certificat vient de Cloudflare, ils le
reconnaissent déjà.

Trois choses à savoir : cette adresse est **publique**, donc seul le mot de
passe des comptes protège les données ; elle **change à chaque démarrage** ; et
la fenêtre du tunnel doit **rester ouverte**, l'accès s'arrête avec elle.

Dès que le port est ouvert, on repasse sur l'accès interne : relancer
`Installer-WMS.bat` sans `-Tunnel` (pour le certificat et la règle de pare-feu),
puis `Demarrer-WMS-HTTPS.bat`.

### Si PostgreSQL ne peut pas être installé

```
Installer-WMS.bat -SansPostgreSQL
```

Le WMS tourne alors sur un fichier SQLite. C'est un **secours**, pas une cible :
SQLite supporte mal plusieurs écritures simultanées, et c'est exactement ce que
font plusieurs caristes qui rangent en même temps. Tenable quelques jours pour
un POC, à repasser sur PostgreSQL avant tout usage réel.

Les deux options se combinent : `Installer-WMS.bat -Tunnel -SansPostgreSQL`.

---

## 5. Démarrer, et vérifier

```
Demarrer-WMS-HTTPS.bat
```

L'écran affiche l'adresse à donner aux téléphones, de la forme
`https://192.168.0.x:8443`.

À vérifier dans l'ordre, parce que chaque étape ratée a une cause différente :

1. **Sur le serveur lui-même**, ouvrir cette adresse. La page doit s'afficher
   avec un cadenas. Si elle s'affiche avec un avertissement, l'autorité n'a pas
   été inscrite : relancer l'installation en administrateur.
2. **Depuis un autre PC du réseau**, la même adresse. Si elle ne répond pas,
   c'est le pare-feu ou le réseau — voir plus bas.
3. **Depuis un téléphone**, après y avoir installé l'autorité
   `certificats\ac-structa.crt` (iPhone : le profil `ac-structa.mobileconfig`,
   puis Réglages → Général → Informations → Réglages de confiance des
   certificats, et activer « AC STRUCTA »).

---

## 6. Si les téléphones n'aboutissent pas

Le symptôme utile n'est pas « ça ne marche pas » mais **lequel** de ces trois :

| Ce que montre le téléphone | Cause | Qui corrige |
|---|---|---|
| La page tourne, puis « impossible d'ouvrir la page » | port fermé, ou isolation des clients sur le Wi-Fi | service informatique / prestataire |
| Avertissement de certificat | autorité installée mais pas approuvée (iPhone : Réglages de confiance) | vous |
| La page s'ouvre | rien | — |

Pour le premier cas, le pare-feu du poste est le premier suspect. Sur un poste
intégré au domaine, les règles entrantes sont pilotées par stratégie de groupe
et une règle posée localement peut être annulée : c'est alors au prestataire
d'ouvrir **TCP 8443 en entrée, portée `192.168.0.0/24`**.

Un diagnostic guidé existe :

```
.venv\Scripts\python.exe outils\diagnostic_reseau.py
```

Il dit lequel des maillons est en cause plutôt que de laisser deviner.

---

## 7. Après la mise en service

- **Réservation DHCP** pour le poste serveur, à demander au prestataire. Le
  certificat est lié à l'adresse IP : si elle change, l'accès est rompu et le
  certificat doit être refait et réinstallé sur tous les téléphones.
- **Sauvegarde** : `deploiement\windows\Sauvegarder.ps1`, à planifier. Elle
  bascule seule sur `pg_dump` en lisant `.env`.
- **Certificat** : valable un peu plus d'un an (limite imposée par Apple). Pour
  le refaire : `.venv\Scripts\python.exe outils\certificat_https.py --refaire`,
  puis réinstaller l'autorité sur les téléphones.
