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

L'adresse est affichée, et une page avec un QR code s'ouvre : les caristes
scannent l'écran plutôt que de recopier une adresse aléatoire.
"""
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from queue import Empty, Queue

RACINE = Path(__file__).resolve().parent.parent
ADRESSE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
ATTENTE_MAX = 90  # secondes avant d'abandonner l'attente de l'adresse


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


def page_qr(adresse):
    """Écrit une page locale : l'adresse en grand, et son QR code.

    L'adresse d'un tunnel est aléatoire et longue. La recopier sur le clavier
    d'un téléphone, dix fois par jour et à chaque relance, ne tient pas : on
    affiche un QR que l'appareil photo lit d'un regard.
    """
    lib = RACINE / "wms" / "static" / "app" / "vendor" / "qrcode.min.js"
    script = lib.read_text(encoding="utf-8") if lib.is_file() else ""
    fichier = RACINE / "logs" / "acces-tunnel.html"
    fichier.parent.mkdir(parents=True, exist_ok=True)
    manque = "" if script else (
        "<p class='alerte'>Le generateur de QR n'est pas installe. "
        "Lancez une fois : python manage.py telecharger_libs</p>")
    fichier.write_text(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Acces WMS</title><style>
 body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#1C394B;color:#fff;
      margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;
      justify-content:center;gap:1.5rem;padding:2rem;box-sizing:border-box;text-align:center}}
 h1{{font-size:1.4rem;font-weight:600;margin:0;letter-spacing:.02em}}
 #qr{{background:#fff;padding:1.25rem;border-radius:12px;line-height:0}}
 .adresse{{font-family:ui-monospace,Consolas,monospace;font-size:1.15rem;background:#0f2634;
          padding:.75rem 1.1rem;border-radius:8px;word-break:break-all;max-width:32rem}}
 .note{{opacity:.75;font-size:.9rem;max-width:34rem;line-height:1.5}}
 .alerte{{color:#f0b429}}
</style></head><body>
<h1>Scannez pour ouvrir le WMS</h1>
<div id="qr"></div>
<div class="adresse">{adresse}</div>
{manque}
<p class="note">Cette adresse est publique et <strong>change a chaque
demarrage</strong>. Ne fermez pas la fenetre du tunnel : l'acces s'arrete avec
elle. Laissez cette page ouverte, les caristes scannent l'ecran.</p>
<script>{script}</script>
<script>
 if (typeof QRCode !== 'undefined') {{
   new QRCode(document.getElementById('qr'),
     {{ text: {adresse!r}, width: 260, height: 260, correctLevel: QRCode.CorrectLevel.M }});
 }}
</script></body></html>""", encoding="utf-8")
    return fichier


def lire_en_fond(flux, file_attente):
    for ligne in iter(flux.readline, ""):
        file_attente.put(ligne.rstrip("\n"))
    flux.close()


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

    print("  Ouverture du tunnel...\n")
    tunnel = subprocess.Popen(
        [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{port}"],
        cwd=str(RACINE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace")
    lignes = Queue()
    threading.Thread(target=lire_en_fond, args=(tunnel.stdout, lignes),
                     daemon=True).start()

    adresse = None
    limite = time.monotonic() + ATTENTE_MAX
    try:
        while adresse is None and time.monotonic() < limite:
            if tunnel.poll() is not None:
                print("\n  Le tunnel s'est ferme avant de donner une adresse.")
                print("  Ce poste a-t-il acces a internet ? Un proxy d'entreprise")
                print("  peut bloquer la connexion sortante de cloudflared.\n")
                appli.terminate()
                return 1
            try:
                ligne = lignes.get(timeout=0.5)
            except Empty:
                continue
            trouvee = ADRESSE.search(ligne)
            if trouvee:
                adresse = trouvee.group(0)

        if adresse is None:
            print("\n  Aucune adresse apres "
                  f"{ATTENTE_MAX} secondes. Le tunnel reste ouvert : regardez la")
            print("  fenetre de cloudflared, l'adresse peut arriver en retard.\n")
        else:
            fichier = page_qr(adresse)
            print("\n  " + "=" * 62)
            print("   ADRESSE A OUVRIR SUR LES TELEPHONES :")
            print(f"\n      {adresse}\n")
            print("   Une page avec le QR code correspondant vient de s'ouvrir :")
            print("   les caristes scannent l'ecran, rien a recopier.")
            print("  " + "=" * 62)
            print(f"\n   Page : {fichier}")
            print("\n   Cette fenetre doit rester ouverte. La fermer coupe l'acces.\n")
            try:
                webbrowser.open(fichier.as_uri())
            except Exception:
                pass

        # On relaie ce que dit cloudflared : une coupure doit se voir.
        while tunnel.poll() is None and appli.poll() is None:
            try:
                print("   [tunnel] " + lignes.get(timeout=1.0))
            except Empty:
                pass
    except KeyboardInterrupt:
        print("\n  Arret demande.")
    finally:
        for processus in (tunnel, appli):
            if processus.poll() is None:
                processus.terminate()
                try:
                    processus.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    processus.kill()
        print("  Serveur et tunnel arretes.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
