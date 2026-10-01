"""Publie le WMS par un tunnel Cloudflare, sans rien ouvrir sur le pare-feu.

**Solution d'attente**, à n'utiliser que tant que l'accès par le réseau interne
n'est pas ouvert. Ce qu'il faut savoir avant de s'en servir :

- l'adresse produite est **publique** : n'importe qui sur internet qui la
  connaît atteint la page de connexion. Seul le mot de passe protège alors les
  données de l'entrepôt. Des comptes à mots de passe faibles deviennent le seul
  rempart ;
- elle **change à chaque lancement**, et n'est donc pas mémorisable ;
- elle passe par un service tiers, hors du réseau de STRUCTA.

Ce que le tunnel apporte, en échange :

- aucune règle de pare-feu, aucune permission à demander : `cloudflared` ouvre
  une connexion **sortante**, comme un navigateur ;
- un certificat HTTPS reconnu par tous les téléphones — plus aucune autorité à
  installer sur chaque appareil, et la caméra fonctionne aussitôt.

    python outils/demarrer_tunnel.py

Une page locale s'ouvre aussitôt, en « préparation ». Elle se rafraîchit toute
seule et le **QR code y apparaît dès que l'adresse a été vérifiée** — les
caristes scannent l'écran plutôt que de recopier une adresse aléatoire. Tant
qu'aucune adresse ne répond, il n'y a délibérément aucun QR : un QR qui mène à
« page pas trouvée » fait chercher la panne du côté des téléphones.

Le service gratuit de Cloudflare tire le nom d'hôte au sort et sa route ne se
propage pas toujours ; le script essaie donc plusieurs fois, avec plusieurs
réglages, et s'arrête dès qu'une adresse répond vraiment (voir `TENTATIVES` et
`BUDGET_TOTAL`).
"""
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from queue import Empty, Queue
from string import Template

RACINE = Path(__file__).resolve().parent.parent
ADRESSE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
#: Secondes avant d'abandonner l'attente de l'ADRESSE — pas de sa mise en
#: service, qui est mesurée plus loin. 25 et non 90 : un tunnel rapide annonce
#: la sienne en deux à cinq secondes. Passé ce délai il ne l'annoncera plus, et
#: attendre une minute de plus ne fait que retarder la tentative suivante — qui
#: est justement ce qui peut réussir.
ATTENTE_MAX = 25

#: Combien de temps laisser à une adresse pour se mettre à répondre.
#: Cloudflare l'annonce lui-même : « it may take some time to be reachable ».
#:
#: 12 secondes, et non 40. Deux raisons, la seconde étant la vraie :
#:
#: - un essai coûte désormais moins d'une seconde — le nom est résolu une fois
#:   pour toutes AVANT la boucle. Douze secondes font donc une dizaine
#:   d'essais, largement de quoi voir une propagation, qui prend trois à six
#:   secondes dans le cas courant ;
#: - retirer une adresse au sort ne coûte qu'une poignée de secondes. Patienter
#:   quarante secondes devant un nom qui se tait est donc PIRE que d'en tirer un
#:   autre : le nom d'hôte est justement la loterie qu'on essaie de gagner.
ATTENTE_JOIGNABLE = 12

#: Délai d'un essai. Court exprès : derrière un proxy d'entreprise qui ne
#: répond pas, dix secondes par essai transforment le contrôle en attente
#: interminable, alors que le verdict est le même.
DELAI_ESSAI = 3

#: On sonde `/api/sante/` : ouvert sans compte, et il répond 200 seulement si la
#: base répond ET si le schéma est à jour. La page de connexion, elle, aurait
#: répondu 200 même avec une base en panne.
SONDE = "/api/sante/"

#: Ce que la réponse doit contenir pour être crue. Un 200 ne suffit pas : un
#: proxy d'entreprise qui intercepte le trafic répond 200 avec sa propre page
#: « accès bloqué », et on annoncerait un tunnel opérationnel devant un mur.
MARQUE_SANTE = '"service"'

#: Résolveurs publics, désignés par leur IP — donc joignables SANS DNS, ce qui
#: est tout l'intérêt : sur ce poste, `getaddrinfo` échoue sur tout nom en
#: `.trycloudflare.com` (erreur 11001). Deux fournisseurs : si le réseau bloque
#: l'un, l'autre a une chance.
RESOLVEURS_DOH = [
    ("1.1.1.1", "cloudflare-dns.com"),
    ("8.8.8.8", "dns.google"),
]

#: L'adresse est réaffichée à ce rythme, en secondes. Sans cela elle se noie
#: sous le journal de cloudflared, et on remonte la fenêtre pour la relire.
RAPPEL_ADRESSE = 300

