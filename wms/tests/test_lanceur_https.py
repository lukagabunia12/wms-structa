"""Le lanceur HTTPS (`outils/demarrer_https.py`), dernière étape de `Demarrer-WMS.bat`.

On ne démarre pas de serveur ici : on vérifie les décisions que le lanceur prend
AVANT, et qui ont chacune coûté une matinée quand elles manquaient — un second
lancement qui se battait avec le premier pour le port, un ancien lanceur resté
ouvert qui tenait le port 8000, un certificat expiré découvert par tous les
téléphones le même jour.
"""
import contextlib
import datetime as dt
import io
import socket
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

OUTILS = Path(__file__).resolve().parents[2] / "outils"
sys.path.insert(0, str(OUTILS))
import demarrer_https as D  # noqa: E402


def _port_qui_ecoute():
    """Une socket qui écoute sur un port libre de la boucle locale."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s, s.getsockname()[1]


def _port_libre():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _lancer(*arguments):
    """`main()` avec ces arguments ; rend (code de sortie, ce qui a été affiché)."""
    sortie = io.StringIO()
    with mock.patch.object(sys, "argv", ["demarrer_https.py", "--sans-navigateur", *arguments]), \
            contextlib.redirect_stdout(sortie):
        code = D.main()
    return code, sortie.getvalue()


class DejaDemarreTest(SimpleTestCase):
    def test_un_port_qui_ecoute_est_vu(self):
        s, port = _port_qui_ecoute()
        try:
            self.assertTrue(D.port_occupe(port))
        finally:
            s.close()
        self.assertFalse(D.port_occupe(port))

    def test_second_lancement_ne_demarre_rien(self):
        """Le WMS tourne déjà : on le dit et on s'arrête, code 0 — rien n'est créé."""
        s, port = _port_qui_ecoute()
        try:
            with mock.patch.object(D, "certificat_a_refaire") as certificat:
                code, texte = _lancer("--port", str(port), "--port-appli", str(_port_libre()))
        finally:
            s.close()
        self.assertEqual(code, 0)
        self.assertIn("tourne déjà", texte)
        certificat.assert_not_called()

    def test_port_de_l_application_pris_par_un_ancien_lanceur(self):
        """Port 8000 tenu par l'ancien Demarrer-WMS.bat : la cause est nommée, code 1."""
        s, port_appli = _port_qui_ecoute()
        try:
            code, texte = _lancer("--port", str(_port_libre()), "--port-appli", str(port_appli))
        finally:
            s.close()
        self.assertEqual(code, 1)
        self.assertIn("déjà pris", texte)
        self.assertIn("ancien Demarrer-WMS.bat", texte)


class RenouvellementTest(SimpleTestCase):
    """Le certificat serveur est refait un mois avant sa fin, sans rien demander."""

    def setUp(self):
        dossier = Path(tempfile.mkdtemp())
        self.cert, self.cle = dossier / "wms.crt", dossier / "wms.key"
        patch = mock.patch.multiple(D.C, SRV_CERT=self.cert, SRV_CLE=self.cle)
        patch.start()
        self.addCleanup(patch.stop)

    def _ecrire(self, jours_restants):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        cle = ec.generate_private_key(ec.SECP256R1())
        nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "essai")])
        maintenant = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(nom).issuer_name(nom)
                .public_key(cle.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(maintenant - dt.timedelta(days=400))
                .not_valid_after(maintenant + dt.timedelta(days=jours_restants))
                .sign(cle, hashes.SHA256()))
        self.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self.cle.write_bytes(cle.private_bytes(serialization.Encoding.PEM,
                                               serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))

    def test_absent(self):
        self.assertEqual(D.certificat_a_refaire(), "absent")

    def test_valide_longtemps_rien_a_faire(self):
        self._ecrire(200)
        self.assertEqual(D.certificat_a_refaire(), "")

    def test_moins_d_un_mois_a_refaire(self):
        self._ecrire(10)
        self.assertTrue(D.certificat_a_refaire().startswith("fin de validité le "))

    def test_deja_expire_a_refaire(self):
        self._ecrire(-3)
        self.assertTrue(D.certificat_a_refaire().startswith("fin de validité le "))

    def test_illisible_a_refaire(self):
        self.cert.write_text("pas un certificat")
        self.cle.write_text("pas une clé")
        self.assertEqual(D.certificat_a_refaire(), "illisible")
