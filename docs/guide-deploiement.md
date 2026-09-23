# Mettre le WMS Structa en serveur

Ce guide couvre le passage d'un poste isolé à un **serveur** que les postes et les
téléphones de l'entrepôt interrogent, avec une **base PostgreSQL**.

À lire dans l'ordre. Comptez une demi-journée, dont l'essentiel est de l'attente
d'installation.

---

## Ce qui change, et pourquoi

| | Aujourd'hui (poste) | Après (serveur) |
|---|---|---|
| Démarrage | quelqu'un double-clique sur le `.bat` | automatique au démarrage de la machine, sans session ouverte |
| Base | un fichier `db.sqlite3` | PostgreSQL |
| Écritures simultanées | SQLite verrouille toute la base pendant une écriture | plusieurs postes écrivent en même temps |
| Sauvegarde | copier un fichier à la main | `pg_dump` planifié, avec rotation |
| Panne | personne ne le sait | la sonde `/api/sante/` répond 503 |

Le point qui compte vraiment : **SQLite verrouille la base entière à chaque
écriture**. Un poste tient très bien. Cinq opérateurs qui rangent des cabines en
même temps commencent à se croiser, et l'un d'eux voit « database is locked ».
C'est la raison technique de passer sur PostgreSQL, pas une question de volume.

---

## La bascule définitive : un double-clic

Quand la répétition vous a convaincue, **`Basculer-PostgreSQL.bat`** prépare la
base d'**exploitation** — `wms`, pas `wms_essai` — et fait passer le WMS dessus
pour de bon.

