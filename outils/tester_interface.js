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
   le champ n'accepte que des chiffres. Le même champ sert parfois à chercher
   un n° de chantier, qui n'a pas de tirets : le masque se débranche alors. */
const { masquerNumero, masqueNumeroActif } =
  extraire('function formaterNumero', 'const debounce =', 'masquerNumero, masqueNumeroActif');

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
  ['septième chiffre refusé', '2603479', '26_03_47'],
  ['saisie encore partielle', '2603', '26_03'],
];
for (const [nom, saisi, attendu] of cas) {
  verifier(nom, masquerNumero(new ChampFactice()).taper(saisi), attendu);
}

champ = masquerNumero(new ChampFactice());
champ.taper('260347');
masqueNumeroActif(champ, false);
verifier('bascule chantier : les tirets partent', champ.value, '260347');
champ.value = '';
verifier('chantier : six chiffres intacts', champ.taper('251280'), '251280');
masqueNumeroActif(champ, true);
verifier('retour cabine : reformaté', champ.value, '25_12_80');

console.log(echecs ? `\n${echecs} test(s) en échec.` : '\nInterface OK — tous les tests passent.');
process.exit(echecs ? 1 : 0);
