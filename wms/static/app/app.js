const API = '/api';
let token = localStorage.getItem('wms_token') || '';
let USER = localStorage.getItem('wms_user') || '';
let EMPS = [];
/* --- Droits : une case par geste ----------------------------------------------
   Le serveur envoie, par /api/moi/, ce que le compte peut faire — une clé par
   case de sa fiche dans l'administration — et le nom de chaque case. L'écran
   ne propose que ce que le serveur acceptera ; quand il refuse quand même un
   geste, il dit QUELLE case manque, avec le mot de la fiche : c'est ce que
   l'administrateur cherchera pour la cocher.                                 */
let DROITS = {};
let LIBELLES_DROITS = {};

// N'affiche pas une commande que le serveur refusera : sans ce contrôle, l'opérateur
// remplit un formulaire pour découvrir un 403 à la validation.
const peut = (droit) => DROITS[droit] === true;
const peutUnDe = (droits) => droits.some(peut);
const DROITS_CABINES = ['cab_ranger', 'cab_statut', 'cab_envoyer', 'cab_corriger'];
const DROITS_EMPLACEMENTS = ['empl_service', 'empl_regler', 'empl_creer'];
/** A-t-il la main sur les emplacements — n'importe laquelle des trois cases ? */
const gereEmplacements = () => peutUnDe(DROITS_EMPLACEMENTS);
const libelleDroit = (droit) => LIBELLES_DROITS[droit] || droit;
/** La phrase d'un geste refusé : la case qui manque, et à qui la demander. */
const sansLeDroit = (droit) => `Ton compte n’a pas le droit « ${libelleDroit(droit)} ». `
  + 'Demande-le à l’administrateur du WMS.';
/** Garde des gestes : vrai, et un message, quand le compte n'a pas la case. */
function refuseSansDroit(droit) {
  if (peut(droit)) return false;
  toast(sansLeDroit(droit), 'err');
  return true;
}

const el = () => document.getElementById('app');
const $ = (s) => el().querySelector(s);
const esc = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
/* --- Saisie d'un n° de cabine ------------------------------------------------
   Le numéro a TOUJOURS la forme XX_XX_XX. Au poste, taper les tirets bas oblige
   à changer de clavier deux fois par cabine, avec des gants : on les pose donc
   tout seuls, et le champ n'accepte que des chiffres. `inputmode="numeric"`
   ouvre directement le pavé numérique du téléphone.                          */

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

