/* Tests de l'interface, sans navigateur.

   `verifier_interface.js` contrôle la structure — les écrans existent, les
   destinations sont joignables. Il ne dit rien de ce que le code FAIT. Ces
   tests-ci prennent des fonctions pures d'`app.js`, les exécutent et
   comparent le résultat : c'est la seule chose qui attrape une régression de
   comportement dans 4 900 lignes servies sans outil de build.

   Node seul suffit : aucune dépendance, rien à installer, la CI le lance tel
   quel. Les fonctions à tester sont extraites du fichier réel, jamais copiées
   — un test qui vit sur une copie ne teste plus rien au bout d'un mois.

   Usage : node outils/tester_interface.js     (code 1 si un test échoue)
*/
const fs = require('fs');
const path = require('path');

const APP = path.join(__dirname, '..', 'wms', 'static', 'app', 'app.js');
const source = fs.readFileSync(APP, 'utf8');

/** Découpe le fichier entre deux repères et l'évalue dans une portée à part. */
function extraire(debut, fin, noms) {
  const i = source.indexOf(debut);
  const j = source.indexOf(fin, i);
  if (i < 0 || j < 0) {
    throw new Error(`Repère introuvable dans app.js : « ${i < 0 ? debut : fin} ». `
      + 'Le code a été réorganisé : mettez ces repères à jour plutôt que de retirer le test.');
  }
  return eval(`(function(){${source.slice(i, j)}; return {${noms}};})()`);
}

let echecs = 0;
function verifier(nom, obtenu, attendu) {
  const bon = String(obtenu) === String(attendu);
  if (!bon) echecs++;
  console.log(`${bon ? '  ok  ' : '  ECHEC'} ${nom}`
    + (bon ? '' : `\n         obtenu « ${obtenu} », attendu « ${attendu} »`));
}

/* --- Le masque des numéros de cabine ---------------------------------------
   Un n° de cabine s'écrit XX_XX_XX. Sur un téléphone, taper un tiret bas
   demande de changer de clavier trois fois : le masque les pose tout seuls et
   le champ n'accepte que des chiffres. */
const { masquerNumero } = extraire('function formaterNumero', 'const debounce =', 'masquerNumero');

class ChampFactice {
  constructor() { this.value = ''; this.dataset = {}; this.attrs = {}; this.ecouteurs = []; this.selectionStart = 0; }
  setAttribute(cle, valeur) { this.attrs[cle] = valeur; }
  addEventListener(_, fn) { this.ecouteurs.push(fn); }
  dispatchEvent() { this.ecouteurs.forEach(fn => fn()); }
  setSelectionRange(debut) { this.selectionStart = debut; }
  taper(texte) { this.value += texte; this.selectionStart = this.value.length; this.dispatchEvent(); return this.value; }
}

console.log('Masque des numéros de cabine');
let champ = masquerNumero(new ChampFactice());
verifier('frappe chiffre par chiffre', ['2', '6', '0', '3', '4', '7'].map(c => champ.taper(c)).pop(), '26_03_47');
verifier('pavé numérique demandé', champ.attrs.inputmode, 'numeric');

const cas = [
  ['collé d’un bloc', '260347', '26_03_47'],
  ['déjà formaté', '26_03_47', '26_03_47'],
  ['lettres ignorées', '26aa03zz47', '26_03_47'],
  // La règle a changé : le dernier groupe va de 1 à 3 chiffres. Le fichier de
  // production compte des semaines à plus de 99 cabines (« 25_49_400 »), que le
  // masque tronquait silencieusement en un numéro valide — celui d'une AUTRE
  // cabine. Le septième chiffre est donc accepté, le huitième toujours refusé.
  ['septième chiffre accepté', '2603479', '26_03_479'],
  ['huitième chiffre refusé', '26034799', '26_03_479'],
  ['trois chiffres du fichier de production', '2549400', '25_49_400'],
  ['saisie encore partielle', '2603', '26_03'],
];
for (const [nom, saisi, attendu] of cas) {
  verifier(nom, masquerNumero(new ChampFactice()).taper(saisi), attendu);
}

/* --- Le chantier et son lot -------------------------------------------------
   Un chantier s'écrit « 251213 », et se décline en lots : « 251213-1 ». Il se
   saisit en deux champs — un pavé numérique n'a pas de tiret — et le champ de
   gauche accepte aussi un numéro collé d'un bloc. La première version gardait
   les chiffres et coupait à six : « 251213-1 » collé devenait « 251213 », le
   chantier voisin, sans un mot. C'est cette troncature que ces tests ferment. */
