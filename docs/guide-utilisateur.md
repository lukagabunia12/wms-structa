# Guide utilisateur — WMS Structa

> L'interface opérateur est disponible à la racine du serveur (`http://127.0.0.1:8000/`).
> Ce guide décrit les opérations métier qu'elle propose.

Selon votre compte, certaines opérations peuvent être refusées : la consultation est ouverte à tous,
mais les écritures dépendent des droits accordés (**cabines**, **référentiel**,
**matières premières**). Un compte « lecture seule » ne peut rien modifier.

Au téléphone, quatre onglets en bas de l'écran : **Cabines** (scanner une fiche ou
une étiquette, et tout ce qui se fait sur une cabine), **Stock** (chercher dans le stock
des cabines ou des matières premières), **MP** (entrer, sortir, déplacer des vitrages et
des cartons) et **Plus**. Au bureau, les mêmes écrans sont dans la barre latérale.

En haut à droite, la **cloche** signale ce qui demande un geste — voir « La cloche »
plus bas.

## Cabines
Suivi des cabines par numéro (`xx_xx_xx`) et chantier (6 chiffres, éventuellement suivis du
lot : `251213-1`), avec un statut — « Conforme » ou « En quarantaine » — et une sortie
définitive.

## Recherche et traçabilité
Recherche d'emplacements et de cabines ; le **Journal** retrace tout ce qui est arrivé à
chaque cabine, avec l'auteur et la date.

## Emplacements — tout se passe au même endroit

Menu **Référentiel → Emplacements** (ou la tuile « Emplacements » de l'accueil).
C'est l'unique écran du référentiel : occupation, ajout, réglages et suppression.
Il remplace les anciens écrans « Emplacements » et « Gestion des emplacements »,
qui proposaient chacun des champs différents.

**Ajouter** — le bouton orange **« + Nouvel emplacement »** est en haut à droite du
titre, toujours visible. Une fenêtre s'ouvre : code, **ce qu'il range** (cabines sur deux
places, cabines en capacité illimitée, MP — cartons, MP — vitrages), description, et la
case « zone de réception ». Le code est ce qui sera imprimé sur l'étiquette QR collée sur
l'emplacement.

**Créer un rack entier** — bouton **« Créer un rack »**, à côté du précédent.
Voir la section « Créer un rack » plus bas.

**Modifier ou supprimer** — cliquer sur une ligne de la liste ouvre la fiche de
l'emplacement. On y trouve, dans l'ordre :

1. l'occupation (les deux places gauche et droite, ou les cabines en capacité
   illimitée) et les boutons « Saisir le n° à la main » / « Sortir une cabine » ;
2. les **réglages** : code, ce qu'il range, description, zone de réception — puis la
   mise en service de l'emplacement et de chacune de ses places (deux pour des cabines,
   trois pour des matières premières) ;
3. l'**impression de l'étiquette QR** et la **suppression**.

Un emplacement scanné donne accès à la même fiche : bouton « Régler cet emplacement ».
Pour un emplacement MP, la fiche montre aussi ses **codes acceptés** (voir plus bas).

### Ce que le WMS refuse de supprimer, et pourquoi

| Situation | Ce qui se passe |
|---|---|
| Des cabines y sont rangées | Refus. Déplacez-les ou envoyez-les d'abord — sinon elles se retrouveraient « non rangées » sans aucune trace. Personne ne peut passer outre, pas même un administrateur. |
| Du stock MP y est posé | Refus, pour la même raison : sortez les vitrages ou les cartons d'abord — ou changez-les d'emplacement. |
| Aucune cabine | Suppression après une simple confirmation. Le journal des cabines garde le code de l'emplacement : l'historique reste lisible. |

**Désactiver** reste le bon geste pour un emplacement provisoirement hors d'usage :
il disparaît des écrans de rangement, plus personne ne peut y ranger de cabine, et
il se remet en service d'un geste.

### Zones

Les zones se règlent dans l'administration (`/admin/`). Une zone encore rattachée à des
emplacements ne peut pas être supprimée : l'administration nomme les emplacements à
rattacher ailleurs d'abord.

## Matières premières — vitrages et cartons

Onglet **MP**, en bas de l'écran. Tout part de l'emplacement, comme tout part du
numéro pour une cabine : on scanne l'étiquette du rack ou du chevalet — ou on tape
son code —, l'écran montre ses **trois places, gauche, milieu, droite**, et ce que
chacune porte, code par code, avec la quantité.

