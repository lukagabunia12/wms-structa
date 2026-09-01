"""Génère une autorité de certification locale et le certificat du serveur WMS.

Pourquoi c'est nécessaire : les navigateurs mobiles refusent l'accès à la caméra
hors HTTPS. Sans certificat, le scan des QR codes est indisponible sur les
téléphones — la fonction qui fait tout l'intérêt de l'application au poste.

Pourquoi une autorité locale plutôt qu'un certificat auto-signé seul : un
certificat auto-signé déclenche un avertissement **à chaque appareil et à chaque
renouvellement**. Avec une autorité, on installe une fois l'autorité sur chaque
téléphone, et tous les certificats qu'elle signe ensuite sont acceptés sans
avertissement — y compris après renouvellement.

    python outils/certificat_https.py            # génère ce qui manque
    python outils/certificat_https.py --refaire  # regénère le certificat serveur
    python outils/certificat_https.py --etat     # ce qui existe, et jusqu'à quand
"""
import argparse
import datetime as dt
import ipaddress
import socket
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "certificats"
AC_CERT = DOSSIER / "ac-structa.crt"
AC_CLE = DOSSIER / "ac-structa.key"
SRV_CERT = DOSSIER / "wms.crt"
SRV_CLE = DOSSIER / "wms.key"

#: Apple refuse tout certificat serveur dont la validité dépasse 398 jours —
#: silencieusement, avec une erreur de confiance illisible.
#:
#: 395 et non 397 : le certificat est antidaté d'un jour pour tolérer une horloge
#: mal réglée, si bien que 397 donnait une durée totale de 398 jours — la limite
#: exacte, pas en dessous. Deux jours de marge coûtent moins qu'un iPhone qui
#: refuse sans dire pourquoi.
JOURS_SERVEUR = 395
ANNEES_AC = 10


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        return x509, hashes, serialization, rsa, NameOID
    except ImportError:
        sys.exit("Le module « cryptography » est absent.\n"
                 "  .venv\\Scripts\\python.exe -m pip install -r requirements-https.txt")


def adresses_locales():
    """Toutes les adresses IPv4 de la machine, plus la boucle locale.

    Le certificat doit couvrir l'adresse par laquelle les téléphones arrivent.
    Un certificat émis pour le seul nom d'hôte provoque une erreur de sécurité
    dès qu'on tape l'adresse IP — ce que font les opérateurs.
    """
    trouvees = {"127.0.0.1"}
    try:
        # Aucune donnée n'est envoyée : on demande juste au système quelle
        # interface il utiliserait pour sortir, ce qui donne l'IP du LAN.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("10.255.255.255", 1))
        trouvees.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            trouvees.add(info[4][0])
    except Exception:
        pass
    return sorted(trouvees)


def noms_locaux():
    noms = {"localhost"}
    try:
        h = socket.gethostname()
        noms.add(h)
        noms.add(h + ".local")
        noms.add(h.lower())
    except Exception:
        pass
    return sorted(noms)


def _nom(NameOID, x509, commun, organisation="STRUCTA INDUSTRIES"):
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organisation),
        x509.NameAttribute(NameOID.COMMON_NAME, commun),
    ])


