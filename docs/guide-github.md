# Mettre le projet sur GitHub

GitHub donne trois choses : une copie du code **hors de cette machine**, tout
l'historique des commits, et l'exécution automatique des contrôles à chaque
envoi. Il ne donne **pas** de sauvegarde de l'installation — voir la dernière
section.

Une règle non négociable : le dépôt est **privé**.

## Ce qui ne partira pas — vérifié le 7 septembre 2026

Rien de sensible n'est suivi par git, et surtout : **rien de sensible ne l'a
jamais été**. C'est le point important, parce qu'un fichier ajouté au
`.gitignore` après coup reste dans l'historique, et l'historique part avec le
dépôt.

| Fichier | Contient | Suivi | Dans l'historique |
|---|---|---|---|
| `.env` | clé secrète Django, mot de passe PostgreSQL | non | **0 commit** |
| `db.sqlite3` | toutes les données de l'entrepôt | non | **0 commit** |
| `certificats/ac-structa.key` | clé de l'autorité qui signe tous les certificats du parc | non | **0 commit** |
| `logs/` | journaux du serveur | non | 0 commit |
| `cloudflared.exe` | binaire de 54 Mo | non | 0 commit |
| `.env.example` | modèle **sans aucune valeur** | oui | volontaire |

Pour refaire le contrôle vous-même, dans le dossier du projet :

```bash
git log --all --full-history --oneline -- .env db.sqlite3 "*.key" "*.pem"
```

**Aucune ligne** ne doit sortir. Si un jour une ligne sort, ne poussez pas : un
secret présent dans l'historique doit être révoqué, pas seulement retiré.

> `git check-ignore -v .env` répond en nommant la ligne du `.gitignore` qui
> protège le fichier. C'est le contrôle rapide avant un envoi.

## Deux décisions à prendre avant de créer le dépôt

**1. Privé, toujours.** Le code n'expose aucun mot de passe, mais il décrit le
fonctionnement de l'entrepôt, le modèle de comptes et de droits, et la façon
dont le serveur est publié vers l'extérieur. C'est du code d'entreprise : il
n'a rien à faire en public.

**2. Sur quel compte ?** Un dépôt créé sur un compte personnel appartient à ce
compte : il part avec la personne. Pour du code qui fait tourner un entrepôt,
la place normale est une **organisation STRUCTA**, où plusieurs personnes
peuvent avoir accès. Le Livret d'Accueil désigne **Amaury de Maintenant** pour
l'informatique : c'est la personne à qui poser la question du compte et de
l'hébergement du code chez un prestataire externe. Ce guide ne tranche pas à sa
place — il décrit les gestes, une fois la décision prise.

## 1. Créer le dépôt vide sur github.com

1. Se connecter sur <https://github.com> → bouton **+** en haut à droite →
   **New repository**.
2. **Owner** : le compte ou l'organisation retenue au point précédent.
3. **Repository name** : `wms-structa`.
4. **Private** — cocher. Jamais *Public*.
5. **Ne cocher aucune** des cases « Add a README », « Add .gitignore »,
   « Choose a license ».
6. **Create repository**.

> Le point 5 compte. Le projet a déjà son `README.md` et son `.gitignore`. Si
> GitHub crée les siens, le dépôt distant a un commit que vous n'avez pas, et
> le premier envoi est refusé (« Updates were rejected »). Un dépôt vide
> s'envoie sans rien négocier.

La page qui s'affiche ensuite propose « …or push an existing repository from
the command line » et donne l'adresse du dépôt. C'est celle de l'étape 2.

## 2. Relier le dossier du projet au dépôt

Ouvrir un terminal **dans le dossier du projet** : dans l'explorateur Windows,
aller dans `C:\Users\lgabunia\Claude\Projects\WMS Structa\wms-structa`, clic
droit dans le fond de la fenêtre → **Git Bash Here** (ou *Ouvrir dans le
Terminal*).

```bash
git remote add origin https://github.com/VOTRE-COMPTE/wms-structa.git
git remote -v
```

La seconde commande doit afficher deux lignes, `fetch` et `push`, avec
l'adresse. Remplacez `VOTRE-COMPTE` par le compte ou l'organisation ; l'adresse
exacte est celle affichée par GitHub à la fin de l'étape 1.

En cas d'erreur de frappe : `git remote remove origin`, puis recommencer.

## 3. Premier envoi

```bash
git status
```

Doit afficher `nothing to commit, working tree clean` — à part
`docs/Archive/`, un ancien PRO 225 en double qui n'est ni suivi ni ignoré. Deux
choix : l'ignorer (`echo "/docs/Archive/" >> .gitignore`) ou le versionner
(`git add docs/Archive && git commit -m "Archive PRO 225"`). Ne laissez pas la
question ouverte : un `git add -A` distrait l'emporterait sans que vous l'ayez
décidé.

