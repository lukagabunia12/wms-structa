"""Terminaison TLS devant le serveur d'application : le WMS en HTTPS sur le réseau interne.

Pourquoi ce fichier plutôt qu'un serveur HTTPS de plus : `waitress`, qui sert déjà
le WMS en exploitation, ne fait pas de TLS. Plutôt que d'ajouter un second serveur
d'application — et de devoir vérifier qu'il se comporte comme le premier — on
place devant lui un terminateur TLS de quarante lignes, en bibliothèque standard.
Django sait déjà traiter ce cas : `DJANGO_DERRIERE_PROXY=True` lui fait lire
l'entête `X-Forwarded-Proto`, exactement comme derrière le tunnel Cloudflare.

Le flux est recopié octet pour octet. Seule la première ligne d'entêtes est
réécrite, pour y insérer l'origine et le protocole. Les corps de requête — dont
les photos de fiches, jusqu'à 12 Mo — ne sont ni analysés ni bufferisés.

    python outils/proxy_https.py --vers 127.0.0.1:8000 --ecoute 0.0.0.0:8443
"""
import argparse
import asyncio
import ssl
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CERT = RACINE / "certificats" / "wms.crt"
CLE = RACINE / "certificats" / "wms.key"

#: Entêtes que le proxy pose lui-même. Toute valeur venant du client est écrasée :
#: sans cela, n'importe qui pourrait annoncer « X-Forwarded-Proto: https » sur une
#: connexion en clair et faire croire à Django que la session est protégée — ou
#: « X-Forwarded-For: 1.2.3.4 » pour se faire passer pour un autre poste auprès
#: du frein aux essais de mot de passe.
IMPOSES = {b"x-forwarded-proto": b"https"}
RETIRES = {b"x-forwarded-proto", b"x-forwarded-ssl", b"x-forwarded-port",
           b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-by",
           b"forwarded", b"x-real-ip"}

TAILLE_MAX_ENTETES = 64 * 1024

#: Une connexion qui ne dit plus rien est fermée au bout de ce délai. Chaque
#: connexion d'un téléphone en occupe une chez waitress, qui en accepte un
#: nombre limité : sans ce délai, quelques dizaines de connexions muettes
#: suffisaient à rendre le WMS sourd à tous les autres.
DELAI_INACTIVITE = 75
#: Délai entre deux morceaux d'un même envoi (une photo de fiche sur un Wi-Fi
#: faible) : large, pour ne jamais couper un envoi qui avance.
DELAI_CORPS = 120

#: Le contexte TLS en service : `recharger_certificat()` y remet le certificat
#: renouvelé sans couper les connexions en cours.
CONTEXTE = None


def reecrire_entetes(tete: bytes, port_local: int, client: str = "") -> bytes:
    """Réécrit le bloc d'entêtes : impose X-Forwarded-Proto et X-Forwarded-For,
    retire tout ce que le client aurait pu inventer à leur place."""
    lignes = tete.split(b"\r\n")
    sortie = [lignes[0]]                      # la ligne de requête reste intacte
    for ligne in lignes[1:]:
        if not ligne:
            continue
        nom = ligne.split(b":", 1)[0].strip().lower()
        if nom in RETIRES:
            continue                          # posé par nous, pas par le client
        sortie.append(ligne)
    for nom, valeur in IMPOSES.items():
        sortie.append(nom.title() + b": " + valeur)
    sortie.append(b"X-Forwarded-Port: " + str(port_local).encode())
    if client:
        # L'adresse réelle du téléphone. waitress ne la croit que venant de
        # 127.0.0.1 (option --trusted-proxy du lanceur) : de n'importe où
        # ailleurs, l'entête est jeté.
        sortie.append(b"X-Forwarded-For: " + client.encode("ascii", "replace"))
    return b"\r\n".join(sortie) + b"\r\n\r\n"


async def _pomper(lecteur, ecrivain):
    """Recopie un sens du flux jusqu'à la fermeture. Aucun buffer complet."""
    try:
        while True:
            bloc = await lecteur.read(65536)
            if not bloc:
                break
            ecrivain.write(bloc)
            await ecrivain.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            ecrivain.close()
        except Exception:
            pass


