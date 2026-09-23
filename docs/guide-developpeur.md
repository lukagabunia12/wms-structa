# Guide développeur — WMS Structa

Ce guide sert aussi de contexte à l'assistant IA.

## Architecture
- **Django 5.2** expose une **API REST** (DRF) sous `/api/`. L'interface opérateur est un
  fichier JavaScript natif, `wms/static/app/app.js`, servi par Django — sans outil de build.
- Base **PostgreSQL** en exploitation ; **SQLite** (`db.sqlite3`, chemin `DJANGO_DB_PATH`)
  sur un poste de développement.
- Utilisateur personnalisé `wms.Utilisateur` : un rôle (administrateur, opérateur, lecture
  seule) et deux droits fins, **cabines** et **référentiel**.

## Où vit la logique

| Module | Rôle |
|---|---|
| `wms/services_cabines.py` | Toute écriture sur une cabine : créer, ranger, déplacer, changer de statut, envoyer, reprendre, corriger, supprimer. Chaque geste écrit sa ligne de `MouvementCabine` dans la même transaction. Aussi : mise en service des emplacements, places condamnées, remise à zéro avec sauvegarde. |
| `wms/services_emplacements.py` | Le référentiel : créer un rack, supprimer un emplacement, une sélection ou un rack — tout ou rien, et refusé tant qu'une cabine y est rangée. |
| `wms/services_import.py` | Import du fichier de production (`CabineAttendue`), tout ou rien. |
| `wms/lecture_fiche.py`, `wms/ocr_fiche.py` | Lecture du n° de cabine sur la photo de la fiche papier. |
| `wms/export_inventaire.py` | Inventaire des cabines en CSV lisible par Excel. |

Les vues (`wms/views.py`) ne portent pas de règle métier : elles traduisent les refus des
services (`ValidationError`) en réponses 400.

## Invariants à ne jamais casser
1. **Une cabine ne s'écrit jamais en direct** : toujours par `services_cabines`, qui journalise.
2. **Où est une cabine**, c'est `Occupation` — une ligne par emplacement occupé. « Rangée » se
   déduit, ne se stocke pas.
3. Une place (emplacement × gauche/droite) ne porte qu'une cabine : contrainte en base
   `place_occupee_par_une_seule_cabine`.
4. Le journal (`MouvementCabine`) recopie en texte le numéro, le chantier, les positions et
   l'auteur : il reste lisible quand la cabine, l'emplacement ou le compte ont disparu.
5. Le `code` d'un emplacement est normalisé en **MAJUSCULES** et unique.

## Contrat d'erreur de l'API
Une saisie invalide produit un **400 avec `{"erreur": [...]}`**, jamais un 500. Les filtres
d'identifiant passent par `_filtre_id`.

## Droits
`wms/permissions.py` (`DroitWMS`, câblé en `DEFAULT_PERMISSION_CLASSES`) : lecture ouverte à
tout compte authentifié, écriture soumise au droit déclaré par la vue (`droit_ecriture` ou
`droits_par_action`). `droits_effectifs()` accorde tout à `role == admin` **et à
`is_superuser`** — `createsuperuser` laisse `role = operateur`. `EstAdministrateur` réserve
l'import du fichier de production aux administrateurs.

## Migrations
`wms/migrations/` est committé. La CI lance `makemigrations --check --dry-run` : elle
**échoue si une migration manque** au lieu d'en générer une à la volée. Après toute
modification de `models.py`, lancer `python manage.py makemigrations wms` et committer le
résultat.

## Tests
`python manage.py test` (un seul fichier : `python manage.py test wms.tests.test_cabines`),
puis `node outils/verifier_interface.js` et `node outils/tester_interface.js` pour
l'interface.

**Un test doit pouvoir échouer.** Deux pièges rencontrés : comparer un état avant/après sans
l'avoir falsifié d'abord (le test passe même si la fonction ne fait rien), et une fixture dont
les données coïncident par hasard avec le résultat attendu.

**Consigne permanente : toute évolution rejoue les tests existants et en ajoute de nouveaux.**

## Historique
Le volet « articles » de la maquette d'origine (articles, stock, mouvements, réceptions) a été
retiré en septembre 2026 : aucun écran ne s'en servait plus. La migration `0023` en a
sauvegardé le contenu, s'il y en avait, dans `sauvegardes/articles-retires_<date>.json`,
avant que la `0024` ne supprime les tables.