#: Les trois réglages essayés, dans cet ordre. Le symptôme observé —
#: « Registered tunnel connection » d'un côté, erreur 530 de l'autre — a trois
#: causes courantes, et chaque ligne en écarte une :
#:
#: 1. le nom d'hôte est tiré au sort et sa route ne s'est pas propagée ;
#: 2. QUIC passe par UDP 7844, qu'un réseau d'entreprise dégrade souvent sans le
#:    bloquer franchement : le precheck passe, le tunnel s'enregistre, et les
#:    données ne circulent pas. `http2` passe par TCP 443, comme un navigateur ;
#: 3. une IPv6 à moitié fonctionnelle donne exactement ce symptôme. Le journal de
#:    ce poste montre une IPv6 de lien local ; `--edge-ip-version 4` l'écarte.
REGLAGES = [
    ([], "par defaut (QUIC)"),
    (["--protocol", "http2"], "en http2 (TCP 443, comme un navigateur)"),
    (["--protocol", "http2", "--edge-ip-version", "4"], "en http2, IPv4 seulement"),
]

#: Combien de fois refaire le tour des trois réglages.
#:
#: « Le tunnel marche une fois sur 10 » : c'est la description d'une loterie, et
#: la loterie est le nom d'hôte, tiré au sort à chaque lancement. Reprendre le
#: MÊME réglage n'est donc pas espérer un miracle — c'est reprendre un billet.
#: Un seul tour laissait trois chances sur dix ; trois tours en donnent neuf,
#: soit un peu plus de six chances sur dix, et cela ne coûte du temps que
#: lorsque ça échoue. C'est exactement le compromis demandé : des contrôles
#: rapides, mais qui insistent.
TOURS = 3

TENTATIVES = [(options, comment)
              for _ in range(TOURS)
              for options, comment in REGLAGES]

#: Plafond de temps pour TOUTE la série de tentatives, en secondes.
#:
#: Neuf tentatives coûtent une quinzaine de secondes chacune quand elles
#: échouent normalement, soit un peu plus de deux minutes. Mais si `cloudflared`
#: se met à traîner, chacune peut atteindre trente-sept secondes et la série
#: cinq minutes — inacceptable devant un camion à charger. Passé ce budget on
#: s'arrête et on explique : insister, oui ; indéfiniment, non.
BUDGET_TOTAL = 150


def trouver_cloudflared():
    """cloudflared.exe, où qu'il soit posé sur ce poste."""
    noms = ["cloudflared.exe", "cloudflared"]
    dossiers = [RACINE, RACINE / "outils", RACINE / "deploiement" / "windows"]
    # Il a pu être rangé au moment du nettoyage : on le retrouve quand même.
    dossiers += sorted(RACINE.glob("_a_supprimer/*"))
    for dossier in dossiers:
        for nom in noms:
            chemin = dossier / nom
            if chemin.is_file():
                return chemin
    from shutil import which
    trouve = which("cloudflared")
    return Path(trouve) if trouve else None


def python_du_projet():
    for relatif in (Path(".venv") / "Scripts" / "python.exe",
                    Path(".venv") / "bin" / "python"):
        chemin = RACINE / relatif
        if chemin.is_file():
            return chemin
    return Path(sys.executable)


def environnement():
    """Réglages imposés au serveur, sans toucher au fichier .env.

    Modifier `.env` pour un usage temporaire laisserait le poste configuré pour
    un tunnel longtemps après qu'on a cessé de s'en servir. Ces variables ne
    valent que pour les processus lancés ici.
    """
    env = os.environ.copy()
    env["DJANGO_DERRIERE_PROXY"] = "True"      # cookies Secure, en-têtes du proxy
    env["DJANGO_FORCER_HTTPS"] = "False"       # la redirection est faite par Cloudflare
    env["DJANGO_HSTS_SECONDS"] = "0"           # l'adresse change : pas de HSTS à graver
    env["DJANGO_ALLOWED_HOSTS"] = "*"          # le sous-domaine n'est connu qu'après coup
    env["DJANGO_CSRF_ORIGINS"] = "https://*.trycloudflare.com"
    return env


def serveur_appli(port):
    """waitress si présent, `runserver` sinon — lié à la boucle locale."""
    py = python_du_projet()
    waitress = py.parent / ("waitress-serve.exe" if os.name == "nt" else "waitress-serve")
    if waitress.is_file():
        return [str(waitress), f"--listen=127.0.0.1:{port}", "--threads=8",
                "config.wsgi:application"]
    return [str(py), "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"]


#: La feuille de style des trois etats. Une seule, pour qu'ils se ressemblent :
#: c'est la meme page qui se transforme sous les yeux, pas trois pages.
STYLE_PAGE = """
 body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#1C394B;color:#fff;
      margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;
      justify-content:center;gap:1.5rem;padding:2rem;box-sizing:border-box;text-align:center}
 h1{font-size:1.4rem;font-weight:600;margin:0;letter-spacing:.02em}
 #qr{background:#fff;padding:1.25rem;border-radius:12px;line-height:0}
 .adresse{font-family:ui-monospace,Consolas,monospace;font-size:1.15rem;background:#0f2634;
          padding:.75rem 1.1rem;border-radius:8px;word-break:break-all;max-width:32rem}
 .note{opacity:.75;font-size:.9rem;max-width:34rem;line-height:1.5}
 .alerte{color:#f0b429;max-width:34rem;line-height:1.5;font-size:.95rem}
 .etat{background:#0f2634;padding:1rem 1.4rem;border-radius:8px;max-width:32rem;
       font-size:1.05rem}
 .sablier{font-size:2.4rem;line-height:1;opacity:.8}
"""