async def _longueur_corps(tete: bytes):
    """Combien d'octets de corps suivent ces entêtes.

    Renvoie un entier, `"chunked"`, ou `None` s'il faut cesser de découper (mise à
    niveau de protocole). Sans ce découpage, on ne saurait pas où finit une
    requête et où commence la suivante — et sur une connexion persistante, seule
    la première recevrait l'entête `X-Forwarded-Proto`.
    """
    longueur, chunked, upgrade = 0, False, False
    for ligne in tete.split(b"\r\n")[1:]:
        if b":" not in ligne:
            continue
        nom, valeur = ligne.split(b":", 1)
        nom, valeur = nom.strip().lower(), valeur.strip().lower()
        if nom == b"content-length":
            try:
                longueur = int(valeur)
            except ValueError:
                longueur = 0
        elif nom == b"transfer-encoding" and b"chunked" in valeur:
            chunked = True
        elif nom == b"upgrade":
            upgrade = True
    if upgrade:
        return None
    return "chunked" if chunked else longueur


class RequeteIllisible(Exception):
    """Un corps de requête qu'on ne sait pas découper : la connexion est fermée."""


async def _lire(lecteur, n):
    return await asyncio.wait_for(lecteur.read(n), DELAI_CORPS)


async def _ligne(lecteur):
    return await asyncio.wait_for(lecteur.readuntil(b"\r\n"), DELAI_CORPS)


async def _relayer_corps(lecteur, ecrivain, longueur):
    """Recopie le corps sans jamais le charger en mémoire."""
    if longueur == "chunked":
        while True:
            ligne = await _ligne(lecteur)
            ecrivain.write(ligne)
            try:
                taille = int(ligne.strip().split(b";")[0] or b"0", 16)
            except ValueError:
                # Un morceau dont la taille n'est pas un nombre : on ne sait plus
                # où finit la requête. Continuer, ce serait mélanger la suite du
                # flux avec la requête suivante.
                raise RequeteIllisible() from None
            if taille == 0:
                # Lignes d'en-queue éventuelles, puis la ligne vide finale.
                while True:
                    fin = await _ligne(lecteur)
                    ecrivain.write(fin)
                    if fin == b"\r\n":
                        break
                await ecrivain.drain()
                return
            reste = taille + 2                              # + le CRLF du morceau
            while reste:
                bloc = await _lire(lecteur, min(65536, reste))
                if not bloc:
                    return
                ecrivain.write(bloc)
                reste -= len(bloc)
            await ecrivain.drain()
        return
    reste = longueur
    while reste > 0:
        bloc = await _lire(lecteur, min(65536, reste))
        if not bloc:
            return
        ecrivain.write(bloc)
        reste -= len(bloc)
    await ecrivain.drain()


async def _requetes(lecteur, ecrivain, port_local, client=""):
    """Sens client -> application : réécrit les entêtes de CHAQUE requête.

    Une connexion persistante porte plusieurs requêtes. La version précédente ne
    réécrivait que la première : à partir de la deuxième, Django voyait une
    requête en clair, redirigeait vers HTTPS et l'application tournait en rond.
    """
    try:
        while True:
            try:
                tete = await asyncio.wait_for(lecteur.readuntil(b"\r\n\r\n"),
                                              DELAI_INACTIVITE)
            except (asyncio.IncompleteReadError, ConnectionResetError,
                    asyncio.TimeoutError):
                return
            except asyncio.LimitOverrunError:
                return
            if len(tete) > TAILLE_MAX_ENTETES:
                return
            ecrivain.write(reecrire_entetes(tete[:-4], port_local, client))
            await ecrivain.drain()
            longueur = await _longueur_corps(tete)
            if longueur is None:
                # Mise à niveau du protocole : on cesse de découper et on recopie.
                await _pomper(lecteur, ecrivain)
                return
            await _relayer_corps(lecteur, ecrivain, longueur)
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError,
            asyncio.LimitOverrunError, asyncio.TimeoutError, RequeteIllisible):
        pass
    finally:
        try:
            ecrivain.close()
        except Exception:
            pass


def _adresse_client(ecrivain):
    """L'adresse IP du téléphone, telle que la connexion TLS la voit."""
    pair = ecrivain.get_extra_info("peername")
    if isinstance(pair, (tuple, list)) and pair:
        return str(pair[0])
    return ""


