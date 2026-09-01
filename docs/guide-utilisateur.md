# Guide utilisateur — WMS Structa

> L'interface opérateur est disponible à la racine du serveur (`http://127.0.0.1:8000/`).
> Ce guide décrit les opérations métier qu'elle propose.

Selon votre compte, certaines opérations peuvent être refusées : la consultation est ouverte à tous,
mais les écritures dépendent des droits accordés (mouvements, inventaire, cabines, référentiel).
Un compte « lecture seule » ne peut rien modifier.

## Opérations de stock
- **Réception** : enregistrer l'arrivée d'un article (crée une entrée + une réception numérotée).
  Option « à ranger » : l'article arrive en zone de réception avant rangement.
- **Rangement** : déplacer depuis la zone « à ranger » vers un emplacement définitif.
- **Entrée / Sortie** : ajouter ou retirer une quantité sur un emplacement.
  Une sortie supérieure au stock disponible est refusée.
- **Transfert** : déplacer une quantité d'un emplacement à un autre.
- **Inventaire** : saisir la quantité comptée ; l'écart génère un ajustement.
- **Correction** : annuler un mouvement (crée un mouvement inverse ; l'historique est conservé).

## Cabines
Suivi des cabines par numéro (`xx_xx_xx`) et chantier (6 chiffres), avec un statut métier
(ex. « Quarantaine ») et une sortie définitive.

## Recherche et traçabilité
Recherche d'articles, d'emplacements et de cabines ; historique complet des mouvements,
et reconstitution du stock à une date donnée.

## Emplacements — tout se passe au même endroit

Menu **Référentiel → Emplacements** (ou la tuile « Emplacements » de l'accueil).
C'est l'unique écran du référentiel : occupation, ajout, réglages et suppression.
Il remplace les anciens écrans « Emplacements » et « Gestion des emplacements »,
qui proposaient chacun des champs différents.

**Ajouter** — le bouton orange **« + Nouvel emplacement »** est en haut à droite du
titre, toujours visible. Une fenêtre s'ouvre : code, zone, mode de rangement,
description, et la case « zone de réception ». Le code est ce qui sera imprimé sur
l'étiquette QR collée sur la travée.

**Créer un rack entier** — bouton **« Créer un rack »**, à côté du précédent.
Voir la section « Créer un rack » plus bas.

**Modifier ou supprimer** — cliquer sur une ligne de la liste ouvre la fiche de
l'emplacement. On y trouve, dans l'ordre :

1. l'occupation (les trois places G/M/D, ou les cabines en capacité illimitée) et les
   boutons « Ranger ici » / « Sortir d'ici » ;
2. les **réglages** : code, zone, mode de rangement, description, zone de réception,
   emplacement actif ;
3. l'**impression de l'étiquette QR** et la **suppression**.

Un emplacement scanné donne accès à la même fiche : bouton « Régler / supprimer cet
emplacement ».

### Ce que le WMS refuse de supprimer, et pourquoi

| Situation | Ce qui se passe |
|---|---|
| Des cabines y sont rangées | Refus. Sortez-les ou transférez-les d'abord — sinon elles se retrouveraient « non rangées » sans aucune trace. |
| Il porte encore du stock | Refus pour un opérateur — le message dit quels articles bloquent et invite à s'adresser à un administrateur. **Un administrateur**, lui, peut le supprimer avec son stock : voir ci-dessous. |
| Il apparaît dans l'historique | Le WMS propose de le **désactiver** plutôt que de le supprimer. La suppression reste possible en confirmant une seconde fois, mais le journal affichera alors « ? » à la place du code. |
| Rien de tout cela | Suppression après une simple confirmation. |

**Désactiver** est souvent le bon geste pour une travée démontée : l'emplacement
disparaît des écrans de rangement, plus personne ne peut y ranger de cabine, et
l'historique reste lisible.

#### Supprimer un emplacement qui porte du stock — administrateurs seulement

Les écrans qui vident un emplacement (Sortie, Transfert) appartiennent au volet
articles, aujourd'hui retiré des menus : sans cette porte, un emplacement portant du
stock serait définitivement impossible à supprimer.

Un **administrateur** voit alors une fenêtre qui liste, article par article, ce qui
va être sorti, et demande un **motif obligatoire**. À la validation, le WMS enregistre
une **sortie de stock par article**, à son nom et avec son motif. Ce n'est pas un
transfert : les quantités quittent les totaux du stock, et le journal des mouvements
en garde la trace.

Un opérateur, même avec le droit « référentiel », ne peut pas forcer : le message lui
indique quels articles bloquent et à qui s'adresser.

> Les cabines rangées, elles, ne se forcent jamais — même pour un administrateur.
> Il suffit d'un clic sur « Sortir d'ici » depuis l'emplacement, alors que forcer
> rendrait tout le parc « non rangé » sans aucune trace.

### Zones

Même principe : **+ Nouvelle zone** en haut, clic sur une zone pour tout modifier (nom,
rôle, description, ordre d'affichage, active) ou la supprimer. Une zone encore rattachée
à des emplacements ne peut pas être supprimée — c'est son *rôle* qui permet au suivi du
processus d'annoncer « en attente de départ » plutôt qu'un simple code d'emplacement.

> Un emplacement **sans zone** est signalé sur sa fiche : le suivi du processus ne sait
> alors pas distinguer une cabine qui attend son départ d'une cabine qui sort de
> production. Rattachez chaque emplacement à une zone.

## Corriger ou supprimer une cabine mal saisie

Tout se fait depuis la **fiche de la cabine** : écran Cabines (ou scan du QR), puis
clic sur la cabine. Deux boutons sous l'étiquette QR.

### Corriger la fiche — le bon geste dans la plupart des cas

Ouvre une fenêtre où **tout** est modifiable : n° de cabine, n° de chantier, type,
modèle, et les informations reprises de la fiche papier (revendeur, client, tissus,
fond de cabine). La correction est enregistrée dans le journal avec l'avant et
l'après, champ par champ : « n° 26_03_47 → 26_03_48 ». Rien ne change en silence.

Corriger conserve tout l'historique de la cabine. C'est presque toujours préférable à
supprimer puis ressaisir — y compris sur une cabine déjà envoyée, dont la fiche reste
corrigeable même si plus aucune opération logistique n'est possible.

### Supprimer la cabine

Réservé au vrai doublon ou à la cabine créée par erreur. Le WMS regarde d'abord ce
que la suppression ferait perdre :

| Situation | Ce qui se passe |
|---|---|
| Cabine tout juste créée (ou seulement corrigée) | Confirmation simple. Sans conséquence. |
| Cabine rangée quelque part | Avertissement : la place sera libérée. Vérifiez que la cabine n'y est physiquement plus, sinon une autre y sera rangée par-dessus. |
| Cabine ayant déjà bougé (rangements, quarantaine…) | Le WMS propose de corriger la fiche plutôt. Ce n'est probablement pas une simple faute de frappe. |
| Cabine déjà envoyée | Avertissement : c'est une archive rattachée à un chantier. |

Dans les trois derniers cas, la suppression reste possible, mais elle demande un
**motif** — c'est lui qui répondra à « où est passée la 26_03_47 ? » la semaine
suivante.

> **Le journal survit à la suppression.** La ligne « Suppression de la cabine »
> conserve le numéro, le chantier, votre nom, la date et le motif ; les mouvements
> passés de la cabine restent visibles dans le Journal, recherchables par son numéro.
> Seule la fiche disparaît.

Ces deux actions demandent le droit **cabines**.

## Créer un rack entier en une fois

Dix colonnes sur trois niveaux, c'est trente fois le même formulaire. Le bouton
**« Créer un rack »** (écran Emplacements) demande la structure et génère tout.

| Champ | Ce qu'il veut dire |
|---|---|
| **Nom du rack** | Le début de chaque code. « AC » donne AC550, AC551… |
| **Cellules en longueur** | Le nombre de colonnes, c'est-à-dire de montants. |
| **Niveaux** | Le nombre d'étagères par colonne. |
| **Commencer au numéro** | Le numéro de la première colonne. Un « 050 » saisi garde son zéro de tête. |
| **Pas entre colonnes** | De combien le numéro augmente d'une colonne à la suivante (10 par défaut). |

**Le niveau s'ajoute au numéro de colonne.** Avec un pas de 10, la colonne 550
donne AC550, AC551, AC552, et la colonne suivante démarre à 560 :

> Rack **AC**, **10** colonnes, départ **550**, pas **10**, **3** niveaux
> → AC550 AC551 AC552 · AC560 AC561 AC562 · … · AC640 AC641 AC642 — **30 emplacements**

**L'aperçu montre tous les codes avant d'écrire quoi que ce soit.** Ceux qui
existent déjà apparaissent barrés : ils seront laissés intacts, jamais modifiés.
C'est ce qui rend l'opération rejouable — pour ajouter un 4ᵉ niveau à un rack
existant, on relance la même génération avec « Niveaux = 4 », et seul le nouveau
niveau est créé.

La zone, le mode de rangement et la description saisis s'appliquent à tout le rack.

> Le WMS refuse une génération où les niveaux déborderaient sur la colonne
> suivante (par exemple 3 niveaux avec un pas de 2 : la colonne 550 irait
> jusqu'à 552, et la suivante s'appellerait aussi 552).

## Imprimer les étiquettes QR

Écran **Étiquettes**, onglet **Emplacements**. Trois portées :

- **Une cellule** — une seule étiquette (aussi disponible depuis la fiche d'un emplacement) ;
- **Une colonne** — la bande d'un montant : AC550, AC551, AC552 ;
- **Un rack entier** — toutes les bandes du rack, une par colonne.

Chaque **bande** fait **8 cm de large** et **toute la hauteur de la feuille A4**.
Les QR y sont empilés à la verticale, largement espacés — comme les niveaux le sont
sur le montant — et **le code d'emplacement figure au-dessus de chaque QR**.

La bande est l'image du montant : **le niveau le plus haut est imprimé en haut, le
niveau 0 tout en bas** (AC552, AC551, AC550). On la pose d'un bloc, sans avoir à la
retourner.

Deux bandes tiennent côte à côte sur une A4, donc un rack de 10 colonnes sort en
5 feuilles. Une étiquette seule ne consomme pas toute une page : elle reste compacte. Les bandes s'enchaînent
sur la feuille — deux tiennent côte à côte sur une A4 — et aucune n'est jamais
coupée entre deux pages : on découpe le long des pointillés et on pose la bande
d'un bloc sur le montant.

La **taille des QR** se règle en haut de l'écran : grand (55 mm), moyen (40 mm,
par défaut) ou compact (28 mm). C'est un maximum : au-delà de cinq ou six niveaux,
les QR sont réduits automatiquement pour que la bande tienne encore sur une seule
page — une bande n'est jamais coupée en deux.