### Entrer

1. **Entrer** ;
2. touchez la **place** où vous posez — rien n'est présélectionné ;
3. tapez le **code élément** : quelques signes suffisent, la liste se resserre à
   mesure. « vitr.8 » propose les VITR.8…, « 445 » le VITR.445X2072.BP, « 434 » le
   même par son n° d'article, « ESS 1 F » le fond de carton marqué ainsi sur la
   palette. Touchez le bon code : il doit venir de la base, il ne s'invente pas ;
4. la **quantité**, en pièces. Pour un carton, le bouton **« 160 · 1 palette »**
   l'écrit d'un geste — il ne le fait jamais tout seul, une palette entamée existe ;
5. **Entrer**. Le même code posé à nouveau sur la même place s'additionne.

**Ancienne génération** — un code d'ancienne génération (lignes grisées des
vitrages, lignes rouges des cartons) reste proposé, marqué **« ancienne gen »** : il
reste du stock à ranger. À la validation, le WMS demande : **« Attention : … est une
ancienne génération. Tu veux vraiment l'entrer ? »** — « Non » n'enregistre rien.

Un emplacement **réservé à certains codes** les propose d'une touche, en pastilles,
au-dessus du champ : on touche celui qu'on pose. La recherche ne cherche alors que
parmi eux — un autre code se pose sur un autre emplacement. Et quand un code a sa
place réservée ailleurs, l'écran le dit au moment où on le choisit (« Ce code a sa
place réservée en AH510 »).

### Sortir