async def servir_client(lecteur, ecrivain, cible, port_local):
    hote, port = cible
    try:
        amont_l, amont_e = await asyncio.open_connection(hote, port)
    except OSError:
        # Le serveur d'application n'est pas démarré : on le dit en HTTP plutôt
        # que de fermer sèchement, sinon le téléphone affiche une page blanche.
        corps = ("Le serveur WMS ne repond pas sur %s:%s : il demarre ou "
                 "redemarre. Reessayez dans une minute.\r\n" % (hote, port)).encode()
        ecrivain.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain; charset=utf-8\r\n"
                       b"Content-Length: " + str(len(corps)).encode()
                       + b"\r\nConnection: close\r\n\r\n" + corps)
        try:
            await ecrivain.drain()
        finally:
            ecrivain.close()
        return
    await asyncio.gather(_requetes(lecteur, amont_e, port_local, _adresse_client(ecrivain)),
                         _pomper(amont_l, ecrivain))


def silencier_deconnexions(boucle):
    """Fait taire le bruit d'asyncio quand un client raccroche brutalement.

    Sous Windows, la boucle « Proactor » appelle `socket.shutdown()` sur une
    connexion déjà réinitialisée par le pair et remonte l'échec comme une
    exception non rattrapée : trente lignes de trace pour un téléphone qui a
    changé d'écran. Le flux, lui, n'a rien : les requêtes suivantes sont servies
    normalement. On filtre donc ces exceptions-là, et elles seules — toute autre
    erreur continue d'être affichée.
    """
    def gestionnaire(_boucle, contexte):
        exc = contexte.get("exception")
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        # OSError 10054/10053 : mêmes causes, remontées sans classe dédiée.
        # 121 (délai de sémaphore), 64 (nom réseau plus disponible), 1236
        # (connexion interrompue) : un téléphone sorti du Wi-Fi ou mis en
        # veille au milieu d'un échange — vu sur le serveur, même innocuité.
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (
                10053, 10054, 10058, 121, 64, 1236):
            return
        _boucle.default_exception_handler(contexte)

    boucle.set_exception_handler(gestionnaire)


def recharger_certificat():
    """Remet le certificat (renouvelé sur le disque) dans le contexte en service.

    Les connexions déjà ouvertes gardent l'ancien ; toutes les suivantes
    reçoivent le nouveau. Rend False si rien n'est en service ou si les fichiers
    sont illisibles — l'ancien certificat reste alors servi.
    """
    if CONTEXTE is None:
        return False
    try:
        CONTEXTE.load_cert_chain(str(CERT), str(CLE))
    except (OSError, ssl.SSLError):
        return False
    return True


async def demarrer(ecoute, cible):
    global CONTEXTE
    if not (CERT.is_file() and CLE.is_file()):
        sys.exit("Certificat absent. Lancez d'abord :\n"
                 "  .venv\\Scripts\\python.exe outils\\certificat_https.py")
    silencier_deconnexions(asyncio.get_running_loop())
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(CERT), str(CLE))
    # TLS 1.2 minimum : en dessous, les navigateurs récents refusent la connexion.
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    CONTEXTE = ctx
    hote, port = ecoute
    serveur = await asyncio.start_server(
        lambda lecture, ecriture: servir_client(lecture, ecriture, cible, port),
        hote, port, ssl=ctx)
    return serveur


def analyser(adresse, defaut_port):
    if ":" in adresse:
        h, p = adresse.rsplit(":", 1)
        return h, int(p)
    return adresse, defaut_port


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ecoute", default="0.0.0.0:8443")
    p.add_argument("--vers", default="127.0.0.1:8000")
    args = p.parse_args()
    ecoute = analyser(args.ecoute, 8443)
    cible = analyser(args.vers, 8000)

    async def tourner():
        serveur = await demarrer(ecoute, cible)
        print(f"  HTTPS  : https://{ecoute[0]}:{ecoute[1]}  ->  http://{cible[0]}:{cible[1]}")
        print("  Ctrl+C pour arrêter.\n")
        async with serveur:
            await serveur.serve_forever()

    try:
        asyncio.run(tourner())
    except KeyboardInterrupt:
        print("\n  Arrêté.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
