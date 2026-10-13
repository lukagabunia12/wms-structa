"""Les outils du serveur Windows, vérifiables ailleurs que sous Windows.

Le Planificateur de tâches, icacls et netstat n'existent pas ici : on vérifie
ce que les outils leur donnent à manger — le XML des tâches, les lignes de
.env, la lecture de netstat — et les décisions qu'ils prennent avant.
"""
import asyncio
import datetime as dt
import io
import os
import shutil
import ssl
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

OUTILS = Path(__file__).resolve().parents[2] / "outils"
sys.path.insert(0, str(OUTILS))
import basculer_base as BB  # noqa: E402
import certificat_https as C  # noqa: E402
import demarrer_https as D  # noqa: E402
import preparer_copie as PC  # noqa: E402
import preparer_env as PE  # noqa: E402
import proxy_https as P  # noqa: E402
import serveur_wms as W  # noqa: E402

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _args(**surcharges):
    valeurs = dict(heures=["12:30", "22:30"], nettoyage_tous_les=7,
                   nettoyage_jour="dimanche", heure_nettoyage="03:15", jours_journaux=0,
                   compte_sauvegarde=None, sans_service=False)
    valeurs.update(surcharges)
    return SimpleNamespace(**valeurs)


def _xml(texte):
    # Le fichier est écrit en UTF-16 ; ElementTree refuse une déclaration
    # d'encodage sur une chaîne déjà décodée.
    return ET.fromstring(texte.split("?>", 1)[1])