GABARIT = Template("""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Acces WMS</title>$rafraichir<style>$style</style></head><body>
$corps
</body></html>""")

#: Le fichier est TOUJOURS le meme : le navigateur garde un seul onglet, et
#: c'est son contenu qui change. Deux fichiers obligeraient a suivre lequel est
#: a jour, ce que personne ne fera au milieu d'un chargement de camion.
PAGE = "acces-tunnel.html"


def ecrire_page(corps, rafraichir_apres=None):
    """Ecrit la page locale et rend son chemin.

    `rafraichir_apres` en secondes : la page se recharge seule. C'est ce qui
    permet au QR d'apparaitre sans que personne ne surveille la fenetre noire.
    """
    fichier = RACINE / "logs" / PAGE
    fichier.parent.mkdir(parents=True, exist_ok=True)
    rafraichir = ("" if rafraichir_apres is None else
                  f'<meta http-equiv="refresh" content="{rafraichir_apres}">')
    fichier.write_text(
        GABARIT.substitute(rafraichir=rafraichir, style=STYLE_PAGE, corps=corps),
        encoding="utf-8")
    return fichier


def page_attente(etat):
    """« Ca travaille » — ouverte des le demarrage, elle se remplira seule."""
    return ecrire_page(f"""<h1>Acces WMS : preparation en cours</h1>
<div class="sablier">&#8987;</div>
<div class="etat">{etat}</div>
<p class="note">Cette page se remplit <strong>toute seule</strong> : le QR code
apparaitra ici des que l'adresse repondra vraiment. Il n'y a rien a faire, rien
a relancer. Laissez-la ouverte.</p>""", rafraichir_apres=3)


def page_qr(adresse, note_dns=False):
    """L'adresse en grand et son QR code — ecrite seulement si elle repond.

    L'adresse d'un tunnel est aleatoire et longue. La recopier sur le clavier
    d'un telephone, dix fois par jour et a chaque relance, ne tient pas : on
    affiche un QR que l'appareil photo lit d'un regard.
    """
    lib = RACINE / "wms" / "static" / "app" / "vendor" / "qrcode.min.js"
    script = lib.read_text(encoding="utf-8") if lib.is_file() else ""
    manque = "" if script else (
        "<p class='alerte'>Le generateur de QR n'est pas installe. "
        "Lancez une fois : python manage.py telecharger_libs</p>")
    # Verifiee par contournement : l'adresse repond depuis internet, mais ce
    # poste ne la resout pas. Les telephones sur le meme Wi-Fi ne la resoudront
    # pas non plus — c'est le « page pas trouvee » deja rencontre, et la phrase
    # qui l'evite doit etre SUR la page qu'on scanne, pas dans une fenetre noire.
    avertissement = "" if not note_dns else (
        "<p class='alerte'>Si un telephone affiche &laquo;&nbsp;page pas "
        "trouvee&nbsp;&raquo; : coupez le Wi-Fi et passez en donnees mobiles. "
        "Ce poste ne resout pas cette adresse par le DNS de l'entreprise, et "
        "les telephones sur le meme Wi-Fi ne la resoudront pas non plus.</p>")
    return ecrire_page(f"""<h1>Scannez pour ouvrir le WMS</h1>
<div id="qr"></div>
<div class="adresse">{adresse}</div>
{manque}{avertissement}
<p class="note">Cette adresse est publique et <strong>change a chaque
demarrage</strong>. Ne fermez pas la fenetre du tunnel : l'acces s'arrete avec
elle. Laissez cette page ouverte, les caristes scannent l'ecran.</p>
<script>{script}</script>
<script>
 if (typeof QRCode !== 'undefined') {{
   new QRCode(document.getElementById('qr'),
     {{ text: {json.dumps(adresse)}, width: 260, height: 260,
        correctLevel: QRCode.CorrectLevel.M }});
 }}
</script>""", rafraichir_apres=120)


def page_echec():
    """Aucune adresse n'a repondu : surtout pas de QR.

    Un QR affiche « au cas ou » se retrouve scanne, echoue, et fait chercher la
    panne du cote des telephones. Mieux vaut une page qui dit non.
    """
    return ecrire_page("""<h1>Pas d'acces par tunnel pour le moment</h1>
<p class="alerte">Aucune adresse n'a repondu. Il n'y a volontairement pas de QR
code : il ne menerait nulle part.</p>
<p class="note">La fenetre noire du tunnel dit ce qui a ete essaye et ce qui
reste possible. Cette page se mettra a jour d'elle-meme si vous relancez.</p>""",
                       rafraichir_apres=10)


