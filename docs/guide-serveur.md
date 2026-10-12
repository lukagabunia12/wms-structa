# Mettre le WMS sur le serveur Windows

Ce guide monte le WMS sur le serveur Windows, y transfère les données du PC
actuel, puis décrit l'exploitation au quotidien : démarrage automatique,
sauvegardes, ménage des journaux, mise à jour, restauration.

Le principe : rien n'est bricolé à la main sur le serveur. On prépare une copie
propre sur le PC, on l'emporte, on double-clique un fichier sur le serveur.
Ensuite, le WMS tourne seul : il démarre avec Windows, sans session ouverte, il
est sauvegardé deux fois par jour, et ses journaux sont nettoyés chaque semaine.

Compter **une heure** le jour J, dont l'essentiel en attente.

---

## En bref

| Quand | Qui | Quoi |
|---|---|---|
| Avant | service informatique | serveur prêt, adresse IP fixe, nom `wms.structa.fr` dans le DNS interne, port 8443 ouvert, partage réseau pour la copie des sauvegardes (§ 1) |
| Avant | vous | Python et PostgreSQL installés sur le serveur (§ 1) |
| Jour J | vous | arrêter le WMS sur le PC, `Preparer-Copie.bat`, copier, `Installer-WMS.bat`, vérifier (§ 2 à 5) |
| Jour J | service informatique | faire pointer `wms.structa.fr` sur le serveur (§ 6) |
| Après | vous | neutraliser l'ancien PC, retirer l'accès de test, essayer une restauration (§ 6, 8, 11) |

---

## 1. Ce qu'il faut sur le serveur

### La machine

- **Windows Server** 2019, 2022 ou 2025 — ou un Windows 10/11 Pro dédié —,
  **allumé en permanence**.
- 2 cœurs et 4 Go de mémoire suffisent. Prévoir **10 Go libres** : c'est très
  au-dessus du besoin — la base et ses sauvegardes se comptent en centaines de
  mégaoctets au plus — et le ménage hebdomadaire en donne la mesure exacte
  (`logs\nettoyage.log`).
- **Fuseau horaire** : (UTC+01:00) Paris. Les heures des sauvegardes suivent
  l'horloge de Windows.
- **Mises à jour Windows** : redémarrages programmés hors des heures de travail.
  Le WMS repart seul au démarrage, mais un redémarrage à 10 h coupe les caristes
  deux minutes.
- Sur un Windows 10/11 : mise en veille **jamais**.

### Python

<https://www.python.org/downloads/windows/>