const { lireChantierSaisi, motifChantier } = (() => {
  const i = source.indexOf('function motifChantier()');
  const j = source.indexOf('const typeDispenseDeChantier', i);
  if (i < 0 || j < 0) {
    throw new Error('Repères du chantier introuvables dans app.js : le code a été '
      + 'réorganisé, mettez-les à jour plutôt que de retirer le test.');
  }
  // `lireChantierSaisi` lit deux champs par `$(...)` : on lui en fournit deux.
  const valeurs = { '#eChantier': '', '#eLot': '' };
  const $ = (id) => ({ get value() { return valeurs[id]; } });
  const REFS_CABINE = {};
  const fn = eval(`(function(){${source.slice(i, j)};
    return { lireChantierSaisi, motifChantier, valeurs };})()`);
  return { lireChantierSaisi: (num, lot) => {
             valeurs['#eChantier'] = num; valeurs['#eLot'] = lot;
             return fn.lireChantierSaisi();
           },
           motifChantier: fn.motifChantier };
})();

console.log('\nChantier et lot');
const casChantier = [
  ['six chiffres seuls', '251213', '', '251213'],
  ['chantier + lot dans les deux champs', '251213', '1', '251213-1'],
  ['lot à deux chiffres', '251213', '12', '251213-12'],
  ['lot zéro ignoré', '251213', '0', '251213'],
  ['zéro de tête du lot retiré', '251213', '01', '251213-1'],
  ['collé d’un bloc avec tiret', '251213-1', '', '251213-1'],
  ['collé avec une espace', '251213 2', '', '251213-2'],
  ['collé avec une barre', '251213/3', '', '251213-3'],
  ['le collage gagne sur le champ Lot', '251213-4', '9', '251213-4'],
  ['champ vide', '', '1', ''],
  // Ce qui n'est ni l'une ni l'autre forme ressort TEL QUEL : c'est le contrôle
  // de forme qui le refuse en le citant, jamais une troncature muette.
  ['forme inconnue rendue intacte', 'AF-3164', '', 'AF-3164'],
  ['sept chiffres rendus intacts', '2512130', '', '2512130'],
];
for (const [nom, num, lot, attendu] of casChantier) {
  verifier(nom, lireChantierSaisi(num, lot), attendu);
}

const motif = motifChantier();
const casMotif = [
  ['251213', true], ['251213-1', true], ['251213-12', true],
  ['251213-0', false], ['251213-123', false], ['25121', false],
  ['2512130', false], ['AF-3164', false], ['251213 -1', false], ['', false],
];
for (const [valeur, attendu] of casMotif) {
  verifier(`motif : ${valeur || '(vide)'}`, motif.test(valeur), attendu);
}

/* --- Le code imprimé sur l'étiquette ------------------------------------------
   Il doit prendre exactement la largeur du QR : c'est lui qu'on lit de loin. Le
   corps se calcule sur la longueur du code, plafonné pour qu'un code court ne
   devienne pas plus haut que le QR. */
const { corpsDuCode, codeEnSvg } = (() => {
  const i = source.indexOf('const CHASSE_GRAS');
  const j = source.indexOf('async function imprimerBandes', i);
  if (i < 0 || j < 0) {
    throw new Error('Repères des étiquettes introuvables dans app.js : le code a été '
      + 'réorganisé, mettez-les à jour plutôt que de retirer le test.');
  }
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  return eval(`(function(){${source.slice(i, j)}; return { corpsDuCode, codeEnSvg };})()`);
})();

console.log('\nCode imprimé sur l’étiquette');
verifier('« Y550 » remplit un QR de 40 mm', corpsDuCode('Y550', 40).toFixed(2), '17.13');
verifier('un code court plafonne à la moitié du côté', corpsDuCode('A1', 40), 20);
verifier('un code long s’écrit moins haut', corpsDuCode('AC-1557', 40) < corpsDuCode('AC551', 40), true);
verifier('minuscules comptées comme capitales', corpsDuCode('ac551', 40), corpsDuCode('AC551', 40));
const svgAjuste = codeEnSvg('Y550', 40, 17.13, true);
verifier('largeur imposée : celle du QR', /textLength="40" lengthAdjust="spacingAndGlyphs"/.test(svgAjuste)
  && /width="40mm"/.test(svgAjuste), true);
