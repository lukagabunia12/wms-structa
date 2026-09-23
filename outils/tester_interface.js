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

console.log(echecs ? `\n${echecs} test(s) en échec.` : '\nInterface OK — tous les tests passent.');
process.exit(echecs ? 1 : 0);
