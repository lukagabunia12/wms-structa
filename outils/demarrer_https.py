"""Démarre le WMS en HTTPS sur le réseau interne, d'un seul geste.

C'est la dernière étape de `Demarrer-WMS.bat` — le seul lanceur, qui prépare
l'environnement, la base et le pare-feu avant de passer la main ici — et de
`deploiement/windows/Demarrer-serveur.bat` pour la tâche planifiée.

Trois choses à la fois : le certificat (créé s'il manque, refait si l'adresse
de la machine a changé ou s'il arrive en fin de validité), le serveur
d'application sur la boucle locale, et la terminaison TLS ouverte au réseau.

Le serveur d'application est volontairement lié à **127.0.0.1** : le port 8000
n'est donc joignable d'aucune autre machine. Seul le port 8443, chiffré, sort sur
le réseau. Sans cela, un opérateur qui taperait `http://ip:8000` obtiendrait
l'application en clair — et Django, se croyant derrière un proxy HTTPS, le
redirigerait vers `https://ip:8000`, un port qui ne parle pas TLS.

    python outils/demarrer_https.py
    python outils/demarrer_https.py --service              (tâche planifiée du serveur)
    python outils/demarrer_https.py --port 8443 --port-appli 8000
"""
import argparse
import datetime as dt
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
import certificat_https as C  # noqa: E402


def python_venv():
    exe = RACINE / ".venv" / "Scripts" / "python.exe"
    return str(exe) if exe.is_file() else sys.executable


#: Réglages de waitress derrière le terminateur TLS, partagés avec le tunnel.
#:
#: --trusted-proxy : waitress 3 jette par défaut les entêtes X-Forwarded-*.
#:   Django ne voyait donc jamais « https » : `request.is_secure()` restait faux,
#:   les adresses absolues partaient en http://, et la moindre redirection HTTPS
#:   tournait en boucle. Les entêtes ne sont crus que venant de 127.0.0.1 — le
#:   terminateur, ou cloudflared pour le tunnel — qui écrasent ceux du client.
#: X-Forwarded-For : l'adresse réelle du téléphone. Sans elle, tous les clients
#:   arrivaient de 127.0.0.1, et le frein aux essais de mot de passe ne pouvait
#:   pas distinguer un poste d'un autre.
#: --connection-limit : 100 par défaut, et chaque téléphone en ouvre plusieurs.
#:   Sous Windows, waitress ne peut pas dépasser ~500 connexions (select).
OPTIONS_WAITRESS = ["--threads=8", "--connection-limit=300", "--channel-timeout=120",
                    "--trusted-proxy=127.0.0.1",
                    "--trusted-proxy-headers=x-forwarded-for x-forwarded-proto"]


def serveur_appli(port_appli):
    """waitress s'il est là, `runserver` sinon — jamais rien d'autre à installer."""
    py = python_venv()
    waitress = RACINE / ".venv" / "Scripts" / "waitress-serve.exe"
    if waitress.is_file():
        return [str(waitress), f"--listen=127.0.0.1:{port_appli}",
                *OPTIONS_WAITRESS, "config.wsgi:application"]
    return [py, "manage.py", "runserver", f"127.0.0.1:{port_appli}", "--noreload"]


def _liste(texte):
    return [x.strip() for x in (texte or "").split(",") if x.strip()]


def preparer_environnement(port, service=False):
    """Réglages que Django attend quand le TLS est terminé devant lui.

    `DJANGO_DERRIERE_PROXY` existait déjà pour le tunnel Cloudflare : le cas est
    exactement le même. On y ajoute les origines de confiance — sans elles, la
    connexion à /admin/ échoue en « CSRF verification failed ».

    Les hôtes et origines déjà écrits dans `.env` sont repris, pas remplacés :
    ce que le lanceur pose dans l'environnement passe AVANT `.env`, et une
    liste calculée ici effaçait celle que l'administrateur y avait écrite.
    """
    env = dict(os.environ)
    if service:
        # La sortie du lanceur part dans logs/service.log : les avertissements
        # de Django n'y seraient qu'un doublon de wms.log, sans rotation.
        env["DJANGO_LOG_CONSOLE"] = "False"
    env["DJANGO_DERRIERE_PROXY"] = "True"
    # La redirection vers HTTPS n'a pas lieu d'être : le port 8000 n'est pas
    # exposé, et une redirection depuis lui pointerait vers un port sans TLS.
    env["DJANGO_FORCER_HTTPS"] = "False"
    # HSTS ne s'applique pas à une adresse IP, et pinerait un nom d'hôte interne
    # pour un an. Inutile ici, gênant plus tard.
    env["DJANGO_HSTS_SECONDS"] = "0"
    origines = [f"https://{a}:{port}" for a in C.adresses_locales()]
    origines += [f"https://{n}:{port}" for n in C.noms_locaux()]
    anciennes = _liste(C.valeur_env("DJANGO_CSRF_ORIGINS"))
    env["DJANGO_CSRF_ORIGINS"] = ",".join(dict.fromkeys(anciennes + origines))
    hotes = _liste(C.valeur_env("DJANGO_ALLOWED_HOSTS"))
    if "*" in hotes:
        env["DJANGO_ALLOWED_HOSTS"] = "*"
    else:
        env["DJANGO_ALLOWED_HOSTS"] = ",".join(
            dict.fromkeys(hotes + C.adresses_locales() + C.noms_locaux()))
    return env