const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

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
  // Matières premières : des feuilles empilées — le verre comme le carton
  // arrivent en paquets de plaques.
  couches:'<path d="M12 3.5l8.5 4.3-8.5 4.3-8.5-4.3z"/><path d="M3.5 12.1l8.5 4.3 8.5-4.3"/><path d="M3.5 16.3l8.5 4.2 8.5-4.2"/>',
  // La cloche des alertes, en haut à droite.
  cloche:'<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.6 2.1H4.4z"/><path d="M10 20.4a2.1 2.1 0 0 0 4 0"/>',
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
        <input id="cfChamp" placeholder="${esc(champ.placeholder || '')}" autocomplete="off">
        <div class="manque" id="cfManque"></div>` : ''}
      <div class="modal-actions">
        <button class="btn ${danger ? 'danger' : 'orange'}" type="button" data-oui>${esc(ok)}</button>
        ${extra ? `<button class="btn ${extra.danger ? 'danger' : 'ghost'}" type="button" data-extra>${esc(extra.libelle)}</button>` : ''}
        ${annuler ? `<button class="btn ghost" type="button" data-non>${esc(annuler)}</button>` : ''}
      </div>`, { surFermeture: () => resoudre(reponse) });
    // Avec un champ, la reponse porte ce qui a ete saisi : `{ok, valeur}`. Sans
    // champ, elle reste le `true` que tous les appels connaissent deja.
    corps.querySelector('[data-oui]').onclick = () => {
      const saisi = corps.querySelector('#cfChamp');
      const valeur = (saisi ? saisi.value : '').trim();
      /* Un champ obligatoire garde la fenêtre OUVERTE et met le curseur dedans.
         La refermer en affichant une erreur ferait tout reprendre depuis le
         geste précédent — et sur un téléphone, à côté d'un rack, c'est le genre
         de friction qui pousse à écrire « ok » pour passer. */
      if (champ && champ.obligatoire && !valeur) {
        if (saisi) {
          saisi.focus();
          saisi.setAttribute('aria-invalid', 'true');
        }
        const dit = corps.querySelector('#cfManque');
        if (dit) dit.textContent = champ.manque || 'Cette information est obligatoire.';
        return;
      }
      reponse = champ ? { ok: true, valeur } : true;
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

function logout() {
  token = ''; USER = '';
  // Les droits partent avec le compte : le suivant reçoit les siens au boot.
  DROITS = {}; LIBELLES_DROITS = {};
  localStorage.removeItem('wms_token'); localStorage.removeItem('wms_user');
  // Le compte suivant n'a peut-être ni la cloche ni le droit de régler les
  // seuils : rien ne doit en rester.
  fermerAlertes();
  ALERTES = { total: 0, empreinte: null, groupes: null, vues: lireAlertesVues() };
  quitterReglageSeuils(false);
  renderLogin();
}

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

/* --- Profil d'usage --------------------------------------------------------
   Trois façons de se servir du WMS, déduites des droits DÉJÀ appliqués par le
   serveur : aucun rôle supplémentaire à administrer.

   Pourquoi masquer plutôt que griser : un cariste à qui l'on présente onze
   destinations dont neuf lui sont interdites cherche son bouton au lieu de
   ranger. Les écrans restent joignables par leur nom — rien n'est supprimé,
   seulement retiré du chemin de celui qui n'en a pas l'usage.                */
function profil() {
  if (gereEmplacements() || peut('modeles')) return 'gestion';
  if (peutUnDe(DROITS_CABINES)) return 'cariste';
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
/* « MP » s'ajoute pour les matières premières — vitrages et cartons. Un
   quatrième onglet et non un geste de plus dans le Scanner : on y arrive avec
   une palette ou un chevalet, pas avec une cabine, et le parcours est autre.

   Les onglets portent désormais le nom de ce qu'on y trouve, comme « MP » :
   l'ancien « Scanner » s'appelle « Cabines » — tout geste sur une cabine y
   commence —, et l'ancien « Parc » s'appelle « Stock » : on y cherche les
   cabines ET les matières premières, et « parc » ne se dit pas d'une palette
   de verre. Les clés d'écran (`scanner`, `cabines`) ne changent pas : ce sont
   elles que retiennent l'historique du navigateur et les liens déjà posés. */
const ONGLETS_COMMUNS = [['scanner', 'Cabines', 'build'],
                         ['cabines', 'Stock', 'search'],
                         ['mp', 'MP', 'couches'],
                         ['more', 'Plus', 'menu']];
const ONGLETS = { cariste: ONGLETS_COMMUNS, gestion: ONGLETS_COMMUNS,
                  lecture: ONGLETS_COMMUNS };

function navBar(active) {
  const items = ONGLETS[profil()] || ONGLETS.lecture;
  return `<div class="nav">${items.map(([g,l,ic]) => `<button data-go="${g}" class="${active===g?'on':''}"><span class="ic">${icon(ic,22)}</span>${l}</button>`).join('')}</div>`;
}

// Écran courant, pour surligner la bonne entrée de la barre latérale. Renseigné par
// go() ; les rendus rappelés directement (après un enregistrement) conservent la valeur.
let ECRAN = 'home';


// Barre latérale : desktop seulement. Elle expose TOUTES les destinations, là où le
// mobile en cache la moitié derrière l'onglet « Plus ».
/* Sept entrées au lieu de treize. Ce qui a disparu, et pourquoi :

   - « Ranger », « Sortir » et « Créer une cabine » demandaient chacun QUELLE
     cabine avant de proposer leur geste. C'est le Scanner qui pose désormais
     cette question, une seule fois, et l'état de la cabine décide de la suite.
     Les écrans existent toujours : on y arrive par le geste, plus par le menu.
   - « Trouver une cabine » faisait exactement ce que fait le Scanner.
   - « Par chantier » et « Cabines envoyées » n'étaient que le Parc avec un
     filtre posé. Le champ de recherche du Parc cherche déjà un n° de chantier,
     et « Envoyées » y est un filtre rapide.
   - « Zones » : elles se règlent dans l'administration, pas au poste.     */
const MENU_CABINES = [
  ['Cabines', [['scanner','Scanner une cabine','scan'],
               ['cabines','Stock des cabines','build'],
               ['home','Tableau de bord','chart']]],
  ['Suivi', [['journal','Journal','history']]],
  ['Matières premières', [['mp','Entrer, sortir','couches'],
                          ['stockmp','Stock MP','search'],
                          ['journalmp','Journal MP','history']]],
  // « Emplacements » ouvre l'écran unique : occupation, création, réglages et
  // suppression au même endroit. Il est ici, dans le référentiel, parce que
  // c'est là qu'on vient quand on cherche à ajouter ou corriger un emplacement.
  ['Référentiel', [['emplacements','Emplacements','box'],
                   ['modeles','Modèles de cabine','tag'],
                   ['etiquettes','Étiquettes','print'],
                   // La case « importer le fichier de production » — voir `menuLateral`.
                   // « Repartir de zéro » n'est plus ici : vider l'entrepôt
                   // n'est pas un geste de poste. Il vit dans /admin, derrière
                   // un second mot de passe, trois phrases à recopier et une
                   // sauvegarde écrite avant le premier effacement.
                   ['import','Fichier de production','clip']]],
];

/* Ce que chaque profil voit dans le menu. Un cariste garde de quoi retrouver
   une cabine ; il n'a pas à naviguer dans le référentiel, qu'il ne peut pas
   modifier de toute façon — le serveur refuserait. */
const MENU_PAR_PROFIL = {
  cariste: ['scanner', 'cabines', 'mp', 'stockmp', 'journalmp'],
  lecture: ['scanner', 'cabines', 'emplacements', 'mp', 'stockmp', 'journalmp'],
};

function menuLateral() {
  const base = MENU_CABINES;
  const permis = MENU_PAR_PROFIL[profil()];
  // L'import ne dépend pas du profil mais de SA case : la personne qui tient le
  // planning n'a pas forcément d'autre droit, et un gestionnaire n'a pas
  // forcément celui-là. Le serveur refuse de toute façon (403) ; ceci évite
  // seulement de proposer un écran sans effet.
  const ouvert = (cle) => (cle === 'import' ? peut('production')
                                            : (!permis || permis.includes(cle)));
  return base
    .map(([titre, liens]) => [titre, liens.filter(([cle]) => ouvert(cle))])
    .filter(([, liens]) => liens.length);
}

/** L'entrée du menu à surligner : celle de ce qui est À L'ÉCRAN. Le Stock côté
    MP, c'est « Stock MP » ; une fiche, c'est l'écran dont elle dépend. */
function entreeMenuActive() {
  if (ECRAN === 'cabines' && PARC_MODE === 'mp') return 'stockmp';
  return { 'fiche-emplacement': 'emplacements', 'mp-emplacement': 'mp',
           'fiche-mp': 'stockmp' }[ECRAN] || ECRAN;
}

function sideBar() {
  const active = entreeMenuActive();
  const groupes = menuLateral().map(([titre, liens]) =>
    `<span class="grp">${esc(titre)}</span>` + liens.map(([cle, libelle, ic]) =>
      `<button data-go="${cle}" class="${active === cle ? 'on' : ''}">${icon(ic, 18)}${esc(libelle)}</button>`).join('')
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
  // La cloche vit dans la barre du haut, à droite, sur tous les écrans : au
  // téléphone dans la barre marine, au bureau dans une barre à elle — la
  // marque et le compte y sont déjà, dans la barre latérale.
  el().innerHTML = `<div class="shell">${sideBar()}<main class="main">`
    + `<div class="top${voitAlertes() ? '' : ' sans-cloche'}"><span class="brand">WMS Structa</span>`
    + `<span class="top-droite">${clocheHTML()}<span class="who">${esc((USER || '?').slice(0, 2).toUpperCase())}</span></span></div>`
    + `<div class="wrap">${body}</div></main></div>${navBar(active)}`;
  el().querySelectorAll('[data-go]').forEach(b => b.onclick = () => go(b.dataset.go));
  el().querySelectorAll('[data-logout]').forEach(b => b.onclick = logout);
  brancherCloche();
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
    import: renderImport, modeles: renderModeles,
    // Matières premières : l'onglet, le stock (le Stock côté MP), le journal.
    mp: renderMP, stockmp: renderCabines, journalmp: renderJournalMP };
  // « Stock MP » du menu, c'est le Stock, ouvert côté MP. Le côté se choisit ICI,
  // une fois, et non dans le rendu : rejoué par le retour ou le rafraîchissement,
  // l'écran doit garder le côté que l'utilisateur a choisi depuis — il peut
  // avoir touché « Cabines » entre-temps.
  if (name === 'stockmp') { choisirParc('mp'); name = 'cabines'; }
  // Le réglage des seuils est un mode du Stock MP : partir ailleurs le termine.
  if (name !== 'cabines') quitterReglageSeuils(false);
  // Écran inconnu : on retombe sur le Scanner, qui est l'accueil.
  const cle = ecrans[name] ? name : 'scanner';
  // Venir aux emplacements par le menu, c'est repartir de la liste des racks.
  // Le rafraîchissement automatique, lui, ne passe pas par ici : il garde le
  // rack ouvert sous les yeux de qui le regarde.
  if (cle === 'emplacements' || cle === 'rack') RACK_OUVERT = null;
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
const ECRANS_TEMPS_REEL = ['home', 'cabines', 'emplacements', 'rack', 'journal',
                           'mp', 'journalmp'];
//: Une empreinte par famille d'écrans : une palette de verre posée ne doit pas
//: redessiner la liste des cabines — on y perdrait la page chargée et le
//: défilement pour rien. Le plan d'un rack, lui, montre les deux.
let EMPREINTES = {};

/** Ce que l'écran courant regarde dans le pouls : `[famille, empreinte]`. */
function empreinteDeLEcran(p) {
  const cabines = [p.mouvements, p.dernier, p.cabines, p.emplacements];
  // Les alertes aussi : un seuil réglé ailleurs change les pastilles « sous
  // le seuil » de la liste sans qu'aucun mouvement ne s'écrive.
  const mp = [p.mouvements_mp, p.dernier_mp, p.emplacements, p.alertes_empreinte];
  if (ECRAN === 'mp' || ECRAN === 'journalmp' || (ECRAN === 'cabines' && PARC_MODE === 'mp')) {
    return ['mp', mp.join('·')];
  }
  if (ECRAN === 'emplacements' || ECRAN === 'rack') {
    return ['tout', cabines.concat(mp).join('·')];
  }
  return ['cabines', cabines.join('·')];
}

function rafraichissementPossible() {
  if (!token || document.visibilityState !== 'visible') return false;
  if (!ECRANS_TEMPS_REEL.includes(ECRAN)) return false;
  const actif = document.activeElement;
  if (actif && /^(INPUT|SELECT|TEXTAREA)$/.test(actif.tagName)) return false;
  if (document.querySelector('.modal')) return false;   // une fenêtre est ouverte
  if (document.querySelector('.alertes-panneau')) return false;   // on lit les alertes
  if (CAMERA) return false;                             // la caméra tourne
  if (RANGEMENT && RANGEMENT.cabine) return false;      // un rangement est commencé
  return true;
}

async function battement() {
  if (!token) return;
  let p;
  try { p = await api('/pouls/'); } catch (_) { return; }   // hors réseau : on réessaiera
  // La cloche suit le pouls sur TOUS les écrans, saisie en cours comprise :
  // elle ne redessine qu'elle-même.
  suivreAlertes(p);
  const [famille, vue] = empreinteDeLEcran(p);
  if (EMPREINTES[famille] === undefined) { EMPREINTES[famille] = vue; return; }
  if (vue === EMPREINTES[famille] || !rafraichissementPossible()) return;
  EMPREINTES[famille] = vue;
  rejouerEcran();
}

setInterval(battement, POULS_MS);
// Revenir sur l'onglet, c'est le moment où l'écran a le plus de chances d'être
// périmé : on ne fait pas attendre le prochain battement.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') battement();
});

/* --- La cloche : les alertes, en haut à droite -----------------------------
   Ce qui demande un geste sans que personne soit venu le chercher : un code
   passé sous son seuil d'alerte, une palette posée là où son code n'est plus
   accepté. Le pouls en porte le nombre et une empreinte ; la liste n'est
   relue que lorsque l'empreinte bouge — pas toutes les dix secondes.

   La pastille est ROUGE tant qu'une alerte n'a pas été vue sur ce poste, puis
   marine. Une alerte vue reste une alerte — elle ne s'éteint qu'une fois le
   stock refait, le seuil changé ou la palette déplacée —, mais elle n'a plus
   à crier. Une alerte qui se règle puis revient redevient rouge : elle est
   oubliée dès qu'elle disparaît de la liste.

   La cloche n'est montrée qu'à ceux qui peuvent agir sur ce qu'elle dit :
   entrer du stock ou le déplacer, régler un seuil, régler les codes acceptés.
   À un cariste des cabines, une pastille rouge sur le verre n'apprendrait qu'à
   ignorer les pastilles. */
const CLE_ALERTES_VUES = 'wms_alertes_vues';

/** Les alertes déjà vues sur CE poste. Le stockage peut manquer (navigation
    privée, données effacées) : la cloche marche alors sans mémoire. */
function lireAlertesVues() {
  try { return new Set(JSON.parse(localStorage.getItem(CLE_ALERTES_VUES) || '[]')); }
  catch (_) { return new Set(); }
}
function ecrireAlertesVues(vues) {
  try { localStorage.setItem(CLE_ALERTES_VUES, JSON.stringify([...vues])); } catch (_) {}
}

let ALERTES = { total: 0, empreinte: null, groupes: null, vues: lireAlertesVues() };
let ALERTES_EN_LECTURE = false;
//: Une relecture demandée pendant une autre : faite dès que la première rend
//: la main. Ignorée, elle laissait la cloche en retard sur le geste qu'on
//: venait de faire, le temps du battement suivant.
let ALERTES_A_RELIRE = false;
//: Les alertes nouvelles au moment où l'on ouvre la cloche. Ouvrir les marque
//: vues — la pastille se calme —, mais elles restent signalées dans la liste
//: le temps de la lire, relecture comprise.
let NEUVES_A_L_OUVERTURE = new Set();

const voitAlertes = () => peutUnDe(['mp', 'mp_seuils', 'empl_regler']);

/** Les clés d'une réponse `/alertes/`, toutes sortes confondues. */
const clesAlertes = (groupes) => (groupes || []).flatMap(g => (g.items || []).map(x => x.cle));

/** Combien d'alertes n'ont pas encore été vues ici. */
const nonVues = (cles, vues) => cles.filter(c => !vues.has(c)).length;

/** « VITR.445, VITR.470 et 2 autres » — la même phrase que le serveur. */
function listeCodes(codes, combien = 3) {
  const l = (codes || []).slice();
  if (l.length <= 1) return l.join('');
  if (l.length <= combien) return `${l.slice(0, -1).join(', ')} et ${l[l.length - 1]}`;
  const reste = l.length - combien;
  return `${l.slice(0, combien).join(', ')} et ${reste} autre${reste > 1 ? 's' : ''}`;
}

/** La phrase que lit un lecteur d'écran, et l'infobulle. */
function libelleCloche(total, neuves) {
  if (!total) return 'Alertes : aucune';
  return `Alertes : ${total}${neuves ? `, dont ${neuves} nouvelle${neuves > 1 ? 's' : ''}` : ''}`;
}

function clocheHTML() {
  if (!voitAlertes()) return '';
  const n = ALERTES.total || 0;
  const neuves = ALERTES.groupes ? nonVues(clesAlertes(ALERTES.groupes), ALERTES.vues) : 0;
  const titre = libelleCloche(n, neuves);
  return `<button type="button" class="cloche${neuves ? ' neuve' : ''}" id="cloche"
      aria-label="${esc(titre)}" title="${esc(titre)}" aria-haspopup="dialog" aria-expanded="false">${
      icon('cloche', 22)}${n ? `<span class="pastille-n">${n > 99 ? '99+' : n}</span>` : ''}</button>`;
}

function brancherCloche() {
  const b = document.getElementById('cloche');
  if (b) b.onclick = () => (document.querySelector('.alertes-panneau') ? fermerAlertes() : ouvrirAlertes());
}

/** Redessine la cloche, et elle seule : elle change pendant qu'on saisit, et
    ne doit rien prendre à l'écran. `sonner` : une alerte nouvelle vient
    d'arriver — la cloche bat une fois, sans bruit. */
function majCloche(sonner) {
  const b = document.getElementById('cloche');
  if (!b) return;
  const modele = document.createElement('div');
  modele.innerHTML = clocheHTML();
  const neuf = modele.firstElementChild;
  if (!neuf) return;
  b.className = neuf.className;
  b.title = neuf.title;
  b.setAttribute('aria-label', neuf.getAttribute('aria-label'));
  b.innerHTML = neuf.innerHTML;
  if (sonner) {
    b.classList.add('sonne');
    setTimeout(() => b.classList.remove('sonne'), 1300);
  }
}

/** Relit la liste des alertes. Appelée quand le pouls dit qu'elle a changé,
    à l'ouverture de la cloche, et juste après un geste qui peut la changer. */
async function chargerAlertes() {
  if (!token || !voitAlertes()) return;
  if (ALERTES_EN_LECTURE) { ALERTES_A_RELIRE = true; return; }
  ALERTES_EN_LECTURE = true;
  let r;
  try { r = await api('/alertes/'); }
  catch (_) { return; }                       // hors réseau : le pouls redemandera
  finally {
    ALERTES_EN_LECTURE = false;
    if (ALERTES_A_RELIRE) { ALERTES_A_RELIRE = false; setTimeout(chargerAlertes, 0); }
  }
  // Ce qui n'était pas vu avant cette lecture : la cloche ne bat que pour une
  // alerte qui n'y figurait pas — compter ne suffit pas, une alerte peut se
  // régler pendant qu'une autre naît.
  const neuvesAvant = new Set(clesAlertes(ALERTES.groupes).filter(c => !ALERTES.vues.has(c)));
  const cles = clesAlertes(r.groupes);
  // Une alerte réglée sort de la mémoire : si elle revient, elle est nouvelle.
  ALERTES.vues = new Set(cles.filter(c => ALERTES.vues.has(c)));
  ALERTES.total = r.total;
  ALERTES.empreinte = r.empreinte;
  ALERTES.groupes = r.groupes || [];
  const panneau = document.querySelector('.alertes-panneau');
  if (panneau) {
    // Sous les yeux : ce qui arrive pendant qu'on lit est vu aussitôt — et
    // signalé comme nouveau tant que la liste reste ouverte.
    cles.filter(c => !ALERTES.vues.has(c)).forEach(c => NEUVES_A_L_OUVERTURE.add(c));
    remplirAlertes(panneau);
    cles.forEach(c => ALERTES.vues.add(c));
  }
  ecrireAlertesVues(ALERTES.vues);
  majCloche(cles.some(c => !ALERTES.vues.has(c) && !neuvesAvant.has(c)));
}

/** Ce que le pouls apprend à la cloche : relire seulement si l'ensemble a bougé. */
function suivreAlertes(p) {
  if (!p || !voitAlertes()) return;
  if (ALERTES.groupes === null || p.alertes_empreinte !== ALERTES.empreinte) chargerAlertes();
}

function ouvrirAlertes() {
  fermerAlertes();
  const panneau = document.createElement('div');
  panneau.className = 'alertes-panneau';
  panneau.setAttribute('role', 'dialog');
  panneau.setAttribute('aria-label', 'Alertes');
  el().appendChild(panneau);
  // Les nouvelles le restent à l'écran le temps de cette lecture, même une
  // fois marquées vues — et même quand la relecture redessine la liste.
  NEUVES_A_L_OUVERTURE = new Set(clesAlertes(ALERTES.groupes).filter(c => !ALERTES.vues.has(c)));
  remplirAlertes(panneau);
  clesAlertes(ALERTES.groupes).forEach(c => ALERTES.vues.add(c));
  ecrireAlertesVues(ALERTES.vues);
  majCloche(false);
  const b = document.getElementById('cloche');
  if (b) b.setAttribute('aria-expanded', 'true');
  setTimeout(() => document.addEventListener('click', clicHorsAlertes), 0);
  document.addEventListener('keydown', echapAlertes);
  // Ce qui est montré tout de suite est la dernière lecture ; on relit dans la
  // foulée : un « réservé à » ou un total a pu changer sans que l'ensemble
  // des alertes bouge.
  chargerAlertes();
}

function fermerAlertes() {
  const panneau = document.querySelector('.alertes-panneau');
  if (panneau) panneau.remove();
  NEUVES_A_L_OUVERTURE = new Set();
  document.removeEventListener('click', clicHorsAlertes);
  document.removeEventListener('keydown', echapAlertes);
  const b = document.getElementById('cloche');
  if (b) b.setAttribute('aria-expanded', 'false');
}

function clicHorsAlertes(ev) {
  if (!ev.target.closest('.alertes-panneau, #cloche')) fermerAlertes();
}

function echapAlertes(ev) {
  if (ev.key === 'Escape') fermerAlertes();
}

/** Une alerte, et le geste qu'elle demande : ouvrir le code, ou l'emplacement. */
function alerteHTML(type, x) {
  const neuve = (!ALERTES.vues.has(x.cle) || NEUVES_A_L_OUVERTURE.has(x.cle)) ? ' neuve' : '';
  if (type === 'seuil') {
    return `<button type="button" class="alerte-ligne${neuve}" data-article="${x.article}">
      <span class="alerte-t"><span class="code-mp">${esc(x.code)}</span>
        <span class="etat ${x.en_stock ? 'att' : 'crit'}">${x.en_stock} / ${x.seuil}</span></span>
      <span class="alerte-d">${x.en_stock ? `Plus que ${esc(quantiteMP(x.en_stock, x.famille))}`
        : 'Plus aucun en stock'} — seuil d’alerte ${x.seuil}</span></button>`;
  }
  return `<button type="button" class="alerte-ligne${neuve}" data-emp="${x.emplacement}" data-code="${esc(x.code_emplacement)}">
      <span class="alerte-t"><span class="code-mp">${esc(x.code)}</span>
        <span class="etat att">${esc(x.position)}</span></span>
      <span class="alerte-d">${esc(quantiteMP(x.quantite, x.famille))} posé${x.quantite > 1 ? 's' : ''} sur
        ${esc(x.code_emplacement)}, réservé à ${esc(listeCodes(x.acceptes))} : à changer d’emplacement.</span></button>`;
}

function remplirAlertes(panneau) {
  const groupes = ALERTES.groupes;
  const corps = groupes === null ? '<div class="empty">Chargement…</div>'
    : !groupes.length ? `<div class="empty">Aucune alerte : chaque code est au-dessus de son seuil,
        et chaque palette est là où elle est acceptée.</div>`
    : groupes.map(g => `<div class="sec">${esc(g.titre)} · ${g.items.length}</div>
        <div class="alertes-liste">${g.items.map(x => alerteHTML(g.type, x)).join('')}</div>
        ${g.type === 'seuil' ? '<button type="button" class="lien" data-stock>Voir ces codes dans le stock</button>' : ''}`).join('');
  panneau.innerHTML = `<div class="alertes-tete"><span>Alertes</span>
      <button type="button" class="modal-x" data-fermer aria-label="Fermer">${icon('close', 20)}</button></div>
    <div class="alertes-corps">${corps}</div>`;
  panneau.querySelector('[data-fermer]').onclick = fermerAlertes;
  panneau.querySelectorAll('[data-article]').forEach(n => n.onclick = () => {
    fermerAlertes();
    ouvrirFicheArticleMP({ id: n.dataset.article });
  });
  panneau.querySelectorAll('[data-emp]').forEach(n => n.onclick = () => {
    fermerAlertes();
    ouvrirEmplacementMP({ id: n.dataset.emp, code: n.dataset.code });
  });
  const stock = panneau.querySelector('[data-stock]');
  if (stock) stock.onclick = () => { fermerAlertes(); ouvrirStockMP({ sous_seuil: '1' }); };
}


const tile = (ic, title, sub, goName) =>
  `<div class="tile ${goName?'':'dim'}" ${goName?`data-go="${goName}"`:''}><span class="ic">${icon(ic,26)}</span><span class="t">${esc(title)}</span><span class="s">${esc(sub)}</span></div>`;

//: Nombre de cabines retenues dans « Consultées récemment ».
const RECENTS_MAX = 8;

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
  // Ni « Cabines » ni « Stock » : les deux sont des onglets de la barre du bas,
  // visible en permanence à trois centimètres de ces vignettes. Une vignette
  // qui double un onglet fait chercher lequel des deux est le bon.
  v.push(tile('box', 'Emplacements', peut('empl_creer') ? 'occupation, ajout et réglages'
    : (gereEmplacements() ? 'occupation et réglages' : 'occupation des racks'), 'emplacements'));
  v.push(tile('history', 'Journal', 'tous les mouvements', 'journal'));
  if (peut('production')) v.push(tile('clip', 'Fichier de production',
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
    /* Le serveur laisse tout compte LIRE le fichier de production — l'écran
       d'entrée en a besoin pour se pré-remplir. Ce n'est donc pas une question
       de droit mais d'utilité : un cariste range des cabines, il n'analyse pas
       le plan de production, et ce tableau lui ferait dérouler son écran pour
       rien. D'où le bloc réservé ICI, à l'affichage, à qui importe le fichier. */
    const semaines = peut('production')
      ? await api('/cabines-attendues/par_semaine/').catch(() => null)
      : null;
    layout(`<h2 class="title">Tableau de bord</h2>
      ${rappelEnCours()}
      <div class="kpis">
        <div class="kpi clic" data-cab="{}"><div class="l">Cabines en stock</div><div class="v">${actives}</div></div>
        <div class="kpi clic ${quarantaine ? 'warn' : ''}" data-cab='{"statut":"quarantaine"}'><div class="l">En quarantaine</div><div class="v">${quarantaine}</div></div>
        <div class="kpi clic" data-cab='{"sans_chantier":"1"}'><div class="l">Sans chantier</div><div class="v">${sansChantier}</div></div>
        <div class="kpi clic" data-cab='{"rangee":"0"}'><div class="l">Non rangées</div><div class="v">${nonRangees}</div></div>
      </div>
      ${blocSemaines(semaines)}
      <div class="sec">Aller à</div>
      <div class="tiles">${vignettesAccueil()}</div>`, 'home');
    brancherRappelEnCours();
    brancherSemaines(semaines);
    el().querySelectorAll('[data-cab]').forEach(n => n.onclick = () => {
      try { ouvrirCabines(JSON.parse(n.dataset.cab)); } catch (_) { ouvrirCabines(); }
    });
  } catch (e) { toast(e.message, 'err'); }
}

/* --- Annoncées / arrivées, semaine par semaine ------------------------------
   « La production annoncée en S37 est-elle arrivée ? » Le fichier de production
   couvre 42 semaines : les montrer toutes d'emblée noie le regard, n'en montrer
   que trois cache le retard qu'on cherche.

   L'écran ouvre donc sur les semaines UTILES — celles où quelque chose est
   arrivé, plus la semaine en cours et les suivantes — et un bouton déplie le
   reste. Le choix est mémorisé le temps de la session, pas au-delà : au poste,
   on veut l'affichage court par défaut. */
let SEMAINES_TOUTES = false;

/** La semaine ISO d'aujourd'hui, au format du classeur (« S37 »).

    Calculée, pas demandée au serveur : c'est la même date des deux côtés, et un
    aller-retour de plus pour un repère d'affichage n'a pas de sens. L'algorithme
    est celui de la norme ISO 8601 — le jeudi de la semaine décide de son numéro,
    ce qui évite de se tromper d'une semaine au tournant de janvier. */
function semaineISO(quand = new Date()) {
  const d = new Date(Date.UTC(quand.getFullYear(), quand.getMonth(), quand.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const janvier = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const n = Math.ceil(((d - janvier) / 86400000 + 1) / 7);
  return 'S' + String(n).padStart(2, '0');
}

function blocSemaines(d) {
  if (!d || !(d.semaines || []).length) return '';
  const ici = semaineISO();
  /* Ce qui « bouge » : une arrivée, ou une semaine qu'on n'a pas encore passée.
     Une semaine passée sans aucune arrivée n'est pas une information utile au
     quotidien — mais elle le devient quand on analyse, d'où le bouton. */
  const utile = (l) => l.arrivees > 0 || (l.semaine && l.semaine >= ici);
  const vues = SEMAINES_TOUTES ? d.semaines : d.semaines.filter(utile);
  const cachees = d.semaines.length - vues.length;

  const ligne = (l) => {
    const part = l.annoncees ? Math.round((l.arrivees / l.annoncees) * 100) : 0;
    const nom = l.semaine || 'Sans semaine';
    return `<tr class="${l.semaine === ici ? 'ici' : ''}">
      <td class="sem">${esc(nom)}${l.semaine === ici ? ' <span class="pill">en cours</span>' : ''}</td>
      <td class="n">${l.annoncees}</td>
      <td class="n">${l.arrivees}</td>
      <td class="n ${l.reste ? 'du' : 'ok'}">${l.reste || '—'}</td>
      <td class="jauge"><span style="width:${part}%"></span><i>${part}%</i></td>
    </tr>`;
  };

  return `<div class="sec">Annoncées / arrivées, par semaine de production</div>
    <div class="card semaines">
      <div class="meta" style="margin:-2px 0 10px">« Arrivées » compte les cabines
        entrées en stock un jour, y compris celles déjà parties en chantier : la
        question est de savoir si la production est bien arrivée.</div>
      <div class="specs"><table><thead><tr>
        <th>Semaine</th><th class="n">Annoncées</th><th class="n">Arrivées</th>
        <th class="n">Reste</th><th>Arrivé</th>
      </tr></thead><tbody>${vues.map(ligne).join('')}
      <tr class="total"><td class="sem">Total</td><td class="n">${d.annoncees}</td>
        <td class="n">${d.arrivees}</td>
        <td class="n ${d.annoncees - d.arrivees ? 'du' : 'ok'}">${d.annoncees - d.arrivees || '—'}</td>
        <td></td></tr>
      </tbody></table></div>
      ${cachees || SEMAINES_TOUTES ? `<button class="btn ghost" id="tbSem">${
        SEMAINES_TOUTES ? 'Ne montrer que les semaines en cours et arrivées'
                        : `Voir les ${cachees} autres semaines`}</button>` : ''}
      ${d.hors_fichier ? `<div class="meta" style="margin-top:8px"><b>${d.hors_fichier}</b>
        cabine${d.hors_fichier === 1 ? '' : 's'} en stock n'appartient à aucune semaine :
        elle a été enregistrée hors fichier de production. Le motif est au journal.</div>` : ''}
    </div>`;
}

function brancherSemaines(d) {
  const b = $('#tbSem');
  if (!b) return;
  b.onclick = () => {
    SEMAINES_TOUTES = !SEMAINES_TOUTES;
    const zone = b.closest('.card');
    /* On redessine le bloc seul, pas l'écran : recharger le tableau de bord
       relancerait cinq requêtes pour déplier un tableau déjà en mémoire. */
    zone.outerHTML = blocSemaines(d);
    brancherSemaines(d);
  };
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

/* --- Le code, aussi large que le QR -------------------------------------------
   Le code était écrit en 15 pt : « Y550 » tenait sur 12 mm au-dessus d'un carré
   de 40. C'est pourtant lui qu'on cherche des yeux en remontant l'allée, et lui
   qu'on recopie quand le scan ne prend pas.

   Il prend maintenant exactement la largeur du QR : au-dessus d'un QR de 40 mm,
   « Y550 » s'écrit sur 40 mm de large et 12 mm de haut. Le corps se déduit de la
   longueur du code — un code long s'écrit moins haut, jamais plus large — et le
   SVG (`textLength`) ajuste la largeur au dixième de millimètre, quelle que soit
   la police réellement présente sur le poste qui imprime.                      */

// Chasse des capitales et des chiffres en Arial gras, en millièmes de corps.
const CHASSE_GRAS = { A: 722, B: 722, C: 722, D: 722, E: 667, F: 611, G: 778, H: 722,
  I: 278, J: 556, K: 722, L: 611, M: 833, N: 722, O: 778, P: 667, Q: 778, R: 722,
  S: 667, T: 611, U: 722, V: 667, W: 944, X: 667, Y: 667, Z: 611,
  '-': 333, '.': 278, '/': 278, ' ': 278, '_': 556 };
const HAUTEUR_CODE = 0.86;     // hauteur du bloc, en corps : la capitale et un filet dessous

/** Corps (mm) qui donne au code la largeur `cote`. Plafonné à la moitié du côté :
 *  un code de deux caractères ne doit pas devenir plus haut que le QR lui-même. */
function corpsDuCode(code, cote) {
  const chasse = [...String(code)].reduce((s, c) =>
    s + (/\d/.test(c) ? 556 : (CHASSE_GRAS[c.toUpperCase()] || 722)), 0) / 1000;
  return Math.min(cote / (chasse || 1), cote / 2);
}

/** Le code en SVG. `ajuste` : le texte est étiré ou resserré à la largeur exacte. */
function codeEnSvg(code, largeur, corps, ajuste) {
  const r = (x) => Math.round(x * 100) / 100;
  const h = r(corps * HAUTEUR_CODE), texte = esc(code);
  const position = ajuste
    ? `x="0" textLength="${r(largeur)}" lengthAdjust="spacingAndGlyphs"`
    : `x="${r(largeur / 2)}" text-anchor="middle"`;
  return `<svg class="code" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${r(largeur)} ${h}"
      width="${r(largeur)}mm" height="${h}mm" role="img" aria-label="${texte}"><text
      ${position} y="${r(corps * 0.76)}" font-size="${r(corps)}">${texte}</text></svg>`;
}

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
  const multiple = bandes.length > 1;
  // 297 mm − 2 × 8 mm de marge, moins la marge interne de la bande et la ligne
  // de titre qu'elle porte quand il y en a plusieurs.
  const utileMM = 297 - 16 - 12 - (multiple ? 5 : 0);
  const parEtiquette = utileMM / parBande;
  // Code → QR : 3 mm de blanc. Un QR se repère à ses trois carrés d'angle, cernés
  // de blanc ; un texte gras collé au-dessus les ferait mal détecter.
  const ECART = 3, AIR = 3;                   // puis 3 mm d'une étiquette à l'autre
  // Hauteur du code pour un QR de 1 mm : il en prend la largeur, sa hauteur suit
  // donc sa longueur. Le plus haut de la planche fixe l'encombrement.
  const rapport = Math.max(...codes.map(c => corpsDuCode(c, 1) * HAUTEUR_CODE));
  // La taille choisie est un maximum : au-delà de quatre ou cinq niveaux, il faut
  // bien réduire pour que la bande tienne encore sur une seule page.
  const mm = pleineHauteur
    ? Math.max(20, Math.min(Number(TAILLE_QR),
                            Math.floor((parEtiquette - ECART - AIR) / (1 + rapport))))
    : Number(TAILLE_QR);
  // Passé six ou sept niveaux, même un QR de 20 mm ne laisse plus la place d'un
  // code aussi large que lui : c'est alors le code qui rapetisse. Jamais le QR
  // sous 20 mm — en dessous, un téléphone ne le lit plus à bout de bras.
  const hauteurMax = pleineHauteur ? Math.max(4, parEtiquette - ECART - AIR - mm) : Infinity;
  const codeDe = (c) => {
    const plein = corpsDuCode(c, mm);
    const corps = Math.min(plein, hauteurMax / HAUTEUR_CODE);
    return codeEnSvg(c, mm, corps, corps >= plein * 0.98);
  };
  const pixels = Math.round(mm * 8);          // ≈ 200 dpi
  if (codes.length > 4) toast(`Préparation de ${codes.length} étiquettes…`);

  const images = {};
  for (const code of codes) images[code] = await qrEnImage('LOC:' + code, pixels);
  const rate = codes.find(c => !images[c]);
  if (rate) { toast('Impossible de générer le QR de ' + rate, 'err'); return; }

  const fenetre = window.open('', '_blank');
  if (!fenetre) { toast('Autorise les fenêtres pop-up pour imprimer.', 'err'); return; }

  // Les étiquettes sont dans leur propre bloc : sinon le titre de la bande entre
  // dans la répartition et creuse un écart plus large en haut qu'entre les QR.
  const corps = bandes.map(b => `<div class="bande${b.codes.length > 1 ? ' pleine' : ''}">
      ${multiple && b.titre ? `<div class="bande-titre">${esc(b.titre)}</div>` : ''}
      <div class="etiquettes">${b.codes.map(c => `<div class="etiquette">
          ${codeDe(c)}
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
                 color: #6b7780; text-align: center; margin-bottom: 2mm }
  .etiquette { text-align: center }
  /* Le code au-dessus du QR, de sa largeur exacte : c'est lui qu'on lit de loin,
     et lui qu'on recopie quand le scan ne prend pas. */
  .code { display: block; margin: 0 auto ${ECART}mm; overflow: visible }
  .code text { font-family: Arial, 'Liberation Sans', 'Helvetica Neue', Helvetica, Roboto, sans-serif;
               font-weight: 700; fill: #000 }
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

function renderEtiquettes() {
  // Les cabines ne portent pas de QR code : seules les étiquettes d'emplacement
  // s'impriment — ce sont elles qu'on scanne pour ranger une cabine.
  layout(`<h2 class="title">Étiquettes QR</h2><div id="zone"></div>`, 'more');
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
        <div class="aide">Bandes de ${LARGEUR_BANDE_MM} mm de large, QR empilés à la verticale. Au-dessus de chacun, le code d'emplacement en gros caractères, aussi large que le QR. Deux bandes tiennent côte à côte sur une A4.</div>
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
  empMode();
}

/* ============================ CABINES =======================================
   Écrans du suivi de cabines : emplacement scanné (ranger, envoyer), fiche
   cabine avec historique, parc et archives des cabines envoyées, journal.     */

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
      ${peut('cab_ranger') ? '<button class="btn orange" data-entree>Aller à l’entrée avec ce numéro</button>' : ''}
      <button class="btn ghost" data-refaire>Une autre cabine</button>
    </div>`;
  const aller = zone.querySelector('[data-entree]');
  if (aller) aller.onclick = () => { ENTREE_NUMERO = num; go('entree'); };
  const refaire = zone.querySelector('[data-refaire]');
  if (refaire) refaire.onclick = options.refaire || (() => go(ECRAN));
}

/* --- Récents de cabines ------------------------------------------------------
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
  // La forme vient du serveur : le modèle est le seul à décider ce qu'est un
  // chantier valable. Le repli n'a lieu que si le référentiel n'a pas répondu.
  const forme = REFS_CABINE.aide_chantier
    || 'Six chiffres, éventuellement suivis du lot : 251213 ou 251213-1.';
  return `${forme} Obligatoire, sauf pour les types : ${liste}. `
       + 'Dans tous les cas, il est exigé pour sortir la cabine de l’entrepôt.';
}

/* Le chantier se saisit en DEUX champs et non en un. « 251213-1 » tapé dans un
   seul champ oblige à quitter le pavé numérique pour aller chercher le tiret —
   sur un téléphone, avec des gants — et laisse passer « 251213 -1 », « 251213/1 »
   ou « 251213_1 », que le serveur refuse ensuite sans que l'opérateur voie où est
   la faute. Deux champs numériques ne peuvent produire qu'une forme valide.
   Cette saisie n'apparaît QUE lorsque le fichier de production ne donne pas de
   chantier pour cette cabine : partout ailleurs, il vient du fichier et ne se
   retape pas. */
const CHAMPS_CHANTIER = `<div class="grille-chantier">
  <div><label for="eChantier">N° de chantier *</label>
    <input id="eChantier" placeholder="Ex. 251213" inputmode="numeric"
           autocomplete="off" maxlength="9"></div>
  <div><label for="eLot">Lot</label>
    <input id="eLot" placeholder="aucun" inputmode="numeric"
           autocomplete="off" maxlength="2"></div>
</div>`;

/* Le champ de chantier des écrans qui en AFFECTENT un à une cabine déjà créée
   (sortie, envoi, correction de fiche). Quatre écrans l'écrivaient chacun à sa
   façon, tous en « 6 chiffres » avec `inputmode="numeric"` : le pavé numérique
   d'iOS n'a pas de tiret, un chantier à lot était donc intypable sur la moitié
   du parc. Un seul champ, un seul libellé, une seule aide — celle du serveur. */
const champChantier = (id, valeur) =>
  `<label for="${id}">N° de chantier</label>
   <input id="${id}" value="${esc(valeur || '')}" inputmode="text" autocomplete="off"
          maxlength="${REFS_CABINE.taille_chantier || 9}"
          placeholder="Ex. 251213 ou 251213-1">
   <div class="aide">${esc(aideChantier())}</div>`;

/** La forme d'un chantier, telle que le modèle la définit. Repli local
    seulement si le référentiel n'a pas répondu. */
function motifChantier() {
  const REPLI = /^\d{6}(-[1-9]\d?)?$/;
  const brut = REFS_CABINE.motif_chantier;
  // `new RegExp(undefined)` ne lève pas : il rend /(?:)/, qui accepte TOUT. Un
  // référentiel muet aurait donc désarmé le contrôle en silence au lieu de
  // retomber sur le repli.
  if (typeof brut !== 'string' || !brut) return REPLI;
  try { return new RegExp(brut); } catch (_) { return REPLI; }
}

/** Recompose « 251213-1 » depuis les deux champs. Chaîne vide si rien n'est saisi.

    Le champ de gauche accepte aussi un chantier collé d'un bloc : « 251213-1 »,
    « 251213 1 », « 251213/1 » disent la même chose et sont reconnus. La première
    version ne gardait que les chiffres et coupait à six : un numéro collé depuis
    un courriel perdait son lot sans un mot, et la cabine partait sur le chantier
    voisin. Ce qui n'est ni l'une ni l'autre forme ressort tel quel — c'est le
    contrôle qui le refuse, en le citant, plutôt qu'une troncature silencieuse. */
function lireChantierSaisi() {
  const brut = String((($('#eChantier') || {}).value) || '').trim();
  const lot = String((($('#eLot') || {}).value) || '').replace(/\D/g, '').replace(/^0+/, '');
  if (!brut) return '';
  const colle = brut.match(/^(\d{6})\D+(\d{1,2})$/);
  if (colle) return colle[1] + '-' + colle[2].replace(/^0+/, '');
  return lot ? brut + '-' + lot : brut;
}

/** Vrai si le type choisi dispense de chantier. Lu au moment de valider, pas au
    dessin : l'opérateur change parfois le type après avoir vu le formulaire. */
const typeDispenseDeChantier = () =>
  TYPES_SANS_CHANTIER.includes((($('#e_type') || {}).value) || '');

/** Le garde-fou de l'écran : refuse un chantier absent, ou mal formé.

    Le serveur porte les deux mêmes règles — c'est lui qui tranche — mais un
    aller-retour pour apprendre qu'un champ obligatoire est vide fait perdre le
    temps que ce formulaire est censé gagner. La forme est contrôlée même sur une
    express, qui n'a pas besoin de chantier mais n'a pas le droit d'en porter un
    faux. */
function chantierRefuse(chantier) {
  const champ = $('#eChantier') || $('#e_chantier');
  const stop = (message) => { toast(message, 'err'); if (champ) champ.focus(); return true; };
  if (chantier && !motifChantier().test(chantier)) {
    return stop(`« ${chantier} » n’est pas un n° de chantier. ${aideChantier()}`);
  }
  if (!chantier && !typeDispenseDeChantier()) {
    return stop('Le n° de chantier est obligatoire pour ce type de cabine.');
  }
  return false;
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
  <div class="meta">${c.etape_libelle ? esc(c.etape_libelle) + ' · ' : ''}${c.position
    ? esc((c.zone_nom ? c.zone_nom + ' / ' : '') + ouEstLaCabine(c)) : 'non rangée'}</div>
  ${(c.quarantaine && c.quarantaine.active && c.quarantaine.motif)
    /* Le motif sur la ligne : sans lui, « En quarantaine : 3 » donne trois
       numéros et il faut ouvrir trois fiches pour savoir ce qui bloque. */
    ? `<div class="motif-q">${esc(c.quarantaine.motif)}</div>` : ''}
</div>`;

// --- Emplacement scanné : les deux options demandées, ranger et sortir -------
/** Le conteneur `#zone` de l'écran courant, posé si l'écran n'en a pas.

    Les fiches — celle d'une cabine, celle d'un emplacement — s'écrivent dans le
    `#zone` de l'écran qui les appelle. Le Scanner et l'écran des gestes n'en
    posent pas : ils écrivent leurs cartes directement. Ces fiches rendaient donc
    la main en silence, sans message ni erreur en console. Deux fois le même
    oubli, et deux fois le même symptôme sur le terrain : scanner le QR d'un
    emplacement n'affichait plus ce qu'il contient, et « Voir sa fiche » ne
    faisait rien du tout. D'où ce passage obligé, contrôlé par
    `verifier_interface.js` : la troisième fois n'arrivera pas.

    L'onglet reste « Cabines » : une fiche ouverte depuis un scan est une étape
    du parcours, pas une destination du menu. */
function zoneEcran(options = {}) {
  // `neuf` : l'écran est reposé même s'il existe déjà un `#zone`. C'est le cas
  // des fiches, qui sont des écrans entiers. Écrite dans le `#zone` du Stock, la
  // fiche d'une cabine s'affichait SOUS le titre, la recherche, les cinq
  // pastilles, le panneau de filtres et le bouton d'export — il fallait
  // dérouler tout cela pour la voir, et toucher une cabine dans la liste
  // semblait ne rien faire du tout.
  if (options.neuf || !$('#zone')) layout('<div id="zone"></div>', ongletCourant());
  return $('#zone');
}

/** L'onglet à garder allumé quand un écran se pose de lui-même : celui d'où
    l'on vient, s'il fait partie de la barre du bas. Une fiche ouverte depuis le
    Stock laisse « Stock » allumé ; ouverte depuis un scan, « Cabines ». */
const ongletCourant = () =>
  (ONGLETS_COMMUNS.some(([cle]) => cle === ECRAN) ? ECRAN : 'scanner');

async function montrerEmplacement(emp, opts = {}) {
  const zone = zoneEcran();
  // Toutes les re-lectures de l'écran repassent par ici : sans cela, la première
  // action (ranger, sortir) perdait les options et faisait réapparaître le bouton
  // de réglage au milieu de la fiche, qui en porte déjà un.
  const redessiner = () => montrerEmplacement(emp, opts);
  if (!zone) return;
  // Un emplacement de matières premières ne porte pas de cabine : il a son
  // propre écran, avec ses trois places. Toutes les portes y mènent — scan,
  // fiche d'emplacement, recherche —, sans que chacune ait à le savoir.
  if (emp.est_mp) return montrerEmplacementMP(emp, opts);
  zone.innerHTML = '<div class="empty">Chargement…</div>';
  await refsCabine();   // sinon les places s'affichent « G — G » au lieu de « G — Gauche »
  try {
    // `?pour_cabine=` : sans lui, le serveur répond pour une cabine ordinaire
    // et l'écran proposerait « Gauche » à un grand modèle.
    const d = await api(`/emplacements/${emp.id}/places/`
      + (CABINE_A_RANGER ? '?pour_cabine=' + CABINE_A_RANGER.id : ''));
    if (d.est_mp) return montrerEmplacementMP(emp, opts);
    // Deux modes : deux places nommées, ou capacité illimitée sans place.
    const occupants = d.illimite
      ? (d.cabines || []).map(c => ({ code: '—', cabine: c }))
      : d.places.filter(p => !p.libre);
    /* Une cabine attend une place : le choix tactile qui s'affiche plus bas dit
       déjà, case par case, ce qui est libre et QUI occupe le reste. Garder aussi
       la liste du haut donnait deux fois les trois mêmes lignes sur un écran de
       téléphone — « G — Gauche libre » au-dessus de « G / Gauche / libre » —
       et repoussait le geste hors de l'écran. Hors de ce cas, la liste reste :
       c'est elle qu'on vient lire quand on scanne un emplacement pour savoir ce
       qu'elle contient. */
    // Ranger et sortir ont chacun leur case : un compte peut avoir l'une sans
    // l'autre, et l'écran ne propose que la sienne.
    const ranger = peut('cab_ranger'), sortir = peut('cab_envoyer');
    const attendUnePlace = Boolean(CABINE_A_RANGER) && ranger
      && !d.complet && !d.illimite
      && !(d.cabines || []).some(x => x.id === CABINE_A_RANGER.id);
    /* Une cabine qui prend l’emplacement entier n'apparaît QU'UNE FOIS. La version
       précédente rendait les deux places l'une sous l'autre avec le même numéro :
       on lisait deux cabines — ou une donnée fausse — et rien ne disait pourquoi
       la seconde place n'était plus choisissable. */
    const entiere = d.illimite ? null
      : (d.places || []).find(p => p.occupation && p.occupation.place === 'T');
    const contenu = d.illimite
      ? ((d.cabines || []).length
          ? d.cabines.map(c => ligneOccupant(c, { titre: esc(c.numero), ici: d.code })).join('')
          : '<div class="empty">Aucune cabine ici.</div>')
      : entiere
        ? ligneOccupant(entiere.cabine, {
            titre: 'Tout l’emplacement', etat: 'occupé', ici: d.code,
            pourquoi: 'Un grand modèle occupe les deux places : aucune autre'
                    + ' cabine ne peut être posée ici.',
          })
        : d.places.map(p => (p.libre
            ? `<div class="item" style="cursor:default"><div class="r">${esc(p.code)} — ${
                esc(p.libelle)} <span class="etat ok">libre</span></div></div>`
            : ligneOccupant(p.cabine, {
                titre: `${esc(p.code)} — ${esc(p.libelle)}`, ici: d.code }))).join('');
    zone.innerHTML = `
      <div class="card"><div class="muted small">${esc(d.zone || 'Sans zone')}</div>
        <div class="r" style="font-size:17px;font-weight:700">Emplacement ${esc(d.code)}</div>
        <div class="meta" style="margin-top:3px">${esc(d.mode_libelle)}${d.illimite ? ` · ${d.nb_cabines} cabine${d.nb_cabines === 1 ? '' : 's'}` : ''}</div>
        ${attendUnePlace ? '' : `<div class="list" style="margin-top:10px">${contenu}</div>`}
        ${(ranger || sortir) ? `
          ${(ranger && !d.complet) ? `<button class="btn orange btn-fiche" id="eFiche">${icon('fiche', 20)} Scanner la fiche de la cabine</button>
          <div class="meta" style="margin-top:5px;text-align:center">Photographie le tableau collé sur la cabine : le n° est lu tout seul.</div>` : ''}
          <div class="row" style="margin-top:12px">
          ${ranger ? `<button class="btn ghost" id="eRanger" ${d.complet ? 'disabled style="opacity:.45"' : ''}>Saisir le n° à la main</button>` : ''}
          ${sortir ? `<button class="btn ghost" id="eSortir" ${occupants.length ? '' : 'disabled style="opacity:.45"'}>Sortir une cabine</button>` : ''}
        </div>` : ''}
        ${d.complet ? `<div class="banner" style="margin:12px 0 0">${
          CABINE_A_RANGER ? 'Plus de place ici pour cette cabine' : 'Cet emplacement est plein'
          } : impossible de ranger ici.</div>` : ''}
        <div id="eAct"></div></div>
      ${(gereEmplacements() && !opts.sansReglages) ? `<button class="btn ghost" id="eReglage" style="margin-top:12px">${icon('cog', 17)} ${
        peut('empl_creer') ? 'Régler / supprimer cet emplacement' : 'Régler cet emplacement'}</button>` : ''}
      ${opts.pied ? piedGestes({ suite: 'Scanner autre chose' }) : ''}`;

    // Le pied est posé par `layout()` pour les écrans, pas ici : ce bloc est
    // écrit dans un `#zone`, et ses `data-go` n'ont donc pas été branchés.
    if (opts.pied) {
      zone.querySelectorAll('[data-go]').forEach(b => b.onclick = () => go(b.dataset.go));
    }

    // Un seul formulaire de réglage dans toute l'application : celui de la fiche.
    // Il y en avait trois, avec des champs différents — on ne savait plus lequel
    // faisait foi, et aucun ne permettait de supprimer.
    if (gereEmplacements() && !opts.sansReglages) {
      $('#eReglage').onclick = () => ficheEmplacement(emp, opts.retour || renderEmplacements);
    }

    if (!(ranger || sortir)) return;

    // Parcours « fiche cabine d'abord » : une cabine attend une place, on la range
    // sans la rechercher. Le scan de l'emplacement suffit.
    if (CABINE_A_RANGER && ranger) {
      const c = CABINE_A_RANGER;
      const dejaLa = (d.cabines || []).some(x => x.id === c.id);
      if (!dejaLa && !d.complet) {
        $('#eAct').innerHTML = `<div class="banner" style="margin-top:12px">Cabine ${esc(c.numero)} en attente de rangement.</div>
          ${blocPlaces(d)}
          <div class="row" style="margin-top:10px">
            <button class="btn orange" id="wOk" style="margin-top:0">Ranger ici</button>
            <button class="btn ghost" id="wNon" style="margin-top:0">Annuler</button>
          </div>`;
        const placeW = choixPlace(d, $('#wOk'));
        $('#wNon').onclick = () => { CABINE_A_RANGER = null; redessiner(); };
        $('#wOk').onclick = async () => {
          const choix = placeW();
          if (!sansPlaceAChoisir(d) && !choix) { toast('Touche la place où tu poses la cabine.', 'err'); return; }
          try {
            const corps = { emplacement: emp.id };
            if (choix) corps.place = choix;
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

    if ($('#eRanger')) $('#eRanger').onclick = () => {
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
            $('#cform').innerHTML = blocPlaces(d)
              + `<button class="btn orange" id="cok">Ranger ${esc(cab.numero)}</button>`;
            const placeC = choixPlace(d, $('#cok'));
            $('#cok').onclick = async () => {
              const choix = placeC();
              if (!sansPlaceAChoisir(d) && !choix) { toast('Touche la place où tu poses la cabine.', 'err'); return; }
              try {
                const corps = { emplacement: emp.id };
                if (choix) corps.place = choix;
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

    if ($('#eSortir')) $('#eSortir').onclick = () => {
      $('#eAct').innerHTML = `<div class="sec">Quelle cabine sortir ?</div>
        <div class="banner">La sortie est <b>définitive</b> : la cabine quitte
          l'entrepôt et rejoint les archives.</div>
        <div class="list">${occupants.map(p => `<div class="item" data-cab="${p.cabine.id}">
          <div class="r">${d.illimite ? '' : p.code + ' · '}${esc(p.cabine.numero)} ${badgeStatut(p.cabine)}</div>
          <div class="d">Chantier ${p.cabine.chantier ? esc(p.cabine.chantier) : '<em>à affecter</em>'}</div></div>`).join('')}</div>
        <div id="sform"></div>`;
      $('#eAct').querySelectorAll('[data-cab]').forEach(it => it.onclick = async () => {
        const cab = occupants.find(p => String(p.cabine.id) === it.dataset.cab).cabine;
        if (!cab.chantier) {
          // Règle métier : pas de sortie sans chantier, quel que soit le type.
          $('#sform').innerHTML = `<div class="banner">Cette cabine n’a pas de chantier : affecte-le avant de l’envoyer.</div>
            ${champChantier('scha', '')}
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

//: Le nom des places en mots, pas en lettres. « G » se lit sur une étiquette de
//: rack ; dans une phrase, « gauche » se comprend sans traduire.
//: Le nom des places en mots, pas en lettres. « G » se lit sur une étiquette de
//: rack ; dans une phrase, « gauche » se comprend sans traduire. « T » n'y est
//: pas : un emplacement pris en entier s'écrit par son seul code — « AC550 »,
//: et non « AC550·T », qui se lisait comme un code de rack inexistant et qu'on
//: cherchait sur les étiquettes. L'étendue se dit sur la fiche de
//: l'emplacement, là où elle a un sens.
const NOM_PLACE = { G: 'gauche', D: 'droite' };

/** Les codes des emplacements occupés par une cabine, sans doublon, dans l'ordre. */
const codesEmplacements = (c) => emplacementsDe(c)
  .map(o => o.emplacement_code)
  .filter((code, i, tout) => code && tout.indexOf(code) === i);

/** Où est la cabine, en clair et en une ligne.

    Une place : « A-01 · gauche ». L'emplacement entier : « A-01 », sans suffixe.
    Plusieurs emplacements : « 3 emplacements : A-01, A-02, A-03 ».

    Le COMPTE vient d'abord dans le dernier cas, et c'est le point : un
    XL (3modules) tient sur trois emplacements, et « A-01·T, A-02·T, A-03·T » se
    lisait comme un code de rack, pas comme trois endroits. Un cariste qui n'a lu
    que le premier va chercher les deux autres tiers de la cabine.

    Repli sur `position` : quelques listes servent une vue réduite de la cabine,
    sans le détail de ses occupations. */
function ouEstLaCabine(c) {
  if (!c) return '';
  const occs = (c.occupations || []).filter(o => o.emplacement_code);
  if (!occs.length) return c.position || '';
  const codes = codesEmplacements(c);
  if (codes.length > 1) return `${codes.length} emplacements : ${codes.join(', ')}`;
  // Sans nom connu — l'emplacement entier, ou une capacité illimitée — on rend
  // le code seul : c'est ce qui est écrit sur l'étiquette.
  const nom = NOM_PLACE[occs[0].place];
  return nom ? `${codes[0]} · ${nom}` : codes[0];
}

/** Y a-t-il une place à désigner ? Deux cas disent non, pour deux raisons
    opposées : une capacité illimitée n'a pas de place nommée, et un grand modèle
    n'en laisse pas le choix — il prend l’emplacement entier. Les écrans posaient
    la question en testant `d.illimite` seul, et proposaient donc « Gauche » à
    une cabine qui remplit l’emplacement : le serveur corrigeait après coup, en
    silence, ce qui est la pire des deux façons de ne pas décider. */
const sansPlaceAChoisir = (d) =>
  Boolean(d.illimite || (d.pour_cabine && d.pour_cabine.tout_l_emplacement));

/** Une ligne d'occupation dans la fiche d'un emplacement.

    « aussi en A-02, A-03 » est la partie qui évite de chercher : une cabine peut
    tenir sur plusieurs emplacements, et devant A-01 on veut lire tout de suite qu'elle
    se prolonge ailleurs. Sans cela, un cariste voit une cabine complète là où il
    n'y en a qu'un tiers, et cherche les deux autres au hasard du rack. */
function ligneOccupant(cabine, options = {}) {
  if (!cabine) return '';
  const ailleurs = codesEmplacements(cabine).filter(code => code !== options.ici);
  /* Deux états sur une ligne, et ils ne parlent pas de la même chose : la PLACE
     est occupée, la CABINE est conforme ou en quarantaine. La première version
     posait le statut de la cabine à côté du nom de la place — « G — Gauche
     Conforme » — et on lisait que la place était conforme. Chacun est donc
     rendu à côté de ce qu'il qualifie.

     Le mot du badge vient de l'appelant : « occupée » va avec une place et avec
     une cabine, « occupé » avec un emplacement. Écrit une fois pour tous, il
     produisait « Tout l’emplacement occupée » — et une faute d'accord dans un
     libellé, au poste, fait douter du reste de l'écran. */
  return `<div class="item" style="cursor:default">
    <div class="r">${options.titre} <span class="etat att">${
      options.etat || 'occupée'}</span></div>
    <div class="d">${esc(cabine.numero)} ${badgeStatut(cabine, { rangement: false })}${
      cabine.modele ? ' · ' + esc(cabine.modele) : ''}</div>
    <div class="meta">Chantier ${
      cabine.chantier ? esc(cabine.chantier) : '<em>à affecter</em>'}</div>
    ${ailleurs.length ? `<div class="meta"><b>Cette cabine occupe aussi ${
      ailleurs.length === 1 ? 'l’emplacement' : 'les emplacements'} ${esc(ailleurs.join(', '))}</b></div>` : ''}
    ${options.pourquoi ? `<div class="meta">${options.pourquoi}</div>` : ''}
  </div>`;
}

function placesHTML(d, choisie) {
  if (d.illimite) return '';
  const libelle = (code) => ((REFS_CABINE.places || []).find(x => x.code === code) || {}).libelle || code;
  return `<label>Sous-emplacement</label>
    <div class="places" id="places">${(d.places || []).map(p => {
      const libre = p.libre;
      /* Condamnée n'est pas occupée, et le dire change le geste : devant une
         place « occupée » on cherche la cabine, devant une place « condamnée —
         pilier » on prend l'autre. La faire disparaître passerait pour un
         défaut d'affichage, et quelqu'un y poserait une cabine à la main. */
      const etat = p.condamnee ? 'condamnée' : (libre ? 'libre' : occupantCourt(p));
      return `<button type="button" class="place${p.condamnee ? ' condamnee' : ''}"
        data-place="${esc(p.code)}" ${libre ? '' : 'disabled'}
        title="${esc(p.condamnee || '')}"
        aria-pressed="${String(p.code === choisie)}">
        <span class="c">${esc(p.code)}</span>
        <span class="l">${esc(libelle(p.code))}</span>
        <span class="l${p.condamnee ? ' o' : ''}">${esc(etat)}</span></button>`;
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
  if (sansPlaceAChoisir(d)) { if (surChoix) surChoix(null); return () => null; }
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

/** Le choix tactile d'une place, posé et branché d'un seul appel.

    Trois écrans avaient dérivé vers une liste déroulante : le rangement après
    scan de l'emplacement, la saisie du n° à la main devant le rack, et
    « Choisir dans la liste » depuis la fiche. Dérouler un menu pour dire
    « droite » est un geste de bureau — devant un rack, avec des gants, on ne
    déroule rien. Les trois cases montrent d'un coup d'œil ce qui est libre et
    QUI occupe le reste, et se touchent sans viser.

    Le bouton reste éteint tant qu'aucune place n'est touchée. Rien n'est
    présélectionné : la version d'avant cochait la première libre, un cariste
    pressé validait sans regarder, et la cabine était enregistrée à gauche alors
    qu'il l'avait posée à droite — une erreur muette, retrouvée des semaines plus
    tard en cherchant la cabine.

    Rend une fonction : la place retenue, ou `null` en capacité illimitée. */
function choixPlace(d, bouton, options = {}) {
  if (!bouton) return () => null;
  const libelle = bouton.textContent;
  if (!sansPlaceAChoisir(d)) {
    bouton.disabled = true;
    bouton.textContent = options.attente || 'Touche une place libre';
  }
  const lire = brancherPlaces(d, () => {
    bouton.disabled = false;
    bouton.textContent = libelle;
  });
  return () => (sansPlaceAChoisir(d) ? null : lire());
}

/** Le bloc des places, ou la phrase qui explique qu'il n'y en a pas à choisir. */
const blocPlaces = (d) => {
  if (d.illimite) {
    return '<div class="meta" style="padding:6px 2px">Capacité illimitée :'
         + ' aucune place à désigner.</div>';
  }
  // Un grand modèle : on le DIT, plutôt que de poser deux cases dont aucune ne
  // serait le bon geste. L'opérateur apprend ici, devant le rack, pourquoi il
  // n'aura pas de voisin — et pas au moment où il essaie d'en poser un.
  if (d.pour_cabine && d.pour_cabine.tout_l_emplacement) {
    return `<div class="banner" style="margin:11px 0 0">${esc(d.pour_cabine.numero)}
      est un <b>${esc(d.pour_cabine.modele || 'grand modèle')}</b> : elle prend
      <b>tout l’emplacement</b>. Il n'y a pas de place à choisir.</div>`;
  }
  return placesHTML(d);
};

/* Ce que le WMS gère lui-même : l'identité de la cabine et sa vie dans
   l'entrepôt. Revendeur, client, tissus et fond de cabine n'y sont plus — ils
   viennent du fichier de production, qui est la source, et les répéter ici
   présentait deux fois la même information en laissant croire à deux versions. */
const DETAIL_CABINE = [
  ['numero', 'N° de cabine'], ['chantier', 'Chantier'],
  ['type_libelle', 'Type'], ['modele', 'Modèle'],
  ['statut_libelle', 'État'], ['position', 'Emplacement'],
];

/** Tout ce que le WMS sait de cette cabine, replié/déplié d'une touche.

    Deux blocs, et ils ne disent pas la même chose. « Dans l'entrepôt » : ce que
    le WMS gère — le numéro, l'état, l'emplacement. « Fichier de production » :
    ce que la production annonce, et qui est la SOURCE de tout le reste.

    Il n'y a plus de section « Fiche de la cabine ». Elle listait revendeur,
    client, tissus et fond de cabine relus sur la photo du tableau papier — donc
    une seconde version d'informations que le fichier porte déjà. Quand les deux
    différaient, l'écran les montrait côte à côte sans dire laquelle croire.
    Aujourd'hui la fiche papier ne sert qu'à lire le numéro. */
async function afficherToutesCaracteristiques(c) {
  const zone = $('#fTousChamps');
  const bouton = $('#fTout');
  if (!zone) return;
  if (zone.dataset.ouvert === 'oui') {
    zone.innerHTML = '';
    zone.dataset.ouvert = 'non';
    if (bouton) bouton.textContent = ' Toutes les caractéristiques';
    if (bouton) bouton.insertAdjacentHTML('afterbegin', icon('clip', 17));
    return;
  }
  zone.dataset.ouvert = 'oui';
  zone.innerHTML = '<div class="empty">Lecture…</div>';
  if (bouton) { bouton.textContent = ' Masquer les caractéristiques'; bouton.insertAdjacentHTML('afterbegin', icon('close', 17)); }

  // `position` passe par `ouEstLaCabine` : la valeur brute du serveur est
  // « A-01·T, A-02·T, A-03·T », qui se lit comme un code de rack. Ici comme
  // ailleurs, on écrit « 3 emplacements : A-01, A-02, A-03 ».
  const valeur = (cle) => (cle === 'position' ? ouEstLaCabine(c) : c[cle]);
  const siennes = DETAIL_CABINE
    .filter(([cle]) => (valeur(cle) || '') !== '')
    .map(([cle, lib]) => `<tr><td>${esc(lib)}</td><td><b>${esc(valeur(cle))}</b></td></tr>`).join('');

  // La ligne de production est facultative : une cabine créée hors fichier n'en
  // a pas, et son absence se dit plutôt que de laisser un bloc vide.
  const attendue = await api('/cabines-attendues/' + encodeURIComponent(c.numero) + '/')
    .catch(() => null);
  const specs = attendue ? Object.entries(attendue.specifications || {}) : [];

  zone.innerHTML = `<div class="card" style="margin-top:10px">
    <div class="sec" style="margin-top:0">Dans l'entrepôt</div>
    <div class="specs"><table><tbody>${siennes}</tbody></table></div>
    <div class="sec">Fichier de production</div>
    ${attendue ? `<div class="specs"><table><tbody>${LIGNES_ATTENDUE
        .filter(([cle]) => (attendue[cle] || '') !== '')
        .map(([cle, lib]) => `<tr><td>${esc(lib)}</td><td><b>${esc(attendue[cle])}</b></td></tr>`)
        .join('')}</tbody></table></div>
      ${specs.length ? `<details style="margin-top:10px"><summary class="meta">La ligne
        complète du classeur (${specs.length} colonnes)</summary>
        <div class="specs"><table><tbody>${specs
          .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')}</tbody></table>
        </div></details>` : ''}`
      : `<div class="meta">Cette cabine n'est pas dans le fichier de production :
         soit elle a été créée avant le premier import, soit un administrateur
         l'a enregistrée hors fichier. Le motif est alors au journal.</div>`}
  </div>`;
}

/** Libellé court d'un champ de fiche, pour un message. */
function etiquetteChamp(cle) {
  const e = CHAMPS_ENTREE.find(([c]) => c === cle);
  return e ? e[1].replace(/ \*$/, '').replace(/\s*\([^)]*\)/, '') : cle;
}

async function ouvrirScanFiche(emp, d, redessiner) {
  const zone = $('#eAct');
  if (!zone) return;
  /* Une photo, pas la caméra de scan. Ce bloc proposait aussi « Activer la
     caméra » sous le titre « Photographier la fiche » : on visait le tableau et
     rien ne se passait, cette caméra-là ne lit que les QR — et les cabines n'en
     portent pas. */
  zone.innerHTML = `<div class="sec" style="margin-top:14px">Lire le n° de cabine</div>
    <label class="fichier btn-fiche" id="fLabel">${icon('camera', 22)} <span>Photographier la fiche</span>
      <input type="file" id="fPhoto" accept="image/*" capture="environment"></label>
    <div class="meta" style="margin-top:6px;text-align:center">Le tableau à deux colonnes,
      bien à plat et éclairé : le n° est lu tout seul, le reste vient du fichier de production.</div>
    <div id="fEtat"></div><div id="fSuite"></div>
    <button class="btn ghost" id="fNon" style="margin-top:10px">Annuler</button>`;

  $('#fNon').onclick = () => redessiner();
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

   « Envoyée » n'y figure pas non plus, et c'est le même raisonnement poussé
   au bout : ce n'est pas un état qu'on DÉCLARE, c'est la conséquence du geste
   de sortie. La proposer ici la mettait au même rang qu'un constat — un départ
   définitif à un bouton d'écart de « conforme » — et laissait croire qu'il
   existait plusieurs façons de sortir une cabine. Il n'y en a qu'une : le
   bouton « La sortir de l'entrepôt », qui demande son motif.                  */

//: Ce que la boîte propose : l'état de la cabine, et rien d'autre. Deux
//: réponses possibles à « comment est-elle ? », et c'est tout ce qu'on lui
//: demande.
const STATUTS_PROPOSES = [
  // Lever une quarantaine, c'est revenir ici : la cabine redevient conforme.
  // Un statut « Levée de quarantaine » distinct
  // laissait des cabines saines marquées d'un libellé alarmant pendant des
  // semaines, sans rien apprendre de plus — le passage par la quarantaine est
  // écrit au journal, avec son motif et sa date.
  ['libre',       'Conforme',              'Aucun défaut, ou quarantaine levée : elle reste en stock.'],
  ['quarantaine', 'En quarantaine',         'Bloquée : un défaut à traiter avant tout départ.'],
];

/** Le bandeau « pourquoi cette cabine est bloquée ». Écrit une fois, lu partout.

    Le motif vit au journal — c'est la bonne place, il en faut un par
    changement. Mais il n'était QUE là : pour savoir ce qui bloque une cabine il
    fallait ouvrir sa fiche, dérouler l'historique et repérer la bonne ligne.
    Devant un rack, personne ne le fait.

    Une quarantaine LEVÉE est montrée aussi, en gris : « pourquoi cette cabine
    a-t-elle été bloquée le mois dernier ? » est une vraie question, et la levée
    ne doit pas effacer la réponse. */
function blocQuarantaine(cabine) {
  const q = cabine && cabine.quarantaine;
  if (!q || !(q.motif || q.active)) return '';
  const quand = q.date ? new Date(q.date).toLocaleDateString('fr-FR') : '';
  const signe = [quand && ('le ' + quand), q.par && ('par ' + q.par)]
    .filter(Boolean).join(' ');
  return `<div class="banner ${q.active ? 'quarantaine' : 'levee'}">
    <b>${q.active ? 'En quarantaine' : 'Quarantaine levée'}${
      signe ? ' — mise ' + esc(signe) : ''}</b><br>
    ${q.motif ? esc(q.motif) : '<em>aucun motif enregistré</em>'}</div>`;
}

/** Le même rappel, en TEXTE, pour les boîtes de confirmation.

    `confirmer()` échappe son texte : on ne peut pas y glisser le bandeau. Et
    c'est bien ainsi — au moment de lever une quarantaine ou de sortir une
    cabine bloquée, ce qu'il faut sous les yeux est la phrase, pas un cadre. */
function rappelQuarantaine(cabine) {
  const q = cabine && cabine.quarantaine;
  if (!q || !q.motif) return '';
  const quand = q.date ? new Date(q.date).toLocaleDateString('fr-FR') : '';
  return `\n\nMise en quarantaine${quand ? ' le ' + quand : ''}${
    q.par ? ' par ' + q.par : ''} :\n« ${q.motif} »`;
}

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
  if (refuseSansDroit('cab_statut')) return;
  const ref = STATUTS_PROPOSES.find(s => s[0] === code) || [code, code, ''];
  const rep = await confirmer({
    titre: verbeStatut(cabine, code) + ' ?',
    /* Lever une quarantaine sans avoir le motif sous les yeux, c'est déclarer
       conforme sans savoir ce qu'on est censé avoir réparé. Il était dans
       l'historique ; il est maintenant dans la question. */
    texte: `${cabine.numero} — ${ref[2]}`
         + (code === 'libre' ? rappelQuarantaine(cabine) : ''),
    ok: 'Confirmer',
    danger: code === 'quarantaine',
    /* Une quarantaine EXIGE son motif : elle bloque la cabine et empêche son
       départ, et sans la raison écrite personne ne sait ce qu'il faut réparer
       pour la lever — la cabine reste immobile des semaines. La lever ne
       l'exige pas : constater qu'elle est redevenue conforme se passe
       d'explication. */
    champ: code === 'quarantaine'
      ? { libelle: 'Pourquoi cette quarantaine ? *', obligatoire: true,
          placeholder: 'Ex. rayure sur la paroi gauche',
          manque: 'Sans motif, personne ne saura quoi réparer pour la lever.' }
      : { libelle: 'Motif (facultatif, conservé dans l’historique)',
          placeholder: 'Ex. contrôle refait, conforme' },
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
 * répondait par un départ, juste après qu'on l'a posée dans l’emplacement — un
 * geste que rien ne distinguait des deux autres, dans la même liste.
 */
function ouvrirStatut(cabine, contexte, apres, opts = {}) {
  // La question suit un rangement. Sans la case « changer le statut », elle est
  // sautée : le rangement, lui, est fait, et l'écran suivant s'ouvre.
  if (!peut('cab_statut')) { if (apres) apres(null); return; }
  const actuel = cabine.statut;
  const proposes = opts.statuts
    ? STATUTS_PROPOSES.filter(([code]) => opts.statuts.includes(code))
    : STATUTS_PROPOSES;
  modale(`Statut de ${esc(cabine.numero)}`, `
    <div class="meta">${esc(contexte)}</div>
    ${blocQuarantaine(cabine)}
    <div class="statuts" id="stListe">${proposes.map(([code, nom, aide]) => `
      <button type="button" class="statut" data-st="${code}" aria-pressed="${String(code === actuel)}">
        <span class="n">${esc(nom)}${code === actuel ? ' <span class="pill">actuel</span>' : ''}</span>
        <span class="a">${esc(aide)}</span>
      </button>`).join('')}</div>
    <label style="margin-top:12px" id="stMotifLib">Motif (facultatif)</label>
    <input id="stMotif" placeholder="Ex. rayure sur la paroi" autocomplete="off">
    <div class="manque" id="stManque"></div>
    <div class="row" style="margin-top:12px">
      <button class="btn orange" id="stOk" style="margin-top:0">Enregistrer le statut</button>
      <button class="btn ghost" id="stNon" style="margin-top:0">Laisser tel quel</button>
    </div>`);

  let choisi = actuel;
  const cases = Array.from(document.querySelectorAll('#stListe .statut'));
  /* Le libellé du motif suit le statut choisi : obligatoire pour poser une
     quarantaine, facultatif pour tout le reste. L'annoncer AVANT la validation
     évite de faire toucher « Enregistrer » pour apprendre qu'il manque quelque
     chose — et évite surtout le « ok » tapé pour passer. */
  const majMotif = () => {
    const dur = choisi === 'quarantaine';
    const lib = $('#stMotifLib'), champ = $('#stMotif'), manque = $('#stManque');
    if (lib) lib.textContent = dur ? 'Pourquoi cette quarantaine ? *' : 'Motif (facultatif)';
    if (champ) {
      champ.placeholder = dur ? 'Ex. rayure sur la paroi gauche'
                              : 'Ex. contrôle refait, conforme';
    }
    if (manque) manque.textContent = '';
  };
  cases.forEach(b => b.onclick = () => {
    choisi = b.dataset.st;
    cases.forEach(x => x.setAttribute('aria-pressed', String(x.dataset.st === choisi)));
    majMotif();
  });
  majMotif();

  $('#stNon').onclick = () => { fermerModale(); if (apres) apres(null); };
  $('#stOk').onclick = async () => {
    const motif = ($('#stMotif').value || '').trim();
    if (choisi === actuel) { fermerModale(); if (apres) apres(null); return; }
    if (choisi === 'quarantaine' && !motif) {
      $('#stManque').textContent = 'Sans motif, personne ne saura quoi réparer '
                                 + 'pour la lever.';
      $('#stMotif').focus();
      return;
    }
    try {
      await api(`/cabines/${cabine.id}/statut/`, { method: 'POST', body: { statut: choisi, motif } });
      const nom = (proposes.find(s => s[0] === choisi) || [])[1] || choisi;
      toast(cabine.numero + ' : ' + nom, 'ok');
      fermerModale();
      if (apres) apres(choisi);
    } catch (e) { toast(e.message, 'err'); }
  };
}

/** LA sortie. Il n'y en a qu'une, et elle est définitive.

    Il y avait deux gestes voisins, côte à côte sur la fiche : « Sortir de
    l'emplacement » (la cabine restait en stock, nulle part) et « Envoyer
    (définitif) ». Personne ne peut deviner lequel choisir, les deux libèrent la
    place, et l'état « en stock, non rangée » ne correspondait à rien sur le
    terrain — une cabine qu'on descend du rack part.

    « c'est rentrée et sortie » : un geste pour entrer, un geste pour sortir.
    Le motif et la confirmation sont demandés par `envoyerCabine`, par où passe
    toute sortie. */
async function sortirDefinitivement(cabine, apres) {
  if (refuseSansDroit('cab_envoyer')) return null;
  try {
    if (!(await envoyerCabine(cabine))) return null;
  } catch (e) { toast(e.message, 'err'); return null; }
  // On relit la fiche : l'écran suivant doit montrer la cabine telle qu'elle
  // est maintenant — archivée, sans emplacement.
  let frais = cabine;
  try { frais = await api(`/cabines/${cabine.id}/`); } catch (_) {}
  toast(`${frais.numero} sortie de l’entrepôt`, 'ok');
  noterRecentCabine(frais);
  if (apres) apres(frais);
  return frais;
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
      ${blocPlaces(d)}
      <button class="btn orange" id="pOk">${ailleurs
        ? 'Déplacer de ' + esc(cabine.emplacement_code) + ' vers ' + esc(d.code)
        : 'Ranger en ' + esc(d.code)}</button>
    </div>`;
  const place = choixPlace(d, $('#pOk'));
  $('#pOk').onclick = async () => {
    try {
      const choix = place();
      if (!sansPlaceAChoisir(d) && !choix) { toast('Touche la place où tu poses la cabine.', 'err'); return; }
      const corps = { emplacement: emp.id };
      if (choix) corps.place = choix;
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
  if (!peut('cab_ranger')) {
    layout(`<h2 class="title">Ranger une cabine</h2>
      <div class="banner">${esc(sansLeDroit('cab_ranger'))}</div>`, 'rangement');
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
  // cariste de marcher jusqu'à l’emplacement, de scanner et de toucher une place
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
      ${peut('cab_envoyer') ? '<button class="btn orange" id="djReprendre">La remettre en stock</button>'
        : `<div class="meta">${esc(sansLeDroit('cab_envoyer'))}</div>`}
      <button class="btn ghost" id="djAutre">Autre cabine</button>
    </div>`;
  $('#djAutre').onclick = () => { arreterCamera(); repartirRangement(); etapeRangement(); };
  if ($('#djReprendre')) $('#djReprendre').onclick = async () => {
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
  if (refuseSansDroit('cab_envoyer')) return null;
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
  // Sortir exige un n° de chantier, pour tous les types sans exception — et la
  // case « sortir des cabines ». Le dire ici plutôt que de laisser le geste
  // échouer après coup.
  const sansDroit = !peut('cab_envoyer');
  const bloque = sansDroit || !c.chantier;
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
        <span class="t">La sortir de l’entrepôt</span>
        <span class="s">${sansDroit ? esc(sansLeDroit('cab_envoyer')) : bloque
          ? 'Impossible sans n° de chantier : à affecter sur la fiche de la cabine'
          : `C'est définitif : ${plusieurs ? 'ses emplacements se libèrent'
             : esc(c.position) + ' se libère'}, la cabine part et rejoint les archives`}</span>
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
    // Un seul geste de sortie dans toute l'application, et il est définitif :
    // la confirmation et le motif sont posés par `envoyerCabine`.
    const frais = await sortirDefinitivement(c);
    if (!frais) return;
    // La cabine est PARTIE : il n'y a plus rien à ranger. On repart à zéro,
    // prêt pour la suivante — proposer de la reposer quelque part serait
    // proposer l'impossible, et c'est ce que faisait l'ancien retrait de place.
    RANGEMENT = RANGEMENT_NEUF();
    etapeRangement();
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
      ${blocCameraHTML('Scanner le QR de l’emplacement', 'L’étiquette collée sur l’emplacement')}
      <div id="rEmpEtat"></div>
      <details style="margin-top:14px"><summary class="meta">Saisir le code à la main</summary>
        <label style="margin-top:8px">Code de l’emplacement</label>
        <input id="rEmp" placeholder="Ex. AC551" autocomplete="off">
        <button class="btn ghost" id="rEmpOk">Continuer</button>
      </details>
    </div>`;
  brancherRappel();
  // Scan : un refus s'affiche sur la vidéo. Saisie : sous le champ.
  brancherCamera((texte) => retenirEmplacement(texte));
  const valider = async () => {
    const refus = await retenirEmplacement($('#rEmp').value);
    const etat = $('#rEmpEtat');
    if (etat) etat.innerHTML = refus ? `<div class="banner">${esc(refus)}</div>` : '';
  };
  $('#rEmpOk').onclick = valider;
  $('#rEmp').onkeydown = (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); valider(); } };
}

/** Retient l'emplacement scanné ou saisi. Renvoie '' quand il est retenu — l'étape
 *  suivante s'ouvre —, sinon la raison du refus, que l'appelant affiche. */
async function retenirEmplacement(texte) {
  const code = String(texte || '').replace(/^LOC:/i, '').trim();
  if (!code) return 'Saisis le code de l’emplacement.';
  try {
    const res = await api('/emplacements/?search=' + encodeURIComponent(code))
      .then(d => d.results || []);
    const e = res.find(x => (x.code || '').toUpperCase() === code.toUpperCase())
           || (res.length === 1 ? res[0] : null);
    if (!e) return `Aucun emplacement ne correspond à « ${code} ».`;
    if (e.est_mp) {
      return `${e.code} range des matières premières (${e.usage_libelle}) : on n’y pose `
           + 'pas de cabine. Scanne un emplacement de cabines.';
    }
    const d = await api(`/emplacements/${e.id}/places/`
      + (RANGEMENT.cabine ? '?pour_cabine=' + RANGEMENT.cabine.id : ''));
    // On reste à l'étape 2 : la cabine reste en main, il suffit de scanner un
    // autre emplacement. Repartir de zéro ferait refaire la photo de la fiche.
    if (d.complet) return `${d.code} n’a plus de place libre pour cette cabine. Scanne un autre emplacement.`;
    await arreterCamera();
    RANGEMENT.emp = e;
    RANGEMENT.d = d;
    etapeRangement();
    return '';
  } catch (err) { return err.message; }
}

/* --- Étape 3 : quelle place ? ---------------------------------------------- */
function etapePlace() {
  const zone = $('#zone');
  if (!zone) return;
  const { cabine, emp, d } = RANGEMENT;
  // Une cabine n'occupe qu'un emplacement : la ranger ailleurs la DÉPLACE.
  // Sans cet avertissement, ranger une cabine déjà posée vidait sa emplacement en
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
      ${blocPlaces(d)}
      <button class="btn orange" id="rOk">Ranger en ${esc(d.code)}</button>
      <button class="btn ghost" id="rAutre">Choisir un autre emplacement</button>
    </div>`;
  brancherRappel();
  $('#rAutre').onclick = () => { RANGEMENT.emp = null; RANGEMENT.d = null; etapeRangement(); };
  // Le geste a été choisi à l'étape précédente, et le rappel du haut porte de
  // quoi le changer : il n'y a plus de question à reposer ici.

  const bouton = $('#rOk');
  const place = choixPlace(d, bouton);

  bouton.onclick = async () => {
    const choix = place();
    if (!sansPlaceAChoisir(d) && !choix) { toast('Touche la place où tu poses la cabine.', 'err'); return; }
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
  if (refuseSansDroit('cab_envoyer')) return false;
  let c = cabine;
  try { c = await api(`/cabines/${cabine.id}/`); } catch (_) {}
  if (c && c.statut === 'quarantaine') {
    const ok = await confirmer({
      titre: `${c.numero} est EN QUARANTAINE`,
      texte: 'Cette cabine est bloquée.' + rappelQuarantaine(c) + '\n\n'
           + 'La sortir la fait quitter définitivement l’entrepôt, avec son '
           + 'défaut, et elle ne pourra plus être rangée.\n\n'
           + 'Confirmes-tu la sortie de cette cabine en quarantaine ?',
      ok: 'Oui, sortir malgré la quarantaine',
      annuler: 'Non, je la laisse',
      danger: true,
    });
    if (!ok) return false;
  }
  /* LE MOTIF, demandé ici et pas ailleurs. Le serveur l'exige depuis que
     sortir et envoyer sont un seul geste, et cinq écrans appellent cette
     fonction : demandé à chacun, il aurait été oublié par trois — c'est
     exactement ce qui était arrivé à la confirmation de quarantaine. */
  let note = (corps.note || '').trim();
  if (!note) {
    const ou = c && c.position ? ` ${ouEstLaCabine(c)} se libère, et` : '';
    const rep = await confirmer({
      titre: `Sortir ${c.numero} de l’entrepôt ?`,
      texte: `C’est définitif :${ou} la cabine rejoint les archives. `
           + 'Elle ne pourra plus être rangée — seule une remise en stock, '
           + 'depuis sa fiche, la ferait revenir.',
      ok: 'Sortir la cabine',
      danger: true,
      champ: { libelle: 'Pourquoi sort-elle ? *', obligatoire: true,
               placeholder: 'Ex. départ en pose, chargée camion 12',
               manque: 'Sans motif, personne ne saura où elle est passée.' },
    });
    if (!rep || !rep.ok) return false;
    note = (rep.valeur || '').trim();
  }
  await api(`/cabines/${cabine.id}/envoyer/`, { method: 'POST',
    body: { ...corps, note } });
  return true;
}

/* ===========================================================================
   SORTIR UNE CABINE — par la fiche, comme le rangement

   Même geste d'entrée que pour ranger : on photographie la fiche collée sur la
   cabine. C'est la seule chose que le cariste a en main devant le rack.

   Il n'y a pas d'étape « emplacement » ici : la fiche identifie la cabine, et le
   WMS sait déjà où elle est rangée. Faire scanner l’emplacement n'apporterait aucune
   information — seulement une occasion d'échouer.
   =========================================================================== */

let SORTIE = { cabine: null };

async function renderSortieCabine() {
  if (!peut('cab_envoyer')) {
    layout(`<h2 class="title">Sortir une cabine</h2>
      <div class="banner">${esc(sansLeDroit('cab_envoyer'))}</div>`, 'sortie-cabine');
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
      ${blocQuarantaine(c)}
      <div class="banner">La sortie est <b>définitive</b> : la cabine quitte
        l'entrepôt, ${range ? 'sa place se libère, ' : ''}et elle rejoint les
        archives — une cabine sortie ne se range plus.</div>
      ${!c.chantier ? `<div class="banner">Pas d'envoi sans chantier, quel que soit le
          type de cabine. Renseigne-le d'abord.</div>
        ${champChantier('sCha', '')}` : ''}
      <label for="sNote">Pourquoi sort-elle ? *</label>
      <input id="sNote" placeholder="Ex. départ en pose, BL 2026-0412" autocomplete="off">
      <div class="manque" id="sManque"></div>
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
      // Le motif est exigé par le serveur : le dire ICI évite l'aller-retour
      // qui renvoie une erreur rouge après coup, et le champ garde la saisie.
      if (!note) {
        $('#sManque').textContent = 'Sans motif, personne ne saura où elle est passée.';
        $('#sNote').setAttribute('aria-invalid', 'true');
        $('#sNote').focus();
        bouton.disabled = false;
        return;
      }
      // Une cabine qu'on descend du rack part : sortir, c'est envoyer. Il n'y
      // a pas d'état « en stock, nulle part » à proposer.
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
  const zone = zoneEcran({ neuf: true });
  if (!zone) return;
  zone.innerHTML = '<div class="empty">Chargement…</div>';
  try {
    const [c, hist] = await Promise.all([
      api(`/cabines/${cabine.id}/`),
      api(`/cabines/${cabine.id}/historique/`),
    ]);
    noterRecentCabine(c);   // alimente les « Récents » du scanner
    // Quatre cases, quatre familles de boutons : chacune n'apparaît qu'à qui l'a.
    const statuer = peut('cab_statut'), ranger = peut('cab_ranger');
    const sortir = peut('cab_envoyer'), corriger = peut('cab_corriger');
    const modifiable = !c.envoyee && (statuer || ranger || sortir);
    zone.innerHTML = `
      ${retour ? '<button class="btn ghost" id="fRetour" style="margin:0 0 12px">← Retour</button>' : ''}
      <div class="card">
        <div class="r" style="font-size:18px;font-weight:700">${esc(c.numero)} ${
          badgeStatut(c, { rangement: false })}</div>
        <div class="meta" style="margin-top:4px">
          ${esc(c.type_libelle)} · chantier ${c.chantier ? esc(c.chantier) : '<em>non affecté</em>'}
          ${c.modele ? ' · ' + esc(c.modele) : ''}</div>
        <div class="meta">${c.position ? 'Rangée en ' + esc(ouEstLaCabine(c)) : 'Non rangée'}</div>
        ${blocEmplacements(c)}
        <div style="margin-top:12px">${blocQuarantaine(c)}</div>
        ${c.envoyee ? '' : `<div class="meta" style="margin-top:4px">Sans mouvement depuis ${c.jours_immobile} jour${c.jours_immobile === 1 ? '' : 's'}</div>`}
        ${c.envoyee ? `<div class="banner" style="margin:12px 0 0">Cabine envoyée le ${new Date(c.envoi_date).toLocaleString('fr-FR')} — fiche archivée. La fiche reste corrigeable, et la cabine peut être remise en stock si elle revient.</div>
          ${sortir ? `<button class="btn orange" id="fReprendre">La remettre en stock</button>` : ''}` : ''}
        <button class="btn ghost" id="fTout" style="margin-top:12px">${
          icon('clip', 17)} Toutes les caractéristiques</button>
        <div id="fTousChamps"></div>
        <div id="fAct"></div>
          ${corriger ? `<div class="row" style="margin-top:10px">
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

    /* « Toutes les caractéristiques » : tout ce que le WMS sait de cette cabine,
       d'un seul geste. La fiche n'en montrait que sept champs — ceux qui portent
       une règle logistique — et le reste (gamme, semaine de production, jour,
       tissus, fond, et la ligne complète du classeur) n'était visible qu'avant
       l'entrée en stock, sur l'écran de la cabine annoncée. Une fois la cabine
       entrée, cette information devenait inatteignable alors qu'elle est en base.
       Replié par défaut : devant le rack on veut le geste, pas la fiche
       technique. */
    $('#fTout').onclick = () => afficherToutesCaracteristiques(c);

    // Corriger et supprimer restent accessibles sur une cabine envoyée : une faute
    // de frappe reste une faute de frappe une fois la cabine partie, et corriger
    // l'archive vaut mieux que la supprimer pour la ressaisir.
    if (corriger) {
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
    const titreGestes = ranger ? (c.position ? 'Changer d’emplacement' : 'Ranger cette cabine')
                               : 'La sortir';
    $('#fAct').innerHTML = `
      ${statuer ? `<div class="sec">État de la cabine</div>
      ${statutsPossibles.map(s => `<button class="btn ghost" data-vers="${s.code}"
        >${esc(verbeStatut(c, s.code))}</button>`).join('')}` : ''}
      ${(ranger || sortir) ? `<div class="sec" style="margin-top:14px">${titreGestes}</div>` : ''}
      ${ranger ? `<button class="btn ghost" id="fRanger">${icon('in', 17)} ${
        c.position ? 'La ranger ailleurs' : 'Choisir son emplacement'}</button>` : ''}
      ${sortir ? `<button class="btn orange" id="fSortir">${icon('out', 17)} La sortir de l’entrepôt</button>` : ''}
      <div id="fZone"></div>`;

    $('#fAct').querySelectorAll('[data-vers]').forEach(b => b.onclick =
      () => confirmerChangementStatut(c, b.dataset.vers, () => ficheCabine(c, retour)));

    // Retient la cabine, puis renvoie au scanner : le scan de l'emplacement la range.
    /* Les trois chemins de rangement — scan, saisie du code, liste — sont
       maintenant UN écran, `ecranRangement`. Ils vivaient ici en trois
       fermetures qui se ressemblaient, et la copie de la saisie du code était
       celle qui marchait : celle du bloc d'après-création renvoyait vers cette
       fiche, où il fallait appuyer une seconde fois sur le même libellé. */
    if (ranger) $('#fRanger').onclick = () => ecranRangement(c, () => ficheCabine(c, retour));

    /* La sortie exige un n° de chantier, pour tous les types sans exception —
       l'exemption vaut pour ENTRER en stock, jamais pour en sortir. Ce chemin
       sait l'affecter au lieu de laisser le geste échouer après coup. Le motif,
       lui, est demandé par `envoyerCabine`, par où passe toute sortie.

       Ce bouton était double — « Sortir de l'emplacement » et « Envoyer
       (définitif) » l'un sous l'autre — et l'envoi, ici, sautait la
       confirmation de quarantaine : il appelait `/envoyer/` en direct. */
    if (sortir) $('#fSortir').onclick = async () => {
      if (!c.chantier) {
        $('#fZone').innerHTML = `<div class="banner">N° de chantier obligatoire pour sortir la cabine.</div>
          ${champChantier('fCha', '')}
          <button class="btn orange" id="fChaOk">Affecter puis continuer</button>`;
        $('#fChaOk').onclick = async () => {
          try {
            await api(`/cabines/${c.id}/chantier/`, { method: 'POST', body: { chantier: $('#fCha').value } });
          } catch (e) { toast(e.message, 'err'); return; }
          sortirDefinitivement(c, () => ficheCabine(c, retour));
        };
        return;
      }
      sortirDefinitivement(c, () => ficheCabine(c, retour));
    };
  } catch (e) { zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}


/* --- Corriger ou supprimer une cabine mal saisie ----------------------------
   Une cabine créée avec un mauvais numéro n'avait aucune issue dans l'interface :
   ni correction, ni suppression. Il fallait passer par l'administration Django,
   qui écrit sans rien journaliser.                                            */

function ouvrirCorrectionCabine(c, apres) {
  if (refuseSansDroit('cab_corriger')) return;
  const types = REFS_CABINE.types || [{ code: 'normale', libelle: 'Normale' }];
  const ligne = (id, libelle, valeur, extra = '') =>
    `<label for="${id}">${esc(libelle)}</label>
     <input id="${id}" value="${esc(valeur || '')}" autocomplete="off" ${extra}>`;

  const corps = modale('Corriger la fiche ' + c.numero, `
    ${ligne('kNum', 'N° de cabine *', c.numero, 'placeholder="26_03_47"')}
    <div class="aide">Format attendu : deux chiffres, deux chiffres, deux chiffres, séparés par des tirets bas.</div>
    ${champChantier('kCha', c.chantier)}
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
  if (refuseSansDroit('cab_corriger')) return;
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
  choisirParc('cabines');
  go('cabines');
}

const filtreActif = (poses) => Object.entries(poses).every(([k, v]) => FILTRES_CAB[k] === v);

/** Nombre de filtres posés, hors tri : sert à annoncer « Filtres (3) ». */
function nbFiltresCab() {
  const vide = FILTRES_CAB_VIDE();
  return Object.keys(vide).filter(k => k !== 'ordering' && FILTRES_CAB[k] !== vide[k]).length;
}

async function renderCabines() {
  // Le Stock a deux faces : les cabines, et les matières premières. Le choix se
  // fait par les deux boutons du haut, et le téléphone s'en souvient.
  if (PARC_MODE === 'mp') return renderStockMP();
  await refsCabine();
  const options = await api('/cabines/filtres/').catch(() => null);
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

  layout(`<h2 class="title">Stock</h2>
    ${basculeParc()}
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
  brancherBasculeParc();
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


//: Reflet exact de `Emplacement.MODES_PLACES` — un test Django compare les deux.
//: Le jour où les modes ont changé côté serveur (« gmd » → « gd »), cette liste
//: est restée en arrière : chaque création d'emplacement était refusée.
const MODES_EMP = [['gd', '2 places (gauche, droite)'], ['illimite', 'Capacité illimitée']];

/* Ce que range un emplacement, en UNE question : des cabines — sur deux places
   ou en capacité illimitée — ou une famille de matières premières, sur trois
   places. Les modes des cabines viennent de MODES_EMP, qui reste la source. */
const AIDE_CHOIX_CABINES = {
  gd: 'Gauche et droite, une cabine chacune — une seule si c’est un grand modèle.',
  illimite: 'Aire tampon — à ranger, sortie de production : autant de cabines que nécessaire.',
};
const CHOIX_USAGE = [
  ...MODES_EMP.map(([mode, libelle]) => [`cabines-${mode}`,
    `Cabines — ${libelle.charAt(0).toLowerCase()}${libelle.slice(1)}`, AIDE_CHOIX_CABINES[mode] || '']),
  ['carton', 'MP — cartons', 'Palettes de cartons, sur trois places : gauche, milieu, droite.'],
  ['vitrage', 'MP — vitrages', 'Chevalets de vitrages, sur trois places : gauche, milieu, droite.'],
];

/** Le choix qui décrit un emplacement tel qu'il est. */
const choixUsageDe = (e) => (e && e.est_mp ? e.usage : `cabines-${(e && e.mode_places) || 'gd'}`);

/** Un choix → ce qu'on écrit : `{ usage, mode_places }`. Le mode d'un
    emplacement MP ne décrit rien : on garde celui qu'il avait. */
function usageDeChoix(choix, avant) {
  if (String(choix).startsWith('cabines-')) {
    return { usage: 'cabines', mode_places: choix.slice('cabines-'.length) };
  }
  return { usage: choix, mode_places: (avant && avant.mode_places) || 'gd' };
}

const optionsUsage = (choisi) => CHOIX_USAGE.map(([c, l]) =>
  `<option value="${c}"${c === choisi ? ' selected' : ''}>${esc(l)}</option>`).join('');

const AIDE_MODE = '« 2 places » pour un emplacement où chaque cabine a sa place, à gauche ou à droite. '
  + '« Capacité illimitée » pour une aire tampon — à ranger, sortie de production — '
  + 'qui accueille autant de cabines que nécessaire. « MP » pour des vitrages ou des cartons, '
  + 'posés sur trois places : gauche, milieu, droite.';

/* --- Création : en haut de l'écran, dans une fenêtre ----------------------- */
function ouvrirNouvelEmplacement(apres) {
  const corps = modale('Nouvel emplacement', `
    <label for="nCode">Code de l'emplacement *</label>
    <input id="nCode" placeholder="Ex. C004, D012 ou ARANGER" autocomplete="off" autocapitalize="characters">
    <div class="aide">C'est ce code qui sera imprimé sur l'étiquette QR collée sur l’emplacement.</div>
    <label for="nMode">Ce qu’il range</label><select id="nMode">${optionsUsage('cabines-gd')}</select>
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
        ...usageDeChoix(corps.querySelector('#nMode').value),
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
    <label for="rMode">Ce qu’il range</label><select id="rMode">${optionsUsage('cabines-gd')}</select>
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
        ...usageDeChoix(corps.querySelector('#rMode').value),
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
  return EMPS;
}

/* --- Écran principal : les racks d'abord ------------------------------------
   L'entrepôt se pense par rack. Une liste plate de 45 emplacements — demain 400 —
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
  // Un emplacement de matières premières n'est ni libre ni plein POUR UNE
  // CABINE : il ne les prend pas. Il sort de l'échelle, qui parle de cabines.
  if (e.est_mp) return 'mp';
  const n = e.nb_cabines || 0;
  if (n === 0) return 'vide';
  if (e.illimite) return 'une';
  if (!e.places_libres || !e.places_libres.length) return 'complet';
  return n === 1 ? 'une' : 'deux';
}

const CLASSE_ETAT = { vide: 'ok', une: 'att', deux: 'crit', complet: 'plein', inactif: '', mp: 'mp' };

/* Ce qu'on affiche, et ce qu'on n'affiche plus.

   La version précédente montrait « 2/3 » : deux places prises sur trois. Le
   chiffre est exact et pourtant trompeur — les cabines n'ont pas toutes la même
   largeur, si bien qu'un emplacement « 1/3 » peut n'accueillir plus personne, et
   qu'un « 2/3 » peut encore prendre une petite. Le seul état sur lequel on peut
   s'engager sans connaître les dimensions, c'est : entièrement libre, ou pas.
   Pour le reste on annonce ce qu'on sait de sûr — le nombre de cabines
   présentes — et « complet » quand le WMS refusera d'y ranger quoi que ce soit. */
const LIBELLE_ETAT = { vide: 'libre', une: '1 cabine', deux: '2 cabines',
                       complet: 'complet', inactif: 'inactif', mp: 'MP' };

/** Ce que porte un emplacement MP, en deux mots : « vide », « 2 codes ». */
function contenuMPCourt(e) {
  const m = e.mp || {};
  if (!m.codes) return 'vide';
  return `${m.codes} code${m.codes > 1 ? 's' : ''}`;
}

/** La pastille d'état d'un emplacement dans une liste : l'occupation pour les
    cabines, la matière et le contenu pour un emplacement MP. */
function etiquetteEtat(e) {
  const etat = etatEmplacement(e);
  if (etat === 'mp') {
    return `<span class="etat mp ${esc(e.usage)}">${esc(e.usage_libelle || 'MP')} · ${contenuMPCourt(e)}</span>`;
  }
  return `<span class="etat ${CLASSE_ETAT[etat]}">${LIBELLE_ETAT[etat]}</span>`;
}

/** Ce qu'on inscrit dans une case du plan : jamais un décompte de places. */
function occupationCourte(e) {
  const etat = etatEmplacement(e);
  if (etat === 'inactif') return 'hors service';
  if (etat === 'mp') return contenuMPCourt(e);
  if (etat === 'vide') return 'libre';
  if (etat === 'complet') return 'complet';
  const n = e.nb_cabines || 0;
  return n + ' cabine' + (n > 1 ? 's' : '');
}

async function renderEmplacements() {
  // Rappelé directement au retour d'une fiche, sans passer par `go()` : il
  // reprend son nom d'écran, et avec lui le rafraîchissement automatique.
  if (ECRAN !== 'rack') ECRAN = 'emplacements';
  await refsCabine();
  // Créer et supprimer ont leur case ; régler et mettre hors service, les leurs.
  // Un compte qui n'a aucune des trois consulte, et l'écran le lui dit.
  const creer = peut('empl_creer');

  layout(`
    <div class="tete-ecran">
      <h2 class="title" style="margin:0">Emplacements</h2>
      ${creer ? `<div class="actions-tete">
        <button class="btn ghost bouton-tete" id="eRack">${icon('grille', 18)} Créer un rack</button>
        <button class="btn orange bouton-tete" id="eNouveau">${icon('plus', 18)} Nouvel emplacement</button>
      </div>` : ''}
    </div>
    ${gereEmplacements() ? '' : `<div class="banner">Consultation seule : ton compte n’a aucune
      des cases des emplacements (${esc(DROITS_EMPLACEMENTS.map(libelleDroit).join(', '))}).</div>`}
    <div class="card">
      <label for="eSearch">Aller directement à un emplacement</label>
      <input id="eSearch" placeholder="Code de l’emplacement (ex. AC551)" autocomplete="off">
      <div class="list" id="eRes"></div>
    </div>
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'emplacements');

  if (creer) {
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
            <div class="r">${esc(e.code)} ${etiquetteEtat(e)}</div>
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
      zone.innerHTML = `<div class="empty">Aucun emplacement. ${peut('empl_creer') ? 'Commence par créer un rack.' : ''}</div>`;
      return;
    }
    zone.innerHTML = `<div class="sec">${groupes.length} rack${groupes.length === 1 ? '' : 's'} · ${emps.length} emplacement${emps.length === 1 ? '' : 's'}</div>
      <div class="racks">${groupes.map(([nom, liste]) => {
        const cabines = liste.reduce((n, e) => n + (e.nb_cabines || 0), 0);
        const libres = liste.filter(e => etatEmplacement(e) === 'vide').length;
        const mp = liste.filter(e => e.est_mp).length;
        // La jauge montre ce qui reste : c'est la question posée devant le rack.
        const part = liste.length ? Math.round((libres / liste.length) * 100) : 0;
        return `<button class="rack" data-rack="${esc(nom)}">
          <span class="nom">${esc(nom === '(hors rack)' ? 'Hors rack' : nom)}</span>
          <span class="jauge ${libres ? '' : 'sature'}"><span style="width:${part}%"></span></span>
          <span class="chiffres"><b>${libres}</b> emplacement${libres > 1 ? 's' : ''} entièrement libre${libres > 1 ? 's' : ''}</span>
          <span class="detail">sur ${liste.length} · ${cabines} cabine${cabines === 1 ? '' : 's'} rangée${cabines === 1 ? '' : 's'}${
            mp ? ` · ${mp} pour les MP` : ''}</span>
        </button>`;
      }).join('')}</div>`;
    zone.querySelectorAll('[data-rack]').forEach(b => b.onclick = () => ouvrirRack(b.dataset.rack, emps));
    // Après une modification — ou un rafraîchissement automatique —, on revient
    // sur le rack qu'on regardait : c'est la raison d'être de RACK_OUVERT.
    if (RACK_OUVERT && groupes.some(([nom]) => nom === RACK_OUVERT)) ouvrirRack(RACK_OUVERT, emps);
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
    // Un emplacement MP porte la texture de sa matière — verre ou carton — et
    // se lit « vide » ou « 2 codes » : l'échelle des cabines ne le concerne pas.
    // Réservé à certains codes : un coin marqué, et les codes dans l'infobulle.
    const reserves = e.est_mp ? (e.codes_acceptes || []).map(a => a.code) : [];
    const matiere = e.est_mp ? ` ${esc(e.usage)}${e.mp && e.mp.lignes ? ' charge' : ''}${
      reserves.length ? ' reserve' : ''}` : '';
    return `<button class="case ${etatEmplacement(e)}${matiere}" data-emp="${e.id}" title="${
        esc(e.code + (e.est_mp ? ' — ' + (e.usage_libelle || '') : '')
            + (reserves.length ? ' — réservé à ' + listeCodes(reserves) : ''))}"${coche}>
      <span class="c">${esc(e.code)}</span>
      <span class="o">${occupationCourte(e)}</span>
    </button>`;
  };

  // En sélection, le n° de colonne et le niveau se touchent : ils cochent toute
  // la colonne, tout le niveau — le sol d'un rack où se posent les chevalets.
  const enTete = (c) => (SELECTION_RACK.actif
    ? `<button type="button" class="col sel" data-col="${c}" title="Toute la colonne ${c}">${c}</button>`
    : `<span class="col">${c}</span>`);
  const etage = (niv) => (SELECTION_RACK.actif
    ? `<button type="button" class="niv sel" data-niv="${niv}" title="Tout le niveau ${niv}">N${niv}</button>`
    : `<span class="niv">N${niv}</span>`);
  const plan = (colonnes.length && niveaux.length)
    ? `<div class="plan" style="--colonnes:${colonnes.length}">
         <div class="plan-entete"><span class="coin"></span>${colonnes.map(enTete).join('')}</div>
         ${niveaux.map(niv => `<div class="plan-ligne">
            ${etage(niv)}
            ${colonnes.map(c => cellule(parPosition.get(c + '/' + niv))).join('')}
          </div>`).join('')}
       </div>`
    : '';
  const familles = [...new Set(liste.filter(e => e.est_mp).map(e => e.usage))];

  zone.innerHTML = `
    <button class="btn ghost" id="rRetour">&#8592; Tous les racks</button>
    <div class="sec">Rack ${esc(nom === '(hors rack)' ? '— hors rack' : nom)} ·
      ${liste.filter(e => etatEmplacement(e) === 'vide').length} libre${liste.filter(e => etatEmplacement(e) === 'vide').length > 1 ? 's' : ''} sur ${liste.length}</div>
    <div class="legende">
      <span><i class="pastille ok"></i>libre</span>
      <span><i class="pastille att"></i>1 cabine</span>
      <span><i class="pastille crit"></i>2 cabines</span>
      <span><i class="pastille plein"></i>complet — le WMS refusera d’y ranger</span>
      ${familles.includes('vitrage') ? '<span><i class="pastille vitrage"></i>MP · vitrages</span>' : ''}
      ${familles.includes('carton') ? '<span><i class="pastille carton"></i>MP · cartons</span>' : ''}
      ${liste.some(e => e.est_mp && (e.codes_acceptes || []).length)
        ? '<span><i class="pastille reserve"></i>réservé à certains codes</span>' : ''}
    </div>
    ${SELECTION_RACK.actif ? `<div class="aide" style="margin:-2px 2px 10px">Touchez une case — ou un
      n° de colonne, un niveau (N0, N1…) pour cocher toute la ligne d’un coup.</div>` : ''}
    ${plan}
    ${orphelins.length ? `<div class="sec">Sans position dans le rack</div>
      <div class="cases-libres">${orphelins.map(cellule).join('')}</div>` : ''}
    ${peutUnDe(['empl_regler', 'empl_creer']) ? `<button class="btn ghost" id="selMode" style="margin-top:22px">
        ${SELECTION_RACK.actif ? 'Quitter la sélection'
          : icon('grille', 17) + ' Sélectionner plusieurs emplacements'}</button>` : ''}
    ${(peut('empl_creer') && !SELECTION_RACK.actif && nom !== '(hors rack)') ? `<button class="btn danger" id="rSupp"
        style="margin-top:10px">${icon('trash', 17)} Supprimer le rack ${esc(nom)}</button>` : ''}
    ${SELECTION_RACK.actif ? barreSelection(liste.length,
      liste.filter(e => e.est_mp && SELECTION_RACK.ids.has(e.id)).length) : ''}`;

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
  const bTout = $('#selTout');
  if (bTout) bTout.onclick = () => { liste.forEach(e => SELECTION_RACK.ids.add(e.id)); ouvrirRack(nom, emps); };
  const bUsage = $('#selUsage');
  if (bUsage) bUsage.onclick = () => ouvrirUsageSelection(nom);
  const bCodes = $('#selCodes');
  if (bCodes) bCodes.onclick = () => ouvrirCodesSelection(nom, liste);
  // Une colonne, un niveau : cochés d'un coup — ou décochés, s'ils l'étaient tous.
  const basculer = (cible) => {
    if (!cible.length) return;
    const tous = cible.every(e => SELECTION_RACK.ids.has(e.id));
    cible.forEach(e => (tous ? SELECTION_RACK.ids.delete(e.id) : SELECTION_RACK.ids.add(e.id)));
    ouvrirRack(nom, emps);
  };
  zone.querySelectorAll('[data-col]').forEach(b => b.onclick = () =>
    basculer(liste.filter(e => String(e.colonne) === b.dataset.col)));
  zone.querySelectorAll('[data-niv]').forEach(b => b.onclick = () =>
    basculer(liste.filter(e => String(e.niveau) === b.dataset.niv)));
  const supp = $('#rSupp');
  if (supp) supp.onclick = () => ouvrirSuppressionRack(nom);
}

/** La barre qui compte les cases cochées, et ce qu'on peut en faire : régler
    ce qu'elles rangent, ou les supprimer — chaque bouton selon sa case. */
function barreSelection(total, nbMP = 0) {
  const n = SELECTION_RACK.ids.size;
  // « Codes acceptés » ne concerne que les emplacements MP : éteint tant
  // qu'aucun n'est coché, et il le dit.
  return `<div class="selbar">
    <div class="sel-n">${n === 0 ? 'Touchez les emplacements à sélectionner'
      : `${n} emplacement${n > 1 ? 's' : ''} sélectionné${n > 1 ? 's' : ''}${
        nbMP && nbMP < n ? ` · dont ${nbMP} MP` : ''}`}</div>
    ${peut('empl_regler') ? `<div class="row">
      <button class="btn" id="selUsage" style="margin-top:0"${n ? '' : ' disabled'}
        >${icon('cog', 17)} Ce qu’ils rangent</button>
      <button class="btn" id="selCodes" style="margin-top:0"${nbMP ? '' : ' disabled'}
        title="${nbMP ? 'Réserver ces emplacements à certains codes' : 'Pour les emplacements MP seulement'}"
        >${icon('couches', 17)} Codes acceptés</button>
    </div>` : ''}
    <div class="row" style="margin-top:8px">
      <button class="btn ghost" id="selTout" style="margin-top:0"${n >= total ? ' disabled' : ''}
        >Tout le rack</button>
      <button class="btn ghost" id="selVider" style="margin-top:0"${n ? '' : ' disabled'}
        >Tout décocher</button>
    </div>
    ${peut('empl_creer') ? `<div class="row" style="margin-top:8px">
      <button class="btn danger" id="selSupp" style="margin-top:0"${n ? '' : ' disabled'}
        >${icon('trash', 17)} Supprimer</button>
    </div>` : ''}
  </div>`;
}

/* --- Ce que rangent les emplacements : cabines, cartons, vitrages ----------
   Le geste se fait en nombre — une colonne, un niveau, le rack — parce que
   c'est ainsi qu'on organise un entrepôt : « le sol de AH prend les chevalets
   de verre ». Le serveur dit d'abord ce qui changera, ce qui l'est déjà, et ce
   qui résiste — une cabine ou une palette encore posée — en le nommant.
   L'application ne déplace rien : elle applique aux emplacements libres, et
   laisse les autres tels quels, sous les yeux de l'opérateur.               */
async function ouvrirUsageSelection(nom) {
  const ids = [...SELECTION_RACK.ids];
  if (!ids.length) return;
  const n = ids.length;
  const corps = modale(`Ce que range${n > 1 ? 'nt' : ''} ${n} emplacement${n > 1 ? 's' : ''}`, `
    <div class="statuts">${CHOIX_USAGE.map(([c, titre, aide]) => `<button type="button" class="statut"
        data-choix="${c}" aria-pressed="false"><span class="n">${esc(titre)}</span>
        <span class="a">${esc(aide)}</span></button>`).join('')}</div>
    <div id="uBilan" style="margin-top:12px"></div>
    <div class="modal-actions">
      <button class="btn orange" id="uGo" type="button" disabled>Choisis ce qu’ils rangent</button>
      <button class="btn ghost" id="uNon" type="button">Annuler</button>
    </div>`);
  let choix = null;
  const appliquer = corps.querySelector('#uGo');
  const zoneBilan = corps.querySelector('#uBilan');
  corps.querySelector('#uNon').onclick = fermerModale;
  corps.querySelectorAll('[data-choix]').forEach(b => b.onclick = async () => {
    choix = b.dataset.choix;
    corps.querySelectorAll('[data-choix]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    appliquer.disabled = true;
    appliquer.textContent = 'Analyse…';
    try {
      const bilan = await api('/emplacements/usage/', { method: 'POST', body: { ids, choix, apercu: true } });
      if (choix !== b.dataset.choix) return;           // un autre choix entre-temps
      zoneBilan.innerHTML = bilanUsageHTML(bilan);
      const k = bilan.changes.length;
      appliquer.disabled = !k;
      appliquer.textContent = k ? `Appliquer à ${k} emplacement${k > 1 ? 's' : ''}` : 'Rien à changer';
    } catch (e) {
      zoneBilan.innerHTML = `<div class="aide alerte">${esc(e.message)}</div>`;
      appliquer.textContent = 'Choisis ce qu’ils rangent';
    }
  });
  appliquer.onclick = async () => {
    if (!choix) return;
    appliquer.disabled = true;
    try {
      const r = await api('/emplacements/usage/', { method: 'POST', body: { ids, choix } });
      fermerModale();
      const k = r.changes.length, b = r.bloques.length;
      toast(`${k} emplacement${k > 1 ? 's' : ''} : ${r.libelle}`
            + (b ? ` — ${b} laissé${b > 1 ? 's' : ''} tel${b > 1 ? 's' : ''} quel${b > 1 ? 's' : ''}` : ''), 'ok');
      // La sélection est consommée, comme après une suppression.
      SELECTION_RACK = { rack: nom, actif: false, ids: new Set() };
      await rafraichirEmplacements();
      renderEmplacements();
    } catch (e) { appliquer.disabled = false; toast(e.message, 'err'); }
  };
}

function bilanUsageHTML(b) {
  const morceaux = [];
  if (b.changes.length) {
    morceaux.push(`<div class="banner fait" style="margin:0 0 8px">${b.changes.length} emplacement${
      b.changes.length > 1 ? 's passeront' : ' passera'} en « ${esc(b.libelle)} ».</div>`);
  }
  if (b.deja.length) {
    morceaux.push(`<div class="meta">${b.deja.length} ${b.deja.length > 1 ? 'le sont' : 'l’est'} déjà :
      ${esc(b.deja.slice(0, 10).join(', '))}${b.deja.length > 10 ? '…' : ''}</div>`);
  }
  if (b.bloques.length) {
    morceaux.push(`<div class="banner" style="margin:10px 0 0">${b.bloques.length} ne
        ${b.bloques.length > 1 ? 'peuvent' : 'peut'} pas changer — ${b.bloques.length > 1 ? 'ils restent' : 'il reste'} tel${
        b.bloques.length > 1 ? 's' : ''} quel${b.bloques.length > 1 ? 's' : ''} :</div>
      <div class="list">${b.bloques.slice(0, 6).map(x => `<div class="item" style="cursor:default">
        <div class="r">${esc(x.code)}</div><div class="d">${esc(x.message)}</div></div>`).join('')}
        ${b.bloques.length > 6 ? `<div class="meta">… et ${b.bloques.length - 6} autre(s).</div>` : ''}</div>`);
  }
  return morceaux.join('');
}

/* --- Codes acceptés : réserver des emplacements MP à certains codes --------
   Un emplacement MP accepte toute sa famille, jusqu'à ce qu'on le réserve à
   un ou plusieurs codes : « le sol de AH ne prend que les VITR.445 ». À
   l'unité, cela se règle dans la fiche de l'emplacement ; ici, en nombre,
   pour une sélection — chaque emplacement prenant les codes de SA famille.
   Comme pour l'usage, le serveur dit d'abord ce qui changera, ce qui l'est
   déjà, ce qui résiste ; et ce qui est déjà posé reste où il est.          */
const MODES_CODES = [
  ['remplacer', 'Réserver à des codes précis',
   'Seuls les codes choisis pourront y entrer. Une réservation existante est remplacée.'],
  ['ajouter', 'Ajouter des codes à leur réservation',
   'Les codes déjà acceptés le restent ; ceux-ci s’y ajoutent.'],
  ['tous', 'Accepter de nouveau tous les codes',
   'Retire la réservation : tout code de leur famille peut y entrer.'],
];

/** Ce que fera le réglage, en une phrase — d'après le bilan du serveur. */
function phraseCodes(b) {
  const k = b.changes.length;
  if (!k) return '';
  const emp = `${k} emplacement${k > 1 ? 's' : ''}`;
  const codes = listeCodes(b.codes || [], 4);
  if (b.mode === 'tous') return `${emp} accepter${k > 1 ? 'ont' : 'a'} de nouveau tous les codes de leur famille.`;
  if (b.mode === 'ajouter') {
    return `${codes} ${(b.codes || []).length > 1 ? 's’ajoutent' : 's’ajoute'} à la réservation de ${emp}.`;
  }
  return `${emp} ser${k > 1 ? 'ont réservés' : 'a réservé'} à ${codes}.`;
}

/** Ceux que le réglage ne change pas, dits selon le geste : « ajouter » à un
    emplacement ouvert à toute sa famille ne change rien — il les accepte
    déjà. */
function phraseDejaCodes(b) {
  const n = b.deja.length;
  if (!n) return '';
  const quoi = b.mode === 'tous' ? (n > 1 ? 'acceptent déjà tous les codes' : 'accepte déjà tous les codes')
    : b.mode === 'ajouter' ? (n > 1 ? 'les acceptent déjà' : 'les accepte déjà')
    : (n > 1 ? 'le sont déjà' : 'l’est déjà');
  return `${n} ${quoi} : ${b.deja.slice(0, 10).join(', ')}${n > 10 ? '…' : ''}`;
}

function bilanCodesHTML(b) {
  const morceaux = [];
  if (b.changes.length) {
    morceaux.push(`<div class="banner fait" style="margin:0 0 8px">${esc(phraseCodes(b))}</div>`);
  }
  if (b.deja.length) {
    morceaux.push(`<div class="meta">${esc(phraseDejaCodes(b))}</div>`);
  }
  if (b.hors_reservation && b.hors_reservation.length) {
    morceaux.push(`<div class="aide alerte" style="margin-top:10px">Déjà posés et plus acceptés après le
        réglage — ils restent où ils sont, peuvent sortir ou changer d’emplacement, et la cloche les
        signale : ${esc(b.hors_reservation.slice(0, 4).map(x => `${x.code} (${listeCodes(x.codes)})`).join(' · '))}${
        b.hors_reservation.length > 4 ? '…' : ''}</div>`);
  }
  if (b.bloques.length) {
    morceaux.push(`<div class="banner" style="margin:10px 0 0">${b.bloques.length} ne
        ${b.bloques.length > 1 ? 'changent' : 'change'} pas :</div>
      <div class="list">${b.bloques.slice(0, 6).map(x => `<div class="item" style="cursor:default">
        <div class="r">${esc(x.code)}</div><div class="d">${esc(x.message)}</div></div>`).join('')}
        ${b.bloques.length > 6 ? `<div class="meta">… et ${b.bloques.length - 6} autre(s).</div>` : ''}</div>`);
  }
  return morceaux.join('');
}

/** Le choix des codes : une saisie qui propose, et les codes retenus en
    pastilles qu'on retire d'une touche. `familles` resserre la recherche. */
function brancherChoixCodes(racine, familles, choisis, surChangement) {
  const champ = racine.querySelector('[data-codes-saisie]');
  const boite = racine.querySelector('[data-codes-sugg]');
  const pastilles = racine.querySelector('[data-codes-choisis]');
  let propositions = [];
  const dessiner = () => {
    pastilles.innerHTML = choisis.map(a => `<span class="chip fixe"><span class="code-mp">${esc(a.code)}</span>
      <button type="button" class="chip-x" data-retirer="${a.id}" aria-label="Retirer ${esc(a.code)}">${icon('close', 14)}</button></span>`).join('');
    pastilles.querySelectorAll('[data-retirer]').forEach(b => b.onclick = () => {
      const i = choisis.findIndex(a => String(a.id) === b.dataset.retirer);
      if (i >= 0) choisis.splice(i, 1);
      dessiner();
      surChangement();
    });
  };
  champ.oninput = debounce(async () => {
    const t = champ.value.trim();
    if (!cleMP(t)) { boite.innerHTML = ''; propositions = []; return; }
    try {
      const famille = familles.length === 1 ? `famille=${encodeURIComponent(familles[0])}&` : '';
      propositions = (await api(`/mp/suggestions/?${famille}q=${encodeURIComponent(t)}`))
        .filter(a => !choisis.some(c => c.id === a.id));
      if (champ.value.trim() !== t) return;
      boite.innerHTML = propositions.slice(0, 6).map(a => `<div class="item sugg-mp" data-art="${a.id}">
          <div class="r"><span class="code-mp">${esc(a.code)}</span>${badgeAncienne(a)}</div>
          <div class="d">${sousTitreArticle(a)}</div></div>`).join('')
        || `<div class="empty" style="padding:12px">Aucun code de la base ne ressemble à « ${esc(t)} ».</div>`;
      boite.querySelectorAll('[data-art]').forEach(n => n.onclick = () => {
        const a = propositions.find(x => String(x.id) === n.dataset.art);
        if (!a) return;
        choisis.push(a);
        champ.value = '';
        boite.innerHTML = '';
        dessiner();
        surChangement();
        champ.focus();
      });
    } catch (e) { boite.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }, 160);
  dessiner();
}

async function ouvrirCodesSelection(nom, liste) {
  const ids = [...SELECTION_RACK.ids];
  if (!ids.length) return;
  const familles = [...new Set(liste.filter(e => e.est_mp && SELECTION_RACK.ids.has(e.id)).map(e => e.usage))];
  const n = ids.length;
  const exemple = familles.length === 1 ? FAMILLES_MP[familles[0]].exemple : 'Ex. vitr.445 ou C8.FD';
  const corps = modale(`Codes acceptés — ${n} emplacement${n > 1 ? 's' : ''}`, `
    <div class="statuts">${MODES_CODES.map(([m, titre, aide]) => `<button type="button" class="statut"
        data-mode="${m}" aria-pressed="false"><span class="n">${esc(titre)}</span>
        <span class="a">${esc(aide)}</span></button>`).join('')}</div>
    <div id="cCodes" hidden>
      <label for="cSaisie">Les codes</label>
      <div class="chips" data-codes-choisis></div>
      <input id="cSaisie" data-codes-saisie placeholder="${esc(exemple)}" autocomplete="off"
             autocapitalize="characters" spellcheck="false">
      <div class="list" data-codes-sugg></div>
      ${familles.length > 1 ? `<div class="aide">La sélection mêle vitrages et cartons : chaque
        emplacement prendra les codes de sa famille.</div>` : ''}
    </div>
    <div id="cBilan" style="margin-top:12px"></div>
    <div class="modal-actions">
      <button class="btn orange" id="cGo" type="button" disabled>Choisis le réglage</button>
      <button class="btn ghost" id="cNon" type="button">Annuler</button>
    </div>`);
  let mode = null;
  const choisis = [];
  const appliquer = corps.querySelector('#cGo');
  const zoneBilan = corps.querySelector('#cBilan');
  const zoneCodes = corps.querySelector('#cCodes');
  corps.querySelector('#cNon').onclick = fermerModale;
  let demande = 0;
  const apercu = debounce(async () => {
    if (!mode) return;
    if (mode !== 'tous' && !choisis.length) {
      zoneBilan.innerHTML = '';
      appliquer.disabled = true;
      appliquer.textContent = 'Choisis au moins un code';
      return;
    }
    const ici = ++demande;
    appliquer.disabled = true;
    appliquer.textContent = 'Analyse…';
    try {
      const bilan = await api('/emplacements/codes/', { method: 'POST', body: {
        ids, articles: choisis.map(a => a.id), mode, apercu: true } });
      if (ici !== demande) return;                      // un autre réglage entre-temps
      zoneBilan.innerHTML = bilanCodesHTML(bilan);
      const k = bilan.changes.length;
      appliquer.disabled = !k;
      appliquer.textContent = k ? `Appliquer à ${k} emplacement${k > 1 ? 's' : ''}` : 'Rien à changer';
    } catch (e) {
      if (ici !== demande) return;
      zoneBilan.innerHTML = `<div class="aide alerte">${esc(e.message)}</div>`;
      appliquer.textContent = 'Choisis le réglage';
    }
  }, 200);
  // Le bouton s'éteint DÈS que la demande change : pendant le délai de
  // l'aperçu, il appliquerait sinon un réglage que personne n'a vu.
  const changer = () => {
    appliquer.disabled = true;
    appliquer.textContent = 'Analyse…';
    apercu();
  };
  brancherChoixCodes(zoneCodes, familles, choisis, changer);
  corps.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => {
    mode = b.dataset.mode;
    corps.querySelectorAll('[data-mode]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    zoneCodes.hidden = mode === 'tous';
    if (mode !== 'tous') corps.querySelector('#cSaisie').focus();
    changer();
  });
  appliquer.onclick = async () => {
    if (!mode) return;
    appliquer.disabled = true;
    try {
      const r = await api('/emplacements/codes/', { method: 'POST', body: {
        ids, articles: choisis.map(a => a.id), mode } });
      fermerModale();
      const k = r.changes.length, b = r.bloques.length;
      toast(`${k} emplacement${k > 1 ? 's' : ''} : ${r.libelle}`
            + (b ? ` — ${b} laissé${b > 1 ? 's' : ''} tel${b > 1 ? 's' : ''} quel${b > 1 ? 's' : ''}` : ''), 'ok');
      chargerAlertes();
      SELECTION_RACK = { rack: nom, actif: false, ids: new Set() };
      await rafraichirEmplacements();
      renderEmplacements();
    } catch (e) { appliquer.disabled = false; toast(e.message, 'err'); }
  };
}

/** Dans la fiche d'un emplacement MP : les codes qu'il accepte, et de quoi
    en ajouter ou en retirer — chaque geste s'enregistre aussitôt. */
function blocCodesAcceptes(e, gerer) {
  if (!e.est_mp) return '';
  const fam = FAMILLES_MP[e.usage] || FAMILLES_MP.vitrage;
  const codes = e.codes_acceptes || [];
  return `<div class="sec" style="margin-top:18px">Codes acceptés</div>
    <div class="card" id="fCodes">
      ${codes.length
        ? `<div class="meta" style="margin-top:0">Seul${codes.length > 1 ? 's ces codes entrent' : ' ce code entre'}
             en ${esc(e.code)} :</div>
           <div class="chips" style="margin:8px 0 0">${codes.map(a => `<span class="chip fixe"><span class="code-mp">${
             esc(a.code)}</span>${gerer ? `<button type="button" class="chip-x" data-retirer="${a.id}"
             aria-label="Retirer ${esc(a.code)}">${icon('close', 14)}</button>` : ''}</span>`).join('')}</div>`
        : `<div class="meta" style="margin-top:0">Tous les ${esc(fam.plusieurs)} de la base peuvent y entrer.</div>`}
      ${gerer ? `<label for="fCodeAjout">${codes.length ? 'Ajouter un code' : 'Le réserver à un code'}</label>
        <input id="fCodeAjout" placeholder="${esc(fam.exemple)}" autocomplete="off"
               autocapitalize="characters" spellcheck="false">
        <div class="list" id="fCodeSugg"></div>
        <div class="aide">${codes.length ? '' : 'Réservé, il refusera les autres codes. '}Ce qui y est
          déjà posé reste où il est : il peut toujours sortir ou changer d’emplacement.</div>
        <div id="fCodesBilan"></div>
        ${codes.length ? `<button type="button" class="btn ghost" id="fCodesTous">Accepter de nouveau
          tous les ${esc(fam.plusieurs)}</button>` : ''}` : ''}
    </div>`;
}

function brancherCodesAcceptes(e, redessiner) {
  const carte = document.getElementById('fCodes');
  if (!carte || !peut('empl_regler')) return;
  const codes = (e.codes_acceptes || []).slice();
  // Un enregistrement à la fois : chaque geste envoie la liste ENTIÈRE, et
  // deux retraits rapides partiraient chacun d'une liste où l'autre code est
  // encore — le second remettrait le premier.
  const figer = (oui) => carte.querySelectorAll('button, input').forEach(n => { n.disabled = oui; });
  const enregistrer = async (articles, phrase) => {
    figer(true);
    try {
      const r = await api('/emplacements/codes/', { method: 'POST', body: {
        ids: [e.id], articles, mode: articles.length ? 'remplacer' : 'tous' } });
      toast(phrase, 'ok');
      chargerAlertes();
      await rafraichirEmplacements();
      await redessiner();
      const restants = (r.hors_reservation || [])[0];
      const zone = document.getElementById('fCodesBilan');
      if (restants && zone) {
        zone.innerHTML = `<div class="aide alerte">Encore posé${restants.codes.length > 1 ? 's' : ''} ici et
          plus accepté${restants.codes.length > 1 ? 's' : ''} : ${esc(listeCodes(restants.codes))}. Il${
          restants.codes.length > 1 ? 's restent' : ' reste'} là jusqu’à ce qu’on le${
          restants.codes.length > 1 ? 's' : ''} sorte ou change d’emplacement ; la cloche le signale.</div>`;
      }
    } catch (err) { figer(false); toast(err.message, 'err'); }
  };
  carte.querySelectorAll('[data-retirer]').forEach(b => b.onclick = () => {
    const retire = codes.find(a => String(a.id) === b.dataset.retirer);
    const reste = codes.filter(a => a !== retire);
    enregistrer(reste.map(a => a.id), reste.length
      ? `${retire.code} retiré : ${e.code} accepte ${listeCodes(reste.map(a => a.code))}`
      : `${e.code} accepte de nouveau tous les codes`);
  });
  const tous = carte.querySelector('#fCodesTous');
  if (tous) {
    tous.onclick = async () => {
      const ok = await confirmer({
        titre: `Ouvrir ${e.code} à tous les codes ?`,
        texte: `La réservation est retirée : tout ${(FAMILLES_MP[e.usage] || {}).un || 'code'} de la base pourra y entrer.`,
        ok: 'Accepter tous les codes',
      });
      if (ok) enregistrer([], `${e.code} accepte de nouveau tous les codes`);
    };
  }
  const champ = carte.querySelector('#fCodeAjout');
  const boite = carte.querySelector('#fCodeSugg');
  let propositions = [];
  champ.oninput = debounce(async () => {
    const t = champ.value.trim();
    if (!cleMP(t)) { boite.innerHTML = ''; propositions = []; return; }
    try {
      propositions = (await api(`/mp/suggestions/?famille=${encodeURIComponent(e.usage)}&q=${encodeURIComponent(t)}`))
        .filter(a => !codes.some(c => c.id === a.id));
      if (champ.value.trim() !== t) return;
      boite.innerHTML = propositions.slice(0, 6).map(a => `<div class="item sugg-mp" data-art="${a.id}">
          <div class="r"><span class="code-mp">${esc(a.code)}</span>${badgeAncienne(a)}</div>
          <div class="d">${sousTitreArticle(a)}</div></div>`).join('')
        || `<div class="empty" style="padding:12px">Aucun code de la base ne ressemble à « ${esc(t)} ».</div>`;
      boite.querySelectorAll('[data-art]').forEach(n => n.onclick = () => {
        const a = propositions.find(x => String(x.id) === n.dataset.art);
        if (!a) return;
        const apres = codes.concat([a]);
        enregistrer(apres.map(x => x.id), `${e.code} réservé à ${listeCodes(apres.map(x => x.code))}`);
      });
    } catch (err) { boite.innerHTML = `<div class="empty">${esc(err.message)}</div>`; }
  }, 160);
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
  const detail = etat.cabines
    ? `${etat.cabines} cabine${etat.cabines > 1 ? 's' : ''} rangée${etat.cabines > 1 ? 's' : ''}` : '';
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
      compte d'emplacements et les cabines rangées ;
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
  ].filter(Boolean).join(' · ');

  const corps = etat.supprimable
    ? `<div class="banner">Le rack <b>${esc(etat.rack)}</b> et ses <b>${etat.emplacements}</b>
         emplacements vont être supprimés.<br>
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
  // Une fiche ne se redessine jamais toute seule : elle porte des formulaires —
  // réglages, entrée de matières premières. Sans ce nom d'écran à elle, le
  // rafraîchissement automatique rejouait l'écran des emplacements par-dessus,
  // et renvoyait au plan du rack au milieu d'une saisie.
  ECRAN = 'fiche-emplacement';
  // Toujours relire la fiche : `EMPS` est une photo prise au démarrage, et un
  // collègue a pu créer ou déplacer un emplacement depuis. Le formulaire
  // affichait alors « Sans zone » sur un emplacement zoné — et l'enregistrement
  // effaçait sa zone pour de bon.
  let e;
  try { e = await api(`/emplacements/${emp.id}/`); }
  catch (err) { toast(err.message, 'err'); return; }

  // Trois cases, trois blocs : régler (le formulaire, les codes acceptés),
  // mettre en service (l'emplacement, ses places), créer et supprimer.
  const regler = peut('empl_regler'), service = peut('empl_service');
  const supprimer = peut('empl_creer');
  const sup = e.suppression || {};

  layout(`
    <button class="btn ghost retour" id="fRetour">← Retour aux emplacements</button>
    <h2 class="title">${esc(e.code)} <span class="pill">${esc(e.est_mp ? e.usage_libelle : e.mode_libelle)}</span>${e.actif === false ? '<span class="etat crit">inactif</span>' : ''}</h2>
    <div id="zone"><div class="empty">Chargement…</div></div>
    <div class="sec" style="margin-top:18px">Réglages de l'emplacement</div>
    <div class="card">
      ${regler ? '' : `<div class="banner" style="margin-bottom:12px">Consultation seule : il faut la case
        « ${esc(libelleDroit('empl_regler'))} » pour modifier ces réglages.</div>`}
      <label for="fCode">Code</label>
      <input id="fCode" value="${esc(e.code)}" ${regler ? '' : 'disabled'} autocomplete="off" autocapitalize="characters">
      <div class="aide">Renommer l'emplacement rend obsolètes les étiquettes QR déjà collées : réimprimez-la juste après.</div>
      <label for="fMode">Ce qu’il range</label>
      <select id="fMode" ${regler ? '' : 'disabled'}>${optionsUsage(choixUsageDe(e))}</select>
      <div class="aide">${AIDE_MODE}${(e.nb_cabines || (e.mp && e.mp.lignes))
        ? ' <b>Ce réglage ne change que sur un emplacement vide.</b>' : ''}</div>
      <label for="fDesc">Description</label>
      <input id="fDesc" value="${esc(e.description || '')}" placeholder="facultatif" ${regler ? '' : 'disabled'}>
      ${e.est_mp ? '' : `<label class="case"><input type="checkbox" id="fStaging" ${e.staging ? 'checked' : ''} ${regler ? '' : 'disabled'}> Zone de réception (« à ranger »)</label>`}
      ${regler ? '<button class="btn orange" id="fOk">Enregistrer les modifications</button>' : ''}
    </div>
    ${blocCodesAcceptes(e, regler)}
    ${blocMiseEnService(e, service)}
    <div class="row actions-fiche" style="margin-top:12px">
      <button class="btn ghost" id="fEtiq">${icon('print', 17)} Imprimer l'étiquette QR</button>
      ${supprimer ? `<button class="btn danger" id="fSup" style="margin-top:14px">${icon('trash', 17)} Supprimer</button>` : ''}
    </div>
    ${supprimer && !sup.possible && sup.message ? `<div class="banner" style="margin-top:12px">${esc(sup.message)}</div>` : ''}`,
    'more');

  $('#fRetour').onclick = retour || renderEmplacements;
  $('#fEtiq').onclick = () => printLocationLabel(e.code);
  brancherMiseEnService(e, () => ficheEmplacement({ id: e.id }, retour));
  brancherCodesAcceptes(e, () => ficheEmplacement({ id: e.id }, retour));

  // Occupation + opérations de rangement : l'écran partagé avec le scanner.
  montrerEmplacement(e, { sansReglages: true });

  if (supprimer) $('#fSup').onclick = () => supprimerEmplacement(e, retour);
  if (!regler) return;

  $('#fOk').onclick = async () => {
    const code = $('#fCode').value.trim();
    if (!code) { toast('Le code est obligatoire.', 'err'); return; }
    const bouton = $('#fOk');
    bouton.disabled = true;
    try {
      // La case « à ranger » n'existe que pour les cabines : absente, on garde
      // la valeur d'avant plutôt que de l'effacer.
      const staging = $('#fStaging');
      await api(`/emplacements/${e.id}/`, { method: 'PATCH', body: {
        code,
        ...usageDeChoix($('#fMode').value, e),
        description: $('#fDesc').value.trim(),
        staging: staging ? staging.checked : Boolean(e.staging),
        // `actif` n'est PAS ici : il a ses règles et son propre geste, plus bas
        // dans l'écran. Le serveur le refuse d'ailleurs en lecture seule.
      } });
      toast('Emplacement enregistré', 'ok');
      await rafraichirEmplacements();
      ficheEmplacement({ id: e.id }, retour);
    } catch (err) { bouton.disabled = false; toast(err.message, 'err'); }
  };
}

/* --- Mise en service : l'emplacement, et chacune de ses deux places ---------
   Trois questions se posent devant un rack à moitié vide, et l'écran doit y
   répondre sans qu'on aille chercher : cet emplacement prend-il des cabines,
   sinon POURQUOI, et depuis quand. Un booléen seul n'en dit qu'un tiers.

   Condamner une place seule est le cas courant : un pilier devant la gauche de
   AC550 ne retire pas la droite du stock. Désactiver l'emplacement entier pour
   cela perdrait une place saine — et personne ne saurait laquelle des deux
   posait problème.                                                            */
function blocMiseEnService(e, gerer) {
  const inactif = e.actif === false;
  const quand = e.actif_le ? new Date(e.actif_le).toLocaleString('fr-FR') : null;
  const condamnees = e.places_condamnees || [];
  const parPlace = Object.fromEntries(condamnees.map(p => [p.place, p]));

  /* Les places ne sont proposées que pour un emplacement à places nommées :
     une aire à capacité illimitée n'en a pas, et le serveur le refuse. Un
     emplacement de matières premières en a trois. */
  const listePlaces = e.est_mp
    ? [{ code: 'G', libelle: 'Gauche' }, { code: 'M', libelle: 'Milieu' }, { code: 'D', libelle: 'Droite' }]
    : (REFS_CABINE.places || []);
  const places = (e.illimite && !e.est_mp) ? '' : `
    <div class="sec">${e.est_mp ? 'Les trois places' : 'Les deux places'}</div>
    <div class="meta" style="margin:-2px 0 8px">${e.est_mp
      ? 'Une place condamnée ne prend plus rien ; les autres continuent.'
      : 'Une place condamnée ne prend plus de cabine ; l’autre continue.'} Pour retirer
      l'emplacement entier, utilisez « hors service » ci-dessus.</div>
    <div class="list">${listePlaces.map(({ code, libelle }) => {
      const c = parPlace[code];
      return `<div class="item" style="cursor:default">
        <div class="r">${esc(code)} — ${esc(libelle)} ${c
          ? '<span class="etat hs">condamnée</span>'
          : '<span class="etat ok">en service</span>'}</div>
        ${c ? `<div class="meta">${esc(c.motif)}${c.cree_par ? ' — ' + esc(c.cree_par) : ''}${
          c.cree_le ? ', le ' + new Date(c.cree_le).toLocaleDateString('fr-FR') : ''}</div>` : ''}
        ${gerer ? `<button class="btn ${c ? 'ghost' : 'danger'}" data-place="${esc(code)}"
          data-cond="${c ? '0' : '1'}" style="margin-top:8px">${c
            ? 'Remettre cette place en service' : 'Condamner cette place'}</button>` : ''}
      </div>`;
    }).join('')}</div>`;

  return `<div class="sec" style="margin-top:18px">Mise en service</div>
    <div class="card">
      <div class="r" style="font-size:16px;font-weight:700">${esc(e.code)} est
        ${inactif ? '<span class="etat hs">hors service</span>'
                  : '<span class="etat ok">en service</span>'}</div>
      ${inactif
        ? `<div class="meta" style="margin-top:5px">${e.motif_inactif
              ? esc(e.motif_inactif) : 'Aucun motif enregistré.'}${
            e.actif_par_nom ? ' — ' + esc(e.actif_par_nom) : ''}${quand ? ', le ' + esc(quand) : ''}</div>
           <div class="meta" style="margin-top:5px">Il garde son historique et reste
             consultable, mais ${e.est_mp ? 'plus rien ne peut y être posé' : 'aucune cabine ne peut plus y être rangée'}.</div>`
        : `<div class="meta" style="margin-top:5px">${e.est_mp
             ? 'Les matières premières peuvent y être posées.'
             : 'Les cabines peuvent y être rangées.'}${quand ? ' Remis en service le ' + esc(quand) + '.' : ''}</div>`}
      ${gerer ? `<button class="btn ${inactif ? 'orange' : 'danger'}" id="fBascule">${
        inactif ? 'Remettre en service' : 'Mettre hors service'}</button>` : ''}
      ${places}
    </div>`;
}

function brancherMiseEnService(e, redessiner) {
  const bascule = $('#fBascule');
  if (bascule) {
    bascule.onclick = async () => {
      const inactif = e.actif === false;
      /* Remettre en service ne demande rien : constater qu'un obstacle a
         disparu n'a pas à s'expliquer. Le retirer du stock, si — sans motif
         écrit, personne ne saura six mois plus tard s'il faut le rouvrir. */
      let motif = '';
      if (!inactif) {
        const rep = await confirmer({
          titre: 'Mettre ' + e.code + ' hors service ?',
          texte: (e.est_mp ? 'Plus rien ne pourra y être posé. ' : 'Plus aucune cabine ne pourra y être rangée. ')
               + 'L’historique est conservé, et le geste se défait.',
          ok: 'Mettre hors service', danger: true,
          champ: { libelle: 'Pourquoi ?', placeholder: 'Ex. rack démonté, pilier devant',
                   obligatoire: true,
                   manque: 'Sans motif, personne ne saura s’il faut le rouvrir.' },
        });
        if (!rep || !rep.ok) return;
        motif = rep.valeur;
      }
      bascule.disabled = true;
      try {
        await api(`/emplacements/${e.id}/activation/`, { method: 'POST',
          body: { actif: inactif, motif } });
        toast(`${e.code} ${inactif ? 'remis en service' : 'mis hors service'}`, 'ok');
        await rafraichirEmplacements();
        redessiner();
      } catch (err) { bascule.disabled = false; toast(err.message, 'err'); }
    };
  }

  document.querySelectorAll('[data-place][data-cond]').forEach(b => {
    b.onclick = async () => {
      const condamnee = b.dataset.cond === '1';
      const place = b.dataset.place;
      let motif = '';
      if (condamnee) {
        const rep = await confirmer({
          titre: `Condamner la place ${place} de ${e.code} ?`,
          texte: e.est_mp ? 'Cette place ne prendra plus rien. Les autres continuent.'
                          : 'Cette place ne prendra plus de cabine. L’autre continue.',
          ok: 'Condamner', danger: true,
          champ: { libelle: 'Pourquoi ?', placeholder: 'Ex. pilier, montant tordu',
                   obligatoire: true,
                   manque: 'Sans motif, personne ne saura s’il faut la rouvrir.' },
        });
        if (!rep || !rep.ok) return;
        motif = rep.valeur;
      }
      b.disabled = true;
      try {
        await api(`/emplacements/${e.id}/place/`, { method: 'POST',
          body: { place, condamnee, motif } });
        toast(`Place ${place} ${condamnee ? 'condamnée' : 'remise en service'}`, 'ok');
        await rafraichirEmplacements();
        redessiner();
      } catch (err) { b.disabled = false; toast(err.message, 'err'); }
    };
  });
}

/* Suppression d'un emplacement. Deux issues, toutes deux explicites :
   - vide : confirmation, puis suppression définitive ;
   - des cabines y sont rangées : refus, avec le geste à faire (les déplacer
     ou les envoyer). Le serveur le dit dans `suppression.message`.          */
async function supprimerEmplacement(e, retour) {
  const sup = e.suppression || {};
  if (!sup.possible) {
    await confirmer({
      titre: 'Suppression impossible',
      texte: sup.message || 'Cet emplacement ne peut pas être supprimé pour le moment.',
      ok: 'J\'ai compris', annuler: null,
    });
    return;
  }
  const ok = await confirmer({
    titre: 'Supprimer ' + e.code + ' ?',
    texte: `L'emplacement ${e.code} est vide. Le supprimer est définitif ; le journal des cabines garde son code.`,
    ok: 'Supprimer définitivement', danger: true,
  });
  if (!ok) return;
  try {
    await api(`/emplacements/${e.id}/`, { method: 'DELETE' });
    toast('Emplacement ' + e.code + ' supprimé', 'ok');
    await rafraichirEmplacements();
    (retour || renderEmplacements)();
  } catch (err) { toast(err.message, 'err'); }
}

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

/* --- Onglet Entrée : ajouter une cabine ------------------------------------
   La fiche imprimée en production ne porte aucun code : on la recopie une fois,
   puis on imprime une étiquette QR à coller. C'est cette étiquette qui rend les
   scans suivants possibles — la saisie n'a lieu qu'à l'entrée, jamais après.

   La photo de la fiche part au serveur (`/cabines/lire-fiche/`), qui en lit le
   texte et pré-remplit le formulaire ; rien ne s'enregistre sans relecture.   */

const CHAMPS_ENTREE = [
  ['numero', 'N° de cabine (REF. CABINE) *', 'Ex. 26_03_47'],
  ['chantier', 'N° de commande / chantier *', 'Ex. 251280 ou 251280-1'],
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
  if (!peut('cab_ranger')) {
    layout(`<h2 class="title">Entrée d'une cabine</h2>
      <div class="banner">${esc(sansLeDroit('cab_ranger'))}</div>`, 'entree');
    return;
  }
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
  if (!peut('hors_fichier')) {
    etat.innerHTML = '';
    blocRefusHorsFichier(numero);
    return;
  }
  etat.innerHTML = `<div class="banner"><b>${esc(numero)}</b> n’est pas annoncée par le
    fichier de production. Ton compte peut la créer quand même — dis pourquoi, ce
    sera écrit au journal.</div>`;
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
    ${a.chantier_a_saisir ? `<div class="banner" style="margin-top:12px">${a.chantier_brut
        ? `Le fichier porte le chantier « ${esc(a.chantier_brut)} », que le WMS ne sait
           pas enregistrer tel quel. Saisis-le.`
        : 'Le fichier ne donne aucun n° de chantier pour cette cabine. Sans lui, '
          + 'elle ne peut pas être enregistrée.'}</div>
      ${CHAMPS_CHANTIER}` : ''}
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
    if ($('#eChantier')) corps.chantier = lireChantierSaisi();
    if (chantierRefuse(corps.chantier)) return;
    bouton.disabled = true;
    try {
      await creerCabine(corps);
    } catch (e) { bouton.disabled = false; toast(e.message, 'err'); }
  };
}

/** Cabine absente du fichier, compte sans la case qui l'autorise : c'est un refus.

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
      cabine n’y figure pas. Dans les deux cas, c’est une personne qui a le droit
      « ${esc(libelleDroit('hors_fichier'))} » qui tranche — un administrateur l’a :
      préviens-la avec ce numéro.</div>
    <button class="btn ghost" id="eAutre">Une autre cabine</button>
  </div>`;
  $('#eAutre').onclick = renderEntree;
}

/** Chemin manuel : photo de la fiche puis relecture des champs. Réservé, dès
    qu'un fichier de production est importé, aux comptes qui ont la case
    « enregistrer une cabine absente du fichier », et alors avec un motif —
    c'est le serveur qui l'exige, cet écran ne fait que le demander. */
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
  if (chantierRefuse(corps.chantier)) return;
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

/* --- Ranger une cabine : UN écran, trois façons d'y désigner l'emplacement ---
   Ce geste vivait en trois endroits qui se ressemblaient : dans la fiche de la
   cabine (trois boutons et leurs fermetures), dans le bloc affiché après une
   création, et derrière le scan. Deux défauts en sont sortis :

   - « Saisir le code », après une création, ouvrait la FICHE de la cabine — où
     il fallait appuyer sur « Saisir le code » une seconde fois. Le libellé
     promettait un champ et livrait un détour ;
   - les gestes s'écrivaient sous le formulaire de création, donc sous
     quarante-trois caractéristiques à dérouler.

   D'où cet écran unique, qui est un ÉCRAN (`layout`) et non un bloc ajouté en
   bas : le bouton « retour » du navigateur y fonctionne, et il s'ouvre en haut.
   Le champ de code est posé et focalisé d'emblée — c'est la voie la plus
   courante quand la caméra ne sert pas, et la faire mériter un appui de plus
   n'apporte rien. */
async function ecranRangement(cabine, retour) {
  if (refuseSansDroit('cab_ranger')) return;
  const revenir = retour || (() => ficheCabine(cabine));
  const deja = (cabine.occupations || []).some(o => o.emplacement);

  layout(`<button class="btn ghost retour" id="rgRetour">← Retour</button>
    <h2 class="title">${deja ? 'Changer d’emplacement' : 'Ranger la cabine'}</h2>
    <div class="card">
      <div class="r" style="font-size:17px;font-weight:700">${esc(cabine.numero)}</div>
      <div class="meta" style="margin-top:3px">Chantier ${cabine.chantier
        ? esc(cabine.chantier) : '<em>à affecter</em>'}${
        cabine.modele ? ' · ' + esc(cabine.modele) : ''}</div>
      ${deja ? `<div class="meta" style="margin-top:5px">Actuellement : <b>${
        esc(ouEstLaCabine(cabine))}</b>. La ranger ailleurs libère cette place.</div>` : ''}
    </div>

    <div class="card" style="margin-top:12px">
      <div class="sec" style="margin-top:0">Où la posez-vous ?</div>
      <label for="rgCode">Code de l'emplacement</label>
      <input id="rgCode" placeholder="Ex. AC550" autocomplete="off"
             autocapitalize="characters" spellcheck="false">
      <div class="meta" style="margin-top:6px">Tapez les premières lettres : la
        liste se réduit à mesure. Ou scannez l'étiquette QR du rack.</div>
      <div class="list" id="rgResultats"></div>
      <button class="btn orange" id="rgProposer">${icon('search', 17)} Proposer un emplacement</button>
      <div class="meta" style="margin-top:5px">Le WMS cherche une place où ce
        modèle tient vraiment, en tenant compte de son gabarit.</div>
      <button class="btn ghost" id="rgScan">${icon('scan', 17)} Scanner l’emplacement</button>
      <button class="btn ghost" id="rgListe">Voir tous les emplacements</button>
      <div id="rgZone"></div>
    </div>`, ongletCourant());

  $('#rgRetour').onclick = revenir;
  // Retient la cabine, puis renvoie au scanner : le scan de l'emplacement la range.
  $('#rgScan').onclick = () => { CABINE_A_RANGER = cabine; go('trouver'); };

  const champ = $('#rgCode');
  champ.focus();
  champ.oninput = debounce(() => chercherEmplacements(cabine, champ.value.trim(), revenir), 250);
  champ.onkeydown = (ev) => {
    /* Entrée sur un code complet : au poste on tape « AC550 » et on valide, on
       ne cherche pas l'élément d'une liste à la souris. On prend le premier
       résultat SEULEMENT s'il n'y en a qu'un — sinon on choisirait pour la
       personne, ce qui est exactement l'erreur qu'on a corrigée sur les places. */
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    const items = document.querySelectorAll('#rgResultats [data-e]');
    if (items.length === 1) items[0].click();
  };

  $('#rgListe').onclick = () => listerEmplacements(cabine, revenir);
  $('#rgProposer').onclick = () => proposerEmplacement(cabine, revenir, 0);
}


/** « Où est-ce que celle-ci rentre ? » — la question qu'on pose devant le rack.

    Personne ne connaît par cœur l'état de deux cents emplacements, et encore
    moins lesquels acceptent un grand modèle. Le WMS, lui, le sait : le serveur
    classe les emplacements possibles et rend le meilleur en tête (voir
    `services_cabines.emplacements_pour`). `saut` permet d'en demander un autre —
    la proposition n'est pas un ordre, l'entrepôt a ses raisons qu'un écran
    ignore (une allée encombrée, un camion qui arrive). */
async function proposerEmplacement(cabine, revenir, saut = 0) {
  const zone = $('#rgZone');
  if (!zone) return;
  zone.innerHTML = '<div class="empty">Recherche d’un emplacement…</div>';
  let d;
  try {
    d = await api(`/emplacements/pour_cabine/?cabine=${cabine.id}`);
  } catch (e) { zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

  const possibles = (d.emplacements || []).filter(e => e.possible);
  if (!possibles.length) {
    /* Aucun emplacement : le dire, et dire pourquoi. « Rien trouvé » tout seul
       laisse chercher à la main ce que le WMS vient de ne pas trouver. */
    const grand = d.cabine && d.cabine.tout_l_emplacement;
    zone.innerHTML = `<div class="banner">
      <b>Aucun emplacement ne peut prendre ${esc(cabine.numero)}.</b><br>
      ${grand ? `Ce modèle (${esc(d.cabine.modele || '')}) prend l’emplacement
        ENTIER : il lui faut un emplacement dont les deux places sont libres, et
        il n’en reste aucun.`
       : 'Toutes les places sont occupées ou condamnées.'}
      <br>Sortez une cabine, ou remettez un emplacement en service.</div>`;
    return;
  }

  const rang = ((saut % possibles.length) + possibles.length) % possibles.length;
  const choisi = possibles[rang];
  ouvrirPlacesPour(cabine, { id: choisi.id, code: choisi.code }, revenir, {
    note: phraseProposition(choisi, d, rang, possibles.length),
    suivant: possibles.length > 1
      ? () => proposerEmplacement(cabine, revenir, saut + 1) : null,
  });
}


/** Pourquoi CELUI-LÀ. Une proposition sans raison ne se discute pas, donc ne
    se corrige pas : on l'applique ou on l'ignore, et les deux sont mauvais. */
function phraseProposition(e, d, rang, total) {
  const rangEcrit = rang === 0 ? '1re' : `${rang + 1}e`;
  const suite = total > 1 ? ` (${rangEcrit} sur ${total} possibles)` : '';
  if (e.illimite) {
    return `<b>${esc(e.code)}</b> — aire à capacité illimitée${suite}.`;
  }
  if (d.cabine && d.cabine.tout_l_emplacement) {
    return `<b>${esc(e.code)}</b> est entièrement libre${suite}. Un
      ${esc(d.cabine.modele || 'grand modèle')} prend l’emplacement entier :
      seuls les emplacements vides lui conviennent.`;
  }
  if ((e.libres || []).length === 1) {
    return `<b>${esc(e.code)}</b> : il n’y reste qu’une place${suite}. On finit
      un emplacement entamé plutôt que d’en ouvrir un autre — les grands modèles
      n’acceptent que les emplacements entiers, et chacun laissé à moitié vide
      leur est perdu.`;
  }
  return `<b>${esc(e.code)}</b> est libre${suite}.`;
}

/** Les emplacements qui correspondent à ce qu'on tape.

    Passe par `pour_cabine` et non par la liste générale : c'est ce qui permet à
    chaque ligne de dire si CETTE cabine y tient. La liste générale ne le savait
    pas, et annonçait des places libres qui ne l'étaient pas pour elle. */
async function chercherEmplacements(cabine, texte, revenir) {
  const zone = $('#rgResultats');
  if (!zone) return;
  if (!texte) { zone.innerHTML = ''; return; }
  try {
    const d = await api(`/emplacements/pour_cabine/?cabine=${cabine.id}&q=`
                        + encodeURIComponent(texte));
    dessinerEmplacements((d.emplacements || []).slice(0, 8), cabine, revenir,
                         'Aucun emplacement ne commence par « ' + texte + ' »', d);
  } catch (e) {
    zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

/** Tous les emplacements, pour qui préfère parcourir que taper. */
async function listerEmplacements(cabine, revenir) {
  const zone = $('#rgResultats');
  if (!zone) return;
  zone.innerHTML = '<div class="empty">Chargement…</div>';
  try {
    const d = await api(`/emplacements/pour_cabine/?cabine=${cabine.id}`);
    dessinerEmplacements(d.emplacements || [], cabine, revenir,
                         'Aucun emplacement.', d);
  } catch (e) {
    zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

/** Ce qui reste libre, en clair : « Gauche », « Gauche · Droite », « entier ». */
function libellesPlaces(libres) {
  return (libres || []).map(p => p === 'T' ? 'emplacement entier'
                                           : (NOM_PLACE[p] || p)).join(' · ');
}

/* Une ligne par emplacement, avec de quoi choisir SANS ouvrir. Chaque ligne
   répond POUR la cabine qu'on tient : ce qui lui reste de libre, ou pourquoi
   elle ne rentre pas. La version d'avant listait les places libres « en
   général » — un grand modèle se voyait proposer une place où il ne tient pas,
   et le refus tombait après qu'on l'a touchée.

   Un emplacement qui ne convient pas reste VISIBLE et grisé : le faire
   disparaître ferait chercher un code qui existe, et douter de l'écran. */
function dessinerEmplacements(emps, cabine, revenir, vide, contexte = {}) {
  const zone = $('#rgResultats');
  if (!zone) return;
  if (!emps.length) { zone.innerHTML = `<div class="empty">${esc(vide)}</div>`; return; }
  zone.innerHTML = emps.map(e => {
    const libres = e.libres || [];
    const badge = e.possible
      ? `<span class="etat ok">${e.illimite ? 'place libre' : esc(libellesPlaces(libres))}</span>`
      : `<span class="etat crit">${e.actif === false ? 'hors service' : 'complet'}</span>`;
    const dessous = !e.possible ? esc(e.pourquoi || 'aucune place libre')
      : (e.illimite
          ? `${e.cabines} cabine${e.cabines === 1 ? '' : 's'} ici · capacité illimitée`
          : (libres[0] === 'T'
              ? 'Entièrement libre — ce modèle prend l’emplacement entier'
              : (libres.length === 1
                  ? 'Dernière place libre de cet emplacement'
                  : 'Places libres : ' + esc(libellesPlaces(libres)))));
    return `<div class="item${e.possible ? '' : ' indisponible'}"${
      e.possible ? ` data-e="${e.id}"` : ''}>
      <div class="r">${esc(e.code)} ${badge}</div>
      <div class="d">${esc(e.zone || 'Sans zone')} · ${esc(e.mode_libelle)}${
        e.staging ? ' · zone de réception' : ''}</div>
      <div class="meta">${dessous}</div>
    </div>`;
  }).join('');

  // Combien peuvent vraiment la prendre : sans ce compte, une liste entièrement
  // grisée ressemble à un écran en panne.
  const possibles = emps.filter(e => e.possible).length;
  if (!possibles) {
    zone.insertAdjacentHTML('afterbegin', `<div class="banner"><b>Aucun de ces
      emplacements ne peut prendre ${esc(cabine.numero)}${
      contexte.cabine && contexte.cabine.tout_l_emplacement
        ? ` : un ${esc(contexte.cabine.modele || 'grand modèle')} prend l’emplacement entier`
        : ''}.</b> Chaque ligne dit pourquoi.</div>`);
  }

  zone.querySelectorAll('[data-e]').forEach(it => it.onclick = () => {
    const e = emps.find(x => String(x.id) === it.dataset.e);
    ouvrirPlacesPour(cabine, e, revenir);
  });
}

/** L'emplacement est choisi : reste à toucher la place. Jamais présélectionnée.

    `options.note` : pourquoi cet emplacement, quand il vient d'une proposition.
    `options.suivant` : de quoi en demander un autre — une proposition doit
    pouvoir se refuser, l'entrepôt a des raisons qu'un écran ignore. */
async function ouvrirPlacesPour(cabine, emplacement, revenir, options = {}) {
  const zone = $('#rgZone');
  if (!zone) return;
  zone.innerHTML = '<div class="empty">Lecture des places…</div>';
  const champ = $('#rgCode');
  if (champ) champ.value = emplacement.code;
  const resultats = $('#rgResultats');
  if (resultats) resultats.innerHTML = '';
  try {
    const d = await api(`/emplacements/${emplacement.id}/places/?pour_cabine=${cabine.id}`);
    if (d.complet) {
      /* Il dit CE QUI occupe, pas seulement « complet » : devant un rack, une
         place qu'on voit vide et que l'écran refuse fait douter de l'écran. Un
         grand modèle, lui, a besoin des deux places — et c'est la raison qu'on
         ne devine pas. */
      const grand = d.pour_cabine && d.pour_cabine.tout_l_emplacement;
      const occupees = (d.places || []).filter(p => !p.libre);
      zone.innerHTML = `<div class="banner"><b>${esc(emplacement.code)} ne peut pas
        prendre ${esc(cabine.numero)}.</b><br>
        ${d.actif === false
          ? 'Emplacement hors service' + (d.motif_inactif ? ' : ' + esc(d.motif_inactif) : '') + '.'
          : (grand
              ? `Ce modèle (${esc(d.pour_cabine.modele || '')}) prend l’emplacement
                 ENTIER, et ${occupees.length ? 'une place est déjà prise'
                 : 'une place est condamnée'}.`
              : 'Les deux places sont prises ou condamnées.')}
        ${occupees.map(p => `<br>${esc(p.libelle)} : ${p.condamnee
          ? 'condamnée — ' + esc(p.condamnee)
          : 'occupée par ' + esc((p.cabine || {}).numero || '?')}`).join('')}
        </div>
        <button class="btn orange" id="rgAutre">${icon('search', 17)} Proposer un autre emplacement</button>`;
      const autre = $('#rgAutre');
      if (autre) autre.onclick = () => proposerEmplacement(cabine, revenir, 0);
      return;
    }
    zone.innerHTML = `<div class="card" style="margin-top:12px">
      ${options.note ? `<div class="banner">${options.note}</div>` : ''}
      <div class="r" style="font-weight:700">Emplacement ${esc(emplacement.code)}</div>
      ${blocPlaces(d)}
      <button class="btn orange" id="rgOk">Ranger en ${esc(emplacement.code)}</button>
      ${options.suivant ? '<button class="btn ghost" id="rgAutre">Proposer un autre emplacement</button>' : ''}
    </div>`;
    if (options.suivant) $('#rgAutre').onclick = options.suivant;
    /* La proposition s'écrit sous trois boutons : sur un téléphone, elle naît
       hors de l'écran et on croit qu'il ne s'est rien passé. */
    zone.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const lirePlace = choixPlace(d, $('#rgOk'));
    $('#rgOk').onclick = async () => {
      const choix = lirePlace();
      if (!sansPlaceAChoisir(d) && !choix) {
        toast('Touchez la place où vous posez la cabine.', 'err');
        return;
      }
      const bouton = $('#rgOk');
      bouton.disabled = true;
      try {
        const corps = { emplacement: emplacement.id };
        if (choix) corps.place = choix;
        const frais = await api(`/cabines/${cabine.id}/ranger/`, { method: 'POST', body: corps });
        toast('Rangée en ' + emplacement.code + (choix ? ' · ' + NOM_PLACE[choix] : ''), 'ok');
        /* L'ÉTAT, demandé ici. C'est le seul moment où quelqu'un a la cabine
           sous les yeux : reporté à la fiche, personne ne le déclare et le
           statut reste celui de la veille. Cette question existait sur les
           trois anciens chemins de rangement ; en les fusionnant en un seul
           écran, je l'avais perdue. */
        ouvrirStatut(frais || cabine,
          `Rangée en ${emplacement.code}${choix ? ' · ' + NOM_PLACE[choix] : ''}. Quel est son état ?`,
          () => revenir());
      } catch (err) { bouton.disabled = false; toast(err.message, 'err'); }
    };
  } catch (e) {
    zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

/** Création, puis les deux gestes qui suivent au poste : coller l'étiquette,
    ranger. Un seul endroit crée une cabine — les deux chemins d'entrée
    aboutissaient sinon à deux enchaînements différents. */
async function creerCabine(corps) {
  const c = await api('/cabines/', { method: 'POST', body: corps });
  toast('Cabine ' + c.numero + ' créée', 'ok');
  noterRecentCabine(c);
  /* Un ÉCRAN, pas un bloc ajouté sous le formulaire. Les gestes s'écrivaient
     dans `#apres`, donc sous les quarante-trois caractéristiques de la cabine :
     il fallait dérouler toute la page pour les trouver. Et « Saisir le code »
     ouvrait la fiche de la cabine, où il fallait appuyer une seconde fois sur le
     même libellé. Ici, la page suivante s'ouvre en haut, sur un champ prêt. */
  ecranRangement(c, renderEntree);
  return c;
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
    <div class="cam-ecran">
      <div class="cam-vue" id="reader"></div>
      <div class="cam-statut" id="camStatut" role="status" hidden></div>
      <div class="cam-lu" id="camLu" hidden></div>
    </div>
    <div class="cam-repos" id="camRepos">
      <div class="cam-ico">${icon('camera', 38)}</div>
      <div class="cam-t">${esc(titre)}</div>
      <div class="cam-st">${esc(sousTitre)}</div>
      <button class="btn orange cam-btn" id="camGo">${icon('camera', 20)} Activer la caméra</button>
      <div class="cam-note" id="camNote">Le navigateur va demander l’autorisation. Elle n’est demandée qu’une fois.</div>
    </div>
    <div class="cam-actions" id="camActions" hidden>
      <button class="btn ghost cam-stop" id="camStop" type="button">Arrêter la caméra</button>
    </div>
  </div>`;
}

const STATUT_OUVERTURE = 'Ouverture de la caméra…';
const STATUT_LECTURE = '<span class="pouls" aria-hidden="true"></span> Lecture en cours — visez l’étiquette';

/** Ce que désigne un code lu, dit en clair au-dessus du code. */
function natureDuCode(texte) {
  if (/^LOC:/i.test(texte)) return 'Emplacement lu';
  if (/^CAB:/i.test(texte) || MOTIF_NUMERO_CABINE.test(texte)) return 'Cabine lue';
  return 'Code lu';
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
function reglerCamera() {
  let piste = null;
  try {
    const flux = document.querySelector('#reader video');
    piste = flux && flux.srcObject && flux.srcObject.getVideoTracks()[0];
  } catch (_) { return; }
  if (!piste) return;

  // `applyConstraints` échoue par promesse, pas par exception : sans ce `catch`,
  // un appareil sans mise au point pilotable laissait une erreur non traitée.
  try { piste.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {}); } catch (_) {}

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

/* --- Scanner : on voit qu'il lit, on confirme ce qu'il a lu -------------------
   Avant, la lecture « basculait » : au premier code décodé, la caméra
   s'éteignait, la vidéo disparaissait, « Activer la caméra » revenait à sa place
   et le code lu s'écrivait plus bas — souvent sous le bord de l'écran.
   « Rescanner » rallumait la caméra de zéro.

   Tout se passe maintenant SUR la vidéo :
   - pendant la visée, une pastille « Lecture en cours » et un trait qui balaie
     le cadre disent que l'appareil cherche ;
   - dès qu'un code est lu, l'image se fige sur l'étiquette, les angles du cadre
     passent au vert, le téléphone vibre, et le code s'affiche en grand avec
     « Confirmer » et « Rescanner ». Rien ne s'enchaîne avant « Confirmer » —
     trois étiquettes se touchent sur un montant, c'est ici qu'on voit laquelle
     a été prise ;
   - « Rescanner » relance la visée à l'instant, caméra restée ouverte, et ignore
     une seconde et demie le code qu'on vient d'écarter : le temps de viser la
     voisine sans relire aussitôt la même ;
   - un code refusé (emplacement inconnu, déjà plein) se dit au même endroit, sur
     l'image figée, avec « Rescanner » : ni message à chercher plus bas, ni
     caméra à rallumer.

   `surLecture(texte)` reçoit le texte brut (« LOC:Y550 ») au « Confirmer ».
   Elle peut renvoyer, ou promettre, un message de refus : il s'affiche sur la
   vidéo et la caméra reste prête. Sinon la caméra s'éteint : l'écran suivant a
   pris le relais.                                                            */
function brancherCamera(surLecture) {
  const bouton = $('#camGo'), repos = $('#camRepos'), note = $('#camNote'),
        actions = $('#camActions'), stop = $('#camStop'), cadre = $('#cam'),
        statut = $('#camStatut'), carte = $('#camLu');
  if (!bouton) return;
  let lecteur = null;                       // la caméra de CE bloc
  let tenu = null;                          // le code affiché, qui attend un geste
  let ecarte = { texte: '', jusqua: 0 };    // le code qu'on vient de refuser
  const present = () => document.body.contains(cadre);
  const direStatut = (html) => { statut.innerHTML = html; statut.hidden = !html; };
  const fermerCarte = () => {
    carte.hidden = true; carte.innerHTML = ''; cadre.classList.remove('lu');
  };

  const eteindre = async () => {
    const l = lecteur;
    lecteur = null; tenu = null;
    // Un geste a pu l'éteindre avant nous (l'étape suivante, un changement
    // d'écran) : on n'éteint que la sienne, jamais celle d'un autre bloc.
    if (l && CAMERA === l) await arreterCamera();
    if (!present()) return;                 // l'écran a changé entre-temps
    fermerCarte(); direStatut('');
    const torche = $('#camTorche');
    if (torche) torche.remove();            // liée à la piste qu'on vient de fermer
    cadre.classList.remove('actif');
    repos.hidden = false; actions.hidden = true;
    bouton.disabled = false;
  };

  const reprendre = () => {
    ecarte = { texte: tenu || '', jusqua: Date.now() + 1500 };
    tenu = null;
    fermerCarte();
    direStatut(STATUT_LECTURE);
    try { lecteur.resume(); } catch (_) { eteindre().then(() => bouton.click()); }
  };

  const montrer = (texte, refus) => {
    carte.className = 'cam-lu' + (refus ? ' refus' : '');
    carte.innerHTML = `<div class="lu-t">${icon(refus ? 'alert' : 'check', 16)}
        ${esc(refus ? 'Code refusé' : natureDuCode(texte))}</div>
      <div class="lu-code">${esc(texte.replace(/^(LOC|CAB):/i, ''))}</div>
      ${refus ? `<div class="lu-msg">${esc(refus)}</div>` : ''}
      <div class="lu-boutons">
        ${refus ? '' : '<button class="btn orange" id="luOk" type="button">Confirmer</button>'}
        <button class="btn ${refus ? 'orange' : 'ghost'}" id="luNon" type="button">Rescanner</button>
      </div>`;
    carte.hidden = false;
    cadre.classList.add('lu');
    const ok = carte.querySelector('#luOk'), non = carte.querySelector('#luNon');
    non.onclick = reprendre;
    if (ok) ok.onclick = () => confirmer(texte, ok, non);
    (ok || non).focus({ preventScroll: true });
    carte.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };

  const confirmer = async (texte, ok, non) => {
    ok.disabled = non.disabled = true;
    ok.textContent = 'Vérification…';
    let refus = '';
    try { refus = await surLecture(texte); }
    catch (e) { refus = (e && e.message) || 'Lecture refusée.'; }
    refus = typeof refus === 'string' ? refus.trim() : '';
    if (refus && present() && lecteur && tenu === texte) { montrer(texte, refus); return; }
    if (refus) toast(refus, 'err');
    await eteindre();
  };

  const lu = (brut) => {
    const texte = String(brut || '').trim();
    if (!texte || !lecteur || tenu !== null) return;
    if (texte === ecarte.texte && Date.now() < ecarte.jusqua) return;
    tenu = texte;
    try { lecteur.pause(true); } catch (_) {}   // l'image reste figée sur l'étiquette lue
    vibrer(40);
    direStatut('');
    montrer(texte, '');
  };

  bouton.onclick = async () => {
    bouton.disabled = true;
    note.classList.remove('erreur');
    note.textContent = 'Autorisation demandée…';
    await arreterCamera();                  // une seule caméra à la fois
    // Le conteneur doit être VISIBLE avant `start()`. html5-qrcode mesure sa
    // largeur pour dimensionner la vidéo et le cadre de visée : sur un conteneur
    // en `display:none` il lit 0 et n'affiche rien. La caméra tournait bien —
    // voyant allumé, bouton passé à « Arrêter » — mais l'écran restait vide.
    cadre.classList.add('actif');
    direStatut(STATUT_OUVERTURE);
    let l = null;
    try {
      l = new Html5Qrcode('reader', false, {
        // Détecteur de codes NATIF du navigateur quand il existe. C'est la
        // correction qui compte sur Android : Chrome décode alors le QR dans le
        // système, en une fraction du temps que met le décodeur JavaScript, et
        // sur des images bien plus dégradées. Sans lui, une étiquette un peu de
        // biais ou mal éclairée n'était tout simplement jamais lue.
        experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      });
      lecteur = l; CAMERA = l;
      await l.start(
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
          qrbox: (lg, h) => { const c = Math.floor(Math.min(lg, h) * 0.6); return { width: c, height: c }; },
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
        lu,
        () => {});                          // échecs de décodage : normaux, image par image
      if (!present() || lecteur !== l) { if (CAMERA === l) await arreterCamera(); return; }
      repos.hidden = true; actions.hidden = false;
      direStatut(STATUT_LECTURE);
      reglerCamera();
    } catch (e) {
      if (l && CAMERA === l) CAMERA = null;
      lecteur = null;
      direStatut('');
      cadre.classList.remove('actif');     // retour à l'état de repos, bouton compris
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
    ${(secure && hasLib) ? blocCameraHTML('Scanner un QR code', 'L’étiquette d’un emplacement')
      : `<div class="banner">${!hasLib
          ? 'Lecteur de QR non chargé : ce poste n’a pas accès à internet. Un administrateur doit lancer une fois « python manage.py telecharger_libs » sur le serveur pour rendre le scan et les étiquettes autonomes. En attendant, saisie manuelle ci-dessous.'
          : 'Caméra indisponible ici (HTTPS requis). Sur le téléphone, ouvre l’appli via l’adresse https du tunnel pour scanner à la caméra ; ici, saisie manuelle.'}</div>`}
    <div class="card"><label for="code">Code scanné, n° de cabine ou emplacement</label>
      <input id="code" placeholder="Ex. 00_00_01 ou C001 — les propositions s’affichent en tapant">
      <div class="list" id="sugg"></div>
      <button class="btn" id="go">Valider</button></div>
    <div id="zone"></div>`, 'trouver');

  const champ = $('#code');
  champ.setAttribute('autocomplete', 'off');

  const choisirEmplacement = (e) => {
    $('#sugg').innerHTML = '';
    champ.value = e.code;
    // L'emplacement scanné propose de ranger ou de sortir, place par place.
    montrerEmplacement(e, { retour: () => go('trouver') });
  };
  const choisirCabine = (c) => {
    $('#sugg').innerHTML = '';
    champ.value = c.numero;
    noterRecentCabine(c);
    ouvrirEcran(() => ficheCabine(c, () => history.back()), 'fiche');
  };

  // Suggestions en direct, cabines et emplacements à la fois : au poste on tape
  // aussi bien un numéro de cabine qu'un code d'emplacement.
  const suggerer = debounce(async () => {
    const brut = champ.value.trim();
    const t = brut.replace(/^LOC:/i, '').trim();
    const liste = $('#sugg');
    if (!liste) return;
    if (t.length < 2) {
      // Les cabines consultées récemment, relues auprès du serveur — voir
      // recentsCabinesAJour().
      const r = await recentsCabinesAJour();
      if (champ.value.trim().length >= 2) return;   // l'opérateur a tapé entre-temps
      liste.innerHTML = r.length
        ? `<div class="sec">Consultées récemment</div>${r.map(ligneCabine).join('')}`
        : '';
      const parId = {};
      r.forEach(x => { parId[x.id] = x; });
      liste.querySelectorAll('.item').forEach(it => it.onclick = () => choisirCabine(parId[it.dataset.id]));
      return;
    }
    try {
      const [emps, cabs] = await Promise.all([
        api('/emplacements/?search=' + encodeURIComponent(t)).then(d => d.results || []),
        // Une étiquette d'emplacement (« LOC: ») ne désigne jamais une cabine.
        /^LOC:/i.test(brut) ? Promise.resolve([])
          : api('/cabines/?numero=' + encodeURIComponent(t)).then(d => d.results || []).catch(() => []),
      ]);
      const blocEmp = emps.length
        ? `<div class="sec">Emplacements</div>${emps.slice(0, 4).map(e => `<div class="item" data-emp="${e.id}"><div class="r">${esc(e.code)}</div><div class="d">${esc(e.est_mp ? e.usage_libelle : (e.zone_cabine_nom || e.zone || ''))}</div></div>`).join('')}`
        : '';
      const blocCab = cabs.length
        ? `<div class="sec">Cabines</div>${cabs.slice(0, 5).map(c => `<div class="item" data-cab="${c.id}"><div class="r">${esc(c.numero)} ${badgeStatut(c)}</div><div class="d">Chantier ${esc(c.chantier || '—')}</div></div>`).join('')}`
        : '';
      liste.innerHTML = (blocEmp + blocCab) || '<div class="empty">Aucun résultat</div>';
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
  // Renvoie '' quand l'écran a trouvé, sinon la raison — affichée par l'appelant.
  const run = async () => {
    const brut = (champ.value || '').trim();
    if (!brut) return '';
    try {
      if (/^LOC:/i.test(brut)) {
        const code = brut.slice(4).trim().toUpperCase();
        const d = await api('/emplacements/?search=' + encodeURIComponent(code));
        const res = d.results || [];
        const e = res.find(x => (x.code || '').toUpperCase() === code) || (res.length === 1 ? res[0] : null);
        if (!e) {
          suggerer();
          return res.length ? 'Plusieurs emplacements correspondent, choisis dans la liste.'
                            : `Aucun emplacement ne porte le code « ${code} ».`;
        }
        choisirEmplacement(e);
        return '';
      }
      const ref = brut.replace(/^CAB:/i, '').trim();
      const cible = ref.toUpperCase();

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
      if (cabExact) { choisirCabine(cabExact); return ''; }
      if (empExact) { choisirEmplacement(empExact); return ''; }
      if (cabs.length + emps.length === 1) {
        if (cabs.length) choisirCabine(cabs[0]); else choisirEmplacement(emps[0]);
        return '';
      }
      suggerer();
      return cabs.length + emps.length
        ? 'Plusieurs correspondances, choisis dans la liste.'
        : 'Ni cabine ni emplacement ne correspond à « ' + ref + ' »';
    } catch (e) { return e.message; }
  };
  const valider = async () => { const refus = await run(); if (refus) toast(refus, 'err'); };

  champ.oninput = suggerer;
  champ.onfocus = () => { if (!champ.value.trim()) suggerer(); };
  $('#go').onclick = valider;
  champ.addEventListener('keydown', e => { if (e.key === 'Enter') valider(); });
  suggerer();

  if (secure && hasLib) {
    brancherCamera(async (texte) => {
      champ.value = texte;
      const refus = await run();
      // Trouvé : la fiche s'écrit plus bas, sous le champ — on y descend.
      if (!refus && $('#zone')) $('#zone').scrollIntoView({ block: 'start', behavior: 'smooth' });
      return refus;
    });
  }
}

/* « Plus » : tout ce que le menu autorise, moins ce qui est déjà dans la barre du
   bas. La liste était écrite une deuxième fois ici, en dur et sans filtrage par
   les droits : un cariste s'y voyait proposer les zones et les étiquettes, deux
   écrans que le serveur lui refuse. Elle dérivait aussi du menu à chaque ajout —
   « Suivi du processus » y serait resté après avoir été retiré partout ailleurs. */
/* --- Le WMS sur l'écran d'accueil ------------------------------------------
   Une icône sur le téléphone, qui ouvre le WMS en plein écran : plus d'adresse
   https://…:8443 à retaper, plus d'onglet perdu parmi vingt autres.

   Chrome sur Android sait l'installer d'un geste : il annonce l'installation
   possible par `beforeinstallprompt`, qu'on garde pour le bouton « Installer »
   de l'écran Plus. L'iPhone n'a pas d'équivalent — Safari ne laisse aucune page
   proposer son installation —, on y écrit donc le geste, en trois lignes.

   Ouvert depuis l'icône, le WMS le sait (`display-mode: standalone`) et ne
   propose plus rien.                                                          */
let INVITATION_INSTALL = null;
window.addEventListener('beforeinstallprompt', (ev) => {
  // Pas de bandeau surgi au milieu d'un rangement : c'est l'écran Plus qui propose.
  ev.preventDefault();
  INVITATION_INSTALL = ev;
  if (ECRAN === 'more') rejouerEcran();
});
window.addEventListener('appinstalled', () => {
  INVITATION_INSTALL = null;
  toast('WMS Structa est sur l’écran d’accueil.', 'ok');
  if (ECRAN === 'more') rejouerEcran();
});

/** Le geste à proposer : 'installe' (ouvert depuis l'icône), 'invitation'
 *  (Chrome installe d'un geste), 'ios', 'android' — ou '' sur un ordinateur. */
function plateformeRaccourci({ ua = '', installe = false, invitation = false, tactile = false } = {}) {
  if (installe) return 'installe';
  if (invitation) return 'invitation';
  // Un iPad se présente comme un Mac : c'est l'écran tactile qui le trahit.
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && tactile)) return 'ios';
  if (/Android/i.test(ua)) return 'android';
  return '';
}

const ETAPES_RACCOURCI = {
  android: ['Menu <b>⋮</b> de Chrome, en haut à droite',
            '<b>Ajouter à l’écran d’accueil</b>',
            '<b>Installer</b>'],
  ios: ['Dans Safari : <b>…</b> à droite de l’adresse, puis <b>Partager</b> — ou directement le bouton Partager',
        '<b>Sur l’écran d’accueil</b>',
        '<b>Ajouter</b>'],
};

function blocRaccourci() {
  const cas = plateformeRaccourci({
    ua: navigator.userAgent,
    installe: (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
              || navigator.standalone === true,
    invitation: Boolean(INVITATION_INSTALL),
    tactile: (navigator.maxTouchPoints || 0) > 1,
  });
  if (!cas || cas === 'installe') return '';
  return `<div class="card raccourci">
    <div class="sec" style="margin-top:0">Sur l’écran d’accueil</div>
    <p>Une icône <b>WMS Structa</b> sur ce téléphone, qui ouvre le WMS en plein écran —
      sans adresse à retaper.</p>
    ${cas === 'invitation'
      ? '<button class="btn orange" id="rcInstaller">Installer sur ce téléphone</button>'
      : `<ol>${ETAPES_RACCOURCI[cas].map(e => `<li>${e}</li>`).join('')}</ol>`}
  </div>`;
}

function brancherRaccourci() {
  const bouton = $('#rcInstaller');
  if (!bouton) return;
  bouton.onclick = async () => {
    const invitation = INVITATION_INSTALL;
    INVITATION_INSTALL = null;             // une invitation ne sert qu'une fois
    if (invitation) {
      try {
        await invitation.prompt();
        const choix = await invitation.userChoice;
        if (choix && choix.outcome !== 'accepted') {
          toast('Pas installé. Le menu ⋮ de Chrome → « Ajouter à l’écran d’accueil » le propose aussi.');
        }
      } catch (_) {}
    }
    if (ECRAN === 'more') rejouerEcran();
  };
}

function renderMore() {
  const dansLaBarre = new Set((ONGLETS[profil()] || ONGLETS.lecture).map(o => o[0]));
  const items = menuLateral()
    .flatMap(([, liens]) => liens)
    .filter(([cle]) => !dansLaBarre.has(cle));
  layout(`<h2 class="title">Plus</h2><div class="list">${items.map(([g,l,ic]) => `<div class="item" data-go="${g}"><div class="r">${icon(ic,18)} ${l}</div></div>`).join('')}</div>${blocRaccourci()}<button class="btn ghost" id="logout" style="margin-top:16px">Se déconnecter (${esc(USER)})</button>`, 'more');
  $('#logout').onclick = logout;
  brancherRaccourci();
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
  const [, moi] = await Promise.all([
    rafraichirEmplacements(),
    api('/moi/').catch(() => null),
  ]);
  DROITS = (moi && moi.droits) || {};
  LIBELLES_DROITS = (moi && moi.libelles_droits) || {};
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
  // Le nom de l'écran AVANT de le dessiner : resté à « home », il allumait
  // « Tableau de bord » dans la barre latérale au-dessus de l'écran Cabines,
  // et le pouls redessinait cet écran comme s'il était le tableau de bord.
  ECRAN = 'scanner';
  renderScanner();
  // La cloche n'attend pas le premier battement : ce qui sonnait avant la
  // connexion se voit dès l'arrivée.
  chargerAlertes();
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

   Écran réservé à la case « importer le fichier de production ». Le serveur
   le refuse aussi (403) : ce n'est pas l'interface qui protège, elle évite
   seulement de proposer un bouton qui ne marcherait pas.
   =========================================================================== */

let IMPORT = { fichier: null, rapport: null };

/* ============================ MODÈLES DE CABINE ============================
   Deux cabines tiennent dans un emplacement — une seule si c'est un grand modèle.
   Cette liste-là ne peut pas vivre dans le code : le catalogue bouge, et
   « COLLAB » était annoncé comme grand modèle avant sa première cabine.

   L'écran ne montre pas seulement ce qui a été réglé : il montre tous les
   modèles que les données connaissent — le fichier de production et le stock.
   Un modèle nouveau apparaît donc tout seul au prochain import, compté
   « une place » jusqu'à ce que quelqu'un tranche. C'est le défaut qui laisse
   ranger : refuser tout modèle non déclaré bloquerait l'entrepôt un lundi
   matin sur une ligne de tableur.                                            */

let MODELES = { liste: [], filtre: '' };

async function renderModeles() {
  layout(`<h2 class="title">Modèles de cabine</h2>
    <div class="meta" style="margin:-4px 0 12px">Deux cabines tiennent dans une
      emplacement. Un <b>grand modèle</b> la prend en entier : le WMS refuse alors d'y
      poser une voisine.</div>
    <input id="mdFiltre" class="recherche" type="search" autocomplete="off"
           placeholder="Chercher un modèle…" value="${esc(MODELES.filtre)}">
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'more');
  const champ = $('#mdFiltre');
  champ.oninput = debounce(() => { MODELES.filtre = champ.value; dessinerModeles(); }, 200);
  await chargerModeles();
}

async function chargerModeles() {
  try {
    const d = await api('/modeles-cabine/');
    MODELES.liste = d.modeles || [];
    MODELES.grands = d.nb_grands || 0;
    MODELES.hors = d.emplacements_hors_regle || [];
    dessinerModeles();
  } catch (e) {
    const zone = $('#zone');
    if (zone) zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

function dessinerModeles() {
  const zone = $('#zone');
  if (!zone) return;
  const filtre = ModelesCle(MODELES.filtre);
  const vus = MODELES.liste.filter(m => !filtre || ModelesCle(m.nom).includes(filtre));
  const modifiable = peut('modeles');

  /* Les emplacements laissés hors règle par un reclassement. Aucune cabine n'est
     déplacée quand un modèle change de taille — le WMS écrirait une position que
     personne n'a vérifiée devant le rack. Il le DIT, et c'est un travail
     d'entrepôt, pas une donnée à corriger ici. */
  const hors = MODELES.hors.length ? `<div class="banner" style="margin-bottom:12px">
    <b>${MODELES.hors.length} emplacement${MODELES.hors.length === 1 ? '' : 's'}</b> ne
    respecte${MODELES.hors.length === 1 ? '' : 'nt'} plus la règle : un grand modèle
    y partage la place avec une autre cabine. Aucune n'a été déplacée — c'est à
    faire dans l'entrepôt.
    <div class="specs" style="margin-top:8px"><table><tbody>${MODELES.hors.map(t =>
      `<tr><td>${esc(t.code)}</td><td>${t.cabines.map(c =>
        `${esc(c.numero)}${c.grand ? ' <b>(' + esc(c.modele) + ')</b>' : ''}`).join(' + ')}</td></tr>`
      ).join('')}</tbody></table></div></div>` : '';

  zone.innerHTML = hors + `<div class="sec">${vus.length} modèle${vus.length === 1 ? '' : 's'}`
    + ` · ${MODELES.grands} grand${MODELES.grands === 1 ? '' : 's'}</div>`
    + (vus.length ? `<div class="list">${vus.map(m => `<div class="item" style="cursor:default">
        <div class="r">${esc(m.nom)}${m.grand
          ? ' <span class="etat att">tout l’emplacement</span>' : ''}</div>
        <div class="meta">${m.nb_attendues} annoncée${m.nb_attendues === 1 ? '' : 's'} · ${
          m.nb_en_stock} en stock${m.regle_par ? ' · réglé par ' + esc(m.regle_par) : ''}</div>
        ${modifiable ? `<div class="bascule">
          <button aria-pressed="${!m.grand}" data-md="${esc(m.nom)}" data-grand="0">Une place</button>
          <button aria-pressed="${m.grand}" data-md="${esc(m.nom)}" data-grand="1">Tout l’emplacement</button>
        </div>` : ''}
      </div>`).join('')}</div>`
      : `<div class="empty">${MODELES.filtre
          ? 'Aucun modèle ne correspond.'
          : 'Aucun modèle : importez le fichier de production.'}</div>`);

  if (!modifiable) return;
  zone.querySelectorAll('[data-md]').forEach(b => b.onclick = async () => {
    const grand = b.dataset.grand === '1';
    zone.querySelectorAll('[data-md]').forEach(x => { x.disabled = true; });
    try {
      await api('/modeles-cabine/regler/', { method: 'POST',
        body: { nom: b.dataset.md, grand } });
      toast(`${b.dataset.md} : ${grand ? 'tout l’emplacement' : 'une place'}`, 'ok');
      await chargerModeles();
    } catch (e) {
      toast(e.message, 'err');
      zone.querySelectorAll('[data-md]').forEach(x => { x.disabled = false; });
    }
  });
}

/** Même normalisation que le serveur, pour que le filtre trouve « xl (2modules) ». */
const ModelesCle = (nom) => String(nom || '').split(/\s+/).join(' ').trim().toUpperCase();


async function renderImport() {
  if (!peut('production')) {
    layout(`<h2 class="title">Fichier de production</h2>
      <div class="banner">${esc(sansLeDroit('production'))}</div>`, 'import');
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
      ${d.sans_chantier ? LIGNE_RAPPORT('Sans n° de chantier', d.sans_chantier) : ''}
      ${d.absentes_du_fichier ? LIGNE_RAPPORT('Déjà en base et absentes de ce fichier', d.absentes_du_fichier + ' — conservées') : ''}
    </tbody></table></div>

    ${d.sans_chantier ? `<div class="banner" style="margin-top:12px">
      ${d.sans_chantier} ligne${d.sans_chantier === 1 ? '' : 's'} n’${d.sans_chantier === 1 ? 'a' : 'ont'} pas de
      n° de chantier exploitable : colonne vide, ou forme que le WMS ne sait pas
      enregistrer. Les lots sont acceptés (« 251213-1 »), ce n’est donc pas eux.
      La cabine est quand même importée avec toutes ses caractéristiques, et le n° de
      chantier sera demandé — et exigé — à son entrée en stock.</div>` : ''}

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
   MATIÈRES PREMIÈRES — vitrages et cartons

   Un parcours court, qui part de l'emplacement comme celui des cabines part
   du numéro : on scanne l'étiquette du rack ou du chevalet, l'écran montre ses
   trois places — gauche, milieu, droite — et ce qu'elles portent, et l'on
   entre ou l'on sort.

   Trois règles tiennent l'écran propre :
   - le code se CHOISIT dans la base, il ne se tape pas en entier : on écrit
     « vitr.8 » ou « 445 » et la liste se resserre. Un code tapé à la main finit
     par exister en deux orthographes, et le stock se coupe en deux ;
   - rien n'est présélectionné, ni la place ni la quantité : la palette posée à
     droite ne doit pas s'écrire à gauche parce qu'on a validé trop vite ;
   - une ancienne génération se confirme, en toutes lettres.
   =========================================================================== */

const FAMILLES_MP = {
  vitrage: { un: 'vitrage', plusieurs: 'vitrages', titre: 'Vitrages',
             exemple: 'Ex. vitr.445 ou 445' },
  carton: { un: 'carton', plusieurs: 'cartons', titre: 'Cartons',
            exemple: 'Ex. C8.FD ou ESS 1 F' },
};
const NOMS_PLACES_MP = { G: 'gauche', M: 'milieu', D: 'droite' };
const PLACES_MP = ['G', 'M', 'D'];

/** La clé de comparaison d'un code : la même règle que le serveur
    (`normaliser_code_mp`). « vitr.445 », « VITR 445 » → « VITR445 ». */
function cleMP(texte) {
  return String(texte == null ? '' : texte).replace(/×/g, 'X')
    .normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .toUpperCase().replace(/[^0-9A-Z]/g, '');
}

/** Une quantité saisie → entier ≥ 1, ou `null`. Pas de virgule : on compte des
    pièces. Les espaces sont tolérés (« 1 600 »), le reste non. */
function lireQuantite(brut) {
  const t = String(brut == null ? '' : brut).replace(/\s/g, '');
  if (!/^\d+$/.test(t)) return null;
  const n = parseInt(t, 10);
  return n >= 1 ? n : null;
}

/** « 19 vitrages », « 1 carton ». */
function quantiteMP(n, famille) {
  const f = FAMILLES_MP[famille] || { un: 'pièce', plusieurs: 'pièces' };
  return `${n} ${n > 1 ? f.plusieurs : f.un}`;
}

const badgeAncienne = (a) => (a && a.ancienne_generation
  ? ' <span class="etat ancienne">ancienne gen</span>' : '');

/** Ce qu'on lit sous un code : désignation, fournisseur, n° article. */
const sousTitreArticle = (a) => [a.designation,
  a.fournisseur ? a.fournisseur + (a.numero ? ' n°' + a.numero : '') : (a.numero ? 'n°' + a.numero : ''),
].filter(Boolean).map(esc).join(' · ');

/* --- L'onglet MP --------------------------------------------------------- */

async function renderMP() {
  const agir = peut('mp');
  layout(`<h2 class="title">Matières premières</h2>
    <div class="meta" style="margin:-4px 0 14px">Vitrages et cartons. Tout part de
      l’emplacement : scanne son étiquette, puis entre ou sors.</div>
    ${agir ? '' : `<div class="banner">Consultation seule : il faut la case
      « ${esc(libelleDroit('mp'))} » pour entrer ou sortir du stock.</div>`}
    <div class="gestes">
      <button class="geste" id="mQr">
        <span class="ic">${icon('scan', 26)}</span>
        <span class="t">Scanner un emplacement MP</span>
        <span class="s">L’étiquette du rack ou du chevalet</span>
      </button>
      <button class="geste" id="mCherche">
        <span class="ic">${icon('search', 26)}</span>
        <span class="t">Trouver par code élément</span>
        <span class="s">Un vitrage, un carton : où il est, combien il en reste</span>
      </button>
    </div>
    <div id="mCam"></div>
    <div class="card">
      <div class="sec" style="margin-top:0">Ou saisir l’emplacement</div>
      <input id="mEmp" placeholder="Ex. AH500" autocomplete="off" autocapitalize="characters" spellcheck="false">
      <div class="list" id="mEmpSugg"></div>
      <div id="mEmpEtat"></div>
      <button class="btn ghost" id="mEmpOk">Continuer</button>
    </div>
    <div class="sec">En stock</div>
    <div class="kpis" id="mKpis"><div class="kpi"><div class="l">Chargement…</div></div></div>
    <div class="pied">
      <button data-go="stockmp">${icon('search', 16)} Tout le stock MP</button>
      <button data-go="journalmp">${icon('history', 16)} Journal MP</button>
    </div>`, 'mp');

  // « Trouver par code élément » : le Stock côté MP, le curseur déjà dans la
  // recherche.
  $('#mCherche').onclick = () => ouvrirStockMP({}, { chercher: true });
  $('#mQr').onclick = () => {
    const zone = $('#mCam');
    if (!zone) return;
    zone.innerHTML = blocCameraHTML('Scanner un emplacement MP',
                                    'L’étiquette du rack ou du chevalet');
    brancherCamera((texte) => retenirEmplacementMP(texte));
    const allumer = $('#camGo');
    if (allumer) allumer.click();
    zone.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };

  const champ = $('#mEmp');
  const valider = async () => {
    const refus = await retenirEmplacementMP(champ.value);
    const etat = $('#mEmpEtat');
    if (etat) etat.innerHTML = refus ? `<div class="banner" style="margin:10px 0 0">${esc(refus)}</div>` : '';
  };
  $('#mEmpOk').onclick = valider;
  champ.onkeydown = (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); valider(); } };
  // Les emplacements MP qui ressemblent à la saisie : on tape « AH5 », on touche.
  champ.oninput = debounce(async () => {
    const boite = $('#mEmpSugg');
    const t = champ.value.replace(/^LOC:/i, '').trim();
    if (!boite) return;
    if (t.length < 2) { boite.innerHTML = ''; return; }
    try {
      const res = (await api('/emplacements/?usage=mp&search=' + encodeURIComponent(t))).results || [];
      boite.innerHTML = res.slice(0, 6).map(e => `<div class="item" data-emp="${e.id}">
          <div class="r">${esc(e.code)} ${etiquetteEtat(e)}</div></div>`).join('')
        || '<div class="empty" style="padding:12px">Aucun emplacement MP ne correspond</div>';
      boite.querySelectorAll('[data-emp]').forEach(n => n.onclick = () => {
        const e = res.find(x => String(x.id) === n.dataset.emp);
        if (e) ouvrirEmplacementMP(e);
      });
    } catch (e) { boite.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }, 220);

  try {
    const c = await api('/mp/filtres/');
    const k = $('#mKpis');
    if (!k) return;
    const bas = c.sous_seuil || 0;
    k.innerHTML = ['vitrage', 'carton'].map(f => {
      const x = (c.familles || {})[f] || { codes: 0, quantite: 0 };
      return `<div class="kpi clic kpi-mp ${f}" data-fam="${f}">
        <div class="l">${FAMILLES_MP[f].titre}</div>
        <div class="v">${x.quantite}</div>
        <div class="l">${x.codes} code${x.codes > 1 ? 's' : ''} en stock</div></div>`;
    }).join('')
      // Les codes sous leur seuil : la même chose que la cloche, là où l'on
      // regarde le stock. Sur toute la largeur — un troisième chiffre seul sur
      // sa ligne aurait l'air d'avoir perdu son voisin.
      + `<div class="kpi clic kpi-seuil${bas ? ' warn' : ''}" data-seuil>
          <div class="l">Sous le seuil d’alerte</div>
          <div class="v">${bas}</div>
          <div class="l">${bas ? `code${bas > 1 ? 's' : ''} à recommander — voir la liste`
                               : 'aucun code à recommander'}</div></div>`
      + (c.emplacements_mp ? '' : `<div class="banner" style="grid-column:1/-1;margin:0">
        Aucun emplacement n’est encore réglé pour les matières premières.
        ${peut('empl_regler') ? 'Emplacements → un rack → « Sélectionner » → « Ce qu’ils rangent ».'
          : `Il faut la case « ${esc(libelleDroit('empl_regler'))} » pour les régler.`}</div>`);
    k.querySelectorAll('[data-fam]').forEach(n => n.onclick = () =>
      ouvrirStockMP({ famille: n.dataset.fam }));
    const seuil = k.querySelector('[data-seuil]');
    if (seuil) seuil.onclick = () => ouvrirStockMP({ sous_seuil: '1' });
  } catch (e) {
    const k = $('#mKpis');
    if (k) k.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

/** QR lu (ou code saisi) : un emplacement MP s'ouvre, un autre se refuse — et le
    refus dit pourquoi, sur la vidéo. Renvoie '' quand l'écran suivant est ouvert. */
async function retenirEmplacementMP(texte) {
  const code = String(texte || '').replace(/^(LOC|CAB):/i, '').trim();
  if (!code) return 'Saisis le code de l’emplacement.';
  if (MOTIF_NUMERO_CABINE.test(code)) {
    return `${code} est un n° de cabine : scanne l’étiquette de l’emplacement.`;
  }
  try {
    const d = await api('/mp/emplacement/?code=' + encodeURIComponent(code));
    if (!d.est_mp) return d.refus || `${d.code} range des cabines.`;
    await arreterCamera();
    ouvrirEmplacementMP({ id: d.emplacement, code: d.code });
    return '';
  } catch (e) { return e.message; }
}

/** L'écran d'un emplacement MP, avec son entrée d'historique. */
function ouvrirEmplacementMP(emp) {
  ouvrirEcran(() => ecranEmplacementMP(emp), 'mp-emplacement');
}

async function ecranEmplacementMP(emp) {
  ECRAN = 'mp-emplacement';
  layout(`<h2 class="title">Matières premières</h2>
    <div id="zone"></div>
    <div class="pied">
      <button data-go="mp">${icon('scan', 16)} Un autre emplacement</button>
      <button data-go="stockmp">${icon('search', 16)} Stock MP</button>
    </div>`, 'mp');
  await montrerEmplacementMP(emp);
}

/** Une place et ce qu'elle porte. Chaque ligne se touche : pour en sortir —
    ou, quand on choisit ce qui change d'emplacement, pour la cocher
    (`choisies` : les identifiants cochés, `null` hors de ce choix). */
function placeMPHTML(p, cliquable, choisies = null) {
  const lignes = p.lignes.map(l => `<button type="button" class="mp-ligne${
      l.hors_reservation ? ' hors' : ''}" data-ligne="${l.id}"${
      choisies ? ` aria-pressed="${String(choisies.has(String(l.id)))}"` : ''}${cliquable ? '' : ' disabled'}>
      <span class="code-mp">${esc(l.code)}</span>
      <span class="q">${l.quantite}</span>
      <span class="d">${esc(l.designation || '')}${l.ancienne_generation
        ? ' · <b class="ancienne-txt">ancienne génération</b>' : ''}${l.hors_reservation
        ? ' · <b class="hors-txt">plus accepté ici : à changer d’emplacement</b>' : ''}</span>
    </button>`).join('');
  const vide = p.condamnee
    ? `<div class="mp-vide">Condamnée — ${esc(p.condamnee)}</div>`
    : (p.lignes.length ? '' : '<div class="mp-vide">libre</div>');
  return `<div class="mp-place${p.condamnee ? ' condamnee' : ''}">
    <div class="mp-lettre"><b>${esc(p.code)}</b><span>${esc(NOMS_PLACES_MP[p.code] || '')}</span></div>
    <div class="mp-contenu">${lignes}${vide}</div>
  </div>`;
}

/** Le contenu d'un emplacement MP, et ses trois gestes : entrer, sortir,
    changer d'emplacement.

    S'écrit dans le `#zone` de l'écran courant — l'écran MP, la fiche d'un
    emplacement, ou l'écran Cabines quand on y a lu une étiquette MP. `apres`
    est la phrase de réussite du geste précédent : elle reste affichée
    au-dessus, le temps d'enchaîner le suivant. `alerte` la complète quand le
    geste a fait passer un code sous son seuil, et `arrivee` propose d'ouvrir
    l'emplacement où le stock vient d'arriver. */
async function montrerEmplacementMP(emp, opts = {}) {
  const zone = zoneEcran();
  if (!zone) return;
  const redessiner = (apres, suite = {}) => montrerEmplacementMP(emp, {
    ...opts, apres, alerte: suite.alerte || '', arrivee: suite.arrivee || null });
  zone.innerHTML = '<div class="empty">Chargement…</div>';
  let d;
  try { d = await api('/mp/emplacement/?id=' + encodeURIComponent(emp.id)); }
  catch (e) { zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  // L'opérateur a pu changer d'écran pendant la lecture : rien à dessiner.
  if (!zone.isConnected) return;
  if (!d.est_mp) { zone.innerHTML = `<div class="banner">${esc(d.refus)}</div>`; return; }

  const agir = peut('mp');
  const lignes = d.places.flatMap(p => p.lignes);
  const acceptes = d.codes_acceptes || [];
  zone.innerHTML = `
    ${opts.apres ? `<div class="banner fait">${esc(opts.apres)}</div>` : ''}
    ${opts.alerte ? `<div class="banner">${esc(opts.alerte)}</div>` : ''}
    ${opts.arrivee ? `<div class="row" style="margin:-4px 0 14px"><button class="btn ghost" id="mpArrivee"
        style="margin-top:0">${icon('transfer', 17)} Ouvrir ${esc(opts.arrivee.code)}, où le stock est arrivé</button></div>` : ''}
    <div class="card emp-mp ${esc(d.famille)}">
      <div class="emp-mp-tete">
        <div><span class="famille-mp ${esc(d.famille)}">${esc(d.usage_libelle)}</span>
          <div class="r">Emplacement ${esc(d.code)}</div></div>
        <span class="total">${d.nb_lignes ? quantiteMP(d.quantite, d.famille) : 'vide'}</span>
      </div>
      ${acceptes.length ? `<div class="mp-reserve"><span class="l">Réservé à</span>${
        acceptes.map(a => `<span class="jeton">${esc(a.code)}</span>`).join('')}</div>` : ''}
      ${d.actif ? '' : `<div class="banner" style="margin:10px 0 0">${esc(d.code)} est hors
        service${d.motif_inactif ? ' : ' + esc(d.motif_inactif) : ''}. Rien n’y entre plus ;
        ce qui y reste peut encore sortir ou changer d’emplacement.</div>`}
      <div class="mp-places" id="mpPlacesVue">${d.places.map(p => placeMPHTML(p, agir)).join('')}</div>
      ${agir ? `<div class="row" style="margin-top:12px">
          <button class="btn orange" id="mpEntrer" style="margin-top:0"${d.actif ? '' : ' disabled'}>${icon('in', 17)} Entrer</button>
          <button class="btn ghost" id="mpSortir" style="margin-top:0"${d.nb_lignes ? '' : ' disabled'}>${icon('out', 17)} Sortir</button>
        </div>
        <div class="row" style="margin-top:8px">
          <button class="btn ghost" id="mpDeplacer" style="margin-top:0"${d.nb_lignes ? '' : ' disabled'}>${
            icon('transfer', 17)} Changer d’emplacement</button>
        </div>` : `<div class="meta" style="margin-top:10px">Consultation seule : il faut la case
          « ${esc(libelleDroit('mp'))} ».</div>`}
      <div id="mpAct"></div>
    </div>
    ${(gereEmplacements() && !opts.sansReglages) ? `<button class="btn ghost" id="mpReglage" style="margin-top:12px">${
      icon('cog', 17)} Régler cet emplacement — codes acceptés, places</button>` : ''}
    ${opts.pied ? piedGestes({ suite: 'Scanner autre chose' }) : ''}`;
  // Le pied et le réglage sont écrits dans un `#zone` : `layout()` ne les a
  // pas branchés.
  zone.querySelectorAll('[data-go]').forEach(b => b.onclick = () => go(b.dataset.go));
  const reglage = zone.parentNode && zone.parentNode.querySelector('#mpReglage');
  if (reglage) reglage.onclick = () => ficheEmplacement({ id: d.emplacement }, opts.retour || renderEmplacements);
  const versArrivee = zone.querySelector('#mpArrivee');
  if (versArrivee) versArrivee.onclick = () => ouvrirEmplacementMP(opts.arrivee);
  if (!agir) return;

  const vue = zone.querySelector('#mpPlacesVue');
  const act = zone.querySelector('#mpAct');
  // Le choix de ce qui change d'emplacement : un ensemble d'identifiants le
  // temps du choix, `null` le reste du temps — une ligne touchée ouvre alors
  // sa sortie, comme avant.
  let choisies = null;
  const ouvrirSortie = (id) => {
    const ligne = lignes.find(l => String(l.id) === String(id));
    if (ligne) ouvrirSortieMP(d, ligne, redessiner);
  };
  const dessinerPlaces = () => {
    vue.classList.toggle('selection', Boolean(choisies));
    vue.classList.remove('choisir');
    vue.innerHTML = d.places.map(p => placeMPHTML(p, true, choisies)).join('');
    vue.querySelectorAll('.mp-ligne[data-ligne]').forEach(b => b.onclick = () => toucher(b.dataset.ligne));
  };
  const toucher = (id) => {
    if (!choisies) { ouvrirSortie(id); return; }
    if (choisies.has(id)) choisies.delete(id); else choisies.add(id);
    dessinerPlaces();
    barreChoix();
  };
  const quitterChoix = () => { arreterCamera(); choisies = null; dessinerPlaces(); act.innerHTML = ''; };
  const versLArrivee = (parties, retour, libelleRetour) => {
    // Pendant le choix de l'arrivée, la sélection est figée : elle se modifie
    // par « Modifier la sélection », pas d'un doigt qui frôle une ligne.
    vue.querySelectorAll('.mp-ligne').forEach(b => { b.disabled = true; });
    ouvrirDeplacementMP(d, parties, redessiner, retour, libelleRetour);
  };
  const barreChoix = () => {
    const n = choisies.size;
    act.innerHTML = `<div class="mp-panneau">
      <div class="sec" style="margin-top:0">Changer d’emplacement</div>
      <div class="aide" style="margin:0 0 10px">Touche, ci-dessus, ce qui part — une ligne ou
        plusieurs. Elles iront toutes au même endroit.</div>
      <button class="btn orange" id="mpChoixOk" style="margin-top:0"${n ? '' : ' disabled'}>${n
        ? `Choisir l’arrivée — ${n} ligne${n > 1 ? 's' : ''}` : 'Touche au moins une ligne'}</button>
      <div class="row" style="margin-top:8px">
        <button class="btn ghost" id="mpChoixTout" style="margin-top:0"${n === lignes.length ? ' disabled' : ''}>Tout cocher</button>
        <button class="btn ghost" id="mpChoixNon" style="margin-top:0">Annuler</button>
      </div></div>`;
    act.querySelector('#mpChoixOk').onclick = () => {
      const parties = lignes.filter(l => choisies.has(String(l.id)));
      if (parties.length) {
        versLArrivee(parties, () => { dessinerPlaces(); barreChoix(); }, '← Modifier la sélection');
      }
    };
    act.querySelector('#mpChoixTout').onclick = () => {
      lignes.forEach(l => choisies.add(String(l.id)));
      dessinerPlaces();
      barreChoix();
    };
    act.querySelector('#mpChoixNon').onclick = quitterChoix;
  };

  dessinerPlaces();
  zone.querySelector('#mpEntrer').onclick = () => {
    if (choisies) quitterChoix();
    ouvrirEntreeMP(d, redessiner);
  };
  zone.querySelector('#mpSortir').onclick = () => {
    if (choisies) quitterChoix();
    if (lignes.length === 1) { ouvrirSortie(lignes[0].id); return; }
    // Plusieurs lignes : on désigne celle qu'on emporte, à l'endroit où elle est.
    vue.classList.add('choisir');
    act.innerHTML = `<div class="banner" style="margin:12px 0 0">Touche, ci-dessus,
      la ligne à sortir.</div>`;
    vue.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
  zone.querySelector('#mpDeplacer').onclick = () => {
    arreterCamera();                 // celle d'une arrivée laissée en plan
    // Une seule ligne : il n'y a rien à choisir, on passe à l'arrivée.
    if (lignes.length === 1) {
      choisies = new Set([String(lignes[0].id)]);
      dessinerPlaces();
      versLArrivee(lignes.slice(), quitterChoix, 'Annuler');
      return;
    }
    choisies = new Set();
    dessinerPlaces();
    barreChoix();
    vue.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
}

/** Les trois places, à toucher. Une place condamnée se montre, éteinte, avec sa
    raison : une place qui disparaît passe pour un défaut d'affichage.
    `exclues` : les places d'où part ce qu'on déplace, quand l'arrivée est le
    même emplacement — y « déplacer » ne déplacerait rien. */
function placesMPHTML(d, opts = {}) {
  const exclues = opts.exclues || new Set();
  return `<div class="places" id="mpPlaces">${d.places.map(p => {
    const depart = exclues.has(p.code);
    const etat = p.condamnee ? 'condamnée' : depart ? 'départ'
      : (p.lignes.length ? `${p.lignes.length} code${p.lignes.length > 1 ? 's' : ''}` : 'libre');
    const eteinte = p.condamnee || depart;
    return `<button type="button" class="place${p.condamnee ? ' condamnee' : ''}${depart ? ' depart' : ''}" data-place="${esc(p.code)}"
        aria-pressed="false"${eteinte ? ` disabled title="${esc(p.condamnee || 'C’est d’ici que ça part')}"` : ''}>
        <span class="c">${esc(p.code)}</span>
        <span class="l">${esc(NOMS_PLACES_MP[p.code] || '')}</span>
        <span class="l${p.condamnee ? ' o' : ''}">${esc(etat)}</span></button>`;
  }).join('')}</div>`;
}

/** Entrer : la place, le code choisi dans la base, la quantité. Dans cet ordre,
    celui du geste devant le rack : on pose, on lit l'étiquette, on compte.

    Un emplacement réservé propose ses codes d'une touche, et la recherche ne
    cherche que parmi eux : le serveur refuserait les autres. */
function ouvrirEntreeMP(d, redessiner) {
  const zone = $('#mpAct');
  if (!zone) return;
  const vue = $('#mpPlacesVue');
  if (vue) vue.classList.remove('choisir');
  const fam = FAMILLES_MP[d.famille] || FAMILLES_MP.vitrage;
  const acceptes = d.codes_acceptes || [];
  let place = null;
  let article = null;
  let propositions = [];

  zone.innerHTML = `<div class="mp-panneau">
    <div class="sec" style="margin-top:0">Entrer des ${esc(fam.plusieurs)} en ${esc(d.code)}</div>
    <label>Place</label>
    ${placesMPHTML(d)}
    <label for="mpCode">Code élément</label>
    ${acceptes.length ? `<div class="aide" style="margin:0 0 8px">${esc(d.code)} est réservé à
        ${acceptes.length > 1 ? 'ces codes' : 'ce code'} : touche celui que tu poses.</div>
      <div class="chips">${acceptes.map(a => `<button type="button" class="chip" data-accepte="${a.id}">${
        esc(a.code)}</button>`).join('')}</div>` : ''}
    <input id="mpCode" placeholder="${esc(acceptes.length ? 'Ou cherche parmi eux' : fam.exemple)}" autocomplete="off"
           autocapitalize="characters" autocorrect="off" spellcheck="false">
    <div class="list" id="mpSugg"></div>
    <div id="mpChoisi"></div>
    <label for="mpQte">Quantité (${esc(fam.plusieurs)})</label>
    <div class="qte-mp"><input id="mpQte" inputmode="numeric" pattern="[0-9]*" autocomplete="off">
      <span id="mpColis"></span></div>
    <div class="manque" id="mpManque"></div>
    <button class="btn orange" id="mpOk" disabled>Entrer</button>
    <button class="btn ghost" id="mpAnnul">Annuler</button>
  </div>`;

  const champ = $('#mpCode'), qte = $('#mpQte'), bouton = $('#mpOk');

  const majBouton = () => {
    const n = lireQuantite(qte.value);
    const manque = !place ? 'Touche une place'
      : !article ? 'Choisis le code dans la liste'
      : !n ? 'Indique la quantité' : '';
    bouton.disabled = Boolean(manque);
    bouton.textContent = manque || `Entrer ${quantiteMP(n, d.famille)} en ${place} — ${NOMS_PLACES_MP[place]}`;
  };

  zone.querySelectorAll('#mpPlaces .place').forEach(b => {
    if (b.disabled) return;
    b.onclick = () => {
      place = b.dataset.place;
      zone.querySelectorAll('#mpPlaces .place').forEach(x =>
        x.setAttribute('aria-pressed', String(x.dataset.place === place)));
      majBouton();
      if (!article && !acceptes.length) champ.focus();
    };
  });

  const choisir = (a) => {
    article = a;
    champ.value = a.code;
    $('#mpSugg').innerHTML = '';
    zone.querySelectorAll('[data-accepte]').forEach(x =>
      x.classList.toggle('on', String(x.dataset.accepte) === String(a.id)));
    // Où ce code est-il attendu, s'il l'est ailleurs qu'ici ? La réponse à
    // « est-ce que je le pose au bon endroit ? », avant de le poser.
    const ailleurs = (a.reserve_sur || []).filter(c => c !== d.code);
    $('#mpChoisi').innerHTML = `<div class="mp-choisi${a.ancienne_generation ? ' ancienne' : ''}">
      <b class="code-mp">${esc(a.code)}</b>${badgeAncienne(a)}
      <div>${sousTitreArticle(a)}</div>
      ${a.ancienne_generation ? '<div><b>Ancienne génération</b> : l’entrée te sera demandée en confirmation.</div>' : ''}
      ${ailleurs.length && !acceptes.length ? `<div>Ce code a sa place réservée en <b>${
        esc(listeCodes(ailleurs))}</b>.</div>` : ''}
    </div>`;
    $('#mpColis').innerHTML = a.colisage
      ? `<button type="button" class="chip" id="mpPalette">${a.colisage} · 1 palette</button>` : '';
    const palette = $('#mpPalette');
    if (palette) palette.onclick = () => { qte.value = String(a.colisage); majBouton(); };
    majBouton();
    qte.focus();
  };

  zone.querySelectorAll('[data-accepte]').forEach(b => b.onclick = () => {
    const a = acceptes.find(x => String(x.id) === b.dataset.accepte);
    if (a) choisir(a);
  });

  // Le code a été choisi — d'une touche sur une pastille, ou dans la liste —
  // pendant qu'une recherche attendait son tour : elle n'a plus rien à dire.
  const dejaChoisi = () => Boolean(article) && cleMP(champ.value) === cleMP(article.code);
  const proposer = debounce(async () => {
    const t = champ.value.trim();
    const boite = $('#mpSugg');
    if (!boite) return;
    if (!cleMP(t) || dejaChoisi()) { boite.innerHTML = ''; propositions = []; return; }
    try {
      propositions = await api(`/mp/suggestions/?famille=${encodeURIComponent(d.famille)}`
        + `&emplacement=${encodeURIComponent(d.emplacement)}&q=${encodeURIComponent(t)}`);
      if (champ.value.trim() !== t || dejaChoisi()) return;   // on a tapé, ou choisi, entre-temps
      boite.innerHTML = propositions.length
        ? propositions.slice(0, 8).map(a => `<div class="item sugg-mp" data-art="${a.id}">
            <div class="r"><span class="code-mp">${esc(a.code)}</span>${badgeAncienne(a)}</div>
            <div class="d">${sousTitreArticle(a)}${a.en_stock ? ` · <b>${a.en_stock}</b> en stock` : ''}</div>
          </div>`).join('')
        : `<div class="empty" style="padding:12px">${acceptes.length
            ? `Aucun des codes acceptés en ${esc(d.code)} ne ressemble à « ${esc(t)} ». Un autre code se
               pose sur un autre emplacement.`
            : `Aucun ${esc(fam.un)} de la base ne ressemble à « ${esc(t)} ».`}</div>`;
      boite.querySelectorAll('[data-art]').forEach(n => n.onclick = () => {
        const a = propositions.find(x => String(x.id) === n.dataset.art);
        if (a) choisir(a);
      });
    } catch (e) { boite.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }, 160);

  champ.oninput = () => {
    // Le texte ne correspond plus au code choisi : on repart de la liste.
    if (article && cleMP(champ.value) !== cleMP(article.code)) {
      article = null;
      $('#mpChoisi').innerHTML = '';
      $('#mpColis').innerHTML = '';
      zone.querySelectorAll('[data-accepte]').forEach(x => x.classList.remove('on'));
      majBouton();
    }
    proposer();
  };
  champ.onkeydown = (ev) => {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    // Entrée : le code exact, ou la seule proposition. Jamais la première d'une liste.
    const exact = propositions.find(a => cleMP(a.code) === cleMP(champ.value));
    if (exact) choisir(exact);
    else if (propositions.length === 1) choisir(propositions[0]);
  };
  qte.oninput = majBouton;
  qte.onkeydown = (ev) => { if (ev.key === 'Enter' && !bouton.disabled) { ev.preventDefault(); bouton.click(); } };
  $('#mpAnnul').onclick = () => { zone.innerHTML = ''; };

  bouton.onclick = async () => {
    const n = lireQuantite(qte.value);
    if (!place || !article || !n) { majBouton(); return; }
    if (article.ancienne_generation) {
      const ok = await confirmer({
        titre: 'Attention : ancienne génération',
        texte: `${article.code} est une ancienne génération. Tu veux vraiment l’entrer ?`,
        ok: 'Oui, l’entrer', annuler: 'Non', danger: true,
      });
      if (!ok) return;
    }
    bouton.disabled = true;
    bouton.textContent = 'Enregistrement…';
    try {
      await api('/mp/entrer/', { method: 'POST', body: {
        emplacement: d.emplacement, place: place, article: article.id, quantite: n,
        ancienne_confirmee: Boolean(article.ancienne_generation),
      } });
      const phrase = `Entré : ${quantiteMP(n, d.famille)} ${article.code} en ${d.code}·${place}.`;
      toast(phrase, 'ok');
      chargerAlertes();
      redessiner(phrase + ' Autre chose ?');
    } catch (e) {
      const manque = $('#mpManque');
      if (manque) { manque.textContent = e.message; majBouton(); } else toast(e.message, 'err');
    }
  };
  majBouton();
}

//: Les motifs de sortie qui reviennent : un geste au lieu d'une phrase à taper.
const MOTIFS_SORTIE_MP = ['Production', 'Casse', 'Inventaire', 'Retour fournisseur'];

/** La phrase qui suit une sortie quand le code vient de passer sous son seuil. */
function phraseSeuil(a) {
  if (!a || !a.sous_seuil) return '';
  return `${a.code} est sous son seuil d’alerte : ${a.en_stock
    ? `plus que ${quantiteMP(a.en_stock, a.famille)} en stock` : 'plus aucun en stock'}, pour un seuil de ${a.seuil}.`;
}

/** Sortir une ligne : combien, et pourquoi si on veut le dire. */
function ouvrirSortieMP(d, ligne, redessiner) {
  const zone = $('#mpAct');
  if (!zone) return;
  const vue = $('#mpPlacesVue');
  if (vue) vue.classList.remove('choisir');
  zone.innerHTML = `<div class="mp-panneau">
    <div class="sec" style="margin-top:0">Sortir de ${esc(d.code)}·${esc(ligne.place)} — ${esc(NOMS_PLACES_MP[ligne.place] || '')}</div>
    <div class="mp-choisi${ligne.ancienne_generation ? ' ancienne' : ''}">
      <b class="code-mp">${esc(ligne.code)}</b>${badgeAncienne(ligne)}
      <div>${esc(ligne.designation || '')}</div>
      <div><b>${quantiteMP(ligne.quantite, ligne.famille)}</b> à cette place</div>
    </div>
    <label for="mpQs">Combien ?</label>
    <div class="qte-mp"><input id="mpQs" inputmode="numeric" pattern="[0-9]*" autocomplete="off">
      <button type="button" class="chip" id="mpTout">Tout · ${ligne.quantite}</button></div>
    <label for="mpNote">Pour quoi ? <span class="muted">(facultatif)</span></label>
    <div class="chips" style="margin-bottom:8px">${MOTIFS_SORTIE_MP.map(m =>
      `<button type="button" class="chip" data-motif="${esc(m)}">${esc(m)}</button>`).join('')}</div>
    <input id="mpNote" placeholder="Ou écris-le" autocomplete="off" maxlength="200">
    <div class="manque" id="mpManque"></div>
    <button class="btn orange" id="mpSortOk" disabled>Sortir</button>
    <button class="btn ghost" id="mpAnnul">Annuler</button>
  </div>`;
  zone.scrollIntoView({ block: 'nearest', behavior: 'smooth' });

  const qte = $('#mpQs'), note = $('#mpNote'), bouton = $('#mpSortOk');
  const maj = () => {
    const n = lireQuantite(qte.value);
    const trop = n && n > ligne.quantite;
    bouton.disabled = !n || trop;
    bouton.textContent = !n ? 'Indique la quantité'
      : trop ? `Il n’y en a que ${ligne.quantite}`
      : n === ligne.quantite ? `Tout sortir — ${quantiteMP(n, ligne.famille)}`
      : `Sortir ${quantiteMP(n, ligne.famille)} — il en restera ${ligne.quantite - n}`;
  };
  qte.oninput = maj;
  qte.onkeydown = (ev) => { if (ev.key === 'Enter' && !bouton.disabled) { ev.preventDefault(); bouton.click(); } };
  $('#mpTout').onclick = () => { qte.value = String(ligne.quantite); maj(); };
  zone.querySelectorAll('[data-motif]').forEach(b => b.onclick = () => {
    note.value = b.dataset.motif;
    zone.querySelectorAll('[data-motif]').forEach(x => x.classList.toggle('on', x === b));
  });
  $('#mpAnnul').onclick = () => { zone.innerHTML = ''; };
  qte.focus();

  bouton.onclick = async () => {
    const n = lireQuantite(qte.value);
    if (!n || n > ligne.quantite) { maj(); return; }
    bouton.disabled = true;
    bouton.textContent = 'Enregistrement…';
    try {
      const r = await api('/mp/sortir/', { method: 'POST', body: {
        ligne: ligne.id, quantite: n, note: note.value.trim() } });
      const phrase = `Sorti : ${quantiteMP(n, ligne.famille)} ${ligne.code} de ${d.code}·${ligne.place}`
        + (r.reste ? ` — il en reste ${r.reste}.` : ' — la place est vide pour ce code.');
      toast(phrase, 'ok');
      chargerAlertes();
      redessiner(phrase, { alerte: phraseSeuil(r.article) });
    } catch (e) {
      const manque = $('#mpManque');
      if (manque) { manque.textContent = e.message; maj(); } else toast(e.message, 'err');
    }
  };
  maj();
}

/* --- Changer d'emplacement --------------------------------------------------
   Déplacer une palette, c'était la sortir puis la rentrer : deux saisies, et
   au journal une « sortie » qui comptait comme une consommation. Ici, un geste
   et une ligne de journal par ligne déplacée — d'où, vers où. On choisit ce
   qui part, puis l'arrivée —
   scannée ou tapée — et sa place. Ce que l'arrivée refuserait se dit avant le
   geste, avec la même règle que le serveur, qui la redit au besoin.          */

/** Pourquoi ces lignes ne peuvent pas aller sur cet emplacement — '' si elles
    le peuvent. `e` vient de la liste des emplacements ou de `/mp/emplacement/` :
    les deux portent `est_mp`, `actif`, `usage` et `codes_acceptes[].code`. */
function refusArrivee(e, parties) {
  if (!e.est_mp) return `${e.code} range des cabines.`;
  if (e.actif === false) return `${e.code} est hors service.`;
  const famille = parties.length ? parties[0].famille : e.usage;
  if (e.usage !== famille) {
    return `${e.code} range des ${(FAMILLES_MP[e.usage] || { plusieurs: e.usage }).plusieurs}.`;
  }
  const acceptes = (e.codes_acceptes || []).map(a => a.code);
  if (acceptes.length) {
    const refuses = [...new Set(parties.filter(l => !acceptes.includes(l.code)).map(l => l.code))];
    if (refuses.length) {
      return `${e.code} est réservé à ${listeCodes(acceptes)} : ${listeCodes(refuses)} n’y ${
        refuses.length > 1 ? 'vont' : 'va'} pas.`;
    }
  }
  return '';
}

/** Le bouton du geste : ce qui part, combien, et où — lu avant d'appuyer. */
function phraseDeplacement(items, vers) {
  if (items.length === 1) return `Déplacer ${items[0].quantite} ${items[0].code} vers ${vers}`;
  const total = items.reduce((n, x) => n + x.quantite, 0);
  return `Déplacer ${items.length} lignes — ${quantiteMP(total, items[0].famille)} — vers ${vers}`;
}

/** Ce que dit l'écran une fois le geste fait, d'après la réponse du serveur. */
function phraseDeplace(deplaces) {
  if (!deplaces || !deplaces.length) return '';
  return `Déplacé : ${listeCodes(deplaces.map(x => `${x.quantite} ${x.code}`))} vers ${deplaces[0].destination}.`;
}

/** Changer d'emplacement : combien de chaque ligne, vers où, à quelle place.

    Une ligne part entière si l'on ne dit rien — c'est la palette qu'on
    déplace, et le bouton dit « les 19 » avant qu'on appuie ; une quantité
    tapée n'en déplace qu'une partie. Les places d'arrivée se touchent, et
    rien n'est choisi d'office. */
function ouvrirDeplacementMP(d, parties, redessiner, retour, libelleRetour) {
  const zone = $('#mpAct');
  if (!zone) return;
  const fam = FAMILLES_MP[d.famille] || FAMILLES_MP.vitrage;
  let arrivee = null;      // le contenu de l'emplacement d'arrivée, une fois choisi
  let place = null;
  let resultats = [];
  // Un écran qui a déjà sa caméra — « Trouver », « Scanner une colonne » —
  // n'en reçoit pas une deuxième : les deux porteraient les mêmes repères, et
  // c'est la sienne que le bouton allumerait, branchée pour de bon sur ce
  // déplacement. L'arrivée s'y tape, ou se choisit dans la liste.
  const autreCamera = document.getElementById('cam');
  const scanner = !(autreCamera && !zone.contains(autreCamera));

  zone.innerHTML = `<div class="mp-panneau">
    <div class="sec" style="margin-top:0">Changer d’emplacement — ${parties.length} ligne${parties.length > 1 ? 's' : ''}</div>
    <div class="dep-lignes">${parties.map(l => `<div class="dep-ligne">
        <div class="r"><span class="code-mp">${esc(l.code)}</span>
          <span class="meta">${esc(d.code)}·${esc(l.place)} — ${l.quantite} en place</span></div>
        <div class="qte-mp"><input data-qte="${l.id}" inputmode="numeric" pattern="[0-9]*" autocomplete="off"
            placeholder="tout" aria-label="Combien de ${esc(l.code)} — vide : les ${l.quantite}">
          <span class="aide" style="margin:0">vide : les ${l.quantite}</span></div>
      </div>`).join('')}</div>
    <label for="mpVers">Vers quel emplacement ?</label>
    <div class="vers-mp">
      <input id="mpVers" placeholder="${scanner ? 'Ex. AH510 — ou scanne son étiquette' : 'Ex. AH510'}" autocomplete="off"
             autocapitalize="characters" spellcheck="false">
      ${scanner ? `<button type="button" class="btn ghost" id="mpVersScan" aria-label="Scanner l’étiquette de l’arrivée">${
        icon('scan', 20)}</button>` : ''}
    </div>
    <div id="mpVersCam"></div>
    <div class="list" id="mpVersSugg"></div>
    <div id="mpArriveeVue"></div>
    <div class="manque" id="mpDepManque"></div>
    <button class="btn orange" id="mpDepOk" disabled>Choisis l’emplacement d’arrivée</button>
    <button class="btn ghost" id="mpDepRetour">${esc(libelleRetour || 'Annuler')}</button>
  </div>`;
  zone.scrollIntoView({ block: 'nearest', behavior: 'smooth' });

  const champ = zone.querySelector('#mpVers');
  const bouton = zone.querySelector('#mpDepOk');
  const dire = (texte) => { const m = zone.querySelector('#mpDepManque'); if (m) m.textContent = texte || ''; };

  const lireQuantites = () => parties.map(l => {
    const saisie = zone.querySelector(`[data-qte="${l.id}"]`);
    const brut = saisie ? saisie.value.trim() : '';
    if (!brut) return { ligne: l, n: l.quantite, tout: true, faux: false };
    const n = lireQuantite(brut);
    return { ligne: l, n, tout: false, faux: !n || n > l.quantite };
  });

  const maj = () => {
    const q = lireQuantites();
    const fausse = q.find(x => x.faux);
    const manque = fausse ? `${fausse.ligne.code} : ${fausse.n
        ? `il n’y en a que ${fausse.ligne.quantite}` : 'quantité illisible'}`
      : !arrivee ? 'Choisis l’emplacement d’arrivée'
      : !place ? 'Touche la place d’arrivée' : '';
    bouton.disabled = Boolean(manque);
    bouton.textContent = manque || phraseDeplacement(
      q.map(x => ({ code: x.ligne.code, quantite: x.n, famille: x.ligne.famille })),
      `${arrivee.code}·${place}`);
  };

  const dessinerArrivee = () => {
    const vueArr = zone.querySelector('#mpArriveeVue');
    if (!vueArr || !arrivee) return;
    const ici = String(arrivee.emplacement) === String(d.emplacement);
    const acceptes = (arrivee.codes_acceptes || []).map(a => a.code);
    vueArr.innerHTML = `<div class="mp-choisi"><b>${esc(arrivee.code)}</b>${ici ? ' — le même emplacement, une autre place' : ''}
        — ${arrivee.nb_lignes ? `${esc(quantiteMP(arrivee.quantite, arrivee.famille))} déjà posés` : 'vide'}${
        acceptes.length ? ` · réservé à ${esc(listeCodes(acceptes))}` : ''}</div>
      <label>Place d’arrivée</label>
      ${placesMPHTML(arrivee, { exclues: ici ? new Set(parties.map(l => l.place)) : null })}`;
    vueArr.querySelectorAll('#mpPlaces .place').forEach(b => {
      if (b.disabled) return;
      b.onclick = () => {
        place = b.dataset.place;
        vueArr.querySelectorAll('#mpPlaces .place').forEach(x =>
          x.setAttribute('aria-pressed', String(x.dataset.place === place)));
        maj();
      };
    });
  };

  /** Retient l'arrivée — par son identifiant (liste) ou par son code (saisie,
      étiquette scannée). Rend le refus à dire, ou '' : la caméra s'en sert. */
  const choisirArrivee = async (cible) => {
    let dest;
    try {
      dest = await api('/mp/emplacement/?' + (cible.id
        ? 'id=' + encodeURIComponent(cible.id)
        : 'code=' + encodeURIComponent(String(cible.code || '').replace(/^(LOC|CAB):/i, '').trim())));
    } catch (e) { dire(e.message); return e.message; }
    if (!zone.isConnected) return '';
    const refus = dest.est_mp ? refusArrivee(dest, parties) : (dest.refus || `${dest.code} range des cabines.`);
    if (refus) { dire(refus); return refus; }
    arrivee = dest;
    place = null;
    dire('');
    champ.value = dest.code;
    const boite = zone.querySelector('#mpVersSugg');
    if (boite) boite.innerHTML = '';
    dessinerArrivee();
    maj();
    return '';
  };

  // L'arrivée a été retenue — Entrée, étiquette scannée — pendant qu'une
  // recherche attendait son tour : la liste n'a plus lieu d'être.
  const dejaRetenue = () => Boolean(arrivee)
    && champ.value.replace(/^LOC:/i, '').trim().toUpperCase() === String(arrivee.code).toUpperCase();
  const proposer = debounce(async () => {
    const t = champ.value.replace(/^LOC:/i, '').trim();
    const boite = zone.querySelector('#mpVersSugg');
    if (!boite) return;
    if (!t || dejaRetenue()) { boite.innerHTML = ''; return; }
    try {
      const res = (await api(`/emplacements/?usage=${encodeURIComponent(d.famille)}&search=${encodeURIComponent(t)}`)).results || [];
      // On a tapé, ou retenu l'arrivée, entre-temps.
      if (champ.value.replace(/^LOC:/i, '').trim() !== t || dejaRetenue()) return;
      resultats = res.slice(0, 6);
      boite.innerHTML = resultats.map(e => {
        const refus = refusArrivee(e, parties);
        return `<div class="item${refus ? ' indisponible' : ''}" data-vers="${e.id}">
          <div class="r">${esc(e.code)}${String(e.id) === String(d.emplacement) ? ' <span class="pill">ici</span>' : ''} ${etiquetteEtat(e)}</div>
          ${refus ? `<div class="d">${esc(refus)}</div>` : ''}</div>`;
      }).join('') || `<div class="empty" style="padding:12px">Aucun emplacement de ${esc(fam.plusieurs)} ne correspond.</div>`;
      boite.querySelectorAll('[data-vers]').forEach(n => n.onclick = () => {
        const e = resultats.find(x => String(x.id) === n.dataset.vers);
        if (e && !refusArrivee(e, parties)) choisirArrivee({ id: e.id });
      });
    } catch (e) { boite.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }, 200);

  champ.oninput = () => {
    if (arrivee) {
      arrivee = null;
      place = null;
      zone.querySelector('#mpArriveeVue').innerHTML = '';
      maj();
    }
    dire('');
    proposer();
  };
  champ.onkeydown = (ev) => {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    if (champ.value.trim()) choisirArrivee({ code: champ.value });
  };
  zone.querySelectorAll('[data-qte]').forEach(c => { c.oninput = maj; });
  const boutonScan = zone.querySelector('#mpVersScan');
  if (boutonScan) boutonScan.onclick = () => {
    const cam = zone.querySelector('#mpVersCam');
    if (!cam) return;
    cam.innerHTML = blocCameraHTML('Scanner l’emplacement d’arrivée',
                                   'L’étiquette du rack ou du chevalet où ça va');
    brancherCamera(async (texte) => {
      const refus = await choisirArrivee({ code: texte });
      // Lue et retenue : la caméra a fini son travail, son cadre part avec elle.
      if (!refus) setTimeout(() => { if (!CAMERA) cam.innerHTML = ''; }, 600);
      return refus;
    });
    const allumer = $('#camGo');
    if (allumer) allumer.click();
    cam.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
  zone.querySelector('#mpDepRetour').onclick = () => { arreterCamera(); retour(); };

  bouton.onclick = async () => {
    const q = lireQuantites();
    if (q.some(x => x.faux) || !arrivee || !place) { maj(); return; }
    bouton.disabled = true;
    bouton.textContent = 'Enregistrement…';
    try {
      // La quantité LUE à l'écran part, « tout » compris : si un autre poste a
      // complété la ligne entre-temps, on déplace ce qu'on a vu — le serveur
      // refuse si la ligne a baissé, au lieu de déplacer autre chose.
      const r = await api('/mp/deplacer/', { method: 'POST', body: {
        lignes: q.map(x => ({ ligne: x.ligne.id, quantite: x.n })),
        emplacement: arrivee.emplacement, place: place } });
      arreterCamera();
      const phrase = phraseDeplace(r.deplaces);
      toast(phrase, 'ok');
      chargerAlertes();
      const ailleurs = String(arrivee.emplacement) !== String(d.emplacement);
      redessiner(phrase, { arrivee: ailleurs ? { id: arrivee.emplacement, code: arrivee.code } : null });
    } catch (e) {
      dire(e.message);
      maj();
    }
  };
  maj();
}

/* --- Le stock MP : le Stock côté matières premières ------------------------
   Une ligne par code, avec ses positions : la question posée est « où sont
   les VITR.445, et combien en reste-t-il ? ». Les filtres sont ceux de la
   matière — famille, fournisseur, génération, seuil — et non ceux des cabines. */

//: Le Stock s'ouvre sur ce qu'on a regardé en dernier, sur CE téléphone.
let PARC_MODE = (() => {
  try { return localStorage.getItem('wms_parc') === 'mp' ? 'mp' : 'cabines'; }
  catch (_) { return 'cabines'; }
})();

function choisirParc(mode) {
  PARC_MODE = mode === 'mp' ? 'mp' : 'cabines';
  try { localStorage.setItem('wms_parc', PARC_MODE); } catch (_) {}
}

/** Les deux boutons du haut du Stock : cabines, ou matières premières. */
function basculeParc() {
  const bouton = (mode, ic, libelle) => `<button type="button" role="tab" data-parc="${mode}"
      aria-selected="${String(PARC_MODE === mode)}">${icon(ic, 19)}<span>${libelle}</span></button>`;
  return `<div class="bascule-parc" role="tablist" aria-label="Que chercher ?">
    ${bouton('cabines', 'build', 'Cabines')}${bouton('mp', 'couches', 'MP')}</div>`;
}

function brancherBasculeParc() {
  el().querySelectorAll('[data-parc]').forEach(b => b.onclick = () => {
    if (b.dataset.parc === PARC_MODE) return;
    choisirParc(b.dataset.parc);
    renderCabines();
  });
}

const FILTRES_MP_VIDE = () => ({ q: '', famille: '', fournisseur: '', rack: '',
                                 generation: '', sous_seuil: '', tous: '', tri: 'code' });
let FILTRES_MP = FILTRES_MP_VIDE();
let OPTIONS_MP = { fournisseurs: [], racks: [], familles: {}, tris: [] };
let PANNEAU_MP = null;

//: Mettre le curseur dans la recherche au prochain affichage — une seule fois.
let CHERCHER_MP = false;

/* Régler les seuils d'alerte en nombre : un mode du Stock MP, comme la
   sélection dans le plan d'un rack. Les codes s'y cochent au lieu d'ouvrir
   leur fiche, et une barre en bas dit combien et propose le réglage.
   `null` hors du mode ; sinon les identifiants cochés, et la case « codes
   sans stock » telle qu'elle était — le mode l'allume, un seuil se règle
   AUSSI pour un code à zéro, c'est même pour lui qu'il sert d'abord.      */
let SEUILS_MP = null;
//: La dernière liste affichée : « Toute la liste » coche ce qu'on voit.
let LISTE_MP = [];

/** Ouvre le Stock côté MP, éventuellement sur un filtre déjà posé. */
function ouvrirStockMP(preset, options = {}) {
  choisirParc('mp');
  SEUILS_MP = null;
  FILTRES_MP = Object.assign(FILTRES_MP_VIDE(), preset || {});
  CHERCHER_MP = Boolean(options.chercher);
  go('cabines');
}

function entrerReglageSeuils() {
  // `connus` garde chaque code coché tel qu'on l'a vu : un filtre changé
  // entre-temps peut le faire sortir de la liste, il reste coché et nommé.
  SEUILS_MP = { ids: new Set(), connus: new Map(), tousAvant: FILTRES_MP.tous };
  FILTRES_MP.tous = '1';
  renderStockMP();
}

/** Sort du mode et rend à la case « codes sans stock » sa valeur d'avant. */
function quitterReglageSeuils(redessiner = true) {
  if (!SEUILS_MP) return;
  FILTRES_MP.tous = SEUILS_MP.tousAvant;
  SEUILS_MP = null;
  if (redessiner) renderStockMP();
}

const CHAMPS_MP = { famille: '#mFa', fournisseur: '#mFo', rack: '#mRk', generation: '#mGe', tri: '#mTr' };

const CHIPS_MP = () => [
  ['vitrage', 'Vitrages', { famille: 'vitrage' }],
  ['carton', 'Cartons', { famille: 'carton' }],
  ['ancienne', 'Ancienne génération', { generation: 'ancienne' }],
  ['sous_seuil', 'Sous le seuil d’alerte', { sous_seuil: '1' }],
];

const filtreMPActif = (poses) => Object.entries(poses).every(([k, v]) => FILTRES_MP[k] === v);

function requeteMP() {
  const vide = FILTRES_MP_VIDE();
  return Object.entries(FILTRES_MP)
    .filter(([k, v]) => v !== '' && !(k === 'tri' && v === vide.tri))
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
}

async function renderStockMP() {
  const options = await api('/mp/filtres/').catch(() => null);
  if (options) OPTIONS_MP = options;
  const opts = (liste, choisie, tous) => `<option value="">${esc(tous)}</option>`
    + liste.map(([v, l]) => `<option value="${esc(v)}"${String(choisie) === String(v) ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const deplie = PANNEAU_MP !== null ? PANNEAU_MP
    : Boolean(window.matchMedia && window.matchMedia('(min-width:1024px)').matches);
  const regler = peut('mp_seuils');
  // Le mode n'a de sens qu'avec le droit de régler : un compte qui ne l'a pas
  // n'y reste pas, d'où qu'il y soit arrivé.
  if (SEUILS_MP && !regler) quitterReglageSeuils(false);

  layout(`<h2 class="title">Stock</h2>
    ${basculeParc()}
    <input id="mQ" class="recherche" type="search" autocomplete="off" spellcheck="false"
           placeholder="Code, dimension, emplacement…" value="${esc(FILTRES_MP.q)}">
    <div class="chips" id="mChips"></div>
    <details class="filtres" id="mPan"${deplie ? ' open' : ''}>
      <summary><span id="mTitre">Filtres</span></summary>
      <div class="grille-filtres">
        <div><label for="mFa">Famille</label>
          <select id="mFa">${opts([['vitrage', 'Vitrages'], ['carton', 'Cartons']], FILTRES_MP.famille, 'Toutes')}</select></div>
        <div><label for="mFo">Fournisseur</label>
          <select id="mFo">${opts((OPTIONS_MP.fournisseurs || []).map(f => [f, f]), FILTRES_MP.fournisseur, 'Tous')}</select></div>
        <div><label for="mRk">Rack</label>
          <select id="mRk">${opts((OPTIONS_MP.racks || []).map(r => [r, r]), FILTRES_MP.rack, 'Tous')}</select></div>
        <div><label for="mGe">Génération</label>
          <select id="mGe">${opts([['actuelle', 'Actuelle'], ['ancienne', 'Ancienne']], FILTRES_MP.generation, 'Toutes')}</select></div>
        <div><label for="mTr">Trier par</label>
          <select id="mTr">${(OPTIONS_MP.tris || [{ code: 'code', libelle: 'Code' }]).map(t =>
            `<option value="${esc(t.code)}"${FILTRES_MP.tri === t.code ? ' selected' : ''}>${esc(t.libelle)}</option>`).join('')}</select></div>
      </div>
      <label class="case"><input type="checkbox" id="mTous"${FILTRES_MP.tous === '1' ? ' checked' : ''}>
        <span>Montrer aussi les codes sans stock — toute la base</span></label>
    </details>
    <div id="mActifs"></div>
    <div class="row actions-stock">
      <button class="btn ghost" id="mExport" style="margin-top:0">${icon('in', 17)} Télécharger le stock MP (Excel)</button>
      ${regler ? `<button class="btn ${SEUILS_MP ? '' : 'ghost'}" id="mSeuils" style="margin-top:0">${SEUILS_MP
        ? 'Terminer le réglage des seuils' : `${icon('cloche', 17)} Régler les seuils d’alerte`}</button>` : ''}
    </div>
    ${SEUILS_MP ? `<div class="aide" style="margin:10px 2px 0">Touche les codes à régler — ou « Toute la
      liste », après l’avoir resserrée avec les filtres. Le même seuil s’appliquera à tous.</div>` : ''}
    <div id="zone"><div class="empty">Chargement…</div></div>
    ${SEUILS_MP ? '<div class="selbar" id="mSelbar"></div>' : ''}`, 'cabines');
  brancherBasculeParc();

  Object.entries(CHAMPS_MP).forEach(([cle, sel]) => {
    const n = $(sel);
    if (n) n.onchange = () => { FILTRES_MP[cle] = n.value; majEtListerMP(); };
  });
  $('#mPan').ontoggle = (ev) => { PANNEAU_MP = ev.target.open; };
  $('#mQ').oninput = debounce(() => { FILTRES_MP.q = $('#mQ').value.trim(); majEtListerMP(); }, 250);
  $('#mTous').onchange = () => { FILTRES_MP.tous = $('#mTous').checked ? '1' : ''; majEtListerMP(); };
  $('#mExport').onclick = exporterStockMP;
  const boutonSeuils = $('#mSeuils');
  if (boutonSeuils) boutonSeuils.onclick = () => (SEUILS_MP ? quitterReglageSeuils() : entrerReglageSeuils());
  if (CHERCHER_MP) { CHERCHER_MP = false; $('#mQ').focus(); }
  majEtListerMP();
}

function synchroniserChampsMP() {
  Object.entries(CHAMPS_MP).forEach(([cle, sel]) => {
    const n = $(sel);
    if (n && n.value !== FILTRES_MP[cle]) n.value = FILTRES_MP[cle];
  });
  const q = $('#mQ');
  if (q && q.value !== FILTRES_MP.q) q.value = FILTRES_MP.q;
  const tous = $('#mTous');
  if (tous) tous.checked = FILTRES_MP.tous === '1';
}

function majEtListerMP() {
  const boite = $('#mChips');
  if (boite) {
    const c = OPTIONS_MP || {};
    const nombre = {
      vitrage: ((c.familles || {}).vitrage || {}).codes,
      carton: ((c.familles || {}).carton || {}).codes,
      ancienne: c.ancienne_generation, sous_seuil: c.sous_seuil,
    };
    boite.innerHTML = CHIPS_MP().map(([cle, libelle, poses]) =>
      `<button type="button" class="chip ${filtreMPActif(poses) ? 'on' : ''}" data-chip="${cle}">
        ${esc(libelle)}${nombre[cle] === undefined ? '' : `<span class="n">${nombre[cle]}</span>`}</button>`).join('');
    boite.querySelectorAll('[data-chip]').forEach(b => b.onclick = () => {
      const [, , poses] = CHIPS_MP().find(x => x[0] === b.dataset.chip);
      const actif = filtreMPActif(poses);
      const vide = FILTRES_MP_VIDE();
      Object.keys(poses).forEach(k => { FILTRES_MP[k] = actif ? vide[k] : poses[k]; });
      synchroniserChampsMP();
      majEtListerMP();
    });
  }
  const vide = FILTRES_MP_VIDE();
  const n = Object.keys(vide).filter(k => k !== 'tri' && k !== 'q' && FILTRES_MP[k] !== vide[k]).length;
  const titre = $('#mTitre');
  if (titre) titre.textContent = n ? `Filtres (${n})` : 'Filtres';
  const zone = $('#mActifs');
  if (zone) {
    const morceaux = [];
    if (FILTRES_MP.q) morceaux.push(`« ${FILTRES_MP.q} »`);
    if (FILTRES_MP.famille) morceaux.push(FAMILLES_MP[FILTRES_MP.famille].plusieurs);
    if (FILTRES_MP.fournisseur) morceaux.push('fournisseur ' + FILTRES_MP.fournisseur);
    if (FILTRES_MP.rack) morceaux.push('rack ' + FILTRES_MP.rack);
    if (FILTRES_MP.generation) morceaux.push('génération ' + FILTRES_MP.generation);
    if (FILTRES_MP.sous_seuil) morceaux.push('sous le seuil d’alerte');
    if (FILTRES_MP.tous) morceaux.push('codes sans stock inclus');
    zone.innerHTML = morceaux.length
      ? `<div class="actifs"><span>${esc(morceaux.join(' · '))}</span>
           <button type="button" class="lien" data-vider>Tout effacer</button></div>` : '';
    const vider = zone.querySelector('[data-vider]');
    if (vider) vider.onclick = () => { FILTRES_MP = FILTRES_MP_VIDE(); synchroniserChampsMP(); majEtListerMP(); };
  }
  listerStockMP();
}

/** Le seuil d'un code, dit comme on le lit dans une liste. */
const libelleSeuil = (a) => (a.seuil_reappro ? `seuil d’alerte ${a.seuil_reappro}` : '');

/** Une carte par code : son total, et chacune de ses positions. En réglage des
    seuils, la carte se coche (`choisi` vaut alors vrai ou faux). */
function ligneArticleMP(a, choisi) {
  const positions = (a.positions || []).map(p =>
    `<span class="jeton">${esc(p.position)} <b>${p.quantite}</b></span>`).join('');
  const seuil = libelleSeuil(a);
  return `<div class="item article-mp" data-cle="${a.id}"${choisi === undefined ? ''
      : ` role="button" aria-pressed="${String(Boolean(choisi))}"`}>
    <div class="r"><span class="famille-mp ${esc(a.famille)}">${esc(FAMILLES_MP[a.famille] ? FAMILLES_MP[a.famille].titre : a.famille)}</span>
      <span class="code-mp">${esc(a.code)}</span>${badgeAncienne(a)}
      ${a.sous_seuil ? '<span class="etat crit">sous le seuil</span>' : ''}
      <span class="total">${a.en_stock || 0}</span></div>
    <div class="d">${sousTitreArticle(a)}${seuil ? ` · <span class="seuil-mp">${esc(seuil)}</span>` : ''}</div>
    ${positions ? `<div class="positions">${positions}</div>` : '<div class="meta">Aucun en stock.</div>'}
  </div>`;
}

function ouvrirFicheArticleMP(a) {
  ouvrirEcran(() => ficheArticleMP(a, () => history.back()), 'fiche-mp');
}

async function listerStockMP() {
  const zone = $('#zone');
  if (!zone) return;
  const q = requeteMP();
  try {
    const liste = await api('/mp/stock/' + (q ? '?' + q : ''));
    if (requeteMP() !== q || !$('#zone')) return;     // les filtres ont changé entre-temps
    LISTE_MP = liste;
    const total = liste.reduce((n, a) => n + (a.en_stock || 0), 0);
    zone.innerHTML = `<div class="sec">${liste.length} code${liste.length === 1 ? '' : 's'}${
        total ? ` · ${total} pièce${total === 1 ? '' : 's'} en stock` : ''}</div>
      <div class="list${SEUILS_MP ? ' a-cocher' : ''}" data-liste>${liste.length
        ? liste.map(a => ligneArticleMP(a, SEUILS_MP ? SEUILS_MP.ids.has(a.id) : undefined)).join('')
        : `<div class="empty">${requeteMP() ? 'Rien ne correspond à ces filtres. Essaie d’en retirer un.'
                                            : 'Aucune matière première en stock pour l’instant.'}</div>`}</div>`;
    zone.querySelectorAll('[data-cle]').forEach(n => n.onclick = () => {
      const a = liste.find(x => String(x.id) === n.dataset.cle);
      if (!a) return;
      if (!SEUILS_MP) { ouvrirFicheArticleMP(a); return; }
      if (SEUILS_MP.ids.has(a.id)) SEUILS_MP.ids.delete(a.id);
      else { SEUILS_MP.ids.add(a.id); SEUILS_MP.connus.set(a.id, a); }
      n.setAttribute('aria-pressed', String(SEUILS_MP.ids.has(a.id)));
      barreSeuils();
    });
    barreSeuils();
  } catch (e) { zone.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

/** La barre du réglage des seuils : combien de codes cochés, et le geste. */
function barreSeuils() {
  const barre = $('#mSelbar');
  if (!barre || !SEUILS_MP) return;
  const n = SEUILS_MP.ids.size;
  const visibles = LISTE_MP.filter(a => !SEUILS_MP.ids.has(a.id)).length;
  // La barre est l'élément collant lui-même : enveloppée dans un bloc à sa
  // taille, elle n'aurait nulle part où glisser et resterait au bas de la
  // liste, hors de vue.
  barre.innerHTML = `<div class="sel-n">${n ? `${n} code${n > 1 ? 's' : ''} coché${n > 1 ? 's' : ''}` : 'Touche les codes à régler'}</div>
    <div class="row">
      <button class="btn orange" id="mSeuilGo" style="margin-top:0"${n ? '' : ' disabled'}>${icon('cloche', 17)} Seuil d’alerte${
        n ? ` pour ${n} code${n > 1 ? 's' : ''}` : ''}</button>
    </div>
    <div class="row" style="margin-top:8px">
      <button class="btn ghost" id="mSeuilTout" style="margin-top:0"${visibles ? '' : ' disabled'}>Toute la liste</button>
      <button class="btn ghost" id="mSeuilVider" style="margin-top:0"${n ? '' : ' disabled'}>Tout décocher</button>
    </div>`;
  barre.querySelector('#mSeuilGo').onclick = () => {
    const codes = [...SEUILS_MP.ids].map(id => SEUILS_MP.connus.get(id)).filter(Boolean);
    ouvrirReglageSeuils(codes, () => quitterReglageSeuils());
  };
  barre.querySelector('#mSeuilTout').onclick = () => {
    LISTE_MP.forEach(a => { SEUILS_MP.ids.add(a.id); SEUILS_MP.connus.set(a.id, a); });
    listerStockMP();
  };
  barre.querySelector('#mSeuilVider').onclick = () => {
    SEUILS_MP.ids = new Set();
    listerStockMP();
  };
}

/** Un seuil tapé → un entier (0 et vide : pas d'alerte, `null`), ou `undefined`
    s'il est illisible. La même lecture que le serveur. */
function lireSeuil(brut) {
  const t = String(brut == null ? '' : brut).replace(/\s/g, '');
  if (t === '') return null;
  if (!/^\d+$/.test(t)) return undefined;
  const n = parseInt(t, 10);
  return n > 0 ? n : null;
}

/** Le seuil d'alerte d'un ou de plusieurs codes, d'un geste. `apres` : ce qui
    se passe une fois le seuil écrit — redessiner la fiche, quitter le mode. */
function ouvrirReglageSeuils(articles, apres) {
  const n = articles.length;
  if (!n) return;
  const parValeur = new Map();
  articles.forEach(a => {
    const v = a.seuil_reappro ? String(a.seuil_reappro) : '';
    parValeur.set(v, (parValeur.get(v) || 0) + 1);
  });
  // Ce qui est réglé aujourd'hui : on ne remplace pas à l'aveugle.
  const actuel = n === 1
    ? (articles[0].seuil_reappro ? `Seuil d’alerte actuel : ${articles[0].seuil_reappro}.` : 'Pas de seuil d’alerte aujourd’hui.')
    : 'Aujourd’hui : ' + [...parValeur.entries()].map(([v, k]) =>
        `${v ? `seuil ${v}` : 'pas de seuil'} pour ${k} code${k > 1 ? 's' : ''}`).join(', ') + '.';
  const anciens = articles.filter(a => a.ancienne_generation).map(a => a.code);
  const corps = modale(`Seuil d’alerte — ${n} code${n > 1 ? 's' : ''}`, `
    <div class="meta" style="margin-top:0;word-break:break-word">${esc(listeCodes(articles.map(a => a.code), 6))}</div>
    <div class="aide">${esc(actuel)}</div>
    <label for="sValeur">Nouveau seuil d’alerte</label>
    <input id="sValeur" inputmode="numeric" pattern="[0-9]*" autocomplete="off" placeholder="Ex. 20"
           value="${n === 1 && articles[0].seuil_reappro ? esc(String(articles[0].seuil_reappro)) : ''}">
    <div class="aide">La cloche sonne quand le stock total ${n > 1 ? 'd’un de ces codes' : 'du code'} passe
      <b>en dessous</b> de ce nombre. Vide : plus d’alerte.</div>
    ${anciens.length ? `<div class="aide alerte">${esc(listeCodes(anciens))} : ancienne génération — elle
      s’écoule, son seuil ne déclenchera pas d’alerte.</div>` : ''}
    <div class="manque" id="sManque"></div>
    <div class="modal-actions">
      <button class="btn orange" id="sOk" type="button">Enregistrer</button>
      <button class="btn ghost" id="sNon" type="button">Annuler</button>
    </div>`);
  const champ = corps.querySelector('#sValeur'), ok = corps.querySelector('#sOk');
  const maj = () => {
    const v = lireSeuil(champ.value);
    ok.disabled = v === undefined;
    ok.textContent = v === undefined ? 'Un nombre entier, ou rien'
      : v === null ? `Plus d’alerte pour ${n > 1 ? `ces ${n} codes` : 'ce code'}`
      : `Seuil ${v} pour ${n > 1 ? `ces ${n} codes` : 'ce code'}`;
  };
  champ.oninput = maj;
  champ.onkeydown = (ev) => { if (ev.key === 'Enter' && !ok.disabled) { ev.preventDefault(); ok.click(); } };
  corps.querySelector('#sNon').onclick = fermerModale;
  ok.onclick = async () => {
    const v = lireSeuil(champ.value);
    if (v === undefined) { maj(); return; }
    ok.disabled = true;
    try {
      const r = await api('/mp/seuils/', { method: 'POST', body: {
        articles: articles.map(a => a.id), seuil: v } });
      fermerModale();
      toast(r.seuil ? `Seuil d’alerte ${r.seuil} pour ${r.nombre} code${r.nombre > 1 ? 's' : ''}`
                    : `Plus d’alerte pour ${r.nombre} code${r.nombre > 1 ? 's' : ''}`, 'ok');
      chargerAlertes();
      if (apres) apres(r);
    } catch (e) {
      ok.disabled = false;
      const m = corps.querySelector('#sManque');
      if (m) m.textContent = e.message; else toast(e.message, 'err');
    }
  };
  maj();
  champ.focus();
}

/** Même chemin que l'inventaire des cabines : le fichier passe par le jeton. */
async function exporterStockMP() {
  const bouton = $('#mExport');
  const libelle = bouton ? bouton.innerHTML : '';
  if (bouton) { bouton.disabled = true; bouton.textContent = 'Préparation…'; }
  try {
    const q = requeteMP();
    const r = await fetchReseau(API + '/mp/export/' + (q ? '?' + q : ''),
                                { headers: token ? { Authorization: 'Token ' + token } : {} });
    if (r.status === 401) { logout(); throw new Error('Session expirée, reconnecte-toi.'); }
    if (!r.ok) throw new Error('L’export a été refusé (' + r.status + ').');
    const fichier = await r.blob();
    const nom = ((r.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)/) || [])[1]
      || 'stock-mp.csv';
    const url = URL.createObjectURL(fichier);
    const lien = document.createElement('a');
    lien.href = url; lien.download = nom;
    document.body.appendChild(lien); lien.click(); lien.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    toast('Stock MP exporté : ' + nom, 'ok');
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    if (bouton) { bouton.disabled = false; bouton.innerHTML = libelle; }
  }
}

/** La fiche d'un code : la base, son seuil d'alerte, ses positions — qui
    ouvrent l'emplacement —, les emplacements qui lui sont réservés, et les
    derniers mouvements. */
async function ficheArticleMP(a, retour) {
  ECRAN = 'fiche-mp';
  layout(`<button class="btn ghost retour" id="faRetour">← Retour</button>
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'cabines');
  $('#faRetour').onclick = retour || (() => go('cabines'));
  const zoneFiche = $('#zone');
  let x;
  try { x = await api('/mp/article/?id=' + encodeURIComponent(a.id)); }
  catch (e) { zoneFiche.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (!zoneFiche.isConnected) return;          // l'opérateur est passé à autre chose
  const lignesBase = [
    ['Famille', FAMILLES_MP[x.famille] ? FAMILLES_MP[x.famille].titre : x.famille],
    ['Fournisseur', x.fournisseur], ['N° article', x.numero],
    ['Autres références', x.references],
    ['Colisage', x.colisage ? `${x.colisage} par palette` : ''],
    ['Seuil d’alerte', x.seuil_reappro || 'aucun — pas d’alerte'],
  ].filter(([, v]) => v !== '' && v !== null && v !== undefined);
  const reserves = x.reserve_sur || [];
  zoneFiche.innerHTML = `
    <h2 class="title"><span class="code-mp">${esc(x.code)}</span>${badgeAncienne(x)}</h2>
    ${x.sous_seuil ? `<div class="banner">Sous le seuil d’alerte : ${x.en_stock
      ? `plus que ${esc(quantiteMP(x.en_stock, x.famille))} en stock` : 'plus aucun en stock'}, pour un
      seuil de ${x.seuil_reappro}.</div>` : ''}
    ${x.ancienne_generation ? `<div class="banner">Ancienne génération : le stock restant
      s’écoule, l’entrée demande une confirmation.</div>` : ''}
    ${x.actif ? '' : '<div class="banner">Ce code n’est plus actif dans la base : il ne se propose plus à l’entrée.</div>'}
    <div class="card">
      <div style="font-size:14px;line-height:1.45">${esc(x.designation || '')}</div>
      <div class="specs"><table><tbody>${lignesBase.map(([l, v]) =>
        `<tr><td>${esc(l)}</td><td>${esc(String(v))}</td></tr>`).join('')}</tbody></table></div>
      ${peut('mp_seuils') ? `<button class="btn ghost" id="faSeuil">${icon('cloche', 17)} Régler le seuil d’alerte</button>` : ''}
    </div>
    <div class="sec" style="margin-top:18px">En stock · ${quantiteMP(x.en_stock || 0, x.famille)}${
      x.positions.length > 1 ? ` sur ${x.positions.length} positions` : ''}
      ${x.sous_seuil ? ' · <span class="etat crit">sous le seuil</span>' : ''}</div>
    <div class="list">${x.positions.length ? x.positions.map(p => `<div class="item" data-emp="${p.emplacement}" data-code="${esc(p.code_emplacement)}">
        <div class="r ligne-total">${esc(p.code_emplacement)} · ${esc(p.place)} — ${esc(NOMS_PLACES_MP[p.place] || '')}
          <span class="total">${p.quantite}</span></div>
        <div class="meta">Dernier mouvement le ${esc(new Date(p.modifie_le).toLocaleDateString('fr-FR'))}</div>
      </div>`).join('') : '<div class="empty">Aucun en stock.</div>'}</div>
    ${reserves.length ? `<div class="sec" style="margin-top:18px">Emplacements réservés à ce code · ${reserves.length}</div>
      <div class="list">${reserves.map(e => `<div class="item" data-emp="${e.id}" data-code="${esc(e.code)}">
        <div class="r">${esc(e.code)}</div></div>`).join('')}</div>` : ''}
    <div class="sec" style="margin-top:18px">Derniers mouvements</div>
    <div class="list">${x.mouvements.length ? x.mouvements.map(ligneMouvementMP).join('')
      : '<div class="empty">Aucun mouvement.</div>'}</div>`;
  zoneFiche.querySelectorAll('[data-emp]').forEach(n => n.onclick = () =>
    ouvrirEmplacementMP({ id: n.dataset.emp, code: n.dataset.code }));
  const seuil = zoneFiche.querySelector('#faSeuil');
  if (seuil) seuil.onclick = () => ouvrirReglageSeuils([x], () => ficheArticleMP(a, retour));
}

/** Une ligne du journal MP. Un changement d'emplacement se lit d'où vers où,
    avec ce qui reste aux deux bouts. */
function ligneMouvementMP(m) {
  const deplace = m.type === 'transfert';
  const etat = { entree: 'ok', sortie: 'att', transfert: 'dep' }[m.type] || '';
  const signe = { entree: '+', sortie: '−' }[m.type] || '';
  const ou = deplace
    ? `${esc(m.origine)} → ${esc(m.position)} · reste ${m.reste_origine === null || m.reste_origine === undefined
        ? '—' : m.reste_origine} au départ, ${m.reste} à l’arrivée`
    : `${esc(m.position)} · reste ${m.reste}`;
  return `<div class="item" style="cursor:default">
    <div class="r"><span class="etat ${etat}">${esc(m.type_libelle)}</span>
      ${signe}${m.quantite} <span class="code-mp">${esc(m.code)}</span></div>
    <div class="d">${ou}${m.note ? ' · ' + esc(m.note) : ''}</div>
    <div class="meta">${esc(new Date(m.date).toLocaleString('fr-FR'))}${m.utilisateur_nom ? ' — ' + esc(m.utilisateur_nom) : ''}</div>
  </div>`;
}

async function renderJournalMP() {
  layout(`<h2 class="title">Journal MP</h2>
    <div class="card"><label for="jq">Filtrer</label>
      <input id="jq" placeholder="Code, emplacement, auteur ou motif" autocomplete="off" spellcheck="false">
      <label for="jty">Mouvement</label>
      <select id="jty"><option value="">Tous</option><option value="entree">Entrées</option><option value="sortie">Sorties</option>
        <option value="transfert">Changements d’emplacement</option></select></div>
    <div id="zone"><div class="empty">Chargement…</div></div>`, 'mp');
  const charger = () => {
    const t = $('#jq').value.trim(), ty = $('#jty').value;
    const q = [t ? 'search=' + encodeURIComponent(t) : '', ty ? 'type=' + ty : ''].filter(Boolean).join('&');
    listePaginee($('#zone'), '/mp/journal/' + (q ? '?' + q : ''), {
      ligne: ligneMouvementMP,
      vide: q ? 'Aucun mouvement ne correspond.' : 'Aucun mouvement de matières premières pour l’instant.',
      entete: (total) => `<div class="sec">${total} mouvement${total === 1 ? '' : 's'}</div>`,
    });
  };
  $('#jq').oninput = debounce(charger, 250);
  $('#jty').onchange = charger;
  charger();
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
  layout(`<h2 class="title">Cabines</h2>
    ${rappelEnCours()}
    <div class="meta" style="margin:-4px 0 14px">Deux choses se scannent :
      la <b>fiche</b> collée sur la cabine, et le <b>QR d'un emplacement</b>.
      Les cabines ne portent pas de QR code.</div>
    <div class="gestes">
      <label class="geste" id="sFicheLab">
        <span class="ic">${icon('camera', 26)}</span>
        <span class="t">Photographier la fiche</span>
        <span class="s">Le tableau à deux colonnes, collé sur la cabine</span>
        <input type="file" id="sFiche" accept="image/*" capture="environment">
      </label>
      <button class="geste" id="sQr">
        <span class="ic">${icon('scan', 26)}</span>
        <span class="t">Scanner le QR d’un emplacement</span>
        <span class="s">L’étiquette collée sur l’emplacement</span>
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
   Pas de troisième pastille vers le Stock : l'onglet « Stock » est en bas de
   l'écran en permanence, et un raccourci de plus vers ce qui est déjà à un
   doigt de distance est exactement le doublon qu'on retire partout ailleurs.
   Deux pastilles tiennent aussi sur une seule ligne — trois en font deux. */
const piedGestes = (options = {}) => `<div class="pied">
  ${options.fiche ? `<button id="gFiche">${icon('clip', 16)} Voir sa fiche</button>` : ''}
  <button data-go="scanner">${icon('scan', 16)} ${
    esc(options.suite || 'Une autre cabine')}</button>
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
  // Un geste dont le compte n'a pas la case est éteint, comme les autres
  // gestes impossibles, et dit laquelle manque.
  const faute = (droit) => (peut(droit) ? '' : sansLeDroit(droit));

  const gestes = [];
  if (partie) {
    gestes.push(gesteBouton('gReprendre', 'La remettre en stock',
      'Elle est revenue : retour de chantier, livraison refusée',
      { icone: 'in', empeche: faute('cab_envoyer') }));
  } else if (!range) {
    gestes.push(gesteBouton('gRanger', 'La ranger',
      'Scanner l’emplacement, puis toucher la place',
      { icone: 'in', empeche: faute('cab_ranger') }));
  } else {
    gestes.push(gesteBouton('gDeplacer', 'La déplacer',
      `Elle quitte ${cabine.position} pour un autre emplacement`,
      { icone: 'transfer', empeche: faute('cab_ranger') }));
    gestes.push(gesteBouton('gAjouter', 'Ajouter un emplacement',
      `Elle reste aussi en ${cabine.position}`, { icone: 'plus', empeche: faute('cab_ranger') }));
  }
  if (!partie) {
    // UN seul geste de sortie. Il y en avait deux ici aussi — « la sortir de
    // son emplacement » et « l'envoyer » — aux conséquences opposées et aux
    // libellés jumeaux.
    gestes.push(gesteBouton('gSortir', 'La sortir de l’entrepôt',
      range ? `Définitif : ${cabine.position} se libère et la cabine part`
            : 'Définitif : la cabine part et rejoint les archives',
      { icone: 'out', empeche: faute('cab_envoyer') || sansChantier }));
    gestes.push(quarantaine
      ? gesteBouton('gStatut', 'Lever la quarantaine',
          'Elle redevient conforme', { icone: 'check', empeche: faute('cab_statut') })
      : gesteBouton('gStatut', 'La mettre en quarantaine',
          'Un défaut la bloque : elle ne partira pas',
          { icone: 'alert', empeche: faute('cab_statut') }));
  }

  layout(`<h2 class="title">${esc(cabine.numero)}</h2>
    <div class="card">
      <div class="r" style="font-size:17px;font-weight:700">${
        badgeStatut(cabine, { rangement: false })}
        ${range ? 'Rangée en ' + esc(ouEstLaCabine(cabine)) : 'Non rangée'}</div>
      <div class="meta" style="margin-top:5px">Chantier ${
        cabine.chantier ? esc(cabine.chantier) : '<b>à affecter</b>'}${
        cabine.modele ? ' · ' + esc(cabine.modele) : ''}${
        cabine.client ? ' · ' + esc(cabine.client) : ''}</div>
      <div style="margin-top:12px">${blocQuarantaine(cabine)}</div>
    </div>
    <div class="sec">Que faites-vous ?</div>
    <div class="gestes">${gestes.join('')}</div>
    ${piedGestes({ fiche: true })}`, 'scanner');

  const sur = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  sur('#gFiche', () => ouvrirEcran(() => ficheCabine(cabine, () => rafraichirGestes()), 'fiche'));
  sur('#gRanger', () => versRangement(cabine, null));
  sur('#gDeplacer', () => versRangement(cabine, 'deplacer'));
  sur('#gAjouter', () => versRangement(cabine, 'ajouter'));
  sur('#gSortir', () => sortirDefinitivement(cabine, () => rafraichirGestes()));
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
  if (refuseSansDroit('cab_ranger')) return;
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
    if (REFS_CABINE.fichier_production && !peut('hors_fichier')) blocRefusHorsFichier(numero);
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
      'Ses caractéristiques sont déjà là — rien à recopier',
      { icone: 'in', empeche: peut('cab_ranger') ? '' : sansLeDroit('cab_ranger') })}</div>
    ${piedGestes()}`, 'scanner');
  $('#gEntrer').onclick = () => { ENTREE_NUMERO = numero; go('entree'); };
}

/* --- Les deux choses qui se scannent ---------------------------------------

   La fiche papier collée sur la cabine, et le QR collé sur l’emplacement. Rien
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
                                    'L’étiquette collée sur l’emplacement');
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

/** QR lu et confirmé : c'est un emplacement. On tolère un n° de cabine par
    prudence — un code mal collé ne doit pas être un cul-de-sac. Renvoie la raison
    d'un refus, affichée sur la vidéo ; '' quand l'écran suivant s'est ouvert. */
async function retenirScanEmplacement(texte) {
  const code = String(texte || '').replace(/^(LOC|CAB):/i, '').trim();
  if (!code) return 'Ce QR ne porte aucun code.';
  if (MOTIF_NUMERO_CABINE.test(code)) {
    await arreterCamera();
    ouvrirGestes({ numero: code });
    return '';
  }
  try {
    const res = (await api('/emplacements/?search=' + encodeURIComponent(code))).results || [];
    const e = res.find(x => (x.code || '').toUpperCase() === code.toUpperCase())
           || (res.length === 1 ? res[0] : null);
    if (!e) return `Aucun emplacement ne porte le code « ${code} ». Vérifie l’étiquette, ou saisis le n° de la cabine.`;
    await arreterCamera();
    // `pied: true` : cette fiche est le bout d'un scan, pas une destination du
    // menu. Sans porte de sortie visible, on n'a que l'onglet du bas pour
    // revenir — et l'écran des gestes, lui, en propose une.
    await montrerEmplacement(e, { retour: () => go('scanner'), pied: true });
    return '';
  } catch (err) { return err.message; }
}
