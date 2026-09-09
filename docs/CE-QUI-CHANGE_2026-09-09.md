# Livraison — emplacement, motifs obligatoires, repartir de zéro

Quatre demandes, dans l'ordre où vous les avez posées.

---

## 1. Le mot « travée » a disparu

Remplacé par **emplacement** partout : à l'écran, dans les messages du serveur,
dans les commentaires du code et jusque dans les noms des tests. Le balayage
final ne trouve plus une seule occurrence hors migrations (là, les anciens noms
de champs doivent rester : ce sont les colonnes déjà écrites en base).

Le mot avait déjà survécu à **deux** balayages qui se croyaient complets. La
cause : mon `grep 'trav[ée]e'` tournait sans locale UTF-8, et une classe de
caractères ne reconnaît pas un « é » multi-octets dans ces conditions — il
répondait « rien » sur dix lignes bien présentes. `outils/verifier_interface.js`
porte donc un contrôle de plus, qui cherche la **chaîne littérale** dans tout
l'arbre, commentaires compris. `node outils/verifier_interface.js` refuse
maintenant de passer si le mot revient. Vérifié en le remettant exprès.

Au passage, une faute d'accord laissée par le renommage : la ligne d'un
emplacement pris en entier affichait **« Tout l'emplacement occupée »**. Le badge
était écrit une fois pour trois usages différents ; c'est maintenant l'appelant
qui donne le mot, parce que lui seul sait si son titre nomme une place, une
cabine ou un emplacement.

## 2. Plus de suffixe `-T` dans les positions

`AC550-T` s'affiche désormais **`AC550`**. Le code stocké en base reste `T` —
l'historique déjà écrit doit rester lisible — mais il ne sort plus à l'écran :
quand une cabine prend tout l'emplacement, il n'y a pas de place à préciser.
`AC550·G` et `AC550·D` restent, eux : là, la place est une information.

## 3. Pas de quarantaine sans motif, pas de sortie sans motif

**Quarantaine.** Le libellé du champ passe à « Pourquoi cette quarantaine ? * »
dès que vous touchez le statut, avant d'appuyer sur Enregistrer. Sans motif, la
fenêtre **reste ouverte**, le champ passe en rouge et dit pourquoi. Elle ne se
referme pas : sur un téléphone, à côté d'un rack, refermer la fenêtre pour
afficher une erreur est exactement ce qui pousse à taper « ok » pour passer.

Lever une quarantaine n'exige rien. Constater qu'une cabine est redevenue
conforme n'a rien à expliquer — et exiger un motif dans les deux sens ferait
taper « ok » à la levée, puis à la pose par habitude.

**Sortie d'emplacement.** Même règle, même fenêtre. Le motif part au journal à
côté de l'emplacement quitté : c'est lui qui répondra à « où est passée la
00_00_01 ? » le lendemain.

Un motif fait d'espaces ne compte pas. On ne peut pas juger de la qualité d'un
motif, mais on peut refuser le vide déguisé.

## 4. Repartir de zéro, depuis l'application

Nouvel écran : **Plus → Référentiel → Repartir de zéro**. Administrateurs
seulement.

Il annonce les nombres **avant** le geste, en deux colonnes :

| Ce qui part | Ce qui reste |
|---|---|
| toutes les cabines | les lignes du fichier de production |
| tout leur journal | les emplacements et les zones |
| leurs positions | les tailles de modèle réglées |
| | les comptes |

Puis il demande de retaper **EFFACER**. En minuscules, c'est refusé, et l'écran
dit lequel des deux est le mot attendu. Après l'effacement il se redessine sur
un parc vide — la preuve est à l'écran, pas dans un message — et reste
utilisable pour la remise à zéro suivante.

**Pourquoi le fichier de production est conservé.** L'effacer désarmerait au
passage la règle « une cabine non annoncée ne s'enregistre pas », et il faudrait
réimporter 2 264 lignes avant de pouvoir entrer la première cabine.

**Pourquoi un écran et pas la commande.** `python manage.py reinitialiser`
existe toujours et reste le geste de la mise en service. Mais la remise à zéro
sert *pendant* les essais, plusieurs fois de suite — et le terminal est sur le
serveur, pas dans la poche de la personne qui teste.

Si vous préférez quand même la ligne de commande :

    python manage.py migrate
    python manage.py reinitialiser --garder-referentiel

---

## Ce qui a été vérifié

- **602 tests Django** passent (3 ignorés). Il y en avait 579 ; les 23 nouveaux
  couvrent les deux règles de motif et la remise à zéro — dont ce qui **survit**,
  qui est le point de la règle.
- **136 contrôles dans un vrai navigateur** à 390 × 844, sur un vrai serveur :
  7 séries, toutes vertes. La série « repartir de zéro » va jusqu'au bout —
  refus de `effacer`, vérification qu'aucune cabine n'a bougé, effacement, parc
  vide, puis une cabine ré-entrée et rangée pour prouver que l'emplacement est
  bien libre.
- `ruff` : rien à signaler. Les deux vérificateurs d'interface : verts.
- `makemigrations --check` : aucune migration en attente.

Un défaut trouvé par ces contrôles et corrigé : 24 tests existants échouaient
parce qu'ils posaient une quarantaine ou sortaient une cabine **en passant**,
pour préparer autre chose. Ils donnent maintenant un motif, comme la personne au
poste. Un vingt-cinquième affirmait la règle **contraire** (« le motif est
facultatif ») : celui-là a été réécrit, pas retapé.

## C'est commité

Commit **d5a7787**, sur votre dépôt, après comparaison des empreintes md5 des
26 fichiers des deux côtés. `docs/Archive/` reste hors commit — c'est le point
qu'on n'a pas encore tranché.

Au passage, j'ai vidé les dossiers `_a_supprimer/` à la racine et dans
`wms/tests/` : c'étaient mes fichiers de travail, 102 Mo de patches déjà
appliqués et d'archives de transfert, tous reproductibles depuis git. J'ai aussi
nettoyé 175 fichiers temporaires que git n'arrivait pas à effacer dans
`.git/objects/`.

**`docs/_a_supprimer/` n'a pas été touché** : il contient 26 Mo de versions
précédentes de vos procédures PRO (214, 215, 216, 218, 220, 225, 226). Ce sont
vos documents, pas mes fichiers de travail — dites-moi si vous voulez que je les
supprime.

## Sur votre serveur

Les migrations 0019, 0020 et 0021 sont à passer (`python manage.py migrate`), et
`pip install -r requirements.txt` si ce n'est pas déjà fait — openpyxl a été
ajouté pour l'import du fichier de production.

Je n'ai pas pu atteindre votre PostgreSQL depuis ici : ce que je peux tester est
une copie SQLite dans mon environnement, jamais votre base de production.
