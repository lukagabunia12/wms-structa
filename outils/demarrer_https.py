"""Démarre le WMS en HTTPS sur le réseau interne, d'un seul geste.

Trois choses à la fois : le certificat s'il manque, le serveur d'application sur
la boucle locale, et la terminaison TLS ouverte au réseau.

Le serveur d'application est volontairement lié à **127.0.0.1** : le port 8000
n'est donc joignable d'aucune autre machine. Seul le port 8443, chiffré, sort sur
le réseau. Sans cela, un opérateur qui taperait `http://ip:8000` obtiendrait
l'application en clair — et Django, se croyant derrière un proxy HTTPS, le
redirigerait vers `https://ip:8000`, un port qui ne parle pas TLS.

    python outils/demarrer_https.py
    python outils/demarrer_https.py --port 8443 --port-appli 8000
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
import certificat_https as C  # noqa: E402


def python_venv():
    exe = RACINE / ".venv" / "Scripts" / "python.exe"
    return str(exe) if exe.is_file() else sys.executable


def serveur_appli(port_appli):
    """waitress s'il est là, `runserver` sinon — jamais rien d'autre à installer."""
    py = python_venv()
    waitress = RACINE / ".venv" / "Scripts" / "waitress-serve.exe"
    if waitress.is_file():
        return [str(waitress), f"--listen=127.0.0.1:{port_appli}",
                "--threads=8", "config.wsgi:application"]
    return [py, "manage.py", "runserver", f"127.0.0.1:{port_appli}", "--noreload"]


def preparer_environnement(port):
    """Réglages que Django attend quand le TLS est terminé devant lui.

    `DJANGO_DERRIERE_PROXY` existait déjà pour le tunnel Cloudflare : le cas est
    exactement le même. On y ajoute les origines de confiance — sans elles, la
    connexion à /admin/ échoue en « CSRF verification failed ».
    """
    env = dict(os.environ)
    env["DJANGO_DERRIERE_PROXY"] = "True"
    # La redirection vers HTTPS n'a pas lieu d'être : le port 8000 n'est pas
    # exposé, et une redirection depuis lui pointerait vers un port sans TLS.
    env["DJANGO_FORCER_HTTPS"] = "False"
    # HSTS ne s'applique pas à une adresse IP, et pinerait un nom d'hôte interne
    # pour un an. Inutile ici, gênant plus tard.
    env["DJANGO_HSTS_SECONDS"] = "0"
    origines = [f"https://{a}:{port}" for a in C.adresses_locales()]
    origines += [f"https://{n}:{port}" for n in C.noms_locaux()]
    anciennes = [x for x in env.get("DJANGO_CSRF_ORIGINS", "").split(",") if x.strip()]
    env["DJANGO_CSRF_ORIGINS"] = ",".join(dict.fromkeys(anciennes + origines))
    hotes = [x for x in env.get("DJANGO_ALLOWED_HOSTS", "").split(",") if x.strip()]
    if "*" not in hotes:
        env["DJANGO_ALLOWED_HOSTS"] = ",".join(
            dict.fromkeys(hotes + C.adresses_locales() + C.noms_locaux()))
    return env


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
    p.add_argument("--port", type=int, default=8443, help="port HTTPS ouvert au réseau")
    p.add_argument("--port-appli", type=int, default=8000,
                   help="port du serveur d'application, sur la boucle locale")
    args = p.parse_args()

    # 1. Certificat : créé s'il manque, refait si l'adresse de la machine a changé.
    if not (C.SRV_CERT.is_file() and C.SRV_CLE.is_file()):
        print("\n  Aucun certificat : création.")
        sys.argv = ["certificat_https.py"]
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

    env = preparer_environnement(args.port)
    print("\n  Démarrage du serveur d'application (boucle locale)…")
    appli = subprocess.Popen(serveur_appli(args.port_appli), cwd=str(RACINE), env=env)
    time.sleep(2.5)
    if appli.poll() is not None:
        sys.exit("Le serveur d'application s'est arrêté aussitôt. "
                 "Lancez Demarrer-WMS.bat seul pour voir l'erreur.")

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
    print("  Voir docs/guide-https.md.\n")

    import proxy_https as P
    P.CERT, P.CLE = C.SRV_CERT, C.SRV_CLE
    try:
        import asyncio

        async def tourner():
            serveur = await P.demarrer(("0.0.0.0", args.port), ("127.0.0.1", args.port_appli))
            async with serveur:
                await serveur.serve_forever()

        asyncio.run(tourner())
    except KeyboardInterrupt:
        print("\n  Arrêt demandé.")
    finally:
        appli.terminate()
        try:
            appli.wait(timeout=10)
        except Exception:
            appli.kill()
        print("  Serveur d'application arrêté.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
