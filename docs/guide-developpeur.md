# Guide développeur — WMS Structa

Ce guide sert aussi de contexte à l'assistant IA.

## Architecture
- **Django 5.2** expose une **API REST** (DRF) sous `/api/`. L'interface opérateur est un
  fichier JavaScript natif, `wms/static/app/app.js`, servi par Django — sans outil de build.
- Base **PostgreSQL** en exploitation ; **SQLite** (`db.sqlite3`, chemin `DJANGO_DB_PATH`)
  sur un poste de développement.
- Utilisateur personnalisé `wms.Utilisateur` : un rôle (administrateur, opérateur, lecture
  seule) et trois droits fins, **cabines**, **référentiel** et **matières premières**.

## Où vit la logique

| Module | Rôle |
|---|---|
| `wms/services_cabines.py` | Toute écriture sur une cabine : créer, ranger, déplacer, changer de statut, envoyer, reprendre, corriger, supprimer. Chaque geste écrit sa ligne de `MouvementCabine` dans la même transaction. Aussi : mise en service des emplacements, places condamnées, remise à zéro avec sauvegarde. |
| `wms/services_emplacements.py` | Le référentiel : créer un rack, supprimer un emplacement, une sélection ou un rack — tout ou rien, et refusé tant qu'une cabine y est rangée. |
| `wms/services_import.py` | Import du fichier de production (`CabineAttendue`), tout ou rien. |
| `wms/services_mp.py` | Matières premières : entrer, sortir, changer d'emplacement (chaque geste écrit son `MouvementMP`), suggestions de codes, stock par code ; le réglage des emplacements — leur usage (cabines, cartons, vitrages) et leurs codes acceptés — et des seuils d'alerte ; les alertes de la cloche. |
| `wms/export_mp.py` | Stock MP en CSV lisible par Excel, une ligne par position. |
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
6. Un emplacement range des cabines **ou** une famille de MP (`Emplacement.usage`) : jamais
   de cabine sur un emplacement MP (`services_cabines.ranger` refuse, `emplacements_pour`
   le marque impossible), jamais de MP sur un emplacement de cabines.
7. **Le stock MP ne s'écrit que par `services_mp`**, qui journalise. Une ligne par
   (emplacement, place G/M/D, code), quantité strictement positive — contraintes en base.
   `StockMP` est en PROTECT vers l'emplacement et le code : on ne supprime rien qui porte
   du stock.
8. **Verrous MP, toujours dans le même ordre** : les emplacements d'abord — un seul pour
   entrer ou sortir, tous ceux d'un changement d'emplacement **dans l'ordre de leur
   code**, comme les gestes en nombre (`_emplacements`) —, puis les lignes de stock,
   verrouillées seules (`select_for_update(of=("self",))`). Deux gestes croisés
   s'attendent au lieu de s'interbloquer.
9. **Un changement d'emplacement est un geste, pas une sortie suivie d'une entrée** :
   une ligne `MouvementMP` de type `transfert` par ligne déplacée, `position`/`reste`
   pour l'arrivée, `origine`/`reste_origine` pour le départ. Les requêtes de
   consommation (`type = 'sortie'`) ne le voient donc pas. Tout ou rien : une seule
   ligne refusée, rien ne bouge.
10. **Les codes acceptés d'un emplacement ne s'écrivent que par
    `services_mp.regler_codes`**, qui vérifie la famille. Le champ est en lecture seule
    dans `EmplacementSerializer` (sinon `fields = "__all__"` l'aurait ouvert au PATCH),
    et l'administration passe par la même règle (`EmplacementForm`, `ArticleMPForm`).
    Un changement d'usage efface la réservation (`oublier_codes`).

## Contrat d'erreur de l'API
Une saisie invalide produit un **400 avec `{"erreur": [...]}`**, jamais un 500. Les filtres
d'identifiant passent par `_filtre_id`.

## Droits
`wms/permissions.py` (`DroitWMS`, câblé en `DEFAULT_PERMISSION_CLASSES`) : lecture ouverte à
tout compte authentifié, écriture soumise au droit déclaré par la vue (`droit_ecriture` ou
`droits_par_action`). Les deux se combinent : `droits_par_action` nomme les exceptions,
`droit_ecriture` couvre tout le reste — `MatieresPremieresViewSet` exige « mp » partout,
sauf `seuils` qui exige « ref ». Une action ajoutée sans y penser tombe ainsi sous le
droit de la vue au lieu de s'ouvrir à tous. `droits_effectifs()` accorde tout à `role == admin` **et à
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

## Matières premières

`ArticleMP` (la base des codes, semée par la migration `0026` — ajoutée à
`SEMEES_PAR_MIGRATION` de `reprise_sql`), `StockMP` (place par place), `MouvementMP` (le
journal, qui recopie code, position et auteur). La recherche compare des clés réduites aux
lettres et aux chiffres (`normaliser_code_mp`) : « vitr.8 » trouve VITR.831… ; le même
calcul existe côté écran (`cleMP`), testé par `outils/tester_interface.js`. API sous
`/api/mp/` (`emplacement`, `suggestions` — `?emplacement=` pour ne proposer que ses codes
acceptés —, `entrer`, `sortir`, `deplacer`, `seuils`, `stock`, `article`, `journal`,
`export`, `filtres`) ; réglages en nombre : `POST /api/emplacements/usage/` et
`POST /api/emplacements/codes/` (`apercu: true` d'abord, puis le même corps sans).

**La cloche.** `GET /api/alertes/` rend les alertes en groupes (`type`, `titre`,
`items`, chaque item avec une `cle` stable) : codes sous leur seuil d'alerte
(`seuil_reappro`, champ au nom d'origine), lignes posées là où leur code n'est plus
accepté. Le pouls n'en porte que le nombre et une **empreinte**
(`services_mp.empreinte_alertes`, deux requêtes) qui suit aussi le contenu — totaux,
seuils, quantités — : l'écran relit la liste quand elle change, et à l'ouverture de
la cloche. Les alertes vues sont retenues par poste dans `localStorage`
(`wms_alertes_vues`), et oubliées dès qu'elles disparaissent : une alerte qui revient
est nouvelle. Une autre sorte d'alerte s'ajoute en ajoutant un groupe.

## Historique
Le volet « articles » de la maquette d'origine (articles, stock, mouvements, réceptions) a été
retiré en septembre 2026 : aucun écran ne s'en servait plus. La migration `0023` en a
sauvegardé le contenu, s'il y en avait, dans `sauvegardes/articles-retires_<date>.json`,
avant que la `0024` ne supprime les tables.
