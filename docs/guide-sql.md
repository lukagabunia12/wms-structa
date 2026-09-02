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

## Dans pgAdmin — voir les mouvements des cabines

### Avant tout : l'écran de l'application

Le WMS a déjà cet écran : **onglet « Plus » → « Journal »**. Il montre tous les
événements, du plus récent au plus ancien, avec un filtre par numéro de cabine,
par chantier ou par auteur, et une liste déroulante par type d'événement. Pour
« qu'est-ce qui s'est passé sur cette cabine ? », c'est plus rapide que pgAdmin,
et ça marche depuis le téléphone.

pgAdmin sert à ce que l'écran ne sait pas faire : **compter**, **croiser**,
**exporter vers Excel**.

### 1. Choisir la bonne base

Dans **Object Explorer**, à gauche : `Servers` → `PostgreSQL 18` → `Databases`.
Trois bases y répondent :

| Base | Ce qu'elle contient |
|---|---|
| `wms` | **La base du WMS.** C'est celle que `.env` désigne (`DJANGO_DB_NAME=wms`). |
| `wms_essai` | Une base d'essai. Elle répond aux mêmes requêtes, avec d'autres chiffres. |
| `postgres` | La base technique de PostgreSQL. Rien du WMS dedans. |

**Cliquer sur `wms`** pour la sélectionner : tout ce qui suit s'exécute sur la
base sélectionnée, et deux bases qui répondent toutes les deux est la meilleure
façon de se tromper sans le voir. En cas de doute, lancer la requête 1.1 de
`docs/requetes-sql.sql` : elle compte les lignes de chaque table. La bonne base
est celle où le nombre de cabines correspond à ce que vous voyez dans le WMS.

### 2. Ouvrir la fenêtre des requêtes

Base `wms` sélectionnée → menu **Tools → Query Tool** (ou l'icône en forme
d'éclair dans la barre de gauche). Un onglet s'ouvre avec une zone de saisie en
haut et la grille des résultats en bas.

### 3. Coller une requête et l'exécuter

Coller le texte de la requête, puis **F5** (ou le bouton ▶). Le résultat
s'affiche en dessous. Rien ne s'exécute tant que vous n'appuyez pas.

Pour n'exécuter qu'une requête d'un fichier qui en contient plusieurs :
**sélectionner ses lignes à la souris**, puis F5. C'est ce qui permet d'ouvrir
`docs/requetes-sql.sql` en entier et de ne lancer que ce qu'on veut.

### 4. Les requêtes prêtes à l'emploi

Dans `docs/requetes-sql.sql`, section **3 bis** :

| N° | Ce qu'elle répond |
|---|---|
| **3.5** | Les 100 derniers mouvements, en français. **Celle à lancer en premier.** |
| **3.6** | Ce qui s'est passé aujourd'hui, dans l'ordre des heures. |
| **3.7** | Combien de mouvements par type sur sept jours. |
| **3.8** | Qui a fait quoi sur sept jours, et combien de cabines chacun a touchées. |
| **3.9** | Le journal complet d'une cabine, du premier au dernier événement. |
| **3.10** | Les cabines dont le journal parle et qui n'existent plus. |

La 3.5 en entier, pour l'avoir sous la main :

```sql
SELECT to_char(m.date, 'DD/MM/YYYY HH24:MI')        AS "Quand",
       m.cabine_numero                              AS "Cabine",
       CASE m.type
         WHEN 'creation'    THEN 'Création'
         WHEN 'rangement'   THEN 'Rangement'
         WHEN 'transfert'   THEN 'Transfert'
         WHEN 'retrait'     THEN 'Sortie d''emplacement'
         WHEN 'statut'      THEN 'Changement de statut'
         WHEN 'envoi'       THEN 'Envoi'
         WHEN 'correction'  THEN 'Correction de fiche'
         WHEN 'suppression' THEN 'Suppression de la cabine'
         ELSE m.type END                            AS "Événement",
       NULLIF(m.depuis, '')                         AS "Depuis",
       NULLIF(m.vers, '')                           AS "Vers",
       CASE m.statut_apres
         WHEN 'libre'       THEN 'Conforme'
         WHEN 'quarantaine' THEN 'En quarantaine'
         WHEN 'envoye'      THEN 'Envoyée' END      AS "Nouveau statut",
       COALESCE(NULLIF(m.utilisateur_nom, ''), 'compte supprimé') AS "Par qui",
       NULLIF(m.chantier, '')                       AS "Chantier",
       NULLIF(m.note, '')                           AS "Note"
FROM wms_mouvementcabine m
ORDER BY m.date DESC
LIMIT 100;
```

### 5. Lire le résultat

Une ligne = un geste fait dans l'application. Les colonnes ne sont pas toutes
remplies à chaque fois, et **ce n'est pas un trou** : un rangement n'a pas de
statut, un changement de statut n'a pas d'emplacement.

| Colonne | Ce qu'elle dit |
|---|---|
| `type` | Le geste. `rangement`, `transfert`, `envoi`, `statut`, `correction`, `creation`, `retrait`, `suppression`. |
| `depuis` / `vers` | Les positions, sous la forme `AC5601·G`. Un rangement n'a qu'un `vers` ; un transfert a les deux. |
| `statut_avant` / `statut_apres` | Remplis seulement sur un changement de statut ou un envoi. `libre` s'affiche « Conforme » dans le WMS. |
| `cabine_numero` | Le numéro écrit **en dur** dans la ligne. Il survit à la suppression de la cabine — c'est ce qui permet la requête 3.10. |
| `utilisateur_nom` | Le nom au moment du geste, figé lui aussi. Vide veut dire que le compte a été supprimé depuis. |
| `note` | Le motif d'une quarantaine, la raison d'une correction. Facultatif, donc souvent vide. |

### 6. Regarder sans écrire de SQL

`wms` → `Schemas` → `public` → `Tables` → **`wms_mouvementcabine`** → clic droit
→ **View/Edit Data → Last 100 Rows**. La grille s'ouvre ; un clic sur un en-tête
de colonne trie, l'icône en forme d'entonnoir filtre.

C'est pratique pour jeter un œil. Les dates y sont brutes et les types en
anglais interne : pour quelque chose de lisible, la requête 3.5 vaut mieux.

### 7. Sortir vers Excel

Au-dessus de la grille de résultats, le bouton **Download** (flèche vers le bas)
enregistre un CSV. **Ne pas double-cliquer le fichier** : dans Excel, passer par
**Données → À partir d'un fichier texte/CSV**, encodage **UTF-8**, sinon les
accents sont cassés.

### 8. Ce journal ne se modifie pas

`wms_mouvementcabine` est la vérité du WMS : les positions, les listes et les
compteurs sont recalculés depuis lui. Une ligne effacée ou retouchée à la main,
et l'application affichera pour toujours autre chose que ce que vous croyez
avoir corrigé. L'application elle-même s'interdit d'y toucher.

Pour rattraper une erreur, il y a un geste dans le WMS : corriger la fiche,
changer le statut, remettre en stock. Chacun **ajoute** une ligne au journal —
rien ne s'efface, et on sait qui a corrigé quoi.
