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

/** Le source SANS ses commentaires.

    Une fonction commentée ressemble encore à une déclaration : `^function nom(`
    correspond aussi bien à l'intérieur d'un bloc `/* … *\/`. C'est arrivé — un
    retrait de code a emporté le `*\/` d'un commentaire, et tout ce qui suivait
    s'est retrouvé commenté, `renderTrouver` compris. `node --check` passait (le
    fichier reste valide) et ce contrôleur annonçait « OK » : l'écran ne cassait
    qu'au clic sur l'onglet. Les commentaires partent donc avant de chercher les
    déclarations. */
const sansCommentaires = source
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/[^\n]*$/gm, '');

/** Noms déclarés au premier niveau du fichier. */
const declares = new Set();
for (const m of sansCommentaires.matchAll(/^(?:async\s+)?function\s+([A-Za-z0-9_]+)/gm)) declares.add(m[1]);
for (const m of sansCommentaires.matchAll(/^(?:const|let|var)\s+([A-Za-z0-9_]+)/gm)) declares.add(m[1]);

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

/** 4. Toute requête réseau passe par fetchReseau().

    Un `fetch` nu qui échoue lève « TypeError: Failed to fetch » : ce message
    anglais arrivait tel quel sous les yeux du cariste, au fond d'un rack, sans
    lui dire s'il devait recommencer. `fetchReseau()` le remplace par « Pas de
    réseau ». Trois appels nus sont légitimes et nommés ci-dessous ; tout autre
    est une régression, silencieuse jusqu'au jour où le Wi-Fi décroche. */
{
  const TOLERES = new Set([
    'fetchReseau',   // c'est lui qui enveloppe
    'doLogin',       // dit mieux : « le serveur ne répond pas, vérifie l'adresse »
    'lireFiche',     // distingue le délai de 45 s dépassé de l'absence de réseau
  ]);
  // Fonction englobante = la dernière déclaration de premier niveau avant l'appel.
  const debuts = [...source.matchAll(/^(?:async\s+)?function\s+([A-Za-z0-9_]+)/gm)]
    .map(m => ({ index: m.index, nom: m[1] }));
  const englobante = (position) => {
    let nom = '(premier niveau)';
    for (const d of debuts) { if (d.index > position) break; nom = d.nom; }
    return nom;
  };
  for (const appel of source.matchAll(/\bfetch\(/g)) {
    const nom = englobante(appel.index);
    if (!TOLERES.has(nom)) {
      erreurs.push(`${nom}() appelle fetch() directement : passe par fetchReseau(), `
        + 'sinon une panne réseau affiche « Failed to fetch » à l\'opérateur.');
    }
  }
}

/** 5. Une cabine ne se crée que depuis l'écran d'entrée.

    Trois écrans la créaient à la volée depuis les huit champs lus sur la photo
    de la fiche : « Ranger », le scan d'un emplacement, la saisie du numéro à la
    main. Depuis que le fichier de production donne les caractéristiques exactes,
    créer depuis une photo fabrique une fiche approximative à côté d'une fiche
    juste — et une cabine née au pied du rack n'a jamais figuré comme « arrivée ».

    Un seul `POST /cabines/`, donc. Le rangement ne range que ce qui est déjà en
    stock. Ce contrôle est le garde-fou : la règle se perdrait au premier écran
    qui « aurait bien besoin » de créer une cabine au passage. */
{
  const creations = [...source.matchAll(/api\('\/cabines\/',\s*\{\s*method:\s*'POST'/g)];
  if (creations.length !== 1) {
    erreurs.push(`Une cabine est créée depuis ${creations.length} endroit(s) : `
      + 'la création passe par `creerCabine()`, appelée par le seul écran '
      + "d'entrée. Un écran de rangement ne crée pas une cabine absente du stock.");
  }
  if (!declares.has('creerCabine')) erreurs.push('creerCabine() a disparu.');
  if (!declares.has('afficherCabineAbsente')) {
    erreurs.push('afficherCabineAbsente() a disparu : c\'est elle qui refuse et '
                 + "aiguille vers l'entrée.");
  }
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
