# Inventaire du comportement — Maquette WMS STRUCTA

> Référence de transposition (WMS uniquement). Décrit le comportement observable de la maquette actuelle,
> à reproduire à l'identique dans la nouvelle application (Django + API + PWA). Sert aussi de contexte à Claude.
> Établi à partir de : server.js, index.html (WMSCore), wms-app.js, wms-ui.js, wms-plus.js, wms-extra.js, wms-zebra.js.
> Hors périmètre : appro/MRP, carte d'entrepôt (wms-carte.js).

## Architecture générale (préalable indispensable)

- **Toute la logique métier est côté front (JavaScript navigateur).** `server.js` ne connaît PAS le stock : il stocke/relit un **unique blob JSON** (`data`) par application via `/api/data/wms`, avec versionnement optimiste (`rev`/`baseRev`, conflit `409`). Le calcul de stock, les mouvements, les cabines, etc. sont entièrement dans les fichiers `wms-*.js`.
- **Le cœur de calcul** est le module `WMSCore` défini inline dans `index.html` : `emptyState`, `applyMovement`, `stockLine`, `totalStock`, `genRef`, `stockAtDate`, `findByCode`, etc.
- **Empilement de surcouches** (ordre de chargement : `wms-app.js` → `wms-extra.js` → `wms-ui.js` → `wms-zebra.js` → `wms-plus.js` → `wms-carte.js`). Chacune **enveloppe** `window.render`/`window.handle` et **remplace** certaines fonctions `window.scr*`. Pour un écran donné, la version active est celle de la surcouche **la plus externe**. Ex. : les écrans Cabines/Inventaire actifs sont ceux de `wms-plus.js`.
- **Deux modes d'exécution :** (1) Mode serveur (servi par server.js sur `/wms`) : `window.STRUCTA_SESSION` injecté, identité/droits serveur, stock partagé multi-postes via `/api/data/wms`. (2) Mode autonome (index.html seul) : comptes locaux à code PIN, stock en `localStorage` (`structa_wms_v1`).

## 1. Écrans / onglets / fonctionnalités WMS

Barre basse : Accueil, Entrée, Sortie, Recherche, Plus.

- `home` — Accueil : tuiles (Scanner, Réception, Ranger, Sortie, Rechercher, Tableau de bord), KPIs, bandeau « à commander ».
- `in` — Réception / entrée (recherche article → quantité).
- `out` — Sortie (scan QR ou recherche → emplacement → quantité).
- `search` — Recherche multi-entités (articles + cabines + emplacements + traçabilité).
- `more` — Menu « Gestion ».
- `dashboard` — KPIs (réf., qté totale, emplacements, alertes), stock bas, derniers mouvements.
- `articles` / `articleEdit` — Liste + fiche article (CRUD), import CSV.
- `categories` — Catégories (nom, zone) — admin.
- `locations` — Emplacements : recherche, stats, CRUD, suppression sécurisée.
- `labels` — Étiquettes QR articles/emplacements + export Zebra ZPL/CSV.
- `data` — Sauvegarde/extraction : export CSV/JSON, import, démo, reset.
- `receptions` / `recept` — Journal des réceptions + étiquette de réception (QR/ZPL).
- `transfer` — Transfert entre emplacements.
- `putaway` — Rangement / sortie par emplacement (hub : Entrée/Sortie/Cabine).
- `cabines` / `cabine` — Liste et création de cabines (avec statuts).
- `inventaire` — Comptage par emplacement, écarts en ajustements.
- `trace` — Traçabilité totale (mouvements + cabines).
- `reappro` — « À commander » (sous seuil mini).
- `scanpick` — Écran post-scan (Entrée/Sortie/Détail).
- `history` — Historique filtré des mouvements.
- `asof` — Stock à une date (recalcul depuis le journal).
- `users` / `login` / `setup` — Comptes / connexion PIN / création admin (mode autonome).

## 2. Opérations de stock et leur effet EXACT

Modèle d'état : `state = { meta, categories[], locations[], articles[], stock[], mouvements[] }`, enrichi de `receptions[]`, `cabines[]`, `cabEtats[]`, `users[]`, `locArch[]`.
- **stock** = lignes `{articleId, locationId, qte}` — une ligne par couple (article, emplacement).
- **mouvement** = `{id, date(ISO), type, articleId, locationId, qte, user, note, commande}` ; `qte` toujours positive, signe déduit du type ; ajout en tête.

