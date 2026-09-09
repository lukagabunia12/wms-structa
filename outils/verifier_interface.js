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

/* Fonction englobante = la dernière déclaration de premier niveau avant une
   position donnée. Sert à nommer le coupable dans les messages : « telle
   fonction fait ceci », plutôt qu'un numéro de ligne à aller chercher. */
const debuts = [...source.matchAll(/^(?:async\s+)?function\s+([A-Za-z0-9_]+)/gm)]
  .map(m => ({ index: m.index, nom: m[1] }));
const englobante = (position) => {
  let nom = '(premier niveau)';
  for (const d of debuts) { if (d.index > position) break; nom = d.nom; }
  return nom;
};
/** Le texte de la fonction englobante jusqu'à `position` : ce qui a été écrit
    AVANT le point examiné, dans la même fonction. */
const avantDans = (position) => {
  let debut = 0;
  for (const d of debuts) { if (d.index > position) break; debut = d.index; }
  return source.slice(debut, position);
};

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

/** 6. Une fiche ouverte depuis un scan pose son propre écran.

    `montrerEmplacement` et `ficheCabine` s'écrivent dans un `#zone` que le
    Scanner et l'écran des gestes ne posent pas. Toutes deux commençaient par
    `const zone = $('#zone'); if (!zone) return;` — et rendaient donc la main en
    SILENCE quand on les appelait depuis un scan : le QR d'un emplacement
    n'affichait plus son contenu, « Voir sa fiche » ne faisait rien. Aucun
    message, aucune erreur en console, rien à chercher dans un journal.

    Les deux passent maintenant par `zoneEcran()`, qui pose l'écran s'il manque.
    Ce contrôle refuse le retour en arrière : c'est un oubli d'une seule ligne,
    invisible à la relecture, et il s'est déjà produit deux fois. */
{
  if (!declares.has('zoneEcran')) {
    erreurs.push('zoneEcran() a disparu : c\'est elle qui pose le conteneur d\'une '
                 + 'fiche ouverte depuis le Scanner, qui n\'en a pas.');
  }
  for (const nom of ['montrerEmplacement', 'ficheCabine']) {
    const i = source.search(new RegExp('(?:async\\s+)?function\\s+' + nom + '\\b'));
    if (i < 0) { erreurs.push(`${nom}() a disparu.`); continue; }
    // Les vingt premières lignes suffisent : le conteneur se prend en ouverture.
    const tete = source.slice(i, i + 1200);
    if (!/zoneEcran\(/.test(tete)) {
      erreurs.push(`${nom}() ne passe pas par zoneEcran() : appelée depuis le `
        + 'Scanner ou l\'écran des gestes, qui ne posent pas de `#zone`, elle '
        + 'rendrait la main en silence et l\'écran resterait tel quel.');
    }
  }
}

/** 7. Une place se touche, elle ne se déroule pas.

    Le choix « gauche / milieu / droite » a un composant tactile : trois cases
    pleine largeur qui disent ce qui est libre et QUI occupe le reste. Trois
    écrans avaient pourtant dérivé vers un `<select>` — le rangement après scan
    de l'emplacement, la saisie du n° devant le rack, « Choisir dans la liste ».
    Dérouler un menu pour dire « droite » est un geste de bureau : devant un
    rack, avec des gants, on ne déroule rien. La dérive est facile parce qu'un
    `<select>` s'écrit en une ligne, et invisible à la relecture parce qu'elle
    fonctionne. Ce contrôle la refuse.

    Deux conditions : aucune liste déroulante de places, et toute écriture de
    `corps.place` vient d'un choix tactile lu dans la même fonction. */
{
  for (const s of source.matchAll(/<select\b[^>]{0,160}?id="[^"]*[Pp]lace/g)) {
    erreurs.push(`${englobante(s.index)}() fait choisir la place dans une liste `
      + 'déroulante. Pose `blocPlaces(d)` et branche `choixPlace(d, bouton)` : '
      + 'trois cases qu\'on touche avec des gants, sans viser.');
  }
  for (const a of source.matchAll(/corps\.place\s*=/g)) {
    if (!/choixPlace\(|brancherPlaces\(/.test(avantDans(a.index))) {
      erreurs.push(`${englobante(a.index)}() écrit corps.place sans avoir branché `
        + 'de choix tactile : la place vient donc d\'ailleurs — une liste '
        + 'déroulante, ou une valeur devinée. Passe par `choixPlace(d, bouton)`.');
    }
  }
  /* Et surtout : la place ne se DEVINE pas. « Saisir le code » rangeait la
     cabine dans `d.libres[0]` — la première place libre — sans rien demander,
     puis annonçait « Rangée en C001·G ». Personne ne choisissait : une cabine
     posée à droite était écrite à gauche, et l'erreur ne se voyait qu'en allant
     la chercher, des semaines plus tard. Le contrôle par fonction ne suffit pas
     ici : il reste vert si un `choixPlace()` traîne ailleurs dans la même
     fonction, ce qui est le cas dans une fonction longue. Celui-ci regarde
     l'affectation elle-même, et refuse toute place prise dans un tableau. */
  /* La règle vise ce qui PART VERS LE SERVEUR — `corps.place = …` ou la clé
     `place:` d'un corps de requête — et non une lecture locale. Sa première
     version attrapait aussi `const place = occs[0].place`, une lecture
     d'affichage parfaitement légitime : une règle qui crie sur du code sain
     finit par être contournée, et c'est alors le vrai défaut qui passe. */
  for (const a of source.matchAll(/(?:corps\.place\s*=|\bplace:)\s*[A-Za-z_$][\w.$]*\s*\[/g)) {
    erreurs.push(`${englobante(a.index)}() prend la place dans un tableau `
      + `(« ${a[0].trim()}… ») : c'est la deviner. Une place se touche — `
      + '`blocPlaces(d)` puis `choixPlace(d, bouton)` — et rien n\'est '
      + 'présélectionné, pour qu\'une cabine posée à droite ne soit pas '
      + 'enregistrée à gauche.');
  }
  for (const nom of ['placesHTML', 'brancherPlaces', 'choixPlace', 'blocPlaces']) {
    if (!declares.has(nom)) erreurs.push(`${nom}() a disparu : c'est le choix tactile des places.`);
  }
}

/** 3. Les fonctions appelées par les menus du bas et de « Plus » existent aussi. */
for (const nom of ['layout', 'go', 'api', 'toast', 'modale', 'confirmer', 'listePaginee']) {
  if (!declares.has(nom)) erreurs.push(`Fonction de base manquante : ${nom}()`);
}

/** 4. Aucune poignée posée sur un bouton qui n'existe plus.
 *
 *  Ce défaut a frappé trois fois, toujours pareil : on retire un bouton du HTML
 *  et on oublie le `$('#leBouton').onclick = …` juste en dessous. `onclick` sur
 *  `null` lève, donc TOUT le reste de la fonction est sauté — l'écran reste
 *  blanc, ou s'affiche à moitié, et rien ne le dit à qui n'a pas ouvert les
 *  outils de développement. `node --check` passe : le fichier est valide.
 *
 *  On cherche le signal exact de ces trois cas : un id atteint par `$('#x')` et
 *  qui n'apparaît NULLE PART ailleurs dans le fichier. La formulation est
 *  étroite volontairement — une version plus large signalait neuf id sains,
 *  ceux que fabriquent `champChantier('scha')`, `choixRack('pRack')` ou
 *  `gesteBouton('gEntrer')`, et un contrôle qui crie sur du code sain finit
 *  désactivé.
 *
 *  Les id construits par interpolation (`id="e_${cle}"`) sont reconnus par leur
 *  préfixe, relevé dans le source : une liste tenue à la main aurait vieilli. */
const PREFIXES_DYNAMIQUES = [...source.matchAll(/id="([A-Za-z][\w-]*)\$\{/g)]
  .map(m => m[1]);

const acces = new Map();
for (const m of source.matchAll(/\$\('#([A-Za-z][\w-]*)'\)/g)) {
  acces.set(m[1], (acces.get(m[1]) || 0) + 1);
}
for (const [nom, combien] of acces) {
  if (PREFIXES_DYNAMIQUES.some(p => nom.startsWith(p))) continue;
  const partout = (source.match(new RegExp(`\\b${nom}\\b`, 'g')) || []).length;
  if (partout > combien) continue;
  erreurs.push(`« ${nom} » est atteint par $('#${nom}') mais aucun élément ne `
    + `porte cet id : la poignée survit à son bouton. Au premier appel, `
    + `onclick sur null lève et le reste de la fonction ne s'exécute pas — `
    + `l'écran reste blanc, sans message.`);
}

/** 5. Le vocabulaire de la maison : le mot écarté ne revient pas.
 *
 *  « Emplacement » est le mot qu'on dit devant le rack ; l'autre a été retiré
 *  de l'interface sur demande. Il est revenu deux fois, et pas par négligence :
 *  il restait dans les commentaires et les docstrings, et on écrit par
 *  mimétisme de ce qu'on relit.
 *
 *  Le contrôle cherche la chaîne LITTÉRALE, sans classe de caractères. Un
 *  `grep 'trav[ée]e'` lancé sans locale UTF-8 ne voit pas le « é » multi-octets
 *  et répond « rien » sur dix lignes bien présentes : c'est exactement ce qui
 *  est arrivé, et pourquoi ce contrôle-ci n'utilise pas de classe.
 *
 *  Les migrations sont exemptées : les anciens noms de champs y sont figés,
 *  c'est de l'historique déjà écrit en base et le réécrire casserait la
 *  reprise. */
/* Le mot n'est PAS écrit en clair ici : sinon ce contrôle se signalerait
   lui-même, et la première version l'a fait — deux « problèmes » pointant sa
   propre liste. Un contrôle qui crie sur du code sain finit par être désactivé,
   et c'est alors le vrai défaut qui passe. Il est donc assemblé, ce qui a
   l'avantage de couvrir d'un coup les huit graphies. */
const MOTS_ECARTES = [];
for (const base of ['trav' + 'é' + 'e', 'trav' + 'ee']) {
  for (const forme of [base, base[0].toUpperCase() + base.slice(1), base.toUpperCase()]) {
    MOTS_ECARTES.push(forme, forme + 's');
  }
}
const RACINE = path.join(__dirname, '..');
const A_BALAYER = [['wms', ['.py', '.js', '.css', '.html']],
                   ['outils', ['.js', '.py']],
                   ['config', ['.py']]];
/* `_a_supprimer` est le purgatoire : le dossier partagé avec la machine de
   Véronique refuse la suppression, on y déplace donc ce qui doit partir en
   attendant qu'elle vide le dossier. Ces fichiers ne sont ni suivis par git ni
   chargés par Django — bloquer sur eux ferait échouer le contrôle à cause de
   code déjà condamné. */
const EXEMPTS = [path.join('wms', 'migrations'), '__pycache__', 'node_modules',
                 '_a_supprimer'];

function fichiers(dossier, extensions) {
  const trouves = [];
  const descendre = (d) => {
    let entrees;
    try { entrees = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of entrees) {
      const complet = path.join(d, e.name);
      if (EXEMPTS.some(x => complet.includes(x))) continue;
      if (e.isDirectory()) descendre(complet);
      else if (extensions.includes(path.extname(e.name))) trouves.push(complet);
    }
  };
  descendre(path.join(RACINE, dossier));
  return trouves;
}

for (const [dossier, extensions] of A_BALAYER) {
  for (const chemin of fichiers(dossier, extensions)) {
    const lignes = fs.readFileSync(chemin, 'utf8').split('\n');
    lignes.forEach((ligne, i) => {
      for (const mot of MOTS_ECARTES) {
        if (ligne.includes(mot)) {
          erreurs.push(`${path.relative(RACINE, chemin)}:${i + 1} contient `
            + `« ${mot} ». Le mot de la maison est « emplacement » — y compris `
            + `dans les commentaires, parce que c'est là qu'on le relit et `
            + `qu'il revient : ${ligne.trim().slice(0, 70)}`);
          return;
        }
      }
    });
  }
}

if (erreurs.length) {
  console.error('Interface : ' + erreurs.length + ' problème(s)');
  erreurs.forEach(e => console.error('  - ' + e));
  process.exit(1);
}
console.log(`Interface OK — ${declares.size} déclarations, toutes les destinations existent.`);
