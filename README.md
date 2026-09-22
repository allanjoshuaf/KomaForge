# KomaForge

KomaForge est un extracteur en ligne de commande pour les publications web :
mangas, bandes dessinées, livres illustrés et documents paginés. Il ouvre une
véritable session Chrome, détecte les pages du lecteur, puis produit exactement le
format choisi : **CBZ, CBR, PDF, EPUB ou images**.

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
- sortie unique choisie par l'utilisateur ;
- CBZ et EPUB construits avec les images originales, sans recompression ;
- PDF créé sans redimensionnement volontaire ;
- CBR véritable lorsque l'outil `rar` est installé ;
- validation du fichier final avant suppression des fichiers de travail.
- reconnaissance des vrais SVGZ, des SVG servis sous une extension `.svgz` et des
  images intégrées sous forme d'URI `data:` ;
- inventaire automatique des balises, classes, textes et filigranes SVG.

## Qualité et intégrité

KomaForge ne convertit pas une image JPEG en PNG ou inversement pour le simple
plaisir d'uniformiser les pages. Chaque ressource conserve son format, sa résolution
et son hash SHA-256. Les archives CBZ et EPUB sont relues après création et chaque
image embarquée est comparée à l'original téléchargé.

Le PDF est produit avec `img2pdf`, qui encapsule les pages sans leur imposer une
taille de papier ni un redimensionnement. Une conversion ne peut toutefois pas
rendre une source meilleure qu'elle ne l'était sur le serveur.

## Prérequis

L'outil reste volontairement léger et n'installe rien tout seul.

1. [Python 3.10 ou plus récent](https://www.python.org/downloads/). Sous Windows,
   cochez **Add Python to PATH** dans l'installeur.
2. Google Chrome. Voici le
   [guide officiel d'installation de Chrome](https://support.google.com/chrome/answer/95346?hl=fr).
3. Une connexion Internet et les droits d'accès normaux au document visé.

Pour créer des PDF, installez l'option `pdf`. Pour créer un CBR, installez
[WinRAR](https://www.rarlab.com/download.htm), qui fournit l'outil `rar`. CBZ ne
demande aucun logiciel supplémentaire.

Les documents SVG exportés en PDF demandent également
[Inkscape](https://inkscape.org/release/), afin de conserver leurs textes et tracés
en vectoriel au lieu de les transformer silencieusement en pixels.

## Installation sous Windows

Ouvrez PowerShell dans le dossier du projet, puis :

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[pdf]"
```

Cette installation ajoute la commande `komaforge`. L'ancien nom de commande
`document-extractor` reste disponible pour compatibilité.

## Utilisation la plus simple

Ouvrez PowerShell dans le dossier, puis lancez le menu :

```powershell
komaforge
```

Choisissez **Extraction automatique**, collez l'URL, puis choisissez un format.
Sous Windows, les résultats sont créés à la racine du disque système :

```text
C:\Extractions\Manga\
└── exemple.com-nom-du-document\
    ├── pages.json
    └── document.cbz
```

Le nom `Ashkel` ou un chemin `C:\Users\...` n'est jamais codé dans le programme.
Le disque système est détecté automatiquement. Sur macOS et Linux, le dossier
`extractions/manga` reste créé près du projet.

## Commande directe

```powershell
komaforge "https://votre-site.com/document" --format cbz
```

Après l'installation, cette forme fonctionne aussi :

```powershell
komaforge "https://votre-site.com/document" --format epub
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
| `--format cbz` | Produit un seul CBZ, choix par défaut |
| `--format cbr` | Produit un vrai CBR si `rar` est disponible |
| `--format pdf` | Produit un PDF sans redimensionnement |
| `--format epub` | Produit un EPUB 3 à mise en pages fixe |
| `--format images` | Conserve les images originales dans un dossier |
| `--watermarks detect` | Détecte et documente les filigranes SVG sans modifier la page |
| `--watermarks remove` | Retire sans question les seuls candidats SVG à confiance élevée |
| `--expected 185` | Impose un nombre exact de pages |
| `--selector "img.page"` | Impose le groupe d'images |
| `--wait-for-user` | Attend une connexion manuelle dans le navigateur |
| `--profile-dir DOSSIER` | Conserve une session dans un profil séparé |
| `--allow-host cdn.exemple.com` | Autorise explicitement un CDN externe vérifié |
| `--pdf` | Ancien alias de `--format pdf` |
| `--chrome CHEMIN` | Utilise un autre emplacement de Chrome |
| `--output DOSSIER` | Remplace le dossier de sortie automatique |

## Détection automatique : limites assumées

L'URL reste l'entrée principale : KomaForge inspecte le lecteur réellement ouvert
au lieu d'imposer une liste de sites qui deviendrait vite obsolète. Des profils de
sites pourront compléter cette détection plus tard, mais ils resteront des aides
facultatives et remplaçables, jamais une condition pour essayer une URL inconnue.

L'outil n'invente pas un nombre de pages. S'il ne trouve aucune preuve fiable, il
affiche `Pages attendues : non déductibles automatiquement`; vous pouvez alors
fournir `--expected` après vérification sur le site.

Il n'autorise pas automatiquement un domaine CDN complètement différent. Vérifiez
ce domaine, puis ajoutez-le explicitement avec `--allow-host`.

N'utilisez `--allow-partial` que si un résultat incomplet est réellement voulu.

### SVG, SVGZ et filigranes

KomaForge vérifie les octets réels d'une ressource plutôt que de croire son
extension. Un fichier `.svgz` réellement compressé est décompressé; un serveur qui
renvoie directement du XML SVG sous cette extension est également accepté.

La détection des filigranes ne repose jamais sur « le dernier texte ». Elle combine
un terme explicite, la rareté de ses classes, une transformation diagonale et sa
largeur. Le mode par défaut `detect` ne modifie rien. Le mode `remove` est réservé
aux documents que vous possédez ou êtes autorisé à transformer; il ne retire que
les candidats à confiance élevée et valide le SVG après traitement.

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

## Licence

KomaForge est distribué sous licence MIT.