**La même version que sur le PC actuel.** Le dossier de dépendances hors ligne
(`paquets\`) est fabriqué pour une version précise de Python ; une autre version
le rend inutilisable, et l'installation s'arrête en le disant. Pour connaître la
version du PC, depuis le dossier du projet : `.venv\Scripts\python.exe --version`.

Pendant l'installation, deux choix comptent :

- cocher **« Add python.exe to PATH »** sur le premier écran ;
- choisir **« Install for all users »** (« Customize installation », puis la case
  « Install Python for all users »).

Le second n'est pas cosmétique : `Installer-WMS.bat` tourne en administrateur,
et sur un poste du domaine l'élévation bascule souvent sur un autre compte —
pour lequel un Python installé « pour moi seulement » n'existe pas.

> Pas de Python du Microsoft Store : il ne sait pas créer d'environnement de
> projet. Si l'installation dit que Python est introuvable, `Trouver-Python.bat`
> liste les interpréteurs du poste, et `Installer-WMS.bat -Python "C:\…\python.exe"`
> désigne le bon.

### PostgreSQL

<https://www.postgresql.org/download/windows/>

**La version 18**, celle du PC (ou plus récente). Pendant l'installation :

- cocher **« Command Line Tools »** : `psql`, `pg_dump` et `pg_restore` — les
  sauvegardes et les restaurations en ont besoin ;
- **noter le mot de passe du compte `postgres`**. Il sera demandé une fois, à
  l'installation du WMS, et rien ne permet de le retrouver ensuite.

### Les mots de passe

Le mot de passe du compte `wms` est écrit dans `.env`, et ce fichier a ses
règles de lecture. L'installation **refuse** donc un mot de passe :

- avec des accents ou des caractères hors du clavier américain (é, ç, €, °…) ;
- avec des espaces, avec « # », avec « ${ » ;
- qui commence par un guillemet ou une apostrophe.

Lettres, chiffres et ponctuation simple (`- _ . ! @ % + =`) : aucun souci.

### Le réseau — à demander au service informatique

- **Adresse IP fixe** (ou réservation DHCP) pour le serveur.
- **Nom DNS** : `wms.structa.fr` → adresse du serveur, dans le DNS **interne**,
  celui qu'interrogent les téléphones en Wi-Fi. La veille de la bascule, abaisser
  la durée de vie (TTL) de cet enregistrement à 5 minutes : les téléphones
  suivront le changement dans l'heure.
- **Pare-feu** : TCP **8443 entrant**, depuis le réseau des postes et du Wi-Fi.
  L'installation pose la règle Windows ; une stratégie de groupe peut l'annuler,
  et un pare-feu entre deux réseaux (Wi-Fi et serveurs) demande sa propre règle.
- **Wi-Fi** : pas d'isolation entre les téléphones et le serveur.
- Un serveur **hors domaine** dont le réseau est classé « Public » : la règle de
  pare-feu ne s'y applique pas (l'installation le signale). Le classer en
  « Privé ».

### Où iront les sauvegardes

- un **second disque** du serveur (D:) pour le dossier des sauvegardes ;
- un **partage réseau** (NAS, autre serveur) pour leur copie hors de la machine.
  Les tâches tournent sous le compte SYSTEM : sur le réseau, le serveur se
  présente sous le **compte de la machine**, `<DOMAINE>\<NOM-DU-SERVEUR>$`.
  C'est à lui que le partage doit donner le droit d'écrire. Partage hors du
  domaine : voir § 8, « La copie hors de la machine ».

### Antivirus

Exclure de l'analyse en temps réel le dossier des données de PostgreSQL
(`C:\Program Files\PostgreSQL\18\data`) : c'est la recommandation habituelle pour
une base de données — un fichier verrouillé par l'analyse au mauvais moment fait
échouer une écriture. À valider avec le service informatique.

---

## 2. Le jour J, sur le PC : préparer la copie

**a. Les dépendances hors ligne** — une seule fois, et à refaire seulement si
`requirements.txt` change :

```
Preparer-Paquets.bat
```

Le serveur n'aura peut-être pas accès à internet : avec ce dossier, la question
ne se pose pas.

**b. Arrêter le WMS sur le PC** : fermer sa fenêtre. La copie refuse de se faire
tant qu'il tourne — l'export des données doit être la **dernière écriture** du
PC, sinon ce qui serait saisi ensuite ne partirait pas.

**c. Fabriquer la copie** :

```
Preparer-Copie.bat --avec-autorite
```

`--avec-autorite` emporte l'autorité de certification du PC : le serveur signe
son certificat avec la même autorité, et les téléphones qui l'ont déjà installée
n'ont **rien à refaire**. Ils restent même connectés : leurs jetons de connexion
voyagent avec les données. En contrepartie, la copie porte la clé de l'autorité
— de quoi se faire passer pour n'importe quel site auprès de ces téléphones :
clé USB chiffrée ou partage réservé, et **effacer la copie** une fois le serveur
installé.

Sans l'option, le serveur crée sa propre autorité, à installer sur chaque
téléphone (`certificats\ac-structa.crt`, profil `.mobileconfig` sur iPhone).

Le résultat : `WMS-Structa_a-copier_<date>\` et son archive `.zip`, à côté du
dossier du projet.

Ce qui **part** : le code, les dépendances hors ligne, les données de l'entrepôt
(dans `reprise\`, exportées au passage, avec les comptes et leurs mots de passe
chiffrés). Ce qui **ne part pas** :

| Écarté | Raison |
|---|---|
| `.venv\` | chemins et binaires propres au PC |
| `.env` | clé secrète et mot de passe de la base : refaits sur le serveur |
| `certificats\` | émis pour les adresses du PC — sauf l'autorité, avec `--avec-autorite` |
| `db.sqlite3` | ancienne base : les données partent par `reprise\` |
| `logs\`, `sauvegardes\`, `staticfiles\` | propres au PC |
| classeurs `.xlsx` de la racine | fichiers de production : ils s'importent par l'écran dédié |

Le script vérifie ensuite qu'aucun secret n'a échappé au filtre, et détruit la
copie plutôt que de la laisser partir avec.

**À partir de maintenant, plus rien ne se saisit sur le PC.**

---

## 3. Copier sur le serveur

Poser le dossier là où il doit **rester** : les tâches planifiées pointent dessus,
le déplacer ensuite oblige à réinstaller. Par exemple `C:\WMS-Structa\` (ou
`D:\WMS-Structa\`).

Éviter le Bureau, `Téléchargements` et OneDrive : un dossier synchronisé
verrouille des fichiers au mauvais moment.

---

## 4. Installer

Dans le dossier copié, double-cliquer — ou, pour donner le nom de domaine, depuis
une invite de commandes :

```
Installer-WMS.bat -Noms wms.structa.fr
```

Répondre **Oui** à la demande de droits administrateur. Sans `-Noms`,
l'installation demande le nom de domaine (Entrée si les téléphones utilisent
l'adresse IP). Puis quatre questions :

1. le mot de passe à **donner** au compte `wms` de la base — vous le choisissez
   (règles du § 1), il est écrit dans `.env`, vous n'aurez plus à le retenir ;
2. le mot de passe du compte **`postgres`** ;
3. le **dossier des sauvegardes** — proposé : `WMS-Sauvegardes` à la racine du
   disque du WMS ; mieux vaut un autre disque, `D:\WMS-Sauvegardes` ;
4. la **seconde destination**, hors de la machine (`\\nas\sauvegardes\WMS`) —
   Entrée pour s'en passer pour l'instant (l'accueil de l'administration le
   rappellera).

Aucun mot de passe n'est affiché ni écrit dans le journal. Le dossier du WMS
est d'abord réservé aux administrateurs et au service — avant qu'aucun secret
n'y soit écrit. Le script enchaîne ensuite douze étapes : Python,
environnement, dépendances, `.env`, base PostgreSQL, reprise des données,
certificat HTTPS, pare-feu, contrôle de pré-vol, puis les **tâches
planifiées**, une **première sauvegarde** lancée par la tâche elle-même — c'est
elle qui prouve que les droits sont bons — et le **démarrage** du WMS.

Tout est consigné dans `logs\installation.log`.

**L'installation se relance sans risque.** Une base qui porte déjà des tables
n'est jamais écrasée ; si `.env` désigne une base en service, ni le compte, ni
son mot de passe, ni les données ne sont touchés. Les heures des tâches et le
compte de la sauvegarde sont retenus d'une fois sur l'autre (dans `.env`) : une
réinstallation ne les remet pas aux valeurs par défaut. Le certificat est refait
s'il ne couvre plus un nom ou une adresse de la machine.

| Option | Effet |
|---|---|
| `-Noms wms.structa.fr` | le nom que tapent les téléphones : certificat, hôtes autorisés |
| `-Sauvegardes D:\WMS-Sauvegardes` | dossier des sauvegardes, sans question |
| `-CopieSauvegardes \\nas\…\WMS` | seconde destination, sans question |
| `-HeuresSauvegarde "12:30,22:30"` | heures des sauvegardes (défaut ; retenues ensuite) |
| `-NettoyageTousLes 7` | fréquence du ménage des journaux, en jours (défaut : chaque dimanche ; retenue ensuite) |
| `-Taches` | seulement le pré-vol, les tâches, une sauvegarde d'essai et le redémarrage |
| `-SansTaches` | poste d'essai : rien ne démarre tout seul |
| `-Tunnel` | accès par tunnel tant que le port 8443 n'est pas ouvert (adresse **publique**) |
| `-SansPostgreSQL` | secours sur SQLite, quelques jours au plus |

---

## 5. Vérifier

**a. `Etat-WMS.bat`** — tout l'état du serveur en un écran :

- les trois tâches du dossier « WMS Structa », leur dernier passage et le
  prochain ;
- les ports 8443 (téléphones) et 8000 (application, sur la machine seulement) ;
- la **santé** : `OK` et `{"service":"ok","base":"ok","migrations":"ok"}` ;
- le certificat : jours restants, et les noms qu'il ne couvrirait pas ;
- les sauvegardes et la place libre.

**b. Dans un navigateur du serveur**, puis d'un autre PC, puis d'un téléphone :
`https://wms.structa.fr:8443` (tant que le DNS n'est pas basculé :
`https://<adresse-du-serveur>:8443`). La page doit s'ouvrir avec un cadenas.