class TachesPlanifieesTest(SimpleTestCase):
    MAINTENANT = dt.datetime(2026, 10, 12, 9, 0)   # un lundi

    def taches(self, **surcharges):
        return {nom: (_xml(xml), compte)
                for nom, xml, compte in W.definitions(_args(**surcharges), self.MAINTENANT)}

    def test_trois_taches_dans_le_dossier_wms_structa(self):
        self.assertEqual(sorted(self.taches()),
                         sorted([r"\WMS Structa\Service", r"\WMS Structa\Sauvegarde",
                                 r"\WMS Structa\Nettoyage"]))

    def test_le_service_n_est_jamais_arrete_par_le_planificateur(self):
        """Par défaut, une tâche est tuée au bout de trois jours, et quand
        Windows croit la machine sur batterie (un onduleur USB)."""
        service, _ = self.taches()[W.TACHE_SERVICE]
        reglages = service.find("t:Settings", NS)
        self.assertEqual(reglages.find("t:ExecutionTimeLimit", NS).text, "PT0S")
        self.assertEqual(reglages.find("t:DisallowStartIfOnBatteries", NS).text, "false")
        self.assertEqual(reglages.find("t:StopIfGoingOnBatteries", NS).text, "false")
        self.assertEqual(reglages.find("t:MultipleInstancesPolicy", NS).text, "IgnoreNew")
        # Priorité normale : la valeur par défaut (7) ralentit aussi le disque.
        self.assertEqual(reglages.find("t:Priority", NS).text, "4")

    def test_le_service_part_au_demarrage_et_se_relance(self):
        service, _ = self.taches()[W.TACHE_SERVICE]
        declencheurs = service.find("t:Triggers", NS)
        self.assertEqual(declencheurs.find("t:BootTrigger/t:Delay", NS).text, "PT1M")
        repetition = declencheurs.find("t:TimeTrigger/t:Repetition", NS)
        self.assertEqual(repetition.find("t:Interval", NS).text, "PT2M")
        # Pas de durée : la répétition ne s'arrête jamais.
        self.assertIsNone(repetition.find("t:Duration", NS))

    def test_sous_le_compte_systeme_sans_mot_de_passe(self):
        for nom, (tache, compte) in self.taches().items():
            with self.subTest(nom=nom):
                self.assertIsNone(compte)
                self.assertEqual(tache.find("t:Principals/t:Principal/t:UserId", NS).text,
                                 "S-1-5-18")

    def test_le_script_est_protege_des_espaces_du_chemin(self):
        service, _ = self.taches()[W.TACHE_SERVICE]
        arguments = service.find("t:Actions/t:Exec/t:Arguments", NS).text
        self.assertTrue(arguments.startswith('/d /c ""'))
        self.assertTrue(arguments.endswith('Demarrer-serveur.bat""'))
        self.assertEqual(service.find("t:Actions/t:Exec/t:WorkingDirectory", NS).text,
                         str(W.RACINE))

    def test_sauvegarde_a_chaque_heure_demandee(self):
        sauvegarde, _ = self.taches()[W.TACHE_SAUVEGARDE]
        debuts = [d.text for d in sauvegarde.findall(
            "t:Triggers/t:CalendarTrigger/t:StartBoundary", NS)]
        self.assertEqual(debuts, ["2026-10-12T12:30:00", "2026-10-12T22:30:00"])
        self.assertEqual(sauvegarde.find("t:Settings/t:ExecutionTimeLimit", NS).text, "PT2H")

    def test_menage_chaque_dimanche(self):
        menage, _ = self.taches()[W.TACHE_NETTOYAGE]
        declencheur = menage.find("t:Triggers/t:CalendarTrigger", NS)
        self.assertEqual(declencheur.find("t:StartBoundary", NS).text, "2026-10-18T03:15:00")
        self.assertIsNotNone(declencheur.find("t:ScheduleByWeek/t:DaysOfWeek/t:Sunday", NS))
        self.assertEqual(declencheur.find("t:ScheduleByWeek/t:WeeksInterval", NS).text, "1")

    def test_menage_tous_les_trois_jours(self):
        menage, _ = self.taches(nettoyage_tous_les=3)[W.TACHE_NETTOYAGE]
        self.assertEqual(menage.find(
            "t:Triggers/t:CalendarTrigger/t:ScheduleByDay/t:DaysInterval", NS).text, "3")

    def test_menage_toutes_les_deux_semaines_le_mercredi(self):
        menage, _ = self.taches(nettoyage_tous_les=14, nettoyage_jour="mercredi")[W.TACHE_NETTOYAGE]
        declencheur = menage.find("t:Triggers/t:CalendarTrigger", NS)
        self.assertIsNotNone(declencheur.find("t:ScheduleByWeek/t:DaysOfWeek/t:Wednesday", NS))
        self.assertEqual(declencheur.find("t:ScheduleByWeek/t:WeeksInterval", NS).text, "2")

    def test_compte_dedie_pour_la_sauvegarde(self):
        taches = self.taches(compte_sauvegarde="STRUCTA\\svc-wms")
        sauvegarde, compte = taches[W.TACHE_SAUVEGARDE]
        self.assertEqual(compte, "STRUCTA\\svc-wms")
        principal = sauvegarde.find("t:Principals/t:Principal", NS)
        self.assertEqual(principal.find("t:UserId", NS).text, "STRUCTA\\svc-wms")
        self.assertEqual(principal.find("t:LogonType", NS).text, "Password")

    def test_le_compte_dedie_recoit_le_projet_les_journaux_et_les_sauvegardes(self):
        """Le projet est réservé aux administrateurs et à SYSTEM, le dossier des
        sauvegardes aussi (créé par la première sauvegarde, sous SYSTEM) : sans
        ces droits, la sauvegarde d'un compte dédié échouait chaque nuit."""
        appels = []

        def executer(commande, timeout=120):
            appels.append(commande)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier) / "wms"
            racine.mkdir()
            sauvegardes = Path(dossier) / "WMS-Sauvegardes"
            sauvegardes.mkdir()
            with mock.patch.object(W, "RACINE", racine), \
                    mock.patch.object(W, "valeur_env", side_effect=lambda cle:
                                      str(sauvegardes) if cle == "WMS_SAUVEGARDE_DOSSIER" else ""), \
                    mock.patch.object(W, "_executer", side_effect=executer):
                self.assertEqual(W.ouvrir_au_compte("STRUCTA\\svc-wms"), [])
            self.assertEqual(appels, [
                ["icacls", str(racine), "/grant", "STRUCTA\\svc-wms:(OI)(CI)RX", "/Q"],
                ["icacls", str(racine / "logs"), "/grant", "STRUCTA\\svc-wms:(OI)(CI)M", "/Q"],
                ["icacls", str(sauvegardes), "/grant", "STRUCTA\\svc-wms:(OI)(CI)M", "/Q"],
            ])

    def test_dossier_des_sauvegardes_cree_pour_le_compte_et_reserve(self):
        appels = []
        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier) / "wms"
            racine.mkdir()
            sauvegardes = Path(dossier) / "D" / "WMS-Sauvegardes"
            with mock.patch.object(W, "RACINE", racine), \
                    mock.patch.object(W, "valeur_env", side_effect=lambda cle:
                                      str(sauvegardes) if cle == "WMS_SAUVEGARDE_DOSSIER" else ""), \
                    mock.patch.object(W, "_executer", side_effect=lambda c, timeout=120:
                                      appels.append(c) or SimpleNamespace(returncode=0)):
                self.assertEqual(W.ouvrir_au_compte("SRV\\wms-sauvegarde"), [])
            self.assertTrue(sauvegardes.is_dir())
        self.assertIn("/inheritance:r", appels[-1])
        self.assertIn("SRV\\wms-sauvegarde:(OI)(CI)F", appels[-1])

    def test_compte_local_et_retour_a_system(self):
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "SRV-WMS"}):
            self.assertEqual(W.normaliser_compte(".\\wms-sauvegarde"), "SRV-WMS\\wms-sauvegarde")
        for systeme in ("SYSTEM", "system", "Système", "", None):
            self.assertIsNone(W.normaliser_compte(systeme))

    def test_les_reglages_de_la_fois_precedente_sont_repris(self):
        """Une réinstallation (mise à jour, -Taches) remettait en silence les
        horaires par défaut et la sauvegarde sous SYSTEM."""
        env = {W.CLE_HEURES: "12:30,18:00,22:30", W.CLE_MENAGE_JOURS: "3",
               W.CLE_COMPTE: "STRUCTA\\svc-wms"}
        args = SimpleNamespace(heures=None, nettoyage_tous_les=None, nettoyage_jour=None,
                               heure_nettoyage=None, compte_sauvegarde=None)
        with mock.patch.object(W, "valeur_env", side_effect=lambda cle: env.get(cle, "")):
            W.reglages_taches(args)
        self.assertEqual(args.heures, ["12:30", "18:00", "22:30"])
        self.assertEqual(args.nettoyage_tous_les, 3)
        self.assertEqual(args.nettoyage_jour, "dimanche")
        self.assertEqual(args.heure_nettoyage, "03:15")
        self.assertEqual(args.compte_sauvegarde, "STRUCTA\\svc-wms")
        # L'option donnée l'emporte ; « SYSTEM » ramène au compte système.
        args = SimpleNamespace(heures=["22:00"], nettoyage_tous_les=None, nettoyage_jour=None,
                               heure_nettoyage=None, compte_sauvegarde="SYSTEM")
        with mock.patch.object(W, "valeur_env", side_effect=lambda cle: env.get(cle, "")):
            W.reglages_taches(args)
        self.assertEqual(args.heures, ["22:00"])
        self.assertIsNone(args.compte_sauvegarde)

    def test_une_tache_qui_n_a_pas_pu_demarrer_est_signalee_tout_de_suite(self):
        avant = {"Etat": "Ready", "Dernier": "2026-10-11T22:30:00", "Resultat": 0}
        self.assertIsNone(W.tache_finie_sans_resultat(dict(avant), avant))
        self.assertIsNone(W.tache_finie_sans_resultat(
            {"Etat": "Running", "Dernier": "2026-10-12T09:00:00", "Resultat": 267009}, avant))
        self.assertIn("mot de passe", W.tache_finie_sans_resultat(
            {"Etat": "Ready", "Dernier": "2026-10-12T09:00:00", "Resultat": 2147943726}, avant))
        self.assertIn("code 1", W.tache_finie_sans_resultat(
            {"Etat": "Ready", "Dernier": "2026-10-12T09:00:00", "Resultat": 1}, avant))

    def test_sans_service_pour_un_poste_de_travail(self):
        self.assertNotIn(W.TACHE_SERVICE, self.taches(sans_service=True))

    def test_heure_illisible_refusee(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            W.main(["taches", "--heures", "25:00"])

    def test_prochaine_occurrence(self):
        self.assertEqual(W._debut(8, 0, self.MAINTENANT), "2026-10-13T08:00:00")
        self.assertEqual(W._debut(9, 30, self.MAINTENANT), "2026-10-12T09:30:00")


class ArretTest(SimpleTestCase):
    NETSTAT = """
Connexions actives

  Proto  Adresse locale         Adresse distante       État
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1012
  TCP    0.0.0.0:8443           0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       4343
  TCP    192.168.0.65:8443      192.168.0.80:50122     ESTABLISHED     4242
  TCP    127.0.0.1:18000        0.0.0.0:0              LISTENING       999
"""

    def test_lecture_de_netstat_sans_dependre_de_la_langue(self):
        sortie = SimpleNamespace(stdout=self.NETSTAT.replace("LISTENING", "ÉCOUTE"))
        with mock.patch.object(W, "_executer", return_value=sortie):
            self.assertEqual(W.processus_a_l_ecoute(8443), {4242})
            self.assertEqual(W.processus_a_l_ecoute(8000), {4343})

    def test_nom_du_programme(self):
        sortie = SimpleNamespace(stdout='"waitress-serve.exe","4343","Services","0","42 512 Ko"\n')
        with mock.patch.object(W, "_executer", return_value=sortie):
            self.assertEqual(W.nom_programme(4343), "waitress-serve.exe")


class ReglagesEnvTest(SimpleTestCase):
    def setUp(self):
        dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        self.env = dossier / ".env"
        self.env.write_text("DJANGO_SECRET_KEY=" + "k" * 60 + "\nDJANGO_DEBUG=False\n",
                            encoding="utf-8")
        patch = mock.patch.multiple(PE, ENV=self.env, EXEMPLE=dossier / ".env.example")
        patch.start()
        self.addCleanup(patch.stop)

    def test_un_partage_reseau_est_ecrit_tel_quel(self):
        """« \\\\nas\\wms » passé à re.sub devenait « \\nas\\wms »."""
        self.assertEqual(PE.poser_reglages({"WMS_SAUVEGARDE_COPIE": r"\\nas\wms"}), [])
        self.assertIn("WMS_SAUVEGARDE_COPIE=\\\\nas\\wms\n", self.env.read_text(encoding="utf-8"))
        from dotenv import dotenv_values
        self.assertEqual(dotenv_values(self.env)["WMS_SAUVEGARDE_COPIE"], r"\\nas\wms")

    def test_remplace_sans_doubler(self):
        PE.poser_reglages({"WMS_NOMS": "wms.structa.fr"})
        PE.poser_reglages({"WMS_NOMS": "wms.structa.fr,wms2.structa.fr"})
        texte = self.env.read_text(encoding="utf-8")
        self.assertEqual(texte.count("WMS_NOMS="), 1)
        self.assertIn("WMS_NOMS=wms.structa.fr,wms2.structa.fr", texte)

    def test_valeur_vide_retire_la_ligne(self):
        PE.poser_reglages({"WMS_SAUVEGARDE_COPIE": "D:\\Copie"})
        PE.poser_reglages({"WMS_SAUVEGARDE_COPIE": ""})
        self.assertNotIn("WMS_SAUVEGARDE_COPIE", self.env.read_text(encoding="utf-8"))

    def test_valeurs_que_dotenv_relirait_de_travers(self):
        for valeur in ("D:\\a #b", " D:\\a", "'D:\\a'", "${HOME}\\x"):
            with self.subTest(valeur=valeur):
                self.assertTrue(PE.poser_reglages({"WMS_SAUVEGARDE_DOSSIER": valeur}))
        self.assertNotIn("WMS_SAUVEGARDE_DOSSIER", self.env.read_text(encoding="utf-8"))

    def test_une_copie_de_env_est_gardee(self):
        PE.poser_reglages({"WMS_NOMS": "wms.structa.fr"})
        self.assertEqual(len(list(self.env.parent.glob(".env.avant-*"))), 1)

    def test_ligne_de_commande(self):
        sortie = io.StringIO()
        with mock.patch("sys.stdout", sortie):
            code = PE.principal(["--poser", "WMS_NOMS=wms.structa.fr"])
        self.assertEqual(code, 0)
        self.assertIn("WMS_NOMS=wms.structa.fr", self.env.read_text(encoding="utf-8"))


class MotDePasseBaseTest(SimpleTestCase):
    def test_accent_refuse_avant_toute_ecriture(self):
        """Un accent passe par psql et .env, mais pas par pg_dump : la sauvegarde
        de la nuit échouerait sur un mot de passe que le WMS accepte."""
        import basculer_base as B
        dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        env = dossier / ".env"
        env.write_text("DJANGO_SECRET_KEY=x\n", encoding="utf-8")
        args = SimpleNamespace(base="wms", utilisateur="wms", mot_de_passe="Entrepôt-2026",
                               hote="127.0.0.1", port="5432")
        with mock.patch.object(B, "ENV", env), self.assertRaises(SystemExit) as e:
            B.vers_postgresql(args)
        self.assertIn("accent", str(e.exception))
        self.assertEqual(env.read_text(encoding="utf-8"), "DJANGO_SECRET_KEY=x\n")


class GardeFousDeBasculeTest(SimpleTestCase):
    """Deux façons de perdre des journées de travail en changeant de base."""

    def setUp(self):
        self.racine = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.racine, ignore_errors=True)
        for patch in (mock.patch.object(BB, "RACINE", self.racine),
                      mock.patch.object(BB, "ENV", self.racine / ".env")):
            patch.start()
            self.addCleanup(patch.stop)
        (self.racine / ".env").write_text("DJANGO_SECRET_KEY=x\n", encoding="utf-8")

    def base(self, lignes):
        import sqlite3
        base = sqlite3.connect(self.racine / "db.sqlite3")
        base.execute("CREATE TABLE wms_cabine (id INTEGER PRIMARY KEY)")
        base.executemany("INSERT INTO wms_cabine DEFAULT VALUES", [()] * lignes)
        base.commit()
        base.close()

    def test_un_poc_sur_sqlite_avec_des_donnees_bloque_l_installation(self):
        """Réinstallé sur PostgreSQL, il repartait de reprise\\ ou d'une base
        vierge : les jours de travail restés dans db.sqlite3 disparaissaient."""
        self.base(3)
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(BB.sqlite_occupee(), 0)

    def test_sqlite_vide_ou_absent_ne_bloque_rien(self):
        self.assertEqual(BB.sqlite_occupee(), 1)
        self.base(0)
        self.assertEqual(BB.sqlite_occupee(), 1)

    def test_deja_sur_postgresql_ne_bloque_rien(self):
        self.base(3)
        (self.racine / ".env").write_text(
            "DJANGO_DB_ENGINE=django.db.backends.postgresql\n", encoding="utf-8")
        self.assertEqual(BB.sqlite_occupee(), 1)

    def test_bascule_refusee_tant_que_le_wms_tourne(self):
        class Prise:
            def __init__(self, *a): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def settimeout(self, _): pass
            def connect_ex(self, adresse): return 0 if adresse[1] == 8443 else 111
        sortie = io.StringIO()
        with mock.patch("socket.socket", Prise), mock.patch("sys.stdout", sortie):
            self.assertEqual(BB.wms_arrete(), 1)
        self.assertIn("8443", sortie.getvalue())