const svgLibre = codeEnSvg('<b>', 40, 10, false);
verifier('code resserré : centré, sans largeur imposée', /text-anchor="middle"/.test(svgLibre)
  && !/textLength/.test(svgLibre), true);
verifier('code échappé', /&lt;b&gt;/.test(svgLibre) && !/<b>/.test(svgLibre), true);

/* --- Ce que le scan annonce au-dessus du code lu ------------------------------ */
const { natureDuCode } = (() => {
  const motif = source.match(/const MOTIF_NUMERO_CABINE = [^;]+;/);
  const i = source.indexOf('function natureDuCode');
  const j = source.indexOf('/** Traduit l', i);
  if (!motif || i < 0 || j < 0) {
    throw new Error('Repères du scan introuvables dans app.js : le code a été '
      + 'réorganisé, mettez-les à jour plutôt que de retirer le test.');
  }
  return eval(`(function(){${motif[0]} ${source.slice(i, j)}; return { natureDuCode };})()`);
})();

console.log('\nCode lu à la caméra');
for (const [texte, attendu] of [['LOC:Y550', 'Emplacement lu'], ['loc:ac551', 'Emplacement lu'],
                                ['CAB:26_03_47', 'Cabine lue'], ['26_03_479', 'Cabine lue'],
                                ['Y550', 'Code lu']]) {
  verifier(`${texte} → ${attendu}`, natureDuCode(texte), attendu);
}

/* --- Le raccourci sur l'écran d'accueil ----------------------------------------
   Le bon geste selon l'appareil : un bouton quand Chrome sait installer, les
   trois gestes sur iPhone ou Android, et rien sur un ordinateur ni une fois
   ouvert depuis l'icône. */
const { plateformeRaccourci } = extraire('function plateformeRaccourci', 'const ETAPES_RACCOURCI',
                                         'plateformeRaccourci');
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1';
const IPAD = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15';
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36';
const PC = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';

console.log('\nRaccourci sur l’écran d’accueil');
for (const [nom, cas, attendu] of [
  ['iPhone dans Safari', { ua: IPHONE }, 'ios'],
  ['iPad (se dit Mac, mais tactile)', { ua: IPAD, tactile: true }, 'ios'],
  ['vrai Mac : rien', { ua: IPAD, tactile: false }, ''],
  ['Android sans invitation de Chrome', { ua: ANDROID }, 'android'],
  ['Android, Chrome prêt à installer', { ua: ANDROID, invitation: true }, 'invitation'],
  ['ordinateur : rien', { ua: PC }, ''],
  ['ouvert depuis l’icône : rien à proposer', { ua: ANDROID, invitation: true, installe: true }, 'installe'],
]) {
  verifier(nom, plateformeRaccourci(cas), attendu);
}

/* --- Matières premières ---------------------------------------------------------
   Ce qu'on tape au poste ne ressemble jamais tout à fait au code de la base : la
   clé de comparaison est la même des deux côtés (`normaliser_code_mp`). Et une
   quantité se compte en pièces : pas de virgule, pas de zéro. */
const { cleMP, lireQuantite, quantiteMP } = extraire('const FAMILLES_MP = {', 'const badgeAncienne',
                                                     'cleMP, lireQuantite, quantiteMP');
console.log('\nMatières premières : saisie');
for (const [saisi, attendu] of [['vitr.445', 'VITR445'], [' VITR 445 ', 'VITR445'],
                                ['c8.fd.2115x1015×90', 'C8FD2115X1015X90'],
                                ['ESS 1 F', 'ESS1F'], ['Écran-2', 'ECRAN2'], ['', '']]) {
  verifier(`clé de « ${saisi} » → ${attendu || '(vide)'}`, cleMP(saisi), attendu);
}
for (const [saisi, attendu] of [['19', 19], ['1 600', 1600], [' 160 ', 160], ['2,5', null],
                                ['0', null], ['-3', null], ['', null], ['19 pcs', null]]) {
  verifier(`quantité « ${saisi} » → ${attendu}`, lireQuantite(saisi), attendu);
}
verifier('une pièce au singulier', quantiteMP(1, 'vitrage'), '1 vitrage');
verifier('des cartons au pluriel', quantiteMP(160, 'carton'), '160 cartons');

/* Ce que range un emplacement : une seule question à l'écran, deux champs en
   base. Le mode d'un emplacement MP ne décrit rien : il est gardé tel quel. */
