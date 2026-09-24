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
- distinction automatique entre une œuvre, un chapitre et un document paginé ;
- découverte prudente des chapitres d'une œuvre et création d'un fichier par chapitre ;
- reconnaissance des menus cohérents de volumes, tomes ou chapitres ;
- sélection facultative des parties avec une expression comme `1-5,8` ;
- inspection préalable sans téléchargement avec `--inspect` ;
- attente des lecteurs qui annoncent encore leur initialisation ;
- exploration des lecteurs PDF/canvas, y compris leurs Shadow DOM et iframes ;
- récupération du vrai PDF ou EPUB chargé par le navigateur ;
- choix du format conservé dans le menu simple, avec le format source recommandé ;
- refus des logos et captures basse qualité lorsque le lecteur n'expose aucun document ;
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
- validation du fichier final avant suppression des fichiers de travail ;
- reconnaissance des vrais SVGZ, des SVG servis sous une extension `.svgz` et des
  images intégrées sous forme d'URI `data:` ;
- inventaire automatique des balises, classes, textes et filigranes SVG.

## Qualité et intégrité

KomaForge ne convertit pas une image JPEG en PNG ou inversement pour le simple
plaisir d'uniformiser les pages. Chaque ressource conserve son format, sa résolution
et son hash SHA-256. Les archives CBZ et EPUB sont relues après création et chaque
image embarquée est comparée à l'original téléchargé.

Lorsque les pages sont des images, le PDF est produit avec `img2pdf`, qui les
encapsule sans leur imposer une taille de papier ni un redimensionnement. Lorsqu'un
lecteur canvas charge déjà un vrai PDF, KomaForge valide sa structure avec `pikepdf`
et conserve directement ses octets, sans rasterisation ni réencodage. Une conversion
ne peut toutefois pas rendre une source meilleure qu'elle ne l'était sur le serveur.

Lorsqu'un lecteur fournit un EPUB redistribuable, KomaForge valide son conteneur,
son paquet OPF et l'ordre réel de sa spine. Le choix `original` conserve exactement
ses octets. Un choix PDF imprime les sections XHTML avec Chrome; CBZ, CBR, EPUB fixe
et images demandent ensuite un rendu PNG à 200 ppp, annoncé explicitement dans le
terminal et le manifeste.

La validité du ZIP ne suffit pas à prouver que l'EPUB couvre toute la publication.
KomaForge compare aussi les documents présents aux liens de sa propre table des
matières. Si celle-ci nomme des chapitres physiquement absents, le résultat devient
`incomplete`, les chemins manquants sont consignés et aucun faux fichier « complet »
n'est sauvegardé. Les entrées ZIP locales détachées et les octets placés après la fin
du conteneur sont également inventoriés pour permettre une analyse plus profonde.

Un PDF valide n'est pas automatiquement une publication complète. KomaForge compare
aussi ses pages aux compteurs fiables trouvés dans les métadonnées réseau. Si le
lecteur annonce davantage de pages, le manifeste porte le statut `incomplete`, la
commande retourne un code d'échec et aucun PDF incomplet n'est sauvegardé.

## Prérequis

L'outil reste volontairement léger et n'installe rien tout seul.

