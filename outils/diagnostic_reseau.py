"""Où le WMS est-il bloqué : le serveur, le pare-feu Windows, ou le réseau ?

Les trois causes donnent le même symptôme au poste — « ça ne charge pas » — et
appellent trois actions différentes : relancer le serveur, cliquer trois cases
sur ce PC, ou écrire au service informatique. Deviner fait perdre des jours.

Ce script interroge chaque couche dans l'ordre où le paquet les traverse, et
s'arrête à la première qui bloque.

    python outils/diagnostic_reseau.py
    python outils/diagnostic_reseau.py --port 8443
"""
import argparse
import socket
import subprocess
import sys

OK, KO, INFO, DOUTE = "  OK   ", "  BLOQUE", "  ---  ", "  ?    "


def powershell(commande):
    """Renvoie la sortie de PowerShell, ou None. Ne lève jamais."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", commande],
                           capture_output=True, text=True, timeout=25)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def adresses():
    trouvees = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("10.255.255.255", 1))
        trouvees.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            a = i[4][0]
            if a not in trouvees and not a.startswith("127."):
                trouvees.append(a)
    except Exception:
        pass
    return trouvees


def ecoute(port):
    """Le serveur écoute-t-il, et sur quelle interface ?

    Écouter sur 127.0.0.1 seulement est le piège le plus fréquent : tout marche
    sur le PC, rien depuis un téléphone, et aucun message d'erreur nulle part.
    """
    sortie = powershell(
        f"Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty LocalAddress")
    if sortie is None:
        try:
            r = subprocess.run(["netstat", "-an"], capture_output=True, text=True, timeout=20)
            lignes = [ligne for ligne in r.stdout.splitlines()
                      if f":{port}" in ligne and "LISTEN" in ligne.upper()]
            return [ligne.split()[1].rsplit(":", 1)[0] for ligne in lignes]
        except Exception:
            return None
    return [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()]


def joignable(hote, port, delai=3.0):
    try:
        with socket.create_connection((hote, port), timeout=delai):
            return True
    except Exception:
        return False


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, default=8443)
    args = p.parse_args()
    port = args.port
    ips = adresses()
    bloquant = None

    print("\n" + "=" * 66)
    print("  DIAGNOSTIC — pourquoi les téléphones ne joignent pas le WMS")
    print("=" * 66)

    # --- 1. Le serveur écoute-t-il, et où ? ---------------------------------
    print("\n  1. LE SERVEUR")
    interfaces = ecoute(port)
    if interfaces is None:
        print(DOUTE, f"impossible de lire l'état du port {port}.")
    elif not interfaces:
        print(KO, f"rien n'écoute sur le port {port}.")
        print(INFO, "  -> Demarrer-WMS-HTTPS.bat n'est pas lancé, ou s'est arrêté.")
        bloquant = "serveur"
    else:
        ouvert_partout = any(a in ("0.0.0.0", "::", "*") for a in interfaces)
        print(OK if ouvert_partout else KO,
              f"port {port} en écoute sur : {', '.join(interfaces)}")
        if not ouvert_partout:
            print(INFO, "  -> le serveur n'écoute QUE sur cette machine.")
            print(INFO, "     Tout marche ici, rien depuis un téléphone.")
            bloquant = bloquant or "ecoute-locale"

    if not bloquant and not joignable("127.0.0.1", port):
        print(KO, "le port refuse la connexion depuis cette machine même.")
        bloquant = "serveur"
    elif not bloquant:
        print(OK, "l'application répond en boucle locale (127.0.0.1).")

    # Se joindre par sa PROPRE adresse réseau : c'est le test qui sépare
    # « mon PC ne sert que lui-même » de « le réseau ne laisse pas passer ».
    # Sous Windows, ce trajet traverse la pile réseau et le pare-feu comme le
    # ferait un autre poste — sauf les règles d'isolation, qui sont ailleurs.
    for a in adresses():
        if joignable(a, port, 2.0):
            print(OK, f"l'application répond aussi sur {a} (son adresse réseau).")
        else:
            print(KO, f"l'application NE répond PAS sur {a}.")
            bloquant = bloquant or "adresse-reseau"

    # --- 2. Le pare-feu Windows ---------------------------------------------
    print("\n  2. LE PARE-FEU WINDOWS")
    profil = powershell("(Get-NetConnectionProfile | Select-Object -First 1).NetworkCategory")
    if profil:
        print(INFO, f"réseau classé par Windows : {profil}")
        if profil.lower() == "public":
            print(KO, "profil « Public » : Windows bloque TOUTE entrée par défaut,")
            print(INFO, "     et la règle du WMS ne couvre que Domaine et Privé.")
            print(INFO, "  -> Paramètres > Réseau > (votre réseau) > passer en « Privé ».")
            print(INFO, "     C'est LA cause la plus fréquente, et elle se règle en 10 secondes.")
            bloquant = bloquant or "profil-public"
    else:
        print(DOUTE, "profil réseau illisible.")

    regle = powershell(
        "$r = Get-NetFirewallRule -DisplayName 'WMS Structa HTTPS' -ErrorAction SilentlyContinue; "
        "if ($r) { \"$($r.Enabled)|$($r.Profile)|$($r.Action)|$($r.Direction)\" }")
    if not regle:
        print(KO, "aucune règle de pare-feu « WMS Structa HTTPS ».")
        print(INFO, "  -> relancez Demarrer-WMS-HTTPS.bat en ADMINISTRATEUR")
        print(INFO, "     (clic droit > Exécuter en tant qu'administrateur).")
        bloquant = bloquant or "regle-absente"
    else:
        actif, profils, action, sens = (regle.split("|") + ["", "", "", ""])[:4]
        bon = actif.lower() in ("true", "1") and action.lower() == "allow"
        print(OK if bon else KO,
              f"règle trouvée : active={actif}, profils={profils}, {action}, {sens}")
        # `Get-NetConnectionProfile` et le pare-feu ne parlent pas le même
        # vocabulaire : la catégorie « DomainAuthenticated » correspond au profil
        # de pare-feu « Domain ». Comparer les deux mots tels quels faisait
        # accuser le pare-feu à tort, alors qu'il autorisait bien le flux.
        EQUIVALENCES = {"domainauthenticated": "domain", "domain": "domain",
                        "private": "private", "public": "public"}
        attendu = EQUIVALENCES.get((profil or "").lower(), (profil or "").lower())
        couverts = [x.strip().lower() for x in profils.split(",")]
        if profil and attendu not in couverts and "any" not in couverts:
            print(KO, f"la règle ne couvre pas le profil « {profil} » du réseau actuel.")
            bloquant = bloquant or "regle-mauvais-profil"
        elif profil:
            print(OK, f"le profil « {profil} » est bien couvert par la règle.")

    # --- 3. Le réseau -------------------------------------------------------
    print("\n  3. LE RÉSEAU")
    if not ips:
        print(KO, "aucune adresse réseau : cette machine n'est pas sur le réseau.")
        bloquant = bloquant or "hors-reseau"
    else:
        passerelle = powershell(
            "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object -First 1).NextHop")
        # L'adresse qui compte est celle du même sous-réseau que la passerelle.
        # Les autres viennent de cartes virtuelles (VirtualBox, VMware, WSL) :
        # les donner à un téléphone ne mène nulle part, et on y perd une heure.
        principale = None
        if passerelle:
            prefixe = passerelle.rsplit(".", 1)[0] + "."
            principale = next((a for a in ips if a.startswith(prefixe)), None)
        for a in ips:
            if a == principale:
                print(OK, f"adresse à donner aux téléphones : {a}")
            elif principale:
                print(INFO, f"autre adresse : {a}  (carte virtuelle — ne pas utiliser)")
            else:
                print(INFO, f"adresse de ce PC : {a}")
        if passerelle:
            print(INFO, f"passerelle : {passerelle}")
        ips = [principale] if principale else ips

    # --- Verdict ------------------------------------------------------------
    print("\n" + "=" * 66)
    if bloquant == "serveur":
        print("  VERDICT : le serveur ne tourne pas. Rien à demander à personne.")
        print("  Lancez Demarrer-WMS-HTTPS.bat et relisez ce qu'il affiche.")
    elif bloquant == "ecoute-locale":
        print("  VERDICT : le serveur n'écoute que sur lui-même.")
        print("  Utilisez Demarrer-WMS-HTTPS.bat, qui ouvre le port au réseau.")
    elif bloquant == "profil-public":
        print("  VERDICT : c'est Windows, et VOUS pouvez le régler.")
        print("  Passez le réseau en « Privé », puis relancez ce diagnostic.")
    elif bloquant in ("regle-absente", "regle-mauvais-profil"):
        print("  VERDICT : c'est le pare-feu de CE PC, et vous pouvez le régler.")
        print("  Relancez Demarrer-WMS-HTTPS.bat en administrateur.")
    elif bloquant == "adresse-reseau":
        print("  VERDICT : le serveur écoute mais ne répond pas sur son adresse réseau.")
        print("  C'est le pare-feu de CE PC. Relancez le .bat en administrateur.")
    elif bloquant == "hors-reseau":
        print("  VERDICT : cette machine n'est pas connectée au réseau.")
    else:
        print("  VERDICT : de ce côté, tout est en ordre.")
        print("  Le serveur écoute, le pare-feu autorise, la machine est sur le réseau.")
        print("\n  Si un téléphone ne joint toujours pas :")
        for a in ips:
            print(f"      https://{a}:{port}/api/sante/")
        print("\n  alors le blocage est DANS LE RÉSEAU, hors de ce PC :")
        print("   - le WiFi et le poste sont sur deux VLAN qui ne se parlent pas ;")
        print("   - ou l'isolation client est active sur la borne WiFi.")
        print("  Dans les deux cas, seul le service informatique peut ouvrir.")
    print("=" * 66 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