const { usageDeChoix, choixUsageDe, CHOIX_USAGE } = extraire('const MODES_EMP = [', 'const optionsUsage',
                                                             'usageDeChoix, choixUsageDe, CHOIX_USAGE');
console.log('\nCe que range un emplacement');
verifier('quatre choix, cabines d’abord', CHOIX_USAGE.map(c => c[0]).join(' '),
         'cabines-gd cabines-illimite carton vitrage');
verifier('cabines en capacité illimitée', JSON.stringify(usageDeChoix('cabines-illimite')),
         '{"usage":"cabines","mode_places":"illimite"}');
verifier('vitrages : le mode d’avant est gardé',
         JSON.stringify(usageDeChoix('vitrage', { mode_places: 'illimite' })),
         '{"usage":"vitrage","mode_places":"illimite"}');
verifier('un emplacement MP se lit par sa famille', choixUsageDe({ est_mp: true, usage: 'carton' }), 'carton');
verifier('un emplacement de cabines par son mode', choixUsageDe({ est_mp: false, mode_places: 'gd' }), 'cabines-gd');

const { contenuMPCourt } = extraire('function contenuMPCourt', 'function etiquetteEtat', 'contenuMPCourt');
verifier('case MP vide', contenuMPCourt({ mp: { codes: 0 } }), 'vide');
verifier('case MP chargée', contenuMPCourt({ mp: { codes: 2, lignes: 3 } }), '2 codes');

/* --- La cloche, les seuils, le changement d'emplacement ---------------------
   Les phrases et les règles que l'écran dit AVANT le geste : elles doivent
   dire la même chose que le serveur, qui les redit au besoin. Les morceaux du
   fichier sont assemblés dans une même portée — ces fonctions s'appellent
   entre elles, comme dans `app.js`. */
function extraireEnsemble(morceaux, noms) {
  const code = morceaux.map(([debut, fin]) => {
    const i = source.indexOf(debut);
    const j = source.indexOf(fin, i);
    if (i < 0 || j < 0) {
      throw new Error(`Repère introuvable dans app.js : « ${i < 0 ? debut : fin} ». `
        + 'Le code a été réorganisé : mettez ces repères à jour plutôt que de retirer le test.');
    }
    return source.slice(i, j);
  }).join('\n');
  return eval(`(function(){const esc = (s) => String(s); ${code}; return {${noms}};})()`);
}

const mp = extraireEnsemble([
  ['const FAMILLES_MP = {', 'const badgeAncienne'],
  ['const CLE_ALERTES_VUES', 'function clocheHTML'],
  ['/** Un seuil tapé', '/** Le seuil d\'alerte d\'un ou de plusieurs codes'],
  ['const libelleSeuil', '/** Une carte par code'],
  ['/** La phrase qui suit une sortie', '/** Sortir une ligne'],
  ['/** Pourquoi ces lignes ne peuvent pas aller', '/** Changer d\'emplacement : combien'],
  ['/** Ce que fera le réglage, en une phrase', 'function bilanCodesHTML'],
], 'listeCodes, nonVues, clesAlertes, libelleCloche, lireSeuil, libelleSeuil, phraseSeuil, '
   + 'refusArrivee, phraseDeplacement, phraseDeplace, phraseCodes, phraseDejaCodes');

console.log('\nLa cloche');
verifier('un code', mp.listeCodes(['VITR.445']), 'VITR.445');
verifier('deux codes', mp.listeCodes(['A', 'B']), 'A et B');
verifier('trois codes', mp.listeCodes(['A', 'B', 'C']), 'A, B et C');
verifier('au-delà, on compte', mp.listeCodes(['A', 'B', 'C', 'D', 'E']), 'A, B, C et 2 autres');
verifier('rien', mp.listeCodes([]), '');
const groupes = [{ type: 'seuil', items: [{ cle: 'seuil:1' }, { cle: 'seuil:2' }] },
                 { type: 'hors_reservation', items: [{ cle: 'hors:9' }] }];
verifier('les clés de toutes les sortes', mp.clesAlertes(groupes).join(' '), 'seuil:1 seuil:2 hors:9');
verifier('les nouvelles : celles jamais vues ici',
         mp.nonVues(mp.clesAlertes(groupes), new Set(['seuil:1'])), 2);
