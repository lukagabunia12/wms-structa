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

- Rôles : administrateur, opérateur, lecture seule.
- 3 droits fins ajustables par compte : **cabines** (ranger, changer un statut, envoyer,
  corriger ou supprimer une cabine), **référentiel** (créer, modifier, supprimer des
  emplacements et des racks, régler ce qu'ils rangent et les codes MP qu'ils acceptent,
  régler les seuils d'alerte des codes MP, régler la taille des modèles) et **matières
  premières** (entrer, sortir et changer d'emplacement des vitrages et des cartons).
  L'administrateur a tous les droits. À la mise à jour qui l'a créée, la case « matières premières » a été
  cochée sur tous les comptes qui avaient « cabines » : décochez-la là où elle n'a pas
  lieu d'être.
- Deux opérations sont réservées au **rôle administrateur**, au-delà des droits fins :
  importer le fichier de production, et vider le stock des cabines (« Repartir de
  zéro », dans l'administration, derrière trois phrases à recopier et avec une
  sauvegarde écrite avant tout effacement).
- Un emplacement ne se supprime pas tant qu'une cabine y est rangée ou que du stock MP y
  est posé : il faut d'abord le libérer. Chaque suppression est notée dans
  `logs/wms.log`, avec son auteur et son motif — comme chaque changement de ce que
  rangent les emplacements (cabines, cartons, vitrages), de leurs codes acceptés, et
  des seuils d'alerte.
- La base des codes MP (vitrages, cartons) se complète dans l'administration, **Codes
  MP** : code élément, famille, désignation, fournisseur, n° article, autres références
  (séparées par « · », toutes cherchables), colisage, **seuil d'alerte**, ancienne
  génération. La liste permet de modifier directement le seuil d'alerte, « ancienne
  génération » et « actif », ligne par ligne ; l'application, elle, règle le même seuil
  pour une sélection de codes (Stock → MP → « Régler les seuils d'alerte »). Un code
  réservé sur des emplacements ne change pas de famille et ne se décoche pas « actif »
  tant qu'il y est réservé : l'administration nomme les emplacements à régler d'abord.
- Dans **Emplacements**, la fiche d'un emplacement MP porte ses **codes acceptés**
  (vide : toute sa famille). L'administration y applique la règle de l'application :
  pas de code d'une autre famille, aucun code sur un emplacement de cabines. Le
  réglage courant se fait plutôt dans l'application, à l'unité ou en nombre.
- Le **stock MP** et le **journal MP** y sont consultables, jamais modifiables : un
  écart se corrige par une entrée ou une sortie dans l'application, motif
  « Inventaire ». Le journal montre aussi les changements d'emplacement, avec la
  position de départ (« depuis »).
- « Repartir de zéro » ne vide que les cabines : le stock MP et son journal restent.
- Les zones se règlent dans l'administration ; une zone à laquelle des emplacements sont
  rattachés ne se supprime pas.
- Gestion via l'administration : `/admin/`.

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

