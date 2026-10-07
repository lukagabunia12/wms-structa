-- ============================================================================
--  WMS STRUCTA - REQUETES PRETES A L'EMPLOI
--  Ouvrir ce fichier dans DB Browser for SQLite (onglet "Execute SQL"),
--  ou dans pgAdmin (Query Tool) apres la bascule PostgreSQL.
--
--  Selectionner une requete, puis F5 (DB Browser) ou F5 (pgAdmin) pour
--  l'executer. Rien ne s'execute tant que vous ne le demandez pas.
--
--  Les requetes des sections 1 a 4 sont en LECTURE SEULE : elles ne
--  modifient rien, on peut les lancer sans crainte, meme en production.
--  La section 5 ecrit : lire son avertissement AVANT de s'en servir.
--
--  Les sections 1, 2, 3 (jusqu'a 3.4) et 4 fonctionnent telles quelles sur
--  SQLite ET sur PostgreSQL. Les requetes 3.5 a 3.10 utilisent to_char et
--  date_trunc : elles sont ecrites pour PostgreSQL, la base d'exploitation.
--  Les tests booleens sont ecrits "WHERE e.actif" plutot que "actif = 1",
--  parce que le second echoue sur PostgreSQL en "operator does not exist:
--  boolean = integer". Sur SQLite les dates sont du texte
--  "AAAA-MM-JJ hh:mm:ss", sur PostgreSQL de vraies dates -- les
--  comparaisons de la requete 4.2 fonctionnent dans les deux cas.
-- ============================================================================


-- ============================================================================
--  1. REGARDER - ETAT GENERAL
-- ============================================================================

-- 1.1  Combien de lignes dans chaque table ?
--      LA requete a lancer en premier, et celle qui repond a "suis-je bien
--      sur la bonne base ?". Deux bases peuvent repondre, une seule contient
--      le travail du jour.
SELECT 'Emplacements'      AS table_, COUNT(*) AS lignes FROM wms_emplacement
UNION ALL SELECT 'Places condamnees', COUNT(*) FROM wms_placecondamnee
UNION ALL SELECT 'Zones',             COUNT(*) FROM wms_zone
UNION ALL SELECT 'Cabines',           COUNT(*) FROM wms_cabine
UNION ALL SELECT 'Positions',         COUNT(*) FROM wms_occupation
UNION ALL SELECT 'Journal cabines',   COUNT(*) FROM wms_mouvementcabine
UNION ALL SELECT 'Modeles regles',    COUNT(*) FROM wms_modelecabine
UNION ALL SELECT 'Fichier production',COUNT(*) FROM wms_cabineattendue
UNION ALL SELECT 'Codes MP (base)',   COUNT(*) FROM wms_articlemp
UNION ALL SELECT 'Stock MP (lignes)', COUNT(*) FROM wms_stockmp
UNION ALL SELECT 'Journal MP',        COUNT(*) FROM wms_mouvementmp
UNION ALL SELECT 'Codes acceptes',    COUNT(*) FROM wms_emplacement_codes_acceptes
UNION ALL SELECT 'Comptes',           COUNT(*) FROM wms_utilisateur;


-- 1.2  Les comptes et leurs droits : une colonne par case de la fiche.
--      Un administrateur (role 'admin') ou un superutilisateur a TOUS les
--      droits, quelles que soient les cases : elles peuvent etre a 0 sur son
--      compte. Un compte 'lecture' n'en a AUCUN, meme coche.
SELECT username, nom, role, is_superuser, is_active,
       droit_cab_ranger, droit_cab_statut, droit_cab_envoyer, droit_cab_corriger,
       droit_production, droit_hors_fichier,
       droit_mp, droit_mp_seuils,
       droit_empl_service, droit_empl_regler, droit_empl_creer, droit_modeles
FROM wms_utilisateur
ORDER BY username;


-- 1.3  Les emplacements, avec leur zone cabine et leur position dans le rack.
--      "usage" dit ce qu'ils rangent : cabines, carton ou vitrage.
SELECT e.code, e.usage, e.zone, z.nom AS zone_cabine, e.rack, e.colonne, e.niveau,
       e.staging, e.actif, e.description
FROM wms_emplacement e
LEFT JOIN wms_zone z ON z.id = e.zone_cabine_id
ORDER BY e.rack, e.colonne, e.niveau, e.code;


-- 1.4  Les racks : combien de cellules, quels niveaux.
SELECT rack,
       COUNT(*)            AS emplacements,
       COUNT(DISTINCT colonne) AS colonnes,
       MIN(niveau)         AS niveau_bas,
       MAX(niveau)         AS niveau_haut
FROM wms_emplacement
WHERE rack IS NOT NULL AND rack <> ''
GROUP BY rack
ORDER BY rack;


-- 1.5  Qui peut creer et supprimer des emplacements et des racks ?
--      Les roles comptent : un administrateur le peut sans la case, un
--      compte en lecture seule ne le peut pas meme avec. Pour une autre
--      case, remplacer droit_empl_creer par son nom (requete 1.2).
SELECT username, nom, role
FROM wms_utilisateur
WHERE is_active
  AND (is_superuser OR role = 'admin' OR (role = 'operateur' AND droit_empl_creer))
ORDER BY username;


-- ============================================================================
--  2. REGARDER - EMPLACEMENTS LIBRES OU HORS SERVICE
-- ============================================================================

-- 2.1  Emplacements vides (candidats au rangement).
--      Vides = en service, et sans cabine presente. Une cabine envoyee ne
--      compte pas : elle a quitte l'entrepot.
SELECT e.code, e.rack, e.colonne, e.niveau, e.mode_places
FROM wms_emplacement e
WHERE e.actif
  AND NOT EXISTS (SELECT 1
                  FROM wms_occupation o
                  JOIN wms_cabine c ON c.id = o.cabine_id
                  WHERE o.emplacement_id = e.id AND c.statut <> 'envoye')
ORDER BY e.rack, e.colonne, e.niveau, e.code;


-- 2.2  Ce qui est hors service, et pourquoi : les emplacements desactives,
--      puis les places condamnees (gauche ou droite).
SELECT e.code, 'emplacement' AS quoi, e.motif_inactif AS motif, e.actif_le AS depuis
FROM wms_emplacement e
WHERE NOT e.actif
UNION ALL
SELECT e.code, 'place ' || p.place, p.motif, p.cree_le
FROM wms_placecondamnee p
JOIN wms_emplacement e ON e.id = p.emplacement_id
ORDER BY 1, 2;


-- ============================================================================
--  3. REGARDER - CABINES
-- ============================================================================

-- 3.1  Les cabines presentes, avec leur emplacement et leur statut.
--      Statuts : libre (Conforme), quarantaine. La position est dans
--      wms_occupation : une cabine posee a deux endroits sort sur deux lignes,
--      une cabine pas encore rangee sort sans emplacement.
SELECT c.numero, c.chantier, c.type_cabine, c.statut, c.modele,
       e.code AS emplacement, o.place, c.client, c.revendeur, c.date
FROM wms_cabine c
LEFT JOIN wms_occupation o  ON o.cabine_id = c.id AND o.emplacement_id IS NOT NULL
LEFT JOIN wms_emplacement e ON e.id = o.emplacement_id
WHERE c.statut <> 'envoye'
ORDER BY c.statut, c.chantier, c.numero;


-- 3.2  Combien de cabines par chantier, et combien deja envoyees.
SELECT chantier,
       COUNT(*)                                            AS total,
       SUM(CASE WHEN statut = 'envoye' THEN 1 ELSE 0 END)  AS envoyees,
       SUM(CASE WHEN statut <> 'envoye' THEN 1 ELSE 0 END) AS restantes
FROM wms_cabine
WHERE chantier <> ''
GROUP BY chantier
ORDER BY restantes DESC, chantier;


-- 3.3  Le journal complet d'une cabine.
--      Remplacer le numero ci-dessous par celui qui vous interesse.
--      Ce journal survit a la suppression de la cabine : c'est lui qui
--      explique une disparition.
SELECT date, type, statut_avant, statut_apres, depuis, vers,
       utilisateur_nom, note
FROM wms_mouvementcabine
WHERE cabine_numero = '00_00_00'
ORDER BY date;


-- 3.4  Cabines en quarantaine depuis le plus longtemps.
SELECT numero, chantier, statut, statut_date, modele, client
FROM wms_cabine
WHERE statut = 'quarantaine'
ORDER BY statut_date;




-- ============================================================================
--  3 bis. LES MOUVEMENTS DES CABINES - LE JOURNAL
--
--  Ce journal est la verite du WMS : les listes, les positions et les
--  compteurs sont recalcules depuis lui. Chaque ligne dit qui a fait quoi,
--  quand, et sur quelle cabine. Rien ne s'y efface.
--
--  Les huit types d'evenement, et leur nom a l'ecran :
--    creation    -> Creation                rangement -> Rangement
--    transfert   -> Transfert               retrait   -> Sortie d'emplacement
--    statut      -> Changement de statut    envoi     -> Envoi
--    correction  -> Correction de fiche     suppression -> Suppression
--
--  Les trois statuts : libre -> Conforme, quarantaine -> En quarantaine,
--  envoye -> Envoyee.
--
--  Les requetes 3.5 a 3.10 ont ete executees sur un vrai PostgreSQL. Elles
--  n'utilisent que du SQL standard (to_char, date_trunc, interval) : rien
--  qui depende de la version du serveur.
-- ============================================================================

-- 3.5  LES 100 DERNIERS MOUVEMENTS, en francais.
--      LA requete a lancer pour "qu'est-ce qui s'est passe ?". Les colonnes
--      vides ne sont pas des trous : un rangement n'a pas de statut, un
--      changement de statut n'a pas d'emplacement.
SELECT to_char(m.date, 'DD/MM/YYYY HH24:MI')        AS "Quand",
       m.cabine_numero                              AS "Cabine",
       CASE m.type
         WHEN 'creation'    THEN 'Creation'
         WHEN 'rangement'   THEN 'Rangement'
         WHEN 'transfert'   THEN 'Transfert'
         WHEN 'retrait'     THEN 'Sortie d''emplacement'
         WHEN 'statut'      THEN 'Changement de statut'
         WHEN 'envoi'       THEN 'Envoi'
         WHEN 'correction'  THEN 'Correction de fiche'
         WHEN 'suppression' THEN 'Suppression de la cabine'
         ELSE m.type END                            AS "Evenement",
       NULLIF(m.depuis, '')                         AS "Depuis",
       NULLIF(m.vers, '')                           AS "Vers",
       CASE m.statut_apres
         WHEN 'libre'       THEN 'Conforme'
         WHEN 'quarantaine' THEN 'En quarantaine'
         WHEN 'envoye'      THEN 'Envoyee' END      AS "Nouveau statut",
       COALESCE(NULLIF(m.utilisateur_nom, ''), 'compte supprime') AS "Par qui",
       NULLIF(m.chantier, '')                       AS "Chantier",
       NULLIF(m.note, '')                           AS "Note"
FROM wms_mouvementcabine m
ORDER BY m.date DESC
LIMIT 100;


-- 3.6  CE QUI S'EST PASSE AUJOURD'HUI, dans l'ordre.
--      Pour la reunion du matin, ou pour verifier qu'une equipe a bien
--      saisi sa journee. Remplacer 'day' par 'week' pour la semaine.
SELECT to_char(date, 'HH24:MI')                     AS "Heure",
       cabine_numero                                AS "Cabine",
       CASE type
         WHEN 'creation'    THEN 'Creation'
         WHEN 'rangement'   THEN 'Rangement'
         WHEN 'transfert'   THEN 'Transfert'
         WHEN 'retrait'     THEN 'Sortie d''emplacement'
         WHEN 'statut'      THEN 'Changement de statut'
         WHEN 'envoi'       THEN 'Envoi'
         WHEN 'correction'  THEN 'Correction de fiche'
         WHEN 'suppression' THEN 'Suppression de la cabine'
         ELSE type END                              AS "Evenement",
       NULLIF(vers, '')                             AS "Vers",
       COALESCE(NULLIF(utilisateur_nom, ''), 'compte supprime') AS "Par qui",
       NULLIF(note, '')                             AS "Note"
FROM wms_mouvementcabine
WHERE date >= date_trunc('day', now())
ORDER BY date;


-- 3.7  COMBIEN DE MOUVEMENTS PAR TYPE, sur sept jours.
--      Dit d'un coup d'oeil ce que les gens font vraiment de l'application.
--      Beaucoup de 'correction' ou de 'transfert' est un signal : quelque
--      chose se saisit mal du premier coup.
SELECT CASE type
         WHEN 'creation'    THEN 'Creation'
         WHEN 'rangement'   THEN 'Rangement'
         WHEN 'transfert'   THEN 'Transfert'
         WHEN 'retrait'     THEN 'Sortie d''emplacement'
         WHEN 'statut'      THEN 'Changement de statut'
         WHEN 'envoi'       THEN 'Envoi'
         WHEN 'correction'  THEN 'Correction de fiche'
         WHEN 'suppression' THEN 'Suppression de la cabine'
         ELSE type END                              AS "Evenement",
       COUNT(*)                                     AS "Combien"
FROM wms_mouvementcabine
WHERE date >= now() - interval '7 days'
GROUP BY 1
ORDER BY 2 DESC;


-- 3.8  QUI A FAIT QUOI, sur sept jours.
--      Pendant la campagne de test, tout le monde partage le compte TEST :
--      cette requete ne separe alors pas les personnes. Elle reprend son
--      sens le jour ou chacun a son compte.
SELECT COALESCE(NULLIF(utilisateur_nom, ''), 'compte supprime') AS "Par qui",
       COUNT(*)                                     AS "Mouvements",
       COUNT(DISTINCT cabine_numero)                AS "Cabines touchees",
       to_char(MIN(date), 'DD/MM HH24:MI')          AS "Premier",
       to_char(MAX(date), 'DD/MM HH24:MI')          AS "Dernier"
FROM wms_mouvementcabine
WHERE date >= now() - interval '7 days'
GROUP BY 1
ORDER BY 2 DESC;


-- 3.9  LE JOURNAL D'UNE CABINE, du premier au dernier evenement.
--      Remplacer le numero. C'est la vue qui explique une position
--      surprenante : on lit l'histoire dans l'ordre ou elle s'est ecrite.
SELECT to_char(date, 'DD/MM/YYYY HH24:MI')          AS "Quand",
       type                                         AS "Type",
       NULLIF(depuis, '')                           AS "Depuis",
       NULLIF(vers, '')                             AS "Vers",
       NULLIF(statut_avant, '')                     AS "Statut avant",
       NULLIF(statut_apres, '')                     AS "Statut apres",
       COALESCE(NULLIF(utilisateur_nom, ''), 'compte supprime') AS "Par qui",
       NULLIF(note, '')                             AS "Note"
FROM wms_mouvementcabine
WHERE cabine_numero = '00_00_00'
ORDER BY date;


-- 3.10 LES CABINES DONT LE JOURNAL PARLE ET QUI N'EXISTENT PLUS.
--      Une cabine supprimee laisse son journal derriere elle : c'est lui qui
--      explique une disparition, et cette requete les liste toutes.
SELECT m.cabine_numero                              AS "Cabine disparue",
       COUNT(*)                                     AS "Evenements",
       to_char(MAX(m.date), 'DD/MM/YYYY HH24:MI')   AS "Dernier evenement"
FROM wms_mouvementcabine m
LEFT JOIN wms_cabine c ON c.numero = m.cabine_numero
WHERE c.id IS NULL
GROUP BY m.cabine_numero
ORDER BY MAX(m.date) DESC;


-- ============================================================================
--  3 ter. MATIERES PREMIERES - VITRAGES ET CARTONS
--
--  Quatre tables : wms_articlemp (la base des codes, avec leur seuil
--  d'alerte -- colonne seuil_reappro), wms_stockmp (ce qui est pose, place
--  par place : G, M, D), wms_mouvementmp (le journal des entrees, des
--  sorties et des changements d'emplacement) et wms_emplacement_codes_acceptes
--  (les emplacements reserves a certains codes). Le stock ne se corrige pas
--  ici : une entree, une sortie ou un changement d'emplacement dans le WMS,
--  qui l'ecrit au journal.
-- ============================================================================

-- 3.11 Le stock MP par code : combien, et sur combien de positions.
SELECT a.famille, a.code, a.designation, a.ancienne_generation,
       SUM(s.quantite)  AS en_stock,
       COUNT(s.id)      AS positions,
       a.seuil_reappro
FROM wms_articlemp a
JOIN wms_stockmp s ON s.article_id = a.id
GROUP BY a.id, a.famille, a.code, a.designation, a.ancienne_generation, a.seuil_reappro
ORDER BY a.famille, a.code;


-- 3.12 Le stock MP place par place : l'inventaire a recompter devant le rack.
SELECT e.rack, e.code AS emplacement, s.place, a.code, s.quantite,
       s.modifie_le AS dernier_mouvement
FROM wms_stockmp s
JOIN wms_emplacement e ON e.id = s.emplacement_id
JOIN wms_articlemp   a ON a.id = s.article_id
ORDER BY e.rack, e.code,
         CASE s.place WHEN 'G' THEN 1 WHEN 'M' THEN 2 ELSE 3 END,  -- gauche, milieu, droite
         a.code;


-- 3.13 Le journal MP d'un code. Remplacer le code ci-dessous.
--      Pour un changement d'emplacement (type 'transfert'), "origine" est la
--      position de depart et "reste_origine" ce qui y restait ; "position" et
--      "reste", l'arrivee.
SELECT date, type, quantite, origine, reste_origine, position, reste,
       utilisateur_nom, note
FROM wms_mouvementmp
WHERE article_code = 'VITR.445X2072.BP'
ORDER BY date DESC;


-- 3.14 Les codes a recommander : sous leur seuil d'alerte -- ceux que
--      signale la cloche (anciennes generations exclues : on les ecoule, on ne
--      les recommande pas). Le seuil se franchit EN DESSOUS : 50 en stock pour
--      un seuil de 50 ne sonne pas.
SELECT a.code, a.fournisseur, a.seuil_reappro,
       COALESCE(SUM(s.quantite), 0) AS en_stock
FROM wms_articlemp a
LEFT JOIN wms_stockmp s ON s.article_id = a.id
WHERE a.seuil_reappro IS NOT NULL AND a.actif AND NOT a.ancienne_generation
GROUP BY a.id, a.code, a.fournisseur, a.seuil_reappro
HAVING COALESCE(SUM(s.quantite), 0) < a.seuil_reappro
ORDER BY a.code;


-- 3.15 Les emplacements reserves a certains codes. Un emplacement MP absent
--      de cette liste accepte tous les codes de sa famille.
SELECT e.code AS emplacement, e.usage, a.code AS code_accepte
FROM wms_emplacement_codes_acceptes r
JOIN wms_emplacement e ON e.id = r.emplacement_id
JOIN wms_articlemp   a ON a.id = r.articlemp_id
ORDER BY e.code, a.code;


-- 3.16 Les changements d'emplacement, du plus recent au plus ancien : d'ou,
--      vers ou, combien. Ni une entree ni une sortie : ils ne comptent pas
--      dans la consommation (type 'sortie').
SELECT date, article_code, quantite,
       origine       AS depuis,   reste_origine AS reste_au_depart,
       position      AS vers,     reste         AS reste_a_l_arrivee,
       utilisateur_nom
FROM wms_mouvementmp
WHERE type = 'transfert'
ORDER BY date DESC;


-- ============================================================================
--  4. EXTRAIRE - LISTES POUR EXCEL
--
--  Dans DB Browser : executer, puis clic droit sur le resultat ->
--  "Copy" (colle directement dans Excel), ou menu Fichier -> Export ->
--  "Table(s) as CSV file" pour un fichier.
--  Dans pgAdmin : bouton "Download as CSV" en haut a droite du resultat.
--
--  IMPORTANT pour Excel : ouvrir le CSV via Donnees -> "A partir d'un
--  fichier texte/CSV" en choisissant UTF-8, sinon les accents sont casses.
-- ============================================================================

-- 4.1  Inventaire des cabines en stock, une ligne par emplacement occupe.
--      L'ecran « Parc » sait aussi le telecharger (bouton « Telecharger
--      l'inventaire »).
SELECT c.numero       AS "Cabine",
       c.chantier     AS "Chantier",
       c.modele       AS "Modele",
       c.statut       AS "Statut",
       e.code         AS "Emplacement",
       o.place        AS "Place",
       c.client       AS "Client",
       c.revendeur    AS "Revendeur",
       c.date         AS "Entree le"
FROM wms_cabine c
LEFT JOIN wms_occupation o  ON o.cabine_id = c.id AND o.emplacement_id IS NOT NULL
LEFT JOIN wms_emplacement e ON e.id = o.emplacement_id
WHERE c.statut <> 'envoye'
ORDER BY e.code, c.numero;


-- 4.2  Le journal des cabines sur une periode.
--      Adapter les deux dates ci-dessous.
SELECT m.date AS "Date", m.cabine_numero AS "Cabine", m.chantier AS "Chantier",
       m.type AS "Type", m.depuis AS "Depuis", m.vers AS "Vers",
       m.statut_apres AS "Statut", m.utilisateur_nom AS "Par qui", m.note AS "Note"
FROM wms_mouvementcabine m
WHERE m.date >= '2026-01-01' AND m.date < '2027-01-01'
ORDER BY m.date;


-- 4.3  Toutes les cabines d'un chantier.
SELECT c.numero AS "Cabine", c.chantier AS "Chantier",
       c.type_cabine AS "Type", c.statut AS "Statut",
       c.modele AS "Modele", e.code AS "Emplacement", o.place AS "Place",
       c.client AS "Client", c.revendeur AS "Revendeur",
       c.tissu_bk AS "Tissu BK", c.tissu_aq AS "Tissu AQ",
       c.fond_cabine AS "Fond", c.envoi_date AS "Date d'envoi"
FROM wms_cabine c
LEFT JOIN wms_occupation o  ON o.cabine_id = c.id AND o.emplacement_id IS NOT NULL
LEFT JOIN wms_emplacement e ON e.id = o.emplacement_id
WHERE c.chantier = '000000'
ORDER BY c.numero;


-- 4.4  Etiquettes : la liste des codes d'emplacement d'un rack,
--      dans l'ordre d'impression (niveau haut en premier).
SELECT code, rack, colonne, niveau
FROM wms_emplacement
WHERE rack = 'AC'
ORDER BY colonne, niveau DESC;


-- ============================================================================
--  5. CORRIGER A LA MAIN  ---  A LIRE AVANT D'ECRIRE
-- ============================================================================
--
--  AVANT TOUTE ECRITURE :
--    1. ARRETER le WMS (fermer la fenetre du serveur). Une ecriture pendant
--       que l'application tourne peut la bloquer ou etre ecrasee.
--    2. SAUVEGARDER : copier db.sqlite3 ailleurs, sous un autre nom.
--    3. Dans DB Browser, rien n'est ecrit tant que vous n'avez pas clique
--       "Write Changes" (Ecrire les modifications). "Revert Changes" annule
--       tout. C'est votre filet : ne cliquez "Write Changes" qu'apres avoir
--       relu le resultat.
--
--  CE QU'ON PEUT CORRIGER A LA MAIN SANS RISQUE
--  Des champs purement descriptifs, sur lesquels aucune regle logistique ne
--  s'appuie :
--    wms_cabine      : modele, client, revendeur, tissu_bk, tissu_aq, fond_cabine
--    wms_emplacement : description
--    wms_zone        : nom, description, ordre
--
--  CE QU'IL NE FAUT PAS TOUCHER A LA MAIN
--    wms_occupation     -> la position des cabines. La changer ici ne laisse
--                          aucune trace au journal : passer par le WMS
--                          (ranger, deplacer, envoyer), qui l'ecrit.
--    wms_mouvementcabine-> le journal des cabines. On n'efface pas une ligne
--                          d'historique ; l'application elle-meme s'interdit
--                          de le modifier.
--    wms_stockmp        -> le stock des vitrages et des cartons. Le corriger
--                          ici fait mentir le journal MP : faire une entree ou
--                          une sortie dans le WMS (motif "Inventaire").
--    wms_mouvementmp    -> le journal MP. Meme regle que celui des cabines.
--    wms_emplacement_codes_acceptes -> les codes qu'accepte un emplacement MP.
--                          Se reglent dans le WMS, qui verifie la famille :
--                          un vitrage accepte sur un emplacement de cartons
--                          ici le fermerait a tout.
--    wms_utilisateur.password -> mot de passe chiffre. Le remplacer par du
--                          texte rend le compte inutilisable. Passer par
--                          /admin/ ou par : manage.py changepassword
--
--  Exemple d'une correction legitime : un client mal saisi.
--  Toujours REGARDER d'abord ce qu'on s'apprete a changer :
--
--     SELECT id, numero, client FROM wms_cabine WHERE numero = '00_00_00';
--
--  puis, seulement si la ligne est la bonne :
--
--     UPDATE wms_cabine SET client = 'Le bon client' WHERE numero = '00_00_00';
--
--  Toujours un WHERE. Un UPDATE sans WHERE modifie TOUTES les lignes de la
--  table -- c'est l'accident classique, et il est irreversible sans
--  sauvegarde.
--
--  Verifier apres coup :
--     SELECT id, numero, client FROM wms_cabine WHERE numero = '00_00_00';
-- ============================================================================