verifier('rien de nouveau', mp.nonVues(['seuil:1'], new Set(['seuil:1'])), 0);
verifier('ce que lit un lecteur d’écran', mp.libelleCloche(3, 1), 'Alertes : 3, dont 1 nouvelle');
verifier('plusieurs nouvelles', mp.libelleCloche(4, 2), 'Alertes : 4, dont 2 nouvelles');
verifier('aucune alerte', mp.libelleCloche(0, 0), 'Alertes : aucune');

console.log('\nSeuils d’alerte');
for (const [saisi, attendu] of [['20', 20], [' 1 600 ', 1600], ['', null], ['0', null],
                                ['2,5', undefined], ['-3', undefined], ['vingt', undefined]]) {
  verifier(`seuil « ${saisi} » → ${attendu}`, mp.lireSeuil(saisi), attendu);
}
verifier('le seuil dans une liste', mp.libelleSeuil({ seuil_reappro: 50 }), 'seuil d’alerte 50');
verifier('pas de seuil, rien à dire', mp.libelleSeuil({ seuil_reappro: null }), '');
verifier('après une sortie : sous le seuil',
         mp.phraseSeuil({ sous_seuil: true, code: 'VITR.470', en_stock: 8, famille: 'vitrage', seuil: 50 }),
         'VITR.470 est sous son seuil d’alerte : plus que 8 vitrages en stock, pour un seuil de 50.');
verifier('au-dessus du seuil : rien', mp.phraseSeuil({ sous_seuil: false }), '');

console.log('\nChanger d’emplacement');
const lignes = [{ code: 'VITR.470', famille: 'vitrage', place: 'G' },
                { code: 'VITR.927', famille: 'vitrage', place: 'M' }];
const arrivee = (extra) => Object.assign({ code: 'AH510', est_mp: true, actif: true, usage: 'vitrage',
                                           codes_acceptes: [] }, extra);
verifier('une arrivée ouverte', mp.refusArrivee(arrivee(), lignes), '');
verifier('un emplacement de cabines', mp.refusArrivee(arrivee({ est_mp: false }), lignes),
         'AH510 range des cabines.');
verifier('hors service', mp.refusArrivee(arrivee({ actif: false }), lignes), 'AH510 est hors service.');
verifier('une autre famille', mp.refusArrivee(arrivee({ usage: 'carton' }), lignes),
         'AH510 range des cartons.');
verifier('réservé à un des deux codes',
         mp.refusArrivee(arrivee({ codes_acceptes: [{ code: 'VITR.470' }] }), lignes),
         'AH510 est réservé à VITR.470 : VITR.927 n’y va pas.');
verifier('réservé aux deux', mp.refusArrivee(arrivee({
  codes_acceptes: [{ code: 'VITR.470' }, { code: 'VITR.927' }] }), lignes), '');
verifier('le bouton, une ligne',
         mp.phraseDeplacement([{ code: 'VITR.470', quantite: 19, famille: 'vitrage' }], 'AH510·D'),
         'Déplacer 19 VITR.470 vers AH510·D');
verifier('le bouton, plusieurs lignes', mp.phraseDeplacement([
  { code: 'VITR.470', quantite: 19, famille: 'vitrage' },
  { code: 'VITR.927', quantite: 7, famille: 'vitrage' }], 'AH510·D'),
  'Déplacer 2 lignes — 26 vitrages — vers AH510·D');
verifier('après le geste', mp.phraseDeplace([
  { code: 'VITR.470', quantite: 19, destination: 'AH510·D' },
  { code: 'VITR.927', quantite: 7, destination: 'AH510·D' }]),
  'Déplacé : 19 VITR.470 et 7 VITR.927 vers AH510·D.');

console.log('\nCodes acceptés');
verifier('réserver', mp.phraseCodes({ mode: 'remplacer', changes: ['AH500', 'AH510'], codes: ['VITR.470'] }),
         '2 emplacements seront réservés à VITR.470.');
verifier('réserver un seul', mp.phraseCodes({ mode: 'remplacer', changes: ['AH500'], codes: ['A', 'B'] }),
         '1 emplacement sera réservé à A et B.');
verifier('ajouter', mp.phraseCodes({ mode: 'ajouter', changes: ['AH500'], codes: ['VITR.927'] }),
         'VITR.927 s’ajoute à la réservation de 1 emplacement.');
verifier('tout rouvrir', mp.phraseCodes({ mode: 'tous', changes: ['AH500', 'AH501'], codes: [] }),
         '2 emplacements accepteront de nouveau tous les codes de leur famille.');
