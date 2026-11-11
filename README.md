# A3C — Veille du barème URSSAF des petits déplacements

Ce dépôt est **distinct** de `a3c-baremes-batiment-hdf` : il concerne exclusivement la surveillance du plafond d'exonération des indemnités de petits déplacements publié par l'URSSAF, et non les barèmes conventionnels du bâtiment.

## Installation sur GitHub
1. Créer un dépôt **public** sous `duportailphilippe`, nommé `a3c-baremes-urssaf-petits-deplacements`. Cocher **Add a README file** n'est pas nécessaire, car le présent kit en contient déjà un : laisser cette option désactivée.
2. Décompresser cette archive sur votre ordinateur.
3. Depuis l'écran du dépôt vide, cliquer sur **uploading an existing file** ; déposer les fichiers et dossiers contenus *dans* le ZIP (`.github`, `outils`, `donnees`, `README.md`), sans les placer dans un sous-dossier supplémentaire.
4. Vérifier les chemins exacts : `.github/workflows/veille-urssaf.yml`, `outils/controle_urssaf.py` et `donnees/petits-deplacements-urssaf.json`.
5. Valider par **Commit changes** sur `main`.
6. Dans l'onglet **Actions**, sélectionner **Veille URSSAF - petits déplacements** puis **Run workflow** ; vérifier les logs.
7. Activer si besoin les **Issues** dans Settings > General > Features afin de permettre la création des alertes.

## Fonctionnement et limites
- Une exécution est programmée quotidiennement à 06:17 UTC ; GitHub peut en retarder l'exécution.
- Le script compare les données détectées aux données 2026 du JSON et ouvre une **Issue** GitHub en cas de nouvelle année, différence, incohérence ou impossibilité de lire le site URSSAF.
- **Aucun changement de montant n'est publié automatiquement** sans validation humaine ; une alerte n'est pas en elle-même une preuve de hausse du barème.
- Un premier lancement réussi doit être contrôlé avant usage en production : la présentation HTML des sources URSSAF peut évoluer.
- Ce kit ne publie pas encore les données sur GitHub Pages et ne synchronise pas le simulateur HTML local : ce raccordement sera une étape ultérieure.
- Ne déposer dans GitHub **aucun SIRET client, aucune adresse de salarié ou de chantier et aucune donnée personnelle**.

## Origine des données
Source URSSAF déclarée dans le script et dans le JSON. Toujours vérifier la cohérence juridique avant de valider une nouvelle version.
