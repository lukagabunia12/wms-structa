# Guide développeur — WMS Structa

Ce guide sert aussi de contexte à l'assistant IA.

## Architecture
- **Django** (back) expose une **API REST** (DRF). Le front (Quasar/Vue, à venir) la consomme.
- Base **SQLite**, un fichier `db.sqlite3` à la racine (chemin configurable via `DJANGO_DB_PATH`).
- Utilisateur personnalisé `wms.Utilisateur` (rôle + 7 droits fins).

## Le cœur : `wms/services.py`
Toute écriture de stock passe par ce module. Ne jamais modifier `Stock` directement.
- `entree / sortie / ajustement` → un `Mouvement` + mise à jour transactionnelle du cache `Stock`.
- `transfert` = `sortie` + `entree` (deux mouvements).
- `contre_passer` = mouvement inverse (interdit sur un ajustement ; ne supprime rien).
- `receptionner` = entrée + enregistrement `Reception` numéroté `R+AAMMJJ+séq`.
- `recalculer_stock()` reconstruit le cache en rejouant le journal.

## Invariants à ne jamais casser
1. **La vérité du stock est le journal des mouvements** ; `Stock` est un cache reconstructible.
2. Un `Ajustement` est une **valeur absolue** (remise à niveau), pas un delta.
3. Le **stock ne peut pas devenir négatif** (une sortie insuffisante est refusée).
4. Les FK historiques sont en **SET_NULL** : supprimer un article/emplacement conserve l'historique.
5. `ref` article et `code` emplacement sont normalisés en **MAJUSCULES** et uniques.

## Contrat d'erreur de l'API
Une saisie invalide doit produire un **400 avec `{"erreur": [...]}`**, jamais un 500. En pratique :
- Les quantités passent par `services._dec` : refus de ce qui n'est pas un nombre décimal simple
  (virgule, notation scientifique, texte, vide), de plus de 3 décimales, et de plus de 11 chiffres
  avant la virgule. `max_digits` n'étant imposé ni par SQLite ni par Django au `save()`, une valeur
  démesurée écrite en base rendait toute relecture ORM de la colonne impossible.
- Les clés étrangères du corps de la requête passent par `OperationsViewSet._objet`, les filtres
  d'identifiant par `_filtre_id`, les champs texte par `_texte` (les `CharField` ne sont pas bornés
  par SQLite).

## Droits
`wms/permissions.py` (`DroitWMS`, câblé en `DEFAULT_PERMISSION_CLASSES`) applique les droits fins :
lecture ouverte à tout compte authentifié, écriture soumise au droit déclaré par la vue
(`droit_ecriture` ou `droits_par_action`). `droits_effectifs()` accorde tout à `role == admin` **et à
`is_superuser`** — `createsuperuser` laisse `role = operateur`. Une vue en écriture qui ne déclare
aucun droit est ouverte à tout compte authentifié.

## Tests
`python manage.py test`. Les tests métier sont dans `wms/tests/test_mouvements.py`.
**Consigne permanente : toute évolution rejoue les tests existants et en ajoute.**

## Comportement de référence
La transposition doit rester fidèle à la maquette : voir `docs/inventaire-maquette-wms.md`.

## Migrations
`wms/migrations/` est committé (`0001_initial`, `0002_alter_stock_options`). La CI lance
`makemigrations --check --dry-run` : elle **échoue si une migration manque** au lieu d'en générer une à
la volée. Après toute modification de `models.py` — y compris une simple option `Meta` comme
`ordering` — lancer `python manage.py makemigrations wms` et committer le résultat.

## Suite de tests (131 tests)
Lancer : `python manage.py test` (ou un seul fichier : `python manage.py test wms.tests.test_api`).

| Fichier | Couvre |
|---|---|
| `test_mouvements.py` | Moteur métier : entrée/sortie/ajustement, stock jamais négatif, transfert = 2 mouvements, contre-passation (entrée **et** sortie, drapeaux, refus en chaîne), quantités invalides, format des numéros de réception, recalcul qui **répare** un cache falsifié |
| `test_modeles.py` | Normalisation `ref`/`code` en majuscules, unicité de l'EAN si présent |
| `test_api.py` | Authentification par jeton, **droits fins par rôle et par action**, recherche, filtres, tous les endpoints d'opérations, **quantités et identifiants invalides → 400**, unicité insensible à la casse, suppression sécurisée d'emplacement, rangement depuis la zone « à ranger », tableau de bord et alertes de seuil |
| `test_cabines.py` | Recherche par n° de cabine **et** par n° de chantier, validations de format (y compris en création directe), statut métier conservé, sortie irréversible et non annulable par PATCH, emplacement de sortie validé, traçabilité utilisateur |
| `test_import.py` | Commande `importer_maquette` : volumes, normalisation, zone de staging, liens, purge, fichier absent, **reprise de stock** (le journal explique le stock importé), cabines invalides réellement ignorées |
| `test_pages.py` | L'interface et l'administration répondent ; ressources versionnées (anti-cache) |

**Un test doit pouvoir échouer.** Deux pièges rencontrés dans cette suite : comparer un état avant/après
sans l'avoir falsifié d'abord (le test passe même si la fonction ne fait rien), et une fixture dont les
données coïncident par hasard avec le résultat attendu (celle de `test_import` contient donc
volontairement une ligne de stock sans mouvement correspondant).

**Consigne permanente : toute évolution rejoue les tests existants et en ajoute de nouveaux.**
