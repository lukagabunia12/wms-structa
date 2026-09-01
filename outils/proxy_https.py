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
#: connexion en clair et faire croire à Django que la session est protégée.
IMPOSES = {b"x-forwarded-proto": b"https"}
RETIRES = {b"x-forwarded-proto", b"x-forwarded-ssl", b"x-forwarded-port"}

TAILLE_MAX_ENTETES = 64 * 1024


def reecrire_entetes(tete: bytes, port_local: int) -> bytes:
    """Réécrit le bloc d'entêtes : impose X-Forwarded-Proto, retire les usurpations."""
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


async def _relayer_corps(lecteur, ecrivain, longueur):
    """Recopie le corps sans jamais le charger en mémoire."""
    if longueur == "chunked":
        while True:
            ligne = await lecteur.readuntil(b"\r\n")
            ecrivain.write(ligne)
            taille = int(ligne.strip().split(b";")[0] or b"0", 16)
            if taille == 0:
                fin = await lecteur.readuntil(b"\r\n")   # ligne vide finale
                ecrivain.write(fin)
                await ecrivain.drain()
                return
            reste = taille + 2                              # + le CRLF du morceau
            while reste:
                bloc = await lecteur.read(min(65536, reste))
                if not bloc:
                    return
                ecrivain.write(bloc)
                reste -= len(bloc)
            await ecrivain.drain()
        return
    reste = longueur
    while reste > 0:
        bloc = await lecteur.read(min(65536, reste))
        if not bloc:
            return
        ecrivain.write(bloc)
        reste -= len(bloc)
    await ecrivain.drain()


async def _requetes(lecteur, ecrivain, port_local):
    """Sens client -> application : réécrit les entêtes de CHAQUE requête.

    Une connexion persistante porte plusieurs requêtes. La version précédente ne
    réécrivait que la première : à partir de la deuxième, Django voyait une
    requête en clair, redirigeait vers HTTPS et l'application tournait en rond.
    """
    try:
        while True:
            try:
                tete = await lecteur.readuntil(b"\r\n\r\n")
            except (asyncio.IncompleteReadError, ConnectionResetError):
                return
            except asyncio.LimitOverrunError:
                return
            if len(tete) > TAILLE_MAX_ENTETES:
                return
            ecrivain.write(reecrire_entetes(tete[:-4], port_local))
            await ecrivain.drain()
            longueur = await _longueur_corps(tete)
            if longueur is None:
                # Mise à niveau du protocole : on cesse de découper et on recopie.
                await _pomper(lecteur, ecrivain)
                return
            await _relayer_corps(lecteur, ecrivain, longueur)
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            ecrivain.close()
        except Exception:
            pass


async def servir_client(lecteur, ecrivain, cible, port_local):
    hote, port = cible
    try:
        amont_l, amont_e = await asyncio.open_connection(hote, port)
    except OSError:
        # Le serveur d'application n'est pas démarré : on le dit en HTTP plutôt
        # que de fermer sèchement, sinon le téléphone affiche une page blanche.
        corps = ("Le serveur WMS ne repond pas sur %s:%s.\r\n"
                 "Demarrez-le avec Demarrer-WMS.bat." % (hote, port)).encode()
        ecrivain.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain; charset=utf-8\r\n"
                       b"Content-Length: " + str(len(corps)).encode()
                       + b"\r\nConnection: close\r\n\r\n" + corps)
        try:
            await ecrivain.drain()
        finally:
            ecrivain.close()
        return
    await asyncio.gather(_requetes(lecteur, amont_e, port_local),
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
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054, 10058):
            return
        _boucle.default_exception_handler(contexte)

    boucle.set_exception_handler(gestionnaire)


async def demarrer(ecoute, cible):
    if not (CERT.is_file() and CLE.is_file()):
        sys.exit("Certificat absent. Lancez d'abord :\n"
                 "  .venv\\Scripts\\python.exe outils\\certificat_https.py")
    silencier_deconnexions(asyncio.get_running_loop())
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(CERT), str(CLE))
    # TLS 1.2 minimum : en dessous, les navigateurs récents refusent la connexion.
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
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
