# Guide administrateur — WMS Structa

## Installation sur site (poste Windows du LAN)

Le plus simple : double-cliquer sur **`Demarrer-WMS.bat`**, le seul lanceur. Au
premier lancement il installe l'environnement, prépare `.env` (clé secrète générée,
mode production), applique les migrations, télécharge les bibliothèques du scanner,
puis démarre le serveur **en HTTPS** et ouvre le WMS dans le navigateur. La première
fois, le lancer en administrateur (clic droit → Exécuter en tant qu'administrateur) :
il ouvre alors le port 8443 et inscrit l'autorité dans Windows.

En ligne de commande :

1. Installer Python 3.12+.
2. `python -m venv .venv` puis activer ; `pip install -r requirements.txt`.
3. `python outils/preparer_env.py` — crée `.env`, génère la clé secrète, met `DEBUG=False`.
4. `python manage.py migrate` puis `python manage.py createsuperuser`.
5. `python manage.py telecharger_libs` — une fois, avec internet (voir « Sans internet »).
6. Démarrer : `python outils/demarrer_https.py` — waitress sur la boucle locale et le
   HTTPS sur le port 8443, exactement ce que fait `Demarrer-WMS.bat`.

> `python manage.py runserver` est l'outil de **développement** de Django. Il dépanne,
> mais il n'est pas fait pour tenir un poste d'entrepôt à la journée. `waitress`
> (installé par `requirements.txt`) est un vrai serveur d'application, sans binaire
> système à déployer.

### Vérifier qu'on est bien en configuration d'exploitation

```bash
python outils/preparer_env.py --verifier   # clé secrète et DEBUG
python manage.py check --deploy            # liste de contrôle Django
python manage.py test                      # la suite complète doit être verte
```

## Les deux réglages qui comptent vraiment

| Réglage (`.env`) | Valeur attendue | Ce qui arrive sinon |
|---|---|---|
| `DJANGO_SECRET_KEY` | une vraie clé aléatoire | la clé d'exemple est publiée dans le dépôt : n'importe qui peut forger une session d'administrateur. L'application refuse désormais de démarrer dans ce cas. |
| `DJANGO_DEBUG` | `False` | la page d'erreur affiche la configuration complète — clé secrète et mot de passe de base compris — à n'importe quel visiteur, et le CORS s'ouvre à toutes les origines. |

## Accès depuis les téléphones (HTTPS interne)

`Demarrer-WMS.bat` sert le WMS en HTTPS sur le réseau de l'entrepôt — toujours :
l'ancien `Demarrer-WMS-HTTPS.bat` y est fusionné. C'est une obligation, pas un
raffinement : hors HTTPS, les navigateurs mobiles refusent
l'accès à la caméra, et le scan des QR codes est indisponible.

Le lanceur pose lui-même dans l'environnement du serveur :

```
DJANGO_DERRIERE_PROXY=True
DJANGO_CSRF_ORIGINS=https://<adresse-du-serveur>:8443
```

Sans la première ligne, les cookies de session circulent sans l'attribut `Secure`.
Sans la seconde, la connexion à `/admin/` échoue en « CSRF verification failed ».

L'application elle-même n'écoute que sur `127.0.0.1` : seul le port 8443, en
HTTPS, est exposé au réseau. Un `http://<adresse>:8000` depuis un autre poste ne
répond donc pas — c'est voulu, rien ne circule en clair.

Le certificat est émis par une autorité locale, à installer une fois sur chaque
téléphone (`certificats\ac-structa.crt`, ou le profil `.mobileconfig` sur iPhone).
Détail : `docs/guide-https.md`.

> L'ancien accès par tunnel Cloudflare (`Demarrer-WMS-Telephone.bat`) a été
> retiré : il donnait une adresse **publique**, différente à chaque lancement, où
> seul le mot de passe protégeait les données de l'entrepôt.

## Fonctionner sans internet

L'interface s'appuie sur deux bibliothèques JavaScript (lecture du QR à la caméra,
génération des étiquettes). Elles étaient chargées depuis des CDN : **sans internet, le
scan et l'impression d'étiquettes cessaient de fonctionner**. Une commande les installe
une fois pour toutes :

```bash
python manage.py telecharger_libs
```

Elles sont alors servies par Django, depuis `wms/static/app/vendor/`. L'application n'a
plus besoin d'internet. À rejouer avec `--forcer` pour changer de version.

## Comptes et droits

Les comptes se créent et se règlent dans l'administration, **Utilisateurs**. La
fiche d'un compte porte, juste sous l'identifiant, son **rôle** et ses
**droits** — une case par geste.

**Le rôle**

- **Opérateur** : il consulte tout, et fait ce qui est coché — rien d'autre.
- **Lecture seule** : il consulte tout et ne modifie rien ; les cases sont ignorées.
- **Administrateur** : toutes les cases, plus « Repartir de zéro » ; les cases
  sont ignorées.

**Les cases** (rôle Opérateur)

| Groupe | Case | Ce qu'elle permet |
|---|---|---|
| Cabines | Entrer et ranger des cabines | enregistrer une cabine annoncée par le fichier de production, la ranger, la déplacer, lui ajouter un emplacement |
| | Changer le statut d'une cabine | quarantaine, lever la quarantaine — sans elle, la question « quel est son état ? » qui suit un rangement est sautée |
| | Sortir des cabines de l'entrepôt | les envoyer sur chantier (avec le n° de chantier), remettre en stock une cabine revenue |
| | Corriger ou supprimer une fiche cabine | corriger une cabine mal saisie, ou la supprimer |
| Fichier de production | Importer le fichier de production | l'écran « Fichier de production » |
| | Enregistrer une cabine absente du fichier | avec un motif, écrit au journal ; demande aussi « entrer et ranger » |
| Matières premières | Entrer, sortir et déplacer des matières premières | vitrages et cartons |
| | Régler les seuils d'alerte MP | le seuil sous lequel la cloche signale un code |
| Emplacements, racks et modèles | Mettre hors service, condamner une place | et l'inverse : remettre en service, rouvrir |
| | Régler les emplacements | leur code, ce qu'ils rangent, leurs codes MP acceptés, leur description |
| | Créer et supprimer des emplacements et des racks | à l'unité, une sélection, un rack entier |
| | Régler la taille des modèles de cabine | grand modèle ou non |

L'application ne montre à chacun que les boutons de ses cases. Un geste qu'il
ne peut pas faire est absent, ou affiché éteint avec la case qui manque — c'est
le mot à chercher sur sa fiche pour la cocher.

**Les profils prêts à l'emploi.** Dans la liste des comptes, cochez-en un ou
plusieurs, puis choisissez dans « Action » : **Cariste** (les quatre cases des
cabines), **Cariste + MP**, **Matières premières**, **Gestionnaire** (tout le
quotidien, réglages compris, mais ni créer ou supprimer des emplacements, ni le
fichier de production), **Lecture seule**. Un profil fixe le rôle et TOUTES les
cases — passer un gestionnaire en cariste lui retire le reste. Les
administrateurs cochés par mégarde sont laissés tels quels. La colonne
« droits » de la liste dit ce que chacun peut faire : le nom du profil, ou
« Sur mesure » suivi de ses cases ; le filtre « a le droit » répond à « qui
peut… ? ».

À la mise à jour qui a créé ces cases, chaque compte a gardé ce qu'il pouvait
faire, case par case — **sauf « créer et supprimer des emplacements et des
racks »**, que personne n'a reçu d'office : cochez-la pour qui doit l'avoir.

**À savoir aussi**

- Un emplacement ne se supprime pas tant qu'une cabine y est rangée ou que du
  stock MP y est posé : il faut d'abord le libérer. Chaque suppression est notée
  dans `logs/wms.log`, avec son auteur et son motif — comme chaque changement de
  ce que rangent les emplacements (cabines, cartons, vitrages), de leurs codes
  acceptés, et des seuils d'alerte.
- La base des codes MP (vitrages, cartons) se complète dans l'administration,
  **Codes MP** : code élément, famille, désignation, fournisseur, n° article,
  autres références (séparées par « · », toutes cherchables), colisage, **seuil
  d'alerte**, ancienne génération. La liste permet de modifier directement le
  seuil d'alerte, « ancienne génération » et « actif », ligne par ligne ;
  l'application, elle, règle le même seuil pour une sélection de codes (Stock →
  MP → « Régler les seuils d'alerte »). Un code réservé sur des emplacements ne
  change pas de famille et ne se décoche pas « actif » tant qu'il y est réservé :
  l'administration nomme les emplacements à régler d'abord.
- Dans **Emplacements**, la fiche d'un emplacement MP porte ses **codes
  acceptés** (vide : toute sa famille). L'administration y applique la règle de
  l'application : pas de code d'une autre famille, aucun code sur un emplacement
  de cabines. Le réglage courant se fait plutôt dans l'application, à l'unité ou
  en nombre.
- Le **stock MP** et le **journal MP** y sont consultables, jamais modifiables :
  un écart se corrige par une entrée ou une sortie dans l'application, motif
  « Inventaire ». Le journal montre aussi les changements d'emplacement, avec la
  position de départ (« depuis »).
- Les zones se règlent dans l'administration ; une zone à laquelle des
  emplacements sont rattachés ne se supprime pas.
- Gestion via l'administration : `/admin/`. L'administration suit les
  permissions de Django (« Statut équipe », « Statut super-utilisateur »,
  permissions par table), pas les cases du WMS : ne donnez « Statut équipe »
  qu'aux administrateurs du WMS. Exception voulue, les **emplacements** : même
  avec les permissions de Django, on n'y crée rien sans la case « créer et
  supprimer », on n'y règle rien sans « régler les emplacements », et on n'y
  supprime **aucun** emplacement, superutilisateur compris — la suppression se
  fait dans l'application (fiche, sélection, rack), avec ses refus et sa trace.
- Une cabine dont on corrige le numéro suit la règle de l'entrée : vers un
  numéro que le fichier de production n'annonce pas, il faut la case
  « enregistrer une cabine absente du fichier de production » (le journal porte
  alors « hors fichier de production »).

## Repartir de zéro

Remet l'outil à neuf. Réservé au rôle **administrateur**, avec « Statut
équipe » coché pour entrer dans l'administration : lien « Repartir de zéro » sur
l'accueil de l'administration (la page vit sous Cabines → « Repartir de
zéro »).

**Tout est coché** à l'ouverture ; on décoche ce qu'on garde. Chaque partie dit
ce qu'elle efface, avec les nombres du moment :

| Partie | Ce qui part |
|---|---|
| Les cabines | toutes les cabines, leurs positions, leur journal |
| Les matières premières | le stock des vitrages et des cartons, et son journal |
| Le fichier de production | les cabines annoncées — d'ici le prochain import, une cabine entre par saisie libre |
| Le plan de l'entrepôt | emplacements, racks, zones, places condamnées, codes acceptés — les étiquettes QR collées ne mènent plus nulle part tant que les emplacements ne sont pas recréés avec les mêmes codes |
| Les tailles des modèles de cabine | retour aux six grands modèles d'origine |
| La base des codes MP | retour aux codes livrés : codes ajoutés retirés, seuils d'alerte et fiches remis comme à l'installation |

Le plan ne part pas sans les cabines ni le stock MP (ils y sont posés), et la
base des codes ne revient pas sans vider le stock MP : la page coche et décoche
ensemble ce qui va ensemble. **Les comptes restent toujours** — sans eux,
personne ne pourrait se reconnecter ; ils se gèrent dans « Utilisateurs ».
Restent aussi `logs/` et les sauvegardes déjà écrites.

Trois phrases à recopier (« confirmer », la date du jour, une phrase
d'engagement), puis une **sauvegarde** est écrite dans `sauvegardes/` avant le
premier effacement — si elle échoue, rien n'est effacé. Elle contient tout ce
qui part ou change, et se recharge **juste après, avant toute nouvelle saisie** :

```bash
python manage.py loaddata sauvegardes/remise-a-zero_<date>.json
```

Le rechargement rend tout ce qui est parti ou a changé. Une seule chose
reste : un code MP ou un grand modèle d'origine que la remise a **recréé**
(parce qu'il avait été supprimé ou renommé avant) reste en place — la page
l'annonce (« code livré manquant, remis ») ; supprimez-le dans l'administration
s'il ne doit pas exister.

Sur PostgreSQL, les tables touchées sont fermées aux écritures le temps de la
remise (quelques secondes) : un geste fait au même moment attend, puis passe
sur l'outil remis à zéro — il ne peut pas être effacé sans être dans la
sauvegarde. Si un geste en cours tient la base plus de quinze secondes, ou si
la sauvegarde ne peut pas s'écrire, la remise est annulée avant tout
effacement, et la page le dit : réessayez. Le mieux reste de repartir de zéro
quand personne ne travaille.

Pour un retour complet en arrière à une date donnée, la vraie sauvegarde reste
celle de la base entière (voir « Sauvegarde » plus bas) : faites-en une avant de
repartir de zéro.

## Mise en serveur et base PostgreSQL

Procédure complète : **[`docs/guide-deploiement.md`](guide-deploiement.md)** —
préparation de la machine, création de la base, reprise des données, service qui
démarre tout seul, sauvegarde, supervision.

En résumé, rien à modifier dans le code : tout se règle dans `.env`.

```
DJANGO_DB_ENGINE=django.db.backends.postgresql
DJANGO_DB_NAME=wms
DJANGO_DB_USER=wms
DJANGO_DB_PASSWORD=…
DJANGO_DB_HOST=127.0.0.1
DJANGO_DB_PORT=5432
```

Installer le pilote (`pip install -r requirements.txt`), puis :

```bash
# 1. encore sur SQLite
python manage.py reprise_sql exporter --vers reprise
# 2. basculer .env sur PostgreSQL
python manage.py migrate
python manage.py reprise_sql importer --depuis reprise
```

`reprise_sql` compte les lignes de chaque table à l'export et les recompte après
chargement : au moindre écart, **rien n'est écrit**. Le risque d'une reprise n'est
pas qu'elle échoue, c'est qu'elle réussisse à moitié — une base d'apparence
normale, amputée d'une table que personne ne remarque avant l'incident.

## Contrôle avant mise en service

```bash
python outils/preparer_serveur.py
```

Passe en revue ce qui fait rater une mise en production : clé secrète d'exemple,
`DEBUG` actif, base injoignable, schéma en retard, aucun compte administrateur,
bibliothèques du scanner absentes, journaux non inscriptibles. Sort en code 1 s'il
reste un point bloquant — et le script de démarrage refuse alors de lancer le
service.

## Regarder la base directement

Pour voir la base telle qu'elle est, écrire ses propres requêtes ou sortir des
listes vers Excel : **[`docs/guide-sql.md`](guide-sql.md)** — quel outil selon
la base (DB Browser for SQLite aujourd'hui, pgAdmin après la bascule), et
**`docs/requetes-sql.sql`**, des requêtes déjà écrites sur le schéma du WMS.

## Supervision

`GET /api/sante/` répond **200** si la base répond et si le schéma est à jour,
**503** sinon. Sans authentification (un outil de supervision n'a pas de compte)
et sans rien divulguer (ni version, ni chemin, ni hôte de base).

## Sauvegarde

- **SQLite** : la base est le fichier `db.sqlite3`. Sauvegarde = copie de ce fichier,
  serveur arrêté, ou `sqlite3 db.sqlite3 ".backup sauvegarde.sqlite3"` à chaud.
  Conserver plusieurs jours d'historique.
- **Serveur SQL** : sauvegarde côté serveur (`pg_dump`, `mysqldump`), planifiée.

## Journaux

Les erreurs sont écrites dans `logs/wms.log` (rotation automatique, 5 fichiers de 2 Mo).
C'est le premier endroit à regarder quand un opérateur signale un problème de la veille.