def creer_autorite():
    x509, hashes, serialization, rsa, NameOID = _crypto()
    cle = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    sujet = _nom(NameOID, x509, "Autorite interne WMS Structa")
    maintenant = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(sujet).issuer_name(sujet)
            .public_key(cle.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(maintenant - dt.timedelta(days=1))
            .not_valid_after(maintenant + dt.timedelta(days=365 * ANNEES_AC))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle.public_key()),
                           critical=False)
            .sign(cle, hashes.SHA256()))
    DOSSIER.mkdir(exist_ok=True)
    AC_CLE.write_bytes(cle.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    AC_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        AC_CLE.chmod(0o600)
    except Exception:
        pass
    return cert, cle


def charger_autorite():
    x509, hashes, serialization, rsa, NameOID = _crypto()
    cert = x509.load_pem_x509_certificate(AC_CERT.read_bytes())
    cle = serialization.load_pem_private_key(AC_CLE.read_bytes(), password=None)
    return cert, cle


def creer_certificat_serveur(ac_cert, ac_cle, noms, ips):
    x509, hashes, serialization, rsa, NameOID = _crypto()
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    alternatives = [x509.DNSName(n) for n in noms]
    alternatives += [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    maintenant = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(_nom(NameOID, x509, noms[0]))
            .issuer_name(ac_cert.subject)
            .public_key(cle.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(maintenant - dt.timedelta(days=1))
            .not_valid_after(maintenant + dt.timedelta(days=JOURS_SERVEUR))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            # SAN obligatoire : depuis 2017 les navigateurs ignorent le CN.
            .add_extension(x509.SubjectAlternativeName(alternatives), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                           critical=False)
            .add_extension(x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle.public_key()),
                           critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ac_cert.public_key()), critical=False)
            .sign(ac_cle, hashes.SHA256()))
    DOSSIER.mkdir(exist_ok=True)
    SRV_CLE.write_bytes(cle.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    SRV_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        SRV_CLE.chmod(0o600)
    except Exception:
        pass
    return cert


def profil_ios():
    """Écrit un profil de configuration iOS qui installe l'autorité.

    Pourquoi en plus du `.crt` : iOS reconnaît mal un fichier `.crt` reçu par
    certaines applications de messagerie — Gmail, notamment, le traite comme une
    pièce jointe quelconque et ne propose jamais de l'installer. Le format
    `.mobileconfig` est celui qu'iOS attend : il s'ouvre dans Réglages sans
    détour, avec un nom lisible.

    Il ne dispense PAS d'activer la confiance à la main (Réglages > Général >
    Informations > Réglages de confiance) : seul un profil poussé par un serveur
    de gestion de flotte peut le faire, et il n'y en a pas ici.
    """
    import plistlib
    import uuid
    from cryptography import x509 as _x509
    from cryptography.hazmat.primitives import serialization as _ser

    cert = _x509.load_pem_x509_certificate(AC_CERT.read_bytes())
    der = cert.public_bytes(_ser.Encoding.DER)
    # Les identifiants sont dérivés de l'empreinte du certificat : réinstaller le
    # même profil le remplace au lieu d'en empiler un second.
    graine = uuid.uuid5(uuid.NAMESPACE_DNS, "wms.structa.fr/" + cert.fingerprint(
        __import__("cryptography.hazmat.primitives.hashes", fromlist=["SHA256"]).SHA256()).hex())
    profil = {
        "PayloadContent": [{
            "PayloadType": "com.apple.security.root",
            "PayloadVersion": 1,
            "PayloadIdentifier": "fr.structa.wms.autorite",
            "PayloadUUID": str(uuid.uuid5(graine, "racine")).upper(),
            "PayloadDisplayName": "Autorite interne WMS Structa",
            "PayloadDescription": "Certificat de l'autorite qui signe le serveur WMS.",
            "PayloadCertificateFileName": AC_CERT.name,
            "PayloadContent": der,
        }],
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": "fr.structa.wms",
        "PayloadUUID": str(graine).upper(),
        "PayloadDisplayName": "WMS Structa - autorite interne",
        "PayloadDescription": ("Installe l'autorite qui signe le certificat du serveur WMS. "
                               "Pensez ensuite a activer la confiance dans Reglages > General > "
                               "Informations > Reglages de confiance de certificat."),
        "PayloadOrganization": "STRUCTA INDUSTRIES",
        "PayloadRemovalDisallowed": False,
    }
    chemin = DOSSIER / "ac-structa.mobileconfig"
    chemin.write_bytes(plistlib.dumps(profil))
    return chemin


def etat():
    x509, hashes, serialization, rsa, NameOID = _crypto()
    if not AC_CERT.is_file():
        print("\n  Aucune autorité : lancez le script sans option.\n")
        return 1
    ac = x509.load_pem_x509_certificate(AC_CERT.read_bytes())
    print(f"\n  Autorité   : {AC_CERT.name}")
    print(f"               valable jusqu'au {ac.not_valid_after_utc:%d/%m/%Y}")
    if not SRV_CERT.is_file():
        print("  Serveur    : absent\n")
        return 1
    srv = x509.load_pem_x509_certificate(SRV_CERT.read_bytes())
    san = srv.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    noms = [str(n.value) for n in san]
    reste = (srv.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)).days
    print(f"  Serveur    : {SRV_CERT.name}")
    print(f"               valable jusqu'au {srv.not_valid_after_utc:%d/%m/%Y} "
          f"({reste} jour(s))")
    print(f"  Couvre     : {', '.join(noms)}")
    actuelles = set(adresses_locales())
    manquantes = actuelles - set(noms)
    if manquantes:
        print(f"\n  ATTENTION : l'adresse {', '.join(sorted(manquantes))} n'est pas couverte.")
        print("  L'adresse de la machine a changé — relancez avec --refaire.\n")
        return 1
    print()
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--refaire", action="store_true",
                   help="regénère le certificat serveur (après un changement d'adresse)")
    p.add_argument("--etat", action="store_true", help="ce qui existe, et jusqu'à quand")
    args = p.parse_args()
    if args.etat:
        return etat()

    if AC_CERT.is_file() and AC_CLE.is_file():
        ac_cert, ac_cle = charger_autorite()
        print(f"  Autorité existante : {AC_CERT.name} (conservée)")
    else:
        ac_cert, ac_cle = creer_autorite()
        print(f"  Autorité créée : {AC_CERT.name}")

    # Le profil iOS est écrit même quand tout le reste existe déjà : il a pu être
    # ajouté après coup, ou supprimé par mégarde.
    profil = DOSSIER / "ac-structa.mobileconfig"
    if not profil.is_file():
        try:
            print(f"  Profil iOS écrit : {profil_ios().name}")
        except Exception as e:
            print(f"  (profil iOS non écrit : {e})")

    if SRV_CERT.is_file() and not args.refaire:
        print(f"  Certificat serveur existant : {SRV_CERT.name}")
        print("  (--refaire pour le regénérer, après un changement d'adresse IP)")
        return etat()

    noms, ips = noms_locaux(), adresses_locales()
    creer_certificat_serveur(ac_cert, ac_cle, noms, ips)
    try:
        p = profil_ios()
        print(f"  Profil iOS écrit : {p.name}")
    except Exception as e:
        print(f"  (profil iOS non écrit : {e})")
    print(f"  Certificat serveur créé, valable {JOURS_SERVEUR} jours.")
    print(f"  Noms  : {', '.join(noms)}")
    print(f"  IP    : {', '.join(ips)}")
    print("\n  À FAIRE UNE FOIS SUR CHAQUE TÉLÉPHONE :")
    print(f"  installer {AC_CERT.name} — voir docs/guide-https.md")
    print("  Sans cela, le navigateur affiche un avertissement à chaque ouverture.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
