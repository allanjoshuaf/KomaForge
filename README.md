# Friendly Document Extractor

Un assistant en ligne de commande qui détecte les pages image d'un lecteur web,
active si possible son mode continu et enregistre une copie contrôlée du document.

Utilisez-le uniquement sur un site que vous contrôlez ou que vous êtes autorisé à
archiver. L'outil ne contourne ni connexion, ni contrôle d'accès, ni protection du
site.

## Ce que l'outil automatise

- menu guidé si aucune URL n'est fournie ;
- recherche du mode continu/vertical en français et en anglais ;
- priorité automatique à `#readingmode` avec la valeur `full` si ce couple existe ;
- détection prudente du nombre de pages depuis un manifeste, une balise `meta`, un
  attribut ou un compteur visible comme `Page 1 sur 185` ;
- détection du groupe d'images de pages, même en présence de logos et miniatures ;
- défilement automatique pour les images chargées à la demande ;
- contrôle du domaine des images, de leur format, de leur taille et de leur hash ;
- manifeste final `pages.json` avec le sélecteur et le nombre de pages validés ;
- reprise d'une extraction déjà commencée ;
- création facultative d'un PDF.

## Prérequis

L'outil reste volontairement léger et n'installe rien tout seul.

1. [Python 3.10 ou plus récent](https://www.python.org/downloads/). Sous Windows,
   cochez **Add Python to PATH** dans l'installeur.
2. Google Chrome. Voici le
   [guide officiel d'installation de Chrome](https://support.google.com/chrome/answer/95346?hl=fr).
3. Une connexion Internet et les droits d'accès normaux au document visé.

Documentation officielle :
[installation de Playwright pour Python](https://playwright.dev/python/docs/library).

## Installation sous Windows

Ouvrez PowerShell dans le dossier du projet, puis :

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Cette installation ajoute la commande `document-extractor`. Le programme ouvre le
Chrome déjà installé, exactement comme la version fonctionnelle d'origine.

## Utilisation la plus simple

Double-cliquez sur un terminal dans le dossier, puis lancez le menu :

```powershell
python .\extract.py
```

Choisissez **Extraction automatique**, collez l'URL et laissez les autres champs
vides. Sous Windows, les résultats sont créés dans un dossier clair à la racine du
disque système :

```text
C:\Extractions\Manga\
└── exemple.com-nom-du-document\
    ├── pages.json
    ├── document.pdf
    └── images\
        ├── page-0001.jpg
        └── ...
```

Le nom `Ashkel` ou un chemin `C:\Users\...` n'est jamais codé dans le programme.
Le disque système est détecté automatiquement. Sur macOS et Linux, le dossier
`extractions/manga` reste créé près du projet.

## Commande directe

```powershell
python .\extract.py "https://votre-site.com/document"
```

Après l'installation, cette forme fonctionne aussi :

```powershell
document-extractor "https://votre-site.com/document"
```

Ne copiez pas la syntaxe Markdown d'un lien (`[adresse](adresse)`) dans le terminal :
la commande attend seulement l'adresse entre guillemets.

## Options manuelles de secours

L'automatisation reste surchargeable sans modifier le code :

```powershell
python .\extract.py "https://votre-site.com/document" `
  --selector "img.ts-main-image" `
  --reading-mode-selector "#readingmode" `
  --reading-mode-value "full" `
  --expected 185
```

Une balise copiée depuis les outils de développement est également comprise :

```powershell
--selector '<img class="ts-main-image" ...>'
```

Le format CSS `img.ts-main-image` reste recommandé, car il est plus simple à citer
correctement dans tous les terminaux.

Options utiles :

| Option | Rôle |
|---|---|
| `--expected 185` | Impose un nombre exact de pages |
| `--selector "img.page"` | Impose le groupe d'images |
| `--wait-for-user` | Attend une connexion manuelle dans le navigateur |
| `--profile-dir DOSSIER` | Conserve une session dans un profil séparé |
| `--allow-host cdn.exemple.com` | Autorise explicitement un CDN externe vérifié |
| `--pdf` | Crée aussi `document.pdf` si l'option PDF est installée |
| `--chrome CHEMIN` | Utilise un autre emplacement de Chrome |
| `--output DOSSIER` | Remplace le dossier de sortie automatique |

Pour activer le PDF :

```powershell
python -m pip install -e ".[pdf]"
```

## Détection automatique : limites assumées

L'outil n'invente pas un nombre de pages. S'il ne trouve aucune preuve fiable, il
affiche `Pages attendues : non déductibles automatiquement`; vous pouvez alors
fournir `--expected` après vérification sur le site.

Il n'autorise pas automatiquement un domaine CDN complètement différent. Vérifiez
ce domaine, puis ajoutez-le explicitement avec `--allow-host`.

N'utilisez `--allow-partial` que si un résultat incomplet est réellement voulu.

## Tests avant publication

Tests rapides :

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src")
python -m unittest discover -s tests -v
```

Test navigateur complet sur le faux site inclus :

```powershell
$env:RUN_EXTRACTOR_E2E = "1"
python -m unittest tests.test_detection.EndToEndDetectionTests -v
```

Ce dernier test exige automatiquement les cinq pages, l'activation du mode `full`,
le rejet des logos et la création des fichiers contrôlés.

## Avant de publier sur GitHub

Choisissez la licence qui correspond à votre intention (par exemple MIT si vous
voulez autoriser librement la réutilisation). Aucune licence n'est imposée par ce
projet tant que vous n'avez pas fait ce choix.