Touchez la ligne à sortir — ou **Sortir**, puis la ligne. Indiquez **combien**
(« Tout » d'un geste), et si vous voulez **pourquoi** : Production, Casse,
Inventaire, Retour fournisseur, ou un motif écrit. On ne sort jamais plus que ce qui
est là ; à la dernière pièce, la ligne disparaît.

Si la sortie fait passer le code **sous son seuil d'alerte**, l'écran le dit tout de
suite, sous la phrase de réussite : « VITR.470X2072.BP est sous son seuil d'alerte :
plus que 49 vitrages en stock, pour un seuil de 50. »

### Changer d'emplacement

Pour déplacer une palette ou un chevalet, on ne sort pas puis on ne rentre pas :
c'est **un seul geste**, et une seule ligne au journal par ligne déplacée — d'où, vers
où.

1. Sur l'emplacement de départ, **Changer d'emplacement** ;
2. touchez **ce qui part** — une ligne ou plusieurs : elles se cochent. **Tout cocher**
   prend tout l'emplacement. (Avec une seule ligne posée, cette étape est sautée.)
   Puis **Choisir l'arrivée** ;
3. pour chaque ligne, la **quantité** : laissée vide, c'est **toute la ligne** — le
   bouton le dit (« Déplacer 19 VITR.470… ») ; tapée, seulement cette partie ;
4. l'**arrivée** : scannez son étiquette (bouton à droite du champ), ou tapez son code
   — la liste propose les emplacements de la même famille, et dit tout de suite
   ceux qui refuseraient (hors service, réservés à d'autres codes, autre famille) ;
5. touchez la **place d'arrivée** — rien n'est présélectionné. Sur le même
   emplacement, la place de départ est éteinte : on peut aussi passer de gauche à
   droite ;
6. **Déplacer**. Tout passe ou rien : si une seule ligne ne peut pas aller là, rien ne
   bouge, et le message dit laquelle. Le bouton **« Ouvrir AH510, où le stock est
   arrivé »** mène ensuite à l'arrivée.

Une ancienne génération se déplace sans confirmation : elle est déjà là. Un
emplacement hors service se vide encore par ce geste.

### Consulter

Onglet **Stock** → bouton **MP** en haut (le bouton **Cabines** revient au stock des
cabines ; le téléphone se souvient du dernier choix). Depuis l'onglet MP, le geste
**« Trouver par code élément »** y mène directement, le curseur dans la recherche.
Une ligne par code : la quantité totale, le **seuil d'alerte** s'il en a un, et
**toutes ses positions** (AH500·G 19 · AH510·D 6).

- La recherche prend un code, une dimension, un n° d'article ou un **emplacement**
  (« AH5 » montre ce qui est posé en AH5…).
- Filtres rapides : **Vitrages**, **Cartons**, **Ancienne génération**, **Sous le
  seuil d'alerte** (jamais pour une ancienne génération, qu'on écoule). Le panneau
  Filtres ajoute fournisseur, rack, génération, tri, et « toute la base » pour voir
  aussi les codes sans stock.
- Toucher un code ouvre sa fiche : ses références, son seuil d'alerte, ses positions
  — qui ouvrent l'emplacement, pour en sortir ou le déplacer —, les **emplacements
  qui lui sont réservés**, ses derniers mouvements.
- **Télécharger le stock MP (Excel)** : une ligne par position, ce qui est affiché.
- **Journal MP** (onglet MP, ou menu) : chaque entrée, chaque sortie et chaque
  changement d'emplacement (« AH500·M → AH510·G »), avec l'auteur, la date, le motif
  et ce qui restait après — aux deux bouts pour un déplacement. Le filtre
  « Mouvement » isole les changements d'emplacement ; chercher « AH500 » trouve aussi
  ce qui en est parti.

### Seuils d'alerte

Le **seuil d'alerte** d'un code est le stock sous lequel la cloche sonne : seuil 50,
l'alerte part à 49 — pas à 50. Un code sans seuil ne sonne jamais ; une ancienne
génération non plus, quel que soit son seuil : on l'écoule, on ne la recommande pas.

- **Pour un code** : sa fiche (onglet Stock → MP → le code) → **« Régler le seuil
  d'alerte »**.
- **Pour plusieurs codes à la fois** : onglet Stock → MP → **« Régler les seuils
  d'alerte »**. Les codes se cochent au lieu d'ouvrir leur fiche — les codes sans
  stock sont montrés aussi, c'est pour eux qu'un seuil sert d'abord. Resserrez la
  liste avec les filtres (Cartons, un fournisseur…) puis **Toute la liste**, ou
  touchez les codes un à un ; enfin **« Seuil d'alerte pour N codes »**. La fenêtre
  rappelle les seuils actuels avant de les remplacer. Laisser le champ vide retire
  l'alerte.

Régler un seuil demande le droit **référentiel** : c'est un réglage de la base des
codes, pas un geste de poste.

### La cloche

En haut à droite de chaque écran, la cloche porte le **nombre d'alertes** en cours :

- les codes **sous leur seuil d'alerte** — le plus urgent en tête, un code à zéro
  avant un code juste en dessous ;
- les lignes posées sur un emplacement qui **ne les accepte plus** (voir « Codes
  acceptés ») : elles sont à changer d'emplacement.

La pastille est **rouge** tant qu'une alerte n'a pas été vue sur ce téléphone ou ce
poste, et la cloche bat une fois quand une nouvelle arrive. Toucher la cloche ouvre la
liste — les nouvelles y sont marquées d'un point rouge — et la pastille repasse au
bleu marine : une alerte vue reste une alerte, jusqu'à ce que le stock soit refait, le
seuil changé ou la palette déplacée. Une alerte qui disparaît puis revient redevient
rouge. Toucher une alerte ouvre le code, ou l'emplacement.

La cloche suit l'activité de tous les postes, toutes les dix secondes, même pendant
une saisie. Elle n'apparaît que sur les comptes qui ont la case **matières
premières** ou le droit **référentiel** : ceux qui peuvent agir sur ce qu'elle dit.

### Régler les emplacements MP

Un emplacement range des cabines **ou** une famille de matières premières — jamais
les deux. Le réglage se fait en nombre :

1. **Emplacements** → le rack → **« Sélectionner plusieurs emplacements »** ;
2. touchez les cases — ou un **n° de colonne** pour toute la colonne, un **niveau**
   (N0, N1…) pour tout le niveau : le sol d'un rack où se posent les chevalets —, ou
   **Tout le rack** ;
3. **« Ce qu'ils rangent »** → Cabines (2 places ou capacité illimitée), **MP —
   cartons** ou **MP — vitrages** ;
4. le WMS dit ce qui va changer, ce qui l'est déjà, et ce qui ne peut pas — un
   emplacement où une cabine ou du stock MP est encore posé : il est **nommé**, et
   laissé tel quel. **Appliquer** change tous les autres.

Sur le plan du rack, les emplacements MP portent la texture de leur matière — reflets
bleutés pour le verre, cannelures kraft pour le carton — et disent « vide » ou « 2
codes ». Ils ne prennent jamais de cabine : le rangement d'une cabine les refuse, et
l'onglet MP refuse un emplacement de cabines, en le disant sur la vidéo.

Un emplacement se règle aussi à l'unité, sur sa fiche (« Ce qu'il range »), et un rack
se crée directement pour les MP (« Créer un rack » → « Ce qu'il range »).

### Codes acceptés : réserver un emplacement à certains codes

Un emplacement MP accepte, par défaut, **tous les codes de sa famille**. On peut le
**réserver** à un ou plusieurs codes : « le sol de AH ne prend que les VITR.445 et les
VITR.470 ». Les autres codes y sont alors refusés à l'entrée — et au déplacement —,
avec un message qui dit lesquels y vont.

- **À l'unité** : la fiche de l'emplacement (Emplacements → l'emplacement, ou
  « Régler cet emplacement » depuis l'onglet MP) → carte **Codes acceptés**. Tapez un
  code pour l'ajouter, touchez la croix d'une pastille pour le retirer, ou **« Accepter
  de nouveau tous les … »**. Chaque geste s'enregistre aussitôt.
- **En nombre** : le rack → **« Sélectionner plusieurs emplacements »** → les cases (un
  niveau, une colonne…) → **« Codes acceptés »**. Trois réglages :
  - **Réserver à des codes précis** — la réservation devient exactement ces codes ;
  - **Ajouter des codes à leur réservation** — les codes déjà acceptés le restent. Un
    emplacement encore ouvert à toute sa famille n'est pas fermé pour autant : il
    accepte déjà ces codes, et le WMS le dit ;
  - **Accepter de nouveau tous les codes** — retire la réservation.

  Chaque emplacement prend les codes de **sa** famille : d'un même geste, le niveau
  des vitrages et celui des cartons se réservent chacun à leurs codes. Comme pour
  « Ce qu'ils rangent », le WMS montre d'abord ce qui va changer, ce qui l'est déjà
  et ce qui ne peut pas — un emplacement de cabines, ou sans aucun code de sa famille
  dans la sélection.

**Une réservation ne déplace rien.** Ce qui est déjà posé et n'est plus accepté
reste là : il peut toujours sortir ou changer d'emplacement. L'écran de l'emplacement
le marque (« plus accepté ici : à changer d'emplacement »), et la cloche le signale
tant qu'il y est. Quand un emplacement change de famille (« Ce qu'il range »), ses
codes acceptés partent avec l'ancienne famille.

Sur le plan du rack, un emplacement réservé porte un **coin bleu nuit** en haut à
gauche ; son infobulle donne les codes.

### La base des codes

Livrée prête : **19 vitrages** (fournisseurs ATV et MT) et **26 cartons** (un couvercle
et un fond par carton), recopiés des tableaux de l'exploitation, avec leurs anciennes
générations. Elle se complète et se corrige dans l'administration (`/admin/` →
**Codes MP**) : un code retiré se décoche « actif » — il ne se propose plus, mais le
journal et le stock qui le citent restent lisibles.

Entrer, sortir et changer d'emplacement demandent la case **matières premières** sur
le compte ; régler les emplacements (ce qu'ils rangent, leurs codes acceptés) et les
seuils d'alerte, le droit **référentiel**.

## Corriger ou supprimer une cabine mal saisie

Tout se fait depuis la **fiche de la cabine** : onglet Stock (côté Cabines), puis clic
sur la cabine. Les deux boutons **« Corriger la fiche »** et **« Supprimer »** sont sous
ses caractéristiques.

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

Ce qu'il range — cabines ou matières premières — et la description saisis
s'appliquent à tout le rack.

> Le WMS refuse une génération où les niveaux déborderaient sur la colonne
> suivante (par exemple 3 niveaux avec un pas de 2 : la colonne 550 irait
> jusqu'à 552, et la suivante s'appellerait aussi 552).

## Imprimer les étiquettes QR

Écran **Étiquettes**. Trois portées :

- **Une cellule** — une seule étiquette (aussi disponible depuis la fiche d'un emplacement) ;
- **Une colonne** — la bande d'un montant : AC550, AC551, AC552 ;
- **Un rack entier** — toutes les bandes du rack, une par colonne.

Chaque **bande** fait **8 cm de large** et **toute la hauteur de la feuille A4**.
Les QR y sont empilés à la verticale, largement espacés — comme les niveaux le sont
sur le montant — et **le code d'emplacement figure au-dessus de chaque QR, en gros
caractères gras, exactement aussi large que le QR** : au-dessus d'un QR de 40 mm,
« Y550 » s'écrit sur 40 mm de large et 12 mm de haut. Il se lit de loin, en
remontant l'allée, et se recopie sans hésiter quand le scan ne prend pas. Un code
plus long s'écrit moins haut, jamais plus large que le QR.

La bande est l'image du montant : **le niveau le plus haut est imprimé en haut, le
niveau 0 tout en bas** (AC552, AC551, AC550). On la pose d'un bloc, sans avoir à la
retourner.

Deux bandes tiennent côte à côte sur une A4, donc un rack de 10 colonnes sort en
5 feuilles. Une étiquette seule ne consomme pas toute une page : elle reste compacte. Les bandes s'enchaînent
sur la feuille — deux tiennent côte à côte sur une A4 — et aucune n'est jamais
coupée entre deux pages : on découpe le long des pointillés et on pose la bande
d'un bloc sur le montant.

La **taille des QR** se règle en haut de l'écran : grand (55 mm), moyen (40 mm,
par défaut) ou compact (28 mm). C'est un maximum : dès quatre ou cinq niveaux, les
QR — et leur code avec eux — sont réduits automatiquement pour que la bande tienne
encore sur une seule page (environ 35 mm pour cinq niveaux) — une bande n'est jamais coupée
en deux. Le QR ne descend jamais sous 20 mm : au-delà, c'est le code qui s'écrit
moins haut.

## Le WMS sur l'écran d'accueil du téléphone

Écran **Plus** → carte **« Sur l'écran d'accueil »**. Sur Android, le bouton
**« Installer sur ce téléphone »** pose l'icône **WMS Structa** en un geste quand
Chrome le permet ; sinon, et sur iPhone, la carte rappelle les trois gestes à
faire dans le navigateur. L'icône ouvre le WMS en plein écran, sans adresse à
retaper. Ouvert depuis l'icône, le WMS ne propose plus rien : c'est le signe que
tout est en place.

Procédure complète, prérequis compris (certificat du réseau interne) :
`docs/guide-https.md`, section « Mettre le WMS sur l'écran d'accueil ».

## Scanner une étiquette d'emplacement

Onglet **Cabines** → « Scanner le QR d'un emplacement », ou l'étape « Où la ranger ? »
du rangement. L'onglet **MP** a le sien, pour les emplacements de matières premières,
et le changement d'emplacement scanne l'étiquette de l'arrivée de la même façon. Seuls les emplacements portent un QR : la **fiche** collée sur la
cabine se **photographie**, elle ne se scanne pas.

1. **Pendant la visée**, une pastille **« Lecture en cours — visez l'étiquette »**
   s'affiche en haut de la vidéo, et un trait orange balaie le cadre : l'appareil
   cherche. Visez **une seule** étiquette, dans le cadre.
2. **Dès qu'un code est lu**, l'image se fige sur l'étiquette, les angles du cadre
   passent au vert, le téléphone vibre, et le code s'affiche **en grand sur la
   vidéo** — par exemple « Emplacement lu : Y550 » — avec deux boutons :
   - **Confirmer** : le WMS continue avec cet emplacement ;
   - **Rescanner** : la visée repart aussitôt, caméra restée ouverte. La même
     étiquette n'est pas relue pendant une seconde et demie, le temps de viser la
     voisine.

   **Rien ne s'enchaîne avant « Confirmer ».** Trois étiquettes se touchent sur un
   montant : c'est là qu'on vérifie laquelle a été prise.
3. **Un code refusé** — emplacement inconnu, ou plein pour cette cabine — se dit
   au même endroit, sur l'image figée (« Code refusé : A-01 n'a plus de place
   libre pour cette cabine »), avec « Rescanner ». Pas de message à chercher plus
   bas, pas de caméra à rallumer.

Sous la vidéo : **« Éclairer »** allume la lampe du téléphone quand il en a une,
**« Arrêter la caméra »** la rend. Quitter l'écran l'éteint aussi.

Sans caméra, à l'étape « Où la ranger ? » : **« Saisir le code à la main »** sous
la vidéo, puis Entrée ou « Continuer ».