verifier('rien ne change', mp.phraseCodes({ mode: 'tous', changes: [], codes: [] }), '');
verifier('ajouter à un emplacement ouvert : il les accepte déjà',
         mp.phraseDejaCodes({ mode: 'ajouter', deja: ['AH500'] }), '1 les accepte déjà : AH500');
verifier('déjà réservés ainsi', mp.phraseDejaCodes({ mode: 'remplacer', deja: ['AH500', 'AH510'] }),
         '2 le sont déjà : AH500, AH510');
verifier('déjà ouverts', mp.phraseDejaCodes({ mode: 'tous', deja: ['AH500'] }),
         '1 accepte déjà tous les codes : AH500');

/* --- Droits : une case par geste ------------------------------------------------
   Ce que l'écran propose doit suivre les cases du compte, et le profil du menu
   s'en déduire. Les morceaux sont évalués avec les droits d'un compte donné :
   `DROITS` et `LIBELLES_DROITS` sont posés AVANT, comme le fait `boot()`. */
function compteAvec(cases, libelles = {}) {
  const morceaux = [
    ['const peut = (droit)', 'function refuseSansDroit'],
    ['function profil()', '// Onglets du bas'],
    ['const MENU_CABINES = [', '/** L\'entrée du menu à surligner'],
  ].map(([debut, fin]) => {
    const i = source.indexOf(debut);
    const j = source.indexOf(fin, i);
    if (i < 0 || j < 0) {
      throw new Error(`Repère introuvable dans app.js : « ${i < 0 ? debut : fin} ». `
        + 'Le code a été réorganisé : mettez ces repères à jour plutôt que de retirer le test.');
    }
    return source.slice(i, j);
  }).join('\n');
  const DROITS = Object.fromEntries(cases.map(c => [c, true]));
  // `voitAlertes` vit plus loin, au milieu de la cloche : sa seule ligne suffit.
  const alerte = source.match(/const voitAlertes = .*;/)[0];
  return eval(`(function(DROITS, LIBELLES_DROITS){ ${morceaux}; ${alerte};
    return { peut, peutUnDe, gereEmplacements, sansLeDroit, profil, menuLateral, voitAlertes };
  })`)(DROITS, libelles);
}
const entrees = (compte) => compte.menuLateral().flatMap(([, liens]) => liens.map(([cle]) => cle));

console.log('\nDroits à cocher');
const cariste = compteAvec(['cab_ranger', 'cab_statut', 'cab_envoyer', 'cab_corriger']);
verifier('un cariste a le profil cariste', cariste.profil(), 'cariste');
verifier('le cariste ne voit pas le référentiel', entrees(cariste).includes('emplacements'), false);
verifier('ni la cloche du verre', cariste.voitAlertes(), false);
const regleur = compteAvec(['empl_regler', 'empl_service']);
verifier('qui règle les emplacements gère', regleur.profil(), 'gestion');
verifier('il les voit', entrees(regleur).includes('emplacements'), true);
verifier('sans pouvoir en créer', regleur.peut('empl_creer'), false);
verifier('il voit la cloche (codes acceptés)', regleur.voitAlertes(), true);
verifier('une seule case des emplacements suffit à les gérer',
         compteAvec(['empl_service']).gereEmplacements(), true);
verifier('le modèle seul : profil gestion', compteAvec(['modeles']).profil(), 'gestion');
verifier('sans case : lecture', compteAvec([]).profil(), 'lecture');
verifier('l’import suit SA case, pas le profil',
         entrees(compteAvec(['production'])).includes('import'), true);
verifier('un gestionnaire sans la case n’importe pas',
         entrees(compteAvec(['empl_regler', 'empl_creer', 'modeles'])).includes('import'), false);
verifier('les seuils seuls font voir la cloche', compteAvec(['mp_seuils']).voitAlertes(), true);
verifier('le refus nomme la case',
         compteAvec([], { empl_creer: 'créer et supprimer des emplacements et des racks' })
           .sansLeDroit('empl_creer'),
         'Ton compte n’a pas le droit « créer et supprimer des emplacements et des racks ». '
         + 'Demande-le à l’administrateur du WMS.');
verifier('une case inconnue vaut non', compteAvec(['mp']).peut('cab'), false);

console.log(echecs ? `\n${echecs} test(s) en échec.` : '\nInterface OK — tous les tests passent.');
process.exit(echecs ? 1 : 0);