class CopieVersLeServeurTest(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.racine = self.tmp / "wms-structa"
        for chemin, texte in {
            "manage.py": "x", ".env": "secret", "Exemple import.xlsx": "clients",
            "docs/modele.xlsx": "modele", "reprise/donnees.json": "[]",
            "sauvegardes/remise-a-zero_1.json": "[]", "_archive_2026-09-23/vieux.py": "x",
            "certificats/ac-structa.crt": "ac", "certificats/ac-structa.key": "cle ac",
            "certificats/wms.crt": "srv", "certificats/wms.key": "cle srv",
        }.items():
            fichier = self.racine / chemin
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(texte)
        patch = mock.patch.object(PC, "RACINE", self.racine)
        patch.start()
        self.addCleanup(patch.stop)

    def copier(self, **options):
        destination = self.tmp / "copie"
        PC.copier(destination, **options)
        return destination, sorted(p.relative_to(destination).as_posix()
                                   for p in destination.rglob("*") if p.is_file())

    def test_ce_qui_part_et_ce_qui_reste(self):
        destination, fichiers = self.copier()
        self.assertEqual(fichiers, ["docs/modele.xlsx", "manage.py", "reprise/donnees.json"])
        self.assertEqual(PC.controler(destination), [])

    def test_sans_donnees_l_ancien_export_reste_ici(self):
        """Une copie « sans données » (mise à jour du code) emportait le
        reprise/ d'une copie précédente : toute la base d'alors."""
        _, fichiers = self.copier(sans_donnees=True)
        self.assertEqual(fichiers, ["docs/modele.xlsx", "manage.py"])

    def test_avec_l_autorite_les_telephones_n_ont_rien_a_refaire(self):
        destination, fichiers = self.copier(avec_autorite=True)
        self.assertIn("certificats/ac-structa.key", fichiers)
        self.assertIn("certificats/ac-structa.crt", fichiers)
        # Le certificat du serveur, lui, est refait sur place.
        self.assertNotIn("certificats/wms.key", fichiers)
        self.assertEqual(PC.controler(destination, avec_autorite=True), [])
        # Sans l'option, la même copie serait refusée.
        self.assertEqual(PC.controler(destination), ["certificats/ac-structa.key"])

    def test_refus_tant_que_le_wms_tourne(self):
        sortie = io.StringIO()
        with mock.patch.object(PC, "wms_en_marche", return_value=True), \
                mock.patch.object(sys, "argv", ["preparer_copie.py", "--vers",
                                                str(self.tmp / "copie")]), \
                mock.patch("sys.stdout", sortie):
            self.assertEqual(PC.main(), 1)
        self.assertIn("DERNIÈRE écriture", sortie.getvalue())
        self.assertFalse((self.tmp / "copie").exists())

    def test_export_en_echec_aucune_copie_et_l_ancien_export_ne_part_pas(self):
        """Un export raté laissait l'ancien reprise/ partir, et le serveur
        importait des données vieilles de plusieurs semaines."""
        (self.racine / ".venv" / "bin").mkdir(parents=True)
        (self.racine / ".venv" / "bin" / "python").write_text("")
        echec = SimpleNamespace(returncode=1, stdout="", stderr="base injoignable")
        sortie = io.StringIO()
        with mock.patch.object(PC, "wms_en_marche", return_value=False), \
                mock.patch.object(PC.subprocess, "run", return_value=echec), \
                mock.patch.object(sys, "argv", ["preparer_copie.py", "--vers",
                                                str(self.tmp / "copie")]), \
                mock.patch("sys.stdout", sortie):
            self.assertEqual(PC.main(), 1)
        self.assertFalse((self.tmp / "copie").exists())
        self.assertFalse((self.racine / "reprise").exists())


class LanceurTest(SimpleTestCase):
    def test_waitress_croit_le_terminateur_tls(self):
        commande = " ".join(D.OPTIONS_WAITRESS)
        self.assertIn("--trusted-proxy=127.0.0.1", commande)
        self.assertIn("x-forwarded-proto", commande)
        self.assertIn("x-forwarded-for", commande)

    def test_les_hotes_de_env_s_ajoutent_au_lieu_d_etre_remplaces(self):
        valeurs = {"DJANGO_ALLOWED_HOSTS": "wms.exemple.fr", "DJANGO_CSRF_ORIGINS":
                   "https://wms.exemple.fr"}
        with mock.patch.object(C, "valeur_env", side_effect=lambda cle, d="": valeurs.get(cle, d)), \
                mock.patch.object(C, "adresses_locales", return_value=["127.0.0.1", "10.0.0.5"]), \
                mock.patch.object(C, "noms_locaux", return_value=["localhost", "srv"]):
            env = D.preparer_environnement(8443, service=True)
        self.assertEqual(env["DJANGO_ALLOWED_HOSTS"].split(",")[0], "wms.exemple.fr")
        self.assertIn("10.0.0.5", env["DJANGO_ALLOWED_HOSTS"])
        self.assertIn("https://wms.exemple.fr", env["DJANGO_CSRF_ORIGINS"].split(","))
        self.assertIn("https://srv:8443", env["DJANGO_CSRF_ORIGINS"].split(","))
        self.assertEqual(env["DJANGO_LOG_CONSOLE"], "False")

    def test_un_nom_colle_depuis_le_navigateur_est_ramene_a_son_nom(self):
        """« https://wms.structa.fr:8443/ » tapé à la question de l'installation
        serait parti tel quel dans le certificat, où il ne couvre rien."""
        valeur = " https://WMS.structa.fr:8443/ ,wms ,pas un nom, ,srv-wms."
        with mock.patch.object(C, "valeur_env",
                               side_effect=lambda cle, d="": valeur if cle == "WMS_NOMS" else d):
            self.assertEqual(C.noms_publies(), ["srv-wms", "wms", "wms.structa.fr"])

    def test_reinstallation_avec_un_nouveau_nom_refait_le_certificat(self):
        """Une réinstallation avec -Noms gardait l'ancien certificat, qui ne
        couvrait pas le nouveau nom, et l'installation annonçait « certificat
        NON fabriqué ». Il est refait, signé par la même autorité."""
        dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        noms = {"WMS_NOMS": ""}
        chemins = {n: dossier / getattr(C, n).name
                   for n in ("AC_CERT", "AC_CLE", "SRV_CERT", "SRV_CLE")}

        def lancer():
            sortie = io.StringIO()
            with mock.patch.multiple(C, DOSSIER=dossier, **chemins), \
                    mock.patch.object(C, "valeur_env", side_effect=lambda c, d="": noms.get(c, d)), \
                    mock.patch.object(C, "adresses_locales", return_value=["10.0.0.5"]), \
                    mock.patch.object(sys, "argv", ["certificat_https.py", "--si-besoin"]), \
                    mock.patch("sys.stdout", sortie):
                return C.main(), sortie.getvalue()

        self.assertEqual(lancer()[0], 0)
        autorite = chemins["AC_CERT"].read_bytes()
        serveur = chemins["SRV_CERT"].read_bytes()
        # Rien de nouveau : rien n'est refait.
        self.assertEqual(lancer()[0], 0)
        self.assertEqual(chemins["SRV_CERT"].read_bytes(), serveur)
        # Un nom de plus : le certificat serveur est refait, l'autorité reste.
        noms["WMS_NOMS"] = "wms.structa.fr"
        code, sortie = lancer()
        self.assertEqual(code, 0)
        self.assertNotEqual(chemins["SRV_CERT"].read_bytes(), serveur)
        self.assertEqual(chemins["AC_CERT"].read_bytes(), autorite)
        self.assertIn("rien à refaire sur les téléphones", sortie)
        with mock.patch.multiple(C, DOSSIER=dossier, **chemins), \
                mock.patch.object(C, "valeur_env", side_effect=lambda c, d="": noms.get(c, d)), \
                mock.patch.object(C, "adresses_locales", return_value=["10.0.0.5"]):
            self.assertEqual(C.non_couverts(), [])

    def test_l_etoile_reste_l_etoile(self):
        with mock.patch.object(C, "valeur_env",
                               side_effect=lambda cle, d="": "*" if cle == "DJANGO_ALLOWED_HOSTS" else d):
            env = D.preparer_environnement(8443)
        self.assertEqual(env["DJANGO_ALLOWED_HOSTS"], "*")

    def test_un_poste_remplace_ne_relance_pas_l_ancien_wms(self):
        sortie = io.StringIO()
        with mock.patch.object(C, "valeur_env", side_effect=lambda cle, d="":
                               "https://wms.structa.fr:8443" if cle == "WMS_REMPLACE_PAR" else d), \
                mock.patch.object(D, "port_occupe") as port, \
                mock.patch.object(sys, "argv", ["demarrer_https.py"]), \
                mock.patch("sys.stdout", sortie):
            self.assertEqual(D.main(), 2)
        self.assertIn("https://wms.structa.fr:8443", sortie.getvalue())
        port.assert_not_called()

    def test_veille_refait_et_recharge_le_certificat(self):
        recharger = mock.Mock(return_value=True)
        with mock.patch.object(D, "certificat_a_refaire", return_value="fin de validité le 01/11"), \
                mock.patch.object(C, "refaire_certificat_serveur") as refaire, \
                mock.patch("sys.stdout", io.StringIO()):
            self.assertTrue(D.veiller_certificat(recharger))
        refaire.assert_called_once()
        recharger.assert_called_once()

    def test_veille_ne_fait_rien_quand_tout_va_bien(self):
        recharger = mock.Mock()
        with mock.patch.object(D, "certificat_a_refaire", return_value=""), \
                mock.patch.object(C, "non_couverts", return_value=[]), \
                mock.patch.object(C, "refaire_certificat_serveur") as refaire:
            self.assertEqual(D.veiller_certificat(recharger), "")
        refaire.assert_not_called()
        recharger.assert_not_called()

    def test_une_adresse_nouvelle_declenche_le_renouvellement(self):
        with mock.patch.object(D, "certificat_a_refaire", return_value=""), \
                mock.patch.object(C, "non_couverts", return_value=["10.0.0.9"]):
            self.assertIn("10.0.0.9", D.motif_renouvellement())

    def test_l_interpreteur_trouve_ne_tombe_pas_dans_le_parametre_python(self):
        # PowerShell ignore la casse : `$python = ...` ecrirait dans le
        # parametre [string]$Python, l'objet deviendrait du texte et l'etape 1
        # refuserait un Python 3.15 comme "trop ancien" (vu sur SRV-WMS).
        script = (OUTILS.parent / "deploiement" / "windows" / "Installer-WMS.ps1").read_text("ascii")
        self.assertIn("[string]$Python", script)
        self.assertNotRegex(script, r"(?im)^\s*\$python\s*=")


class ProxyTest(SimpleTestCase):
    def test_un_client_qui_disparait_ne_remplit_pas_le_journal(self):
        # WinError 121 vu dans service.log du serveur : un téléphone sorti du
        # Wi-Fi au milieu d'un échange. Bruit, pas une panne.
        boucle = mock.Mock()
        P.silencier_deconnexions(boucle)
        gestionnaire = boucle.set_exception_handler.call_args[0][0]
        for code in (121, 64, 1236, 10054):
            erreur = OSError(code, "deconnexion")
            erreur.winerror = code
            gestionnaire(boucle, {"exception": erreur})
        boucle.default_exception_handler.assert_not_called()
        gestionnaire(boucle, {"exception": ValueError("vraie panne")})
        boucle.default_exception_handler.assert_called_once()

    def test_l_adresse_du_telephone_est_transmise_et_ne_s_invente_pas(self):
        tete = (b"GET /api/moi/ HTTP/1.1\r\nHost: wms.structa.fr:8443\r\n"
                b"X-Forwarded-For: 6.6.6.6\r\nX-Real-IP: 6.6.6.6\r\nForwarded: for=6.6.6.6")
        sortie = P.reecrire_entetes(tete, 8443, "192.168.0.80").decode()
        self.assertNotIn("6.6.6.6", sortie)
        self.assertIn("X-Forwarded-For: 192.168.0.80\r\n", sortie)
        self.assertIn("X-Forwarded-Proto: https\r\n", sortie)
        self.assertIn("Host: wms.structa.fr:8443\r\n", sortie)

    def _session(self, envoi, inactivite=0.5):
        """Un client parle au proxy, qui relaie vers une fausse application.
        Rend ce que l'application a reçu, et si le client a été déconnecté."""
        async def scenario():
            recu = bytearray()

            async def appli(lecteur, ecrivain):
                try:
                    while True:
                        bloc = await lecteur.read(65536)
                        if not bloc:
                            break
                        recu.extend(bloc)
                finally:
                    ecrivain.close()

            serveur_appli = await asyncio.start_server(appli, "127.0.0.1", 0)
            port_appli = serveur_appli.sockets[0].getsockname()[1]
            serveur_proxy = await asyncio.start_server(
                lambda lec, ecr: P.servir_client(lec, ecr, ("127.0.0.1", port_appli), 8443),
                "127.0.0.1", 0)
            port_proxy = serveur_proxy.sockets[0].getsockname()[1]
            lecteur, ecrivain = await asyncio.open_connection("127.0.0.1", port_proxy)
            ecrivain.write(envoi)
            await ecrivain.drain()
            try:
                ferme = await asyncio.wait_for(lecteur.read(), inactivite * 6) == b""
            except asyncio.TimeoutError:
                ferme = False
            ecrivain.close()
            serveur_proxy.close()
            serveur_appli.close()
            return bytes(recu), ferme

        with mock.patch.object(P, "DELAI_INACTIVITE", 0.5):
            return asyncio.run(scenario())

    def test_une_connexion_muette_est_fermee(self):
        recu, ferme = self._session(b"")
        self.assertTrue(ferme)
        self.assertEqual(recu, b"")

    def test_une_taille_de_morceau_illisible_ferme_la_connexion(self):
        recu, ferme = self._session(
            b"POST /api/x/ HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"zz\r\nabc\r\n0\r\n\r\n")
        self.assertTrue(ferme)
        # Rien après l'entête et la ligne illisible n'a été relayé comme une
        # requête suivante.
        self.assertNotIn(b"abc\r\n0", recu)

    def test_morceaux_avec_lignes_de_fin(self):
        recu, _ = self._session(
            b"POST /a HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"3\r\nabc\r\n0\r\nX-Fin: 1\r\n\r\n"
            b"GET /b HTTP/1.1\r\nHost: a\r\n\r\n")
        # La seconde requête est reconnue comme telle : elle reçoit ses entêtes.
        self.assertEqual(recu.count(b"X-Forwarded-Proto: https"), 2)

    def test_rechargement_du_certificat(self):
        self.assertFalse(P.recharger_certificat() if P.CONTEXTE is None else False)
        contexte = mock.Mock(spec=ssl.SSLContext)
        with mock.patch.object(P, "CONTEXTE", contexte):
            self.assertTrue(P.recharger_certificat())
        contexte.load_cert_chain.assert_called_once_with(str(P.CERT), str(P.CLE))


class CertificatTest(SimpleTestCase):
    def test_valeur_lue_dans_env_comme_le_lit_django(self):
        dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        (dossier / ".env").write_text('WMS_NOMS="wms.structa.fr" # le nom public\n',
                                      encoding="utf-8")
        with mock.patch.object(C, "RACINE", dossier), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WMS_NOMS", None)
            self.assertEqual(C.noms_publies(), ["wms.structa.fr"])