def ouvrir_la_page(fichier):
    """Ouvre la page locale. Rend vrai si le navigateur a pris la main.

    Sur un poste sans navigateur par defaut, `webbrowser` leve ou rend faux :
    ce serait absurde d'y perdre le tunnel, donc on ne fait que le signaler.
    """
    try:
        return bool(webbrowser.open(fichier.as_uri()))
    except Exception:                                        # noqa: BLE001
        return False


def _pourquoi(code):
    """Ce que veut dire un code de réponse, en une phrase utile.

    Plusieurs pannes très différentes se cachent derrière « ça ne marche
    pas », et savoir laquelle change complètement ce qu'il y a à faire.
    """
    return {
        530: "Cloudflare ne trouve aucun tunnel derriere cette adresse "
             "(erreur 530) — la route n'est pas propagee, ou le tunnel s'est "
             "referme",
        502: "le tunnel repond mais l'application ne repond pas (erreur 502) "
             "sur 127.0.0.1",
        503: "l'application repond mais sa base de donnees non (erreur 503) "
             "— voyez logs\\wms.log",
        400: "l'application a refuse l'adresse (erreur 400) : "
             "DJANGO_ALLOWED_HOSTS ne l'accepte pas",
        404: "l'adresse repond, mais ce n'est pas le WMS (erreur 404)",
    }.get(code, f"le serveur a repondu {code}")


def _dns_casse(souci):
    """Vrai quand l'échec vient de la RÉSOLUTION du nom, pas du tunnel."""
    texte = str(getattr(souci, "reason", souci))
    return any(marque in texte for marque in (
        "getaddrinfo", "11001", "Name or service not known",
        "nodename nor servname", "Temporary failure in name resolution"))


def rassembler_les_morceaux(entete, corps):
    """Recolle un corps envoye « en morceaux » (`Transfer-Encoding: chunked`).

    Cloudflare decoupe ou il veut : la marque cherchee peut tomber a cheval sur
    deux morceaux, et on refuserait alors une reponse parfaitement bonne. Le
    travail se fait sur les OCTETS, parce que les tailles annoncees sont en
    octets et non en caracteres.

    Une reponse tronquee (on ne lit que le debut) rend ce qui a pu etre recolle,
    ce qui suffit : on ne cherche qu'une marque au debut du corps.
    """
    if b"chunked" not in entete.lower():
        return corps
    morceaux = []
    reste = corps
    while True:
        ligne, sep, suite = reste.partition(b"\r\n")
        if not sep:
            break
        try:
            taille = int(ligne.split(b";")[0].strip() or b"0", 16)
        except ValueError:
            break
        if taille == 0:
            break
        morceaux.append(suite[:taille])
        # Chaque morceau est suivi d'un CRLF qui ne fait pas partie du corps.
        reste = suite[taille:]
        if reste.startswith(b"\r\n"):
            reste = reste[2:]
    return b"".join(morceaux)


def https_par_ip(ip, nom, chemin, accepte="*/*"):
    """Un GET sur `ip`, en présentant `nom`. Aucun DNS n'intervient.

    C'est ce que ferait un navigateur dont on aurait forcé la résolution : la
    connexion part sur l'IP, le certificat est vérifié contre le NOM
    (`server_hostname`), et l'en-tête `Host` porte ce nom lui aussi. On ne
    désactive aucun contrôle — c'est important, l'adresse est publique.

    `Accept-Encoding: identity` parce qu'on lit le corps : une réponse
    compressée nous obligerait à la décompresser pour rien.

    Rend `(code, corps)`.
    """
    contexte = ssl.create_default_context()
    brut = socket.create_connection((ip, 443), timeout=DELAI_ESSAI)
    morceaux = []
    try:
        with contexte.wrap_socket(brut, server_hostname=nom) as tls:
            tls.settimeout(DELAI_ESSAI)
            tls.sendall((f"GET {chemin} HTTP/1.1\r\n"
                         f"Host: {nom}\r\n"
                         f"Accept: {accepte}\r\n"
                         "Accept-Encoding: identity\r\n"
                         "User-Agent: WMS-Structa/verification-tunnel\r\n"
                         "Connection: close\r\n\r\n").encode("ascii"))
            recu = 0
            while recu < 8192:
                bloc = tls.recv(4096)
                if not bloc:
                    break
                morceaux.append(bloc)
                recu += len(bloc)
    finally:
        try:
            brut.close()
        except Exception:                                    # noqa: BLE001
            pass
    entete, _, corps = b"".join(morceaux).partition(b"\r\n\r\n")
    premiere = entete.split(b"\r\n", 1)[0].split()
    code = (int(premiere[1]) if len(premiere) > 1 and premiere[1].isdigit()
            else None)
    return code, rassembler_les_morceaux(entete, corps).decode("utf-8", "replace")


