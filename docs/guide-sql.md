# Regarder et corriger la base directement

Le WMS a son propre écran d'administration (`/admin/`), qui suffit pour la plupart
des corrections. Ce guide est pour l'autre besoin : **voir la base telle qu'elle
est**, écrire ses propres requêtes, sortir des listes vers Excel.

## Quel outil, selon la base

| Base | Outil | Où le prendre |
|---|---|---|
| **SQLite** — aujourd'hui | **DB Browser for SQLite** 3.13.1 | <https://sqlitebrowser.org/dl/> → « Standard installer for 64-bit Windows » |
| **PostgreSQL** — après la bascule | **pgAdmin 4** | Déjà installé avec PostgreSQL. Menu Démarrer → « pgAdmin » |

> pgAdmin **ne parle que PostgreSQL**. Tant que le WMS tourne sur `db.sqlite3`,
> il n'a rien à vous montrer : c'est DB Browser qu'il faut.

Les deux outils s'utilisent pareil, et les requêtes fournies fonctionnent dans
les deux (les rares différences sont signalées en commentaire).

## Ouvrir la base

1. Installer DB Browser (installeur 64 bits).
2. **Arrêter le WMS** si vous comptez modifier quelque chose. Pour seulement
   regarder, ce n'est pas nécessaire.
3. Menu **Ouvrir une base de données** → aller dans le dossier du projet →
   `db.sqlite3`.
4. Onglet **Parcourir les données** pour voir les tables, onglet **Exécuter le
   SQL** pour écrire des requêtes.

Les tables du WMS commencent toutes par `wms_` : `wms_emplacement`,
`wms_article`, `wms_stock`, `wms_mouvement`, `wms_cabine`,
`wms_mouvementcabine`, `wms_zone`, `wms_utilisateur`.

## Les requêtes déjà écrites

**`docs/requetes-sql.sql`** — 17 requêtes prêtes à l'emploi, écrites sur votre
schéma réel et vérifiées. Ouvrir ce fichier dans l'onglet « Exécuter le SQL »,
sélectionner une requête, `F5`.

Elles couvrent trois usages :

- **Regarder** — combien de lignes par table, les comptes et leurs droits, les
  emplacements, la composition des racks.
- **Vérifier** — le stock actuel, les articles sous le minimum, les emplacements
  vides, les derniers mouvements, et **l'écart entre le stock affiché et le
  journal** (requête 2.2, voir plus bas).
- **Extraire** — inventaire valorisé, historique sur une période, cabines d'un
  chantier, ordre d'impression des étiquettes d'un rack.

### La requête qui compte : 2.2

Dans ce WMS, **la vérité du stock est le journal des mouvements**
(`wms_mouvement`) ; la table `wms_stock` n'est qu'un cache recalculable. La
requête 2.2 recalcule le stock depuis le journal et le compare au cache.

**Un résultat vide veut dire que tout est cohérent.** Une ligne veut dire que
quelqu'un a écrit une quantité sans passer par un mouvement — c'est exactement
ce qu'on veut détecter, et c'est invisible depuis l'interface du WMS.

## Sortir vers Excel

Exécuter la requête, puis clic droit sur le résultat → **Copier** (se colle
directement dans Excel), ou menu **Fichier → Exporter → Tables au format CSV**.
Dans pgAdmin, le bouton **Download as CSV** est au-dessus du résultat.

> **Accents cassés dans Excel ?** Ne pas double-cliquer le CSV. Dans Excel :
> **Données → À partir d'un fichier texte/CSV**, et choisir l'encodage
> **UTF-8**.

## Corriger à la main — les trois règles

**1. Arrêter le WMS avant d'écrire.** Une écriture pendant que l'application
tourne peut la bloquer, ou être écrasée par elle.

**2. Sauvegarder d'abord.** Copier `db.sqlite3` sous un autre nom. Un `UPDATE`
sans `WHERE` modifie toutes les lignes de la table, et rien ne l'annule.

**3. Dans DB Browser, rien n'est écrit tant que vous n'avez pas cliqué
« Write Changes ».** « Revert Changes » annule tout. C'est votre filet :
relisez le résultat avant d'écrire.

### Ce qui se corrige à la main sans risque

Des champs purement descriptifs, sur lesquels aucune règle logistique ne
s'appuie :

| Table | Champs |
|---|---|
| `wms_article` | `designation`, `fournisseur`, `prix`, `ean`, poids et dimensions |
| `wms_cabine` | `modele`, `client`, `revendeur`, `tissu_bk`, `tissu_aq`, `fond_cabine` |
| `wms_emplacement` | `description` |
| `wms_zone` | `nom`, `description`, `ordre` |

### Ce qu'il ne faut pas toucher

| Table | Pourquoi |
|---|---|
| `wms_stock` | Ce n'est qu'un **cache**. La modifier crée un écart que la requête 2.2 révélera et que plus personne ne saura expliquer. Pour corriger une quantité : **passer par le WMS** (inventaire ou ajustement), qui écrit un mouvement. |
| `wms_mouvement` | C'est le **journal du stock**. On n'efface pas une ligne d'historique — le WMS sait annuler un mouvement, ce qui laisse une trace. |
| `wms_mouvementcabine` | Journal des cabines, même règle. L'application elle-même s'interdit de le modifier. |
| `wms_utilisateur.password` | Mot de passe **chiffré**. Le remplacer par du texte rend le compte inutilisable. Passer par `/admin/`, ou `manage.py changepassword`. |

Après toute correction, relancer la requête 2.2 : si elle ne renvoie rien, la
base est restée cohérente.

## Et l'écran `/admin/` du WMS ?

Il reste le plus simple pour une correction ponctuelle : les 11 tables y sont
consultables et modifiables, avec recherche et filtres, **sans écrire de SQL**,
et il marche aussi bien sur SQLite que sur PostgreSQL. Il applique en plus les
règles du modèle — notamment l'interdiction de modifier le journal des cabines.

Adresse : `http://<adresse-du-serveur>:8000/admin/`