Ce qu'il fait, dans l'ordre : retour temporaire sur SQLite (pour exporter depuis
la source d'origine, même si `.env` est déjà basculé), export en lecture seule,
pilote, rôle applicatif et base, bascule de `.env`, `migrate`, reprise avec
comptages vérifiés, puis un **contrôle d'exploitation qui écrit réellement** avant
d'annuler — parce qu'une base peut être complète et pourtant inutilisable.

Trois différences avec la répétition, toutes voulues :

| | `Tester-PostgreSQL.bat` | `Basculer-PostgreSQL.bat` |
|---|---|---|
| Base | `wms_essai`, jetable | `wms`, d'exploitation |
| Base déjà existante | **supprimée** et recréée | **refus** si elle contient des tables |
| Fin | état + contrôle serveur | + écriture réelle, puis annulation |

`db.sqlite3` n'est jamais modifié : il reste votre filet. Retour arrière :
`Revenir-SQLite.bat`.

---

## 0. D'abord, répéter sur votre poste

**Ne découvrez pas PostgreSQL le jour de la mise en service.** Votre poste peut
faire tourner exactement la même pile — PostgreSQL compris — avec vos vraies
données, et revenir en arrière en une commande. C'est la répétition générale, et
elle ne coûte qu'une petite heure.

**Préalable, une fois :** installer PostgreSQL depuis
<https://www.postgresql.org/download/windows/>. Noter le mot de passe du compte
`postgres` demandé à l'installation, et **cocher « Command Line Tools »** — c'est
ce qui fournit `psql` et `pg_dump`.

Puis **double-cliquer sur `Tester-PostgreSQL.bat`** à la racine du projet.
(Équivalent en ligne de commande :
`powershell -ExecutionPolicy Bypass -File deploiement\windows\Repeter-PostgreSQL.ps1`.)

Le script enchaîne : export de vos données actuelles (en lecture seule), pilote
PostgreSQL, création d'une base d'**essai** `wms_essai`, bascule de `.env`,
migrations, reprise avec vérification des comptages, puis état final.

### Où est PostgreSQL, une fois installé ?

Nulle part où l'on clique — et c'est normal. **PostgreSQL n'est pas une
application qui s'ouvre**, c'est un *service* Windows qui démarre avec le poste
et attend des connexions sur le port 5432. On ne le « lance » pas : il tourne.

Ce qui s'ouvre, ce sont ses outils :

| Outil | Où | À quoi ça sert |
|---|---|---|
| **pgAdmin 4** | menu Démarrer → « pgAdmin » | Le gestionnaire graphique. Voir les tables, lire les données, lancer du SQL. Installé avec PostgreSQL. S'ouvre dans le navigateur. |
| **psql** | PowerShell : `psql -U postgres` | La même chose en ligne de commande. C'est ce qu'utilisent les scripts — qui le localisent seuls, sans réglage de PATH. |
| **Services Windows** | `services.msc` → `postgresql-x64-…` | Vérifier que le service tourne, l'arrêter, le redémarrer. |
| **`Quelle-Base.bat`** | racine du projet | **Le seul qui compte au quotidien** : sur quelle base le WMS écrit-il en ce moment, et que contient-elle. |

Dans pgAdmin, les tables du WMS sont sous
`Servers → PostgreSQL → Databases → wms_essai → Schemas → public → Tables`,
nommées `wms_emplacement`, `wms_cabine`, `wms_mouvementcabine`…

> pgAdmin sert à **regarder**. Ne modifiez pas les données par là : le WMS tient
> le journal des cabines, et une position changée à la main dans la table n'y
> laisse aucune trace — plus personne ne saura l'expliquer.

Ensuite, `Demarrer-WMS.bat` comme d'habitude : l'application tourne sur
PostgreSQL, avec vos données. Éprouvez-la pour de bon — connexion, scan d'un
emplacement, rangement d'une cabine, création d'un rack, impression d'une bande,
et le journal.

### Revenir à SQLite à tout moment

**Double-cliquer sur `Revenir-SQLite.bat`**, ou :

```bat
.venv\Scripts\python.exe outils\basculer_base.py sqlite
```

Votre `db.sqlite3` est resté intact pendant toute la répétition : l'export ne fait
que lire. Les réglages PostgreSQL restent en commentaire dans `.env`, prêts à
resservir — repasser dessus ne demande pas de les ressaisir.

### Savoir sur quelle base on travaille

C'est **le** piège de cette période : deux bases répondent, une seule contient le
travail du jour.

```bat
Quelle-Base.bat          rem ou : python outils\basculer_base.py etat
```

Affiche le moteur, la base, et surtout **le nombre d'emplacements, de cabines et
d'événements**. Les comptages sont le seul repère fiable.

> `.env` est sauvegardé avant chaque bascule (`.env.avant-<horodatage>`, les dix
> derniers conservés). C'est le fichier qui décide où partent les écritures de
> l'entrepôt : il ne se modifie pas à l'aveugle.

Quand la répétition vous a convaincue, passez à la suite — le serveur.

---

## 1. Préparer la machine serveur

Un PC dédié suffit : 4 Go de RAM, un disque SSD, et **allumé en permanence**.
Ce dernier point n'est pas un détail — c'est ce qui distingue un serveur d'un
poste de travail.

Installer :

1. **Python 3.12+** — cocher « Add Python to PATH ».
2. **PostgreSQL 16** — depuis <https://www.postgresql.org/download/windows/>.
   Noter le mot de passe du compte `postgres` demandé à l'installation.
   Cocher « Command Line Tools » : c'est ce qui fournit `psql` et `pg_dump`.
3. Copier le dossier du projet, par exemple dans `C:\WMS\wms-structa`.

Fixer une **adresse IP fixe** à la machine (ou une réservation DHCP côté box) :
les téléphones se connecteront à cette adresse, et elle ne doit pas changer.

---

## 2. Créer la base

Ouvrir `deploiement\postgresql\creer-base.sql`, **remplacer le mot de passe**
d'exemple, puis :

```bat
psql -U postgres -f deploiement\postgresql\creer-base.sql
```

Le script crée un rôle `wms` et une base `wms` qui lui appartient.
L'application ne se connecte **jamais** en `postgres` : un défaut applicatif
deviendrait sinon un pouvoir d'administration sur toutes les bases de la machine.

Renseigner ensuite `.env` :

```
DJANGO_DB_ENGINE=django.db.backends.postgresql
DJANGO_DB_NAME=wms
DJANGO_DB_USER=wms
DJANGO_DB_PASSWORD=<le mot de passe choisi>
DJANGO_DB_HOST=127.0.0.1
DJANGO_DB_PORT=5432
```

Vérifier l'accès avant d'aller plus loin :

```bat
psql -U wms -d wms -h 127.0.0.1 -f deploiement\postgresql\verifier-acces.sql
```

---

## 3. Reprendre les données existantes

**C'est l'étape à risque.** Pas parce qu'elle peut échouer — parce qu'elle peut
réussir *à moitié* : une base d'apparence normale, mais amputée d'une table que
personne ne remarque avant le jour où une cabine manque à l'appel.

L'outil de reprise s'en prémunit par un **manifeste de comptages** : l'export
compte les lignes de chaque table, l'import recompte après chargement, et
**annule tout** au moindre écart.

```bat
rem 1. AVANT de basculer .env — encore sur SQLite
.venv\Scripts\python.exe manage.py reprise_sql exporter --vers reprise

rem 2. basculer .env sur PostgreSQL (section 2), puis créer le schéma
.venv\Scripts\python.exe manage.py migrate

rem 3. charger, avec vérification automatique
.venv\Scripts\python.exe manage.py reprise_sql importer --depuis reprise
```

La sortie de l'étape 1 liste ce qui part, table par table. Celle de l'étape 3
confirme que les comptages sont identiques — ou refuse, sans rien avoir écrit.

> **Répétez la reprise à blanc avant le jour J**, sur une copie de `db.sqlite3`.
> Elle ne modifie jamais la source : l'export est en lecture seule.

Contrôle indépendant, à n'importe quel moment ensuite :

```bat
.venv\Scripts\python.exe manage.py reprise_sql verifier --depuis reprise
```

Conservez le dossier `reprise\` quelques semaines : c'est votre filet si un
problème apparaît après la bascule.

---

## 4. Installer le service

Dans une console **PowerShell ouverte en administrateur**, depuis le dossier du
projet :

```
Installer-WMS.bat
```

Le script enchaîne : Python, environnement du projet, dépendances (hors ligne
depuis `paquets\` si ce dossier existe), `.env` avec clé secrète tirée au hasard,
rôle et base PostgreSQL, schéma, reprise des données, certificat HTTPS de ce
poste, autorité dans le magasin Windows, règle de pare-feu, puis contrôle de
pré-vol. Tout est consigné dans `logs\installation.log`.

Pas à pas, avec la liste de ce qu'il faut télécharger sur le poste serveur :
**`docs/guide-serveur.md`**.

> `Installer-Serveur.ps1` a été retiré : il installait le WMS en HTTP sur le port
> 8000, avant que le HTTPS ne devienne nécessaire au scan par caméra.

**Pourquoi une tâche planifiée et non un service Windows :** elle est native
(aucun outil tiers à télécharger), elle démarre **sans session ouverte** — le WMS
repart donc tout seul après une coupure de courant — et elle sait se relancer
après un échec. Pour une gestion de service complète (arrêt propre, dépendances
entre services), installez [NSSM](https://nssm.cc) et pointez-le sur
`deploiement\windows\Demarrer-serveur.bat`.

Commandes utiles :

```powershell
Get-ScheduledTask -TaskName "WMS Structa" | Get-ScheduledTaskInfo   # état, dernier résultat
Start-ScheduledTask  -TaskName "WMS Structa"                        # démarrer
Stop-ScheduledTask   -TaskName "WMS Structa"                        # arrêter
```

---

## 5. Vérifier avant d'ouvrir aux opérateurs

```bat
.venv\Scripts\python.exe outils\preparer_serveur.py
```

Le contrôle de pré-vol passe en revue ce qui, en pratique, fait rater une mise en
production : clé secrète d'exemple, `DEBUG` resté actif, base injoignable, schéma
en retard, aucun compte administrateur, bibliothèques du scanner absentes,
journaux non inscriptibles. Il sort en code 1 s'il reste un point bloquant — et
`Demarrer-serveur.bat` refuse alors de lancer le service.

Puis, depuis un autre poste du réseau :

| Adresse | Attendu |
|---|---|
| `http://<ip-serveur>:8000/` | l'écran de connexion |
| `http://<ip-serveur>:8000/api/sante/` | `{"service":"ok","base":"ok","migrations":"ok"}` |
| `http://<ip-serveur>:8000/admin/` | l'administration Django |

Enfin, le vrai test : **connectez-vous, scannez un emplacement, rangez une cabine,
et vérifiez que le journal l'a enregistré.** Une base qui répond ne prouve pas que
le métier fonctionne.

---

## 6. Sauvegarder

Une sauvegarde qu'on ne sait pas restaurer n'est pas une sauvegarde. Le script
vérifie que le fichier produit n'est pas vide et **affiche la commande de
restauration à chaque passage** — gardez-la sous les yeux.

```powershell
powershell -ExecutionPolicy Bypass -File deploiement\windows\Sauvegarder.ps1 -Destination "D:\Sauvegardes\WMS"
```

À planifier une fois par nuit :

```powershell
$a = New-ScheduledTaskAction -Execute "powershell.exe" `
     -Argument "-ExecutionPolicy Bypass -File C:\WMS\wms-structa\deploiement\windows\Sauvegarder.ps1"
$d = New-ScheduledTaskTrigger -Daily -At 22:30
Register-ScheduledTask -TaskName "WMS Structa - sauvegarde" -Action $a -Trigger $d `
    -User "SYSTEM" -RunLevel Highest
```

**Testez une restauration une fois**, sur une base de test, avant d'en avoir
besoin :

```bat
createdb -U postgres wms_test
pg_restore -U postgres -d wms_test --clean --if-exists D:\Sauvegardes\WMS\wms_2026-08-25_2230.dump
```

Sortez au moins une copie de la machine (disque externe, partage réseau) : une
sauvegarde stockée sur le disque qui tombe ne sert à rien.

---

## 7. Superviser

- **`/api/sante/`** répond 200 si tout va bien, **503** si la base est injoignable
  ou si le schéma est en retard sur le code. C'est le point à interroger depuis un
  outil de supervision — il n'exige aucun compte et ne divulgue rien.
- **`logs\wms.log`** (rotation automatique, 5 fichiers de 2 Mo) : le premier
  endroit à regarder quand un opérateur signale un problème de la veille.

---

## Variante : Docker — retirée

Cette variante a été retirée du dépôt : le WMS tourne sur un poste Windows, où
Docker n'est pas installé et n'apporterait qu'une couche de plus à diagnostiquer.
Les fichiers sont dans `_a_supprimer\deploiement-docker\` si le besoin revient.

---

## Et si l'application doit sortir du réseau de l'entrepôt

Le tunnel Cloudflare dépanne mais donne une adresse **publique** qui change à
chaque lancement. Pour un accès durable depuis l'extérieur, l'ordre de préférence :

1. **VPN vers le réseau de l'entrepôt** — rien n'est exposé, aucune configuration
   à changer côté WMS ;
2. **Reverse-proxy HTTPS** (Nginx, IIS, Caddy) avec un vrai certificat. Poser
   alors dans `.env` :
   ```
   DJANGO_DERRIERE_PROXY=True
   DJANGO_CSRF_ORIGINS=https://wms.structa.fr
   DJANGO_ALLOWED_HOSTS=wms.structa.fr
   ```
   Sans la première ligne, les cookies de session circulent sans l'attribut
   `Secure`. Sans la deuxième, la connexion à `/admin/` échoue en « CSRF
   verification failed ».

**Ne mettez jamais `DJANGO_DERRIERE_PROXY=True` sans proxy HTTPS devant** : le
navigateur serait redirigé vers une adresse `https://` qui n'existe pas, et
l'application deviendrait inaccessible depuis le Wi-Fi local.

---

## Dépannage

| Symptôme | Cause la plus fréquente |
|---|---|
| Le service ne démarre pas | Voir `logs\wms.log`, puis `outils\preparer_serveur.py`. Neuf fois sur dix : `.env` incomplet ou base injoignable. |
| « database is locked » | Encore sur SQLite avec plusieurs postes. Passer sur PostgreSQL (sections 2 et 3). |
| Page sans style, boutons inertes | Statiques non servis. Vérifier `DJANGO_SERVIR_STATIQUES=True` dans `.env`. |
| « CSRF verification failed » sur `/admin/` | Derrière un proxy HTTPS sans `DJANGO_CSRF_ORIGINS`. |
| Le scan caméra ne marche pas | La caméra exige HTTPS. Sur le réseau local en `http://`, la saisie manuelle prend le relais. |
| « duplicate key » après la reprise | Séquences non recalées. `reprise_sql importer` le fait ; un `loaddata` lancé à la main, non. |
| L'appli redevient joignable puis retombe | La tâche planifiée relance en boucle un service qui échoue. Lire `logs\wms.log`. |
| Mes cabines d'hier ont disparu | Vous n'êtes pas sur la même base. `Quelle-Base.bat` donne le verdict en trois chiffres. |
| « Le service PostgreSQL ne répond pas » | Le service est arrêté. `services.msc`, chercher `postgresql-x64-…`, démarrer. Le script s'arrête **avant** de demander les mots de passe : la cause est le service, pas le mot de passe. |
| « La base wms existe déjà et contient N tables » | Garde-fou volontaire : ce script n'écrase pas une base d'exploitation. Soit vous jetez la base à la main (`psql -U postgres -c "DROP DATABASE wms;"`), soit vous relancez avec `-Base wms2`. |
| « PostgreSQL est introuvable » alors qu'il est installé | **N'était pas de votre fait.** L'installeur Windows n'ajoute pas son dossier `bin` au PATH, et les scripts testaient bêtement le PATH. Ils cherchent maintenant eux-mêmes dans `Program Files\PostgreSQL\*\bin`. S'il persiste, c'est que « Command Line Tools » n'a pas été coché à l'installation : `Get-ChildItem 'C:\Program Files\PostgreSQL' -Recurse -Filter psql.exe` tranche. |