1. [Python 3.10 ou plus récent](https://www.python.org/downloads/). Sous Windows,
   cochez **Add Python to PATH** dans l'installeur.
2. Google Chrome. Voici le
   [guide officiel d'installation de Chrome](https://support.google.com/chrome/answer/95346?hl=fr).
3. Une connexion Internet et les droits d'accès normaux au document visé.

Pour créer des PDF et convertir un document source vers des pages, installez les
options `pdf` et `conversion`. Pour créer un CBR, installez
[WinRAR](https://www.rarlab.com/download.htm), qui fournit l'outil `rar`. CBZ ne
demande aucun logiciel supplémentaire.

Les documents SVG exportés en PDF sont rendus avec Google Chrome, comme dans le
lecteur web. Inkscape n'est pas utilisé, car son moteur peut déplacer les textes et
les polices intégrées de certaines publications.

## Installation sous Windows

Ouvrez PowerShell dans le dossier du projet, puis :

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[pdf,conversion]"
```

Cette installation ajoute la commande `komaforge`. L'ancien nom de commande
`document-extractor` reste disponible pour compatibilité.

## Utilisation la plus simple

Ouvrez PowerShell dans le dossier, puis lancez le menu :

```powershell
komaforge
```

Choisissez **Extraction automatique**, collez l'URL, puis choisissez le format.
Le choix recommandé **Original** conserve un PDF en PDF, un EPUB en EPUB et regroupe
des pages image en CBZ. Les mêmes formats restent disponibles sans entrer dans les
options avancées; celles-ci servent aux sélecteurs, compteurs et réglages du lecteur.
Si l'URL contient plusieurs volumes ou chapitres, le menu affiche les parties
détectées et demande lesquelles prendre. Le choix par défaut est seulement la
première partie; saisissez `all` pour tout extraire.
Sous Windows, les résultats sont créés à la racine du disque système :

```text
C:\Extractions\Manga\
└── exemple.com-nom-du-document\
    ├── pages.json
    └── document.cbz
```

Avec l'URL d'une œuvre contenant plusieurs chapitres :

```text
C:\Extractions\Manga\
└── exemple.com-nom-de-loeuvre\
    ├── publication.json
    └── chapters\
        ├── 001-Chapitre-1.cbz
        ├── 002-Chapitre-2.cbz
        └── 003-Chapitre-3.cbz
```

Lorsqu'un lecteur expose des volumes plutôt que des chapitres, ils restent nommés
comme tels :

```text
C:\Extractions\Manga\exemple.com-nom-de-loeuvre\
├── publication.json
└── volumes\
    ├── 001-Volume-1.cbz
    └── 002-Volume-2.cbz
```

Aucun nom d'utilisateur ni chemin de profil Windows n'est codé dans le programme.
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

Pour analyser d'abord une URL sans enregistrer les pages :

```powershell
komaforge "https://votre-site.com/oeuvre" --inspect
```

Pour ne prendre qu'une partie des chapitres ou volumes détectés :

```powershell
komaforge "https://votre-site.com/oeuvre" --chapters "1-5,8" --format cbz
```

L'adresse simple entre guillemets reste recommandée. Si un lien Markdown complet
(`adresse` affichée et cible identique) est collé par erreur, KomaForge en extrait
maintenant l'URL; une cible différente du texte affiché est refusée.

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
| `--format original` | Conserve le document PDF/EPUB natif, ou crée un CBZ depuis les pages image |
| `--format cbz` | Produit un seul CBZ, choix par défaut |
| `--format cbr` | Produit un vrai CBR si `rar` est disponible |
| `--format pdf` | Conserve le PDF chargé par le lecteur ou en produit un sans redimensionnement |
| `--format epub` | Produit un EPUB 3 à mise en pages fixe |
| `--format images` | Conserve les images originales dans un dossier |
| `--inspect` | Détecte l'œuvre, ses chapitres et ses pages sans téléchargement |
| `--chapters "1-5,8"` | Sélectionne des chapitres ou volumes par leur position détectée |
| `--scope document` | Force le traitement de l'URL comme un seul document ou chapitre |
| `--scope work` | Force la recherche d'une liste de chapitres |
| `--recover-detached-pdf` | Réassemble un arbre PDF détaché vérifié pour un document possédé ou testé avec autorisation |
| `--watermarks remove` | Retire par défaut les textes exacts de filigrane connus |
| `--watermarks detect` | Détecte et documente sans modifier la page |
| `--watermark-text "SPECIMEN"` | Retire exactement ce texte; option répétable |
| `--expected 185` | Impose un nombre exact de pages |
| `--selector "img.page"` | Impose le groupe d'images |
| `--wait-for-user` | Attend une connexion manuelle dans le navigateur |
| `--profile-dir DOSSIER` | Conserve une session dans un profil séparé |
| `--allow-host cdn.exemple.com` | Autorise explicitement un CDN externe vérifié |
| `--workers 6` | Télécharge de 1 à 12 images en parallèle (6 par défaut) |
| `--pdf` | Ancien alias de `--format pdf` |
| `--chrome CHEMIN` | Utilise un autre emplacement de Chrome |
| `--output DOSSIER` | Remplace le dossier de sortie automatique |

## Détection automatique : limites assumées

L'URL reste l'entrée principale : KomaForge inspecte le lecteur réellement ouvert
au lieu d'imposer une liste de sites qui deviendrait vite obsolète. Des profils de
sites pourront compléter cette détection plus tard, mais ils resteront des aides
facultatives et remplaçables, jamais une condition pour essayer une URL inconnue.

En mode automatique, une liste d'au moins trois liens cohérents et numérotés, ou un
menu contenant au moins deux volumes, tomes ou chapitres cohérents, est nécessaire
pour reconnaître une œuvre. Une URL qui ressemble déjà à un chapitre reste traitée
comme un seul chapitre, même si le lecteur affiche une navigation vers les autres.
`--scope work` et `--scope document` permettent de corriger explicitement une
classification inhabituelle.

Le nombre rapporté correspond aux ressources d'images fournies par le lecteur. Une
image très verticale peut regrouper plusieurs pages imprimées : KomaForge la conserve
alors intacte et ne prétend pas connaître le nombre de pages papier.

L'outil n'invente pas un nombre de pages. S'il ne trouve aucune preuve fiable, il
affiche `Pages attendues : non déductibles automatiquement`; vous pouvez alors
fournir `--expected` après vérification sur le site.

Un domaine HTTPS externe peut être autorisé automatiquement seulement lorsqu'il
fournit plusieurs ressources et représente une part significative du groupe de
pages déjà sélectionné. Un logo, une publicité isolée ou une redirection vers un
autre domaine ne suffit jamais. `--allow-host` reste disponible pour autoriser
explicitement un CDN vérifié qui ne satisfait pas cette règle prudente.

Les pages promotionnelles et séparateurs qui appartiennent réellement à la même
séquence numérotée que le document sont conservés en mode original. KomaForge ne
devine pas qu'une page voulue par l'éditeur doit être supprimée. En revanche, les
vignettes de recommandations et autres images hors de la famille de ressources du
document sont écartées de la sélection automatique.

Les images sont téléchargées avec six connexions simultanées par défaut, puis remises
dans leur ordre documentaire avant la création du manifeste et de l'archive. Si un
serveur refuse le téléchargement direct parallèle, KomaForge retente les seules
ressources concernées dans la session Chrome active.

Les lignes `[OK]` peuvent apparaître dans un ordre différent avec plusieurs connexions :
elles indiquent l'ordre d'arrivée réseau, pas l'ordre du livre. Avant chaque export,
les résultats sont triés par numéro de page. Une page déjà présente n'est désormais
réutilisée que si son URL source, son nom et son empreinte SHA-256 correspondent aux
données de reprise; un ancien placeholder portant le même numéro est retéléchargé.

Pour un PDF construit depuis des images, l'échelle physique est fixée à 96 ppp afin
d'ignorer les métadonnées DPI aberrantes de certains bandeaux très bas. Les dimensions
en pixels, les proportions et l'ordre des images restent inchangés : aucun
rééchantillonnage n'est effectué pour cette mise en pages.

Certains lecteurs PDF dessinent leurs pages dans des balises `canvas`. KomaForge
inspecte aussi les Shadow DOM, les iframes et les réponses réseau. Si le navigateur
charge une ressource `application/pdf`, `--format pdf` la rejoue dans la même session,
la valide et compte ses pages. Avant d'annoncer un succès, il attend également les
métadonnées tardives comme `pageCount`, `totalPages` ou `numberOfPages`. Un écart tel
que `39/393` est refusé et jamais déclaré complet. Si aucun
document ni groupe d'images fiable n'est trouvé, l'extraction s'arrête au lieu de
transformer les logos du lecteur ou des captures d'écran de faible résolution en faux
document.

Les numéros imprimés et le nombre de pages internes peuvent différer. Par exemple,
un lecteur peut afficher 374 pages numérotées alors que ses métadonnées comptent 393
pages avec les couvertures et les pages liminaires. KomaForge conserve ces deux
indications séparément au lieu de présenter l'une comme un nombre de pages accessibles.

KomaForge reconnaît également le cas particulier d'un PDF contenant une seconde
arborescence `/Pages` détachée. Il vérifie si les pages visibles forment exactement
le préfixe ordonné de cet arbre, puis consigne le nombre d'objets de continuation
avec contenu et ressources. Par défaut, cette analyse reste un diagnostic et aucun
PDF incomplet n'est conservé. Pour un document que vous possédez ou êtes autorisé à
tester, `--recover-detached-pdf` réassemble un unique arbre uniquement lorsque son
nombre déclaré et résolu correspond aux métadonnées attendues, que tout le préfixe
visible correspond et que chaque page de continuation possède contenu et ressources.
Le résultat est ensuite rouvert et recompté avant d'être accepté.
Dans le menu interactif, cette autorisation est demandée au moment de la détection,
et seulement après que toutes ces vérifications ont réussi. Une commande directe
reste non interactive et exige explicitement `--recover-detached-pdf`.
Les gros PDF qui annoncent la prise en charge des plages d'octets sont téléchargés
par segments vérifiés. Cela évite qu'une connexion lente oblige à recommencer tout
le fichier après l'expiration d'une unique requête volumineuse.

### SVG, SVGZ et filigranes

KomaForge vérifie les octets réels d'une ressource plutôt que de croire son
extension. Un fichier `.svgz` réellement compressé est décompressé; un serveur qui
renvoie directement du XML SVG sous cette extension est également accepté.

La détection des filigranes ne repose jamais sur « le dernier texte ». Le mode par
défaut `remove` reprend le comportement fiable du script d'origine : il retire un
élément `<text>` seulement lorsque son contenu correspond exactement à un terme
connu comme `SPECIMEN`. `--watermark-text` permet d'ajouter librement un texte exact.
Le mode `detect` conserve tout. Le retrait reste réservé aux documents que vous
possédez ou êtes autorisé à transformer, et le SVG est validé après traitement.

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

Ce dernier test vérifie notamment le mode `full`, le rejet des logos, les SVGZ, la
création d'un document simple et l'extraction d'une œuvre en plusieurs CBZ de
chapitres avec sélection partielle.

## Licence

KomaForge est distribué sous licence MIT.
