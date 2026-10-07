# WMS Structa — socle back-end

Application de gestion d'entrepôt (WMS) de STRUCTA. Réécriture propre, en remplacement
de la maquette Node.js + fichiers JSON. Ce dossier est **autonome** : il peut être copié
et versionné où vous le souhaitez.

## Stack
- **Python / Django 5.2 LTS** + **Django REST Framework** (API)
- Base **PostgreSQL** (base d'exploitation depuis août 2026 ; SQLite reste le mode
  d'un poste de développement isolé — deux caristes qui rangent en même temps
  suffisent à mettre SQLite en défaut)
- HTTPS sur le réseau interne, terminé par `outils/proxy_https.py` — sans lui, les
  navigateurs mobiles refusent l'accès à la caméra et le scan est indisponible
- Front **JavaScript natif** servi par Django (`wms/static/app/app.js`), PWA — **aucun outil de
  build, pas de `npm`**. Voir « Interface opérateur » plus bas.

## Démarrage rapide

**Poste serveur, installation neuve** — un seul geste, tout est enchaîné :

```
Installer-WMS.bat
```

Prérequis à installer d'abord sur ce poste : Python (même version que le poste
d'origine) et PostgreSQL. Détail : **`docs/guide-serveur.md`**.

**Poste de développement**, à la main :

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate   |   Linux/Mac : source .venv/bin/activate
pip install -r requirements.txt
python outils/preparer_env.py     # crée .env, génère la clé secrète, met DEBUG=False
python manage.py migrate          # pas de makemigrations : elles sont committées
python manage.py createsuperuser
python manage.py telecharger_libs # une fois, avec internet : scan et QR sans réseau
python manage.py runserver        # développement
```
> `DJANGO_DEBUG` vaut **False** par défaut : en DEBUG, la page d'erreur expose la clé
> secrète et le mot de passe de la base à n'importe quel visiteur. Sur un poste de
> développement, poser `DJANGO_DEBUG=True` dans `.env`.
> Réglages complets et bascule vers PostgreSQL : `.env.example` et `docs/guide-administrateur.md`.
- Administration : http://127.0.0.1:8000/admin/
- API : http://127.0.0.1:8000/api/

## Tests et style
```bash
python manage.py test           # 736 tests côté serveur
ruff check .                    # style et erreurs de code (pip install ruff)
node outils/verifier_interface.js   # les écrans de l'interface existent et sont joignables
node outils/tester_interface.js     # le comportement de l'interface, sans navigateur
```
Règle permanente du projet : **toute évolution rejoue les tests et en ajoute de nouveaux.**

Le style est décidé une fois dans `pyproject.toml` — 119 caractères, la limite que
Django applique à son propre code — et vérifié par `ruff`, pour qu'une revue parle
du fond et pas des espaces.

La CI (`.github/workflows/ci.yml`) rejoue à chaque modification : ruff, `manage.py
check`, migrations manquantes, contrôle de déploiement (dont le profil durci
derrière le proxy TLS), syntaxe et écrans de l'interface, puis les tests.

## Structure
```
wms-structa/
├── config/            Configuration Django (settings, urls)
├── wms/               Application métier
│   ├── models.py      Cabines, emplacements, journal, fichier de production
│   ├── services_cabines.py       Toute écriture sur une cabine (cœur métier)
│   ├── services_emplacements.py  Racks, suppression d'emplacements
│   ├── services_mp.py            Matières premières : vitrages et cartons
│   ├── services_import.py        Import du fichier de production
│   ├── serializers.py / views.py / urls.py   API REST
│   ├── export_inventaire.py  Inventaire des cabines en CSV lisible par Excel
│   ├── management/commands/  reprise_sql (bascule de base), telecharger_libs
│   └── tests/         Tests
├── docs/              Guides utilisateur / admin / développeur / serveur
├── deploiement/       PostgreSQL, installation et sauvegarde Windows
├── outils/            installation, certificats HTTPS, proxy TLS, diagnostics
├── paquets/           dépendances hors ligne (créé par Preparer-Paquets.bat)
├── certificats/       autorité et certificat du poste (jamais copiés ailleurs)
├── .github/workflows/ CI
├── requirements.txt   base + PostgreSQL + HTTPS (requirements-ocr.txt à part)
└── manage.py
```

## Modèle de données
`cabine`, `occupation` (où se trouve chaque cabine), `mouvementcabine` (le journal),
`emplacement`, `placecondamnee`, `zone`, `modelecabine`, `cabineattendue` (le fichier de
production), `articlemp`, `stockmp` et `mouvementmp` (les matières premières : la base des
codes et leurs seuils d'alerte, le stock place par place, le journal — entrées, sorties,
changements d'emplacement), les codes acceptés par emplacement, et `utilisateur`. Détail et invariants :
`docs/guide-developpeur.md`.

## Périmètre
Le suivi des cabines de douche : entrée, rangement, statut, envoi, et le référentiel des
emplacements. Depuis octobre 2026, les **matières premières** — vitrages et cartons — :
emplacements dédiés à trois places (gauche, milieu, droite), réservables à certains codes,
entrées, sorties, changements d'emplacement en un geste, stock par code, seuils d'alerte et
cloche des alertes, base des codes prête à l'emploi. Les droits se donnent case par case, un
geste par case, et « Repartir de zéro » remet l'outil à neuf (tout, ou ce qu'on coche). Le
volet « articles » de la maquette (stock d'articles générique) avait été retiré en septembre
2026 : aucun écran ne s'en servait.

## Interface opérateur
Une fois le serveur démarré (`runserver`), l'interface est à **http://127.0.0.1:8000/**
(connexion avec le compte créé via `createsuperuser`). L'administration technique reste sur `/admin/`.
L'interface est servie par le même serveur — aucun outil de build à installer.
Fichiers : `wms/templates/app.html` et `wms/static/app/` (app.js, app.css, manifest, icônes).

## Lanceur automatique (Windows)
Double-clique sur **`Demarrer-WMS.bat`**, le seul lanceur : au premier lancement il installe tout (environnement + dépendances), prépare `.env` (clé secrète générée, mode production), applique les migrations, télécharge les bibliothèques du scanner, puis démarre le serveur **en HTTPS** (`https://<adresse du PC>:8443`, la caméra des téléphones l'exige) et ouvre l'application dans le navigateur. Les fois suivantes, il démarre directement. La première fois, lance-le en administrateur (clic droit > Exécuter en tant qu'administrateur) : il ouvre le port 8443 et inscrit l'autorité dans Windows. Détail : `docs/guide-https.md`.
Astuce : clic droit sur le fichier > Envoyer vers > Bureau (créer un raccourci) pour l'avoir à portée de main. Pour arrêter, ferme sa fenêtre.

## Copier le WMS sur un autre poste

Le dossier ne se copie pas tel quel : `.venv` porte les chemins de ce poste-ci,
`.env` porte la clé secrète et le mot de passe de la base, `certificats/` est
émis pour les adresses IP d'ici. Deux scripts s'en chargent :

```
Preparer-Paquets.bat    # une fois, sur un poste qui a internet
Preparer-Copie.bat      # fabrique le dossier + le .zip à emporter
```

puis, sur le poste serveur, `Installer-WMS.bat`. Pas à pas, et liste de ce qu'il
faut y télécharger : **`docs/guide-serveur.md`**.

## Mise en serveur
Détail des choix et de l'exploitation : **`docs/guide-deploiement.md`**. Tout est
scripté dans `deploiement/` — création de la base, reprise des données avec
contrôle de comptages, service qui démarre sans session ouverte, sauvegarde planifiée, sonde de supervision.

Contrôle avant d'ouvrir le service aux postes :
```bash
python outils/preparer_serveur.py     # code 1 s'il reste un point bloquant
```
