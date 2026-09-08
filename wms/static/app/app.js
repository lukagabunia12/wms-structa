const API = '/api';
let token = localStorage.getItem('wms_token') || '';
let USER = localStorage.getItem('wms_user') || '';
let EMPS = [];
let STAGING = null;
let CATS = [];
let DROITS = {};
// Compte administrateur : au-delà des 7 droits fins. Seul l'import du fichier de
// production s'y appuie — il réécrit les caractéristiques de milliers de cabines
// d'un coup, ce n'est pas un geste de poste.
let ADMIN = false;

// N'affiche pas une commande que le serveur refusera : sans ce contrôle, l'opérateur
// remplit un formulaire pour découvrir un 403 à la validation.
const peut = (droit) => DROITS[droit] === true;

const el = () => document.getElementById('app');
const $ = (s) => el().querySelector(s);
const esc = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
const fmt = (n) => { n = Number(n); return Number.isInteger(n) ? n : Math.round(n * 1000) / 1000; };
/* --- Saisie d'un n° de cabine ------------------------------------------------
   Le numéro a TOUJOURS la forme XX_XX_XX. Au poste, taper les tirets bas oblige
   à changer de clavier deux fois par cabine, avec des gants : on les pose donc
   tout seuls, et le champ n'accepte que des chiffres. `inputmode="numeric"`
   ouvre directement le pavé numérique du téléphone.                          */
const FORMAT_NUMERO = /^\d{2}_\d{2}_\d{2}$/;

/** « 260347 » → « 26_03_47 ». Tout ce qui n'est pas un chiffre est ignoré. */
function formaterNumero(brut) {
  // Sept chiffres, pas six : le dernier groupe va de 1 à 3 chiffres. Le fichier
  // de production compte des semaines à plus de 99 cabines (« 25_49_400 »), que
  // le masque tronquait silencieusement en « 25_49_40 » — un numéro valide, mais
  // celui d'une autre cabine.
  const c = String(brut || '').replace(/\D/g, '').slice(0, 7);
  return c.replace(/^(\d{2})(\d{0,2})(\d{0,3}).*$/,
    (_, a, b, d) => a + (b ? '_' + b : '') + (d ? '_' + d : ''));
}

/** Pose le masque sur un champ. Conserve la position du curseur en fin de saisie
    — le cas normal ; une correction au milieu replace le curseur à la fin, ce qui
    reste préférable à un texte qui se réécrit sous les doigts. */
function masquerNumero(champ) {
  if (!champ) return champ;
  champ.setAttribute('inputmode', 'numeric');
  champ.setAttribute('autocomplete', 'off');
  champ.setAttribute('autocapitalize', 'off');
  champ.setAttribute('maxlength', '9');   // 7 chiffres + 2 tirets bas
  champ.dataset.masqueNumero = champ.dataset.masqueNumero || 'on';
  const poser = () => {
    if (champ.dataset.masqueNumero === 'off') return;
    const avant = champ.value;
    const apres = formaterNumero(avant);
    if (apres !== avant) {
      const fin = champ.selectionStart === avant.length;
      champ.value = apres;
      if (fin) { try { champ.setSelectionRange(apres.length, apres.length); } catch (_) {} }
    }
  };
  champ.addEventListener('input', poser);
  poser();
  return champ;
}

/** Rebranche ou coupe le masque sur un champ déjà masqué. Un même champ sert
    parfois à chercher un n° de cabine PUIS un n° de chantier : le chantier n'a
    pas de tirets bas, et les lui imposer rendrait la recherche impossible. */
function masqueNumeroActif(champ, actif) {
  if (!champ) return champ;
  champ.dataset.masqueNumero = actif ? 'on' : 'off';
  if (actif) champ.dispatchEvent(new Event('input'));
  else if (champ.value.includes('_')) champ.value = champ.value.replace(/_/g, '');
  return champ;
}

const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const typeLabel = (t) => ({ IN: 'Entrée', OUT: 'Sortie', AJUST: 'Ajustement' }[t] || t);
const empOpts = (extra) => EMPS.filter(e => !e.staging).map(e => `<option value="${e.id}">${esc(e.code)}</option>`).join('') + (extra || '');

/* Une vibration courte, quand l'appareil en a une. `navigator.vibrate` n'existe
   ni sur ordinateur ni sur iPhone, et Chrome la refuse avant la première
   interaction de l'utilisateur : son absence n'est pas une erreur, on l'enveloppe. */
function vibrer(ms) {
  try { if (navigator.vibrate) navigator.vibrate(ms); } catch (_) {}
}

/* Le bandeau vert disait « Rangé » à qui regardait l'écran. Devant le rack, avec
   du bruit et des gants, on ne regarde pas : on vibre donc à la réussite. Un seul
   endroit à modifier — les 39 gestes qui réussissent passent tous par `'ok'`. */
function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = (type || '') + ' show';
  clearTimeout(t._t); t._t = setTimeout(() => { t.className = (type || ''); }, 2900);
  if (type === 'ok') vibrer(60);
}

const ICON = {
  home:'<path d="M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>',
  scan:'<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><line x1="4" y1="12" x2="20" y2="12"/>',
  truck:'<path d="M3 6h11v9H3z"/><path d="M14 9h4l3 3v3h-7z"/><circle cx="7" cy="18" r="1.6"/><circle cx="17" cy="18" r="1.6"/>',
  box:'<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  out:'<path d="M12 20V6"/><path d="M6 12l6-6 6 6"/>',
  in:'<path d="M12 4v14"/><path d="M6 12l6 6 6-6"/>',
  search:'<circle cx="11" cy="11" r="6"/><line x1="20" y1="20" x2="16" y2="16"/>',
  chart:'<line x1="5" y1="20" x2="5" y2="11"/><line x1="12" y1="20" x2="12" y2="5"/><line x1="19" y1="20" x2="19" y2="14"/>',
  menu:'<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>',
  transfer:'<path d="M4 9h13l-4-4M20 15H7l4 4"/>',
  // Une coche et une alerte manquaient : l'écran des gestes en a besoin pour
  // « lever la quarantaine » et « mettre en quarantaine ».
  check:'<path d="M20 6L9 17l-5-5"/>',
  alert:'<path d="M12 4l9 16H3z"/><line x1="12" y1="10" x2="12" y2="14"/><circle cx="12" cy="17" r=".6" fill="currentColor"/>',
  clip:'<rect x="6" y="4" width="12" height="16" rx="2"/><path d="M9 4h6v3H9z"/>',
  build:'<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1"/>',
  journal:'<circle cx="5" cy="7" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="5" cy="17" r="1"/><line x1="9" y1="7" x2="20" y2="7"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="17" x2="20" y2="17"/>',
  history:'<path d="M4 12a8 8 0 1 0 3-6"/><path d="M4 4v4h4"/><path d="M12 8v4l3 2"/>',
  tag:'<path d="M4 4h8l8 8-8 8-8-8z"/><circle cx="8" cy="8" r="1"/>',
  print:'<path d="M6 9V3h12v6"/><rect x="6" y="13" width="12" height="8"/><path d="M6 17H3v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4h-3"/>',
  plus:'<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  trash:'<path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>',
  close:'<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  grille:'<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><line x1="3.5" y1="9.5" x2="20.5" y2="9.5"/><line x1="3.5" y1="14.5" x2="20.5" y2="14.5"/><line x1="9" y1="4.5" x2="9" y2="19.5"/><line x1="15" y1="4.5" x2="15" y2="19.5"/>',
  // Curseurs de réglage plutôt qu'un engrenage : à 17 px, une roue dentée devient
  // une tache, alors que deux glissières restent lisibles.
  cog:'<line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><circle cx="9" cy="9" r="2.1"/><circle cx="15" cy="15" r="2.1"/>',
  edit:'<path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17z"/><line x1="14.5" y1="7.5" x2="17.5" y2="10.5"/>',
  // Appareil photo : le geste du cariste, pas un pictogramme d'ordinateur.
  camera:'<path d="M3 8.5h3.5L8 6h8l1.5 2.5H21v10H3z"/><circle cx="12" cy="13" r="3.4"/>',
  // Fiche papier : le tableau a deux colonnes de la fiche cabine.
  fiche:'<rect x="4" y="3" width="16" height="18" rx="1.5"/><line x1="4" y1="8" x2="20" y2="8"/><line x1="4" y1="13" x2="20" y2="13"/><line x1="4" y1="18" x2="20" y2="18"/><line x1="11" y1="3" x2="11" y2="21"/>'
};
const icon = (n, s = 24) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-4px">${ICON[n] || ''}</svg>`;

/* --- Fenêtre modale ---------------------------------------------------------
   Un formulaire de création n'a pas sa place en bas d'une liste : il fallait
   dérouler tout l'entrepôt pour l'atteindre, et on perdait ses filtres au retour.
   La modale l'amène au premier plan sans quitter l'écran. Elle vit DANS #app :
   le raccourci $() continue donc de trouver ses champs.                       */
let MODALE = null;

function fermerModale() {
  if (!MODALE) return;
  const { noeud, surFermeture, echap } = MODALE;
  MODALE = null;
  document.removeEventListener('keydown', echap);
  if (noeud.parentNode) noeud.parentNode.removeChild(noeud);
  if (surFermeture) surFermeture();
}

function modale(titre, corps, opts = {}) {
  fermerModale();
  const fond = document.createElement('div');
  fond.className = 'modal-fond';
  fond.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(titre)}">
      <div class="modal-tete"><span>${esc(titre)}</span>
        <button class="modal-x" type="button" aria-label="Fermer">${icon('close', 20)}</button></div>
      <div class="modal-corps">${corps}</div>
    </div>`;
  const echap = (ev) => { if (ev.key === 'Escape') fermerModale(); };
  MODALE = { noeud: fond, surFermeture: opts.surFermeture, echap };
  el().appendChild(fond);
  document.addEventListener('keydown', echap);
  fond.querySelector('.modal-x').onclick = fermerModale;
  // Clic sur le voile seulement : un clic dans la fenêtre ne doit rien fermer.
  fond.onclick = (ev) => { if (ev.target === fond) fermerModale(); };
  return fond.querySelector('.modal-corps');
}

/* Confirmation. Remplace `confirm()`, invisible en mode application installée
   sur le téléphone. Renvoie true (bouton principal), false (annulation ou
   fermeture), ou la valeur du bouton `extra` s'il y en a un.                  */
function confirmer({ titre = 'Confirmer', texte = '', ok = 'Confirmer',
                     annuler = 'Annuler', danger = false, extra = null,
                     champ = null }) {
  return new Promise((resoudre) => {
    let reponse = false;
    const corps = modale(titre, `
      <p class="modal-texte">${esc(texte)}</p>
      ${champ ? `<label for="cfChamp">${esc(champ.libelle)}</label>
        <input id="cfChamp" placeholder="${esc(champ.placeholder || '')}" autocomplete="off">` : ''}
      <div class="modal-actions">
        <button class="btn ${danger ? 'danger' : 'orange'}" type="button" data-oui>${esc(ok)}</button>
        ${extra ? `<button class="btn ${extra.danger ? 'danger' : 'ghost'}" type="button" data-extra>${esc(extra.libelle)}</button>` : ''}
        ${annuler ? `<button class="btn ghost" type="button" data-non>${esc(annuler)}</button>` : ''}
      </div>`, { surFermeture: () => resoudre(reponse) });
    // Avec un champ, la reponse porte ce qui a ete saisi : `{ok, valeur}`. Sans
    // champ, elle reste le `true` que tous les appels connaissent deja.
    corps.querySelector('[data-oui]').onclick = () => {
      const saisi = corps.querySelector('#cfChamp');
      reponse = champ ? { ok: true, valeur: (saisi ? saisi.value : '').trim() } : true;
      fermerModale();
    };
    const nonBouton = corps.querySelector('[data-non]');
    if (nonBouton) nonBouton.onclick = fermerModale;
    const extraBouton = corps.querySelector('[data-extra]');
    if (extraBouton) extraBouton.onclick = () => { reponse = extra.valeur; fermerModale(); };
    corps.querySelector('[data-oui]').focus();
  });
}

/* --- Liste paginée ----------------------------------------------------------
   L'API rend 50 lignes par page. Les écrans lisaient `results` et affichaient
   `count` : « 120 cabines » s'affichait au-dessus de 50 lignes, et les 70 autres
   étaient introuvables — sans le moindre indice à l'écran. Ce bouton charge la
   suite et annonce ce qui reste.

   Options : ligne(x) → HTML (poser data-cle sur l'élément cliquable),
   entete(total, vus), vide, onClic(x), apres(boite, tout), cle.              */
async function listePaginee(boite, chemin, o) {
  const cle = o.cle || 'id';
  const sep = chemin.includes('?') ? '&' : '?';
  let page = 1, tout = [], total = 0, encore = false;

  const dessiner = () => {
    const reste = Math.max(0, total - tout.length);
    boite.innerHTML =
      (o.entete ? o.entete(total, tout) : '')
      + `<div class="list" data-liste>${tout.length
          ? tout.map(o.ligne).join('')
          : `<div class="empty">${esc(o.vide || 'Aucun résultat')}</div>`}</div>`
      + (encore ? `<button class="btn ghost" type="button" data-plus style="margin-top:12px">Voir la suite${reste ? ` (${reste} restant${reste === 1 ? '' : 's'})` : ''}</button>` : '');
    if (o.onClic) boite.querySelectorAll('[data-liste] [data-cle]').forEach(n => n.onclick = () => {
      const x = tout.find(t => String(t[cle]) === n.dataset.cle);
      if (x) o.onClic(x);
    });
    const plus = boite.querySelector('[data-plus]');
    if (plus) plus.onclick = () => {
      plus.disabled = true; plus.textContent = 'Chargement…'; page += 1; charger();
    };
    if (o.apres) o.apres(boite, tout);
  };

  const charger = async () => {
    try {
      const d = await api(`${chemin}${sep}page=${page}`);
      const res = Array.isArray(d) ? d : (d.results || []);
      total = Array.isArray(d) ? res.length : (d.count || 0);
      encore = !Array.isArray(d) && Boolean(d.next);
      tout = tout.concat(res);
      dessiner();
    } catch (e) {
      boite.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  };

  boite.innerHTML = '<div class="empty">Chargement…</div>';
  await charger();
  return tout;
}

// Extrait un message lisible : {"erreur":[…]} du métier, {"detail":…} de DRF, ou les
// erreurs par champ ({"chantier":["…"]}) qui étaient auparavant réduites à « Erreur 400 ».
function messageErreur(data, status) {
  if (!data) return 'Erreur ' + status;
  let m = data.erreur || data.detail;
  if (!m && typeof data === 'object') {
    const parts = [];
    for (const [champ, val] of Object.entries(data)) {
      const txt = Array.isArray(val) ? val.join(' ') : (typeof val === 'string' ? val : '');
      if (txt) parts.push(champ === 'non_field_errors' ? txt : champ + ' : ' + txt);
    }
    if (parts.length) m = parts.join(' — ');
  }
  if (Array.isArray(m)) m = m.join(' ');
  return m || ('Erreur ' + status);
}

/* Un `fetch` qui n'aboutit pas lève « TypeError: Failed to fetch ». Ce message
   anglais arrivait tel quel dans le bandeau rouge : au fond d'un rack, avec le
   Wi-Fi qui décroche, le cariste lisait une phrase qu'il ne comprend pas et ne
   savait pas si son geste était passé. Toutes les requêtes traversent maintenant
   cette fonction : une seule phrase, en français, la même partout.

   Un abandon volontaire (délai dépassé, `AbortController`) est laissé passer :
   l'appelant qui a posé le minuteur dit mieux ce qui s'est passé.            */
async function fetchReseau(url, options) {
  try {
    return await fetch(url, options);
  } catch (e) {
    if (e && e.name === 'AbortError') throw e;
    throw new Error('Pas de réseau');
  }
}

async function api(path, opt = {}) {
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = 'Token ' + token;
  const r = await fetchReseau(API + path, { method: opt.method || 'GET', headers: h, body: opt.body ? JSON.stringify(opt.body) : undefined });
  if (r.status === 401) { logout(); throw new Error('Session expirée, reconnecte-toi.'); }
  if (r.status === 403) throw new Error(messageErreur(await r.json().catch(() => null), 403) || 'Droit insuffisant pour cette opération.');
  const txt = await r.text();
  let data = null;
  // Une erreur serveur renvoie du HTML : JSON.parse levait une exception cryptique
  // (« Unexpected token < ») qui masquait complètement la cause.
  try { data = txt ? JSON.parse(txt) : null; }
  catch (_) { throw new Error(r.ok ? 'Réponse illisible du serveur.' : 'Erreur serveur ' + r.status + '.'); }
  if (!r.ok) throw new Error(messageErreur(data, r.status));
  return data;
}

// Récupère TOUTES les pages. L'API pagine par 50 : lire seulement `results` masquait
// une partie de l'entrepôt (emplacements, lignes de stock à ranger ou à inventorier).
async function apiAll(path) {
  const sep = path.includes('?') ? '&' : '?';
  let page = 1, tout = [];
  for (;;) {
    const d = await api(`${path}${sep}page=${page}`);
    if (Array.isArray(d)) return d;
    tout = tout.concat(d.results || []);
    if (!d.next || page >= 500) break;
    page++;
  }
  return tout;
}

function logout() { token = ''; USER = ''; localStorage.removeItem('wms_token'); localStorage.removeItem('wms_user'); renderLogin(); }

/* Toute réponse non-200 disait « Identifiants incorrects ». C'est faux dans la
   moitié des cas : un serveur arrêté, une adresse erronée ou une erreur 500
   affichaient le même message, et on cherchait un mot de passe pendant que le
   serveur était éteint. Chaque cause a maintenant sa phrase. */
async function doLogin(u, p) {
  let r;
  try {
    r = await fetch(API + '/token/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
  } catch (_) {
    throw new Error('Le serveur ne répond pas. Vérifie qu’il est démarré et que '
                  + 'l’adresse est la bonne.');
  }
  if (r.status === 400 || r.status === 401) {
    throw new Error('Identifiant ou mot de passe incorrect.');
  }
  if (r.status === 429) {
    throw new Error('Trop d’essais rapprochés. Attends une minute et recommence.');
  }
  if (!r.ok) {
    throw new Error(`Le serveur a répondu ${r.status}. Préviens l’administrateur du WMS.`);
  }
  const d = await r.json();
  token = d.token; USER = u;
  localStorage.setItem('wms_token', token); localStorage.setItem('wms_user', u);
}

/* --- Volet articles / matières premières : ARCHIVÉ --------------------------
   Les écrans (Stock, Réception, Sortie, Transfert, Inventaire) et toute l'API
   restent en place, simplement retirés des menus. Repasser ce drapeau à `true`
   les remet dans la navigation, sans autre modification.                     */
const VOLET_ARTICLES = false;

/* --- Profil d'usage --------------------------------------------------------
   Trois façons de se servir du WMS, déduites des droits DÉJÀ appliqués par le
   serveur : aucun rôle supplémentaire à administrer.

   Pourquoi masquer plutôt que griser : un cariste à qui l'on présente onze
   destinations dont neuf lui sont interdites cherche son bouton au lieu de
   ranger. Les écrans restent joignables par leur nom — rien n'est supprimé,
   seulement retiré du chemin de celui qui n'en a pas l'usage.                */
function profil() {
  if (peut('ref') || peut('data')) return 'gestion';
  if (peut('cab')) return 'cariste';
  return 'lecture';
}

// Onglets du bas : poste entrepôt, atteignables au pouce, avec des gants.
// Cinq au maximum : au-delà, les cibles deviennent trop étroites sur un
// téléphone tenu d'une main.
//
// « Trouver » scanne un QR ou une fiche : il répond à « où est CETTE cabine ? ».
// « Parc » ouvre le moteur de recherche : il répond à « lesquelles sont dans tel
// état ? ». Ce sont deux questions distinctes, donc deux onglets ; les confondre
// laissait sans réponse la seule qui ait été posée — retrouver les cabines qui
// ne sont pas rangées.
//
// Les deux portaient des noms qui se recouvraient — « Chercher » et « Cabines » :
// le premier ne disait pas qu'on cherchait UNE cabine, le second ne disait rien
// du tout, tout l'écran ne parlant que de cabines. « Trouver » vise l'unité,
// « Parc » l'ensemble.
//
// En gestion, « Racks » quitte la barre : il reste sur l'accueil et dans le menu,
// et le parcours « Ranger » y mène déjà. Un sixième onglet réduirait toutes les
// cibles pour un écran qu'on n'ouvre pas en tenant une cabine.
/* Trois onglets, les mêmes pour tous les profils.

   Il y en avait cinq, dont trois posaient la même question sous trois noms :
   « Ranger » et « Sortir » demandaient chacun QUELLE cabine avant de proposer
   leur geste, et « Trouver » faisait déjà exactement ce que fait le Scanner —
   lire un QR ou saisir un numéro. Le cariste devait choisir son geste AVANT
   d'avoir identifié la cabine, alors que c'est l'état de la cabine qui décide
   des gestes possibles.

   Le point de départ est le numéro. « Scanner » le lit — photo de la fiche, QR
   ou saisie — et l'écran suivant propose ce qui est possible. Il est donc aussi
   l'écran d'accueil : c'est là que chaque geste commence, autant y être déjà.  */
const ONGLETS_COMMUNS = [['scanner', 'Scanner', 'scan'],
                         ['cabines', 'Parc', 'build'],
                         ['more', 'Plus', 'menu']];
const ONGLETS = { cariste: ONGLETS_COMMUNS, gestion: ONGLETS_COMMUNS,
                  lecture: ONGLETS_COMMUNS };

function navBar(active) {
  const items = VOLET_ARTICLES
    ? [['home','Accueil','home'],['reception','Entrée','in'],['sortie','Sortie','out'],['search','Recherche','search'],['more','Plus','menu']]
    : (ONGLETS[profil()] || ONGLETS.lecture);
  return `<div class="nav">${items.map(([g,l,ic]) => `<button data-go="${g}" class="${active===g?'on':''}"><span class="ic">${icon(ic,22)}</span>${l}</button>`).join('')}</div>`;
}

// Écran courant, pour surligner la bonne entrée de la barre latérale. Renseigné par
// go() ; les rendus rappelés directement (après un enregistrement) conservent la valeur.
let ECRAN = 'home';


// Barre latérale : desktop seulement. Elle expose TOUTES les destinations, là où le
// mobile en cache la moitié derrière l'onglet « Plus ».
/* « Suivi du processus » a été retiré du menu — pas du code. Il montrait les cinq
   étapes et ce qui stagne ; l'onglet Cabines répond aujourd'hui aux mêmes
   questions avec ses filtres rapides chiffrés, et deux de ses cinq étapes
   restent vides tant qu'aucune zone ne porte le rôle « Zone d'envoi » ou
   « Sortie de production ». Le jour où ces rôles sont paramétrés, l'écran
   redevient utile : remettre la ligne ci-dessous et sa vignette d'accueil suffit.
       ['suivi','Suivi du processus','chart'],                                  */
/* Sept entrées au lieu de treize. Ce qui a disparu, et pourquoi :

   - « Ranger », « Sortir » et « Créer une cabine » demandaient chacun QUELLE
     cabine avant de proposer leur geste. C'est le Scanner qui pose désormais
     cette question, une seule fois, et l'état de la cabine décide de la suite.
     Les écrans existent toujours : on y arrive par le geste, plus par le menu.
   - « Trouver une cabine » faisait exactement ce que fait le Scanner.
   - « Par chantier » et « Cabines envoyées » n'étaient que le Parc avec un
     filtre posé. Le champ de recherche du Parc cherche déjà un n° de chantier,
     et « Envoyées » y est un filtre rapide.
   - « Zones » : le fonctionnement par zones est retiré de l'interface. Le
     modèle et les données restent en base — rien n'est perdu, et l'écran
     reviendra le jour où les zones serviront vraiment.                       */
const MENU_CABINES = [
  ['Parc', [['scanner','Scanner une cabine','scan'],
            ['cabines','Toutes les cabines','build'],
            ['home','Tableau de bord','chart']]],
  ['Suivi', [['journal','Journal','history']]],
  // « Emplacements » ouvre l'écran unique : occupation, création, réglages et
  // suppression au même endroit. Il est ici, dans le référentiel, parce que
  // c'est là qu'on vient quand on cherche à ajouter ou corriger une travée.
  ['Référentiel', [['emplacements','Emplacements','box'],
                   ['etiquettes','Étiquettes','print'],
                   // Administrateurs seulement — voir `menuLateral`.
                   ['import','Fichier de production','clip']]],
];

const MENU_ARTICLES = [
  ['Pilotage', [['dashboard','Tableau de bord','chart'], ['stock','Stock','box'],
                ['search','Recherche articles','search']]],
  ['Opérations', [['reception','Réception','truck'], ['ranger','Ranger','clip'],
                  ['sortie','Sortie','out'], ['transfert','Transfert','transfer'],
                  ['inventaire','Inventaire','clip']]],
  ['Suivi', [['receptions','Réceptions','journal'], ['tracabilite','Traçabilité','history']]],
];

/* Ce que chaque profil voit dans le menu. Un cariste garde de quoi retrouver
   une cabine ; il n'a pas à naviguer dans le référentiel, qu'il ne peut pas
   modifier de toute façon — le serveur refuserait. */
const MENU_PAR_PROFIL = {
  cariste: ['scanner', 'cabines'],
  lecture: ['scanner', 'cabines', 'emplacements'],
};

function menuLateral() {
  const base = VOLET_ARTICLES ? MENU_CABINES.concat(MENU_ARTICLES) : MENU_CABINES;
  const permis = MENU_PAR_PROFIL[profil()];
  // L'import ne dépend pas du profil mais du compte : un responsable logistique a
  // le profil « gestion » sans être administrateur. Le serveur refuse de toute
  // façon (403) ; ceci évite seulement de proposer un bouton sans effet.
  const ouvert = (cle) => (cle !== 'import' || ADMIN) && (!permis || permis.includes(cle));
  return base
    .map(([titre, liens]) => [titre, liens.filter(([cle]) => ouvert(cle))])
    .filter(([, liens]) => liens.length);
}

function sideBar() {
  const groupes = menuLateral().map(([titre, liens]) =>
    `<span class="grp">${esc(titre)}</span>` + liens.map(([cle, libelle, ic]) =>
      `<button data-go="${cle}" class="${ECRAN === cle ? 'on' : ''}">${icon(ic, 18)}${esc(libelle)}</button>`).join('')
  ).join('');
  return `<aside class="side">
    <div class="marque"><span class="sceau">${icon('box', 19)}</span>
      <span><span class="nom">WMS</span><span class="desc">Structa Industries</span></span></div>
    <nav class="menu">${groupes}</nav>
    <div class="side-pied">
      <div class="compte"><span class="avatar">${esc((USER || '?').slice(0, 2).toUpperCase())}</span>
        <span><span class="n">${esc(USER || '—')}</span><span class="r">Connecté</span></span></div>
      <button class="btn ghost" data-logout>Se déconnecter</button>
    </div>
  </aside>`;
}

function layout(body, active) {
  el().innerHTML = `<div class="shell">${sideBar()}<main class="main">`
    + `<div class="top"><span class="brand">WMS Structa</span><span class="who">${esc((USER || '?').slice(0, 2).toUpperCase())}</span></div>`
    + `<div class="wrap">${body}</div></main></div>${navBar(active)}`;
  el().querySelectorAll('[data-go]').forEach(b => b.onclick = () => go(b.dataset.go));
  el().querySelectorAll('[data-logout]').forEach(b => b.onclick = logout);
}

function go(name) {
  // Quitter un écran éteint la caméra : laissée allumée elle vide la batterie
  // et empêche l'application suivante d'y accéder.
  arreterCamera();
  const ecrans = {
    // Cabines
    home: renderHome, entree: renderEntree,
    // « Scanner » est le point de départ ET l'écran d'accueil.
    scanner: renderScanner, trouver: renderTrouver,
    // Même écran de scan, autre titre : on sait ce qu'on est venu lire.
    'scan-colonne': () => renderTrouver('Scanner une colonne'),
    rangement: renderRangement, 'sortie-cabine': renderSortieCabine,
    rack: renderEmplacements,
    cabines: renderCabines, emplacements: renderEmplacements,
    journal: renderJournal, etiquettes: renderEtiquettes, more: renderMore,
    import: renderImport,
    // Volet articles — archivé, joignable seulement si VOLET_ARTICLES est réactivé
    reception: renderReception, sortie: renderSortie, search: renderSearch,
    transfert: renderTransfert, ranger: renderRanger, inventaire: renderInventaire,
    receptions: renderReceptions, tracabilite: renderTracabilite,
    dashboard: renderDashboard, stock: renderStock };
  // Écran inconnu : on retombe sur le Scanner, qui est l'accueil.
  const cle = ecrans[name] ? name : 'scanner';
  // Le rendu est empilé plutôt qu'exécuté : c'est lui que rejoueront le bouton
  // « retour » du navigateur et le rafraîchissement automatique.
  ouvrirEcran(() => { ECRAN = cle; (ecrans[cle])(); }, cle);
}

/* --- Le bouton « retour » du navigateur ------------------------------------
   L'application tient dans une seule page : sans rien, le retour du navigateur
   quitte le WMS au lieu de revenir à l'écran précédent — et sur un téléphone
   Android, ce bouton-là est le geste le plus utilisé de tous.

   On empile donc une entrée d'historique par écran ouvert, avec de quoi le
   redessiner. Le retour redescend la pile, l'avance la remonte. Rien n'est
   mémorisé du contenu : chaque écran se redemande au serveur, ce qui évite
   d'afficher au retour une liste vieille de dix minutes.                     */
let PILE = [];              // ce qu'il faut rejouer pour chaque écran visité
let RANG = -1;              // où l'on se trouve dans cette pile
let RETOUR_EN_COURS = false;

function ouvrirEcran(rendu, cle) {
  // Pendant un retour, on rejoue un écran déjà empilé : le réempiler créerait
  // une entrée par appui sur « retour », et le bouton ne remonterait jamais.
  if (RETOUR_EN_COURS) return rendu();
  RANG += 1;
  PILE = PILE.slice(0, RANG);
  PILE.push(rendu);
  try { history.pushState({ rang: RANG }, '', '#' + cle); } catch (_) {}
  return rendu();
}

/** Redessine l'écran courant à l'identique, sans toucher à l'historique. */
function rejouerEcran() {
  const rendu = PILE[RANG];
  return rendu ? rendu() : renderHome();
}

window.addEventListener('popstate', (ev) => {
  const rang = ev.state && typeof ev.state.rang === 'number' ? ev.state.rang : 0;
  RANG = PILE[rang] ? rang : 0;
  arreterCamera();
  RETOUR_EN_COURS = true;
  Promise.resolve(rejouerEcran()).catch(() => {})
    .then(() => { RETOUR_EN_COURS = false; });
});

/* --- Voir les changements en temps réel ------------------------------------
   Deux caristes rangent en même temps : l'écran de l'un doit montrer ce que
   l'autre vient de faire, sans qu'on pense à recharger. Un écran ouvert depuis
   dix minutes ment, et c'est comme ça qu'une place est comptée libre alors
   qu'une cabine y est déjà posée.

   Plutôt que de recharger des listes entières en boucle, on interroge une
   empreinte de l'activité — quatre entiers, `/api/pouls/` — et on ne redessine
   que si elle a bougé. Une liste inchangée ne coûte donc rien.

   Le rafraîchissement est SUSPENDU dès qu'il pourrait effacer un geste en
   cours : champ en cours de saisie, fenêtre ouverte, caméra allumée, rangement
   commencé. Redessiner sous les doigts est pire qu'un chiffre vieux de dix
   secondes. Et l'empreinte n'est retenue qu'APRÈS avoir redessiné : rien n'est
   perdu, le rafraîchissement a lieu dès que la voie est libre.

   Seuls les écrans qui se lisent sont concernés. Une fiche, un formulaire, un
   rangement en cours ne se redessinent jamais tout seuls.                    */
const POULS_MS = 10000;
const ECRANS_TEMPS_REEL = ['home', 'cabines', 'emplacements', 'rack', 'journal'];
let EMPREINTE = null;

function rafraichissementPossible() {
  if (!token || document.visibilityState !== 'visible') return false;
  if (!ECRANS_TEMPS_REEL.includes(ECRAN)) return false;
  const actif = document.activeElement;
  if (actif && /^(INPUT|SELECT|TEXTAREA)$/.test(actif.tagName)) return false;
  if (document.querySelector('.modal')) return false;   // une fenêtre est ouverte
  if (CAMERA) return false;                             // la caméra tourne
  if (RANGEMENT && RANGEMENT.cabine) return false;      // un rangement est commencé
  return true;
}

async function battement() {
  if (!token) return;
  let p;
  try { p = await api('/pouls/'); } catch (_) { return; }   // hors réseau : on réessaiera
  const vue = [p.mouvements, p.dernier, p.cabines, p.emplacements].join('·');
  if (EMPREINTE === null) { EMPREINTE = vue; return; }
  if (vue === EMPREINTE || !rafraichissementPossible()) return;
  EMPREINTE = vue;
  rejouerEcran();
}

setInterval(battement, POULS_MS);
// Revenir sur l'onglet, c'est le moment où l'écran a le plus de chances d'être
// périmé : on ne fait pas attendre le prochain battement.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') battement();
});


const tile = (ic, title, sub, goName) =>
  `<div class="tile ${goName?'':'dim'}" ${goName?`data-go="${goName}"`:''}><span class="ic">${icon(ic,26)}</span><span class="t">${esc(title)}</span><span class="s">${esc(sub)}</span></div>`;

const itemHTML = (a) => `<div class="item" data-id="${a.id}"><div class="r">${esc(a.ref)}</div><div class="d">${esc(a.designation)}</div><div class="meta">${a.categorie_nom?`<span class="pill">${esc(a.categorie_nom)}</span>`:''}${esc(a.unite||'')}</div></div>`;

/* --- Suggestions d'articles -------------------------------------------------
   Un seul moteur pour tous les écrans qui demandent un article (scanner,
   réception, sortie, recherche, « mettre ici »). Trois apports par rapport à la
   recherche brute de l'API :
   - classement utile : ce qui COMMENCE par le texte tapé passe devant, car
     `?search=` cherche « contient » sur ref, ean et désignation et remonte donc
     les résultats pêle-mêle ;
   - articles récents proposés quand le champ est vide (les mêmes références
     reviennent sans cesse au poste) ;
   - une seule implémentation à corriger au lieu de quatre copies.            */

const SUGG_MAX = 8;
const RECENTS_MAX = 8;
let SUGG = {};

function recents() {
  try { return JSON.parse(localStorage.getItem('wms_recents') || '[]'); } catch (_) { return []; }
}

function noterRecent(a) {
  if (!a || !a.id) return;
  const garde = ['id', 'ref', 'designation', 'unite', 'categorie_nom', 'emplacement_defaut'];
  const fiche = {};
  garde.forEach(k => fiche[k] = a[k]);
  const liste = recents().filter(x => x.id !== a.id);
  liste.unshift(fiche);
  try { localStorage.setItem('wms_recents', JSON.stringify(liste.slice(0, RECENTS_MAX))); } catch (_) {}
}

function classerArticles(res, terme) {
  const t = (terme || '').trim().toUpperCase();
  const rang = (a) => {
    const ref = (a.ref || '').toUpperCase();
    const ean = (a.ean || '').toUpperCase();
    const des = (a.designation || '').toUpperCase();
    if (ref === t || ean === t) return 0;
    if (ref.startsWith(t)) return 1;
    if (ean.startsWith(t)) return 2;
    if (des.startsWith(t)) return 3;
    if (ref.includes(t)) return 4;
    return 5;
  };
  return res.slice().sort((x, y) => rang(x) - rang(y) || (x.ref || '').localeCompare(y.ref || ''));
}

async function chercherArticles(terme) {
  const d = await api('/articles/?search=' + encodeURIComponent(terme));
  return classerArticles(d.results || [], terme);
}

// Branche un champ texte sur la liste de suggestions `listeSel`.
// `onPick(article)` est appelé au choix. Renvoie une fonction de rafraîchissement.
function brancherSuggestions(champSel, listeSel, onPick) {
  const champ = $(champSel);
  if (!champ) return () => {};
  champ.setAttribute('autocomplete', 'off');

  const dessiner = (arts, titre) => {
    const liste = $(listeSel);
    if (!liste) return;
    const lot = arts.slice(0, SUGG_MAX);
    SUGG = {};
    lot.forEach(a => SUGG[a.id] = a);
    liste.innerHTML = (titre && lot.length ? `<div class="sec">${esc(titre)}</div>` : '')
      + (lot.length ? lot.map(itemHTML).join('') : '<div class="empty">Aucun article</div>')
      + (arts.length > lot.length ? `<div class="meta" style="padding:6px 2px">${arts.length} correspondances — précise pour affiner</div>` : '');
    liste.querySelectorAll('.item').forEach(it => it.onclick = () => {
      const a = SUGG[it.dataset.id];
      liste.innerHTML = '';
      noterRecent(a);
      onPick(a);
    });
  };

  const montrerRecents = () => {
    const r = recents();
    if (r.length) dessiner(r, 'Récents');
    else { const liste = $(listeSel); if (liste) liste.innerHTML = ''; }
  };

  const rafraichir = debounce(async () => {
    const t = champ.value.trim();
    if (t.length < 2) { montrerRecents(); return; }
    try { dessiner(await chercherArticles(t)); } catch (e) { toast(e.message, 'err'); }
  }, 200);

  champ.oninput = rafraichir;
  champ.onfocus = () => { if (!champ.value.trim()) montrerRecents(); };
  montrerRecents();
  return rafraichir;
}

// Emplacement par défaut de l'article proposé en tête de liste : c'est la
// prédiction la plus utile au poste (l'article retourne presque toujours au même endroit).
const empOptsAvecDefaut = (idDefaut) => {
  const dispo = EMPS.filter(e => !e.staging);
  const defaut = dispo.find(e => String(e.id) === String(idDefaut));
  const autres = dispo.filter(e => e !== defaut);
  return (defaut ? `<option value="${defaut.id}">${esc(defaut.code)} — emplacement habituel</option>` : '')
    + autres.map(e => `<option value="${e.id}">${esc(e.code)}</option>`).join('');
};

function pickerScreen(title, active, onPick) {
  layout(`<h2 class="title">${title}</h2><div class="card"><label>Article</label><input id="q" placeholder="Réf, code-barres ou désignation"><div class="list" id="res"></div><div id="form"></div></div>`, active);
  $('#q').focus();
  brancherSuggestions('#q', '#res', onPick);
}

// Compte les cabines d'un filtre sans rapatrier les lignes : seul `count` est lu.
const compter = (filtre) => api('/cabines/?' + filtre).then(d => d.count).catch(() => '—');

/** Bandeau d'accueil : un rangement laissé en plan se reprend d'un doigt.
    Il ne suffit pas de garder l'état — encore faut-il que celui qui a été
    interrompu sache qu'il l'a été, et où reprendre. */
function rappelEnCours() {
  const r = rangementCommence(RANGEMENT) ? RANGEMENT : relireRangement();
  if (!r) return '';
  const num = (r.cabine && r.cabine.numero) || '';
  const ou = r.d ? ` · emplacement ${r.d.code}` : '';
  return `<button type="button" class="banner clic" data-reprendre
    style="width:100%;text-align:left;border:none;font:inherit;margin-bottom:14px">
    Rangement en cours${num ? ' : ' + esc(num) : ''}${esc(ou)} — reprendre</button>`;
}

function brancherRappelEnCours() {
  const b = el().querySelector('[data-reprendre]');
  if (b) b.onclick = () => go('rangement');
}

/* Vignettes du tableau de bord, filtrées par les droits — comme la barre
   latérale. Elles ne l'étaient pas : un compte en lecture seule se voyait
   proposer « Entrée — créer une cabine », un écran qui l'accueillait par « Ton
   compte n'a pas le droit ». Chercher son bouton parmi des destinations
   interdites fait perdre le temps qu'un tableau de bord est censé gagner.
   « Entrée » et « Par chantier » ont disparu : la première n'existe plus comme
   porte d'entrée (tout part du Scanner), la seconde est devenue un filtre du
   Parc. Une vignette qui mène à un écran supprimé ne mène nulle part. */
function vignettesAccueil() {
  const v = [];
  // Ni « Scanner » ni « Parc » : les deux sont des onglets de la barre du bas,
  // visible en permanence à trois centimètres de ces vignettes. Une vignette
  // qui double un onglet fait chercher lequel des deux est le bon.
  v.push(tile('box', 'Emplacements', peut('ref')
    ? 'occupation, ajout et réglages' : 'occupation des racks', 'emplacements'));
  v.push(tile('history', 'Journal', 'tous les mouvements', 'journal'));
  if (ADMIN) v.push(tile('clip', 'Fichier de production',
    'importer les cabines attendues', 'import'));
  return v.join('');
}

/* Tableau de bord — des compteurs, et rien que des compteurs. Les trois gros
   boutons « Ranger / Sortir / Trouver » ont quitté cet écran : le geste ne part
   plus d'un choix d'action mais du numéro de cabine, donc du Scanner, qui est
   devenu l'écran d'accueil. Ce tableau reste pour l'encadrement, joignable par
   « Plus ». Chaque compteur ouvre la liste qu'il annonce : un « 12 non rangées »
   qui n'y mène pas oblige à retrouver l'écran, puis à reposer les filtres. */
async function renderHome() {
  layout('<div class="empty">Chargement…</div>', 'home');
  try {
    // `archivees` était compté puis jamais affiché : une requête pour rien à
    // chaque ouverture. « Chargées » comptait `statut=charge`, un statut qui
    // n'existe plus : la vignette affichait 0 en toutes circonstances.
    // Remplacée par les cabines sans chantier, qui elles bloquent un départ.
    const [actives, quarantaine, sansChantier, nonRangees] = await Promise.all([
      compter(''), compter('statut=quarantaine'), compter('sans_chantier=1'),
      compter('rangee=0'),
    ]);
    layout(`<h2 class="title">Tableau de bord</h2>
      ${rappelEnCours()}
      <div class="kpis">
        <div class="kpi clic" data-cab="{}"><div class="l">Cabines en stock</div><div class="v">${actives}</div></div>
        <div class="kpi clic ${quarantaine ? 'warn' : ''}" data-cab='{"statut":"quarantaine"}'><div class="l">En quarantaine</div><div class="v">${quarantaine}</div></div>
        <div class="kpi clic" data-cab='{"sans_chantier":"1"}'><div class="l">Sans chantier</div><div class="v">${sansChantier}</div></div>
        <div class="kpi clic" data-cab='{"rangee":"0"}'><div class="l">Non rangées</div><div class="v">${nonRangees}</div></div>
      </div>
      <div class="sec">Aller à</div>
      <div class="tiles">${vignettesAccueil()}</div>`, 'home');
    brancherRappelEnCours();
    el().querySelectorAll('[data-cab]').forEach(n => n.onclick = () => {
      try { ouvrirCabines(JSON.parse(n.dataset.cab)); } catch (_) { ouvrirCabines(); }
    });
  } catch (e) { toast(e.message, 'err'); }
}

// Formulaire de réception pour un article donné. Extrait de renderReception pour être
// réutilisé après la création d'une référence à la volée.
function formulaireReception(a) {
  $('#q').value = a.ref + ' — ' + a.designation;
  if (!empOpts()) { $('#form').innerHTML = '<div class="empty">Crée d\'abord un emplacement.</div>'; return; }
  $('#form').innerHTML = `<label>Emplacement</label><select id="emp">${empOptsAvecDefaut(a.emplacement_defaut)}</select>
    <label>Quantité reçue</label><input id="qte" type="number" min="0" step="any" value="1">
    <label>N° de commande ou de bon de livraison</label><input id="cmd" placeholder="facultatif">
    <label>Commentaire</label><input id="com" placeholder="facultatif">
    ${STAGING ? '<label style="display:flex;align-items:center;gap:8px;margin-top:12px"><input type="checkbox" id="stg" style="width:auto"> Mettre en zone « à ranger »</label>' : ''}
    <button class="btn orange" id="ok">Valider la réception</button>`;
  $('#ok').onclick = async () => {
    try {
      // La case n'est proposée que si une zone « à ranger » existe : sinon la
      // marchandise partait dans un emplacement normal tout en étant enregistrée
      // comme « à ranger ». Le drapeau staging est désormais déduit côté serveur.
      const stg = $('#stg');
      const emp = (stg && stg.checked) ? STAGING : $('#emp').value;
      if (!emp) { toast('Choisis un emplacement.', 'err'); return; }
      const r = await api('/operations/reception/', { method: 'POST', body: {
        article: a.id, emplacement: emp, qte: $('#qte').value,
        commande: $('#cmd').value, commentaire: $('#com').value } });
      toast('Réception ' + r.reception.numero + ' enregistrée', 'ok');
      renderReception();
    } catch (e) { toast(e.message, 'err'); }
  };
}

// Création d'une référence sans quitter la réception : une livraison contient
// régulièrement un article absent du référentiel, et il fallait jusqu'ici passer
// par /admin/ pour l'enregistrer.
async function formulaireNouvelArticle() {
  const cats = await categories();
  $('#res').innerHTML = '';
  $('#form').innerHTML = `<div class="sec">Nouvelle référence</div>
    <label>Désignation *</label><input id="nDes" placeholder="Ex. Vitrage latéral XL 2075×1146">
    <label>Catégorie</label><select id="nCat"><option value="">—</option>${cats.map(c => `<option value="${c.id}">${esc(c.nom)}</option>`).join('')}</select>
    <label>Unité</label><input id="nUni" value="U">
    <label>Code-barres (EAN)</label><input id="nEan" placeholder="facultatif">
    <label>Seuil mini d'alerte</label><input id="nMin" type="number" min="0" step="any" value="0">
    <label>Référence</label><input id="nRef" placeholder="laisser vide pour la générer automatiquement">
    <div class="row" style="margin-top:14px"><button class="btn ghost" id="nAnnul">Annuler</button><button class="btn orange" id="nOk" style="margin-top:0">Créer la référence</button></div>`;
  $('#nDes').focus();
  $('#nAnnul').onclick = () => { $('#form').innerHTML = ''; $('#q').value = ''; $('#q').focus(); };
  $('#nOk').onclick = async () => {
    const designation = $('#nDes').value.trim();
    if (!designation) { toast('La désignation est obligatoire.', 'err'); return; }
    const corps = {
      designation,
      unite: $('#nUni').value.trim() || 'U',
      ean: $('#nEan').value.trim(),
      stock_min: $('#nMin').value || 0,
    };
    if ($('#nCat').value) corps.categorie = $('#nCat').value;
    if ($('#nRef').value.trim()) corps.ref = $('#nRef').value.trim();
    try {
      const a = await api('/articles/', { method: 'POST', body: corps });
      toast('Référence ' + a.ref + ' créée', 'ok');
      noterRecent(a);
      formulaireReception(a);
    } catch (e) { toast(e.message, 'err'); }
  };
}

function renderReception() {
  pickerScreen('Réception', 'reception', (a) => {
    $('#res').innerHTML = '';
    formulaireReception(a);
  });
  // Proposé seulement si le compte a le droit « référentiel », sinon la création
  // échouerait en 403 après saisie.
  if (peut('ref')) {
    const carte = $('#res').parentNode;
    const bouton = document.createElement('button');
    bouton.className = 'btn ghost';
    bouton.id = 'nouveau';
    bouton.textContent = '+ Article absent du référentiel';
    carte.insertBefore(bouton, $('#form'));
    bouton.onclick = formulaireNouvelArticle;
  }
}

function renderSortie() {
  pickerScreen('Sortie', 'sortie', async (a) => {
    $('#res').innerHTML = ''; $('#q').value = a.ref + ' — ' + a.designation;
    try {
      const st = await api('/stock/?article=' + a.id);
      const lines = (st.results || []).filter(l => Number(l.qte) > 0);
      if (!lines.length) { $('#form').innerHTML = '<div class="empty">Aucun stock disponible.</div>'; return; }
      $('#form').innerHTML = `<label>Emplacement</label><select id="emp">${lines.map(l => `<option value="${l.emplacement}">${esc(l.emplacement_code)} — ${fmt(l.qte)} dispo</option>`).join('')}</select>
        <label>Quantité</label><input id="qte" type="number" min="0" step="any" value="1">
        <button class="btn orange" id="ok">Valider la sortie</button>`;
      $('#ok').onclick = async () => {
        try { await api('/operations/sortie/', { method: 'POST', body: { article: a.id, emplacement: $('#emp').value, qte: $('#qte').value } });
          toast('Sortie enregistrée', 'ok'); renderSortie();
        } catch (e) { toast(e.message, 'err'); }
      };
    } catch (e) { toast(e.message, 'err'); }
  });
}

function renderSearch() {
  layout(`<h2 class="title">Rechercher</h2>
    <div class="row" style="margin-bottom:12px"><button class="btn ghost" id="tArt">Article</button><button class="btn ghost" id="tCab">Cabine</button></div>
    <div id="zone"></div>`, 'search');
  const hl = (btn, on) => { btn.style.background = on ? 'var(--navy)' : 'transparent'; btn.style.color = on ? '#fff' : 'var(--navy)'; };

  function articleMode() {
    hl($('#tArt'), true); hl($('#tCab'), false);
    $('#zone').innerHTML = `<div class="card"><label>Article</label><input id="q" placeholder="Réf, code-barres ou désignation"><div class="list" id="res"></div><div id="form"></div></div>`;
    $('#q').focus();
    brancherSuggestions('#q', '#res', showArticle);
  }
  async function showArticle(a) {
    try {
      const lines = await apiAll('/stock/?article=' + a.id);
      const total = lines.reduce((s, l) => s + Number(l.qte), 0);
      $('#res').innerHTML = ''; $('#q').value = a.ref;
      $('#form').innerHTML = `<div style="margin-top:8px"><div class="r" style="font-size:16px">${esc(a.designation)}</div>
        <div class="meta">${esc(a.ref)} · ${esc(a.unite || '')} · seuil ${fmt(a.stock_min)}</div>
        <div class="sec" style="margin-top:12px">Stock par emplacement — total ${fmt(total)}</div>
        ${lines.length ? lines.map(l => `<div class="item"><div class="r">${esc(l.emplacement_code)}</div><div class="d">${fmt(l.qte)}</div></div>`).join('') : '<div class="empty">Aucun stock</div>'}</div>`;
    } catch (e) { toast(e.message, 'err'); }
  }

  function cabineMode() {
    hl($('#tArt'), false); hl($('#tCab'), true);
    $('#zone').innerHTML = `<div class="card"><div class="row"><button class="btn ghost" id="mNum">N° cabine</button><button class="btn ghost" id="mCha">N° chantier</button></div><input id="q" placeholder="Rechercher par numéro de cabine" style="margin-top:10px" inputmode="numeric"></div><div class="list" id="res"></div>`;
    masquerNumero($('#q'));
    let mode = 'numero';
    async function load() {
      const term = ($('#q').value || '').trim();
      const qp = term ? ('?' + mode + '=' + encodeURIComponent(term)) : '';
      try {
        const d = await api('/cabines/' + qp);
        const items = d.results || [];
        $('#res').innerHTML = items.length ? items.map(c => `<div class="item"><div class="r">${esc(c.numero)} <span class="pill">${esc(c.etat || '—')}</span>${c.statut === 'sortie' ? '<span class="pill" style="background:#eee;color:#888">sortie</span>' : ''}</div><div class="d">chantier ${esc(c.chantier)}${c.modele ? ' · ' + esc(c.modele) : ''}</div>${c.emplacement_code ? `<div class="meta">emplacement ${esc(c.emplacement_code)}</div>` : ''}</div>`).join('') : '<div class="empty">Aucune cabine trouvée</div>';
      } catch (e) { toast(e.message, 'err'); }
    }
    const setMode = (m) => { mode = m; hl($('#mNum'), m === 'numero'); hl($('#mCha'), m === 'chantier'); $('#q').placeholder = m === 'numero' ? 'Rechercher par numéro de cabine' : 'Rechercher par numéro de chantier'; masqueNumeroActif($('#q'), m === 'numero'); load(); };
    $('#mNum').onclick = () => setMode('numero');
    $('#mCha').onclick = () => setMode('chantier');
    $('#q').oninput = debounce(load, 250);
    setMode('numero');
  }

  $('#tArt').onclick = articleMode;
  $('#tCab').onclick = cabineMode;
  articleMode();
}

function renderTransfert() {
  pickerScreen('Transfert', 'more', async (a) => {
    $('#res').innerHTML = ''; $('#q').value = a.ref + ' — ' + a.designation;
    try {
      const st = await api('/stock/?article=' + a.id);
      const lines = (st.results || []).filter(l => Number(l.qte) > 0);
      if (!lines.length) { $('#form').innerHTML = '<div class="empty">Aucun stock à transférer.</div>'; return; }
      $('#form').innerHTML = `<label>Depuis</label><select id="src">${lines.map(l => `<option value="${l.emplacement}">${esc(l.emplacement_code)} — ${fmt(l.qte)} dispo</option>`).join('')}</select>
        <label>Vers</label><select id="dst">${empOpts()}</select>
        <label>Quantité</label><input id="qte" type="number" min="0" step="any" value="1">
        <button class="btn orange" id="ok">Valider le transfert</button>`;
      $('#ok').onclick = async () => {
        try { await api('/operations/transfert/', { method: 'POST', body: { article: a.id, source: $('#src').value, destination: $('#dst').value, qte: $('#qte').value } });
          toast('Transfert effectué', 'ok'); renderTransfert();
        } catch (e) { toast(e.message, 'err'); }
      };
    } catch (e) { toast(e.message, 'err'); }
  });
}

async function renderRanger() {
  layout('<h2 class="title">Ranger</h2><div class="empty">Chargement…</div>', 'home');
  if (!STAGING) { layout('<h2 class="title">Ranger</h2><div class="empty">Aucune zone « à ranger » définie.</div>', 'home'); return; }
  try {
    const lines = (await apiAll('/stock/?emplacement=' + STAGING)).filter(l => Number(l.qte) > 0);
    layout(`<h2 class="title">Ranger</h2><div class="sec">Articles en zone « à ranger »</div>
      <div class="list" id="lst">${lines.length ? lines.map(l => `<div class="item" data-a="${l.article}" data-q="${l.qte}"><div class="r">${esc(l.article_ref)}</div><div class="d">${fmt(l.qte)} à ranger</div></div>`).join('') : '<div class="empty">Rien à ranger.</div>'}</div><div id="form"></div>`, 'home');
    el().querySelectorAll('#lst .item').forEach(it => it.onclick = () => {
      const aid = it.dataset.a, q = it.dataset.q;
      $('#form').innerHTML = `<div class="card"><div class="r">${it.querySelector('.r').textContent}</div>
        <label>Vers l'emplacement</label><select id="dst">${empOpts()}</select>
        <label>Quantité</label><input id="qte" type="number" min="0" step="any" value="${fmt(q)}">
        <button class="btn orange" id="ok">Ranger</button></div>`;
      $('#ok').onclick = async () => {
        try { await api('/operations/transfert/', { method: 'POST', body: { article: aid, source: STAGING, destination: $('#dst').value, qte: $('#qte').value } });
          toast('Rangé', 'ok'); renderRanger();
        } catch (e) { toast(e.message, 'err'); }
      };
    });
  } catch (e) { toast(e.message, 'err'); }
}

function renderInventaire() {
  layout(`<h2 class="title">Inventaire</h2><div class="card"><label>Emplacement</label><select id="emp">${empOpts()}</select><button class="btn" id="load">Charger le stock</button></div><div id="zone"></div>`, 'more');
  $('#load').onclick = async () => {
    const emp = $('#emp').value;
    // Sans emplacement, /stock/?emplacement= renvoyait le stock de tout l'entrepôt
    // et l'ajustement partait avec emplacement:"" (ValueError 500).
    if (!emp) { toast('Choisis un emplacement.', 'err'); return; }
    try {
      const lines = await apiAll('/stock/?emplacement=' + emp);
      $('#zone').innerHTML = `<div class="sec">Quantités comptées</div>${lines.length ? lines.map(l => `<div class="item"><div class="r">${esc(l.article_ref)}</div><input type="number" min="0" step="any" value="${fmt(l.qte)}" data-a="${l.article}" data-old="${l.qte}" style="margin-top:6px"></div>`).join('') : '<div class="empty">Aucun article ici.</div>'}${lines.length ? '<button class="btn orange" id="val">Valider l\'inventaire</button>' : ''}`;
      const val = $('#val');
      if (val) val.onclick = async () => {
        const inputs = [...el().querySelectorAll('#zone input')];
        let n = 0;
        try {
          for (const i of inputs) { if (Number(i.value) !== Number(i.dataset.old)) { await api('/operations/ajustement/', { method: 'POST', body: { article: i.dataset.a, emplacement: emp, qte: i.value } }); n++; } }
          toast(n + ' ajustement(s) enregistré(s)', 'ok'); $('#load').click();
        } catch (e) { toast(e.message, 'err'); }
      };
    } catch (e) { toast(e.message, 'err'); }
  };
}


async function renderReceptions() {
  layout('<h2 class="title">Réceptions</h2><div class="empty">Chargement…</div>', 'more');
  try {
    const d = await api('/receptions/');
    const rows = (d.results || []).map(r => `<div class="item"><div class="r">${esc(r.numero)}${r.staging?' <span class="pill">à ranger</span>':''}</div><div class="d">${fmt(r.qte)} — ${new Date(r.date).toLocaleString('fr-FR')}</div>${r.commentaire?`<div class="meta">${esc(r.commentaire)}</div>`:''}</div>`).join('');
    layout(`<h2 class="title">Réceptions (${d.count})</h2><div class="list">${rows || '<div class="empty">Aucune réception</div>'}</div>`, 'more');
  } catch (e) { toast(e.message, 'err'); }
}

async function renderTracabilite() {
  layout('<h2 class="title">Traçabilité</h2><div class="empty">Chargement…</div>', 'more');
  try {
    const d = await api('/mouvements/');
    const rows = (d.results || []).map(m => `<div class="item"><div class="r">${typeLabel(m.type)} · ${fmt(m.qte)}${m.annule?' <span class="pill" style="background:#fbe7d6;color:#8a4b0b">annulé</span>':''}</div><div class="d">${esc(m.article_ref||'?')} @ ${esc(m.emplacement_code||'?')}</div><div class="meta">${new Date(m.date).toLocaleString('fr-FR')}${m.note?' · '+esc(m.note):''}</div></div>`).join('');
    layout(`<h2 class="title">Traçabilité (${d.count})</h2><div class="sec">Derniers mouvements</div><div class="list">${rows || '<div class="empty">Aucun mouvement</div>'}</div>`, 'more');
  } catch (e) { toast(e.message, 'err'); }
}

function labelWindow(titre, code, sous) {
  const w = window.open('', '_blank', 'width=420,height=300');
  if (!w) { toast('Autorise les fenêtres pop-up pour imprimer.', 'err'); return; }
  // esc() sur chaque donnée serveur : la fenêtre est de même origine, une désignation
  // contenant du balisage y exécuterait du script (et pourrait lire le jeton).
  w.document.write(`<title>${esc(titre)}</title><style>body{font-family:system-ui;text-align:center;padding:24px}.c{font-size:30px;font-weight:700}.k{font-family:monospace;font-size:16px;margin-top:8px;border:2px dashed #333;display:inline-block;padding:6px 14px}.s{color:#555;margin-top:10px}</style><div class="c">${esc(titre)}</div><div class="k">${esc(code)}</div><div class="s">${esc(sous||'')}</div><script>window.onload=()=>window.print()<\/script>`);
  w.document.close();
}