Puis :

```bash
git push -u origin main
```

Une fenêtre de navigateur s'ouvre pour la connexion GitHub — c'est le
*Git Credential Manager*, livré avec Git pour Windows. Il retient
l'autorisation : les envois suivants ne demanderont plus rien. La
double authentification est gérée par cette fenêtre, il n'y a pas de jeton à
fabriquer à la main.

L'envoi transfère plusieurs dizaines de Mo : l'historique contient les PRO 220
à 226 en `.docx` **et** en `.pdf`, plusieurs Mo par version, et chaque version
successive y est. Comptez une à deux minutes.

## 4. Ce qui se passe tout de suite après : les contrôles partent seuls

Le projet contient déjà `.github/workflows/ci.yml`. Dès le premier envoi,
GitHub lance treize étapes sur ses propres machines, en trois minutes environ :

- style et erreurs de code (`ruff`),
- contrôles Django, migrations manquantes, contrôle de déploiement,
- syntaxe et écrans de l'interface (`node --check`, `verifier_interface.js`,
  `tester_interface.js`),
- les 494 tests.

Le résultat s'affiche dans l'onglet **Actions** du dépôt, et une pastille verte
ou rouge apparaît à côté du commit.

> Ce fichier n'avait **jamais tourné** — sans dépôt distant, il n'y avait rien
> pour le déclencher. En le vérifiant étape par étape, une étape échouait :
> le « profil durci » lance `check --deploy --fail-level WARNING`, et Django
> refuse une clé secrète de moins de 50 caractères ; celle du fichier en
> faisait 22. Corrigé le 7 septembre 2026 — la clé de CI ne protège rien,
> aucune donnée réelle ne passe par ces machines. Les treize étapes passent.

Si une étape rougit plus tard, cliquez dessus : GitHub montre la sortie exacte
de la commande. C'est la même commande que vous pouvez relancer chez vous.

## Les envois suivants

Trois commandes, toujours les mêmes :

```bash
git add -- fichier1 fichier2      # ou `git add -A` après avoir lu `git status`
git commit -m "Ce que change ce commit, en une phrase"
git push
```

Une habitude qui paie : **un commit = une intention**. Un commit qui touche
quinze fichiers pour trois raisons différentes ne se relit pas et ne se défait
pas.

## Si ça coince

| Message | Cause | Ce qu'il faut faire |
|---|---|---|
| `Authentication failed` | la fenêtre de connexion a été fermée ou l'autorisation a expiré | relancer `git push` ; la fenêtre revient |
| `Updates were rejected because the remote contains work…` | le dépôt GitHub a été créé **avec** un README | `git pull --rebase origin main` puis `git push`, ou supprimer le dépôt sur GitHub et le recréer vide |
| `remote: warning: File … is 52.00 MB` | un fichier volumineux | avertissement seulement ; GitHub **refuse** au-delà de 100 Mo. Aucun fichier du projet n'en approche |
| `Could not resolve host: github.com` | réseau ou proxy d'entreprise | vérifier l'accès à github.com dans un navigateur ; si un proxy est nécessaire, c'est une question pour l'informatique |
| `fatal: not a git repository` | le terminal n'est pas dans le bon dossier | `cd` dans le dossier du projet, ou refaire le clic droit dedans |
| `index.lock: Permission denied` | un fichier de verrouillage resté en place | `mv .git/index.lock .git/_a_supprimer/` puis recommencer |

Le dossier `.git` pèse 73 Mo alors que son archive compressée n'en fait que 12 :
181 objets traînent en vrac, plus huit fichiers temporaires que git signale à
chaque commande (`warning: garbage found: .git/objects/…/tmp_obj_…`). Sans
conséquence sur le fonctionnement. Pour ranger tout ça d'un coup :

```bash
git gc
```

À lancer **depuis Windows**, pas depuis un terminal distant : la commande a
besoin de supprimer des fichiers, et c'est justement ce qui a laissé ces
résidus.

## Ce que GitHub ne remplace pas

GitHub reçoit **le code**. Il ne reçoit ni `.env`, ni la base de données, ni les
certificats — c'est voulu, et c'est exactement ce qui manque pour remonter
l'installation.

Réinstaller depuis GitHub seul donne une application vide. Il faut en plus :

| Élément | Où il vit | Comment il est sauvegardé |
|---|---|---|
| Base PostgreSQL | serveur | `deploiement\windows\Sauvegarder.ps1` — `pg_dump` nocturne vers `D:\Sauvegardes\WMS`, 30 jours conservés |
| `.env` | racine du projet, sur le serveur | à recopier à la main, hors dépôt |
| `certificats/` | racine du projet | à recopier à la main, hors dépôt |

La procédure complète de remise en service est
`docs/WMS-Structa_PRO212_Mise-en-service-serveur.docx`, doublée par
`docs/guide-deploiement.md`.
