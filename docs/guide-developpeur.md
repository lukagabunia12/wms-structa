# Guide développeur — WMS Structa

Ce guide sert aussi de contexte à l'assistant IA.

## Architecture
- **Django 5.2** expose une **API REST** (DRF) sous `/api/`. L'interface opérateur est un
  fichier JavaScript natif, `wms/static/app/app.js`, servi par Django — sans outil de build.
- Base **PostgreSQL** en exploitation ; **SQLite** (`db.sqlite3`, chemin `DJANGO_DB_PATH`)
  sur un poste de développement.
- Utilisateur personnalisé `wms.Utilisateur` : un rôle (administrateur, opérateur, lecture
  seule) et douze droits, une case par geste (`Utilisateur.GROUPES_DROITS`).

## Où vit la logique

| Module | Rôle |
|---|---|
| `wms/services_cabines.py` | Toute écriture sur une cabine : créer, ranger, déplacer, changer de statut, envoyer, reprendre, corriger, supprimer. Chaque geste écrit sa ligne de `MouvementCabine` dans la même transaction. Aussi : mise en service des emplacements, places condamnées. |
| `wms/services_remise.py` | « Repartir de zéro » : six parties (cabines, MP, fichier de production, plan, modèles, codes MP), ce que chacune touche, ce qu'elle emporte (`EXIGE`), la sauvegarde rechargeable écrite avant le premier effacement, et la remise des réglages d'origine — lus dans les migrations qui les sèment (0020, 0026). |
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
11. **« Repartir de zéro » sauvegarde avant d'effacer, dans la même transaction**, et
    remet les réglages d'origine SUR leurs lignes (codes MP par code, modèles par clé)
    au lieu de les recréer : la sauvegarde se recharge alors sans buter sur un code en
    double. Les comptes ne partent jamais.

## Contrat d'erreur de l'API
Une saisie invalide produit un **400 avec `{"erreur": [...]}`**, jamais un 500. Les filtres
d'identifiant passent par `_filtre_id`.

## Droits
Une case par geste, sur `Utilisateur` (`droit_<clé>`) ; la liste et l'ordre de la fiche
font foi dans `Utilisateur.GROUPES_DROITS`. `droits_effectifs()` accorde tout à
`role == admin` **et à `is_superuser`** — `createsuperuser` laisse `role = operateur` —, rien
à `role == lecture`, et les cases cochées à un opérateur. `peut(clé)` : un nom inconnu vaut
« non ».

`wms/permissions.py` (`DroitWMS`, câblé en `DEFAULT_PERMISSION_CLASSES`) : lecture ouverte à
tout compte authentifié, écriture soumise au droit déclaré par la vue (`droit_ecriture` ou
`droits_par_action`). Les deux se combinent : `droits_par_action` nomme les exceptions,
`droit_ecriture` couvre tout le reste, et c'est la case la plus fermée de la vue —
`empl_creer` pour les emplacements, `cab_corriger` pour les cabines. Une action ajoutée sans
y penser tombe ainsi sous elle au lieu de s'ouvrir à tous ; une vue qui ne déclare rien
(`NON_DECLARE`) n'écrit que pour les administrateurs ; une action qui n'écrit rien mais
passe par un POST (`lire_fiche`) s'ouvre en nommant `None`. Le refus (403) nomme la case qui
manque. Seule exception à « une vue, un droit » : `hors_fichier`, vérifiée par
`services_cabines` à la création d'une cabine que le fichier n'annonce pas.

`/api/moi/` rend `droits` et `libelles_droits` : l'écran (`peut`, `sansLeDroit`) cache ce que
le compte ne peut pas faire, et nomme la case quand il éteint un geste.
`wms/tests/test_droits_a_cocher.py` vérifie chaque geste dans les deux sens — la case
seule suffit, toutes les autres ne suffisent pas —, que toute écriture exposée par le
routeur (actions standard et `@action` autres que GET) figure au tableau `GESTES` avec sa
case, ou dans `SANS_CASE` avec sa raison, et qu'aucune case ne reste sans geste. **Un
geste ajouté à l'API entre dans `GESTES`**, sinon ce test échoue.
`wms/tests/test_migration_droits.py` rejoue la migration 0028 (aller et retour).

L'administration de Django suit ses propres permissions, sauf `EmplacementAdmin`, qui
exige en plus les cases (`empl_creer`, `empl_regler`) et ne supprime rien : la suppression
d'emplacements vit dans l'application, par `services_emplacements`. Les actions de `UtilisateurAdmin`
— une par groupe (« Mettre dans le groupe … », créées par `get_actions`), « Retirer de leur
groupe », « Lecture seule » — exigent la permission de modifier : sans elle, Django les
proposait à qui pouvait seulement consulter la liste.