/* --- Impression des étiquettes d'emplacement --------------------------------
   Une « bande » = une colonne du rack : ses niveaux empilés verticalement, le
   code d'emplacement au-dessus de chaque QR, 8 cm de large pour se coller sur
   le montant. Les bandes s'enchaînent sur la feuille — deux par rangée, la
   largeur d'une A4 en accueille deux — mais aucune n'est jamais coupée en deux
   pages : c'est la bande entière qu'on découpe et qu'on va poser.            */

const LARGEUR_BANDE_MM = 80;   // le maximum demandé par l'exploitation
const TAILLES_QR = [['55', 'Grand — 55 mm'], ['40', 'Moyen — 40 mm'],
                    ['28', 'Compact — 28 mm']];
let TAILLE_QR = '40';

/** Un QR en image, prêt à imprimer. Rendu à ~200 dpi : à 96 dpi le carré
 *  s'imprime flou et le scan devient capricieux sous l'éclairage d'un entrepôt. */
function qrEnImage(texte, pixels) {
  return new Promise((resolve) => {
    const boite = document.createElement('div');
    boite.style.cssText = 'position:fixed;left:-10000px;top:0';
    document.body.appendChild(boite);
    try {
      new QRCode(boite, { text: texte, width: pixels, height: pixels,
                          correctLevel: QRCode.CorrectLevel.M });
    } catch (e) { boite.remove(); resolve(''); return; }
    // qrcodejs dessine tantôt un <canvas>, tantôt un <img> : on attend l'un ou l'autre.
    const lire = (essais) => {
      const cv = boite.querySelector('canvas');
      const img = boite.querySelector('img');
      let url = '';
      try {
        url = cv ? cv.toDataURL('image/png')
                 : (img && String(img.src).startsWith('data:') ? img.src : '');
      } catch (_) { url = ''; }
      if (url || essais <= 0) { boite.remove(); resolve(url); return; }
      setTimeout(() => lire(essais - 1), 30);
    };
    lire(8);
  });
}

/**
 * Ouvre la fenêtre d'impression.
 * @param {Array} bandes  [{ titre, codes: ['AC550','AC551','AC552'] }, …]
 * @param {string} titre  intitulé affiché à l'écran, retiré à l'impression
 */
async function imprimerBandes(bandes, titre) {
  if (typeof QRCode === 'undefined') {
    toast('Générateur de QR non chargé : lancez « python manage.py telecharger_libs » sur le serveur.', 'err');
    return;
  }
  const codes = bandes.flatMap(b => b.codes);
  if (!codes.length) { toast('Rien à imprimer.', 'err'); return; }

  // Une bande de plusieurs niveaux occupe toute la hauteur utile d'une A4 et
  // ses étiquettes s'y répartissent : c'est l'image du montant, les niveaux y
  // sont espacés comme ils le sont sur le rack. La largeur, elle, reste à 80 mm,
  // ce qui laisse deux bandes côte à côte sur la feuille.
  const parBande = Math.max(1, ...bandes.map(b => b.codes.length));
  const pleineHauteur = parBande > 1;
  // 297 mm − 2 × 8 mm de marge, moins la marge interne de la bande.
  const utileMM = 297 - 16 - 12;
  // La taille choisie est un maximum : au-delà de quatre ou cinq niveaux, il faut
  // bien réduire pour que la bande tienne encore sur une seule page.
  const mm = pleineHauteur
    ? Math.max(20, Math.min(Number(TAILLE_QR), Math.floor(utileMM / parBande) - 9))
    : Number(TAILLE_QR);
  const pixels = Math.round(mm * 8);          // ≈ 200 dpi
  if (codes.length > 4) toast(`Préparation de ${codes.length} étiquettes…`);

  const images = {};
  for (const code of codes) images[code] = await qrEnImage('LOC:' + code, pixels);
  const rate = codes.find(c => !images[c]);
  if (rate) { toast('Impossible de générer le QR de ' + rate, 'err'); return; }

  const fenetre = window.open('', '_blank');
  if (!fenetre) { toast('Autorise les fenêtres pop-up pour imprimer.', 'err'); return; }

  const multiple = bandes.length > 1;
  // Les étiquettes sont dans leur propre bloc : sinon le titre de la bande entre
  // dans la répartition et creuse un écart plus large en haut qu'entre les QR.
  const corps = bandes.map(b => `<div class="bande${b.codes.length > 1 ? ' pleine' : ''}">
      ${multiple && b.titre ? `<div class="bande-titre">${esc(b.titre)}</div>` : ''}
      <div class="etiquettes">${b.codes.map(c => `<div class="etiquette">
          <div class="code">${esc(c)}</div>
          <img class="qr" src="${images[c]}" alt="${esc(c)}">
        </div>`).join('')}</div>
    </div>`).join('');

  fenetre.document.write(`<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>${esc(titre)}</title>
<style>
  @page { size: A4 portrait; margin: 8mm; }
  *{ box-sizing: border-box }
  body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; color: #16222c }
  .entete { font-size: 11pt; margin: 0 0 5mm; color: #55626c }
  .planche { display: flex; flex-wrap: wrap; gap: 6mm; align-items: flex-start }
  /* 8 cm de large : la contrainte de pose. Deux bandes tiennent côte à côte
     dans la largeur d'une A4, ce qui divise le papier par deux. */
  .bande {
    width: ${LARGEUR_BANDE_MM}mm; max-width: ${LARGEUR_BANDE_MM}mm;
    border: 0.4mm dashed #9aa4ac; border-radius: 2mm;
    padding: 6mm 2mm;
    /* Une bande se découpe et se pose d'un bloc : jamais à cheval sur deux pages. */
    break-inside: avoid; page-break-inside: avoid;
  }
  /* Toute la hauteur de la feuille, étiquettes réparties : les QR sont espacés
     comme les niveaux le sont sur le montant. */
  .bande.pleine { height: ${297 - 16}mm; display: flex; flex-direction: column }
  .bande.pleine .etiquettes {
    flex: 1; display: flex; flex-direction: column; justify-content: space-between;
  }
  .bande-titre { font-size: 7.5pt; letter-spacing: .5pt; text-transform: uppercase;
                 color: #6b7780; text-align: center }
  .etiquette { text-align: center }
  /* Le code au-dessus du QR : c'est lui qu'on lit à l'œil quand le scan ne prend pas. */
  .code { font-family: Consolas, 'Courier New', monospace; font-size: 15pt;
          font-weight: 700; letter-spacing: .6pt; margin-bottom: 1.5mm }
  .qr { display: block; margin: 0 auto; width: ${mm}mm; height: ${mm}mm }
  @media print { .entete { display: none } }
</style></head><body>
<div class="entete">${esc(titre)} — ${codes.length} étiquette${codes.length > 1 ? 's' : ''}. Lancez l'impression, puis découpez le long des pointillés.</div>
<div class="planche">${corps}</div>
<script>window.onload = function(){ setTimeout(function(){ window.print(); }, 250); }<\/script>
</body></html>`);
  fenetre.document.close();
}

// Une seule étiquette — le geste courant depuis la fiche d'un emplacement.
function printLocationLabel(code) {
  return imprimerBandes([{ codes: [code] }], 'Emplacement ' + code);
}

/** Les emplacements d'un rack, groupés en bandes (une par colonne).
 *  Les emplacements créés à l'unité n'ont pas de colonne : chacun fait sa bande. */
function bandesDepuisEmplacements(emplacements, nomRack) {
  const parColonne = new Map();
  emplacements.forEach(e => {
    const cle = e.colonne == null ? 'seul-' + e.id : String(e.colonne);
    if (!parColonne.has(cle)) parColonne.set(cle, { colonne: e.colonne, codes: [] });
    parColonne.get(cle).codes.push(e);
  });
  return [...parColonne.values()]
    .sort((a, b) => (a.colonne ?? 0) - (b.colonne ?? 0))
    .map(g => ({
      titre: g.colonne == null ? '' : `${nomRack || ''} · colonne ${g.colonne}`.trim(),
      // Niveau décroissant : la bande imprimée est l'image du montant. Le niveau
      // le plus haut se colle en haut, le niveau 0 au ras du sol — on pose la
      // bande d'un bloc sans avoir à la retourner ni à réfléchir.
      codes: g.codes.sort((a, b) => (b.niveau ?? 0) - (a.niveau ?? 0)).map(e => e.code),
    }));
}

async function showLocation(emp) {
  try {
    const lines = await apiAll('/stock/?emplacement=' + emp.id);
    const withStock = lines.filter(l => Number(l.qte) > 0);
    $('#zone').innerHTML = `
      <div class="card"><div class="r" style="font-size:16px">Emplacement ${esc(emp.code)}</div>
        <div class="row" style="margin-top:10px"><button class="btn" id="putIn">Mettre ici</button><button class="btn orange" id="takeOut">Retirer d’ici</button></div>
        <div id="act"></div></div>
      <div class="sec">Contenu actuel</div>
      <div class="list">${lines.length ? lines.map(l => `<div class="item"><div class="r">${esc(l.article_ref)}</div><div class="d">${fmt(l.qte)}</div></div>`).join('') : '<div class="empty">Emplacement vide</div>'}</div>`;
    $('#putIn').onclick = () => {
      $('#act').innerHTML = `<label>Article à mettre</label><input id="pq" placeholder="Réf ou désignation — tape 2 lettres"><div class="list" id="pres"></div><div id="pf"></div>`;
      $('#pq').focus();
      brancherSuggestions('#pq', '#pres', (a) => {
        $('#pq').value = a.ref + ' — ' + a.designation;
        $('#pf').innerHTML = `<label>Quantité</label><input id="pqte" type="number" min="0" step="any" value="1"><button class="btn orange" id="pok">Valider l’entrée</button>`;
        $('#pok').onclick = async () => {
          try {
            await api('/operations/entree/', { method: 'POST', body: { article: a.id, emplacement: emp.id, qte: $('#pqte').value } });
            toast('Entrée enregistrée', 'ok');
            showLocation(emp);
          } catch (e) { toast(e.message, 'err'); }
        };
      });
    };
    $('#takeOut').onclick = () => {
      if (!withStock.length) { $('#act').innerHTML = '<div class="empty">Rien à retirer ici.</div>'; return; }
      $('#act').innerHTML = `<label>Article à retirer</label><select id="tsel">${withStock.map(l => `<option value="${l.article}">${esc(l.article_ref)} — ${fmt(l.qte)} dispo</option>`).join('')}</select><label>Quantité</label><input id="tqte" type="number" min="0" step="any" value="1"><button class="btn orange" id="tok">Valider la sortie</button>`;
      $('#tok').onclick = async () => { try { await api('/operations/sortie/', { method: 'POST', body: { article: $('#tsel').value, emplacement: emp.id, qte: $('#tqte').value } }); toast('Sortie enregistrée', 'ok'); showLocation(emp); } catch (e) { toast(e.message, 'err'); } };
    };
  } catch (e) { toast(e.message, 'err'); }
}