def resoudre_par_doh(nom):
    """Les IP de `nom`, demandées à un résolveur public par HTTPS.

    On joint le résolveur par son IP : aucun DNS n'est nécessaire pour le
    joindre, ce qui est exactement ce qu'il faut quand le DNS du poste EST le
    problème.

    Rend `(ips, nom_du_resolveur)`, ou `([], None)` si aucun n'a répondu.
    """
    for ip, nom_resolveur in RESOLVEURS_DOH:
        try:
            code, corps = https_par_ip(
                ip, nom_resolveur,
                "/dns-query?" + urllib.parse.urlencode({"name": nom, "type": "A"}),
                accepte="application/dns-json")
            if code != 200 or "{" not in corps:
                continue
            # `raw_decode` s'arrête à la fin du premier objet : la réponse peut
            # arriver découpée en morceaux (« chunked »), avec des longueurs
            # hexadécimales autour du JSON.
            donnees, _ = json.JSONDecoder().raw_decode(corps[corps.index("{"):])
            # type 1 = un enregistrement A. Les CNAME intermédiaires n'ont pas
            # d'IP à donner, on les laisse.
            ips = [r["data"] for r in donnees.get("Answer", [])
                   if r.get("type") == 1]
            if ips:
                return ips, nom_resolveur
        except Exception:                                    # noqa: BLE001
            # Un résolveur injoignable n'est pas une erreur à remonter : on
            # passe au suivant. C'est l'absence de TOUS qui compte.
            continue
    return [], None


def preparer_la_sonde(nom):
    """Par quel chemin interroger `nom` ? Tranché UNE FOIS, avant la boucle.

    Résoudre à chaque essai est ce qui rendait le contrôle lent : sur ce poste
    chaque résolution échoue, et douze échecs de DNS coûtent plus cher que les
    douze requêtes qu'ils empêchaient.

    Rend `(ips, resolveur, dns_du_poste)`. `dns_du_poste` vrai = le chemin
    ordinaire suffit, c'est le plus fidèle à ce que fera un téléphone.
    """
    try:
        socket.getaddrinfo(nom, 443, type=socket.SOCK_STREAM)
        return [], None, True
    except OSError:
        # Le nom ne se résout pas ICI. Cela ne dit RIEN du tunnel, et rien non
        # plus de ce que verra un téléphone en 4G.
        pass
    ips, resolveur = resoudre_par_doh(nom)
    return ips, resolveur, False


def un_essai(adresse, ips, nom):
    """Un seul essai, par le chemin déjà choisi. Rend `(etat, raison)`.

    `ips` non vide : on court-circuite le DNS du poste. Vide : `urllib`, comme
    un navigateur.
    """
    if ips:
        dernier = "aucune reponse"
        for ip in ips[:3]:
            try:
                code, corps = https_par_ip(ip, nom, SONDE)
            except Exception as souci:                       # noqa: BLE001
                dernier = f"{type(souci).__name__} : {souci}"
                continue
            if code == 200:
                if MARQUE_SANTE in corps:
                    return True, ""
                return False, ("quelque chose repond a cette adresse, mais ce "
                               "n'est pas le WMS — un proxy s'interpose")
            if code is not None:
                return False, _pourquoi(code)
        return None, f"contournement DNS sans reponse ({dernier})"

    try:
        requete = urllib.request.Request(
            adresse.rstrip("/") + SONDE,
            headers={"User-Agent": "WMS-Structa/verification-tunnel",
                     "Accept-Encoding": "identity"})
        with urllib.request.urlopen(requete, timeout=DELAI_ESSAI) as reponse:
            corps = reponse.read(8192).decode("utf-8", "replace")
        if reponse.status != 200:
            return False, _pourquoi(reponse.status)
        if MARQUE_SANTE not in corps:
            return False, ("quelque chose repond a cette adresse, mais ce "
                           "n'est pas le WMS — un proxy s'interpose")
        return True, ""
    except urllib.error.HTTPError as souci:
        # 530 : le nom n'a plus de tunnel derriere lui — le cas rencontre.
        return False, _pourquoi(souci.code)
    except urllib.error.URLError as souci:
        if _dns_casse(souci):
            return None, "ce poste ne resout pas le nom (DNS)"
        return False, f"pas de reponse ({souci.reason})"
    except Exception as souci:                               # noqa: BLE001
        return False, f"{type(souci).__name__} : {souci}"