**Groupes.** `Groupe` (migration 0030) porte les mêmes cases que `Utilisateur` : les deux
héritent de `CasesDroits`, une seule définition. Un compte a un groupe au plus
(`Utilisateur.groupe`, PROTECT) ; `droits_effectifs()` = rôle d'abord, puis cases du groupe
OU cases du compte (ses « droits en plus »). Les groupes de Django sont retirés de
l'administration (`admin.site.unregister`).

**Familles MP.** `FamilleMP` (migration 0031) remplace les choix figés vitrage/carton.
`ArticleMP.famille` et `MouvementMP.famille` portent le CODE de la famille (texte, validé
par `ArticleMP.clean`). Un emplacement MP (`usage = "mp"`) a `familles` (vide : toutes) et
`codes_acceptes` (vide : tous ceux de ces familles) : un code entre si sa famille est
acceptée ET, s'il y a des codes, s'il en fait partie (`services_mp.accepte`). Un code de
famille passé comme usage (« vitrage ») vaut « MP, cette famille seulement » — modèle,
API et génération de rack le traduisent. L'écran lit les familles par `GET /api/mp/familles/`
au démarrage (`chargerFamillesMP`) ; `FAMILLES_MP` dans `app.js` n'est qu'une réserve.

Seul « Repartir de zéro » reste au-delà des cases : rôle administrateur
(`est_administrateur`), dans l'administration.

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

## Exploitation du serveur

- **`wms/exploitation.py`** : réglages (`WMS_SAUVEGARDE_*`, `WMS_JOURNAUX_JOURS`,
  `WMS_POSTGRESQL_*`), rotation des jeux (`jeux_a_supprimer` : tout pendant N jours,
  le premier de chaque mois pendant N mois, jamais moins de N jeux), recherche de
  `pg_dump`/`pg_restore`/`psql` hors du PATH, état lu par l'accueil de
  l'administration (`etat_sauvegarde`, gabarit `admin/wms/index.html` via
  `templatetags/exploitation_admin.py`, qui ne lève jamais).
- **`manage.py sauvegarder`** : `pg_dump --format=custom` (mot de passe par
  `PGPASSWORD`, jamais en argument), relu par `pg_restore --list` — chaque table de
  `connection.introspection` doit y figurer —, écrit en `.partiel` puis renommé ;
  zip de configuration ; copie vérifiée par empreinte ; état dans
  `logs/sauvegarde-etat.json`, journal Windows (900/901).
- **`manage.py restaurer`** : refuse si le WMS tourne ou si la tâche Service est
  active ; filet (`sauvegarder` d'abord) ; PostgreSQL : `pg_restore --file -` envoyé
  à `psql` entre un `BEGIN` et un `COMMIT` écrit **seulement** si `pg_restore` a fini
  sans erreur — un flux interrompu n'est jamais validé (`pg_restore
  --single-transaction` : pas de COMMIT intermédiaire, même avec des « large
  objects »). Le schéma `public` est refait : une table ajoutée depuis la
  sauvegarde ne survit pas pour faire échouer le `migrate` suivant. Échec ou
  réussite : `logs/sauvegarde.log`, `wms.log`, événements 910/911.
- **`manage.py nettoyer`** : journaux de PostgreSQL (`data/log`, jamais le plus
  récent), sessions expirées, `.partiel` abandonnés, mesures.
- **`outils/serveur_wms.py`** : le XML des tâches planifiées (UTF-16, pas de limite
  de durée, pas d'arrêt sur batterie, priorité normale), `etat`, `arreter`
  (désactive la tâche avant de tuer les seuls processus Python à l'écoute),
  `demarrer`. Les réglages des tâches (heures, ménage, compte dédié) sont gardés
  dans `.env` (`WMS_TACHE_*`) : une option absente reprend la valeur précédente.
- **Connexion** : `wms/connexion.py`, le frein aux mots de passe (compteurs en
  cache par compte et par adresse ; jamais par adresse pour la boucle locale),
  branché sur le backend, le signal `user_login_failed`, `/api/token/` (429 +
  `Retry-After`) et le formulaire de l'administration.
- **Corps des requêtes** : `wms/parseurs.py` refuse un JSON qui n'est pas un objet
  (400 au lieu d'un 500 sur `[]` ou `"texte"`). Les listes paginées trient par la
  colonne demandée **puis par `pk`** (`TriStable`) : sans cela, deux lignes égales
  changeaient de page d'une requête à l'autre.

Tests : `test_exploitation`, `test_restauration`, `test_serveur_windows`,
`test_frein_connexion`. Les classes `…Reelle…` tournent contre un vrai PostgreSQL si
`WMS_TEST_PG_PORT` et `WMS_TEST_PG_MOT_DE_PASSE` sont posés (voir leur docstring) ;
sinon elles sont sautées.

## Historique
Le volet « articles » de la maquette d'origine (articles, stock, mouvements, réceptions) a été
retiré en septembre 2026 : aucun écran ne s'en servait plus. La migration `0023` en a
sauvegardé le contenu, s'il y en avait, dans `sauvegardes/articles-retires_<date>.json`,
avant que la `0024` ne supprime les tables.
