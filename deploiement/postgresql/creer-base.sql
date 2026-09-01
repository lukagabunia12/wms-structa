-- Création de la base WMS Structa sur PostgreSQL.
--
-- À exécuter UNE FOIS, en tant que superutilisateur postgres :
--     psql -U postgres -f creer-base.sql
--
-- Remplacez le mot de passe ci-dessous AVANT de lancer le script, puis reportez
-- la même valeur dans .env (DJANGO_DB_PASSWORD). Ne laissez pas ce fichier avec
-- un vrai mot de passe traîner sur le serveur : il est lisible par tous.

-- Un rôle dédié, qui ne sert qu'au WMS. L'application ne doit jamais se
-- connecter en « postgres » : un défaut applicatif deviendrait alors un pouvoir
-- d'administration sur toutes les bases de la machine.
CREATE ROLE wms WITH LOGIN PASSWORD 'CHANGEZ-CE-MOT-DE-PASSE';

-- Encodage figé en UTF-8 : Django écrit de l'UTF-8, et les codes d'emplacement
-- contiennent des accents (« À RANGER »).
--
-- La collation, en revanche, n'est PAS figée ici. « fr_FR.UTF-8 » n'existe pas
-- sous Windows — qui nomme la même chose « French_France.1252 » — ni sur beaucoup
-- de Linux serveurs installés au minimum, et `CREATE DATABASE` échoue alors en
-- « invalid locale name », au pire moment : celui de la mise en service. Sans ces
-- lignes, la base hérite de la locale du serveur PostgreSQL, ce qui convient : le
-- tri de l'application est fait par Django, et l'encodage — le seul point qui
-- compte pour les accents — reste imposé.
CREATE DATABASE wms
    WITH OWNER = wms
         ENCODING = 'UTF8'
         TEMPLATE = template0;

COMMENT ON DATABASE wms IS 'WMS Structa — cabines, emplacements, mouvements';

\connect wms

-- Le rôle possède le schéma : `migrate` doit pouvoir créer ses tables.
ALTER SCHEMA public OWNER TO wms;

-- Depuis PostgreSQL 15, `public` n'est plus ouvert à tous par défaut ; sans
-- cette ligne, `migrate` échoue en « permission denied for schema public ».
GRANT ALL ON SCHEMA public TO wms;

-- Personne d'autre n'a affaire à cette base.
REVOKE ALL ON DATABASE wms FROM PUBLIC;

\echo ''
\echo 'Base « wms » et rôle « wms » créés.'
\echo 'Reportez maintenant dans .env :'
\echo '    DJANGO_DB_ENGINE=django.db.backends.postgresql'
\echo '    DJANGO_DB_NAME=wms'
\echo '    DJANGO_DB_USER=wms'
\echo '    DJANGO_DB_PASSWORD=<le mot de passe choisi>'
\echo '    DJANGO_DB_HOST=127.0.0.1'
\echo '    DJANGO_DB_PORT=5432'