### `applyMovement(state, mv)` — fonction pivot
Trois types : **IN, OUT, ADJUST**. Sur la ligne (articleId, locationId), créée à 0 si absente :
- **IN** : `qte += mv.qte`
- **OUT** : si dispo < mv.qte → échec « Stock insuffisant (X dispo) » ; sinon `qte -= mv.qte`
- **ADJUST** : `qte = mv.qte` (valeur absolue)
- Validations : article et emplacement obligatoires ; `qte>0` pour IN/OUT ; `qte>=0` pour ADJUST. Mouvement toujours journalisé. Stock négatif impossible.

### Détail par opération
- **Entrée (Réception)** `confirmIn` : 1× IN + **1 mouvement IN (note « Réception ») ET 1 réception** → étiquette. Emplacement requis, qte>0.
- **Réception « à ranger »** `confirmInStaging` : 1× IN vers staging `__ARANGER__` + 1 mouvement + 1 réception `staging:true`. Droit `mvt`.
- **Rangement depuis staging** `confirmPutaway` : IN de `q` sur cible **+** OUT de `min(q, stock_staging)` depuis staging. Fixe `article.emplacementId` s'il est vide. Note « Rangement depuis À ranger » ou « Entrée directe ».
- **Sortie (onglet)** `confirmOut` : 1× OUT. Emplacement requis, q>0, stock suffisant.
- **Sortie par emplacement** `confirmLocOut` : 1× OUT (note « Sortie sur scan emplacement »).
- **Transfert A→B** `doTransfer` : **OUT source + IN destination** (2 mouvements). source≠dest, q>0, dispo_source≥q.
- **Inventaire** `applyInv` : par écart, 1× ADJUST = quantité comptée (note « Inventaire (théorique X) »). Case vide = inchangée ; n=théorique ignoré ; n<0 ignoré ; confirmation ; droit `inv`.
- **Correction / contre-passation** `undoMvt` : mouvement **inverse** (IN↔OUT) ; original `annule=true`, nouveau `annulation=true`. **Impossible sur ADJUST** ; refusé si déjà annulé ; échoue si stock insuffisant. Droit `mvt_corr`.

Points subtils : réception normale ET « à ranger » créent mouvement + réception ; rangement/transfert/entrée directe ne créent PAS de réception. Rangement avec q>staging crée du stock net (voulu). Suppression d'article conserve mouvements/réceptions/cabines (réf. orphelines « ? »). Suppression d'emplacement refusée s'il reste stock/cabines ; sinon détache articles et archive dans `locArch`.

## 3. Cabines

`{ id, numero, chantier, modele, locationId, date, user, etat?, etatUser?, etatDate?, statut?, sortieLoc?, sortieDate?, sortieUser? }`
- `chantier` : 6 chiffres (`/^\d{6}$/`). `numero` : unique, `xx_xx_xx`. `locationId` obligatoire (non-staging). `modele` libre.
- **Deux notions d'état** : `etat` = statut personnalisable (`state.cabEtats`, défaut `['Quarantaine']`, création/retrait par droit `ref`, changement par droit `cab`) ; un statut retiré reste porté par les cabines existantes. `statut='sortie'` = sortie via `doCabineOut` (irréversible : pose sortieLoc/Date/User) ; la cabine sortie reste listée et garde son `etat`.
- Liens : `locationId` (apparaît dans le putaway de l'emplacement) ; `chantier` = champ (pas d'entité) ; traçabilité `cabin`/`cabout`.

## 4. Rôles et permissions

Rôles : `admin`, `operateur`, `lecture`. Sept droits fins (`DROITS`) préréglés par rôle puis ajustables par compte (sauf admin) :
- `mvt` (entrées/sorties/transferts/rangement/réceptions), `mvt_corr` (correction), `inv` (inventaire), `cab` (cabines), `ref` (référentiel : articles/catégories/emplacements/statut dormant), `data` (imports/reset), `appro` (hors périmètre).
- admin=tout ; operateur défaut = mvt/mvt_corr/inv/cab ; lecture = consultation seule.
- Trois couches d'application : client mode serveur (`DROIT_RULES` dans wms-plus), client base/rôle (`allow` dans wms-extra), serveur (POST `/api/data/wms` : `lecture`→403, non-admin sans droit→403). Consultation ouverte à tous.
- Nuance : la **sortie de cabine** est gardée dans l'UI par le droit `mvt` (via `canMove`), alors que `DROIT_RULES` la classe sous `cab`.