def port_occupe(port):
    """Vrai si quelque chose répond déjà sur ce port de la machine."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


#: Le certificat serveur est refait un mois avant sa fin : signé par la même
#: autorité, il ne demande rien aux téléphones — mais un certificat expiré,
#: lui, les arrête tous le même matin.
MARGE_RENOUVELLEMENT = dt.timedelta(days=30)


def certificat_a_refaire():
    """Le motif pour lequel le certificat serveur doit être refait, ou ''."""
    if not (C.SRV_CERT.is_file() and C.SRV_CLE.is_file()):
        return "absent"
    try:
        from cryptography import x509
        fin = x509.load_pem_x509_certificate(C.SRV_CERT.read_bytes()).not_valid_after_utc
        if fin - dt.datetime.now(dt.timezone.utc) < MARGE_RENOUVELLEMENT:
            return f"fin de validité le {fin:%d/%m/%Y}"
    except Exception:
        return "illisible"
    return ""


#: Le service tourne des mois sans redémarrer : le certificat est vérifié
#: toutes les six heures, et refait — puis remis en service sans coupure — s'il
#: approche de sa fin ou si la machine a changé d'adresse.
INTERVALLE_VEILLE = 6 * 3600


def horodater(texte):
    return f"[{dt.datetime.now():%d/%m/%Y %H:%M:%S}] {texte}"


def motif_renouvellement():
    """Pourquoi le certificat serveur doit être refait maintenant, ou ''."""
    motif = certificat_a_refaire()
    if motif:
        return motif
    manquants = C.non_couverts()
    if manquants:
        return "non couvert : " + ", ".join(manquants)
    return ""


def veiller_certificat(recharger):
    """Un tour de veille : refait le certificat s'il le faut, puis appelle
    `recharger()` pour le servir sans couper le WMS. Rend le motif, ou ''."""
    motif = motif_renouvellement()
    if not motif:
        return ""
    try:
        C.refaire_certificat_serveur()
    except Exception as e:  # noqa: BLE001 - la veille ne doit jamais tuer le service
        print(horodater(f"Certificat à refaire ({motif}) : ÉCHEC — {e}"), flush=True)
        return motif
    servi = recharger()
    print(horodater(f"Certificat refait ({motif})"
                    + (" et remis en service." if servi else
                       " : il sera servi au prochain démarrage.")), flush=True)
    return motif


def poste_remplace():
    """L'adresse du serveur qui a pris le relais de ce poste, ou ''.

    Après la bascule sur le serveur, un double-clic sur Demarrer-WMS.bat par
    habitude relançait l'ancien WMS : les téléphones qui passaient encore par
    l'adresse IP du PC écrivaient dans une base que plus personne ne lit.
    `WMS_REMPLACE_PAR=https://wms.structa.fr:8443` dans le `.env` du PC l'empêche.
    """
    return C.valeur_env("WMS_REMPLACE_PAR").strip()


def ouvrir_navigateur(port):
    """Ouvre le WMS sur ce PC. Une machine sans navigateur n'est pas une erreur."""
    try:
        webbrowser.open(f"https://localhost:{port}/")
    except Exception:
        pass


def adresse_principale(adresses):
    """L'adresse du même sous-réseau que la passerelle par défaut, ou None.

    C'est le seul repère fiable : le nom de la carte varie, sa description aussi,
    mais la route par défaut désigne toujours l'interface qui sort réellement.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object -First 1).NextHop"],
            capture_output=True, text=True, timeout=15)
        passerelle = r.stdout.strip()
    except Exception:
        passerelle = ""
    if not passerelle or "." not in passerelle:
        return None
    prefixe = passerelle.rsplit(".", 1)[0] + "."
    return next((a for a in adresses if a.startswith(prefixe)), None)


def empreinte_autorite():
    """Empreinte SHA-1 de l'autorité, telle que `certutil` la désigne."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        cert = x509.load_pem_x509_certificate(C.AC_CERT.read_bytes())
        return cert.fingerprint(hashes.SHA1()).hex().upper()
    except Exception:
        return None


