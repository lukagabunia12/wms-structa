-- Contrôle rapide : le compte applicatif voit-il ce qu'il doit voir, et rien de plus ?
--     psql -U wms -d wms -h 127.0.0.1 -f verifier-acces.sql
\echo '--- identité ---'
SELECT current_user AS utilisateur, current_database() AS base, version();
\echo '--- droits sur le schéma ---'
SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS peut_creer_des_tables;
\echo '--- tables du WMS ---'
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
\echo '--- comptages ---'
SELECT 'emplacements' AS table, count(*) FROM wms_emplacement
UNION ALL SELECT 'cabines', count(*) FROM wms_cabine
UNION ALL SELECT 'mouvements de cabine', count(*) FROM wms_mouvementcabine
UNION ALL SELECT 'utilisateurs', count(*) FROM wms_utilisateur;