function renderEtiquettes() {
  // Sans le volet articles, seules les étiquettes d'emplacement ont un sens : ce sont
  // elles qu'on scanne pour ranger une cabine.
  const onglets = VOLET_ARTICLES
    ? '<div class="row"><button class="btn ghost" id="ta">Article</button><button class="btn ghost" id="te">Emplacement</button></div>'
    // Les cabines ne portent pas de QR code : seules les étiquettes
    // d'emplacement s'impriment, et il n'y a donc plus de choix à faire.
    : '';
  layout(`<h2 class="title">Étiquettes QR</h2>${onglets}<div id="zone"></div>`, 'more');
  const artMode = () => {
    $('#zone').innerHTML = '<div class="card"><label>Article</label><input id="q" placeholder="Réf ou désignation"><div class="list" id="res"></div></div>';
    $('#q').focus();
    brancherSuggestions('#q', '#res', (a) => labelWindow(a.ref, 'ART:' + a.ref, a.designation));
  };
  /* Étiquettes d'emplacement, trois portées : une cellule, une colonne entière
     (les niveaux d'un montant), ou tout un rack découpé en bandes de colonnes. */
  const empMode = async () => {
    const zone = $('#zone');
    zone.innerHTML = '<div class="empty">Chargement…</div>';
    // Relu à chaque ouverture : la liste servait la photo prise au démarrage, si
    // bien qu'un emplacement créé dans la foulée n'avait pas d'étiquette à imprimer.
    await rafraichirEmplacements();
    const racks = await api('/emplacements/racks/').catch(() => []);

    zone.innerHTML = `
      <div class="card">
        <label for="pTaille">Taille des QR</label>
        <select id="pTaille">${TAILLES_QR.map(([v, l]) => `<option value="${v}"${v === TAILLE_QR ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>
        <div class="aide">Bandes de ${LARGEUR_BANDE_MM} mm de large, QR empilés à la verticale, code d'emplacement au-dessus de chacun. Deux bandes tiennent côte à côte sur une A4.</div>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn ghost" data-portee="cellule">Une cellule</button>
        <button class="btn ghost" data-portee="colonne">Une colonne</button>
        <button class="btn ghost" data-portee="rack">Un rack entier</button>
      </div>
      <div id="pZone"></div>`;
    $('#pTaille').onchange = () => { TAILLE_QR = $('#pTaille').value; };

    const nomRack = (r) => `${r.rack} — ${r.colonnes} colonne${r.colonnes > 1 ? 's' : ''} × ${r.niveaux} niveau${r.niveaux > 1 ? 'x' : ''} (${r.premier} → ${r.dernier})`;
    const choixRack = (id) => racks.length
      ? `<label for="${id}">Rack</label><select id="${id}">${racks.map(r => `<option value="${esc(r.rack)}">${esc(nomRack(r))}</option>`).join('')}</select>`
      : '';
    const sansRack = `<div class="empty">Aucun rack généré pour l'instant.<br>Écran « Emplacements » → bouton « Créer un rack ».</div>`;

    const portees = {
      cellule: () => {
        const dispo = EMPS.filter(e => !e.staging);
        $('#pZone').innerHTML = dispo.length
          ? `<div class="sec">Cliquer pour imprimer l'étiquette</div>
             <input id="pCherche" placeholder="Filtrer par code (ex. AC55)" autocomplete="off" style="margin-bottom:10px">
             <div class="list" id="pListe"></div>`
          : '<div class="empty">Aucun emplacement.</div>';
        if (!dispo.length) return;
        const dessiner = () => {
          const t = ($('#pCherche').value || '').trim().toUpperCase();
          const vus = dispo.filter(e => !t || e.code.toUpperCase().includes(t));
          $('#pListe').innerHTML = vus.length ? vus.slice(0, 200).map(e => `
            <div class="item" data-c="${esc(e.code)}">
              <div class="r">${esc(e.code)}${e.actif === false ? ' <span class="etat att">inactif</span>' : ''}</div>
              <div class="d">${esc(e.zone_cabine_nom || '')}</div>
              <div class="meta">${icon('print', 16)} imprimer</div></div>`).join('')
            : '<div class="empty">Aucun code ne correspond</div>';
          $('#pListe').querySelectorAll('[data-c]').forEach(it =>
            it.onclick = () => printLocationLabel(it.dataset.c));
        };
        $('#pCherche').oninput = debounce(dessiner, 200);
        dessiner();
      },

      colonne: () => {
        if (!racks.length) { $('#pZone').innerHTML = sansRack; return; }
        $('#pZone').innerHTML = `<div class="card" style="margin-top:12px">
          ${choixRack('pRack')}
          <label for="pCol">Colonne</label><select id="pCol"></select>
          <div class="aide" id="pApercu"></div>
          <button class="btn orange" id="pOk">${icon('print', 17)} Imprimer la bande</button></div>`;
        const majColonnes = () => {
          const r = racks.find(x => x.rack === $('#pRack').value) || racks[0];
          $('#pCol').innerHTML = (r.liste_colonnes || []).map(c => `<option value="${c}">${c}</option>`).join('');
          majApercu();
        };
        const majApercu = async () => {
          const emps = await apiAll(`/emplacements/?rack=${encodeURIComponent($('#pRack').value)}&colonne=${$('#pCol').value}&ordering=code`).catch(() => []);
          // Dans l'ordre imprimé, pas dans l'ordre des codes : ce qu'on lit ici est
          // ce qui sortira, de haut en bas.
          const bande = bandesDepuisEmplacements(emps, $('#pRack').value)[0];
          $('#pApercu').textContent = bande
            ? `Bande de ${bande.codes.length} étiquette(s), de haut en bas : ${bande.codes.join(', ')}`
            : 'Aucun emplacement sur cette colonne.';
        };
        $('#pRack').onchange = majColonnes;
        $('#pCol').onchange = majApercu;
        $('#pOk').onclick = async () => {
          const rack = $('#pRack').value;
          const emps = await apiAll(`/emplacements/?rack=${encodeURIComponent(rack)}&colonne=${$('#pCol').value}&ordering=code`).catch(() => []);
          if (!emps.length) { toast('Aucun emplacement sur cette colonne.', 'err'); return; }
          imprimerBandes(bandesDepuisEmplacements(emps, rack),
                         `${rack} · colonne ${$('#pCol').value}`);
        };
        majColonnes();
      },

      rack: () => {
        if (!racks.length) { $('#pZone').innerHTML = sansRack; return; }
        $('#pZone').innerHTML = `<div class="card" style="margin-top:12px">
          ${choixRack('pRack2')}
          <div class="aide" id="pInfo"></div>
          <button class="btn orange" id="pOk2">${icon('print', 17)} Imprimer toutes les bandes</button></div>`;
        const maj = () => {
          const r = racks.find(x => x.rack === $('#pRack2').value) || racks[0];
          $('#pInfo').textContent = `${r.colonnes} bande(s) de ${r.niveaux} étiquette(s), soit ${r.emplacements} au total — environ ${Math.ceil(r.colonnes / 2)} feuille(s).`;
        };
        $('#pRack2').onchange = maj;
        $('#pOk2').onclick = async () => {
          const rack = $('#pRack2').value;
          const emps = await apiAll(`/emplacements/?rack=${encodeURIComponent(rack)}&ordering=code`).catch(() => []);
          if (!emps.length) { toast('Ce rack est vide.', 'err'); return; }
          imprimerBandes(bandesDepuisEmplacements(emps, rack), 'Rack ' + rack);
        };
        maj();
      },
    };

    zone.querySelectorAll('[data-portee]').forEach(b => b.onclick = () => {
      // Les non-sélectionnés redeviennent « ghost » : sans ce retour, le bouton
      // précédemment actif retombait sur le style plein par défaut et deux
      // portées semblaient sélectionnées en même temps.
      zone.querySelectorAll('[data-portee]').forEach(x => {
        x.classList.remove('orange');
        x.classList.add('ghost');
      });
      b.classList.remove('ghost');
      b.classList.add('orange');
      portees[b.dataset.portee]();
    });
    zone.querySelector('[data-portee="cellule"]').click();
  };
  if (VOLET_ARTICLES) { $('#ta').onclick = artMode; $('#te').onclick = empMode; artMode(); }
  else { empMode(); }
}

/* ============================ CABINES =======================================
   Écrans du suivi de cabines : emplacement scanné (ranger / sortir avec places
   G-M-D), fiche cabine avec historique, recherche par numéro, recherche par
   chantier, archives des cabines envoyées, journal, zones.                    */

let REFS_CABINE = { statuts: [], types: [], places: [] };

//: Cabine en attente d'un emplacement : posée par « Scanner l'emplacement » depuis
//: l'écran Entrée ou une fiche cabine. Le scan suivant la range directement, sans
//: qu'il faille la rechercher — c'est le parcours « fiche d'abord, place ensuite ».
let CABINE_A_RANGER = null;

/* --- Un seul chemin d'entrée -----------------------------------------------

   Trois écrans créaient une cabine à la volée, depuis les huit champs lus sur
   la photo de la fiche : « Ranger », le scan d'un emplacement, et la saisie du
   numéro à la main. C'était le bon geste tant que la fiche papier était la
   seule source d'information.

   Elle ne l'est plus. Le fichier de production annonce chaque cabine avec ses
   caractéristiques exactes. Créer depuis une photo revient désormais à
   fabriquer une fiche approximative — la reconnaissance confond 0 et O, 1 et
   I — à côté d'une fiche juste que le WMS possède déjà. Et une cabine née au
   pied du rack n'a jamais figuré nulle part comme « arrivée ».

   Les écrans de rangement ne rangent donc que ce qui est DÉJÀ en stock. Une
   cabine inconnue renvoie à l'entrée, avec son numéro déjà saisi : c'est un
   aiguillage, pas un cul-de-sac.                                             */

//: Numéro à reprendre au prochain passage sur l'écran d'entrée. Consommé une
//: seule fois, comme `CABINE_A_RANGER` : un numéro qui resterait collé
//: rouvrirait la même cabine à chaque visite de l'écran.
let ENTREE_NUMERO = null;

/** Écrit le refus dans `zone` et branche le renvoi vers l'entrée. */
function afficherCabineAbsente(zone, numero, options = {}) {
  if (!zone) return;
  const num = (numero || '').trim();
  zone.innerHTML = `<div class="card" style="margin-top:10px">
      <div class="banner">La cabine <b>${esc(num || '?')}</b> n’est pas en stock :
        elle n’a jamais été enregistrée à l’entrée. ${esc(options.geste || 'Le rangement')}
        ne la crée pas.</div>
      <div class="meta">Passe par « Entrée d’une cabine » : tape ce numéro, et ses
        caractéristiques viennent du fichier de production — rien à recopier.</div>
      ${peut('cab') ? '<button class="btn orange" data-entree>Aller à l’entrée avec ce numéro</button>' : ''}
      <button class="btn ghost" data-refaire>Une autre cabine</button>
    </div>`;
  const aller = zone.querySelector('[data-entree]');
  if (aller) aller.onclick = () => { ENTREE_NUMERO = num; go('entree'); };
  const refaire = zone.querySelector('[data-refaire]');
  if (refaire) refaire.onclick = options.refaire || (() => go(ECRAN));
}

/* --- Récents de cabines ------------------------------------------------------
   Stockés à part des récents d'articles : mélanger les deux faisait réapparaître
   des références de vitrage dans le scanner de cabines.

   Ce que le navigateur retient, ce sont des IDENTIFIANTS, pas un état. La liste
   était pourtant affichée telle quelle, avec le statut et la position figés au
   moment du clic. Résultat au poste : des cabines déjà envoyées présentées comme
   étant en stock, des cabines supprimées d'une remise à zéro toujours proposées,
   et un badge « Libre » alors que ce statut s'appelle « Conforme » depuis
   son renommage — trois manières de faire croire à un stock qui n'existe pas.

   La liste est donc relue auprès du serveur avant d'être montrée. Ce qui a
   disparu est oublié, ce qui est parti rejoint les archives et sort d'ici.     */
//: Ce qui est retenu d'une cabine consultée. `id` suffirait, le reste évite un
//: écran vide le temps de la relecture.
const CHAMPS_RECENT = ['id', 'numero', 'chantier', 'modele', 'statut', 'statut_libelle',
                       'type_cabine', 'position', 'zone_nom', 'rangee', 'rangement_libelle',
                       'emplacement_code', 'etape_libelle'];

function recentsCabines() {
  try { return JSON.parse(localStorage.getItem('wms_recents_cab') || '[]'); } catch (_) { return []; }
}

function ecrireRecentsCabines(liste) {
  try { localStorage.setItem('wms_recents_cab', JSON.stringify(liste.slice(0, RECENTS_MAX))); } catch (_) {}
}

/** Récents relus auprès du serveur. Une seule requête, quel qu'en soit le nombre.
    En cas de panne réseau on rend ce qu'on a : mieux vaut une liste datée qu'un
    écran vide, et l'ouverture de la fiche dira la vérité. */
async function recentsCabinesAJour() {
  const memoire = recentsCabines();
  const ids = memoire.map(c => c.id).filter(Boolean);
  if (!ids.length) return [];
  let frais;
  try {
    frais = (await api('/cabines/?toutes=1&ids=' + ids.join(','))).results || [];
  } catch (_) {
    return memoire;
  }
  const par = new Map(frais.map(c => [String(c.id), c]));
  // L'ordre du navigateur est celui des consultations : on le garde.
  const garde = memoire.map(c => par.get(String(c.id))).filter(Boolean);
  ecrireRecentsCabines(garde.map(fiche => {
    const f = {};
    CHAMPS_RECENT.forEach(k => f[k] = fiche[k]);
    return f;
  }));
  // Une cabine envoyée n'est plus au poste : elle se consulte dans les archives.
  return garde.filter(c => c.statut !== 'envoye');
}


function noterRecentCabine(c) {
  if (!c || !c.id) return;
  const fiche = {};
  CHAMPS_RECENT.forEach(k => fiche[k] = c[k]);
  const liste = recentsCabines().filter(x => x.id !== c.id);
  liste.unshift(fiche);
  ecrireRecentsCabines(liste);
}

// Une cabine supprimée qui resterait dans les « Récents » du scanner renverrait un
// 404 au premier clic, sans que l'opérateur comprenne pourquoi.
function oublierRecentCabine(c) {
  if (!c || !c.id) return;
  ecrireRecentsCabines(recentsCabines().filter(x => x.id !== c.id));
}

async function refsCabine() {
  if (!REFS_CABINE.statuts.length) {
    try { REFS_CABINE = await api('/referentiels-cabine/'); } catch (_) {}
  }
  return REFS_CABINE;
}

const CLASSE_STATUT = {
  libre: 'ok', quarantaine: 'crit', envoye: '',
};
//: Types qui circulent sans n° de chantier. Doit refléter Cabine.SANS_CHANTIER
//: côté serveur ; c'est lui qui tranche, ceci n'est qu'un texte d'aide.
const TYPES_SANS_CHANTIER = ['express', 'salon', 'occasion'];

/** Phrase d'aide sur l'obligation de chantier, construite depuis le référentiel. */
function aideChantier() {
  const noms = (REFS_CABINE.types || [])
    .filter(t => TYPES_SANS_CHANTIER.includes(t.code))
    .map(t => t.libelle);
  const liste = noms.length ? noms.join(', ') : 'express';
  return `Obligatoire, sauf pour les types : ${liste}. `
       + 'Dans tous les cas, il est exigé pour sortir la cabine de l’entrepôt.';
}

/** Pastille de type, pour tout type qui n'est pas « Normale ».

    Avant, seul « express » était signalé, en dur. Salon et occasion passaient
    donc pour des cabines normales à l'écran — alors que ce sont précisément les
    trois types qui circulent sans chantier, et qu'on aimerait repérer d'un coup
    d'œil dans une liste. Le libellé vient du serveur : ajouter un type ne
    demandera plus de retoucher l'interface. */
function pastilleType(c) {
  const t = c && c.type_cabine;
  if (!t || t === 'normale') return '';
  const ref = (REFS_CABINE.types || []).find(x => x.code === t);
  return `<span class="pill">${esc((ref && ref.libelle) || t)}</span>`;
}

/* Deux informations distinctes, deux pastilles. « Rangé » / « Non rangé » vient
   de l'emplacement — le serveur le calcule, personne ne le saisit — tandis que le
   statut dit l'état de la cabine. Les mélanger dans un seul champ laissait
   apparaître des cabines « Rangé » qui n'étaient nulle part.                   */
/* `rangement: false` retire la pastille « Rangée » : sur l'écran des gestes,
   la ligne d'en dessous dit déjà « Rangée en A-01-2 ». Deux fois le même mot
   à trois centimètres d'écart se lit comme deux informations, et on cherche
   la différence. */
const badgeStatut = (c, options = {}) => {
  const range = (options.rangement !== false && c.rangement_libelle !== undefined)
    ? `<span class="etat ${c.rangee ? 'ok' : ''}">${esc(c.rangement_libelle)}</span> `
    : '';
  return range + `<span class="etat ${CLASSE_STATUT[c.statut] || ''}">${esc(c.statut_libelle || c.statut)}</span>`;
};

const ligneCabine = (c) => `<div class="item" data-id="${c.id}" data-cle="${c.id}">
  <div class="r">${esc(c.numero)} ${badgeStatut(c)}${pastilleType(c)}</div>
  <div class="d">Chantier ${c.chantier ? esc(c.chantier) : '<em>à affecter</em>'}${c.modele ? ' · ' + esc(c.modele) : ''}</div>
  <div class="meta">${c.etape_libelle ? esc(c.etape_libelle) + ' · ' : ''}${c.position ? esc((c.zone_nom ? c.zone_nom + ' / ' : '') + c.position) : 'non rangée'}</div>
</div>`;

// --- Emplacement scanné : les deux options demandées, ranger et sortir -------
async function montrerEmplacement(emp, opts = {}) {
  const zone = $('#zone');
  // Toutes les re-lectures de l'écran repassent par ici : sans cela, la première
  // action (ranger, sortir) perdait les options et faisait réapparaître le bouton
  // de réglage au milieu de la fiche, qui en porte déjà un.
  const redessiner = () => montrerEmplacement(emp, opts);
  if (!zone) return;
  zone.innerHTML = '<div class="empty">Chargement…</div>';
  await refsCabine();   // sinon les places s'affichent « G — G » au lieu de « G — Gauche »
  try {
    const d = await api(`/emplacements/${emp.id}/places/`);
    // Deux modes : trois places nommées, ou capacité illimitée sans place.
    const occupants = d.illimite
      ? (d.cabines || []).map(c => ({ code: '—', cabine: c }))
      : d.places.filter(p => !p.libre);
    const contenu = d.illimite
      ? ((d.cabines || []).length
          ? d.cabines.map(c => `<div class="item" style="cursor:default">
              <div class="r">${esc(c.numero)} <span class="etat ${CLASSE_STATUT[c.statut] || ''}">${esc(c.statut_libelle || c.statut)}</span></div>
              <div class="d">Chantier ${c.chantier ? esc(c.chantier) : '<em>à affecter</em>'}</div></div>`).join('')
          : '<div class="empty">Aucune cabine ici.</div>')
      : d.places.map(p => `<div class="item" style="cursor:default">
          <div class="r">${p.code} — ${esc(p.libelle)} ${p.libre ? '<span class="etat ok">libre</span>' : '<span class="etat att">occupée</span>'}</div>
          ${p.cabine ? `<div class="d">${esc(p.cabine.numero)} · chantier ${p.cabine.chantier || '—'}</div>` : ''}
        </div>`).join('');
    zone.innerHTML = `
      <div class="card"><div class="muted small">${esc(d.zone || 'Sans zone')}</div>
        <div class="r" style="font-size:17px;font-weight:700">Emplacement ${esc(d.code)}</div>
        <div class="meta" style="margin-top:3px">${esc(d.mode_libelle)}${d.illimite ? ` · ${d.nb_cabines} cabine${d.nb_cabines === 1 ? '' : 's'}` : ''}</div>
        <div class="list" style="margin-top:10px">${contenu}</div>
        ${peut('cab') ? `
          ${d.complet ? '' : `<button class="btn orange btn-fiche" id="eFiche">${icon('fiche', 20)} Scanner la fiche de la cabine</button>
          <div class="meta" style="margin-top:5px;text-align:center">Photographie le tableau collé sur la cabine : le n° est lu tout seul.</div>`}
          <div class="row" style="margin-top:12px">
          <button class="btn ghost" id="eRanger" ${d.complet ? 'disabled style="opacity:.45"' : ''}>Saisir le n° à la main</button>
          <button class="btn ghost" id="eSortir" ${occupants.length ? '' : 'disabled style="opacity:.45"'}>Sortir et envoyer</button>
        </div>` : ''}
        ${d.complet ? '<div class="banner" style="margin:12px 0 0">Les trois places sont occupées : impossible de ranger ici.</div>' : ''}
        <div id="eAct"></div></div>
      ${(peut('ref') && !opts.sansReglages) ? `<button class="btn ghost" id="eReglage" style="margin-top:12px">${icon('cog', 17)} Régler / supprimer cet emplacement</button>` : ''}`;

    // Un seul formulaire de réglage dans toute l'application : celui de la fiche.
    // Il y en avait trois, avec des champs différents — on ne savait plus lequel
    // faisait foi, et aucun ne permettait de supprimer.
    if (peut('ref') && !opts.sansReglages) {
      $('#eReglage').onclick = () => ficheEmplacement(emp, opts.retour || renderEmplacements);
    }

    if (!peut('cab')) return;

    // Parcours « fiche cabine d'abord » : une cabine attend une place, on la range
    // sans la rechercher. Le scan de l'emplacement suffit.
    if (CABINE_A_RANGER) {
      const c = CABINE_A_RANGER;
      const dejaLa = (d.cabines || []).some(x => x.id === c.id);
      if (!dejaLa && !d.complet) {
        $('#eAct').innerHTML = `<div class="banner" style="margin-top:12px">Cabine ${esc(c.numero)} en attente de rangement.</div>
          ${d.illimite ? '' : `<label>Place</label><select id="wPlace">${d.libres.map(p => `<option value="${p}">${p}</option>`).join('')}</select>`}
          <div class="row" style="margin-top:10px">
            <button class="btn orange" id="wOk" style="margin-top:0">Ranger ici</button>
            <button class="btn ghost" id="wNon" style="margin-top:0">Annuler</button>
          </div>`;
        $('#wNon').onclick = () => { CABINE_A_RANGER = null; redessiner(); };
        $('#wOk').onclick = async () => {
          try {
            const corps = { emplacement: emp.id };
            if (!d.illimite) corps.place = $('#wPlace').value;
            await api(`/cabines/${c.id}/ranger/`, { method: 'POST', body: corps });
            toast('Cabine ' + c.numero + ' rangée', 'ok');
            CABINE_A_RANGER = null;
            ouvrirStatut(c, `Rangée en ${d.code}${corps.place ? ' · place ' + corps.place : ''}. Quel est son état ?`,
                         () => redessiner());
          } catch (e) { toast(e.message, 'err'); }
        };
      } else if (d.complet) {
        $('#eAct').innerHTML = `<div class="banner" style="margin-top:12px">Cabine ${esc(c.numero)} en attente, mais cet emplacement est complet : scanne-en un autre.</div>`;
      }
    }

    // Parcours du cariste : il a scanné l'emplacement, il photographie la fiche.
    // Le n° de cabine est lu sur la photo, la cabine est reconnue ou créée, il ne
    // reste qu'à toucher la place. Trois gestes, aucune saisie au clavier.
    if ($('#eFiche')) $('#eFiche').onclick = () => ouvrirScanFiche(emp, d, redessiner);

    $('#eRanger').onclick = () => {
      if (d.complet) return;
      $('#eAct').innerHTML = `<div class="sec">Quelle cabine ranger ?</div>
        <input id="cq" placeholder="N° de cabine (ex. 00_00_01)"><div class="list" id="cres"></div><div id="cform"></div>`;
      const champ = masquerNumero($('#cq'));
      champ.setAttribute('autocomplete', 'off');
      champ.focus();
      champ.oninput = debounce(async () => {
        const t = champ.value.trim();
        if (t.length < 2) { $('#cres').innerHTML = ''; return; }
        try {
          const res = (await api('/cabines/?numero=' + encodeURIComponent(t))).results || [];
          $('#cres').innerHTML = res.length ? res.slice(0, 6).map(ligneCabine).join('')
            : '<div class="empty">Aucune cabine</div>';
          $('#cres').querySelectorAll('.item').forEach(it => it.onclick = () => {
            const cab = res.find(x => String(x.id) === it.dataset.id);
            $('#cres').innerHTML = '';
            champ.value = cab.numero;
            // En capacité illimitée il n'y a pas de place à choisir.
            $('#cform').innerHTML = (d.illimite ? '' : `<label>Place</label>
              <select id="cplace">${d.libres.map(p => `<option value="${p}">${p} — ${esc((REFS_CABINE.places.find(x => x.code === p) || {}).libelle || p)}</option>`).join('')}</select>`)
              + `<button class="btn orange" id="cok">Ranger ${esc(cab.numero)}</button>`;
            $('#cok').onclick = async () => {
              try {
                const corps = { emplacement: emp.id };
                if (!d.illimite) corps.place = $('#cplace').value;
                await api(`/cabines/${cab.id}/ranger/`, { method: 'POST', body: corps });
                toast('Cabine rangée', 'ok');
                ouvrirStatut(cab, `Rangée en ${d.code}${corps.place ? ' · place ' + corps.place : ''}. Quel est son état ?`,
                             () => redessiner());
              } catch (e) { toast(e.message, 'err'); }
            };
          });
        } catch (e) { toast(e.message, 'err'); }
      }, 250);
    };

    $('#eSortir').onclick = () => {
      $('#eAct').innerHTML = `<div class="sec">Quelle cabine sortir ?</div>
        <div class="banner">Sortir une cabine, c'est l'<b>envoyer</b> : définitif.</div>
        <div class="list">${occupants.map(p => `<div class="item" data-cab="${p.cabine.id}">
          <div class="r">${d.illimite ? '' : p.code + ' · '}${esc(p.cabine.numero)} ${badgeStatut(p.cabine)}</div>
          <div class="d">Chantier ${p.cabine.chantier ? esc(p.cabine.chantier) : '<em>à affecter</em>'}</div></div>`).join('')}</div>
        <div id="sform"></div>`;
      $('#eAct').querySelectorAll('[data-cab]').forEach(it => it.onclick = async () => {
        const cab = occupants.find(p => String(p.cabine.id) === it.dataset.cab).cabine;
        if (!cab.chantier) {
          // Règle métier : pas de sortie sans chantier, quel que soit le type.
          $('#sform').innerHTML = `<div class="banner">Cette cabine n’a pas de chantier : affecte-le avant de l’envoyer.</div>
            <label>N° de chantier (6 chiffres)</label><input id="scha" inputmode="numeric" placeholder="000123">
            <button class="btn orange" id="sok">Affecter puis envoyer</button>`;
          $('#sok').onclick = async () => {
            try {
              await api(`/cabines/${cab.id}/chantier/`, { method: 'POST', body: { chantier: $('#scha').value } });
              if (!(await envoyerCabine(cab))) return;
              toast(cab.numero + ' envoyée', 'ok');
              redessiner();
            } catch (e) { toast(e.message, 'err'); }
          };
          return;
        }
        try {
          if (!(await envoyerCabine(cab))) return;
          toast(cab.numero + ' envoyée — ' + d.code + ' libéré', 'ok');
          redessiner();
        } catch (e) { toast(e.message, 'err'); }
      });
    };
  } catch (e) { zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

/* --- Ranger depuis la fiche papier ------------------------------------------
   Le parcours du cariste, dans l'ordre où il le vit : il scanne l'étiquette du
   rack, il photographie la fiche collée sur la cabine, il touche la place. Rien
   d'autre. Avant, il fallait connaître le n° de cabine et le taper au clavier,
   au milieu de l'entrepôt — c'est là que naissaient les erreurs de saisie et les
   cabines rangées sous un numéro voisin.

   La photo est lue par le serveur (`/cabines/lire-fiche/`), qui ne crée rien :
   ce qui a été lu est réaffiché pour relecture. L'OCR confond 0 et O, et une
   cabine enregistrée sous un mauvais numéro est introuvable ensuite.           */

/** Qui occupe la place, en trois mots. « occupée » ne disait pas assez : devant
    le rack, savoir QUELLE cabine est là évite d'aller vérifier à la main. */
function occupantCourt(p) {
  return p.cabine ? p.cabine.numero : 'occupée';
}

function placesHTML(d, choisie) {
  if (d.illimite) return '';
  const libelle = (code) => ((REFS_CABINE.places || []).find(x => x.code === code) || {}).libelle || code;
  return `<label>Sous-emplacement</label>
    <div class="places" id="places">${(d.places || []).map(p => {
      const libre = p.libre;
      return `<button type="button" class="place" data-place="${p.code}" ${libre ? '' : 'disabled'}
        aria-pressed="${String(p.code === choisie)}">
        <span class="c">${esc(p.code)}</span>
        <span class="l">${esc(libelle(p.code))}</span>
        <span class="l">${libre ? 'libre' : esc(occupantCourt(p))}</span></button>`;
    }).join('')}</div>`;
}

/** Rend les cases cliquables et renvoie la lecture de la place retenue.
 *
 *  Aucune place n'est pré-sélectionnée, volontairement. La version précédente
 *  cochait la première libre : un cariste pressé validait sans regarder, et la
 *  cabine était enregistrée à gauche alors qu'il l'avait posée à droite. Une
 *  erreur muette, découverte des semaines plus tard en cherchant la cabine.
 *  Le geste doit être explicite ; `surChoix` permet à l'appelant de n'activer
 *  son bouton qu'à ce moment-là.
 */
function brancherPlaces(d, surChoix) {
  if (d.illimite) { if (surChoix) surChoix(null); return () => null; }
  let choisie = null;
  const cases = Array.from(document.querySelectorAll('#places .place'));
  cases.forEach(b => {
    b.setAttribute('aria-pressed', 'false');
    if (b.disabled) return;
    b.onclick = () => {
      choisie = b.dataset.place;
      cases.forEach(x => x.setAttribute('aria-pressed', String(x.dataset.place === choisie)));
      if (surChoix) surChoix(choisie);
    };
  });
  return () => choisie;
}

/** Libellé court d'un champ de fiche, pour un message. */
function etiquetteChamp(cle) {
  const e = CHAMPS_ENTREE.find(([c]) => c === cle);
  return e ? e[1].replace(/ \*$/, '').replace(/\s*\([^)]*\)/, '') : cle;
}

async function ouvrirScanFiche(emp, d, redessiner) {
  const zone = $('#eAct');
  if (!zone) return;
  zone.innerHTML = `<div class="sec" style="margin-top:14px">Fiche de la cabine</div>
    ${blocCameraHTML('Photographier la fiche', 'Le tableau à deux colonnes, bien à plat')}
    <label class="fichier" id="fLabel">${icon('camera', 19)} <span>Prendre la photo</span>
      <input type="file" id="fPhoto" accept="image/*" capture="environment"></label>
    <div id="fEtat"></div><div id="fSuite"></div>
    <button class="btn ghost" id="fNon" style="margin-top:10px">Annuler</button>`;

  // La lecture d'un QR reste possible ici : certaines cabines portent déjà
  // l'étiquette imprimée par le WMS, plus fiable qu'une photo de la fiche.
  brancherCamera(async (texte) => {
    const ref = String(texte || '').replace(/^(CAB|ART|LOC):/i, '').trim();
    const res = (await api('/cabines/?toutes=1&numero=' + encodeURIComponent(ref))
      .then(x => x.results || []).catch(() => []));
    const c = res.find(x => (x.numero || '').toUpperCase() === ref.toUpperCase());
    if (c) proposerRangement(c, emp, d, redessiner);
    else toast('Aucune cabine ne porte le n° « ' + ref + ' »', 'err');
  });

  $('#fNon').onclick = () => { arreterCamera(); redessiner(); };
  $('#fPhoto').onchange = (ev) => lireFichePourRangement(ev.target.files[0], emp, d, redessiner);
}

async function lireFichePourRangement(fichier, emp, d, redessiner) {
  if (!fichier) return;
  const etat = $('#fEtat');
  etat.innerHTML = '<div class="meta">Lecture de la photo en cours… (quelques secondes)</div>';
  try {
    const r = await fetchReseau(API + '/cabines/lire-fiche/', {
      method: 'POST',
      headers: token ? { Authorization: 'Token ' + token } : {},
      body: (() => { const c = new FormData(); c.append('photo', fichier); return c; })(),
    });
    const txt = await r.text();
    let rep = null;
    try { rep = txt ? JSON.parse(txt) : null; } catch (_) { throw new Error('Réponse illisible du serveur.'); }
    if (!r.ok) throw new Error(messageErreur(rep, r.status));

    if (rep.cabine_existante) {
      etat.innerHTML = `<div class="banner" style="background:var(--ok-tint);color:var(--ok)">
        Cabine ${esc(rep.cabine_existante.numero)} reconnue sur la fiche.</div>`;
      proposerRangement(rep.cabine_existante, emp, d, redessiner, '#fSuite');
      return;
    }
    if (!rep.champs || !rep.champs.numero) {
      // Un « non lu » sec est un cul-de-sac : on ne sait pas si la photo était floue,
      // si le moteur n'a rien vu, ou s'il a lu autre chose. On montre donc CE QU'IL A
      // LU, et on offre de reprendre la main sans recommencer le parcours.
      const autres = Object.entries(rep.champs || {})
        .filter(([, v]) => v).map(([k, v]) => `${etiquetteChamp(k)} : ${esc(v)}`);
      etat.innerHTML = `<div class="banner">Le n° de cabine n’a pas été lu sur la photo.
          Reprends-la à plat et bien éclairée, ou saisis le numéro ci-dessous.</div>
        ${autres.length ? `<div class="meta" style="margin-top:8px">Lu malgré tout : ${autres.join(' · ')}</div>` : ''}
        <details style="margin-top:8px"><summary class="meta">Ce que le serveur a lu sur la photo</summary>
          <pre class="ocr-brut">${esc(rep.texte || '(aucun texte)')}</pre></details>
        <label style="margin-top:10px">N° de cabine</label>
        <input id="fNum" placeholder="Ex. 26_03_47" autocomplete="off">
        <button class="btn" id="fNumOk">Continuer avec ce numéro</button>`;
      $('#fNumOk').onclick = async () => {
        const num = ($('#fNum').value || '').trim();
        if (!num) { toast('Saisis le n° de cabine.', 'err'); return; }
        const res = await api('/cabines/?toutes=1&numero=' + encodeURIComponent(num))
          .then(x => x.results || []).catch(() => []);
        const c = res.find(x => (x.numero || '').toUpperCase() === num.toUpperCase());
        if (c) { proposerRangement(c, emp, d, redessiner); return; }
        // Inconnue : cet écran ne crée pas de cabine, il aiguille vers l'entrée.
        replierPriseDeVue();
        afficherCabineAbsente($('#fSuite'), num, { refaire: redessiner });
      };
      masquerNumero($('#fNum')).focus();
      return;
    }
    // Cabine inconnue : elle n'est pas en stock, donc rien à ranger ici.
    etat.innerHTML = '';
    replierPriseDeVue();
    afficherCabineAbsente($('#fSuite'), rep.champs.numero, { refaire: redessiner });
  } catch (e) {
    etat.innerHTML = `<div class="banner">${esc(e.message)}<br>Utilise « Saisir le n° à la main ».</div>`;
  }
}

/* --- La boîte de statut, après chaque geste --------------------------------
   Une cabine qu'on vient de poser ou de sortir a presque toujours un état à
   déclarer : elle est conforme, elle part en quarantaine, ou elle quitte
   l'entrepôt. Le demander APRÈS le geste, sur l'écran où le cariste est déjà,
   évite le détour par la fiche — détour que personne ne faisait, si bien que le
   statut restait celui de la veille.

   « Rangé » et « Non rangé » n'y figurent pas : le WMS les déduit de
   l'emplacement. Les proposer laisserait déclarer « Non rangé » une cabine qu'on
   vient de poser, et le WMS se contredirait lui-même.

   « Envoyée » passe par `/envoyer/`, pas par `/statut/` : c'est cette opération
   qui vide l'emplacement tout en conservant la trace au journal.              */

//: Ce que la boîte propose. L'ordre est celui du poste : le cas courant d'abord.
const STATUTS_PROPOSES = [
  // Lever une quarantaine, c'est revenir ici : la cabine redevient conforme.
  // Un statut « Levée de quarantaine » distinct
  // laissait des cabines saines marquées d'un libellé alarmant pendant des
  // semaines, sans rien apprendre de plus — le passage par la quarantaine est
  // écrit au journal, avec son motif et sa date.
  ['libre',       'Conforme',              'Aucun défaut, ou quarantaine levée : elle reste en stock.'],
  ['quarantaine', 'En quarantaine',         'Bloquée : un défaut à traiter avant tout départ.'],
  ['envoye',      'Envoyée',                'Elle quitte l’entrepôt : ses emplacements se libèrent, le journal garde la trace.'],
];

/** Le geste, du point de vue de l'operateur : « lever » plutot que « conforme ».

    Un etat se nomme au repos ; une action se nomme par son verbe. Le bouton dit
    ce qu'il va faire, ce qui est la seule chose qu'on lise avant d'appuyer. */
function verbeStatut(cabine, code) {
  if (code === 'quarantaine') return 'Mettre en quarantaine';
  if (code === 'libre') {
    return cabine.statut === 'quarantaine' ? 'Lever la quarantaine' : 'Déclarer conforme';
  }
  const ref = STATUTS_PROPOSES.find(s => s[0] === code);
  return ref ? ref[1] : code;
}

/** Change le statut, mais seulement apres confirmation.

    Il y avait sur la fiche une liste deroulante qui, le statut courant et
    l'envoi retires, ne contenait jamais qu'UN choix : on deroulait pour tomber
    sur une seule ligne, et le bouton d'a cote ecrivait aussitot. Un bouton par
    etat possible, nomme par son verbe, et une confirmation qui rappelle ce que
    l'etat veut dire — le motif se saisit la, au moment ou on sait pourquoi. */
async function confirmerChangementStatut(cabine, code, apres) {
  const ref = STATUTS_PROPOSES.find(s => s[0] === code) || [code, code, ''];
  const rep = await confirmer({
    titre: verbeStatut(cabine, code) + ' ?',
    texte: `${cabine.numero} — ${ref[2]}`,
    ok: 'Confirmer',
    danger: code === 'quarantaine',
    champ: { libelle: 'Motif (facultatif, conservé dans l’historique)',
             placeholder: 'Ex. rayure sur la paroi' },
  });
  if (!rep || !rep.ok) return;
  try {
    await api(`/cabines/${cabine.id}/statut/`, { method: 'POST',
      body: { statut: code, motif: rep.valeur } });
    toast(`${cabine.numero} : ${ref[1]}`, 'ok');
    if (apres) apres();
  } catch (e) { toast(e.message, 'err'); }
}

/**
 * Ouvre la boîte de choix du statut.
 * `contexte` : phrase d'introduction. `apres` : rappelé quand c'est fait ou passé.
 * `opts.statuts` : codes autorisés — tous par défaut.
 *
 * Le choix se restreint parce que le moment le restreint. Au sortir d'un
 * rangement, la question posée est « comment est-elle ? » ; « Envoyée » y
 * répondait par un départ, juste après qu'on l'a posée dans la travée — un
 * geste que rien ne distinguait des deux autres, dans la même liste.
 */
function ouvrirStatut(cabine, contexte, apres, opts = {}) {
  const actuel = cabine.statut;
  const proposes = opts.statuts
    ? STATUTS_PROPOSES.filter(([code]) => opts.statuts.includes(code))
    : STATUTS_PROPOSES;
  modale(`Statut de ${esc(cabine.numero)}`, `
    <div class="meta">${esc(contexte)}</div>
    <div class="statuts" id="stListe">${proposes.map(([code, nom, aide]) => `
      <button type="button" class="statut" data-st="${code}" aria-pressed="${String(code === actuel)}">
        <span class="n">${esc(nom)}${code === actuel ? ' <span class="pill">actuel</span>' : ''}</span>
        <span class="a">${esc(aide)}</span>
      </button>`).join('')}</div>
    <label style="margin-top:12px">Motif (facultatif)</label>
    <input id="stMotif" placeholder="Ex. rayure sur la paroi" autocomplete="off">
    <div class="row" style="margin-top:12px">
      <button class="btn orange" id="stOk" style="margin-top:0">Enregistrer le statut</button>
      <button class="btn ghost" id="stNon" style="margin-top:0">Laisser tel quel</button>
    </div>`);

  let choisi = actuel;
  const cases = Array.from(document.querySelectorAll('#stListe .statut'));
  cases.forEach(b => b.onclick = () => {
    choisi = b.dataset.st;
    cases.forEach(x => x.setAttribute('aria-pressed', String(x.dataset.st === choisi)));
  });

  $('#stNon').onclick = () => { fermerModale(); if (apres) apres(null); };
  $('#stOk').onclick = async () => {
    const motif = ($('#stMotif').value || '').trim();
    if (choisi === actuel) { fermerModale(); if (apres) apres(null); return; }
    try {
      if (choisi === 'envoye') {
        if (!(await envoyerCabine(cabine, { note: motif }))) return;
        toast('Cabine ' + cabine.numero + ' envoyée — emplacements libérés', 'ok');
      } else {
        await api(`/cabines/${cabine.id}/statut/`, { method: 'POST', body: { statut: choisi, motif } });
        const nom = (proposes.find(s => s[0] === choisi) || [])[1] || choisi;
        toast(cabine.numero + ' : ' + nom, 'ok');
      }
      fermerModale();
      if (apres) apres(choisi);
    } catch (e) { toast(e.message, 'err'); }
  };
}

/** Range la zone de prise de vue : la cabine est identifiée, on passe à la place. */
function replierPriseDeVue() {
  arreterCamera();
  const cam = $('#cam'), lab = $('#fLabel');
  if (cam) cam.hidden = true;
  if (lab) lab.hidden = true;
}

/** Cabine connue : il ne reste que la place à toucher. */
function proposerRangement(cabine, emp, d, redessiner, cible) {
  const zone = $(cible || '#fSuite') || $('#eAct');
  if (!zone) return;
  replierPriseDeVue();
  // Une cabine n'occupe aujourd'hui qu'UN emplacement : la ranger ailleurs la
  // DÉPLACE. Sans cet avertissement, rescanner la même fiche à un second rack
  // vidait le premier en silence — et personne ne s'en apercevait avant d'aller
  // chercher la cabine là où elle n'était plus.
  const ailleurs = cabine.emplacement && cabine.emplacement_code
                   && cabine.emplacement_code !== d.code;
  zone.innerHTML = `<div class="card" style="margin-top:10px">
      <div class="r" style="font-size:16px;font-weight:700">${esc(cabine.numero)} ${badgeStatut(cabine)}</div>
      <div class="d">Chantier ${cabine.chantier ? esc(cabine.chantier) : '<em>à affecter</em>'}${cabine.modele ? ' · ' + esc(cabine.modele) : ''}</div>
      ${ailleurs ? `<div class="banner" style="margin-top:10px">Cette cabine est
          actuellement en <b>${esc(cabine.emplacement_code)}</b>${cabine.place ? ' · place ' + esc(cabine.place) : ''}.
          La ranger ici la <b>déplace</b> : ${esc(cabine.emplacement_code)} sera libéré.</div>` : ''}
      ${placesHTML(d)}
      <button class="btn orange" id="pOk">${ailleurs
        ? 'Déplacer de ' + esc(cabine.emplacement_code) + ' vers ' + esc(d.code)
        : 'Ranger en ' + esc(d.code)}</button>
    </div>`;
  const bouton = $('#pOk');
  if (!d.illimite) { bouton.disabled = true; bouton.dataset.libelle = bouton.textContent; bouton.textContent = 'Touche une place libre'; }
  const place = brancherPlaces(d, () => {
    bouton.disabled = false;
    if (bouton.dataset.libelle) bouton.textContent = bouton.dataset.libelle;
  });
  bouton.onclick = async () => {
    try {
      const corps = { emplacement: emp.id };
      if (!d.illimite) corps.place = place();
      if (!d.illimite && !corps.place) { toast('Touche la place où tu poses la cabine.', 'err'); return; }
      await api(`/cabines/${cabine.id}/ranger/`, { method: 'POST', body: corps });
      toast('Cabine ' + cabine.numero + ' rangée en ' + d.code, 'ok');
      noterRecentCabine(cabine);
      arreterCamera();
      ouvrirStatut(cabine, `Rangée en ${d.code}${corps.place ? ' · place ' + corps.place : ''}. Quel est son état ?`,
                   () => redessiner());
    } catch (e) { toast(e.message, 'err'); }
  };
}

/* ===========================================================================
   RANGER UNE CABINE — le parcours du cariste, dans l'ordre où il travaille

   Trois étapes, dans l'ordre des gestes réels : il a la fiche sous les yeux au
   moment où il prend la cabine, il découvre l'emplacement en arrivant devant le
   rack, il voit la place libre en levant la tête.

   L'ancien parcours partait de l'emplacement. Il obligeait à décider où poser la
   cabine AVANT de savoir laquelle on transportait, et à revenir en arrière dès
   que la place visée était prise.

   Cet écran ne CRÉE plus de cabine : il ne range que ce qui est déjà en stock.
   Une cabine inconnue est refusée et renvoyée à l'écran d'entrée — voir
   `afficherCabineAbsente`.
   =========================================================================== */

/* --- Rangement en cours : il ne se perd plus --------------------------------
   `renderRangement()` remettait l'état à zéro à chaque ouverture de l'écran. Un
   doigt qui frôle un autre onglet — ou un téléphone qui se verrouille pendant
   qu'on marche jusqu'au rack — et la photo de la fiche, la cabine identifiée et
   l'emplacement scanné étaient perdus : tout était à refaire, sans que rien
   n'explique pourquoi.

   L'état survit donc au changement d'écran, et jusqu'au rechargement de la page
   (`sessionStorage`). Ce qu'il contient est du texte : la photo n'y est pas — une
   fois lue, elle ne sert plus. « Recommencer » reste à portée de doigt sur chaque
   étape, et le rangement se vide de lui-même une fois la cabine posée.         */
const RANGEMENT_NEUF = () => ({ cabine: null, emp: null, d: null, intention: null });
const CLE_RANGEMENT = 'wms_rangement_en_cours';

let RANGEMENT = RANGEMENT_NEUF();

/** Y a-t-il quelque chose à ne pas perdre ? */
const rangementCommence = (r) => Boolean(r && (r.cabine || r.emp));

function memoriserRangement() {
  try {
    if (rangementCommence(RANGEMENT)) {
      sessionStorage.setItem(CLE_RANGEMENT, JSON.stringify(RANGEMENT));
    } else {
      sessionStorage.removeItem(CLE_RANGEMENT);
    }
  } catch (_) {}
}

function relireRangement() {
  try {
    const brut = sessionStorage.getItem(CLE_RANGEMENT);
    if (!brut) return null;
    const r = JSON.parse(brut);
    return rangementCommence(r) ? Object.assign(RANGEMENT_NEUF(), r) : null;
  } catch (_) { return null; }
}

/** Remet le rangement à zéro — le seul endroit qui a le droit de le faire. */
function repartirRangement() {
  RANGEMENT = RANGEMENT_NEUF();
  memoriserRangement();
}

function filEtapes(courante) {
  return `<ol class="fil">${['Cabine', 'Emplacement', 'Place'].map((t, i) => {
    const n = i + 1;
    return `<li class="${n < courante ? 'fait' : (n === courante ? 'ici' : '')}">
      <span class="n">${n < courante ? '✓' : n}</span>${esc(t)}</li>`;
  }).join('')}</ol>`;
}

async function renderRangement() {
  if (!peut('cab')) {
    layout(`<h2 class="title">Ranger une cabine</h2>
      <div class="banner">Ton compte n’a pas le droit « cabines ». Demande-le à
      l’administrateur du WMS.</div>`, 'rangement');
    return;
  }
  await refsCabine();
  // Reprise : l'état en mémoire d'abord, puis celui de la session si l'écran
  // vient d'être rouvert après un rechargement.
  if (!rangementCommence(RANGEMENT)) RANGEMENT = relireRangement() || RANGEMENT_NEUF();
  layout(`<h2 class="title">Ranger une cabine</h2>
    <div id="fil"></div><div id="zone"></div>`, 'rangement');
  etapeRangement();
}

/** Aiguille vers l'étape en cours. Un seul endroit décide de l'avancement. */
function etapeRangement() {
  const fil = $('#fil');
  memoriserRangement();
  const poser = (n) => { if (fil) fil.innerHTML = filEtapes(n); };
  if (!RANGEMENT.cabine) { poser(1); return etapeFiche(); }
  // Cabine envoyée : le serveur refusera de la ranger. Le dire ici évite au
  // cariste de marcher jusqu'à la travée, de scanner et de toucher une place
  // pour n'apprendre qu'à la fin que le geste était impossible.
  if (RANGEMENT.cabine && RANGEMENT.cabine.statut === 'envoye') { poser(1); return etapeEnvoyee(); }
  // Cabine déjà rangée : le geste se choisit AVANT d'aller plus loin. L'écran
  // annonçait « ce nouvel emplacement s'ajoute » et offrait la caméra juste en
  // dessous : la conséquence était décidée sans que personne l'ait demandée, et
  // le seul bouton visible disait « Recommencer ». Tant que rien n'est choisi on
  // ne descend pas aux places — « ranger ici » n'y voudrait rien dire.
  if (RANGEMENT.cabine && cabineRangee(RANGEMENT.cabine) && !RANGEMENT.intention) {
    poser(2);
    return etapeEmplacement();
  }
  if (!RANGEMENT.emp) { poser(2); return etapeEmplacement(); }
  poser(3);
  return etapePlace();
}

/** Bandeau de rappel : ce qui est déjà acquis, et comment y revenir. */
function rappelRangement() {
  const c = RANGEMENT.cabine;
  if (!c) return '';
  const lignes = [`<div class="r">${esc(c.numero)} ${badgeStatut(c)}</div>`];
  const chantier = c.chantier;
  lignes.push(`<div class="d">Chantier ${chantier ? esc(chantier) : '<em>à affecter</em>'}</div>`);
  // Le geste retenu, en clair, et de quoi revenir dessus. Sans cette ligne on
  // arrivait à l'étape des places sans plus savoir ce qu'on avait choisi.
  if (RANGEMENT.intention && c && c.position) {
    const dit = RANGEMENT.intention === 'ajouter'
      ? `Déjà rangée en <b>${esc(c.position)}</b> — le nouvel emplacement s’<b>ajoute</b>.`
      : `Déjà rangée en <b>${esc(c.position)}</b> — elle sera <b>déplacée</b>.`;
    lignes.push(`<div class="meta">${dit}
      <button type="button" class="lien" id="rIntention">changer</button></div>`);
  }
  if (RANGEMENT.d) lignes.push(`<div class="meta">Emplacement ${esc(RANGEMENT.d.code)} · ${esc(RANGEMENT.d.zone || 'sans zone')}</div>`);
  return `<div class="card rappel">${lignes.join('')}
    <button class="btn ghost" id="rRepartir" style="margin-top:10px">Recommencer</button></div>`;
}

function brancherRappel() {
  const b = $('#rRepartir');
  if (b) b.onclick = () => { arreterCamera(); repartirRangement(); etapeRangement(); };
  // Changer de geste rend l'emplacement déjà scanné : il a été choisi pour un
  // déplacement, il n'a pas de raison de valoir pour un ajout.
  const chg = $('#rIntention');
  if (chg) chg.onclick = () => {
    arreterCamera();
    RANGEMENT.intention = null;
    RANGEMENT.emp = null;
    RANGEMENT.d = null;
    etapeRangement();
  };
}

/* --- Identifier une cabine par sa fiche ------------------------------------
   LE geste du poste. La fiche est collée sur la cabine : le cariste l'a sous
   les yeux au moment où il la prend, et il n'a rien d'autre.

   La lecture d'un QR de cabine reste dans le code, mais elle passe au second
   plan : elle suppose qu'une étiquette WMS a été imprimée et collée, ce qui
   n'est le cas d'aucune cabine aujourd'hui. La mettre en avant faisait chercher
   un QR qui n'existe pas.                                                     */
function blocFiche(titre) {
  return `<div class="card">
      <div class="sec" style="margin-top:0">${esc(titre)}</div>
      <label class="fichier btn-fiche" id="fLab">${icon('camera', 22)}
        <span>Photographier la fiche</span>
        <input type="file" id="fIn" accept="image/*" capture="environment"></label>
      <div class="meta" style="margin-top:6px;text-align:center">Le tableau à deux
        colonnes, bien à plat et éclairé.</div>
      <div id="fEtat"></div>
      <div class="sec" style="margin-top:18px">Ou saisir le numéro</div>
      <input id="fNum" placeholder="Ex. 26_03_47" autocomplete="off">
      <button class="btn ghost" id="fNumOk">Continuer</button>
    </div>`;
}

/** Branche le bloc ci-dessus. `surCabine(c)` : fiche reconnue. `surInconnue(champs)` :
 *  aucune cabine ne correspond — la sortie refuse, le rangement propose la création. */
function brancherBlocFiche(surCabine, surInconnue) {
  const chercher = async (numero, champs) => {
    try {
      const res = await api('/cabines/?toutes=1&numero=' + encodeURIComponent(numero))
        .then(x => x.results || []).catch(() => []);
      const c = res.find(x => (x.numero || '').toUpperCase() === numero.toUpperCase());
      await arreterCamera();
      if (c) { noterRecentCabine(c); surCabine(c); }
      else surInconnue(Object.assign({}, champs || {}, { numero }));
    } catch (e) { toast(e.message, 'err'); }
  };

  brancherCamera((texte) => {
    const ref = String(texte || '').replace(/^(CAB|ART|LOC):/i, '').trim();
    if (ref) chercher(ref);
  });
  masquerNumero($('#fNum'));
  $('#fNumOk').onclick = () => {
    const n = ($('#fNum').value || '').trim();
    if (!n) { toast('Saisis le n° de cabine.', 'err'); return; }
    chercher(n);
  };
  $('#fIn').onchange = (ev) => lireFiche(ev.target.files[0], surCabine, surInconnue, chercher);
}

/* --- Préparation de la photo avant envoi -------------------------------------
   Un téléphone Android rend un cliché de 12 Mpx, soit 4 à 8 Mo. Envoyé tel quel
   par le réseau de l'entrepôt, il met des dizaines de secondes et échoue souvent
   — c'est LA raison pour laquelle la lecture de fiche « marchait très mal » sur
   Android alors qu'elle passait sur iPhone, dont les clichés HEIC sont plus légers.

   On réduit donc côté téléphone à la taille que le serveur utilise de toute façon
   (il redimensionne à 1600 px de large avant de reconnaître le texte) : rien n'est
   perdu pour la reconnaissance, et le fichier passe de 6 Mo à 300 Ko environ.

   L'orientation EXIF est appliquée au passage (`imageOrientation: 'from-image'`) :
   une photo prise en portrait arrive couchée sur Android, et le texte devient
   illisible. En cas d'échec — vieux navigateur, format exotique — on envoie
   l'original : mieux vaut lent que rien.                                       */
const PHOTO_LARGEUR_MAX = 1600;
const PHOTO_QUALITE = 0.86;

async function preparerPhoto(fichier) {
  if (!fichier || !/^image\//.test(fichier.type || '')) return fichier;
  try {
    if (typeof createImageBitmap !== 'function' || !document.createElement('canvas').toBlob) {
      return fichier;
    }
    let bitmap;
    try {
      bitmap = await createImageBitmap(fichier, { imageOrientation: 'from-image' });
    } catch (_) {
      bitmap = await createImageBitmap(fichier);   // option non gérée : sans EXIF
    }
    const ratio = Math.min(1, PHOTO_LARGEUR_MAX / Math.max(bitmap.width, bitmap.height));
    // Déjà petite : la recompresser ne ferait que dégrader le texte.
    if (ratio === 1 && fichier.size < 900 * 1024) { bitmap.close && bitmap.close(); return fichier; }
    const toile = document.createElement('canvas');
    toile.width = Math.round(bitmap.width * ratio);
    toile.height = Math.round(bitmap.height * ratio);
    const ctx = toile.getContext('2d');
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap, 0, 0, toile.width, toile.height);
    bitmap.close && bitmap.close();
    const blob = await new Promise(r => toile.toBlob(r, 'image/jpeg', PHOTO_QUALITE));
    if (!blob || blob.size >= fichier.size) return fichier;
    return new File([blob], 'fiche.jpg', { type: 'image/jpeg' });
  } catch (_) {
    return fichier;
  }
}

const ko = (n) => Math.max(1, Math.round(n / 1024));

/** Envoie la photo, interprète la réponse. Commun au rangement et à la sortie. */
/* Une attente muette de plusieurs secondes ressemble à une panne. Le bandeau
   dit ce qui se passe, et la ligne qui le balaie dit que ça travaille encore —
   c'est le seul repère quand la reconnaissance prend dix secondes sur un
   téléphone. Elle s'arrête d'elle-même si l'appareil demande moins d'animation. */
const blocLecture = (titre, sous) => `<div class="lecture">
  <div class="l">${esc(titre)}</div><div class="s">${esc(sous)}</div></div>`;

async function lireFiche(fichier, surCabine, surInconnue, chercher) {
  if (!fichier) return;
  const etat = $('#fEtat');
  if (etat) etat.innerHTML = blocLecture('Préparation de la photo…',
    'Réduction avant l’envoi : l’image de l’appareil pèse trop lourd.');
  try {
    const photo = await preparerPhoto(fichier);
    if (etat) etat.innerHTML = blocLecture(`Lecture de la fiche…`,
      `${ko(photo.size)} Ko envoyés au serveur — quelques secondes.`);
    // Sans délai maximum, un réseau qui ne répond plus laisse « Lecture en
    // cours… » indéfiniment : l'opérateur attend devant un écran qui ne dira
    // jamais rien. Quarante-cinq secondes, puis on rend la main et la saisie.
    const minuteur = new AbortController();
    const stop = setTimeout(() => minuteur.abort(), 45000);
    let r;
    try {
      r = await fetch(API + '/cabines/lire-fiche/', {
        method: 'POST',
        signal: minuteur.signal,
        headers: token ? { Authorization: 'Token ' + token } : {},
        body: (() => { const c = new FormData(); c.append('photo', photo); return c; })(),
      });
    } catch (e) {
      throw new Error(e && e.name === 'AbortError'
        ? 'Le serveur n’a pas répondu en 45 secondes.'
        : 'Pas de réseau');
    } finally { clearTimeout(stop); }
    const txt = await r.text();
    let rep = null;
    try { rep = txt ? JSON.parse(txt) : null; } catch (_) { throw new Error('Réponse illisible du serveur.'); }
    if (!r.ok) throw new Error(messageErreur(rep, r.status));

    if (rep.cabine_existante) {
      await arreterCamera();
      noterRecentCabine(rep.cabine_existante);
      surCabine(rep.cabine_existante);
      return;
    }
    if (!rep.champs || !rep.champs.numero) {
      // Un « non lu » sec est un cul-de-sac : on montre CE QUI A ÉTÉ LU et on
      // rend la main, plutôt que de renvoyer au début.
      const autres = Object.entries(rep.champs || {})
        .filter(([, v]) => v).map(([k, v]) => `${etiquetteChamp(k)} : ${esc(v)}`);
      etat.innerHTML = `<div class="banner">Le n° de cabine n’a pas été lu. Reprends la
          photo à plat, ou saisis le numéro ci-dessous.</div>
        ${autres.length ? `<div class="meta" style="margin-top:8px">Lu malgré tout : ${autres.join(' · ')}</div>` : ''}
        <details style="margin-top:8px"><summary class="meta">Ce que le serveur a lu</summary>
          <pre class="ocr-brut">${esc(rep.texte || '(aucun texte)')}</pre></details>
        <label style="margin-top:10px">N° de cabine</label>
        <input id="fNum2" placeholder="Ex. 26_03_47" autocomplete="off">
        <button class="btn" id="fNum2Ok">Continuer avec ce numéro</button>`;
      $('#fNum2Ok').onclick = () => {
        const num = ($('#fNum2').value || '').trim();
        if (!num) { toast('Saisis le n° de cabine.', 'err'); return; }
        chercher(num, rep.champs);
      };
      masquerNumero($('#fNum2'));
      $('#fNum2').focus();
      return;
    }
    await arreterCamera();
    surInconnue(Object.assign({}, rep.champs));
  } catch (e) {
    if (etat) etat.innerHTML = `<div class="banner">${esc(e.message)}<br>Utilise la saisie manuelle ci-dessous.</div>`;
  }
}

/* --- Étape 1 : quelle cabine ? --------------------------------------------- */
function etapeFiche() {
  const zone = $('#zone');
  if (!zone) return;
  zone.innerHTML = blocFiche('Quelle cabine ?');
  brancherBlocFiche(
    (c) => { RANGEMENT.cabine = c; etapeRangement(); },
    // Inconnue du WMS : on refuse et on aiguille. Cet écran créait la cabine
    // depuis les huit champs de la photo — voir `afficherCabineAbsente`.
    (champs) => afficherCabineAbsente($('#zone'), champs && champs.numero,
                                      { refaire: () => { repartirRangement(); etapeRangement(); } }));
}

/** Une cabine est rangée dès qu'elle occupe un emplacement — c'est le serveur qui
    tranche (`rangee`). Le repli sur la position couvre les écrans allégés. */
const cabineRangee = (c) => Boolean(c && (c.rangee !== undefined
  ? c.rangee : (c.emplacement_code || c.position)));

/** Emplacements occupés par la cabine. Un seul, sauf exception. */
const emplacementsDe = (c) => ((c && c.occupations) || []).filter(x => x.range);

/* Fiche d'une cabine déjà partie.

   C'était une impasse : « elle ne peut plus être rangée », et rien d'autre. Or
   la cabine est là, sous les yeux du cariste, fiche en main. Une sortie faite par
   erreur, un retour de chantier, une livraison refusée — il faut pouvoir la
   remettre en stock. Refuser obligeait à recréer une fiche sous un autre numéro :
   deux historiques pour un seul objet, et un stock qui ment.

   La reprise ne cache rien : l'envoi reste au journal, le retour s'y ajoute. */
function etapeEnvoyee() {
  const zone = $('#zone');
  if (!zone) return;
  const c = RANGEMENT.cabine;
  zone.innerHTML = `<div class="card rappel">
      <div class="r" style="font-size:17px;font-weight:700">${esc(c.numero)} ${badgeStatut(c)}</div>
      <div class="d">Chantier ${c.chantier ? esc(c.chantier) : '<em>à affecter</em>'}${c.modele ? ' · ' + esc(c.modele) : ''}</div>
      <div class="banner" style="margin-top:10px">Cette cabine est <b>envoyée</b> :
        elle est sortie de l’entrepôt et ne fait plus partie du stock.</div>
      <div class="sec">Elle est pourtant devant toi ?</div>
      <button class="btn orange" id="djReprendre">La remettre en stock</button>
      <button class="btn ghost" id="djAutre">Autre cabine</button>
    </div>`;
  $('#djAutre').onclick = () => { arreterCamera(); repartirRangement(); etapeRangement(); };
  $('#djReprendre').onclick = async () => {
    const c2 = await reprendreCabine(c);
    if (!c2) return;
    RANGEMENT.cabine = c2;
    RANGEMENT.intention = null;
    etapeRangement();
  };
}

/** Confirmation, puis retour en stock. Rend la cabine relue, ou null si refus.
    Un seul endroit : la fiche et le parcours Ranger l'appellent tous les deux. */
async function reprendreCabine(c) {
  const ok = await confirmer({
    titre: `${c.numero} a été envoyée`,
    texte: 'Elle est sortie de l’entrepôt' + (c.envoi_date ? ` le ${dateCourte(c.envoi_date)}` : '')
         + '.\n\nLa remettre en stock la fait réapparaître dans les listes, non '
         + 'rangée : sa place d’avant a pu être réattribuée, c’est le rangement qui '
         + 'tranchera.\n\nL’envoi reste inscrit au journal ; le retour s’y ajoute.',
    ok: 'Oui, la remettre en stock',
    annuler: 'Non',
  });
  if (!ok) return null;
  try {
    await api(`/cabines/${c.id}/reprendre/`, { method: 'POST', body: {} });
    const frais = await api(`/cabines/${c.id}/`);
    noterRecentCabine(frais);
    toast(`${c.numero} remise en stock`, 'ok');
    return frais;
  } catch (e) { toast(e.message, 'err'); return null; }
}

/** Date seule, sans l'heure : « le 27/08/2026 ». */
function dateCourte(iso) {
  try { return new Date(iso).toLocaleDateString('fr-FR'); } catch (_) { return ''; }
}

/* --- Étape 1 ter : la cabine est déjà rangée --------------------------------
   Le cariste tient une fiche devant un rack. Le WMS sait déjà où est la cabine :
   la question n'est donc pas « où la ranger ? » mais « qu'est-ce que tu en
   fais ? ». Trois réponses, trois boutons, dans l'ordre de fréquence réelle au
   poste : on descend une cabine bien plus souvent qu'on ne la déplace.       */

/* --- Étape 2 : quel emplacement ? ------------------------------------------ */
/* --- Une cabine déjà rangée : trois gestes, chacun sous son nom ------------
   C'est l'écran qui a été signalé comme ambigu, et il l'était : il affirmait
   que le prochain emplacement s'ajouterait, proposait la caméra dessous, et
   n'offrait comme bouton que « Recommencer ». On scannait sans savoir ce qui
   allait arriver à la place déjà occupée.

   Les trois gestes possibles portent donc leur nom, avec leur conséquence
   écrite dessous, et rien ne se lance avant qu'on en ait touché un. « La
   sortir » n'a pas besoin d'emplacement : elle s'exécute là, sur place.

   Une cabine qui n'est rangée nulle part ne voit jamais cet écran : le cas
   courant reste une photo, un scan, une place.                               */
function blocIntention(c) {
  // Une cabine peut tenir sur deux emplacements : les libellés se mettent au
  // pluriel, et « la sortir » les libère tous — c'est ce que fait le serveur,
  // sortir une cabine à moitié laisserait une place réservée par un morceau
  // qu'on croit parti.
  const plusieurs = (c.nb_emplacements || 1) > 1;
  // Sortir exige un n° de chantier, pour tous les types sans exception. Le dire
  // ici plutôt que de laisser le geste échouer après coup.
  const bloque = !c.chantier;
  return `<div class="card">
    <div class="sec" style="margin-top:0">Déjà rangée en ${esc(c.position)}</div>
    <div class="meta" style="margin:-2px 0 12px">Que voulez-vous faire ?</div>
    <div class="gestes">
      <button class="geste" data-intention="deplacer">
        <span class="ic">${icon('transfer', 26)}</span>
        <span class="t">La déplacer</span>
        <span class="s">Elle quitte ${plusieurs ? 'ses emplacements actuels'
          : esc(c.position)} pour le nouvel emplacement</span>
      </button>
      <button class="geste" data-intention="ajouter">
        <span class="ic">${icon('plus', 26)}</span>
        <span class="t">Ajouter un emplacement</span>
        <span class="s">Elle reste aussi en ${esc(c.position)} — pour une cabine
          qui ne tient pas dans une seule colonne</span>
      </button>
      <button class="geste" data-intention="sortir"${bloque ? ' disabled' : ''}>
        <span class="ic">${icon('out', 26)}</span>
        <span class="t">La sortir de ${plusieurs
          ? `ses ${c.nb_emplacements} emplacements` : esc(c.position)}</span>
        <span class="s">${bloque
          ? 'Impossible sans n° de chantier : à affecter sur la fiche de la cabine'
          : `La place${plusieurs ? 's se libèrent' : ' se libère'}, la cabine n'est
             plus rangée nulle part`}</span>
      </button>
    </div>
  </div>`;
}

function brancherIntention(c) {
  const zone = $('#zone');
  if (!zone) return;
  zone.querySelectorAll('[data-intention]').forEach(b => b.onclick = async () => {
    const geste = b.dataset.intention;
    if (geste !== 'sortir') { RANGEMENT.intention = geste; etapeRangement(); return; }
    const plusieurs = (c.nb_emplacements || 1) > 1;
    const ok = await confirmer({
      titre: `Sortir ${c.numero} de ${c.position} ?`,
      texte: (plusieurs
        ? `Ses ${c.nb_emplacements} places se libèrent et la cabine n'est plus rangée nulle part.`
        : "La place se libère et la cabine n'est plus rangée nulle part.")
        + ' Elle reste en stock, et le journal garde la trace du retrait.',
      ok: plusieurs ? `Sortir des ${c.nb_emplacements} emplacements` : 'Sortir de l’emplacement',
      danger: true,
    });
    if (!ok) return;
    try {
      const frais = await api(`/cabines/${c.id}/sortir/`, { method: 'POST', body: {} });
      toast(`${frais.numero} sortie de son emplacement`, 'ok');
      noterRecentCabine(frais);
      // La cabine n'est plus rangée : l'écran suivant est celui de tout le
      // monde, sans avertissement à lire. On peut la reposer ailleurs, ou
      // s'arrêter là.
      RANGEMENT.cabine = frais;
      RANGEMENT.intention = null;
      etapeRangement();
    } catch (e) { toast(e.message, 'err'); }
  });
}

function etapeEmplacement() {
  const zone = $('#zone');
  if (!zone) return;
  const c = RANGEMENT.cabine;
  if (c && cabineRangee(c) && !RANGEMENT.intention) {
    zone.innerHTML = `${rappelRangement()}${blocIntention(c)}`;
    brancherRappel();
    brancherIntention(c);
    return;
  }
  zone.innerHTML = `${rappelRangement()}
    <div class="card">
      <div class="sec" style="margin-top:0">Où la ranger ?</div>
      ${blocCameraHTML('Scanner le QR de l’emplacement', 'L’étiquette collée sur la travée')}
      <div id="rEmpEtat"></div>
      <details style="margin-top:14px"><summary class="meta">Saisir le code à la main</summary>
        <label style="margin-top:8px">Code de l’emplacement</label>
        <input id="rEmp" placeholder="Ex. AC551" autocomplete="off">
        <button class="btn ghost" id="rEmpOk">Continuer</button>
      </details>
    </div>`;
  brancherRappel();
  brancherCamera((texte) => retenirEmplacement(texte));
  $('#rEmpOk').onclick = () => retenirEmplacement($('#rEmp').value);
}

async function retenirEmplacement(texte) {
  const code = String(texte || '').replace(/^LOC:/i, '').trim();
  if (!code) { toast('Saisis le code de l’emplacement.', 'err'); return; }
  const etat = $('#rEmpEtat');
  try {
    const res = await api('/emplacements/?search=' + encodeURIComponent(code))
      .then(d => d.results || []);
    const e = res.find(x => (x.code || '').toUpperCase() === code.toUpperCase())
           || (res.length === 1 ? res[0] : null);
    if (!e) {
      if (etat) etat.innerHTML = `<div class="banner">Aucun emplacement ne correspond à « ${esc(code)} ».</div>`;
      return;
    }
    const d = await api(`/emplacements/${e.id}/places/`);
    if (d.complet) {
      // On reste à l'étape 2 : la cabine reste en main, il suffit de scanner
      // une autre travée. Repartir de zéro ferait refaire la photo de la fiche.
      if (etat) etat.innerHTML = `<div class="banner">${esc(d.code)} est complet — ses trois
        places sont occupées. Scanne un autre emplacement.</div>`;
      return;
    }
    arreterCamera();
    RANGEMENT.emp = e;
    RANGEMENT.d = d;
    etapeRangement();
  } catch (err) { toast(err.message, 'err'); }
}

/* --- Étape 3 : quelle place ? ---------------------------------------------- */
function etapePlace() {
  const zone = $('#zone');
  if (!zone) return;
  const { cabine, emp, d } = RANGEMENT;
  // Une cabine n'occupe qu'un emplacement : la ranger ailleurs la DÉPLACE.
  // Sans cet avertissement, ranger une cabine déjà posée vidait sa travée en
  // silence, et personne ne le voyait avant d'aller la chercher.
  const ajout = RANGEMENT.intention === 'ajouter';
  // Déplacement : on prévient que la place actuelle sera libérée. Ajout : non,
  // c'est justement ce qu'on ne veut pas.
  const ailleurs = !ajout && cabine && cabine.position && cabine.emplacement_code !== d.code;
  zone.innerHTML = `${rappelRangement()}
    <div class="card">
      <div class="sec" style="margin-top:0">Quelle place ?${ajout ? ' — emplacement supplémentaire' : ''}</div>
      ${ailleurs ? `<div class="banner">Cette cabine est actuellement en
        <b>${esc(cabine.position)}</b>. La ranger ici la <b>déplace</b> — sa place
        actuelle sera libérée.</div>` : ''}
      ${ajout ? `<div class="banner">Emplacement supplémentaire : la cabine reste
        aussi en <b>${esc(cabine.position)}</b>.</div>` : ''}
      ${d.illimite
        ? '<div class="meta">Capacité illimitée : aucune place à désigner.</div>'
        : placesHTML(d)}
      <button class="btn orange" id="rOk">Ranger en ${esc(d.code)}</button>
      <button class="btn ghost" id="rAutre">Choisir un autre emplacement</button>
    </div>`;
  brancherRappel();
  $('#rAutre').onclick = () => { RANGEMENT.emp = null; RANGEMENT.d = null; etapeRangement(); };
  // Le geste a été choisi à l'étape précédente, et le rappel du haut porte de
  // quoi le changer : il n'y a plus de question à reposer ici.

  const bouton = $('#rOk');
  const libelle = bouton.textContent;
  if (!d.illimite) { bouton.disabled = true; bouton.textContent = 'Touche une place libre'; }
  const place = brancherPlaces(d, () => { bouton.disabled = false; bouton.textContent = libelle; });

  bouton.onclick = async () => {
    const choix = d.illimite ? null : place();
    if (!d.illimite && !choix) { toast('Touche la place où tu poses la cabine.', 'err'); return; }
    bouton.disabled = true;
    try {
      let c = cabine;
      const corps = { emplacement: emp.id };
      if (choix) corps.place = choix;
      if (ajout) corps.ajouter = true;
      c = await api(`/cabines/${c.id}/ranger/`, { method: 'POST', body: corps });
      noterRecentCabine(c);
      arreterCamera();
      const ou = `${d.code}${choix ? ' · place ' + choix : ''}`;
      toast(`${c.numero} rangée en ${ou}`, 'ok');
      // Deux réponses possibles à « comment est-elle ? », et deux seulement :
      // conforme, ou bloquée. Une cabine qu'on vient de ranger ne part pas.
      ouvrirStatut(c, `Rangée en ${ou}. Quel est son état ?`, () => {
        // Enchaîner : le cariste range rarement une seule cabine.
        repartirRangement();
        etapeRangement();
        const z = $('#zone');
        if (z) z.insertAdjacentHTML('afterbegin',
          `<div class="banner" style="background:var(--ok-tint);color:var(--ok)">
             ${esc(c.numero)} rangée en ${esc(ou)}. Cabine suivante ?</div>`);
      }, { statuts: ['libre', 'quarantaine'] });
    } catch (e) {
      bouton.disabled = false;
      toast(e.message, 'err');
    }
  };
}

/* --- Envoyer une cabine : UN seul chemin -------------------------------------
   L'envoi partait de cinq endroits — l'écran Sortir, la fiche d'une cabine, la
   fenêtre de statut, et deux boutons de l'écran d'un emplacement. La garde
   « cabine en quarantaine » n'avait été posée que sur deux d'entre eux : par les
   trois autres, une cabine bloquée partait sans que rien ne soit demandé.

   Toute demande d'envoi passe désormais par cette fonction, et par elle seule.
   Deux garanties qu'aucun appelant n'a plus à connaître :

   - le statut est RELU auprès du serveur juste avant de demander. La cabine
     affichée à l'écran peut avoir été mise en quarantaine par un collègue depuis
     que la liste a été chargée ; se fier à la copie affichée revenait à demander
     confirmation d'après une information périmée ;
   - la confirmation nomme la cabine, son défaut, et ce que l'envoi implique.

   Rend `true` si l'envoi a eu lieu, `false` si l'opérateur a refusé. Les erreurs
   remontent à l'appelant, qui sait où les afficher.                           */
async function envoyerCabine(cabine, corps = {}) {
  let c = cabine;
  try { c = await api(`/cabines/${cabine.id}/`); } catch (_) {}
  if (c && c.statut === 'quarantaine') {
    const motif = (c.statut_motif || '').trim();
    const ok = await confirmer({
      titre: `${c.numero} est EN QUARANTAINE`,
      texte: `Cette cabine est bloquée${motif ? ` : ${motif}` : ''}.\n\n`
           + 'La sortir la marque ENVOYÉE : elle quitte définitivement l’entrepôt, '
           + 'avec son défaut, et ne pourra plus être rangée.\n\n'
           + 'Confirmes-tu la sortie de cette cabine en quarantaine ?',
      ok: 'Oui, sortir malgré la quarantaine',
      annuler: 'Non, je la laisse',
      danger: true,
    });
    if (!ok) return false;
  }
  await api(`/cabines/${cabine.id}/envoyer/`, { method: 'POST', body: corps });
  return true;
}

/* ===========================================================================
   SORTIR UNE CABINE — par la fiche, comme le rangement

   Même geste d'entrée que pour ranger : on photographie la fiche collée sur la
   cabine. C'est la seule chose que le cariste a en main devant le rack.

   Il n'y a pas d'étape « emplacement » ici : la fiche identifie la cabine, et le
   WMS sait déjà où elle est rangée. Faire scanner la travée n'apporterait aucune
   information — seulement une occasion d'échouer.
   =========================================================================== */

let SORTIE = { cabine: null };

async function renderSortieCabine() {
  if (!peut('cab')) {
    layout(`<h2 class="title">Sortir une cabine</h2>
      <div class="banner">Ton compte n’a pas le droit « cabines ».</div>`, 'sortie-cabine');
    return;
  }
  await refsCabine();
  // Comme le rangement : une cabine déjà identifiée survit à un aller-retour
  // sur un autre onglet. Sans cela, il fallait reprendre la photo.
  layout(`<h2 class="title">Sortir une cabine</h2><div id="zone"></div>`, 'sortie-cabine');
  etapeSortie();
}

function etapeSortie() {
  if (!SORTIE.cabine) return etapeFicheSortie();
  return etapeConfirmerSortie();
}

/** Ouvre l'écran de sortie sur une cabine déjà identifiée, sans redemander la
    fiche : elle vient d'être scannée à l'écran précédent. `renderSortieCabine`
    ne peut pas servir ici — il remet justement la sélection à zéro. */
function ouvrirSortie(cabine) {
  SORTIE = { cabine };
  ECRAN = 'sortie-cabine';
  layout('<h2 class="title">Sortir une cabine</h2><div id="zone"></div>', 'sortie-cabine');
  etapeSortie();
}

function etapeFicheSortie() {
  const zone = $('#zone');
  if (!zone) return;
  zone.innerHTML = blocFiche('Quelle cabine sortir ?');
  brancherBlocFiche(
    (c) => { SORTIE.cabine = c; etapeSortie(); },
    (champs) => {
      // On ne crée jamais une cabine depuis l'écran de sortie : une cabine qui
      // n'est pas entrée ne peut pas sortir. Le dire vaut mieux que de proposer
      // un formulaire de création qui n'aurait aucun sens ici.
      const etat = $('#fEtat');
      if (etat) etat.innerHTML = `<div class="banner">Aucune cabine du WMS ne porte le
        n° <b>${esc(champs.numero || '?')}</b>. Elle n’a peut-être jamais été rangée.<br>
        Pour la faire entrer : écran <b>Ranger</b>.</div>`;
    });
}

async function etapeConfirmerSortie() {
  const zone = $('#zone');
  if (!zone) return;
  zone.innerHTML = '<div class="empty">Chargement…</div>';
  let c = SORTIE.cabine;
  // Relecture : la photo du cariste peut dater de plusieurs minutes, et un
  // collègue a pu déplacer ou envoyer la cabine entre-temps. Agir sur la copie
  // ferait afficher un emplacement qu'elle a déjà quitté.
  try { c = await api(`/cabines/${c.id}/`); SORTIE.cabine = c; } catch (_) {}

  if (c.statut === 'envoye') {
    zone.innerHTML = `<div class="card rappel">
        <div class="r" style="font-size:17px;font-weight:700">${esc(c.numero)} ${badgeStatut(c)}</div>
        <div class="banner" style="margin-top:10px">Cette cabine est déjà envoyée : elle
          ne fait plus partie du stock. On la retrouve dans « Cabines envoyées ».</div>
        <div class="sec">Elle est pourtant devant toi ?</div>
        <button class="btn orange" id="sReprendre">La remettre en stock</button>
        <button class="btn ghost" id="sRepartir">Autre cabine</button>
      </div>`;
    $('#sRepartir').onclick = () => { SORTIE = { cabine: null }; etapeSortie(); };
    $('#sReprendre').onclick = async () => {
      const frais = await reprendreCabine(c);
      if (frais) { SORTIE = { cabine: frais }; etapeSortie(); }
    };
    return;
  }

  const range = !!(c.emplacement || c.emplacement_code || c.position);
  const ou = c.emplacement_code || c.position || '';
  zone.innerHTML = `
    <div class="card rappel">
      <div class="r" style="font-size:17px;font-weight:700">${esc(c.numero)} ${badgeStatut(c)} ${pastilleType(c)}</div>
      <div class="d">Chantier ${c.chantier ? esc(c.chantier) : '<em>à affecter</em>'}${c.modele ? ' · ' + esc(c.modele) : ''}</div>
      <div class="meta">${range ? 'Rangée en ' + esc(ou) + (c.place ? ' · place ' + esc(c.place) : '') : 'Non rangée'}</div>
      <button class="btn ghost" id="sRepartir" style="margin-top:10px">Autre cabine</button>
    </div>
    <div class="card">
      ${c.statut === 'quarantaine' ? `<div class="banner" style="background:var(--danger-tint);color:var(--danger)">
        <b>Cabine en quarantaine.</b> Elle porte un défaut à traiter${c.statut_motif ? ` : ${esc(c.statut_motif)}` : ''}.
        La sortir demandera une confirmation.</div>` : ''}
      <div class="banner">Sortir une cabine, c'est l'<b>envoyer</b> : elle quitte
        l'entrepôt, ${range ? 'sa place se libère, ' : ''}et elle rejoint les archives.
        <b>C'est définitif</b> — une cabine envoyée ne se range plus.</div>
      ${!c.chantier ? `<div class="banner">Pas d'envoi sans chantier, quel que soit le
          type de cabine. Renseigne-le d'abord.</div>
        <label>N° de chantier (6 chiffres)</label>
        <input id="sCha" inputmode="numeric" placeholder="000123" autocomplete="off">` : ''}
      <label>Motif ou n° de bon (facultatif)</label>
      <input id="sNote" placeholder="Ex. BL 2026-0412" autocomplete="off">
      <button class="btn orange" id="sOk">${c.chantier
        ? (range ? 'Sortir de ' + esc(ou) + ' et envoyer' : 'Marquer envoyée')
        : 'Affecter le chantier puis envoyer'}</button>
    </div>`;

  $('#sRepartir').onclick = () => { SORTIE = { cabine: null }; etapeSortie(); };

  $('#sOk').onclick = async () => {
    const bouton = $('#sOk');
    // La confirmation « cabine en quarantaine » n'est plus ici : elle est dans
    // `envoyerCabine`, par où passe l'envoi. Écrite à chaque appelant, elle avait
    // été oubliée sur trois des cinq écrans qui envoient.
    bouton.disabled = true;
    try {
      if (!c.chantier) {
        const cha = ($('#sCha').value || '').trim();
        if (!cha) { toast('Renseigne le n° de chantier.', 'err'); bouton.disabled = false; return; }
        await api(`/cabines/${c.id}/chantier/`, { method: 'POST', body: { chantier: cha } });
      }
      const note = ($('#sNote').value || '').trim();
      // `/envoyer/` et non `/sortir/` : le retrait d'emplacement seul laissait la
      // cabine « en stock, non rangée », un état qui ne correspondait à rien sur
      // le terrain — une cabine qu'on descend du rack part.
      if (!(await envoyerCabine(c, { note }))) { bouton.disabled = false; return; }
      toast(`${c.numero} envoyée`, 'ok');
      SORTIE = { cabine: null };
      etapeSortie();
      const z = $('#zone');
      if (z) z.insertAdjacentHTML('afterbegin',
        `<div class="banner" style="background:var(--ok-tint);color:var(--ok)">
           ${esc(c.numero)} envoyée${ou ? ' — ' + esc(ou) + ' libéré' : ''}. Cabine suivante ?</div>`);
    } catch (e) { bouton.disabled = false; toast(e.message, 'err'); }
  };
}

// --- Fiche cabine : statuts, position, envoi, historique --------------------
/** Le détail des emplacements, quand la cabine en occupe plusieurs.

    Muet dans le cas courant — un emplacement, déjà écrit sur la ligne au-dessus.
    Une cabine qui se prolonge ailleurs doit le dire ici : c'est la page où l'on
    vient vérifier avant d'aller la chercher. */
function blocEmplacements(c) {
  const occupes = emplacementsDe(c);
  if (occupes.length < 2) return '';   // le cas courant se lit déjà sur la ligne
  return `<div class="sec">${occupes.length} emplacements occupés</div>
    <div class="list">${occupes.map(x => `<div class="item" style="cursor:default">
      <div class="r">${esc(x.position)}</div>
      <div class="meta">${esc(x.zone_nom || 'sans zone')}${x.libelle ? ' · ' + esc(x.libelle) : ''}</div>
    </div>`).join('')}</div>`;
}

async function ficheCabine(cabine, retour) {
  await refsCabine();
  /* La fiche s'écrit dans le `#zone` de l'écran qui l'appelle. L'écran des
     gestes n'en a pas — il pose ses cartes directement — et ce garde-fou
     rendait donc la main en silence : « Voir sa fiche » ne faisait rien, sans
     message ni erreur en console. Là où il n'y a pas de conteneur, la fiche
     pose le sien. L'onglet reste « Scanner » : la fiche est une étape du
     parcours de scan, pas une destination du menu. */
  if (!$('#zone')) layout('<div id="zone"></div>', 'scanner');
  const zone = $('#zone');
  if (!zone) return;
  zone.innerHTML = '<div class="empty">Chargement…</div>';
  try {
    const [c, hist] = await Promise.all([
      api(`/cabines/${cabine.id}/`),
      api(`/cabines/${cabine.id}/historique/`),
    ]);
    noterRecentCabine(c);   // alimente les « Récents » du scanner
    const modifiable = peut('cab') && !c.envoyee;
    zone.innerHTML = `
      ${retour ? '<button class="btn ghost" id="fRetour" style="margin:0 0 12px">← Retour</button>' : ''}
      <div class="card">
        <div class="r" style="font-size:18px;font-weight:700">${esc(c.numero)} ${badgeStatut(c)}</div>
        <div class="meta" style="margin-top:4px">
          ${esc(c.type_libelle)} · chantier ${c.chantier ? esc(c.chantier) : '<em>non affecté</em>'}
          ${c.modele ? ' · ' + esc(c.modele) : ''}</div>
        <div class="meta">${c.position ? 'Rangée en ' + esc(c.position) : 'Non rangée'}</div>
        ${blocEmplacements(c)}
        ${c.envoyee ? '' : `<div class="meta" style="margin-top:4px">Sans mouvement depuis ${c.jours_immobile} jour${c.jours_immobile === 1 ? '' : 's'}</div>`}
        ${c.envoyee ? `<div class="banner" style="margin:12px 0 0">Cabine envoyée le ${new Date(c.envoi_date).toLocaleString('fr-FR')} — fiche archivée. La fiche reste corrigeable, et la cabine peut être remise en stock si elle revient.</div>
          ${peut('cab') ? `<button class="btn orange" id="fReprendre">La remettre en stock</button>` : ''}` : ''}
        <div id="fAct"></div>
          ${peut('cab') ? `<div class="row" style="margin-top:10px">
          <button class="btn ghost" id="fCorriger" style="margin-top:0">${icon('edit', 17)} Corriger la fiche</button>
          <button class="btn danger" id="fSupprimer" style="margin-top:0">${icon('trash', 17)} Supprimer</button>
        </div>` : ''}
      </div>
      <div class="sec">Historique — ${hist.length} événement${hist.length === 1 ? '' : 's'}</div>
      <div class="list">${hist.length ? hist.map(m => `<div class="item" style="cursor:default">
        <div class="r">${esc(m.type_libelle)}${m.statut_apres ? ' → ' + esc(m.statut_apres_libelle) : ''}</div>
        ${(m.depuis || m.vers) ? `<div class="d">${esc(m.depuis || '—')} → ${esc(m.vers || '—')}</div>` : ''}
        <div class="meta">${new Date(m.date).toLocaleString('fr-FR')} · ${esc(m.utilisateur_nom || 'compte supprimé')}${m.note ? ' · ' + esc(m.note) : ''}</div>
      </div>`).join('') : '<div class="empty">Aucun événement</div>'}</div>`;

    if (retour) $('#fRetour').onclick = retour;

    // Corriger et supprimer restent accessibles sur une cabine envoyée : une faute
    // de frappe reste une faute de frappe une fois la cabine partie, et corriger
    // l'archive vaut mieux que la supprimer pour la ressaisir.
    if (peut('cab')) {
      $('#fCorriger').onclick = () => ouvrirCorrectionCabine(c, () => ficheCabine(c, retour));
      $('#fSupprimer').onclick = () => supprimerCabine(c, retour);
    }
    // Une cabine partie par erreur — ou revenue de chantier — se remet en stock
    // depuis sa propre fiche, y compris ouverte depuis « Cabines envoyées ».
    const bReprendre = $('#fReprendre');
    if (bReprendre) bReprendre.onclick = async () => {
      const frais = await reprendreCabine(c);
      if (frais) ficheCabine(frais, retour);
    };
    if (!modifiable) return;

    const statutsPossibles = REFS_CABINE.statuts.filter(s => s.code !== c.statut && s.code !== 'envoye');
    $('#fAct').innerHTML = `
      <div class="sec">État de la cabine</div>
      ${statutsPossibles.map(s => `<button class="btn ghost" data-vers="${s.code}"
        >${esc(verbeStatut(c, s.code))}</button>`).join('')}
      <div class="sec" style="margin-top:14px">${c.position ? 'Changer d’emplacement' : 'Ranger cette cabine'}</div>
      <div class="row">
        <button class="btn ghost" id="fScanEmp" style="margin-top:0">Scanner l'emplacement</button>
        <button class="btn ghost" id="fCodeEmp" style="margin-top:0">Saisir le code</button>
      </div>
      <button class="btn ghost" id="fRanger">Choisir dans la liste</button>
      ${c.position ? '<button class="btn ghost" id="fSortir">Sortir de l’emplacement</button>' : ''}
      <button class="btn orange" id="fEnvoyer">Envoyer (définitif)</button>
      <div id="fZone"></div>`;

    $('#fAct').querySelectorAll('[data-vers]').forEach(b => b.onclick =
      () => confirmerChangementStatut(c, b.dataset.vers, () => ficheCabine(c, retour)));

    // Retient la cabine, puis renvoie au scanner : le scan de l'emplacement la range.
    $('#fScanEmp').onclick = () => { CABINE_A_RANGER = c; go('trouver'); };

    // Saisie du code au clavier : indispensable quand la caméra ne peut pas servir
    // (étiquette abîmée, gants, éclairage) — c'est le repli du scan, pas un luxe.
    $('#fCodeEmp').onclick = () => {
      $('#fZone').innerHTML = `<label>Code de l'emplacement</label>
        <input id="fCode" placeholder="Ex. C001" autocomplete="off">
        <div class="list" id="fCodeRes"></div>`;
      const champ = $('#fCode');
      champ.focus();
      champ.oninput = debounce(async () => {
        const t = champ.value.trim();
        if (t.length < 1) { $('#fCodeRes').innerHTML = ''; return; }
        try {
          const emps = (await api('/emplacements/?search=' + encodeURIComponent(t))).results || [];
          $('#fCodeRes').innerHTML = emps.length
            ? emps.slice(0, 6).map(e => `<div class="item" data-e="${e.id}">
                <div class="r">${esc(e.code)}</div>
                <div class="d">${esc(e.zone_cabine_nom || 'Sans zone')} · ${esc(e.mode_libelle)}</div>
                <div class="meta">${e.illimite ? e.nb_cabines + ' cabine(s)' : 'places libres : ' + (e.places_libres.join(', ') || 'aucune')}</div></div>`).join('')
            : '<div class="empty">Aucun emplacement</div>';
          $('#fCodeRes').querySelectorAll('[data-e]').forEach(it => it.onclick = async () => {
            const e = emps.find(x => String(x.id) === it.dataset.e);
            try {
              const d = await api(`/emplacements/${e.id}/places/`);
              if (d.complet) { toast('Les trois places de ' + e.code + ' sont prises.', 'err'); return; }
              const corps = { emplacement: e.id };
              if (!d.illimite) corps.place = d.libres[0];
              await api(`/cabines/${c.id}/ranger/`, { method: 'POST', body: corps });
              toast('Rangée en ' + e.code + (corps.place ? '·' + corps.place : ''), 'ok');
              ficheCabine(c, retour);
            } catch (err) { toast(err.message, 'err'); }
          });
        } catch (err) { toast(err.message, 'err'); }
      }, 250);
    };

    $('#fRanger').onclick = async () => {
      const emplacements = EMPS.filter(e => e.actif !== false);
      if (!emplacements.length) { $('#fZone').innerHTML = '<div class="empty">Aucun emplacement.</div>'; return; }
      $('#fZone').innerHTML = `<label>Emplacement</label>
        <select id="fEmp">${emplacements.map(e => `<option value="${e.id}">${esc(e.code)}${e.zone_cabine_nom ? ' — ' + esc(e.zone_cabine_nom) : ''}</option>`).join('')}</select>
        <div id="fPlaces"><div class="empty">Chargement des places…</div></div>`;
      const majPlaces = async () => {
        const bloc = $('#fPlaces');
        try {
          const d = await api(`/emplacements/${$('#fEmp').value}/places/`);
          if (d.complet) { bloc.innerHTML = '<div class="banner">Les trois places sont occupées : choisis un autre emplacement.</div>'; return; }
          bloc.innerHTML = (d.illimite
              ? `<div class="meta" style="padding:6px 2px">${esc(d.mode_libelle)} · ${d.nb_cabines} cabine${d.nb_cabines === 1 ? '' : 's'} — pas de place à choisir</div>`
              : `<label>Place</label><select id="fPlace">${d.libres.map(p => `<option value="${p}">${p}</option>`).join('')}</select>`)
            + '<button class="btn orange" id="fRangerOk">Confirmer</button>';
          $('#fRangerOk').onclick = async () => {
            try {
              const corps = { emplacement: $('#fEmp').value };
              if (!d.illimite) corps.place = $('#fPlace').value;
              await api(`/cabines/${c.id}/ranger/`, { method: 'POST', body: corps });
              toast('Cabine rangée', 'ok');
              ficheCabine(c, retour);
            } catch (e) { toast(e.message, 'err'); }
          };
        } catch (e) { bloc.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
      };
      $('#fEmp').onchange = majPlaces;
      majPlaces();
    };

    const sortirOuEnvoyer = (chemin, libelle) => async () => {
      if (!c.chantier) {
        $('#fZone').innerHTML = `<div class="banner">N° de chantier obligatoire pour ${libelle}.</div>
          <label>N° de chantier (6 chiffres)</label><input id="fCha" inputmode="numeric" placeholder="000123">
          <button class="btn orange" id="fChaOk">Affecter puis continuer</button>`;
        $('#fChaOk').onclick = async () => {
          try {
            await api(`/cabines/${c.id}/chantier/`, { method: 'POST', body: { chantier: $('#fCha').value } });
            await api(`/cabines/${c.id}/${chemin}/`, { method: 'POST', body: {} });
            toast('Enregistré', 'ok');
            ficheCabine(c, retour);
          } catch (e) { toast(e.message, 'err'); }
        };
        return;
      }
      try {
        await api(`/cabines/${c.id}/${chemin}/`, { method: 'POST', body: {} });
        toast('Enregistré', 'ok');
        ficheCabine(c, retour);
      } catch (e) { toast(e.message, 'err'); }
    };

    if ($('#fSortir')) $('#fSortir').onclick = sortirOuEnvoyer('sortir', 'sortir la cabine');
    $('#fEnvoyer').onclick = sortirOuEnvoyer('envoyer', 'envoyer la cabine');
  } catch (e) { zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}


/* --- Corriger ou supprimer une cabine mal saisie ----------------------------
   Une cabine créée avec un mauvais numéro n'avait aucune issue dans l'interface :
   ni correction, ni suppression. Il fallait passer par l'administration Django,
   qui écrit sans rien journaliser.                                            */

function ouvrirCorrectionCabine(c, apres) {
  const types = REFS_CABINE.types || [{ code: 'normale', libelle: 'Normale' }];
  const ligne = (id, libelle, valeur, extra = '') =>
    `<label for="${id}">${esc(libelle)}</label>
     <input id="${id}" value="${esc(valeur || '')}" autocomplete="off" ${extra}>`;

  const corps = modale('Corriger la fiche ' + c.numero, `
    ${ligne('kNum', 'N° de cabine *', c.numero, 'placeholder="26_03_47"')}
    <div class="aide">Format attendu : deux chiffres, deux chiffres, deux chiffres, séparés par des tirets bas.</div>
    ${ligne('kCha', 'N° de chantier', c.chantier, 'inputmode="numeric" placeholder="000123 — 6 chiffres"')}
    <div class="aide">${esc(aideChantier())}</div>
    <label for="kType">Type</label>
    <select id="kType">${types.map(t => `<option value="${t.code}"${t.code === c.type_cabine ? ' selected' : ''}>${esc(t.libelle)}</option>`).join('')}</select>
    ${ligne('kMod', 'Modèle', c.modele)}
    <div class="sec" style="margin-top:16px">Fiche papier</div>
    ${ligne('kRev', 'Revendeur', c.revendeur)}
    ${ligne('kCli', 'Client', c.client)}
    ${ligne('kBk', 'Tissu BK', c.tissu_bk)}
    ${ligne('kAq', 'Tissu AQ', c.tissu_aq)}
    ${ligne('kFond', 'Fond de cabine', c.fond_cabine)}
    <div class="row modal-actions">
      <button class="btn ghost" id="kAnnul">Annuler</button>
      <button class="btn orange" id="kOk">Enregistrer la correction</button>
    </div>`);

  masquerNumero(corps.querySelector('#kNum')).focus();
  corps.querySelector('#kAnnul').onclick = fermerModale;
  corps.querySelector('#kOk').onclick = async () => {
    const bouton = corps.querySelector('#kOk');
    bouton.disabled = true;
    const v = (id) => corps.querySelector(id).value.trim();
    try {
      await api(`/cabines/${c.id}/`, { method: 'PATCH', body: {
        numero: v('#kNum'), chantier: v('#kCha'),
        type_cabine: corps.querySelector('#kType').value, modele: v('#kMod'),
        revendeur: v('#kRev'), client: v('#kCli'), tissu_bk: v('#kBk'),
        tissu_aq: v('#kAq'), fond_cabine: v('#kFond'),
      } });
      toast('Fiche corrigée', 'ok');
      fermerModale();
      apres();
    } catch (e) { bouton.disabled = false; toast(e.message, 'err'); }
  };
}

/* Suppression. Aucun motif n'est bloquant — supprimer une saisie erronée est
   l'intention même — mais l'opérateur doit savoir ce qu'il efface, et pouvoir
   corriger plutôt que supprimer quand c'est le bon geste.                    */
async function supprimerCabine(c, retour) {
  const sup = c.suppression || {};
  const revenir = () => (retour || renderCabines)();

  if (sup.possible) {
    const ok = await confirmer({
      titre: 'Supprimer la cabine ' + c.numero + ' ?',
      texte: "Cette cabine vient d'être créée et n'a encore rien vécu : la supprimer "
           + "est sans conséquence. Le journal gardera la trace de la suppression, "
           + "avec votre nom et la date.",
      ok: 'Supprimer', danger: true });
    if (ok) effacerCabine(c, false, 'Saisie erronée', revenir);
    return;
  }

  const choix = await confirmer({
    titre: 'Supprimer la cabine ' + c.numero + ' ?',
    texte: sup.message,
    ok: 'Corriger la fiche plutôt',
    extra: { libelle: 'Supprimer quand même', valeur: 'forcer', danger: true },
    annuler: 'Annuler' });

  if (choix === true) { ouvrirCorrectionCabine(c, () => ficheCabine(c, retour)); return; }
  if (choix !== 'forcer') return;

  // Motif exigé dès qu'on force : c'est la seule chose qui expliquera la
  // disparition à celui qui cherchera cette cabine la semaine prochaine.
  const corps = modale('Supprimer ' + c.numero, `
    <p class="modal-texte">${esc(sup.message)}</p>
    <label for="sMotif">Pourquoi supprimez-vous cette cabine ? *</label>
    <input id="sMotif" placeholder="Ex. doublon de la 26_03_47, créée deux fois" autocomplete="off">
    <div class="aide">Conservé dans le journal des cabines, avec votre nom et la date.</div>
    <div class="row modal-actions">
      <button class="btn ghost" id="sAnnul">Annuler</button>
      <button class="btn danger" id="sOk">Supprimer définitivement</button>
    </div>`);
  const champ = corps.querySelector('#sMotif');
  champ.focus();
  corps.querySelector('#sAnnul').onclick = fermerModale;
  const lancer = () => {
    const motif = champ.value.trim();
    if (!motif) { toast('Indiquez le motif de la suppression.', 'err'); champ.focus(); return; }
    fermerModale();
    effacerCabine(c, true, motif, revenir);
  };
  corps.querySelector('#sOk').onclick = lancer;
  champ.addEventListener('keydown', ev => { if (ev.key === 'Enter') lancer(); });
}

async function effacerCabine(c, force, motif, revenir) {
  const params = [force ? 'force=1' : '', motif ? 'motif=' + encodeURIComponent(motif) : '']
    .filter(Boolean).join('&');
  try {
    await api(`/cabines/${c.id}/${params ? '?' + params : ''}`, { method: 'DELETE' });
    toast('Cabine ' + c.numero + ' supprimée', 'ok');
    oublierRecentCabine(c);
    revenir();
  } catch (e) { toast(e.message, 'err'); }
}

/* --- Recherche de cabines : le moteur de recherche du parc -------------------

   Cet écran remplace une liste et cinq champs. Le besoin exprimé était précis :
   « je n'arrive pas à retrouver les cabines qui ne sont pas rangées ». Le filtre
   existait pourtant déjà — il était simplement invisible, en bas d'un écran
   qu'aucun onglet n'ouvrait, et l'accueil affichait le nombre de cabines non
   rangées sans qu'on puisse cliquer dessus.

   Trois principes en réponse :
   - les questions courantes sont des boutons, pas des combinaisons à composer :
     « Non rangées », « En quarantaine », « Sans chantier », « Sans mouvement » ;
   - chaque bouton annonce son rendement (« Non rangées 12 »), parce qu'un filtre
     dont on ignore le résultat ne se clique pas ;
   - les listes déroulantes ne proposent que ce qui existe vraiment en base
     (`/cabines/filtres/`) : ni chantier fantôme, ni rack disparu.

   Les filtres se cumulent tous. Le résumé au-dessus de la liste dit lesquels
   sont actifs, et un seul bouton les efface.                                  */

//: Ordre des tris proposés. La clé est envoyée telle quelle à `?ordering=`.
const TRIS_CAB = [
  ['numero', 'N° de cabine'],
  ['-derniere_activite_date', 'Activité la plus récente'],
  ['derniere_activite_date', 'Sans mouvement depuis le plus longtemps'],
  ['-date', 'Créées en dernier'],
  ['chantier', 'Chantier'],
];

//: Anciennetés proposées. Le premier seuil vient du serveur (`seuil_immobile_jours`).
const DELAIS_IMMOBILE = [7, 15, 30, 60];

const FILTRES_CAB_VIDE = () => ({
  search: '', rangee: '', statut: '', type: '',
  rack: '', chantier_exact: '', modele_exact: '', immobile: '',
  sans_chantier: '', toutes: '', ordering: 'numero',
});

let FILTRES_CAB = FILTRES_CAB_VIDE();

//: Listes déroulantes et compteurs, relus à chaque ouverture de l'écran : un
//: chantier créé il y a dix secondes doit être proposé.
let OPTIONS_CAB = { chantiers: [], modeles: [], racks: [], compteurs: {},
                    seuil_immobile_jours: 7 };

//: Panneau déplié ou non. `null` : personne n'a encore tranché, on suit la taille
//: de l'écran. Une fois que l'utilisateur l'a ouvert ou fermé, son choix tient —
//: le déplier d'office parce qu'un filtre est posé cachait la liste sous les
//: dix menus, juste après le clic censé la montrer.
let PANNEAU_CAB = null;

//: Filtre ↔ champ de l'écran. Une seule table : le rendu la lit pour poser les
//: valeurs, la synchronisation pour les remettre à jour après un filtre rapide.
const CHAMPS_CAB = { rangee: '#fRa', statut: '#fSt', type: '#fTy',
                     rack: '#fRk', chantier_exact: '#fCh',
                     modele_exact: '#fMo', immobile: '#fIm', ordering: '#fTr' };

/** Filtres rapides : libellé, clé du compteur, les filtres qu'ils posent, et
    s'il faut redessiner l'écran. « Envoyées » en a besoin : le statut « Envoyée »
    n'existe dans la liste déroulante que lorsque les archives sont incluses. */
const CHIPS_CAB = () => [
  ['non_rangees', 'Non rangées', { rangee: '0' }],
  ['quarantaine', 'En quarantaine', { statut: 'quarantaine' }],
  ['sans_chantier', 'Sans chantier', { sans_chantier: '1' }],
  ['immobiles', 'Sans mouvement', { immobile: String(OPTIONS_CAB.seuil_immobile_jours || 7) }],
  // Les cabines parties ne sont plus du stock : on ne les cherche pas, on les
  // retrouve. Ce bouton est l'historique, au même endroit que le reste.
  ['envoyees', 'Envoyées', { toutes: '1', statut: 'envoye' }, true],
];

/** Ouvre l'écran Cabines directement sur un filtre — utilisé par les compteurs
    de l'accueil et le bandeau du cariste, qui annonçaient un chiffre sans y mener. */
function ouvrirCabines(preset) {
  FILTRES_CAB = Object.assign(FILTRES_CAB_VIDE(), preset || {});
  go('cabines');
}

const filtreActif = (poses) => Object.entries(poses).every(([k, v]) => FILTRES_CAB[k] === v);

/** Nombre de filtres posés, hors tri : sert à annoncer « Filtres (3) ». */
function nbFiltresCab() {
  const vide = FILTRES_CAB_VIDE();
  return Object.keys(vide).filter(k => k !== 'ordering' && FILTRES_CAB[k] !== vide[k]).length;
}

async function renderCabines() {
  await refsCabine();
  const [zones, options] = await Promise.all([
    apiAll('/zones/').catch(() => []),
    api('/cabines/filtres/').catch(() => null),
  ]);
  if (options) OPTIONS_CAB = options;

  const opts = (liste, choisie, tousLibelle) =>
    `<option value="">${esc(tousLibelle)}</option>`
    + liste.map(([v, l]) => `<option value="${esc(String(v))}"${String(choisie) === String(v) ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const paires = (liste) => (liste || []).map(x => [x, x]);
  const codes = (liste) => (liste || []).map(x => [x.code, x.libelle]);

  const statuts = codes(REFS_CABINE.statuts)
    .filter(([c]) => c !== 'envoye' || FILTRES_CAB.toutes === '1');
  const envoyees = (OPTIONS_CAB.compteurs || {}).envoyees || 0;
  // Au bureau l'écran est assez haut pour tout montrer ; sur un téléphone la
  // liste passe d'abord. Ensuite, c'est l'utilisateur qui décide.
  const deplie = PANNEAU_CAB !== null ? PANNEAU_CAB
    : Boolean(window.matchMedia && window.matchMedia('(min-width:1024px)').matches);

  layout(`<h2 class="title">Parc des cabines</h2>
    <input id="fQ" class="recherche" type="search" autocomplete="off"
           placeholder="Chercher un n°, un chantier, un modèle…" value="${esc(FILTRES_CAB.search)}">
    <div class="chips" id="chips"></div>
    <details class="filtres" id="fPan"${deplie ? ' open' : ''}>
      <summary><span id="fTitre">Filtres</span></summary>
      <div class="grille-filtres">
        <div><label for="fRa">Rangement</label>
          <select id="fRa">${opts([['1', 'Rangées'], ['0', 'Non rangées']], FILTRES_CAB.rangee, 'Peu importe')}</select></div>
        <div><label for="fSt">Statut</label>
          <select id="fSt">${opts(statuts, FILTRES_CAB.statut, 'Tous')}</select></div>
        <div><label for="fTy">Type</label>
          <select id="fTy">${opts(codes(REFS_CABINE.types), FILTRES_CAB.type, 'Tous')}</select></div>
        <div><label for="fRk">Rack</label>
          <select id="fRk">${opts(paires(OPTIONS_CAB.racks), FILTRES_CAB.rack, 'Tous')}</select></div>
        <div><label for="fCh">Chantier</label>
          <select id="fCh">${opts(paires(OPTIONS_CAB.chantiers), FILTRES_CAB.chantier_exact, 'Tous')}</select></div>
        <div><label for="fMo">Modèle</label>
          <select id="fMo">${opts(paires(OPTIONS_CAB.modeles), FILTRES_CAB.modele_exact, 'Tous')}</select></div>
        <div><label for="fIm">Sans mouvement depuis</label>
          <select id="fIm">${opts(DELAIS_IMMOBILE.map(j => [j, `plus de ${j} jours`]), FILTRES_CAB.immobile, 'Peu importe')}</select></div>
        <div><label for="fTr">Trier par</label>
          <select id="fTr">${TRIS_CAB.map(([v, l]) => `<option value="${v}"${FILTRES_CAB.ordering === v ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
      </div>
      <label class="case"><input type="checkbox" id="fEn"${FILTRES_CAB.toutes === '1' ? ' checked' : ''}>
        <span>Inclure les cabines envoyées${envoyees ? ` (${envoyees})` : ''}</span></label>
    </details>
    <div id="actifs"></div>
    <button class="btn ghost" id="fExport">${icon('in', 17)} Télécharger l'inventaire (Excel)</button>
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'cabines');
  const boutonExport = $('#fExport');
  if (boutonExport) boutonExport.onclick = exporterInventaire;

  Object.entries(CHAMPS_CAB).forEach(([cle, sel]) => {
    const n = $(sel);
    if (n) n.onchange = () => { FILTRES_CAB[cle] = n.value; majEtLister(); };
  });
  $('#fPan').ontoggle = (ev) => { PANNEAU_CAB = ev.target.open; };
  $('#fQ').oninput = debounce(() => {
    FILTRES_CAB.search = $('#fQ').value.trim(); majEtLister();
  }, 250);
  $('#fEn').onchange = () => {
    FILTRES_CAB.toutes = $('#fEn').checked ? '1' : '';
    // Le statut « Envoyée » n'existe dans la liste que si on inclut les envoyées :
    // il faut redessiner l'écran, pas seulement relancer la recherche.
    renderCabines();
  };
  majChipsCab();
  majEtLister();
}

/** Redessine ce qui dépend des filtres sans toucher aux champs : le texte tapé
    dans la recherche ne doit pas perdre le curseur à chaque frappe. */
function majEtLister() {
  majChipsCab();
  listerCabines();
}

/** Recopie les filtres dans les menus de l'écran. Un filtre rapide pose la même
    valeur qu'un menu : les deux doivent dire la même chose, sans quoi le menu
    « Rangement » afficherait « Peu importe » alors que la liste est filtrée. */
function synchroniserChampsCab() {
  Object.entries(CHAMPS_CAB).forEach(([cle, sel]) => {
    const n = $(sel);
    if (n && n.value !== FILTRES_CAB[cle]) n.value = FILTRES_CAB[cle];
  });
  const q = $('#fQ');
  if (q && q.value !== FILTRES_CAB.search) q.value = FILTRES_CAB.search;
}

function majChipsCab() {
  const boite = $('#chips');
  if (!boite) return;
  const c = OPTIONS_CAB.compteurs || {};
  const chips = CHIPS_CAB();
  boite.innerHTML = chips.map(([cle, libelle, poses]) =>
    `<button type="button" class="chip ${filtreActif(poses) ? 'on' : ''}" data-chip="${cle}">
      ${esc(libelle)}${c[cle] === undefined ? '' : `<span class="n">${c[cle]}</span>`}</button>`).join('');
  boite.querySelectorAll('[data-chip]').forEach(b => b.onclick = () => {
    const [, , poses, redessiner] = chips.find(x => x[0] === b.dataset.chip);
    const vide = FILTRES_CAB_VIDE();
    // Un filtre rapide déjà posé se retire au second clic : sans cela, il fallait
    // aller le décocher dans le panneau pour revenir à la liste complète.
    const actif = filtreActif(poses);
    Object.keys(poses).forEach(k => FILTRES_CAB[k] = actif ? vide[k] : poses[k]);
    if (redessiner) { renderCabines(); return; }
    synchroniserChampsCab();
    majEtLister();
  });

  const titre = $('#fTitre');
  const n = nbFiltresCab();
  if (titre) titre.textContent = n ? `Filtres (${n})` : 'Filtres';

  const zone = $('#actifs');
  if (!zone) return;
  const resume = resumeFiltresCab();
  zone.innerHTML = resume
    ? `<div class="actifs"><span>${esc(resume)}</span>
         <button type="button" class="lien" data-vider>Tout effacer</button></div>`
    : '';
  const vider = zone.querySelector('[data-vider]');
  if (vider) vider.onclick = () => {
    const envoyeesAvant = FILTRES_CAB.toutes;
    FILTRES_CAB = FILTRES_CAB_VIDE();
    // Décocher « inclure les envoyées » change la liste des statuts proposés :
    // ce seul cas demande de redessiner l'écran.
    if (envoyeesAvant === '1') { renderCabines(); return; }
    synchroniserChampsCab();
    majEtLister();
  };
}

/** Phrase listant les filtres posés — pour qu'un résultat court s'explique. */
function resumeFiltresCab() {
  const libelle = (liste, code) => ((liste || []).find(x => x.code === code) || {}).libelle || code;
  const morceaux = [];
  const f = FILTRES_CAB;
  // Archives : un seul mot suffit, « Envoyée · envoyées incluses » n'en disait pas
  // plus et se lisait comme deux filtres différents.
  const archives = f.toutes === '1' && f.statut === 'envoye';
  if (f.search) morceaux.push(`« ${f.search} »`);
  if (archives) morceaux.push('cabines envoyées (archives)');
  if (f.rangee === '0') morceaux.push('non rangées');
  if (f.rangee === '1') morceaux.push('rangées');
  if (f.statut && !archives) morceaux.push(libelle(REFS_CABINE.statuts, f.statut));
  if (f.type) morceaux.push(libelle(REFS_CABINE.types, f.type));
  if (f.rack) morceaux.push('rack ' + f.rack);
  if (f.zone) morceaux.push('zone choisie');
  if (f.chantier_exact) morceaux.push('chantier ' + f.chantier_exact);
  if (f.modele_exact) morceaux.push(f.modele_exact);
  if (f.sans_chantier === '1') morceaux.push('sans chantier');
  if (f.immobile) morceaux.push(`sans mouvement depuis plus de ${f.immobile} jours`);
  if (f.toutes === '1' && !archives) morceaux.push('envoyées incluses');
  return morceaux.join(' · ');
}

/** La sélection courante, en paramètres d'URL.

    La liste et l'export s'en servent tous les deux : décrire les filtres à deux
    endroits, c'est exporter autre chose que ce qui est affiché le jour où l'un
    des deux évolue. */
function requeteCabines() {
  const vide = FILTRES_CAB_VIDE();
  return Object.entries(FILTRES_CAB)
    .filter(([k, v]) => v !== '' && !(k === 'ordering' && v === vide.ordering))
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
}

/* --- Export de l'inventaire -------------------------------------------------
   Le bouton est offert à TOUS ceux qui voient l'écran, cariste compris : le
   fichier ne contient rien d'autre que la liste affichée au-dessus. Le réserver
   à un profil n'aurait protégé aucune donnée — et avec un compte partagé, cela
   revenait à le cacher à tout le monde.

   Un lien ordinaire ne peut pas servir ici : l'API n'ouvre rien sans le jeton,
   qui vit en mémoire et ne part pas dans une barre d'adresse. On récupère donc
   le fichier avec le jeton, puis on le remet au navigateur comme s'il venait
   d'un lien.

   Le nom du fichier est celui que le serveur a choisi (il porte la date) : le
   relire évite d'en inventer un second, qui divergerait.                      */
async function exporterInventaire() {
  const bouton = $('#fExport');
  const libelle = bouton ? bouton.innerHTML : '';
  if (bouton) { bouton.disabled = true; bouton.textContent = 'Préparation…'; }
  try {
    const q = requeteCabines();
    const r = await fetchReseau(API + '/cabines/export/' + (q ? '?' + q : ''),
                          { headers: token ? { Authorization: 'Token ' + token } : {} });
    if (r.status === 401) { logout(); throw new Error('Session expirée, reconnecte-toi.'); }
    if (!r.ok) throw new Error('L’export a été refusé (' + r.status + ').');
    const fichier = await r.blob();
    const entete = r.headers.get('Content-Disposition') || '';
    const nom = (entete.match(/filename="?([^";]+)/) || [])[1] || 'inventaire-cabines.csv';
    const url = URL.createObjectURL(fichier);
    const lien = document.createElement('a');
    lien.href = url; lien.download = nom;
    document.body.appendChild(lien); lien.click(); lien.remove();
    // Libérer l'URL tout de suite annule le téléchargement sur certains
    // navigateurs mobiles : on laisse une minute.
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    toast('Inventaire exporté : ' + nom, 'ok');
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    if (bouton) { bouton.disabled = false; bouton.innerHTML = libelle; }
  }
}

async function listerCabines() {
  const zone = $('#zone');
  if (!zone) return;
  const q = requeteCabines();
  await listePaginee(zone, '/cabines/' + (q ? '?' + q : ''), {
    ligne: ligneCabine,
    vide: nbFiltresCab()
      ? 'Aucune cabine ne correspond à ces filtres. Essaie d’en retirer un.'
      : 'Aucune cabine enregistrée.',
    entete: (total, vus) => `<div class="sec">${total} cabine${total === 1 ? '' : 's'}`
      + (total > vus.length ? ` · ${vus.length} affichée${vus.length === 1 ? '' : 's'}` : '') + '</div>',
    // La fiche est un écran à part entière : elle prend son entrée d'historique,
    // et son « Retour » repasse par le navigateur pour que les deux chemins —
    // le bouton de l'écran et celui du téléphone — fassent la même chose.
    onClic: (c) => ouvrirEcran(() => ficheCabine(c, () => history.back()), 'fiche'),
  });
}

/* --- Emplacements : LE référentiel ------------------------------------------
   Un seul écran pour tout : voir l'occupation, créer, régler, imprimer
   l'étiquette, supprimer. Auparavant les réglages se trouvaient à trois endroits
   différents avec des champs différents, la création vivait tout en bas de page —
   il fallait dérouler tout l'entrepôt pour l'atteindre — et la suppression
   n'existait que dans l'administration Django.                                */


const MODES_EMP = [['gmd', '3 places (G, M, D)'], ['illimite', 'Capacité illimitée']];

/* Le fonctionnement par zones est retiré de l'interface : plus d'écran, plus de
   filtre, plus de sélecteur dans les formulaires d'emplacement. Le modèle
   `Zone` et la colonne `Emplacement.zone_cabine` restent en base avec leurs
   valeurs — rien n'est perdu, et tout revient en rétablissant l'écran le jour
   où les zones serviront vraiment au suivi du processus.                      */

const optionsModes = (choisi) => MODES_EMP.map(([c, l]) =>
  `<option value="${c}"${c === choisi ? ' selected' : ''}>${esc(l)}</option>`).join('');

const AIDE_MODE = '« 3 places » pour une travée où chaque cabine a sa position (G, M, D). '
  + '« Capacité illimitée » pour une aire tampon — à ranger, sortie de production — '
  + 'qui accueille autant de cabines que nécessaire.';

/* --- Création : en haut de l'écran, dans une fenêtre ----------------------- */
function ouvrirNouvelEmplacement(apres) {
  const corps = modale('Nouvel emplacement', `
    <label for="nCode">Code de l'emplacement *</label>
    <input id="nCode" placeholder="Ex. C004, D012 ou ARANGER" autocomplete="off" autocapitalize="characters">
    <div class="aide">C'est ce code qui sera imprimé sur l'étiquette QR collée sur la travée.</div>
    <label for="nMode">Mode de rangement</label><select id="nMode">${optionsModes('gmd')}</select>
    <div class="aide">${AIDE_MODE}</div>
    <label for="nDesc">Description</label><input id="nDesc" placeholder="facultatif — ex. rack du fond, allée B">
    <label class="case"><input type="checkbox" id="nStaging"> Zone de réception (« à ranger »)</label>
    <div class="row modal-actions">
      <button class="btn ghost" id="nAnnul">Annuler</button>
      <button class="btn orange" id="nOk">Créer l'emplacement</button>
    </div>`);

  const champ = corps.querySelector('#nCode');
  champ.focus();
  corps.querySelector('#nAnnul').onclick = fermerModale;

  const creer = async () => {
    const code = champ.value.trim();
    if (!code) { toast('Le code est obligatoire.', 'err'); champ.focus(); return; }
    const bouton = corps.querySelector('#nOk');
    bouton.disabled = true;
    try {
      const e = await api('/emplacements/', { method: 'POST', body: {
        code,
        mode_places: corps.querySelector('#nMode').value,
        description: corps.querySelector('#nDesc').value.trim(),
        staging: corps.querySelector('#nStaging').checked,
      } });
      toast('Emplacement ' + e.code + ' créé', 'ok');
      await rafraichirEmplacements();
      fermerModale();
      if (apres) apres(e);
    } catch (err) { bouton.disabled = false; toast(err.message, 'err'); }
  };
  corps.querySelector('#nOk').onclick = creer;
  champ.addEventListener('keydown', ev => { if (ev.key === 'Enter') creer(); });
}

/* --- Création d'un rack entier ---------------------------------------------
   Dix colonnes sur trois niveaux, c'est trente fois le même formulaire — et une
   faute de frappe garantie quelque part. On saisit la structure, on lit les
   codes qui vont sortir, et on valide.

   L'aperçu est calculé par le SERVEUR, avec le code qui écrit réellement : un
   aperçu reconstitué dans le navigateur pourrait diverger, et on validerait
   alors autre chose que ce qu'on a lu.                                        */

const RACK_DEFAUTS = { prefixe: '', debut: '550', pas: '10', colonnes: '10', niveaux: '3' };

function ouvrirNouveauRack(apres) {
  const corps = modale('Créer un rack', `
    <label for="rPrefixe">Nom du rack *</label>
    <input id="rPrefixe" placeholder="Ex. AC" autocomplete="off" autocapitalize="characters">
    <div class="aide">Le début de chaque code : « AC » donne AC550, AC551…</div>

    <div class="row" style="margin-top:4px">
      <div><label for="rColonnes">Cellules en longueur *</label>
        <input id="rColonnes" type="number" min="1" max="300" value="${RACK_DEFAUTS.colonnes}"></div>
      <div><label for="rNiveaux">Niveaux *</label>
        <input id="rNiveaux" type="number" min="1" max="26" value="${RACK_DEFAUTS.niveaux}"></div>
    </div>

    <div class="row" style="margin-top:10px">
      <div><label for="rDebut">Commencer au numéro *</label>
        <input id="rDebut" inputmode="numeric" value="${RACK_DEFAUTS.debut}" autocomplete="off"></div>
      <div><label for="rPas">Pas entre colonnes</label>
        <input id="rPas" type="number" min="1" value="${RACK_DEFAUTS.pas}"></div>
    </div>
    <div class="aide">Le niveau s'ajoute au numéro de colonne : avec un pas de 10, la colonne 550 donne 550, 551, 552, et la suivante démarre à 560. Un « 050 » saisi garde son zéro.</div>

    <div class="sec" style="margin-top:16px">Aperçu</div>
    <div id="rApercu" class="apercu-rack"><span class="muted small">Saisissez le nom du rack.</span></div>

    <div class="sec" style="margin-top:16px">Réglages appliqués à tout le rack</div>
    <label for="rMode">Mode de rangement</label><select id="rMode">${optionsModes('gmd')}</select>
    <label for="rDesc">Description</label><input id="rDesc" placeholder="facultatif — ex. allée centrale">

    <div class="row modal-actions">
      <button class="btn ghost" id="rAnnul">Annuler</button>
      <button class="btn orange" id="rOk" disabled>Créer le rack</button>
    </div>`);

  const v = (id) => corps.querySelector(id).value.trim();
  const bouton = corps.querySelector('#rOk');
  const apercu = corps.querySelector('#rApercu');
  corps.querySelector('#rAnnul').onclick = fermerModale;
  corps.querySelector('#rPrefixe').focus();

  const parametres = () => ({
    prefixe: v('#rPrefixe'), debut: v('#rDebut'), pas: v('#rPas'),
    colonnes: v('#rColonnes'), niveaux: v('#rNiveaux'),
  });

  const rafraichir = async () => {
    if (!v('#rPrefixe')) {
      apercu.innerHTML = '<span class="muted small">Saisissez le nom du rack.</span>';
      bouton.disabled = true;
      return;
    }
    try {
      const d = await api('/emplacements/generer/', {
        method: 'POST', body: { ...parametres(), apercu: true } });
      const codes = d.codes.map(c =>
        `<span class="jeton${c.existe ? ' pris' : ''}">${esc(c.code)}</span>`);
      // Un rack de 300 codes n'a pas à être déroulé en entier : on montre le
      // début, la fin, et on annonce le compte exact.
      const extrait = codes.length > 42
        ? codes.slice(0, 24).join('') + '<span class="muted small">… </span>' + codes.slice(-9).join('')
        : codes.join('');
      apercu.innerHTML = `<div class="apercu-total">${d.total} emplacement${d.total > 1 ? 's' : ''}`
        + (d.existants.length ? ` · <b>${d.existants.length} déjà existant${d.existants.length > 1 ? 's' : ''}, qui ${d.existants.length > 1 ? 'seront ignorés' : 'sera ignoré'}</b>` : '')
        + `</div><div class="jetons">${extrait}</div>`;
      bouton.disabled = d.nouveaux === 0;
      if (d.nouveaux === 0) apercu.innerHTML += '<div class="aide alerte">Tous ces codes existent déjà : rien à créer.</div>';
    } catch (e) {
      apercu.innerHTML = `<div class="aide alerte">${esc(e.message)}</div>`;
      bouton.disabled = true;
    }
  };

  ['#rPrefixe', '#rDebut', '#rPas', '#rColonnes', '#rNiveaux'].forEach(sel => {
    corps.querySelector(sel).oninput = debounce(rafraichir, 300);
  });

  bouton.onclick = async () => {
    bouton.disabled = true;
    try {
      const d = await api('/emplacements/generer/', { method: 'POST', body: {
        ...parametres(),
        mode_places: corps.querySelector('#rMode').value,
        description: v('#rDesc'),
      } });
      toast(`Rack ${d.rack} : ${d.crees.length} emplacement(s) créé(s)`
            + (d.ignores.length ? `, ${d.ignores.length} déjà existant(s)` : ''), 'ok');
      await rafraichirEmplacements();
      fermerModale();
      if (apres) apres(d);
    } catch (e) { bouton.disabled = false; toast(e.message, 'err'); }
  };
}

// EMPS alimente les listes déroulantes de toute l'application : dès qu'un
// emplacement change, on le rafraîchit, sinon les autres écrans travaillent sur
// une photo périmée (une zone effacée à l'enregistrement, par exemple).
async function rafraichirEmplacements() {
  EMPS = await apiAll('/emplacements/').catch(() => EMPS);
  const s = EMPS.find(x => x.staging);
  STAGING = s ? s.id : null;
  return EMPS;
}

/* --- Écran principal : les racks d'abord ------------------------------------
   L'entrepôt se pense par rack. Une liste plate de 45 travées — demain 400 —
   oblige à filtrer avant de voir quoi que ce soit, alors que la question posée
   sur le terrain est toujours « où reste-t-il de la place dans AC ? ».

   Premier niveau : les racks, avec leur taux d'occupation.
   Deuxième niveau : le plan du rack, colonnes en largeur et niveaux en hauteur,
   comme on le voit en levant les yeux. La couleur dit l'occupation.
   Troisième niveau : la fiche de l'emplacement, inchangée.                   */

//: Racks ouverts en dernier, pour revenir où l'on était après une modification.
let RACK_OUVERT = null;

function grouperParRack(emps) {
  const m = new Map();
  emps.forEach(e => {
    const nom = (e.rack || '').trim();
    const cle = nom || '(hors rack)';
    if (!m.has(cle)) m.set(cle, []);
    m.get(cle).push(e);
  });
  // Tri naturel : AC10 après AC9, et « hors rack » toujours en dernier.
  return [...m.entries()].sort((a, b) => {
    if (a[0] === '(hors rack)') return 1;
    if (b[0] === '(hors rack)') return -1;
    return a[0].localeCompare(b[0], 'fr', { numeric: true });
  });
}

/** Occupation d'un emplacement, sur une échelle qui se lit de loin.

    Le remplissage se lit à la couleur : vert vide, orange une cabine, rouge
    deux. « Complet » n'est pas le bout de cette échelle mais un état d'une
    autre nature — le WMS refusera d'y ranger — d'où une couleur qui ne
    prolonge pas le dégradé : un marine plein, qui se lit « fermé ».

    Un emplacement à capacité illimitée n'est jamais ni rouge ni complet :
    par définition il en reprend toujours une. Le peindre en rouge à la
    deuxième cabine ferait chercher de la place ailleurs sans raison. */
function etatEmplacement(e) {
  if (e.actif === false) return 'inactif';
  const n = e.nb_cabines || 0;
  if (n === 0) return 'vide';
  if (e.illimite) return 'une';
  if (!e.places_libres || !e.places_libres.length) return 'complet';
  return n === 1 ? 'une' : 'deux';
}

const CLASSE_ETAT = { vide: 'ok', une: 'att', deux: 'crit', complet: 'plein', inactif: '' };

/* Ce qu'on affiche, et ce qu'on n'affiche plus.

   La version précédente montrait « 2/3 » : deux places prises sur trois. Le
   chiffre est exact et pourtant trompeur — les cabines n'ont pas toutes la même
   largeur, si bien qu'un emplacement « 1/3 » peut n'accueillir plus personne, et
   qu'un « 2/3 » peut encore prendre une petite. Le seul état sur lequel on peut
   s'engager sans connaître les dimensions, c'est : entièrement libre, ou pas.
   Pour le reste on annonce ce qu'on sait de sûr — le nombre de cabines
   présentes — et « complet » quand le WMS refusera d'y ranger quoi que ce soit. */
const LIBELLE_ETAT = { vide: 'libre', une: '1 cabine', deux: '2 cabines',
                       complet: 'complet', inactif: 'inactif' };

/** Ce qu'on inscrit dans une case du plan : jamais un décompte de places. */
function occupationCourte(e) {
  const etat = etatEmplacement(e);
  if (etat === 'inactif') return 'hors service';
  if (etat === 'vide') return 'libre';
  if (etat === 'complet') return 'complet';
  const n = e.nb_cabines || 0;
  return n + ' cabine' + (n > 1 ? 's' : '');
}

async function renderEmplacements() {
  await refsCabine();
  const gerer = peut('ref');

  layout(`
    <div class="tete-ecran">
      <h2 class="title" style="margin:0">Emplacements</h2>
      ${gerer ? `<div class="actions-tete">
        <button class="btn ghost bouton-tete" id="eRack">${icon('grille', 18)} Créer un rack</button>
        <button class="btn orange bouton-tete" id="eNouveau">${icon('plus', 18)} Nouvel emplacement</button>
      </div>` : ''}
    </div>
    ${gerer ? '' : '<div class="banner">Consultation seule : le droit « référentiel » est nécessaire pour créer, modifier ou supprimer un emplacement.</div>'}
    <div class="card">
      <label for="eSearch">Aller directement à un emplacement</label>
      <input id="eSearch" placeholder="Code de l’emplacement (ex. AC551)" autocomplete="off">
      <div class="list" id="eRes"></div>
    </div>
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'emplacements');

  if (gerer) {
    $('#eNouveau').onclick = () => ouvrirNouvelEmplacement(() => renderEmplacements());
    $('#eRack').onclick = () => ouvrirNouveauRack(() => renderEmplacements());
  }

  const champ = $('#eSearch');
  champ.oninput = debounce(async () => {
    const t = champ.value.trim();
    const boite = $('#eRes');
    if (!boite) return;
    if (t.length < 2) { boite.innerHTML = ''; return; }
    try {
      const res = await api('/emplacements/?search=' + encodeURIComponent(t)).then(d => d.results || []);
      boite.innerHTML = res.length
        ? res.slice(0, 8).map(e => `<div class="item" data-emp="${e.id}">
            <div class="r">${esc(e.code)} <span class="etat ${CLASSE_ETAT[etatEmplacement(e)]}">${LIBELLE_ETAT[etatEmplacement(e)]}</span></div>
            <div class="d">${esc(e.zone_cabine_nom || e.zone || 'sans zone')}</div></div>`).join('')
        : '<div class="empty">Aucun emplacement ne correspond</div>';
      boite.querySelectorAll('[data-emp]').forEach(it => it.onclick = () => {
        const e = res.find(x => String(x.id) === it.dataset.emp);
        if (e) ficheEmplacement(e, renderEmplacements);
      });
    } catch (e) { toast(e.message, 'err'); }
  }, 250);

  listerRacks();
}

/** Premier niveau : une carte par rack, avec son occupation. */
async function listerRacks() {
  const zone = $('#zone');
  if (!zone) return;
  try {
    const emps = await apiAll('/emplacements/');
    const groupes = grouperParRack(emps);
    if (!groupes.length) {
      zone.innerHTML = `<div class="empty">Aucun emplacement. ${peut('ref') ? 'Commence par créer un rack.' : ''}</div>`;
      return;
    }
    zone.innerHTML = `<div class="sec">${groupes.length} rack${groupes.length === 1 ? '' : 's'} · ${emps.length} emplacement${emps.length === 1 ? '' : 's'}</div>
      <div class="racks">${groupes.map(([nom, liste]) => {
        const cabines = liste.reduce((n, e) => n + (e.nb_cabines || 0), 0);
        const libres = liste.filter(e => etatEmplacement(e) === 'vide').length;
        // La jauge montre ce qui reste : c'est la question posée devant le rack.
        const part = liste.length ? Math.round((libres / liste.length) * 100) : 0;
        return `<button class="rack" data-rack="${esc(nom)}">
          <span class="nom">${esc(nom === '(hors rack)' ? 'Hors rack' : nom)}</span>
          <span class="jauge ${libres ? '' : 'sature'}"><span style="width:${part}%"></span></span>
          <span class="chiffres"><b>${libres}</b> emplacement${libres > 1 ? 's' : ''} entièrement libre${libres > 1 ? 's' : ''}</span>
          <span class="detail">sur ${liste.length} · ${cabines} cabine${cabines === 1 ? '' : 's'} rangée${cabines === 1 ? '' : 's'}</span>
        </button>`;
      }).join('')}</div>`;
    zone.querySelectorAll('[data-rack]').forEach(b => b.onclick = () => ouvrirRack(b.dataset.rack, emps));
  } catch (e) {
    zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

/* --- Cocher plusieurs cases -------------------------------------------------
   Il n'existait que deux extremes : supprimer UN emplacement depuis sa fiche, ou
   TOUT un rack d'un geste. Demonter une demi-colonne demandait donc autant de
   passages par la fiche qu'il y avait de cases.

   La selection est un mode, pas un etat permanent : hors de ce mode, un appui
   sur une case ouvre sa fiche comme avant. Elle appartient au rack ouvert et se
   remet a zero quand on en change.                                            */
let SELECTION_RACK = { rack: null, actif: false, ids: new Set() };

/** Deuxième niveau : le plan du rack. */
function ouvrirRack(nom, emps) {
  RACK_OUVERT = nom;
  if (SELECTION_RACK.rack !== nom) SELECTION_RACK = { rack: nom, actif: false, ids: new Set() };
  const zone = $('#zone');
  if (!zone) return;
  const liste = emps.filter(e => ((e.rack || '').trim() || '(hors rack)') === nom);

  // Colonnes en largeur, niveaux en hauteur, le plus haut en haut : c'est ce
  // qu'on a sous les yeux devant le rack. Trier autrement obligerait à traduire
  // mentalement à chaque regard.
  const colonnes = [...new Set(liste.map(e => e.colonne).filter(v => v != null))].sort((a, b) => a - b);
  const niveaux = [...new Set(liste.map(e => e.niveau).filter(v => v != null))].sort((a, b) => b - a);
  const parPosition = new Map();
  liste.forEach(e => { if (e.colonne != null && e.niveau != null) parPosition.set(e.colonne + '/' + e.niveau, e); });
  const orphelins = liste.filter(e => e.colonne == null || e.niveau == null);

  // Le rafraîchissement automatique peut avoir fait disparaître une case cochée —
  // un autre poste l'a supprimée entre-temps. On ne garde que ce qui est là.
  const presents = new Set(liste.map(e => e.id));
  SELECTION_RACK.ids = new Set([...SELECTION_RACK.ids].filter(id => presents.has(id)));

  const cellule = (e) => {
    if (!e) return '<span class="case vide-trou"></span>';
    const coche = SELECTION_RACK.actif
      ? ` aria-pressed="${String(SELECTION_RACK.ids.has(e.id))}"` : '';
    return `<button class="case ${etatEmplacement(e)}" data-emp="${e.id}" title="${esc(e.code)}"${coche}>
      <span class="c">${esc(e.code)}</span>
      <span class="o">${occupationCourte(e)}</span>
    </button>`;
  };

  const plan = (colonnes.length && niveaux.length)
    ? `<div class="plan" style="--colonnes:${colonnes.length}">
         <div class="plan-entete"><span class="coin"></span>${colonnes.map(c => `<span class="col">${c}</span>`).join('')}</div>
         ${niveaux.map(niv => `<div class="plan-ligne">
            <span class="niv">N${niv}</span>
            ${colonnes.map(c => cellule(parPosition.get(c + '/' + niv))).join('')}
          </div>`).join('')}
       </div>`
    : '';

  zone.innerHTML = `
    <button class="btn ghost" id="rRetour">&#8592; Tous les racks</button>
    <div class="sec">Rack ${esc(nom === '(hors rack)' ? '— hors rack' : nom)} ·
      ${liste.filter(e => etatEmplacement(e) === 'vide').length} libre${liste.filter(e => etatEmplacement(e) === 'vide').length > 1 ? 's' : ''} sur ${liste.length}</div>
    <div class="legende">
      <span><i class="pastille ok"></i>libre</span>
      <span><i class="pastille att"></i>1 cabine</span>
      <span><i class="pastille crit"></i>2 cabines</span>
      <span><i class="pastille plein"></i>complet — le WMS refusera d’y ranger</span>
    </div>
    ${plan}
    ${orphelins.length ? `<div class="sec">Sans position dans le rack</div>
      <div class="cases-libres">${orphelins.map(cellule).join('')}</div>` : ''}
    ${peut('ref') ? `<button class="btn ghost" id="selMode" style="margin-top:22px">
        ${SELECTION_RACK.actif ? 'Quitter la sélection'
          : icon('grille', 17) + ' Sélectionner plusieurs emplacements'}</button>` : ''}
    ${(peut('ref') && !SELECTION_RACK.actif && nom !== '(hors rack)') ? `<button class="btn danger" id="rSupp"
        style="margin-top:10px">${icon('trash', 17)} Supprimer le rack ${esc(nom)}</button>` : ''}
    ${SELECTION_RACK.actif ? barreSelection() : ''}`;

  const retour = $('#rRetour');
  if (retour) retour.onclick = () => { RACK_OUVERT = null; listerRacks(); };
  zone.querySelectorAll('[data-emp]').forEach(b => b.onclick = () => {
    const e = liste.find(x => String(x.id) === b.dataset.emp);
    if (!e) return;
    if (!SELECTION_RACK.actif) { ficheEmplacement(e, () => renderEmplacements()); return; }
    if (SELECTION_RACK.ids.has(e.id)) SELECTION_RACK.ids.delete(e.id);
    else SELECTION_RACK.ids.add(e.id);
    // Redessiner le plan entier plutôt que la seule case : le compte de la barre
    // et l'état des boutons suivent alors tout seuls, sans code de synchronisation.
    ouvrirRack(nom, emps);
  });
  const mode = $('#selMode');
  if (mode) mode.onclick = () => {
    SELECTION_RACK.actif = !SELECTION_RACK.actif;
    SELECTION_RACK.ids = new Set();
    ouvrirRack(nom, emps);
  };
  const bSupp = $('#selSupp');
  if (bSupp) bSupp.onclick = () => ouvrirSuppressionSelection(nom, emps);
  const bVider = $('#selVider');
  if (bVider) bVider.onclick = () => { SELECTION_RACK.ids = new Set(); ouvrirRack(nom, emps); };
  const supp = $('#rSupp');
  if (supp) supp.onclick = () => ouvrirSuppressionRack(nom);
}

/** La barre qui compte les cases cochées et porte leur suppression. */
function barreSelection() {
  const n = SELECTION_RACK.ids.size;
  return `<div class="selbar">
    <div class="sel-n">${n === 0 ? 'Touchez les emplacements à sélectionner'
      : `${n} emplacement${n > 1 ? 's' : ''} sélectionné${n > 1 ? 's' : ''}`}</div>
    <div class="row">
      <button class="btn danger" id="selSupp" style="margin-top:0"${n ? '' : ' disabled'}
        >${icon('trash', 17)} Supprimer la sélection</button>
      <button class="btn ghost" id="selVider" style="margin-top:0"${n ? '' : ' disabled'}
        >Tout décocher</button>
    </div>
  </div>`;
}

/* --- Supprimer une sélection -----------------------------------------------
   Mêmes précautions que pour un rack entier, et pour la même raison : on
   demande d'abord au serveur CE QUI SERAIT EFFACÉ, on l'affiche, et la
   suppression est ENTIÈRE ou NULLE. Une sélection dont la moitié disparaît
   laisse l'opérateur devant son plan sans savoir laquelle des six cases a
   résisté — c'est exactement ce qu'il ne faut pas.                           */
async function ouvrirSuppressionSelection(nom, emps) {
  const ids = [...SELECTION_RACK.ids];
  if (!ids.length) return;
  modale(`Supprimer ${ids.length} emplacement${ids.length > 1 ? 's' : ''}`,
         '<div class="empty">Analyse en cours…</div>');
  let etat;
  try {
    etat = await api('/emplacements/lot-diagnostic/?ids=' + ids.join(','));
  } catch (e) {
    fermerModale();
    toast(e.message, 'err');
    return;
  }

  // Le compte d'emplacements est déjà dans la phrase : ne reste ici que ce qui
  // s'y trouve encore, et qui est la seule information qui puisse surprendre.
  const detail = [
    etat.cabines ? `${etat.cabines} cabine${etat.cabines > 1 ? 's' : ''} rangée${etat.cabines > 1 ? 's' : ''}` : null,
    etat.lignes_stock ? `${etat.lignes_stock} ligne${etat.lignes_stock > 1 ? 's' : ''} de stock` : null,
  ].filter(Boolean).join(' · ');
  const un = etat.emplacements === 1;

  const corps = etat.supprimable
    ? `<div class="banner">${un ? 'Cet emplacement va être supprimé' : `Ces ${etat.emplacements} emplacements vont être supprimés`} — c'est <b>définitif</b>.${detail ? ` Il ${un ? 'porte' : 'y a'} encore ${detail}.` : ''}</div>
       <div class="meta" style="margin-top:10px;word-break:break-word">${esc(etat.codes.join(' · '))}</div>
       <label style="margin-top:12px">Motif (facultatif)</label>
       <input id="lMotif" placeholder="Ex. colonne démontée" autocomplete="off">
       <div class="row modal-actions">
         <button class="btn danger" id="lGo" style="margin-top:0">Supprimer définitivement</button>
         <button class="btn ghost" id="lNon" style="margin-top:0">Annuler</button>
       </div>`
    : `<div class="banner">Rien ne sera supprimé : ${etat.bloquants.length} emplacement${etat.bloquants.length > 1 ? 's' : ''} de la sélection s'y oppose${etat.bloquants.length > 1 ? 'nt' : ''}${detail ? ` — ${detail}` : ''}.</div>
       <div class="list" style="margin-top:10px">${etat.bloquants.slice(0, 6).map(b =>
         `<div class="item" style="cursor:default"><div class="r">${esc(b.code)}</div>
            <div class="d">${esc(b.message)}</div></div>`).join('')}
         ${etat.bloquants.length > 6 ? `<div class="meta" style="padding:6px 2px">et ${etat.bloquants.length - 6} autre(s)</div>` : ''}</div>
       <div class="row modal-actions">
         <button class="btn ghost" id="lNon" style="margin-top:0">Fermer</button>
       </div>`;
  const boite = modale(`Supprimer ${etat.emplacements} emplacement${etat.emplacements > 1 ? 's' : ''}`, corps);
  boite.querySelector('#lNon').onclick = fermerModale;
  const go = boite.querySelector('#lGo');
  if (!go) return;
  go.onclick = async () => {
    go.disabled = true;
    try {
      const r = await api('/emplacements/supprimer-lot/', { method: 'POST', body: {
        ids, motif: (boite.querySelector('#lMotif').value || '').trim() } });
      fermerModale();
      toast(`${r.supprimes} emplacement${r.supprimes > 1 ? 's' : ''} supprimé${r.supprimes > 1 ? 's' : ''}`, 'ok');
      // On quitte le mode : la sélection est consommée. Y rester ferait revenir
      // sur le plan avec des cases qui se cochent au premier appui, alors qu'on
      // pensait juste ouvrir une fiche.
      SELECTION_RACK = { rack: nom, actif: false, ids: new Set() };
      renderEmplacements();
    } catch (e) {
      go.disabled = false;
      toast(e.message, 'err');
    }
  };
}

/* --- Supprimer un rack entier ----------------------------------------------
   L'opération la plus destructrice de l'écran : une centaine d'emplacements
   peuvent disparaître d'un geste. Trois précautions, dans cet ordre :

   1. on demande d'abord au serveur CE QUI SERA EFFACÉ, et on l'affiche — le
      compte d'emplacements, les cabines rangées, les lignes de stock ;
   2. si quelque chose s'y oppose, on montre le premier obstacle nommément,
      plutôt qu'un refus sec qu'il faudrait aller diagnostiquer ailleurs ;
   3. la confirmation demande de RECOPIER le nom du rack. Un « êtes-vous sûr »
      se clique sans lire ; recopier « AC » oblige à regarder lequel.          */
async function ouvrirSuppressionRack(rack) {
  modale(`Supprimer le rack ${esc(rack)}`, '<div class="empty">Analyse en cours…</div>');
  let etat;
  try {
    etat = await api('/emplacements/rack-diagnostic/?rack=' + encodeURIComponent(rack));
  } catch (e) {
    fermerModale();
    toast(e.message, 'err');
    return;
  }

  const detail = [
    `${etat.emplacements} emplacement${etat.emplacements > 1 ? 's' : ''}`,
    etat.cabines ? `${etat.cabines} cabine${etat.cabines > 1 ? 's' : ''} rangée${etat.cabines > 1 ? 's' : ''}` : null,
    etat.lignes_stock ? `${etat.lignes_stock} ligne${etat.lignes_stock > 1 ? 's' : ''} de stock` : null,
  ].filter(Boolean).join(' · ');

  const corps = etat.supprimable
    ? `<div class="banner">Le rack <b>${esc(etat.rack)}</b> et ses <b>${etat.emplacements}</b>
         emplacements vont être supprimés. ${detail}.<br>
         C'est <b>définitif</b> : ni le rack ni son plan ne se reconstituent.</div>
       <details style="margin-top:10px"><summary class="meta">Voir les ${etat.emplacements} codes</summary>
         <div class="meta" style="margin-top:6px;word-break:break-word">${esc(etat.codes.join(' · '))}</div></details>
       <label style="margin-top:14px">Recopie <b>${esc(etat.rack)}</b> pour confirmer</label>
       <input id="rNom" placeholder="${esc(etat.rack)}" autocomplete="off">
       <label style="margin-top:10px">Motif (facultatif)</label>
       <input id="rMotif" placeholder="Ex. rack démonté le 27/08" autocomplete="off">
       <div class="row" style="margin-top:14px">
         <button class="btn danger" id="rGo" style="margin-top:0" disabled>Supprimer définitivement</button>
         <button class="btn ghost" id="rNon" style="margin-top:0">Annuler</button>
       </div>`
    : `<div class="banner">Ce rack ne peut pas être supprimé : ${etat.bloquants.length}
         emplacement(s) s'y opposent. ${detail}.</div>
       <div class="list" style="margin-top:10px">${etat.bloquants.slice(0, 6).map(b =>
         `<div class="item" style="cursor:default"><div class="r">${esc(b.code)}</div>
          <div class="meta">${esc(b.message)}</div></div>`).join('')}</div>
       ${etat.bloquants.length > 6 ? `<div class="meta" style="margin-top:6px">
         … et ${etat.bloquants.length - 6} autre(s).</div>` : ''}
       <button class="btn ghost" id="rNon" style="margin-top:14px">Fermer</button>`;

  modale(`Supprimer le rack ${esc(rack)}`, corps);
  $('#rNon').onclick = fermerModale;
  if (!etat.supprimable) return;

  const champ = $('#rNom'), bouton = $('#rGo');
  champ.oninput = () => {
    bouton.disabled = champ.value.trim().toUpperCase() !== etat.rack.toUpperCase();
  };
  bouton.onclick = async () => {
    bouton.disabled = true;
    try {
      const r = await api('/emplacements/supprimer-rack/', {
        method: 'POST',
        body: { rack: etat.rack, motif: ($('#rMotif').value || '').trim() },
      });
      fermerModale();
      toast(`Rack ${r.rack} supprimé — ${r.supprimes} emplacements`, 'ok');
      RACK_OUVERT = null;
      renderEmplacements();
    } catch (e) { bouton.disabled = false; toast(e.message, 'err'); }
  };
}


/* --- Fiche d'un emplacement : occupation + réglages + suppression ----------
   C'est ici, et nulle part ailleurs, qu'un emplacement se modifie.           */
async function ficheEmplacement(emp, retour) {
  // Toujours relire la fiche : `EMPS` est une photo prise au démarrage, et un
  // collègue a pu créer ou déplacer un emplacement depuis. Le formulaire
  // affichait alors « Sans zone » sur un emplacement zoné — et l'enregistrement
  // effaçait sa zone pour de bon.
  let e;
  try { e = await api(`/emplacements/${emp.id}/`); }
  catch (err) { toast(err.message, 'err'); return; }

  const gerer = peut('ref');
  const sup = e.suppression || {};

  layout(`
    <button class="btn ghost retour" id="fRetour">← Retour aux emplacements</button>
    <h2 class="title">${esc(e.code)} <span class="pill">${esc(e.mode_libelle)}</span>${e.actif === false ? '<span class="etat crit">inactif</span>' : ''}</h2>
    <div id="zone"><div class="empty">Chargement…</div></div>
    <div class="sec" style="margin-top:18px">Réglages de l'emplacement</div>
    <div class="card">
      ${gerer ? '' : '<div class="banner" style="margin-bottom:12px">Consultation seule : le droit « référentiel » est nécessaire pour modifier.</div>'}
      <label for="fCode">Code</label>
      <input id="fCode" value="${esc(e.code)}" ${gerer ? '' : 'disabled'} autocomplete="off" autocapitalize="characters">
      <div class="aide">Renommer l'emplacement rend obsolètes les étiquettes QR déjà collées : réimprimez-la juste après.</div>
      ${e.zone_cabine ? '' : '<div class="aide alerte">Sans zone, le suivi du processus ne sait pas dire si cette cabine attend son départ ou sort de production. Rattachez l\'emplacement à une zone.</div>'}
      <label for="fMode">Mode de rangement</label>
      <select id="fMode" ${gerer ? '' : 'disabled'}>${optionsModes(e.mode_places)}</select>
      <div class="aide">${AIDE_MODE}${e.nb_cabines ? ' <b>Le mode ne peut changer que sur un emplacement vide.</b>' : ''}</div>
      <label for="fDesc">Description</label>
      <input id="fDesc" value="${esc(e.description || '')}" placeholder="facultatif" ${gerer ? '' : 'disabled'}>
      <label class="case"><input type="checkbox" id="fStaging" ${e.staging ? 'checked' : ''} ${gerer ? '' : 'disabled'}> Zone de réception (« à ranger »)</label>
      <label class="case"><input type="checkbox" id="fActif" ${e.actif !== false ? 'checked' : ''} ${gerer ? '' : 'disabled'}> Emplacement actif</label>
      <div class="aide">Un emplacement inactif reste consultable et garde son historique, mais on ne peut plus y ranger de cabine. C'est l'alternative à la suppression pour une travée démontée.</div>
      ${gerer ? '<button class="btn orange" id="fOk">Enregistrer les modifications</button>' : ''}
    </div>
    <div class="row actions-fiche" style="margin-top:12px">
      <button class="btn ghost" id="fEtiq">${icon('print', 17)} Imprimer l'étiquette QR</button>
      ${gerer ? `<button class="btn danger" id="fSup" style="margin-top:14px">${icon('trash', 17)} Supprimer</button>` : ''}
    </div>
    ${gerer && !sup.possible && sup.message ? `<div class="banner" style="margin-top:12px">${esc(sup.message)}</div>` : ''}`,
    'more');

  $('#fRetour').onclick = retour || renderEmplacements;
  $('#fEtiq').onclick = () => printLocationLabel(e.code);

  // Occupation + opérations de rangement : l'écran partagé avec le scanner.
  montrerEmplacement(e, { sansReglages: true });

  if (!gerer) return;

  $('#fOk').onclick = async () => {
    const code = $('#fCode').value.trim();
    if (!code) { toast('Le code est obligatoire.', 'err'); return; }
    const bouton = $('#fOk');
    bouton.disabled = true;
    try {
      await api(`/emplacements/${e.id}/`, { method: 'PATCH', body: {
        code,
        mode_places: $('#fMode').value,
        description: $('#fDesc').value.trim(),
        staging: $('#fStaging').checked,
        actif: $('#fActif').checked,
      } });
      toast('Emplacement enregistré', 'ok');
      await rafraichirEmplacements();
      ficheEmplacement({ id: e.id }, retour);
    } catch (err) { bouton.disabled = false; toast(err.message, 'err'); }
  };

  $('#fSup').onclick = () => supprimerEmplacement(e, retour);
}

/* Suppression d'un emplacement. Quatre issues, toutes explicites.
   - franche : confirmation simple ;
   - cabines rangées : refus net, avec le geste à faire (« Sortir d'ici ») ;
   - stock présent : réservé aux administrateurs, avec le détail de ce qui sera
     sorti et un motif obligatoire ;
   - historique seul : on propose la désactivation, qui préserve le journal.   */
async function supprimerEmplacement(e, retour) {
  const sup = e.suppression || {};
  const revenir = () => (retour || renderEmplacements)();

  if (sup.possible) {
    const ok = await confirmer({
      titre: 'Supprimer ' + e.code + ' ?',
      texte: `L'emplacement ${e.code} n'est utilisé nulle part : il peut être supprimé sans perte. Cette action est définitive.`,
      ok: 'Supprimer définitivement', danger: true,
    });
    if (ok) effacer(e, false, '', revenir);
    return;
  }

  if (!sup.forcable) {
    await confirmer({
      titre: 'Suppression impossible',
      texte: sup.message || 'Cet emplacement ne peut pas être supprimé pour le moment.',
      ok: 'J\'ai compris', annuler: null,
    });
    return;
  }

  if (sup.motif === 'stock') { supprimerAvecStock(e, sup, revenir); return; }

  const choix = await confirmer({
    titre: 'Que faire de ' + e.code + ' ?',
    texte: sup.message,
    annuler: 'Annuler',
    ok: 'Désactiver (recommandé)',
    extra: { libelle: 'Supprimer quand même', valeur: 'forcer', danger: true },
  });
  if (choix === true) return desactiverEmplacement(e, revenir);
  if (choix !== 'forcer') return;
  const sur = await confirmer({
    titre: 'Confirmer la suppression',
    texte: `L'historique gardera les lignes concernées, mais le code ${e.code} y sera remplacé par « ? ». Action définitive.`,
    ok: 'Supprimer définitivement', danger: true,
  });
  if (sur) effacer(e, true, '', revenir);
}

/* Suppression d'un emplacement qui porte encore du stock — administrateurs seuls.
   L'écran annonce ligne par ligne ce qui va être sorti : sans cela, l'opération
   revient à faire signer un chèque en blanc sur l'inventaire.                 */
function supprimerAvecStock(e, sup, revenir) {
  const lignes = sup.stock || [];
  const corps = modale('Supprimer ' + e.code + ' avec son stock', `
    <p class="modal-texte">${esc(sup.message)}</p>
    <div class="sec" style="margin-top:16px">Ce qui sera sorti de ${esc(e.code)}</div>
    <div class="list">${lignes.length ? lignes.map(l => `<div class="item" style="cursor:default">
        <div class="r">${esc(l.ref)} <span class="etat att">${fmt(l.qte)}</span></div>
        <div class="meta">${esc(l.designation || '')}</div>
      </div>`).join('') : '<div class="empty">Aucune ligne à sortir.</div>'}</div>
    <div class="aide alerte" style="margin-top:12px">Une <b>sortie</b> sera enregistrée pour chaque article, à votre nom. Les quantités disparaîtront des totaux du stock — ce n'est pas un transfert.</div>
    <label for="xMotif">Pourquoi supprimez-vous cet emplacement ? *</label>
    <input id="xMotif" placeholder="Ex. travée démontée, marchandise déjà évacuée" autocomplete="off">
    <div class="aide">Recopié dans chaque mouvement de sortie, avec votre nom et la date.</div>
    <div class="modal-actions">
      <button class="btn danger" id="xOk">Supprimer et sortir le stock</button>
      <button class="btn ghost" id="xDesactiver">Désactiver l'emplacement plutôt</button>
      <button class="btn ghost" id="xAnnul">Annuler</button>
    </div>`);

  const champ = corps.querySelector('#xMotif');
  champ.focus();
  corps.querySelector('#xAnnul').onclick = fermerModale;
  corps.querySelector('#xDesactiver').onclick = () => { fermerModale(); desactiverEmplacement(e, revenir); };
  const lancer = () => {
    const motif = champ.value.trim();
    if (!motif) { toast('Indiquez le motif de la suppression.', 'err'); champ.focus(); return; }
    fermerModale();
    effacer(e, true, motif, revenir);
  };
  corps.querySelector('#xOk').onclick = lancer;
  champ.addEventListener('keydown', ev => { if (ev.key === 'Enter') lancer(); });
}

// L'alternative à la suppression : l'emplacement sort des écrans de rangement,
// son historique et son stock restent intacts.
async function desactiverEmplacement(e, revenir) {
  try {
    await api(`/emplacements/${e.id}/`, { method: 'PATCH', body: { actif: false } });
    toast(e.code + ' désactivé', 'ok');
    await rafraichirEmplacements();
    revenir();
  } catch (err) { toast(err.message, 'err'); }
}

async function effacer(e, force, motif, revenir) {
  const params = [force ? 'force=1' : '', motif ? 'motif=' + encodeURIComponent(motif) : '']
    .filter(Boolean).join('&');
  try {
    await api(`/emplacements/${e.id}/${params ? '?' + params : ''}`, { method: 'DELETE' });
    toast('Emplacement ' + e.code + ' supprimé', 'ok');
    await rafraichirEmplacements();
    revenir();
  } catch (err) { toast(err.message, 'err'); }
}

// --- Recherche par chantier : toutes les cabines affectées ------------------

// --- Journal : qui a fait quoi, quand --------------------------------------
async function renderJournal() {
  await refsCabine();
  layout(`<h2 class="title">Journal des cabines</h2>
    <div class="card"><label for="q">Filtrer</label><input id="q" placeholder="N° de cabine, chantier ou auteur">
      <label for="ty">Type d'événement</label><select id="ty"><option value="">Tous</option>${(REFS_CABINE.types_mouvement || []).map(t => `<option value="${t.code}">${esc(t.libelle)}</option>`).join('')}</select></div>
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'more');
  const charger = () => {
    const t = $('#q').value.trim(), ty = $('#ty').value;
    const q = [t ? 'search=' + encodeURIComponent(t) : '', ty ? 'type=' + ty : ''].filter(Boolean).join('&');
    return listePaginee($('#zone'), '/mouvements-cabine/?' + q, {
      ligne: (m) => `<div class="item" style="cursor:default">
        <div class="r">${esc(m.cabine_numero)} — ${esc(m.type_libelle)}${m.statut_apres ? ' → ' + esc(m.statut_apres_libelle) : ''}</div>
        ${(m.depuis || m.vers) ? `<div class="d">${esc(m.depuis || '—')} → ${esc(m.vers || '—')}</div>` : ''}
        <div class="meta">${new Date(m.date).toLocaleString('fr-FR')} · ${esc(m.utilisateur_nom || 'compte supprimé')}${m.chantier ? ' · chantier ' + esc(m.chantier) : ''}${m.note ? ' · ' + esc(m.note) : ''}</div>
      </div>`,
      vide: 'Aucun événement',
      entete: (total, vus) => `<div class="sec">${total} événement${total === 1 ? '' : 's'}`
        + (total > vus.length ? ` · ${vus.length} affiché${vus.length === 1 ? '' : 's'}` : '') + '</div>',
    });
  };
  $('#q').oninput = debounce(charger, 250);
  $('#ty').onchange = charger;
  charger();
}

// --- Zones -----------------------------------------------------------------
// Même principe que les emplacements : création en haut dans une fenêtre, et
// une fiche unique pour tout modifier. Avant, le clic sur une zone ne permettait
// de changer que son rôle — pas son nom, pas son ordre, et rien ne se supprimait.

/* --- Onglet Entrée : ajouter une cabine ------------------------------------
   La fiche imprimée en production ne porte aucun code : on la recopie une fois,
   puis on imprime une étiquette QR à coller. C'est cette étiquette qui rend les
   scans suivants possibles — la saisie n'a lieu qu'à l'entrée, jamais après.

   La lecture de la fiche par reconnaissance de texte a été retirée : elle ne
   fonctionnait pas. L'analyseur serveur (`wms/lecture_fiche.py`) et son endpoint
   `POST /api/cabines/analyser-fiche/` restent en place, testés, prêts à être
   rebranchés sur une source d'OCR qui marche.                                  */

const CHAMPS_ENTREE = [
  ['numero', 'N° de cabine (REF. CABINE) *', 'Ex. 26_03_47'],
  ['chantier', 'N° de commande / chantier *', 'Ex. 251280'],
  ['modele', 'Modèle (CABINE)', 'Ex. QUATTRO'],
  ['revendeur', 'Revendeur', 'Ex. MYAH'],
  ['client', 'Client', 'Ex. HAS'],
  ['tissu_bk', 'Tissu BK', 'Ex. A2419'],
  ['tissu_aq', 'Tissu AQ', 'Ex. A2414'],
  ['fond_cabine', 'Fond de cabine', 'Ex. VITRE'],
];

// Envoie la photo au serveur, qui reconnaît le texte puis l'analyse, et pré-remplit.
async function envoyerPhotoFiche(fichier) {
  if (!fichier) return;
  const etat = $('#ocrEtat');
  etat.innerHTML = '<div class="meta">Lecture de la photo en cours… (quelques secondes)</div>';
  const corps = new FormData();
  corps.append('photo', fichier);
  try {
    const r = await fetchReseau(API + '/cabines/lire-fiche/', {
      method: 'POST',
      headers: token ? { Authorization: 'Token ' + token } : {},
      body: corps,   // pas de Content-Type : le navigateur pose la frontière multipart
    });
    const txt = await r.text();
    let d = null;
    try { d = txt ? JSON.parse(txt) : null; } catch (_) { throw new Error('Réponse illisible du serveur.'); }
    if (!r.ok) throw new Error(messageErreur(d, r.status));

    let lus = 0;
    CHAMPS_ENTREE.forEach(([cle]) => {
      if (d.champs[cle]) { $('#e_' + cle).value = d.champs[cle]; lus++; }
    });
    const manque = d.manquants || [];
    etat.innerHTML = `<div class="banner" style="${manque.length ? '' : 'background:var(--ok-tint);color:var(--ok)'}">
      ${lus} champ${lus === 1 ? '' : 's'} lu${lus === 1 ? '' : 's'} sur la photo.
      ${manque.length
        ? 'Non lu : ' + manque.map(m => m === 'numero' ? 'n° de cabine' : 'n° de commande').join(', ') + ' — à saisir à la main.'
        : 'Relis les valeurs avant de valider : la reconnaissance peut confondre 0 et O.'}
      </div>`;
    if (d.cabine_existante) {
      $('#apres').innerHTML = `<div class="banner" style="margin-top:12px">Cette cabine est déjà enregistrée.</div>
        <div class="list">${ligneCabine(d.cabine_existante)}</div>`;
      $('#apres').querySelector('.item').onclick = () => ficheCabine(d.cabine_existante, renderEntree);
    }
  } catch (e) {
    etat.innerHTML = `<div class="banner">${esc(e.message)}<br>Saisis les champs à la main ci-dessous.</div>`;
  }
}

/* ===========================================================================
   ENTRÉE D'UNE CABINE — le numéro d'abord, le reste vient du fichier

   L'écran demandait la photo de la fiche papier, puis onze champs à relire.
   Depuis que la production fournit ses spécifications (écran « Fichier de
   production »), tout est déjà connu : la seule chose que l'opérateur a à
   apporter, c'est QUELLE cabine il a devant lui.

   Le chemin manuel n'a pas disparu, et ne doit pas disparaître : une cabine
   absente du fichier — un salon, une occasion, une ligne oubliée — doit pouvoir
   entrer en stock. Elle prend alors l'ancien parcours, photo comprise.
   =========================================================================== */

const MOTIF_NUMERO_CABINE = /^\d{2}_\d{2}_\d{1,3}$/;

async function renderEntree() {
  await refsCabine();
  layout(`<h2 class="title">Entrée d'une cabine</h2>
    <div class="card">
      <div class="sec">1 · Quelle cabine ?</div>
      <label for="eNum">N° de cabine</label>
      <input id="eNum" placeholder="Ex. 26_02_49" autocomplete="off">
      <div class="meta" style="margin-top:6px">Celui de la fiche ou de l'étiquette. Les caractéristiques viennent du fichier de production.</div>
      <div id="eEtat" style="margin-top:10px"></div>
    </div>
    <div id="eSuite"></div>`, 'entree');

  masquerNumero($('#eNum'));
  const champ = $('#eNum');
  const chercher = debounce(() => interrogerAttendue(champ.value.trim()), 350);
  champ.oninput = chercher;
  champ.onkeydown = (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); interrogerAttendue(champ.value.trim()); }
  };
  champ.focus();

  // Numéro apporté par un écran de rangement qui a refusé une cabine inconnue :
  // le cariste ne le retape pas, il l'a déjà lu une fois.
  const apporte = ENTREE_NUMERO;
  ENTREE_NUMERO = null;
  if (apporte) { champ.value = apporte; interrogerAttendue(apporte); }
}

/** Le numéro saisi est-il déjà en stock, annoncé par la production, ou inconnu ?
    Trois réponses, trois écrans. L'ordre compte : une cabine déjà en stock ne se
    recrée pas, et le dire tout de suite évite un 400 après onze champs remplis. */
async function interrogerAttendue(numero) {
  const etat = $('#eEtat'), suite = $('#eSuite');
  if (!etat || !suite) return;
  if (!numero) { etat.innerHTML = ''; suite.innerHTML = ''; return; }
  if (!MOTIF_NUMERO_CABINE.test(numero)) {
    etat.innerHTML = `<div class="meta">Format attendu : 26_02_49 (jusqu'à 3 chiffres à la fin).</div>`;
    suite.innerHTML = '';
    return;
  }

  etat.innerHTML = '<div class="meta">Recherche…</div>';
  // Déjà en stock ? La question se pose d'abord : `?numero=` cherche « contient »,
  // on retient donc la correspondance exacte et rien d'autre.
  try {
    const d = await api('/cabines/?numero=' + encodeURIComponent(numero));
    const deja = (d.results || []).find(c => c.numero === numero);
    if (deja) {
      etat.innerHTML = `<div class="banner">La cabine ${esc(numero)} est <b>déjà enregistrée</b>${deja.position ? ` — rangée en ${esc(deja.position)}` : ''}.</div>`;
      suite.innerHTML = `<div class="card" style="margin-top:12px">
        <button class="btn" id="eVoir">Ouvrir sa fiche</button></div>`;
      $('#eVoir').onclick = () => ouvrirEcran(() => ficheCabine(deja, renderEntree), 'fiche');
      return;
    }
  } catch (e) { etat.innerHTML = `<div class="banner">${esc(e.message)}</div>`; return; }

  let attendue = null;
  try {
    attendue = await api('/cabines-attendues/' + encodeURIComponent(numero) + '/');
  } catch (_) { attendue = null; }   // 404 : pas dans le fichier, saisie manuelle

  if (attendue) { etat.innerHTML = ''; blocAttendue(attendue); return; }

  // Absente du fichier. Trois cas, et le serveur applique exactement la même
  // règle — l'écran ne fait que ne pas proposer un formulaire voué au refus.
  if (!REFS_CABINE.fichier_production) {
    // Aucun fichier importé : le WMS fonctionne comme avant, à la saisie. La
    // règle ne s'arme qu'avec le premier import, sinon rien ne pourrait entrer.
    etat.innerHTML = `<div class="banner">Aucun fichier de production n’a encore été
      importé : les caractéristiques sont à saisir à la main.</div>`;
    blocSaisieManuelle(numero);
    return;
  }
  if (!ADMIN) {
    etat.innerHTML = '';
    blocRefusHorsFichier(numero);
    return;
  }
  etat.innerHTML = `<div class="banner"><b>${esc(numero)}</b> n’est pas annoncée par le
    fichier de production. En tant qu’administrateur tu peux la créer quand même —
    dis pourquoi, ce sera écrit au journal.</div>`;
  blocSaisieManuelle(numero, { horsFichier: true });
}

const LIGNES_ATTENDUE = [
  ['chantier', 'Chantier'], ['gamme', 'Gamme'], ['modele', 'Modèle'],
  ['semaine_production', 'Semaine de production'], ['jour', 'Jour'],
  ['revendeur', 'Revendeur'], ['client', 'Client'],
  ['tissu_bk', 'Tissu BK'], ['tissu_aq', 'Tissu AQ'], ['tissu_ext', 'Tissu extérieur'],
  ['fond_cabine', 'Fond de cabine'], ['num_unique', 'N° unique production'],
];

/** La cabine est annoncée : on montre ce qu'on sait, on ne le fait pas resaisir.

    Les valeurs ne sont pas dans des champs de saisie, et c'est volontaire : les
    rendre modifiables ferait de cet écran une seconde source de vérité, qui
    divergerait du fichier au premier import suivant. Une caractéristique fausse
    se corrige dans le fichier — ou après création, par « Corriger la fiche ». */
function blocAttendue(a) {
  const lignes = LIGNES_ATTENDUE
    .filter(([cle]) => (a[cle] || '') !== '')
    .map(([cle, lib]) => `<tr><td>${esc(lib)}</td><td><b>${esc(a[cle])}</b></td></tr>`).join('');
  const specs = Object.entries(a.specifications || {});

  $('#eSuite').innerHTML = `<div class="card" style="margin-top:12px">
    <div class="banner" style="background:var(--ok-tint);color:var(--ok)">
      Cabine reconnue dans le fichier de production. Rien à recopier.</div>
    <div class="specs"><table><tbody>${lignes}</tbody></table></div>
    ${specs.length ? `<details style="margin-top:10px"><summary class="meta">Toutes les caractéristiques (${specs.length})</summary>
      <div class="specs"><table><tbody>${specs
        .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')}</tbody></table></div></details>` : ''}
    ${a.chantier_a_saisir ? `<div class="banner" style="margin-top:12px">
        Le fichier porte le chantier « ${esc(a.chantier_brut)} », que le WMS ne peut pas
        enregistrer tel quel : il attend 6 chiffres. Saisis le n° de chantier.</div>
      <label for="eChantier">N° de chantier</label>
      <input id="eChantier" placeholder="6 chiffres" inputmode="numeric" autocomplete="off" maxlength="6">` : ''}
    <label for="e_type" style="margin-top:12px">Type de cabine</label>
    <select id="e_type">${REFS_CABINE.types.map(t =>
      `<option value="${t.code}">${esc(t.libelle)}</option>`).join('')}</select>
    <div class="meta" style="margin-top:6px">${esc(aideChantier())}</div>
    <button class="btn orange" id="eCreer">Créer la cabine ${esc(a.numero)}</button>
  </div>
  <div id="apres"></div>`;

  $('#eCreer').onclick = async (ev) => {
    const bouton = ev.currentTarget;
    const corps = { ...a.champs_cabine, type_cabine: $('#e_type').value };
    const saisi = $('#eChantier');
    if (saisi) corps.chantier = saisi.value.trim();
    bouton.disabled = true;
    try {
      await creerCabine(corps);
    } catch (e) { bouton.disabled = false; toast(e.message, 'err'); }
  };
}

/** Cabine absente du fichier, compte non administrateur : c'est un refus.

    Inventer la fiche d'une cabine inconnue n'a plus de sens depuis que la
    production annonce ses caractéristiques : l'opérateur n'a pas les éléments,
    et la reconnaissance de texte confond 0 et O. Deux explications, et une
    seule personne pour trancher — on le dit plutôt que d'ouvrir un formulaire
    que le serveur refusera. */
function blocRefusHorsFichier(numero) {
  $('#eSuite').innerHTML = `<div class="card" style="margin-top:12px">
    <div class="banner">La cabine <b>${esc(numero)}</b> n’est pas annoncée par le
      fichier de production : elle ne peut pas être enregistrée.</div>
    <div class="meta">Soit le dernier fichier n’a pas encore été importé, soit cette
      cabine n’y figure pas. Dans les deux cas c’est un administrateur qui tranche :
      préviens-le avec ce numéro.</div>
    <button class="btn ghost" id="eAutre">Une autre cabine</button>
  </div>`;
  $('#eAutre').onclick = renderEntree;
}

/** Chemin manuel : photo de la fiche puis relecture des champs. Réservé aux
    administrateurs dès qu'un fichier de production est importé, et alors avec
    un motif — c'est le serveur qui l'exige, cet écran ne fait que le demander. */
function blocSaisieManuelle(numero, options = {}) {
  $('#eSuite').innerHTML = `<div class="card" style="margin-top:12px">
      <div class="sec">2 · Photographier la fiche (facultatif)</div>
      <input type="file" id="photo" accept="image/*" capture="environment">
      <div class="meta" style="margin-top:6px">Cadre le tableau bien à plat. La photo est lue par le serveur : rien à installer sur le téléphone.</div>
      <div id="ocrEtat"></div>
    </div>
    <div class="card" style="margin-top:12px">
      <div class="sec">3 · Vérifier et compléter</div>
      <div id="champs">${CHAMPS_ENTREE.map(([cle, lib, ph]) =>
        `<label>${esc(lib)}</label><input id="e_${cle}" placeholder="${esc(ph)}" autocomplete="off">`).join('')}
        <label>Type de cabine</label>
        <select id="e_type">${REFS_CABINE.types.map(t => `<option value="${t.code}">${esc(t.libelle)}</option>`).join('')}</select>
        <div class="meta" style="margin-top:6px">${esc(aideChantier())}</div>
        ${options.horsFichier ? `<label for="eMotif" style="margin-top:12px">Pourquoi cette cabine n’est-elle pas dans le fichier ? *</label>
        <input id="eMotif" placeholder="Ex. cabine de salon, hors chantier" autocomplete="off" maxlength="180">
        <div class="meta" style="margin-top:6px">Écrit au journal avec ton nom. C’est
          la seule trace de cette exception.</div>` : ''}
      </div>
      <button class="btn orange" id="eCreer">Créer la cabine</button>
    </div>
    <div id="apres"></div>`;

  masquerNumero($('#e_numero'));
  $('#e_numero').value = numero;
  $('#photo').onchange = (ev) => envoyerPhotoFiche(ev.target.files[0]);
  $('#eCreer').onclick = creerCabineDepuisEntree;
}

async function creerCabineDepuisEntree() {
  const corps = { type_cabine: $('#e_type').value };
  CHAMPS_ENTREE.forEach(([cle]) => { corps[cle] = $('#e_' + cle).value.trim(); });
  if (!corps.numero) { toast('Le n° de cabine est obligatoire.', 'err'); return; }
  // Le serveur refuse une création hors fichier sans motif ; l'annoncer ici évite
  // un aller-retour et un message d'erreur là où une phrase suffit.
  const motif = $('#eMotif');
  if (motif) {
    corps.motif_hors_fichier = motif.value.trim();
    if (!corps.motif_hors_fichier) {
      toast('Dis pourquoi tu crées cette cabine hors fichier.', 'err');
      motif.focus();
      return;
    }
  }
  try { await creerCabine(corps); } catch (e) { toast(e.message, 'err'); }
}

/** Création, puis les deux gestes qui suivent au poste : coller l'étiquette,
    ranger. Un seul endroit crée une cabine — les deux chemins d'entrée
    aboutissaient sinon à deux enchaînements différents. */
async function creerCabine(corps) {
  const c = await api('/cabines/', { method: 'POST', body: corps });
  toast('Cabine ' + c.numero + ' créée', 'ok');
  noterRecentCabine(c);
  $('#apres').innerHTML = `<div class="card" style="margin-top:12px">
    <div class="r">${esc(c.numero)} — ${esc(c.chantier || 'sans chantier')}</div>
    <div class="sec" style="margin-top:12px">Ranger</div>
    <div class="row">
      <button class="btn ghost" id="aScan" style="margin-top:0">Scanner l'emplacement</button>
      <button class="btn ghost" id="aFiche" style="margin-top:0">Saisir le code</button>
    </div>
    <button class="btn ghost" id="aPlus">Entrer une autre cabine</button>
    <div id="aZone"></div></div>`;
  $('#aPlus').onclick = renderEntree;
  $('#aScan').onclick = () => { CABINE_A_RANGER = c; go('trouver'); };
  $('#aFiche').onclick = () => ficheCabine(c, renderEntree);
  return c;
}

/* --- Gestion des emplacements : fusionnée dans « Emplacements » -------------
   Il y avait deux écrans quasi identiques (« Emplacements » pour l'occupation,
   « Gestion des emplacements » pour les réglages) et un troisième formulaire
   après un scan. Trois portes, trois jeux de champs, aucune suppression. Tout
   est désormais dans `renderEmplacements` → `ficheEmplacement`. Ce renvoi reste
   pour les raccourcis et les habitudes déjà prises.                          */


/* --- Écran Stock (volet articles, archivé) -----------------------------------
   Tous les articles avec leur quantité totale ; au clic, les emplacements où
   l'article est rangé. Le total vient de l'API (annotation `total_stock`) : on ne
   télécharge pas toutes les lignes de stock pour les additionner ici.          */

// État dérivé de la quantité et du seuil. Partagé avec l'écran d'un article, pour
// que la même situation ne se lise pas différemment d'un écran à l'autre.
function etatStock(a) {
  const total = Number(a.total_stock) || 0;
  const seuil = Number(a.stock_min) || 0;
  if (total <= 0) return ['crit', 'Épuisé'];
  if (seuil > 0 && total < seuil) return ['att', 'Sous seuil'];
  return ['ok', 'En stock'];
}

const ligneStock = (a) => {
  const [cls, libelle] = etatStock(a);
  const n = a.nb_emplacements || 0;
  const lieux = n === 0 ? 'aucun emplacement' : n + (n > 1 ? ' emplacements' : ' emplacement');
  return `<div class="item" data-id="${a.id}">
    <div class="r">${esc(a.ref)} <span class="etat ${cls}">${libelle}</span></div>
    <div class="d">${esc(a.designation)}</div>
    <div class="meta">${fmt(a.total_stock)} ${esc(a.unite || '')}${Number(a.stock_min) > 0 ? ' · seuil ' + fmt(a.stock_min) : ''} · ${lieux}</div>
  </div>`;
};

let STOCK_TERME = '';

function renderStock() {
  layout(`<h2 class="title">Stock</h2>
    <div class="card"><label>Filtrer</label><input id="q" placeholder="Référence, code-barres ou désignation"></div>
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'more');
  const champ = $('#q');
  champ.value = STOCK_TERME;
  champ.setAttribute('autocomplete', 'off');
  champ.oninput = debounce(() => { STOCK_TERME = champ.value.trim(); chargerStock(1); }, 250);
  champ.focus();
  chargerStock(1);
}

async function chargerStock(page, deja) {
  const zone = $('#zone');
  if (!zone) return;
  // Pagination par 50 : on charge à la demande plutôt que 694 articles d'un coup.
  const filtre = STOCK_TERME.length >= 2 ? '&search=' + encodeURIComponent(STOCK_TERME) : '';
  try {
    const d = await api('/articles/?ordering=ref' + filtre + '&page=' + page);
    const arts = (deja || []).concat(d.results || []);
    const reste = Math.max(0, (d.count || 0) - arts.length);
    zone.innerHTML = `<div class="sec">${d.count} article${d.count === 1 ? '' : 's'}${STOCK_TERME ? ' pour « ' + esc(STOCK_TERME) + ' »' : ''}</div>
      <div class="list" id="lst">${arts.length ? arts.map(ligneStock).join('') : '<div class="empty">Aucun article</div>'}</div>
      ${d.next ? `<button class="btn ghost" id="plus">Charger la suite (${reste} restant${reste === 1 ? '' : 's'})</button>` : ''}`;
    zone.querySelectorAll('#lst .item').forEach(it => it.onclick = () => {
      const a = arts.find(x => String(x.id) === it.dataset.id);
      if (a) montrerArticle(a, renderStock);
    });
    const plus = $('#plus');
    if (plus) plus.onclick = () => {
      plus.disabled = true; plus.textContent = 'Chargement…';
      chargerStock(page + 1, arts);
    };
  } catch (e) { zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

// Écran d'un article scanné ou choisi : stock par emplacement + entrée / sortie.
// La spec (docs/inventaire-maquette-wms.md, écran `scanpick`) prévoit ces actions ;
// l'écran se contentait d'afficher le stock, sans rien permettre.
// `retour` : callback facultatif, affiche un bouton de retour (écran Stock).
async function montrerArticle(a, retour) {
  noterRecent(a);
  try {
    const lignes = await apiAll('/stock/?article=' + a.id);
    const total = lignes.reduce((s, l) => s + Number(l.qte), 0);
    const avecStock = lignes.filter(l => Number(l.qte) > 0);
    const [cls, libelle] = etatStock({ total_stock: total, stock_min: a.stock_min });
    $('#zone').innerHTML = `
      ${retour ? '<button class="btn ghost" id="sRetour" style="margin:0 0 12px">← Retour au stock</button>' : ''}
      <div class="card"><div class="muted small" style="font-family:var(--f-data);font-weight:700;color:var(--orange)">${esc(a.ref)}</div>
        <div class="r" style="font-size:16px;font-weight:700;margin-top:2px">${esc(a.designation)}</div>
        <div class="meta" style="margin-top:3px">total ${fmt(total)} ${esc(a.unite || '')}${Number(a.stock_min) > 0 ? ' · seuil ' + fmt(a.stock_min) : ''} <span class="etat ${cls}">${libelle}</span></div>
        ${peut('mvt') ? '<div class="row" style="margin-top:12px"><button class="btn" id="sIn">Ajouter du stock</button><button class="btn orange" id="sOut">Retirer du stock</button></div>' : ''}
        <div id="sAct"></div></div>
      <div class="sec">Emplacements où cet article est rangé</div>
      <div class="list">${avecStock.length
        ? avecStock.map(l => `<div class="item" style="cursor:default"><div class="r">${esc(l.emplacement_code)}</div><div class="d">${fmt(l.qte)} ${esc(a.unite || '')}</div></div>`).join('')
        : '<div class="empty">Cet article n’est rangé nulle part.</div>'}
        ${lignes.length > avecStock.length ? `<div class="meta" style="padding:2px 4px">${lignes.length - avecStock.length} emplacement(s) à quantité nulle, masqué(s).</div>` : ''}</div>`;

    if (retour) $('#sRetour').onclick = retour;
    if (!peut('mvt')) return;

    const valider = (url, libelle) => async () => {
      try {
        await api(url, { method: 'POST', body: { article: a.id, emplacement: $('#sEmp').value, qte: $('#sQte').value } });
        toast(libelle, 'ok');
        montrerArticle(a);
      } catch (e) { toast(e.message, 'err'); }
    };

    $('#sIn').onclick = () => {
      if (!EMPS.filter(e => !e.staging).length) { $('#sAct').innerHTML = '<div class="empty">Crée d\'abord un emplacement.</div>'; return; }
      $('#sAct').innerHTML = `<label>Emplacement</label><select id="sEmp">${empOptsAvecDefaut(a.emplacement_defaut)}</select>
        <label>Quantité</label><input id="sQte" type="number" min="0" step="any" value="1">
        <button class="btn orange" id="sOk">Valider l’entrée</button>`;
      $('#sOk').onclick = valider('/operations/entree/', 'Entrée enregistrée');
    };

    $('#sOut').onclick = () => {
      if (!avecStock.length) { $('#sAct').innerHTML = '<div class="empty">Aucun stock à retirer.</div>'; return; }
      $('#sAct').innerHTML = `<label>Emplacement</label><select id="sEmp">${avecStock.map(l => `<option value="${l.emplacement}">${esc(l.emplacement_code)} — ${fmt(l.qte)} dispo</option>`).join('')}</select>
        <label>Quantité</label><input id="sQte" type="number" min="0" step="any" value="1">
        <button class="btn orange" id="sOk">Valider la sortie</button>`;
      $('#sOk').onclick = valider('/operations/sortie/', 'Sortie enregistrée');
    };
  } catch (e) { toast(e.message, 'err'); }
}

/* --- Caméra : un bouton qu'on voit, pas un lien anglais ---------------------
   `Html5QrcodeScanner` fournit une interface toute faite : un lien
   « Request Camera Permissions » en anglais, en petit, au milieu d'un cadre vide,
   accompagné d'un « Scan an Image File » dont personne n'a l'usage ici. Au poste,
   téléphone tenu d'une main et gants sur l'autre, ce lien ne se trouve pas.

   On pilote donc la classe bas niveau `Html5Qrcode` et on habille le déclencheur
   nous-mêmes : une zone pleine largeur, l'icône de l'appareil photo, un bouton
   orange, et une phrase qui dit ce qui va se passer. L'autorisation du navigateur
   n'est demandée qu'au clic — jamais à l'ouverture de l'écran, où elle arrive
   sans contexte et se fait refuser.                                            */

//: Instance en cours. `go()` s'en sert pour éteindre la caméra en quittant l'écran :
//: une caméra laissée allumée vide la batterie et bloque l'appli suivante.
let CAMERA = null;

function blocCameraHTML(titre, sousTitre) {
  return `<div class="cam" id="cam">
    <div class="cam-vue" id="reader"></div>
    <div class="cam-repos" id="camRepos">
      <div class="cam-ico">${icon('camera', 38)}</div>
      <div class="cam-t">${esc(titre)}</div>
      <div class="cam-st">${esc(sousTitre)}</div>
      <button class="btn orange cam-btn" id="camGo">${icon('camera', 20)} Activer la caméra</button>
      <div class="cam-note" id="camNote">Le navigateur va demander l’autorisation. Elle n’est demandée qu’une fois.</div>
    </div>
    <button class="btn ghost cam-stop" id="camStop" hidden>Arrêter la caméra</button>
    <div class="cam-lu" id="camLu" hidden></div>
  </div>`;
}

/* --- Ce qui a été lu, avant d'agir -----------------------------------------
   Le décodage est immédiat, et l'application enchaînait aussitôt : la caméra
   s'éteignait, l'écran suivant s'ouvrait, et personne n'avait vu passer le code.
   Au poste, cela donnait des gens qui ne savaient pas quel emplacement ils
   venaient de scanner — trois étiquettes empilées sur le même montant, et rien
   à l'écran pour dire laquelle avait été prise.

   On s'arrête donc un instant : le code en grand, et deux boutons. « Continuer »
   fait exactement ce que faisait la lecture avant, « Rescanner » rallume la
   caméra. Le décodage n'est pas ralenti d'une milliseconde — c'est
   l'enchaînement qui demande un appui, et c'est tout ce qui manquait.

   La vibration sert au cas où la lecture arrive alors qu'on ne regarde pas
   l'écran : elle dit « c'est lu », sans obliger à fixer le téléphone.        */
function confirmerLecture(texte, surLecture) {
  const lu = (texte || '').trim();
  vibrer(40);
  const bloc = $('#camLu');
  // Un écran qui n'a pas de zone de confirmation garde l'ancien comportement :
  // mieux vaut enchaîner que perdre la lecture.
  if (!bloc) { surLecture(lu); return; }
  bloc.hidden = false;
  bloc.innerHTML = `<div class="lu-t">Code lu</div>
    <div class="lu-code">${esc(lu.replace(/^(LOC|CAB|ART):/i, ''))}</div>
    <div class="row">
      <button class="btn orange" id="luOk" style="margin-top:0">Continuer</button>
      <button class="btn ghost" id="luNon" style="margin-top:0">Rescanner</button>
    </div>`;
  const fermer = () => { bloc.hidden = true; bloc.innerHTML = ''; };
  const ok = bloc.querySelector('#luOk');
  ok.onclick = () => { fermer(); surLecture(lu); };
  bloc.querySelector('#luNon').onclick = () => {
    fermer();
    const go = $('#camGo');
    if (go) go.click();          // on rallume : la visée reprend là où elle était
  };
  ok.focus();
}

/** Traduit l'échec du navigateur en geste à faire, plutôt qu'en nom d'erreur. */
function messageCamera(e) {
  const nom = (e && (e.name || e.message)) || '';
  if (/NotAllowed|Permission/i.test(nom)) {
    return 'Autorisation refusée. Dans la barre d’adresse, touche le cadenas → '
         + 'Autorisations → Caméra → Autoriser, puis recharge la page.';
  }
  if (/NotFound|Devices/i.test(nom)) return 'Aucune caméra détectée sur cet appareil.';
  if (/NotReadable|TrackStart/i.test(nom)) {
    return 'La caméra est déjà utilisée par une autre application. Ferme-la et réessaie.';
  }
  if (/Overconstrained/i.test(nom)) return 'Aucune caméra arrière : réessaie, la caméra avant sera utilisée.';
  return 'Caméra indisponible : ' + esc(String(e && e.message || nom || 'raison inconnue'));
}

/** Éteint la caméra si elle tourne. Sans effet sinon, et ne lève jamais. */
async function arreterCamera() {
  const lecteur = CAMERA;
  CAMERA = null;
  if (!lecteur) return;
  try { await lecteur.stop(); } catch (e) {}
  try { lecteur.clear(); } catch (e) {}
}

/* Réglages appliqués APRÈS le démarrage : ils ne sont pas tous acceptés à
   l'ouverture du flux, et un réglage refusé à ce moment-là fait échouer toute la
   caméra. Ici, ce qui passe passe ; ce qui ne passe pas est ignoré.

   La torche est proposée seulement si l'appareil la déclare. Dans une allée de
   rack, c'est la différence entre une étiquette lue et une étiquette recopiée
   à la main. */
function reglerCamera(lecteur) {
  let piste = null;
  try {
    const flux = document.querySelector('#reader video');
    piste = flux && flux.srcObject && flux.srcObject.getVideoTracks()[0];
  } catch (_) { return; }
  if (!piste) return;

  try { piste.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (_) {}

  let capacites = {};
  try { capacites = (piste.getCapabilities && piste.getCapabilities()) || {}; } catch (_) {}
  if (!('torch' in capacites)) return;

  const stop = $('#camStop');
  if (!stop || $('#camTorche')) return;
  stop.insertAdjacentHTML('beforebegin',
    '<button class="btn ghost cam-stop" id="camTorche" type="button">Éclairer</button>');
  let allumee = false;
  $('#camTorche').onclick = async () => {
    allumee = !allumee;
    try {
      await piste.applyConstraints({ advanced: [{ torch: allumee }] });
      $('#camTorche').textContent = allumee ? 'Éteindre la lampe' : 'Éclairer';
    } catch (_) { allumee = !allumee; }
  };
}

/** Branche le bloc caméra rendu par `blocCameraHTML`. `surLecture(texte)` au scan. */
function brancherCamera(surLecture) {
  const bouton = $('#camGo'), repos = $('#camRepos'), note = $('#camNote'),
        stop = $('#camStop'), cadre = $('#cam');
  if (!bouton) return;

  const eteindre = async () => {
    await arreterCamera();
    if (!$('#cam')) return;             // l'écran a changé entre-temps
    repos.hidden = false; stop.hidden = true; cadre.classList.remove('actif');
    bouton.disabled = false;
  };

  bouton.onclick = async () => {
    bouton.disabled = true;
    note.textContent = 'Autorisation demandée…';
    // Le conteneur doit être VISIBLE avant `start()`. html5-qrcode mesure sa
    // largeur pour dimensionner la vidéo et le cadre de visée : sur un conteneur
    // en `display:none` il lit 0 et n'affiche rien. La caméra tournait bien —
    // voyant allumé, bouton passé à « Arrêter » — mais l'écran restait vide.
    cadre.classList.add('actif');
    try {
      const lecteur = new Html5Qrcode('reader', false, {
        // Détecteur de codes NATIF du navigateur quand il existe. C'est la
        // correction qui compte sur Android : Chrome décode alors le QR dans le
        // système, en une fraction du temps que met le décodeur JavaScript, et
        // sur des images bien plus dégradées. Sans lui, une étiquette un peu de
        // biais ou mal éclairée n'était tout simplement jamais lue.
        experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      });
      CAMERA = lecteur;
      await lecteur.start(
        { facingMode: 'environment' },
        {
          // 15 images par seconde : le décodeur natif les tient sans peine, et
          // doubler les tentatives double les chances sur une main qui bouge.
          fps: 15,
          // Cadre de visée calculé sur la vidéo réelle. Une valeur fixe de 250 px
          // dépasse la largeur d'un téléphone tenu en portrait, et html5-qrcode
          // refuse alors de démarrer.
          //
          // 0,6 et non 0,8 : sur un montant, Y500, Y501 et Y502 sont collées à
          // quelques centimètres l'une de l'autre. Un cadre large les prenait
          // toutes les trois dans le champ, et c'est celle qui entrait la
          // première qui gagnait. Un cadre plus serré oblige à viser — et sur un
          // flux de 1280 px de large, il reste 768 px pour le code : bien assez.
          qrbox: (l, h) => { const c = Math.floor(Math.min(l, h) * 0.6); return { width: c, height: c }; },
          // `aspectRatio: 1` forçait un flux carré. Android n'en produit pas :
          // il rendait alors sa plus petite définition, souvent 480 px de large,
          // sur laquelle un QR d'étiquette ne fait plus assez de pixels pour être
          // décodé. On demande la définition, pas la forme.
          videoConstraints: {
            facingMode: 'environment',
            width: { ideal: 1280 }, height: { ideal: 720 },
            // Mise au point continue : sans elle, Android reste sur la mise au
            // point de l'infini et l'étiquette tenue à 30 cm reste floue.
            advanced: [{ focusMode: 'continuous' }],
          },
        },
        (texte) => { eteindre(); confirmerLecture(texte, surLecture); },
        () => {});                       // échecs de décodage : normaux, image par image
      if (!$('#cam')) { await arreterCamera(); return; }
      repos.hidden = true; stop.hidden = false;
      reglerCamera(lecteur);
    } catch (e) {
      CAMERA = null;
      cadre.classList.remove('actif');   // retour à l'état de repos, bouton compris
      bouton.disabled = false;
      note.innerHTML = messageCamera(e);
      note.classList.add('erreur');
    }
  };
  stop.onclick = eteindre;
}

async function renderTrouver(titre = 'Trouver une cabine') {
  const secure = window.isSecureContext;
  const hasLib = typeof Html5Qrcode !== 'undefined';
  layout(`<h2 class="title">${esc(titre)}</h2>
    ${(secure && hasLib) ? blocCameraHTML('Scanner un QR code', 'Emplacement, cabine ou article')
      : `<div class="banner">${!hasLib
          ? 'Lecteur de QR non chargé : ce poste n’a pas accès à internet. Un administrateur doit lancer une fois « python manage.py telecharger_libs » sur le serveur pour rendre le scan et les étiquettes autonomes. En attendant, saisie manuelle ci-dessous.'
          : 'Caméra indisponible ici (HTTPS requis). Sur le téléphone, ouvre l’appli via l’adresse https du tunnel pour scanner à la caméra ; ici, saisie manuelle.'}</div>`}
    <div class="card"><label>${VOLET_ARTICLES ? 'Code scanné ou début de référence' : 'Code scanné, n° de cabine ou emplacement'}</label>
      <input id="code" placeholder="${VOLET_ARTICLES ? 'Ex. VITR. — les propositions s’affichent en tapant' : 'Ex. 00_00_01 ou C001 — les propositions s’affichent en tapant'}">
      <div class="list" id="sugg"></div>
      <button class="btn" id="go">Valider</button></div>
    <div id="zone"></div>`, 'trouver');

  const champ = $('#code');
  champ.setAttribute('autocomplete', 'off');

  const choisirArticle = (a) => { $('#sugg').innerHTML = ''; champ.value = a.ref; noterRecent(a); montrerArticle(a); };
  const choisirEmplacement = (e) => {
    $('#sugg').innerHTML = '';
    champ.value = e.code;
    // Volet cabines : l'emplacement scanné propose ranger / sortir avec les places G-M-D.
    if (VOLET_ARTICLES) showLocation(e); else montrerEmplacement(e, { retour: () => go('trouver') });
  };
  const choisirCabine = (c) => {
    $('#sugg').innerHTML = '';
    champ.value = c.numero;
    noterRecentCabine(c);
    ouvrirEcran(() => ficheCabine(c, () => history.back()), 'fiche');
  };

  // Suggestions en direct sur les DEUX référentiels : au poste on scanne aussi bien
  // une étiquette d'article qu'une étiquette d'emplacement.
  const suggerer = debounce(async () => {
    const brut = champ.value.trim();
    const t = brut.replace(/^(ART|LOC):/i, '').trim();
    const liste = $('#sugg');
    if (!liste) return;
    if (t.length < 2) {
      // Récents du bon référentiel : les cabines quand le volet articles est archivé.
      // Les cabines sont relues auprès du serveur — voir recentsCabinesAJour().
      const r = VOLET_ARTICLES ? recents() : await recentsCabinesAJour();
      if (champ.value.trim().length >= 2) return;   // l'opérateur a tapé entre-temps
      const rendu = VOLET_ARTICLES ? itemHTML : ligneCabine;
      liste.innerHTML = r.length
        ? `<div class="sec">Consultées récemment</div>${r.map(rendu).join('')}`
        : '';
      SUGG = {}; r.forEach(x => SUGG[x.id] = x);
      liste.querySelectorAll('.item').forEach(it => it.onclick = () => {
        const choix = SUGG[it.dataset.id];
        if (VOLET_ARTICLES) choisirArticle(choix); else choisirCabine(choix);
      });
      return;
    }
    try {
      const cherchePlaces = !/^ART:/i.test(brut);
      const [arts, emps, cabs] = await Promise.all([
        (VOLET_ARTICLES && !/^LOC:/i.test(brut)) ? chercherArticles(t) : Promise.resolve([]),
        cherchePlaces ? api('/emplacements/?search=' + encodeURIComponent(t)).then(d => d.results || []) : Promise.resolve([]),
        (!VOLET_ARTICLES && !/^LOC:/i.test(brut))
          ? api('/cabines/?numero=' + encodeURIComponent(t)).then(d => d.results || []).catch(() => [])
          : Promise.resolve([]),
      ]);
      const lotA = arts.slice(0, SUGG_MAX);
      SUGG = {};
      lotA.forEach(a => SUGG[a.id] = a);
      const blocEmp = emps.length
        ? `<div class="sec">Emplacements</div>${emps.slice(0, 4).map(e => `<div class="item" data-emp="${e.id}"><div class="r">${esc(e.code)}</div><div class="d">${esc(e.zone_cabine_nom || e.zone || '')}</div></div>`).join('')}`
        : '';
      const blocCab = cabs.length
        ? `<div class="sec">Cabines</div>${cabs.slice(0, 5).map(c => `<div class="item" data-cab="${c.id}"><div class="r">${esc(c.numero)} ${badgeStatut(c)}</div><div class="d">Chantier ${esc(c.chantier || '—')}</div></div>`).join('')}`
        : '';
      const blocArt = lotA.length
        ? `<div class="sec">Articles</div>${lotA.map(itemHTML).join('')}${arts.length > lotA.length ? `<div class="meta" style="padding:6px 2px">${arts.length} correspondances — précise pour affiner</div>` : ''}`
        : '';
      liste.innerHTML = (blocEmp + blocCab + blocArt) || '<div class="empty">Aucun résultat</div>';
      liste.querySelectorAll('.item[data-id]').forEach(it => it.onclick = () => choisirArticle(SUGG[it.dataset.id]));
      liste.querySelectorAll('.item[data-emp]').forEach(it => it.onclick = () => {
        const e = emps.find(x => String(x.id) === it.dataset.emp);
        if (e) choisirEmplacement(e);
      });
      liste.querySelectorAll('.item[data-cab]').forEach(it => it.onclick = () => {
        const c = cabs.find(x => String(x.id) === it.dataset.cab);
        if (c) choisirCabine(c);
      });
    } catch (e) { toast(e.message, 'err'); }
  }, 200);

  // Valider / Entrée / lecture caméra : code complet attendu, on résout à l'exact.
  // Si le texte est ambigu, on n'échoue plus en cul-de-sac : on montre les choix.
  const run = async () => {
    const brut = (champ.value || '').trim();
    if (!brut) return;
    try {
      if (/^LOC:/i.test(brut)) {
        const code = brut.slice(4).trim().toUpperCase();
        const d = await api('/emplacements/?search=' + encodeURIComponent(code));
        const res = d.results || [];
        const e = res.find(x => (x.code || '').toUpperCase() === code) || (res.length === 1 ? res[0] : null);
        if (!e) { suggerer(); toast(res.length ? 'Plusieurs emplacements correspondent, choisis dans la liste.' : 'Emplacement introuvable', 'err'); return; }
        choisirEmplacement(e);
        return;
      }
      const ref = brut.replace(/^(ART|CAB):/i, '').trim();
      const cible = ref.toUpperCase();

      if (!VOLET_ARTICLES) {
        // Sans préfixe, le texte peut désigner une cabine OU un emplacement : on
        // interroge les deux. Auparavant seules les cabines étaient cherchées, si bien
        // que taper « C001 » répondait « introuvable » alors que l'emplacement existait.
        const cherchePlace = !/^CAB:/i.test(brut);
        const [cabs, emps] = await Promise.all([
          api('/cabines/?toutes=1&numero=' + encodeURIComponent(ref))
            .then(d => d.results || []).catch(() => []),
          cherchePlace ? api('/emplacements/?search=' + encodeURIComponent(ref))
            .then(d => d.results || []).catch(() => []) : Promise.resolve([]),
        ]);
        // Une correspondance exacte l'emporte, quel que soit le référentiel.
        const empExact = emps.find(x => (x.code || '').toUpperCase() === cible);
        const cabExact = cabs.find(x => (x.numero || '').toUpperCase() === cible);
        if (cabExact) { choisirCabine(cabExact); return; }
        if (empExact) { choisirEmplacement(empExact); return; }
        if (cabs.length + emps.length === 1) {
          if (cabs.length) choisirCabine(cabs[0]); else choisirEmplacement(emps[0]);
          return;
        }
        suggerer();
        toast(cabs.length + emps.length
          ? 'Plusieurs correspondances, choisis dans la liste.'
          : 'Ni cabine ni emplacement ne correspond à « ' + ref + ' »', 'err');
        return;
      }

      const arts = await chercherArticles(ref);
      const a = arts.find(x => (x.ref || '').toUpperCase() === cible || (x.ean || '').toUpperCase() === cible)
             || (arts.length === 1 ? arts[0] : null);
      if (!a) {
        suggerer();
        toast(arts.length ? 'Plusieurs articles correspondent, choisis dans la liste.' : 'Article introuvable', 'err');
        return;
      }
      choisirArticle(a);
    } catch (e) { toast(e.message, 'err'); }
  };

  champ.oninput = suggerer;
  champ.onfocus = () => { if (!champ.value.trim()) suggerer(); };
  $('#go').onclick = run;
  champ.addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
  suggerer();

  if (secure && hasLib) {
    brancherCamera((texte) => { champ.value = texte; run(); });
  }
}

async function renderDashboard() {
  layout('<h2 class="title">Tableau de bord</h2><div class="empty">Chargement…</div>', 'home');
  try {
    const d = await api('/tableau-de-bord/');
    const bas = d.stock_bas.map(b => `<div class="item"><div class="r">${esc(b.ref)}</div><div class="d">${esc(b.designation)}</div><div class="meta">stock ${fmt(b.stock)} / seuil ${fmt(b.min)}</div></div>`).join('');
    const mv = d.derniers_mouvements.map(m => `<div class="item"><div class="r">${esc(m.type)} · ${fmt(m.qte)}</div><div class="d">${esc(m.article)} @ ${esc(m.emplacement)}</div><div class="meta">${new Date(m.date).toLocaleString('fr-FR')}</div></div>`).join('');
    layout(`<h2 class="title">Tableau de bord</h2>
      <div class="kpis">
        <div class="kpi"><div class="l">Références</div><div class="v">${d.references}</div></div>
        <div class="kpi"><div class="l">Emplacements</div><div class="v">${d.emplacements}</div></div>
        <div class="kpi"><div class="l">Mouvements</div><div class="v">${d.mouvements}</div></div>
        <div class="kpi warn"><div class="l">À ranger</div><div class="v">${fmt(d.a_ranger)}</div></div>
      </div>
      <div class="duo">
        <div><div class="sec">À commander (${d.stock_bas.length})</div><div class="list">${bas || '<div class="empty">Aucun article sous le seuil</div>'}</div></div>
        <div><div class="sec">Derniers mouvements</div><div class="list">${mv || '<div class="empty">Aucun</div>'}</div></div>
      </div>`, 'home');
  } catch (e) { toast(e.message, 'err'); }
}

/* « Plus » : tout ce que le menu autorise, moins ce qui est déjà dans la barre du
   bas. La liste était écrite une deuxième fois ici, en dur et sans filtrage par
   les droits : un cariste s'y voyait proposer les zones et les étiquettes, deux
   écrans que le serveur lui refuse. Elle dérivait aussi du menu à chaque ajout —
   « Suivi du processus » y serait resté après avoir été retiré partout ailleurs. */
function renderMore() {
  const dansLaBarre = new Set((ONGLETS[profil()] || ONGLETS.lecture).map(o => o[0]));
  const items = menuLateral()
    .flatMap(([, liens]) => liens)
    .filter(([cle]) => !dansLaBarre.has(cle));
  layout(`<h2 class="title">Plus</h2><div class="list">${items.map(([g,l,ic]) => `<div class="item" data-go="${g}"><div class="r">${icon(ic,18)} ${l}</div></div>`).join('')}</div><button class="btn ghost" id="logout" style="margin-top:16px">Se déconnecter (${esc(USER)})</button>`, 'more');
  $('#logout').onclick = logout;
}

/* --- Accès des testeurs -----------------------------------------------------
   On entre dans l'application en scannant un QR code collé dans l'entrepôt. On
   arrivait alors devant deux champs vides : le testeur, téléphone en main devant
   une cabine, n'a aucune raison de connaître l'identifiant du compte d'essai.

   Le serveur peut donc les pré-remplir — `WMS_ACCES_TEST=identifiant:motdepasse`
   dans le .env. Il reste un bouton à appuyer : on voit sous quel compte on entre,
   et « Se déconnecter » ne reboucle pas sur une reconnexion automatique. Sans la
   variable, l'écran est celui de toujours, et rien n'est écrit dans la page.   */
function accesTest() {
  const bloc = document.getElementById('acces-test');
  if (!bloc) return null;
  try { return JSON.parse(bloc.textContent); } catch (_) { return null; }
}

function renderLogin() {
  const essai = accesTest();
  el().innerHTML = `<div class="login"><div class="logo">WMS Structa</div><div class="sub">Connexion</div>
    <div class="card">${essai ? `<div class="banner">Campagne de test : le compte d’essai est déjà renseigné. Appuyer sur « Se connecter ».</div>` : ''}<label>Identifiant</label>
    <input id="u" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" value="${esc(essai && essai.identifiant)}">
    <label>Mot de passe</label>
    <input id="p" type="password" autocomplete="current-password" autocapitalize="none" autocorrect="off" spellcheck="false" value="${esc(essai && essai.motdepasse)}">
    <button class="btn" id="go">Se connecter</button></div></div>`;
  const submit = async () => { try { await doLogin(el().querySelector('#u').value.trim(), el().querySelector('#p').value); await boot(); } catch (e) { toast(e.message, 'err'); } };
  el().querySelector('#go').onclick = submit;
  el().querySelector('#p').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  el().querySelector(essai ? '#go' : '#u').focus();
}

async function boot() {
  // Vestige : les récents d'articles restaient dans le navigateur après l'archivage du
  // volet articles et remontaient dans le scanner de cabines.
  if (!VOLET_ARTICLES) { try { localStorage.removeItem('wms_recents'); } catch (_) {} }
  const [, moi] = await Promise.all([
    rafraichirEmplacements(),
    api('/moi/').catch(() => null),
  ]);
  DROITS = (moi && moi.droits) || {};
  ADMIN = Boolean(moi && moi.administrateur);
  // Le nom affiché vient du serveur : depuis que la casse de l'identifiant est
  // tolérée, ce qui a été tapé n'est pas forcément l'orthographe du compte.
  if (moi && (moi.nom || moi.username)) {
    USER = moi.nom || moi.username;
    try { localStorage.setItem('wms_user', USER); } catch (_) {}
  }
  // Premier barreau de la pile : sans lui, le tout premier « retour » sortirait
  // de l'application au lieu de ramener à l'accueil.
  // Premier barreau de la pile : le Scanner, qui est l'accueil.
  PILE = [() => { ECRAN = 'scanner'; renderScanner(); }];
  RANG = 0;
  try { history.replaceState({ rang: 0 }, '', '#home'); } catch (_) {}
  renderScanner();
}

// Chargées à la demande : utiles seulement pour créer une référence.
async function categories() {
  if (!CATS.length) { try { CATS = await apiAll('/categories/'); } catch (_) { CATS = []; } }
  return CATS;
}

if (token) { boot(); } else { renderLogin(); }

/* ===========================================================================
   FICHIER DE PRODUCTION — l'import des cabines attendues

   La production tient un classeur Excel des cabines à venir, avec toutes leurs
   caractéristiques. L'importer ici évite de recopier onze champs à chaque
   entrée : l'opérateur n'aura plus qu'à saisir le numéro.

   Deux temps, jamais un seul : on ANALYSE le fichier, on montre ce qui va se
   passer, et on n'écrit qu'après confirmation. Le fichier réel contient de
   vraies erreurs de saisie — découvrir après coup qu'on a importé le mauvais
   classeur n'est pas une option.

   Écran réservé aux administrateurs. Le serveur le refuse aussi (403) : ce
   n'est pas l'interface qui protège, elle évite seulement de proposer un
   bouton qui ne marcherait pas.
   =========================================================================== */

let IMPORT = { fichier: null, rapport: null };

async function renderImport() {
  if (!ADMIN) {
    layout(`<h2 class="title">Fichier de production</h2>
      <div class="banner">L'import du fichier de production est réservé aux comptes
      administrateurs.</div>`, 'import');
    return;
  }
  IMPORT = { fichier: null, rapport: null };
  layout(`<h2 class="title">Fichier de production</h2>
    <div id="impEtatBase"><div class="empty">Chargement…</div></div>
    <div class="card" style="margin-top:12px">
      <div class="sec">Importer un classeur</div>
      <input type="file" id="impFichier" accept=".xlsx,.xlsm">
      <div class="meta" style="margin-top:6px">Le classeur Excel de la production
        (.xlsx). La colonne <b>CABINE</b> identifie chaque ligne. Rien n'est écrit
        avant que vous ne confirmiez.</div>
    </div>
    <div id="impRapport"></div>`, 'import');

  $('#impFichier').onchange = (ev) => analyserFichierImport(ev.target.files[0]);
  etatCabinesAttendues();
}

/** Ce que la table contient déjà. Sans ce repère, on ne sait pas si un import a
    jamais eu lieu, ni de quel fichier vient ce qui est en base. */
async function etatCabinesAttendues() {
  const zone = $('#impEtatBase');
  if (!zone) return;
  try {
    const d = await api('/cabines-attendues/?ordering=-importe_le&page=1');
    const derniere = (d.results || [])[0];
    zone.innerHTML = `<div class="card">
      <div class="r" style="font-size:18px;font-weight:700">${d.count} cabine${d.count === 1 ? '' : 's'} attendue${d.count === 1 ? '' : 's'}</div>
      <div class="meta" style="margin-top:4px">${derniere
        ? `Dernier import : ${esc(derniere.fichier || 'fichier sans nom')}, le
           ${new Date(derniere.importe_le).toLocaleString('fr-FR')}${derniere.importe_par_nom ? ' par ' + esc(derniere.importe_par_nom) : ''}`
        : 'Aucun import pour l’instant : les entrées se font entièrement à la main.'}</div>
      <div class="meta" style="margin-top:6px">Ces lignes ne sont pas du stock : elles
        décrivent ce qu'on attend. Une cabine entre en stock quand elle arrive.</div>
    </div>`;
  } catch (e) { zone.innerHTML = `<div class="banner">${esc(e.message)}</div>`; }
}

async function analyserFichierImport(fichier) {
  const zone = $('#impRapport');
  if (!fichier || !zone) return;
  IMPORT = { fichier, rapport: null };
  zone.innerHTML = `<div class="card" style="margin-top:12px"><div class="meta">Lecture de
    ${esc(fichier.name)} (${ko(fichier.size)} Ko)… quelques secondes.</div></div>`;
  try {
    const corps = new FormData();
    corps.append('fichier', fichier);
    const r = await fetchReseau(API + '/cabines-attendues/analyser/', {
      method: 'POST',
      headers: token ? { Authorization: 'Token ' + token } : {},
      body: corps,
    });
    const txt = await r.text();
    let d = null;
    try { d = txt ? JSON.parse(txt) : null; }
    catch (_) { throw new Error('Réponse illisible du serveur.'); }
    if (!r.ok) throw new Error(messageErreur(d, r.status));
    IMPORT.rapport = d;
    dessinerRapportImport(d);
  } catch (e) {
    zone.innerHTML = `<div class="card" style="margin-top:12px">
      <div class="banner">${esc(e.message)}</div></div>`;
  }
}

const LIGNE_RAPPORT = (libelle, valeur, fort) =>
  `<tr><td>${esc(libelle)}</td><td>${fort ? '<b>' + valeur + '</b>' : valeur}</td></tr>`;

function dessinerRapportImport(d) {
  const zone = $('#impRapport');
  if (!zone) return;
  const erreurs = d.erreurs || [];
  const MONTRE = 60;

  zone.innerHTML = `<div class="card" style="margin-top:12px">
    <div class="sec">Ce que cet import ferait</div>
    <div class="meta" style="margin-bottom:8px">${esc(d.fichier)} — ${d.lignes} ligne${d.lignes === 1 ? '' : 's'}, ${d.colonnes} colonnes</div>
    <div class="specs"><table><tbody>
      ${LIGNE_RAPPORT('Lignes retenues', d.retenues, true)}
      ${LIGNE_RAPPORT('· nouvelles', d.nouvelles)}
      ${LIGNE_RAPPORT('· à mettre à jour', d.modifiees)}
      ${LIGNE_RAPPORT('· inchangées', d.inchangees)}
      ${LIGNE_RAPPORT('Lignes refusées', erreurs.length, erreurs.length > 0)}
      ${d.sans_chantier ? LIGNE_RAPPORT('Sans n° de chantier exploitable', d.sans_chantier) : ''}
      ${d.absentes_du_fichier ? LIGNE_RAPPORT('Déjà en base et absentes de ce fichier', d.absentes_du_fichier + ' — conservées') : ''}
    </tbody></table></div>

    ${d.sans_chantier ? `<div class="banner" style="margin-top:12px">
      ${d.sans_chantier} ligne${d.sans_chantier === 1 ? '' : 's'} porte${d.sans_chantier === 1 ? '' : 'nt'} un chantier
      que le WMS ne peut pas enregistrer — « 251213-1 » au lieu de 6 chiffres. La
      cabine est quand même importée avec toutes ses caractéristiques ; le n° de
      chantier sera demandé à l'entrée.</div>` : ''}

    ${erreurs.length ? `<details style="margin-top:12px" open>
      <summary class="meta"><b>${erreurs.length} ligne${erreurs.length === 1 ? '' : 's'} refusée${erreurs.length === 1 ? '' : 's'}</b> — à corriger dans le classeur</summary>
      <div class="specs" style="max-height:320px;overflow:auto"><table><thead>
        <tr><th>Ligne</th><th>N° lu</th><th>Motif</th></tr></thead><tbody>
        ${erreurs.slice(0, MONTRE).map(e => `<tr><td class="court">${e.ligne}</td>
          <td class="court">${esc(e.numero || e.indice || '—')}</td>
          <td>${esc(e.motif)}</td></tr>`).join('')}
      </tbody></table></div>
      ${erreurs.length > MONTRE ? `<div class="meta" style="margin-top:6px">${erreurs.length - MONTRE} autres non affichées — la liste complète est dans le fichier ci-dessous.</div>` : ''}
      <button class="btn ghost" id="impCsv">${icon('in', 17)} Télécharger la liste des refus (CSV)</button>
    </details>` : ''}

    ${d.colonnes_libres && d.colonnes_libres.length ? `<details style="margin-top:8px">
      <summary class="meta">${d.colonnes_libres.length} colonnes conservées telles quelles</summary>
      <div class="meta" style="margin-top:6px">${esc(d.colonnes_libres.join(' · '))}</div>
      <div class="meta" style="margin-top:6px">Elles sont enregistrées et affichées sur
        la fiche, sans que le WMS s'appuie dessus. « MONTANT NET PRODUIT » est la seule
        colonne volontairement ignorée.</div></details>` : ''}

    ${d.retenues ? `<button class="btn orange" id="impOk">Importer ${d.retenues} ligne${d.retenues === 1 ? '' : 's'}</button>`
      : `<div class="banner" style="margin-top:12px">Aucune ligne exploitable dans ce
         fichier. Rien à importer.</div>`}
    <button class="btn ghost" id="impAnnul">Choisir un autre fichier</button>
  </div>`;

  const csv = $('#impCsv');
  if (csv) csv.onclick = () => telechargerRefus(d);
  const annul = $('#impAnnul');
  if (annul) annul.onclick = renderImport;
  const ok = $('#impOk');
  if (ok) ok.onclick = () => appliquerImport(ok);
}

/** La liste des refus en CSV : c'est dans Excel qu'on les corrige, pas à l'écran.
    Point-virgule et BOM — Excel en français ouvre le reste en une seule colonne. */
function telechargerRefus(d) {
  const lignes = [['Ligne', 'N° lu', 'Indice', 'Motif']]
    .concat((d.erreurs || []).map(e => [e.ligne, e.numero || '', e.indice || '', e.motif]));
  const texte = '﻿' + lignes
    .map(l => l.map(v => `"${String(v).replace(/"/g, '""')}"`).join(';')).join('\r\n');
  const url = URL.createObjectURL(new Blob([texte], { type: 'text/csv;charset=utf-8' }));
  const lien = document.createElement('a');
  lien.href = url;
  lien.download = 'lignes-refusees.csv';
  document.body.appendChild(lien); lien.click(); lien.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

async function appliquerImport(bouton) {
  if (!IMPORT.fichier || !IMPORT.rapport) return;
  const d = IMPORT.rapport;
  const ok = await confirmer({
    titre: `Importer ${d.retenues} ligne(s) ?`,
    texte: `${d.nouvelles} cabine(s) ajoutée(s), ${d.modifiees} mise(s) à jour, `
         + `${d.inchangees} inchangée(s).\n\n`
         + 'Les cabines attendues déjà en base et absentes de ce fichier sont '
         + 'conservées : un import n’efface jamais.\n\n'
         + 'Aucune cabine en stock n’est modifiée.',
    ok: 'Importer',
    annuler: 'Non',
  });
  if (!ok) return;

  bouton.disabled = true;
  bouton.textContent = 'Import en cours…';
  try {
    const corps = new FormData();
    corps.append('fichier', IMPORT.fichier);
    const r = await fetchReseau(API + '/cabines-attendues/importer/', {
      method: 'POST',
      headers: token ? { Authorization: 'Token ' + token } : {},
      body: corps,
    });
    const txt = await r.text();
    let rep = null;
    try { rep = txt ? JSON.parse(txt) : null; }
    catch (_) { throw new Error('Réponse illisible du serveur.'); }
    if (!r.ok) throw new Error(messageErreur(rep, r.status));
    toast(`${rep.importees} ligne(s) importée(s)`, 'ok');
    // Le premier import arme la règle « une cabine non annoncée ne s'enregistre
    // pas ». `REFS_CABINE` est mis en cache pour la session : sans cette remise à
    // zéro, l'écran d'entrée continuerait de proposer la saisie libre.
    REFS_CABINE = { statuts: [], types: [], places: [] };
    renderImport();
  } catch (e) {
    bouton.disabled = false;
    bouton.textContent = `Importer ${d.retenues} ligne(s)`;
    toast(e.message, 'err');
  }
}

/* ===========================================================================
   SCANNER — le point de départ de tout

   Trois façons de lire un numéro, une seule suite. L'ancien écran ne faisait
   qu'aiguiller vers « Ranger » ou vers « Trouver » : il fallait avoir choisi son
   geste avant de savoir de quelle cabine on parlait. Ici on identifie d'abord,
   et l'écran suivant propose ce que l'état de la cabine autorise.

   Le champ de saisie n'est plus replié. Il l'était, et c'était un vrai défaut :
   un navigateur pilotant l'application ne le « voyait » pas — au sens propre,
   il le considérait invisible. Un cariste pressé ne le voyait pas davantage.
   =========================================================================== */

async function renderScanner() {
  await refsCabine();
  layout(`<h2 class="title">Scanner</h2>
    ${rappelEnCours()}
    <div class="meta" style="margin:-4px 0 14px">Deux choses se scannent :
      la <b>fiche</b> collée sur la cabine, et le <b>QR d'un emplacement</b>.
      Les cabines ne portent pas de QR code.</div>
    <div class="gestes">
      <label class="geste" id="sFicheLab">
        <span class="ic">${icon('camera', 26)}</span>
        <span class="t">Photographier la fiche cabine</span>
        <span class="s">Le tableau à deux colonnes, collé sur la cabine</span>
        <input type="file" id="sFiche" accept="image/*" capture="environment">
      </label>
      <button class="geste" id="sQr">
        <span class="ic">${icon('scan', 26)}</span>
        <span class="t">Scanner le QR d’un emplacement</span>
        <span class="s">L’étiquette collée sur la travée</span>
      </button>
    </div>
    <div id="fEtat"></div>
    <div id="sCam"></div>
    <div class="card" style="margin-top:14px">
      <div class="sec" style="margin-top:0">Ou saisir le n° de cabine</div>
      <input id="sNum" placeholder="Ex. 26_03_47" autocomplete="off">
      <button class="btn ghost" id="sNumOk">Continuer</button>
    </div>
    <div id="aRanger"></div>`, 'scanner');
  brancherRappelEnCours();

  brancherChoixScanner();

  // Le compteur de l'ancien accueil : il dit s'il reste du travail, et il y mène.
  compter('rangee=0').then(n => {
    const z = $('#aRanger');
    if (!z) return;
    z.innerHTML = n
      ? `<button type="button" class="banner clic" data-voir style="margin-top:16px;width:100%;text-align:left;border:none;font:inherit">${
          n} cabine${n === 1 ? '' : 's'} en attente de rangement — voir la liste</button>`
      : '';
    const voir = z.querySelector('[data-voir]');
    if (voir) voir.onclick = () => ouvrirCabines({ rangee: '0' });
  }).catch(() => {});
}

/* ===========================================================================
   LES GESTES POSSIBLES — c'est l'état qui décide

   Un seul écran remplace le choix « Ranger / Sortir » fait à l'aveugle. Il
   énonce d'abord ce qu'est la cabine, puis ne propose que ce qui a un sens :
   une cabine qui n'est nulle part se range, une cabine rangée se déplace, se
   complète ou se sort, une cabine partie se remet en stock.

   Un geste impossible n'est pas masqué : il est affiché éteint, avec sa raison.
   Masquer laisse chercher ; dire évite le déplacement jusqu'au rack.

   Chaque bouton reprend un parcours qui existe déjà et qui est éprouvé — cet
   écran est un aiguillage, pas une réécriture des gestes.
   =========================================================================== */

const GESTES_ECRAN = { numero: '', cabine: null, attendue: null };

/** Point d'entrée unique : un numéro, et on va chercher ce qu'on en sait. */
async function ouvrirGestes(depart) {
  const numero = String((depart && depart.numero) || '').trim();
  if (!numero) { toast('Aucun numéro lu.', 'err'); return; }
  ouvrirEcran(async () => {
    ECRAN = 'gestes';
    layout(`<h2 class="title">${esc(numero)}</h2>
      <div class="empty">Recherche…</div>`, 'scanner');
    let cabine = (depart && depart.cabine) || null;
    let attendue = null;
    try {
      if (!cabine) {
        const d = await api('/cabines/?toutes=1&numero=' + encodeURIComponent(numero));
        cabine = (d.results || []).find(c => c.numero === numero) || null;
      }
      if (!cabine) {
        attendue = await api('/cabines-attendues/' + encodeURIComponent(numero) + '/')
          .catch(() => null);
      }
    } catch (e) {
      layout(`<h2 class="title">${esc(numero)}</h2>
        <div class="banner">${esc(e.message)}</div>
        ${piedGestes()}`, 'scanner');
      return;
    }
    GESTES_ECRAN.numero = numero;
    GESTES_ECRAN.cabine = cabine;
    GESTES_ECRAN.attendue = attendue;
    dessinerGestes();
  }, 'gestes');
}

/** Recharge la cabine puis redessine — après un geste qui l'a changée. */
async function rafraichirGestes() {
  const n = GESTES_ECRAN.numero;
  if (!n) return;
  try {
    const d = await api('/cabines/?toutes=1&numero=' + encodeURIComponent(n));
    GESTES_ECRAN.cabine = (d.results || []).find(c => c.numero === n) || null;
  } catch (_) {}
  dessinerGestes();
}

/* Nommé `gesteBouton` et pas `bouton` : une quinzaine de fonctions de ce
   fichier déclarent déjà un `const bouton` local pour le bouton qu'elles
   manipulent. Deux noms identiques à deux portées différentes se relisent mal,
   même quand le langage s'en sort. */
const gesteBouton = (id, titre, sous, options = {}) => `<button class="geste" id="${id}"${
  options.empeche ? ' disabled' : ''}>
  <span class="ic">${icon(options.icone || 'in', 26)}</span>
  <span class="t">${esc(titre)}</span>
  <span class="s">${esc(options.empeche || sous)}</span></button>`;

/* Le pied de tous les écrans du parcours de scan — voir plus haut, côté CSS,
   pourquoi il est commun. `fiche` n'est proposé que si la cabine existe : sans
   cabine en stock, il n'y a pas de fiche à ouvrir.
   Pas de troisième pastille vers le Parc : l'onglet « Parc » est en bas de
   l'écran en permanence, et un raccourci de plus vers ce qui est déjà à un
   doigt de distance est exactement le doublon qu'on retire partout ailleurs.
   Deux pastilles tiennent aussi sur une seule ligne — trois en font deux. */
const piedGestes = (options = {}) => `<div class="pied">
  ${options.fiche ? `<button id="gFiche">${icon('clip', 16)} Voir sa fiche</button>` : ''}
  <button data-go="scanner">${icon('scan', 16)} Une autre cabine</button>
</div>`;

function dessinerGestes() {
  const { numero, cabine, attendue } = GESTES_ECRAN;
  if (!cabine) return dessinerGestesSansCabine(numero, attendue);

  const range = cabineRangee(cabine);
  const partie = cabine.statut === 'envoye';
  const quarantaine = cabine.statut === 'quarantaine';
  // Sortir et envoyer exigent un n° de chantier pour TOUS les types : c'est la
  // règle du serveur, autant l'annoncer ici plutôt que d'échouer au bout.
  const sansChantier = !cabine.chantier
    ? 'Il faut d’abord un n° de chantier — corrige la fiche.' : '';

  const gestes = [];
  if (partie) {
    gestes.push(gesteBouton('gReprendre', 'La remettre en stock',
      'Elle est revenue : retour de chantier, livraison refusée', { icone: 'in' }));
  } else if (!range) {
    gestes.push(gesteBouton('gRanger', 'La ranger',
      'Scanner l’emplacement, puis toucher la place', { icone: 'in' }));
  } else {
    gestes.push(gesteBouton('gDeplacer', 'La déplacer',
      `Elle quitte ${cabine.position} pour un autre emplacement`, { icone: 'transfer' }));
    gestes.push(gesteBouton('gAjouter', 'Ajouter un emplacement',
      `Elle reste aussi en ${cabine.position}`, { icone: 'plus' }));
    gestes.push(gesteBouton('gSortir', 'La sortir de son emplacement',
      `Libère ${cabine.position}, la cabine reste en stock`,
      { icone: 'out', empeche: sansChantier }));
  }
  if (!partie) {
    gestes.push(gesteBouton('gEnvoyer', 'L’envoyer',
      'Elle quitte l’entrepôt — définitif',
      { icone: 'truck', empeche: sansChantier }));
    gestes.push(quarantaine
      ? gesteBouton('gStatut', 'Lever la quarantaine',
          'Elle redevient conforme', { icone: 'check' })
      : gesteBouton('gStatut', 'La mettre en quarantaine',
          'Un défaut la bloque : elle ne partira pas', { icone: 'alert' }));
  }

  layout(`<h2 class="title">${esc(cabine.numero)}</h2>
    <div class="card">
      <div class="r" style="font-size:17px;font-weight:700">${
        badgeStatut(cabine, { rangement: false })}
        ${range ? 'Rangée en ' + esc(cabine.position) : 'Non rangée'}</div>
      <div class="meta" style="margin-top:5px">Chantier ${
        cabine.chantier ? esc(cabine.chantier) : '<b>à affecter</b>'}${
        cabine.modele ? ' · ' + esc(cabine.modele) : ''}${
        cabine.client ? ' · ' + esc(cabine.client) : ''}</div>
      ${quarantaine && cabine.statut_motif
        ? `<div class="banner" style="margin:12px 0 0">Quarantaine : ${esc(cabine.statut_motif)}</div>` : ''}
    </div>
    <div class="sec">Que faites-vous ?</div>
    <div class="gestes">${gestes.join('')}</div>
    ${piedGestes({ fiche: true })}`, 'scanner');

  const sur = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  sur('#gFiche', () => ouvrirEcran(() => ficheCabine(cabine, () => rafraichirGestes()), 'fiche'));
  sur('#gRanger', () => versRangement(cabine, null));
  sur('#gDeplacer', () => versRangement(cabine, 'deplacer'));
  sur('#gAjouter', () => versRangement(cabine, 'ajouter'));
  sur('#gSortir', () => ouvrirSortie(cabine));
  sur('#gEnvoyer', async () => {
    if (await envoyerCabine(cabine)) { toast(`${cabine.numero} envoyée`, 'ok'); rafraichirGestes(); }
  });
  sur('#gStatut', () => {
    const vers = quarantaine ? 'libre' : 'quarantaine';
    confirmerChangementStatut(cabine, vers, () => rafraichirGestes());
  });
  sur('#gReprendre', async () => {
    const ok = await confirmer({
      titre: `Remettre ${cabine.numero} en stock ?`,
      texte: 'La cabine redevient conforme et non rangée. L’envoi reste écrit au '
           + 'journal, le retour s’y ajoute.',
      ok: 'La remettre en stock', annuler: 'Non',
    });
    if (!ok) return;
    try {
      await api(`/cabines/${cabine.id}/reprendre/`, { method: 'POST', body: {} });
      toast(`${cabine.numero} remise en stock`, 'ok');
      rafraichirGestes();
    } catch (e) { toast(e.message, 'err'); }
  });
}

/** Le geste de rangement, ouvert sur une cabine déjà identifiée. */
function versRangement(cabine, intention) {
  RANGEMENT = RANGEMENT_NEUF();
  RANGEMENT.cabine = cabine;
  RANGEMENT.intention = intention;
  go('rangement');
}

/** Pas de cabine à ce numéro : soit la production l'annonce, soit personne. */
function dessinerGestesSansCabine(numero, attendue) {
  if (!attendue) {
    layout(`<h2 class="title">${esc(numero)}</h2><div id="eSuite"></div>
      ${piedGestes()}`, 'scanner');
    if (REFS_CABINE.fichier_production && !ADMIN) blocRefusHorsFichier(numero);
    else { ENTREE_NUMERO = numero; go('entree'); }
    return;
  }
  const lignes = LIGNES_ATTENDUE
    .filter(([cle]) => (attendue[cle] || '') !== '')
    .map(([cle, lib]) => `<tr><td>${esc(lib)}</td><td><b>${esc(attendue[cle])}</b></td></tr>`).join('');
  layout(`<h2 class="title">${esc(numero)}</h2>
    <div class="card">
      <div class="banner" style="background:var(--ok-tint);color:var(--ok)">
        Annoncée par la production, pas encore en stock.</div>
      <div class="specs"><table><tbody>${lignes}</tbody></table></div>
    </div>
    <div class="sec">Que faites-vous ?</div>
    <div class="gestes">${gesteBouton('gEntrer', 'La faire entrer en stock',
      'Ses caractéristiques sont déjà là — rien à recopier', { icone: 'in' })}</div>
    ${piedGestes()}`, 'scanner');
  $('#gEntrer').onclick = () => { ENTREE_NUMERO = numero; go('entree'); };
}

/* --- Les deux choses qui se scannent ---------------------------------------

   La fiche papier collée sur la cabine, et le QR collé sur la travée. Rien
   d'autre : **les cabines ne portent pas de QR code**, et l'application n'en
   propose donc plus ni la lecture ni l'impression.

   Un choix explicite, pas une caméra qui devine. Faire chercher les deux à la
   même caméra doublerait le travail de décodage à chaque image — sur les
   téléphones du parc, c'est la mise au point qui souffre en premier. Deux
   boutons coûtent une pression et rendent le geste sûr.                      */
function brancherChoixScanner() {
  const photo = $('#sFiche');
  if (photo) {
    photo.onchange = (ev) => lireFiche(
      ev.target.files[0],
      (cabine) => ouvrirGestes({ numero: cabine.numero, cabine }),
      (champs) => ouvrirGestes({ numero: (champs && champs.numero) || '' }),
      (numero) => ouvrirGestes({ numero }));
  }

  const qr = $('#sQr');
  if (qr) qr.onclick = () => {
    const zone = $('#sCam');
    if (!zone) return;
    zone.innerHTML = blocCameraHTML('Scanner le QR d’un emplacement',
                                    'L’étiquette collée sur la travée');
    brancherCamera((texte) => retenirScanEmplacement(texte));
    // Un choix, puis la caméra : sans ce déclenchement il faudrait deux
    // pressions pour un geste que l'opérateur a déjà demandé.
    const go = $('#camGo');
    if (go) go.click();
    zone.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };

  const champ = masquerNumero($('#sNum'));
  const suivre = () => {
    const n = (champ.value || '').trim();
    if (!n) { toast('Saisis le n° de cabine.', 'err'); return; }
    ouvrirGestes({ numero: n });
  };
  $('#sNumOk').onclick = suivre;
  champ.onkeydown = (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); suivre(); } };
}

/** QR lu : c'est un emplacement. On tolère un n° de cabine par prudence — un
    code mal collé ne doit pas être un cul-de-sac. */
async function retenirScanEmplacement(texte) {
  const code = String(texte || '').replace(/^(LOC|CAB):/i, '').trim();
  if (!code) return;
  await arreterCamera();
  if (MOTIF_NUMERO_CABINE.test(code)) { ouvrirGestes({ numero: code }); return; }
  try {
    const res = (await api('/emplacements/?search=' + encodeURIComponent(code))).results || [];
    const e = res.find(x => (x.code || '').toUpperCase() === code.toUpperCase())
           || (res.length === 1 ? res[0] : null);
    if (!e) {
      const etat = $('#fEtat');
      if (etat) etat.innerHTML = `<div class="banner">Aucun emplacement ne porte le code
        « ${esc(code)} ». Vérifie l’étiquette, ou saisis le n° de la cabine.</div>`;
      return;
    }
    await montrerEmplacement(e, { retour: () => go('scanner') });
  } catch (err) { toast(err.message, 'err'); }
}