def joignable(adresse, limite_secondes=ATTENTE_JOIGNABLE, pendant=None,
              sur_essai=None):
    """L'adresse sert-elle le WMS, vue d'internet ? Rend `(etat, raison, par)`.

    C'est le chemin exact que prendront les téléphones : ce poste sort vers
    l'edge de Cloudflare, qui redescend par le tunnel. Une réponse ici prouve
    que la chaîne entière est debout — pas seulement que `cloudflared` s'est
    connecté, ce que le journal affirmait déjà pendant que l'adresse rendait un
    530.

    Trois états, et le troisième compte autant que les deux autres :
    `True` elle sert le WMS ; `False` elle a répondu autre chose, et on dit
    quoi ; `None` on n'a PAS PU savoir. Confondre le troisième avec le second
    est précisément ce qui a fait déclarer en panne un tunnel qui marchait.

    `par` nomme le chemin emprunté. Ce n'est pas un détail : vérifiée « par
    contournement », l'adresse répond depuis internet alors que ce poste ne la
    résout pas — et les téléphones sur le même Wi-Fi ne la résoudront pas non
    plus. C'est l'explication du « page pas trouvée » sur le téléphone.

    `sur_essai(numero, raison)` est appelé après chaque échec : sans cela le
    contrôle est muet, et on ne sait pas s'il travaille ou s'il est bloqué.
    `pendant` est appelé entre deux essais ; il laisse parler `cloudflared` et
    peut rendre une raison d'abandonner — inutile de sonder une adresse dont le
    tunnel s'est déjà refermé.
    """
    nom = urllib.parse.urlparse(adresse).hostname or adresse
    ips, resolveur, dns_du_poste = preparer_la_sonde(nom)
    if dns_du_poste:
        par = "DNS du poste"
    elif ips:
        par = f"contournement DNS via {resolveur}"
    else:
        # Ni le DNS du poste ni aucun résolveur public : on ne peut RIEN
        # affirmer. Insister n'apporterait aucune information nouvelle.
        return None, ("ce poste ne resout pas l'adresse, et les resolveurs "
                      "publics (1.1.1.1, 8.8.8.8) ne repondent pas d'ici non "
                      "plus : la verification est impossible depuis ce poste"), "aucun"

    fin = time.monotonic() + limite_secondes
    essai = 0
    while True:
        essai += 1
        etat, raison = un_essai(adresse, ips, nom)
        if etat is True:
            return True, "", par
        if sur_essai is not None:
            sur_essai(essai, raison)
        if time.monotonic() >= fin:
            return etat, raison, par
        if pendant is None:
            time.sleep(1.0)
        else:
            fin_pause = time.monotonic() + 1.0
            while time.monotonic() < fin_pause:
                abandon = pendant()
                if abandon:
                    return False, abandon, par
                time.sleep(0.2)


def bloc_adresse(adresse, fichier, verifiee):
    """Le pavé qu'on lit à travers l'atelier. Réaffiché de temps en temps.

    Deux états, et pas trois : `True` elle répond ; `None` on n'a PAS PU le
    vérifier depuis ce poste, ce qui ne dit rien de ce que verra un téléphone
    et ne doit donc pas être annoncé comme une panne.

    Une adresse dont on sait qu'elle ne répond pas n'a rien à faire ici : ce
    pavé existe pour être lu de loin et scanné. Un échec tient sur une ligne.
    """
    lignes = ["", "  " + "=" * 62]
    if verifiee:
        lignes.append("   ADRESSE A OUVRIR SUR LES TELEPHONES (verifiee, elle repond) :")
    else:
        lignes.append("   ADRESSE PRODUITE — IMPOSSIBLE DE LA VERIFIER D'ICI :")
    lignes += ["", f"      {adresse}", "",
               "   Le QR code correspondant est ouvert a l'ecran :",
               "   les caristes scannent, rien a recopier.",
               "  " + "=" * 62]
    if fichier:
        lignes += ["", f"   Page QR : {fichier}"]
    return "\n".join(lignes)


def lire_en_fond(flux, file_attente):
    for ligne in iter(flux.readline, ""):
        file_attente.put(ligne.rstrip("\n"))
    flux.close()


