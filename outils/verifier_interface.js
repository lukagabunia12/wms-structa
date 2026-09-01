#!/usr/bin/env node
/**
 * Contrôle statique de l'interface opérateur.
 *
 * `node --check` ne valide que la syntaxe : un écran dont la fonction a disparu
 * passe le contrôle sans broncher et ne casse qu'à l'ouverture, chez l'opérateur.
 * Ce script vérifie que chaque destination annoncée par la navigation existe
 * réellement — c'est exactement le défaut qui a échappé à une relecture.
 *
 *     node outils/verifier_interface.js
 */
const fs = require('fs');
const path = require('path');

const FICHIER = path.join(__dirname, '..', 'wms', 'static', 'app', 'app.js');
const source = fs.readFileSync(FICHIER, 'utf8');
const erreurs = [];

/** Noms déclarés au premier niveau du fichier. */
const declares = new Set();
for (const m of source.matchAll(/^(?:async\s+)?function\s+([A-Za-z0-9_]+)/gm)) declares.add(m[1]);
for (const m of source.matchAll(/^(?:const|let|var)\s+([A-Za-z0-9_]+)/gm)) declares.add(m[1]);

/** 1. Les écrans routés par go() pointent vers une fonction qui existe. */
const bloc = source.match(/const ecrans = \{([\s\S]*?)\};/);
if (!bloc) {
  erreurs.push("Table des écrans introuvable dans go() — le contrôle ne sait plus quoi vérifier.");
} else {
  // Les commentaires sont retirés : « joignable seulement si … » se lisait
  // sinon comme une paire écran/fonction.
  const table = bloc[1].replace(/\/\/[^\n]*/g, '');
  const routes = [...table.matchAll(/([A-Za-z0-9_]+)\s*:\s*([A-Za-z0-9_]+)/g)];
  if (routes.length < 10) erreurs.push(`Seulement ${routes.length} écrans routés : table probablement mal lue.`);
  for (const [, ecran, fonction] of routes) {
    if (!declares.has(fonction)) erreurs.push(`Écran « ${ecran} » → ${fonction}() n'existe pas.`);
  }
  /** 2. Chaque entrée de menu mène à un écran routé. */
  const routés = new Set(routes.map(r => r[1]));
  for (const bloc2 of ['MENU_CABINES', 'MENU_ARTICLES']) {
    const m = source.match(new RegExp(`const ${bloc2} = \\[([\\s\\S]*?)\\n\\];`));
    if (!m) continue;
    for (const e of m[1].matchAll(/\['([a-zA-Z]+)'\s*,\s*'/g)) {
      if (!routés.has(e[1])) erreurs.push(`${bloc2} : l'entrée « ${e[1] }» ne mène à aucun écran.`);
    }
  }

  /** 2 bis. Les onglets du bas mènent eux aussi quelque part.
      Ils n'étaient pas contrôlés : un onglet ajouté avec une clé mal orthographiée
      renvoyait silencieusement à l'accueil, sans erreur ni message. */
  const ong = source.match(/const ONGLETS = \{([\s\S]*?)\n\};/);
  if (!ong) {
    erreurs.push('Table ONGLETS introuvable.');
  } else {
    // `matchAll` rend [texte complet, groupe 1, groupe 2] : sans la virgule de tête,
    // `profil` valait le texte entier et `corps` le seul nom du profil — la boucle
    // ne contrôlait rien et annonçait « OK ». Le terminateur est `]],` (fin du
    // tableau du profil) et non `],` (fin d'un onglet).
    for (const [, profil, corps] of ong[1].matchAll(/(\w+):\s*\[([\s\S]*?)\]\],\s*\n/g)) {
      const cles = [...corps.matchAll(/\['([a-zA-Z-]+)'\s*,/g)].map(x => x[1]);
      if (cles.length > 5) erreurs.push(`ONGLETS.${profil} : ${cles.length} onglets, 5 au maximum sur un téléphone.`);
      for (const c of cles) {
        if (!routés.has(c)) erreurs.push(`ONGLETS.${profil} : l'onglet « ${c} » ne mène à aucun écran.`);
      }
    }
  }

  /** 2 ter. Ce qu'un profil a le droit de voir doit exister dans le menu.
      Une clé absente de MENU_CABINES ne fait rien apparaître : elle ne provoque
      aucune erreur non plus, l'entrée disparaît simplement du menu. */
  const parProfil = source.match(/const MENU_PAR_PROFIL = \{([\s\S]*?)\n\};/);
  const dansMenu = new Set();
  for (const bloc2 of ['MENU_CABINES', 'MENU_ARTICLES']) {
    const m = source.match(new RegExp(`const ${bloc2} = \\[([\\s\\S]*?)\\n\\];`));
    if (m) for (const e of m[1].matchAll(/\['([a-zA-Z-]+)'\s*,\s*'/g)) dansMenu.add(e[1]);
  }
  if (parProfil) {
    for (const [, profil, corps] of parProfil[1].matchAll(/(\w+):\s*\[([^\]]*)\]/g)) {
      for (const c of corps.matchAll(/'([a-zA-Z-]+)'/g)) {
        if (!dansMenu.has(c[1])) erreurs.push(`MENU_PAR_PROFIL.${profil} : « ${c[1]} » n'existe dans aucun menu.`);
      }
    }
  }
}

/** 2 quater. L'envoi d'une cabine ne part que d'UN endroit.
    Envoyer est irréversible, et une cabine en quarantaine doit être confirmée.
    Tant que cinq écrans appelaient `/envoyer/` chacun de son côté, la garde était
    posée sur deux d'entre eux et oubliée sur les trois autres. Un seul appel :
    celui de `envoyerCabine()`. */
{
  const appels = [...source.matchAll(/api\(`\/cabines\/\$\{[^}]+\}\/envoyer\//g)];
  if (appels.length !== 1) {
    erreurs.push(`L'envoi d'une cabine part de ${appels.length} endroit(s) : `
      + 'il doit passer par `envoyerCabine()` et par lui seul, '
      + 'qui demande confirmation pour une cabine en quarantaine.');
  }
  if (!declares.has('envoyerCabine')) erreurs.push('envoyerCabine() a disparu.');
}

/** 3. Les fonctions appelées par les menus du bas et de « Plus » existent aussi. */
for (const nom of ['layout', 'go', 'api', 'toast', 'modale', 'confirmer', 'listePaginee']) {
  if (!declares.has(nom)) erreurs.push(`Fonction de base manquante : ${nom}()`);
}

if (erreurs.length) {
  console.error('Interface : ' + erreurs.length + ' problème(s)');
  erreurs.forEach(e => console.error('  - ' + e));
  process.exit(1);
}
console.log(`Interface OK — ${declares.size} déclarations, toutes les destinations existent.`);
