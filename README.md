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

## Importer les données de la maquette
```bash
python manage.py importer_maquette /chemin/vers/wms.json --purge
```

## Tests et style
```bash
python manage.py test          # 469 tests
ruff check .                   # style et erreurs de code (pip install ruff)
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
│   ├── models.py      Les 8 tables du modèle
│   ├── services.py    Moteur de mouvements (cœur métier)
│   ├── serializers.py / views.py / urls.py   API REST
│   ├── management/commands/importer_maquette.py
│   └── tests/         Tests (dont logique métier des mouvements)
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
8 tables : `categorie`, `emplacement`, `article`, `utilisateur`, `stock`, `mouvement`,
`reception`, `cabine` (+ `etatcabine`). Détail et invariants : `docs/guide-developpeur.md`
et `docs/inventaire-maquette-wms.md`.

## Périmètre
v1 = WMS (articles, emplacements, stock, mouvements, réceptions, cabines).
Appro / MRP = module ultérieur (l'article prévoit déjà des champs réservés).

## Interface opérateur
Une fois le serveur démarré (`runserver`), l'interface est à **http://127.0.0.1:8000/**
(connexion avec le compte créé via `createsuperuser`). L'administration technique reste sur `/admin/`.
L'interface est servie par le même serveur — aucun outil de build à installer.
Fichiers : `wms/templates/app.html` et `wms/static/app/` (app.js, app.css, manifest, icônes).

## Lanceur automatique (Windows)
Double-clique sur **`Demarrer-WMS.bat`** : au premier lancement il installe tout (environnement + dependances), prepare `.env` (cle secrete generee, mode production), applique les migrations, telecharge les bibliotheques du scanner, puis demarre le serveur et ouvre l'application dans le navigateur. Les fois suivantes, il demarre directement.
Astuce : clic droit sur le fichier > Envoyer vers > Bureau (creer un raccourci) pour l'avoir a portee de main. Pour arreter, ferme la fenetre "serveur".

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