def ouvrir_un_tunnel(cloudflared, port, options, comment):
    """Lance cloudflared, attend son adresse. Rend `(processus, file, adresse)`.

    `adresse` vaut None si aucune n'est venue — l'appelant décide alors s'il
    réessaie autrement.
    """
    print("  Ouverture du tunnel...\n")
    tunnel = subprocess.Popen(
        [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{port}"] + options,
        cwd=str(RACINE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace")
    lignes = Queue()
    threading.Thread(target=lire_en_fond, args=(tunnel.stdout, lignes),
                     daemon=True).start()

    adresse = None
    limite = time.monotonic() + ATTENTE_MAX
    while adresse is None and time.monotonic() < limite:
        if tunnel.poll() is not None:
            return tunnel, lignes, None
        try:
            ligne = lignes.get(timeout=0.5)
        except Empty:
            continue
        trouvee = ADRESSE.search(ligne)
        if trouvee:
            adresse = trouvee.group(0)
    return tunnel, lignes, adresse


def fermer(processus):
    if processus is None or processus.poll() is not None:
        return
    processus.terminate()
    try:
        processus.wait(timeout=8)
    except subprocess.TimeoutExpired:
        processus.kill()


def main():
    port = 8000
    cloudflared = trouver_cloudflared()
    if not cloudflared:
        print("\n  cloudflared est introuvable.\n")
        print("  Cherche dans le dossier du projet, outils\\, deploiement\\windows\\,")
        print("  _a_supprimer\\, et dans le PATH.\n")
        print("  A telecharger : https://developers.cloudflare.com/cloudflare-one/"
              "connections/connect-networks/downloads/")
        print("  Posez cloudflared.exe a la racine du projet, puis relancez.\n")
        return 1

    print("\n  " + "-" * 62)
    print("   WMS Structa - acces par tunnel (solution d'attente)")
    print("  " + "-" * 62)
    print(f"   cloudflared : {cloudflared}")
    print("\n   L'adresse produite est PUBLIQUE : seul le mot de passe des comptes")
    print("   protege les donnees. A remplacer par l'acces interne des que le")
    print("   port 8443 est ouvert.\n")

    env = environnement()
    py = python_du_projet()

    print("  Mise a jour du schema de la base...")
    if subprocess.run([str(py), "manage.py", "migrate", "--noinput"],
                      cwd=str(RACINE), env=env).returncode != 0:
        print("\n  La base n'a pas pu etre preparee. Rien n'est demarre.")
        return 1

    print("\n  Demarrage du serveur (boucle locale)...")
    appli = subprocess.Popen(serveur_appli(port), cwd=str(RACINE), env=env)
    time.sleep(2.5)
    if appli.poll() is not None:
        print("  Le serveur s'est arrete aussitot. Lancez Demarrer-WMS.bat seul "
              "pour voir l'erreur.")
        return 1

    # LA LOTERIE, JOUEE PLUSIEURS FOIS. Un seul essai suffisait tant que
    # Cloudflare servait le nom d'hote qu'il venait de creer. Ce n'est plus
    # vrai : des tunnels enregistres, prechecks au vert, pour des adresses qui
    # rendent 530. « Une fois sur dix » — c'est la description d'un tirage au
    # sort, et on ne gagne pas une loterie en prenant un seul billet.
    #
    # La page locale s'ouvre DES MAINTENANT, en « preparation » : elle se
    # remplira toute seule quand une adresse repondra. Personne n'a a
    # surveiller cette fenetre noire en attendant.
    onglet_ouvert = ouvrir_la_page(page_attente("Demarrage du tunnel..."))

    adresse = None
    derniere = None
    tunnel = lignes = None
    fin_du_budget = time.monotonic() + BUDGET_TOTAL
    try:
        for numero, (options, comment) in enumerate(TENTATIVES, start=1):
            if numero > 1 and time.monotonic() > fin_du_budget:
                print(f"\n  J'arrete la : {numero - 1} tentatives en "
                      f"{BUDGET_TOTAL} secondes, cela suffit a conclure.")
                break
            print(f"\n  --- Tentative {numero} sur {len(TENTATIVES)} : {comment} ---")
            page_attente(f"Tentative {numero} sur {len(TENTATIVES)} :"
                         f" ouverture du tunnel {comment}.")
            tunnel, lignes, adresse = ouvrir_un_tunnel(
                cloudflared, port, options, comment)

            if adresse is None:
                if tunnel.poll() is not None:
                    print("  Le tunnel s'est ferme avant de donner une adresse.")
                    print("  Ce poste a-t-il acces a internet sans proxy ?")
                else:
                    print(f"  Aucune adresse apres {ATTENTE_MAX} secondes.")
                fermer(tunnel)
                continue

            # L'adresse en texte TOUT DE SUITE : le controle qui suit ne doit
            # pas ressembler a un silence, c'est ce qui a deja mal tourne. Mais
            # PAS DE QR avant d'etre sur — « afficher qr code une fois c'est
            # operationnelle ». Un QR qui mene a « page pas trouvee » fait
            # chercher la panne du cote des telephones.
            print(f"\n   Adresse proposee : {adresse}")
            print(f"   Je verifie qu'elle repond vraiment ({ATTENTE_JOIGNABLE} s au plus).")
            print("   Le QR code apparaitra tout seul dans la page deja ouverte.")
            page_attente(f"Tentative {numero} sur {len(TENTATIVES)} : je verifie"
                         " que l'adresse repond vraiment avant de vous montrer le"
                         " QR code.")

            def relayer(t=tunnel, q=lignes):
                """Laisse parler cloudflared, et dit s'il faut arreter d'attendre."""
                while True:
                    try:
                        print("   [tunnel] " + q.get_nowait())
                    except Empty:
                        break
                if t.poll() is not None:
                    return ("le tunnel s'est referme pendant la verification "
                            "— l'adresse est morte avec lui")
                return None

            def dire_l_essai(n, pourquoi):
                # Un essai coute moins d'une seconde : les annoncer tous
                # remplirait l'ecran sans rien apprendre de plus.
                if n == 1 or n % 4 == 0:
                    print(f"   ... essai {n} : {pourquoi}")

            etat, raison, par = joignable(adresse, pendant=relayer,
                                          sur_essai=dire_l_essai)
            if etat is True:
                # Verifiee par contournement = elle repond depuis internet,
                # mais ce poste ne la resout pas. Les telephones sur le meme
                # Wi-Fi ne la resoudront pas non plus : c'est l'explication du
                # « page pas trouvee », et elle doit etre SUR la page scannee.
                contournee = par != "DNS du poste"
                fichier = page_qr(adresse, note_dns=contournee)
                print(bloc_adresse(adresse, fichier, True))
                if not onglet_ouvert:
                    ouvrir_la_page(fichier)
                if contournee:
                    print("\n   Note : ce poste ne RESOUT pas cette adresse (le DNS")
                    print("   de l'entreprise ne connait pas ce domaine). Verifiee")
                    print(f"   par {par}, elle repond bien depuis internet.")
                    print("   Sur les telephones, si « page pas trouvee » : coupez")
                    print("   le Wi-Fi et passez en donnees mobiles.")
                print("\n   Cette fenetre doit rester ouverte. La fermer coupe l'acces.\n")
                break

            if etat is None:
                # VERIFICATION IMPOSSIBLE, et non tunnel mort. Insister
                # n'apporterait aucune information nouvelle : le probleme est
                # ici, pas dans le tunnel. On garde celui-ci, et on le dit.
                fichier = page_qr(adresse, note_dns=True)
                print(bloc_adresse(adresse, fichier, None))
                if not onglet_ouvert:
                    ouvrir_la_page(fichier)
                print(f"\n   Pourquoi : {raison}.")
                print("\n   L'adresse est peut-etre tres bien : le tunnel est")
                print("   enregistre et il tourne. Essayez-la sur un telephone en")
                print("   4G — le DNS n'y est pas celui de ce poste.")
                print("\n   Cette fenetre doit rester ouverte. La fermer coupe l'acces.\n")
                break

            # Elle ne repond pas. On le DIT — sur UNE ligne : repete huit fois,
            # le pave complet noie la fenetre. Puis on recommence, et le nom
            # d'hote suivant sera different : c'est le tirage qu'on rejoue.
            print(f"   -> N'A PAS REPONDU : {raison}.")
            fermer(tunnel)
            derniere = adresse
            adresse = None
            if numero < len(TENTATIVES):
                print("   Je recommence — nouvelle adresse, autre reglage.")

        if adresse is None:
            print("\n  " + "=" * 62)
            page_echec()
            print("   AUCUNE DES TENTATIVES N'A DONNE UNE ADRESSE QUI REPOND.")
            print("  " + "=" * 62)
            print("\n   Le service gratuit trycloudflare.com ne sert pas les tunnels")
            print("   de ce poste en ce moment. Ce n'est ni le WMS ni ce script :")
            print("   cloudflared s'enregistre, et Cloudflare repond qu'il ne")
            print("   trouve aucun tunnel derriere le nom d'hote qu'il vient de")
            print("   creer.")
            print("\n   Ce qui marche, sans Cloudflare : Demarrer-WMS.bat, puis sur")
            print("   les telephones l'adresse https://<adresse de ce poste>:8443,")
            print("   sur le meme Wi-Fi, une fois l'autorite certificats\\ac-structa.crt")
            print("   installee (docs/guide-https.md).")
            if derniere:
                # Pour memoire, et sans l'encadrer : elle ne repond pas, on ne
                # veut pas qu'elle attire l'oeil ni qu'on la recopie.
                print(f"\n   (derniere adresse produite : {derniere})\n")
            else:
                print("")
            fermer(appli)
            return 1

        # On relaie ce que dit cloudflared : une coupure doit se voir. Et on
        # reaffiche l'adresse de temps en temps — sans cela elle se noie sous
        # trente lignes de journal, et il faut remonter la fenetre pour la relire.
        prochain_rappel = time.monotonic() + RAPPEL_ADRESSE
        while tunnel.poll() is None and appli.poll() is None:
            try:
                ligne = lignes.get(timeout=1.0)
                print("   [tunnel] " + ligne)
                # Une reconnexion se lit dans le journal de cloudflared : on la
                # met en evidence, parce qu'entre les deux les telephones ont
                # vu une erreur et vont demander pourquoi.
                if "Unregistered tunnel connection" in ligne or "Lost connection" in ligne:
                    print("   ! Le tunnel a perdu sa connexion. cloudflared va")
                    print("     reessayer ; l'adresse ne change pas.")
                elif "Registered tunnel connection" in ligne:
                    print("   > Tunnel connecte.")
            except Empty:
                pass
            if time.monotonic() >= prochain_rappel:
                print(bloc_adresse(adresse, None, True))
                prochain_rappel = time.monotonic() + RAPPEL_ADRESSE
    except KeyboardInterrupt:
        print("\n  Arret demande.")
    finally:
        # `fermer()` tolere None : aucune tentative n'a forcement abouti.
        fermer(tunnel)
        fermer(appli)
        print("  Serveur et tunnel arretes.")
        if adresse:
            # Sans cette phrase, on relance le lendemain avec l'adresse de la
            # veille — collee sur un mur ou gardee en favori — et on conclut que
            # « le tunnel ne marche plus ».
            print(f"  L'adresse {adresse} est MORTE avec ce tunnel.")
            print("  Le prochain demarrage en produira une autre : le QR code")
            print("  affiche a l'ecran est le seul a jour.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