## 5. Flux de scan

- `wms-zebra.js` = **export d'étiquettes** pour imprimantes Zebra (ZPL/CSV, tailles mm), PAS l'entrée de scan.
- Scan d'entrée = **caméra** via `html5-qrcode`, avec repli saisie manuelle. Codes : `ART:<ref|id>`, `LOC:<code>`, `REC:<id>`, + EAN-13/8, UPC-A, CODE-128/39 (correspondance sur `ref`/`ean`).
- Actions : Scanner accueil → emplacement=putaway, REC:=étiquette, article=scanpick (Entrée/Sortie/Détail), inconnu=proposer création. `in:scan`/`out:scan`, `putaway:scan/scanart`, `invc:scan`, `transfer:scan`, `search:scan` selon contexte.

## 6. Règles et cas limites notables

- **genRef** : 1re lettre de la catégorie (MAJ, sinon `A`) + 4 chiffres, séquence = `articles.length+1` jusqu'à unicité (ex. `V0001`). `ref` unique (insensible casse), `ean` unique si présent. Import CSV : ref existante régénérée.
- **genRecId** réception : `R` + AAMMJJ + `-` + 4 chiffres (ex. `R260722-0001`).
- IDs internes : `id-<base36(ts)>-<random>`.
- **Concurrence/révisions** : verrou optimiste sur le **document entier** (`baseRev===doc.rev` sinon 409 → le client adopte le doc serveur). Push débounce 800 ms ; pull toutes les 12 s ; adoption bloquée si `formBusy()` ; `sendBeacon` au déchargement. Écriture serveur atomique (.tmp+rename), backup quotidien 30 j.
- **Statut dormant** article : exclu des alertes/à-commander ; propagé WMS↔Appro par le serveur (`syncStatuts`) par `ref` normalisée, `statutTs` départage.
- Dates ISO 8601 en stockage, affichage fr-FR ; filtres en heure locale.
- **Stock à une date** : rejeu du journal trié (IN+, OUT−, ADJUST=absolu). Dépend de l'intégrité du journal.
- Champs obligatoires : article→désignation ; emplacement→code (unique, MAJ) ; catégorie→nom ; cabine→chantier(6)+numero+emplacement ; mouvement→emplacement+q>0.
- Quantités : décimaux autorisés ; `unite` texte libre non contrôlée. Staging `__ARANGER__` exclu de tous les sélecteurs. Anti-doublon article : Levenshtein sur la désignation (≥0,80 garde, ≥0,55 suggestions).

## 7. Points de vigilance pour une transposition fidèle (Django + API)

1. **Le stock n'est jamais stocké : il est dérivé du journal des mouvements.** L'API doit garantir stock = somme des mouvements par (article, emplacement).
2. **ADJUST = valeur absolue** (reset de la ligne), pas un delta.
3. **Concurrence : verrou optimiste global** (pas par entité) → décider comment reproduire le 409/adoption et le `formBusy` en Django/API.
4. **Transfert = 2 mouvements OUT+IN** (pas de type dédié) → 2 lignes dans l'historique.
5. **Contre-passation** = mouvement inverse + flags `annule`/`annulation`, impossible sur ADJUST.
6. **Rangement partiel** (q>staging) crée du stock net (voulu).
7. **Réception ≠ mouvement** : 2 enregistrements créés ensemble à l'entrée manuelle seulement ; numérotation `R+AAMMJJ+séq`.
8. **Deux notions d'état de cabine** (`etat` métier vs `statut='sortie'` irréversible) — ne pas fusionner.
9. **Réf. orphelines assumées** : FK `SET_NULL`/nullable, pas `CASCADE`.
10. **Droits sur 3 couches** parfois incohérentes (ex. sortie cabine gardée par `mvt`) — choisir la couche qui fait foi tout en reproduisant les gardes observables.
11. **`ref` = clé fonctionnelle inter-applis** (normalisée MAJ) — unicité structurante.
12. Numérotation basée sur `.length+1` (fragile après suppressions) → « incrémente jusqu'à unicité ».
13. Quantités décimales, unité non contrôlée — ne pas imposer d'entiers.
14. Conventions QR `ART:` / `LOC:` / `REC:` (+ EAN) à conserver pour compatibilité des étiquettes déjà imprimées.