def installer_autorite_windows():
    """Ajoute l'autorité au magasin de confiance de Windows, si elle n'y est pas.

    Edge et Chrome lisent ce magasin : sans cela, ils affichent
    « ERR_CERT_AUTHORITY_INVALID » sur le serveur, alors que la connexion
    fonctionne parfaitement. On installe donc l'autorité sur la machine qui
    héberge le WMS — c'est là qu'on la consulte le plus souvent.

    Sans droits administrateur, l'opération échoue proprement : le serveur
    démarre quand même, seul l'avertissement subsiste dans le navigateur.
    """
    if os.name != "nt" or not C.AC_CERT.is_file():
        return None
    empreinte = empreinte_autorite()
    if empreinte:
        try:
            deja = subprocess.run(["certutil", "-store", "Root", empreinte],
                                  capture_output=True, text=True, timeout=25)
            if deja.returncode == 0 and empreinte.lower() in deja.stdout.lower().replace(" ", ""):
                return "deja"
        except Exception:
            pass
    try:
        r = subprocess.run(["certutil", "-addstore", "-f", "Root", str(C.AC_CERT)],
                           capture_output=True, text=True, timeout=40)
        return "installee" if r.returncode == 0 else "refusee"
    except Exception:
        return "refusee"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, default=C.port_https(),
                   help="port HTTPS ouvert au réseau (défaut : WMS_PORT_HTTPS de .env, sinon 8443)")
    p.add_argument("--port-appli", type=int, default=8000,
                   help="port du serveur d'application, sur la boucle locale")
    p.add_argument("--sans-navigateur", action="store_true",
                   help="ne pas ouvrir le WMS dans le navigateur")
    p.add_argument("--service", action="store_true",
                   help="tâche planifiée du serveur : sans navigateur, messages "
                        "horodatés, journaux de Django dans wms.log seulement")
    args = p.parse_args()
    if args.service:
        args.sans_navigateur = True

    # Ce poste a été remplacé par le serveur : on ne relance pas l'ancien WMS.
    remplace = poste_remplace()
    if remplace:
        print("\n  Le WMS ne tourne plus sur ce poste : il a été transféré sur")
        print(f"      {remplace}")
        print("  Rien n'est démarré ici. Pour revenir sur ce poste (retour arrière),")
        print("  retirez la ligne WMS_REMPLACE_PAR du fichier .env.\n")
        return 2

    # 0. Déjà démarré — une autre fenêtre, ou la tâche planifiée : on n'en lance
    #    pas un second, on montre le premier.
    if port_occupe(args.port):
        print(f"\n  Le WMS tourne déjà sur ce PC : https://localhost:{args.port}")
        print("  Rien à démarrer. Pour le relancer, fermez d'abord sa fenêtre.\n")
        if not args.sans_navigateur:
            ouvrir_navigateur(args.port)
        return 0
    if port_occupe(args.port_appli):
        print(f"\n  Le port {args.port_appli} est déjà pris sur ce PC.")
        print("  Le plus souvent : un WMS lancé par l'ancien Demarrer-WMS.bat tourne")
        print("  encore, dans une fenêtre « WMS Structa - serveur ». Fermez-la, puis")
        print("  relancez Demarrer-WMS.bat.\n")
        return 1

    # 1. Certificat : créé s'il manque, refait si l'adresse de la machine a
    #    changé ou s'il arrive en fin de validité.
    motif = certificat_a_refaire()
    if motif == "absent":
        print("\n  Aucun certificat : création.")
        sys.argv = ["certificat_https.py"]
        C.main()
    elif motif:
        print(f"\n  Certificat serveur à refaire ({motif}) : il est refait.")
        sys.argv = ["certificat_https.py", "--refaire"]
        C.main()
    elif C.etat() != 0:
        print("\n  L'adresse de la machine a changé : le certificat est refait.")
        sys.argv = ["certificat_https.py", "--refaire"]
        C.main()

    # L'autorité dans le magasin Windows : sinon Edge et Chrome refusent le
    # serveur sur cette machine même, avec un message qui laisse croire à une
    # panne alors que tout fonctionne.
    etat_ac = installer_autorite_windows()
    if etat_ac == "installee":
        print("  Autorité ajoutée au magasin de confiance de Windows.")
    elif etat_ac == "refusee":
        print("  Note : autorité NON ajoutée au magasin Windows (droits administrateur")
        print("         requis). Edge et Chrome afficheront un avertissement sur ce PC.")

    env = preparer_environnement(args.port, service=args.service)
    print(horodater("Démarrage du serveur d'application (boucle locale)…")
          if args.service else "\n  Démarrage du serveur d'application (boucle locale)…")
    appli = subprocess.Popen(serveur_appli(args.port_appli), cwd=str(RACINE), env=env)
    time.sleep(2.5)
    if appli.poll() is not None:
        sys.exit("\n  Le serveur d'application s'est arrêté aussitôt : son message "
                 "d'erreur est juste au-dessus.")

    adresses = [a for a in C.adresses_locales() if a != "127.0.0.1"]
    # Une machine avec VirtualBox, VMware ou WSL porte plusieurs adresses, dont
    # une seule mène au réseau de l'entrepôt. Afficher les deux sans les
    # distinguer fait essayer la mauvaise pendant une heure : on retient celle
    # du même sous-réseau que la passerelle par défaut.
    principale = adresse_principale(adresses)
    print("\n  " + "-" * 62)
    if principale:
        print("  Le WMS est en HTTPS. Adresse à donner aux téléphones :")
        print(f"      https://{principale}:{args.port}")
        autres = [a for a in adresses if a != principale]
        if autres:
            print("\n  (cartes virtuelles, à ne pas utiliser : "
                  + ", ".join(autres) + ")")
    elif adresses:
        print("  Le WMS est en HTTPS. Adresses possibles :")
        for a in adresses:
            print(f"      https://{a}:{args.port}")
    else:
        print("      (aucune adresse réseau détectée — machine hors réseau ?)")
    print(f"\n  Sur ce PC :  https://localhost:{args.port}")
    print("  " + "-" * 62)
    print("\n  Première fois sur un téléphone : installez l'autorité")
    print(f"      {C.AC_CERT}")
    print("  Sans elle, le navigateur affiche un avertissement de sécurité.")
    print("  Voir docs/guide-https.md.")
    print("\n  Pour arrêter le WMS : fermez cette fenêtre.\n")

    import proxy_https as P
    P.CERT, P.CLE = C.SRV_CERT, C.SRV_CLE
    appli_tombee = False
    try:
        import asyncio

        async def surveiller(serveur):
            # Le serveur d'application tombe (base injoignable, erreur au
            # démarrage d'un fil) : on arrête tout, plutôt que de laisser le port
            # 8443 répondre « 502 » à des téléphones qui croiraient le WMS en
            # marche. La fenêtre le dit, et la tâche planifiée peut relancer.
            nonlocal appli_tombee
            while appli.poll() is None:
                await asyncio.sleep(3)
            appli_tombee = True
            print(horodater("Le serveur d'application s'est arrêté (code "
                            f"{appli.returncode}) : le WMS s'arrête aussi."), flush=True)
            serveur.close()

        async def veiller():
            while True:
                await asyncio.sleep(INTERVALLE_VEILLE)
                await asyncio.to_thread(veiller_certificat, P.recharger_certificat)

        async def tourner():
            serveur = await P.demarrer(("0.0.0.0", args.port), ("127.0.0.1", args.port_appli))
            veille = asyncio.create_task(surveiller(serveur))
            veille_certificat = asyncio.create_task(veiller())
            if not args.sans_navigateur:
                ouvrir_navigateur(args.port)
            try:
                await serveur.serve_forever()
            except asyncio.CancelledError:
                if not appli_tombee:
                    raise                     # Ctrl+C : l'arrêt suit son cours
            finally:
                veille.cancel()
                veille_certificat.cancel()
                # Fermer sans attendre les connexions encore ouvertes : un
                # téléphone resté sur une page garde la sienne, et l'arrêt
                # attendrait qu'il la lâche.
                serveur.close()
                fermer = getattr(serveur, "close_clients", None)   # Python 3.13+
                if fermer:
                    fermer()

        asyncio.run(tourner())
    except KeyboardInterrupt:
        print("\n  Arrêt demandé.")
    finally:
        if appli.poll() is None:
            appli.terminate()
            try:
                appli.wait(timeout=10)
            except Exception:
                appli.kill()
        print("  Serveur d'application arrêté.\n")
    return 1 if appli_tombee else 0


if __name__ == "__main__":
    sys.exit(main())