**c. L'accueil de l'administration** (`/admin/`), cadre **« Sauvegardes et
disque »** : la première sauvegarde y figure.

**d. Le vrai test** : se connecter, scanner un emplacement, ranger une cabine,
retrouver le geste au journal. Une base qui répond ne prouve pas que le métier
fonctionne.

---

## 6. Basculer les téléphones et neutraliser le PC

1. **Le DNS** : le service informatique fait pointer `wms.structa.fr` sur
   l'adresse du serveur. Les téléphones suivent à l'expiration de leur cache.
2. **Les téléphones** : copie faite avec `--avec-autorite`, rien à faire. Sinon,
   installer la nouvelle autorité sur chacun (`docs/guide-https.md`).
   Les téléphones qui ouvraient le WMS par l'**adresse IP** du PC doivent passer
   à `https://wms.structa.fr:8443` (ajouter de nouveau l'icône sur l'écran
   d'accueil).
3. **Le PC** : ajouter à son fichier `.env` la ligne

   ```
   WMS_REMPLACE_PAR=https://wms.structa.fr:8443
   ```

   `Demarrer-WMS.bat` refuse alors de relancer le WMS sur le PC, et dit où il est
   passé. Sans elle, un double-clic par habitude ferait renaître une seconde
   base, où des cabines seraient rangées sans que le serveur le sache.

Le retour sur le PC n'est simple que le premier jour, tant que rien n'a été
saisi sur le serveur : retirer la ligne, remettre le DNS.

---

## 7. Au quotidien

### Les fichiers à double-cliquer (racine du dossier, sur le serveur)

| Fichier | Effet |
|---|---|
| `Etat-WMS.bat` | tout l'état du serveur en un écran |
| `Arreter-WMS.bat` | arrête le WMS **pour de bon** : il ne repart pas, même au redémarrage de Windows |
| `Redemarrer-WMS.bat` | le remet en service (les migrations éventuelles s'appliquent au passage) |
| `Sauvegarder-WMS.bat` | une sauvegarde tout de suite — avant une mise à jour, une opération délicate |
| `Restaurer-WMS.bat` | revenir à une sauvegarde (§ 8) |
| `Quelle-Base.bat` | sur quelle base, et combien d'emplacements, de cabines, d'événements |

`Demarrer-WMS.bat` reste l'outil d'un poste de travail : sur le serveur, c'est la
tâche planifiée qui démarre le WMS.

### Ce qui tourne tout seul

Trois tâches, dans le Planificateur de tâches, dossier **« WMS Structa »**, toutes
sous le compte SYSTEM — aucun mot de passe stocké, rien qui expire :

| Tâche | Quand | Ce qu'elle fait |
|---|---|---|
| Service | au démarrage de Windows, puis toutes les 2 minutes | démarre le WMS ; s'il tourne, ne fait rien ; s'il est tombé, le relance |
| Sauvegarde | 12:30 et 22:30 | base et configuration, vérifiées, avec rotation (§ 8) |
| Nettoyage | le dimanche à 03:15 | journaux trop anciens, mesures (§ 9) |

Le Planificateur, livré à lui-même, arrête une tâche au bout de trois jours ou
quand il croit la machine sur batterie (un onduleur USB) : ces réglages sont
neutralisés à l'installation.

### Où regarder

| Où | Quoi |
|---|---|
| `logs\service.log` | chaque démarrage du WMS, et pourquoi il n'a pas démarré |
| `logs\wms.log` | erreurs de l'application, gestes sensibles (suppressions, réglages) |
| `logs\sauvegarde.log` | chaque sauvegarde et chaque restauration |
| `logs\nettoyage.log` | chaque ménage : ce qui est parti, ce que pèsent journaux, base et sauvegardes |
| `logs\taches-erreurs.log` | les erreurs imprévues des tâches (vide en temps normal) |
| `logs\installation.log` | chaque installation |
| Observateur d'événements → Journaux Windows → Application, source **« WMS Structa »** | 900 : sauvegarde réussie, 901 : en échec ; 910 / 911 : restauration — c'est là que regarde un outil de supervision |

---

## 8. Les sauvegardes

### Ce qui est sauvegardé

Chaque passage écrit un **jeu** de deux fichiers sous le même horodatage :

- `wms_<date>.dump` — toute la base, par `pg_dump`, compressée. Le fichier est
  **relu** aussitôt (`pg_restore --list`) : chaque table de la base doit y
  figurer, sinon la sauvegarde est déclarée en échec ;
- `wms_<date>_fichiers.zip` — `.env`, `certificats\` (clé de l'autorité
  comprise) et les sauvegardes de « Repartir de zéro ».

Ces fichiers contiennent la clé secrète, le mot de passe de la base et toutes
les données. Créé par la première sauvegarde, le dossier est réservé aux
administrateurs et à SYSTEM ; de même pour une copie sur un autre disque de la
machine. **Un dossier qui existait déjà garde ses droits** (il peut servir à
autre chose) : l'installation le signale, à vérifier dans Propriétés →
Sécurité. Un partage réseau garde les droits que lui donne le NAS : à réserver
de la même façon.

### Quand, où, combien de temps

- **12:30 et 22:30** : le travail du matin est à l'abri avant l'après-midi.
  Autres heures : `Installer-WMS.bat -Taches -HeuresSauvegarde "12:30,18:00,22:30"`.
- **Où** : `WMS_SAUVEGARDE_DOSSIER` et `WMS_SAUVEGARDE_COPIE` dans `.env`. Un
  changement vaut dès la sauvegarde suivante.
- **Combien de temps** : tout est gardé **30 jours** ; au-delà, la première de
  chaque mois pendant **12 mois** ; et **jamais moins de 7** jeux, quel que soit
  leur âge — si les sauvegardes s'arrêtaient, la rotation n'effacerait pas les
  dernières bonnes. Même règle sur la copie. Réglages : `WMS_SAUVEGARDE_JOURS`,
  `_MOIS`, `_MINIMUM`. Seuls les fichiers nommés `wms_<date>…` sont touchés.

### Savoir qu'elles tournent

L'accueil de l'administration, cadre **« Sauvegardes et disque »** :

| Étiquette | Signifie |
|---|---|
| OK | dernière sauvegarde réussie, copie hors machine à jour |
| À voir | pas de copie hors machine, copie en échec, ou disque presque plein |
| Alerte | la dernière a échoué, ou aucune n'a réussi depuis 30 heures |

La phrase dit quoi faire. `Etat-WMS.bat` affiche la même chose.

### La copie hors de la machine

Une sauvegarde sur le disque qui tombe ne sert à rien. La copie part dans
`WMS_SAUVEGARDE_COPIE`, vérifiée par empreinte.

- **Partage d'un serveur ou d'un NAS du domaine** : donner le droit de
  modification au compte de la machine, `<DOMAINE>\<NOM-DU-SERVEUR>$`.
- **NAS hors du domaine** : la sauvegarde tourne sous un compte dédié, qui doit
  exister sur le NAS avec le même nom et le même mot de passe. Créer ce compte
  local sur le serveur, avec **« Le mot de passe n'expire jamais »** (sinon la
  tâche cesse de démarrer le jour où il expire) — Python doit avoir été installé
  « pour tous les utilisateurs » (§ 1). Puis, dans une invite de commandes en
  administrateur :

  ```
  .venv\Scripts\python.exe outils\serveur_wms.py taches --compte-sauvegarde .\wms-sauvegarde --essayer
  ```

  Windows demande son mot de passe. Le compte reçoit la lecture du dossier du
  WMS, l'écriture de `logs\` et du dossier des sauvegardes, rien de plus. Il
  est retenu : une réinstallation le garde (et redemande son mot de passe).
  Revenir à SYSTEM : `--compte-sauvegarde SYSTEM`.

`Sauvegarder-WMS.bat` tourne sous **votre** compte, pas celui de la tâche : pour
éprouver les droits de la tâche, c'est `Installer-WMS.bat -Taches` (il lance une
sauvegarde par la tâche elle-même), ou, dans le Planificateur, « Exécuter » sur
la tâche Sauvegarde.

### Restaurer

Trois fichiers, dans l'ordre :

1. **`Arreter-WMS.bat`** ;
2. **`Restaurer-WMS.bat`** : il liste les sauvegardes (celles du dossier et de la
   copie), on tape l'horodatage de la première colonne — ou le chemin complet
   d'un fichier `.dump` —, puis **RESTAURER** pour confirmer ;
3. **`Redemarrer-WMS.bat`**.

Les garde-fous :

- la restauration **refuse de tourner** tant que le WMS tourne, ou tant que la
  tâche Service peut le relancer : des caristes qui travaillent sur une base qui
  recule dans le temps, c'est du travail perdu sans que personne le voie ;
- **le filet** : la base actuelle est sauvegardée juste avant d'être remplacée.
  Une restauration choisie par erreur se défait de la même façon, en restaurant
  le filet ;
- le rechargement se fait en **une seule transaction** : un fichier abîmé, une
  erreur, une fenêtre fermée en plein milieu, et la base reste telle qu'elle
  était.

Le zip de configuration n'est pas restauré : remettre un ancien `.env`
changerait le mot de passe de la base sous les pieds du WMS.

### Essayer une restauration, une fois par mois

Une sauvegarde qu'on n'a jamais relue n'est qu'un espoir. Dans une base d'essai,
sans toucher au WMS, depuis une invite de commandes **ouverte en
administrateur** — le dossier des sauvegardes leur est réservé (chaque commande
demande le mot de passe de `postgres`) :

```
cd /d "C:\Program Files\PostgreSQL\18\bin"
createdb -h 127.0.0.1 -U postgres wms_test
pg_restore -h 127.0.0.1 -U postgres -d wms_test --no-owner "D:\WMS-Sauvegardes\wms_2026-10-12_223000.dump"
psql -h 127.0.0.1 -U postgres -d wms_test -c "SELECT count(*) FROM wms_cabine"
dropdb -h 127.0.0.1 -U postgres wms_test
```

Le nombre de cabines doit correspondre à ce que montrait le WMS à l'heure de la
sauvegarde.

### Restaurer sur une machine neuve

Le serveur est perdu. Sur la nouvelle machine, préparée comme au § 1 :

1. copier le code du WMS (dernière copie `Preparer-Copie.bat --sans-donnees`) ;
2. depuis le dernier `wms_<date>_fichiers.zip` de la copie hors machine,
   extraire `certificats\ac-structa.crt`, `ac-structa.key` et
   `ac-structa.mobileconfig` dans `certificats\` : les téléphones garderont leur
   confiance. Ne pas reprendre `.env` : l'installation en fait un neuf ;
3. `Installer-WMS.bat -Noms wms.structa.fr` (base vierge : il demande de créer
   un compte administrateur, qui disparaîtra à la restauration) ;
4. `Arreter-WMS.bat`, `Restaurer-WMS.bat` en donnant le chemin complet du
   dernier `.dump` de la copie, `Redemarrer-WMS.bat` ;
5. le DNS vers la nouvelle adresse.

---

## 9. Les journaux et leur ménage

### Ce qu'ils pèsent

| Journal | Croissance | Plafond |
|---|---|---|
| `logs\wms.log` | quelques Ko par jour | 6 fichiers de 2 Mo (rotation) |
| `logs\service.log` | quelques lignes par démarrage | renommé au-delà de 5 Mo, 3 anciens gardés |
| `logs\sauvegarde.log`, `logs\nettoyage.log` | deux lignes par passage | 4 fichiers de 1 Mo chacun |
| `logs\taches-erreurs.log` | vide en temps normal | renommé au-delà de 2 Mo |
| `logs\installation.log` | à chaque installation | ramené à 256 Ko au-delà de 1 Mo, par le ménage |
| journaux de PostgreSQL (`data\log`) | un fichier par jour et par redémarrage, de l'ordre de 0,1 à 0,2 Mo par jour | **aucun** : PostgreSQL ne les efface jamais sous Windows → le ménage |
| sessions de l'administration (base) | une ligne par connexion | effacées à expiration, par le ménage |
| sauvegardes | deux jeux par jour | rotation (§ 8) |

Hors sauvegardes, l'ensemble reste sous la cinquantaine de mégaoctets. La seule
source sans fin était celle de PostgreSQL : c'est à elle que s'attaque le ménage.

### La tâche de ménage

Chaque dimanche à 03:15, elle efface :

- les journaux de PostgreSQL de plus de **30 jours** (`WMS_JOURNAUX_JOURS` dans
  `.env`), jamais le plus récent ;
- les sessions expirées ;
- les fichiers provisoires abandonnés par une écriture interrompue ;

et raccourcit `installation.log`. Puis elle mesure ce que pèsent journaux,
sauvegardes, base et ses plus grosses tables, et la place libre — dans
`logs\nettoyage.log` et sur l'accueil de l'administration.

Elle ne touche **jamais** à `wms.log` (c'est aussi l'historique des gestes
sensibles : qui a supprimé quoi), ni aux sauvegardes, ni à celles de « Repartir
de zéro ».

Autre fréquence : `Installer-WMS.bat -Taches -NettoyageTousLes 3` (tous les trois
jours), `14` (un dimanche sur deux). Voir ce qui partirait, sans rien effacer :

```
.venv\Scripts\python.exe manage.py nettoyer --simulation
```

---

## 10. Mettre à jour le WMS

1. Sur le poste où se prépare la nouvelle version : `Preparer-Copie.bat
   --sans-donnees` — le code seul.
2. Sur le serveur : `Arreter-WMS.bat`, **puis** `Sauvegarder-WMS.bat` — dans
   cet ordre, la sauvegarde contient le tout dernier geste des caristes.
3. Copier le contenu de la nouvelle copie **par-dessus** le dossier du WMS, en
   remplaçant les fichiers. `.env`, `.venv\`, `certificats\` et `logs\` ne sont
   pas dans la copie : ils restent tels quels. (Une copie par-dessus n'efface
   rien : si une version retire un fichier, elle le dit.)
4. `Installer-WMS.bat`, avec les mêmes options que la première fois
   (`-Noms wms.structa.fr`) : dépendances, migrations, tâches, sauvegarde
   d'essai, redémarrage — sans toucher à la base ni aux mots de passe.
   Si `requirements.txt` n'a pas changé, `Redemarrer-WMS.bat` suffit : les
   migrations s'appliquent au démarrage.
5. `Etat-WMS.bat`. Sur les téléphones, la nouvelle version se charge d'elle-même.

---

## 11. Sécurité : avant d'ouvrir aux caristes

- **Retirer `WMS_ACCES_TEST`** de `.env` s'il y est : l'écran de connexion
  donnerait un identifiant et son mot de passe à quiconque ouvre l'adresse. Le
  contrôle de pré-vol le signale.
- **Effacer la copie** apportée (clé USB, archive `.zip`) : elle contient toute
  la base, et la clé de l'autorité avec `--avec-autorite`.
- Le dossier du WMS et celui des sauvegardes sont réservés aux administrateurs
  et à SYSTEM : ne pas y rouvrir de droits « Utilisateurs ».
- **Mots de passe** : au-delà de 10 échecs sur un compte (ou 30 depuis une même
  adresse) en 15 minutes, la connexion est refusée jusqu'à la fin de la fenêtre,
  même avec le bon mot de passe — l'application comme l'administration.
- **Téléphone perdu** : dans l'administration, « Jeton d'authentification » →
  « Jetons », supprimer celui du compte. Le téléphone devra se reconnecter.

---

## 12. Dépannage

| Symptôme | Cause la plus fréquente |
|---|---|
| `Etat-WMS.bat` : « Santé : injoignable » | Le service n'a pas démarré : la fin de `logs\service.log` s'affiche dessous. Juste après un redémarrage de Windows, PostgreSQL n'est parfois pas prêt : la tâche réessaie toutes les deux minutes. |
| La tâche Service ne cesse de repartir | Un point bloquant au pré-vol, ou la base injoignable : `logs\service.log`. |
| Sauvegardes en **Alerte** | La phrase le dit : `pg_dump` introuvable (`WMS_POSTGRESQL_BIN` dans `.env`), disque plein, base injoignable. |
| Copie « EN ÉCHEC — accès refusé » | Le partage n'autorise pas l'écriture au compte de la machine (`…\<NOM-DU-SERVEUR>$`), ou au compte dédié. |
| Après la bascule, avertissement de certificat sur les téléphones | Copie faite sans `--avec-autorite` : installer la nouvelle autorité. |
| `wms.structa.fr` ne répond pas, l'adresse IP oui | DNS pas encore basculé, ou cache du téléphone (attendre le TTL, ou couper et rallumer le Wi-Fi). |
| Rien ne répond depuis les téléphones | Port 8443 fermé (pare-feu, stratégie de groupe) ou isolation Wi-Fi : `.venv\Scripts\python.exe outils\diagnostic_reseau.py` dit lequel. |
| `Restaurer-WMS.bat` : « la tâche … est active » | Passer par `Arreter-WMS.bat`, qui la désactive. |
| Sur l'ancien PC : « Le WMS ne tourne plus sur ce poste » | Normal : `WMS_REMPLACE_PAR` le renvoie vers le serveur. |
| L'installation refuse un mot de passe | Règles du § 1 : ni accent, ni espace, ni « # », ni « ${ ». |
| « La base wms existe déjà et contient N tables » | Garde-fou : l'installation n'écrase pas une base. Si `.env` la désigne, elle est reprise telle quelle. |
| L'installation s'arrête : « Ce poste travaille sur SQLite, et sa base contient des données » | Serveur monté avec `-SansPostgreSQL` : `Basculer-PostgreSQL.bat` (WMS arrêté) emporte ces données sur PostgreSQL, puis relancer l'installation. |
| Restauration refusée : « le compte wms ne possède pas le schéma public » | Le message donne la commande `ALTER SCHEMA … OWNER TO wms` à lancer une fois. |
| L'installation signale un réseau « Public » | La règle de pare-feu ne s'y applique pas : classer le réseau en Privé (§ 1). |
