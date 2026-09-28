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
- interface guidée en français, anglais, russe et chinois ;
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
- CBZ construit avec les images originales lorsqu'elles sont déjà compatibles ;
- pages SVG rendues en PNG à leur taille native pour les lecteurs CBZ/CBR ;
- EPUB construit avec les ressources originales, y compris les SVG ;
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

Une exception volontaire concerne les pages SVG dans un CBZ ou un CBR : beaucoup
de lecteurs de bandes dessinées refusent ce format dans une archive pourtant valide.
KomaForge les rend donc en PNG sans compression destructive, exactement aux
dimensions de leur `viewBox` (par exemple `1200 x 1600`), puis vérifie toutes les
pages. Les formats Images et EPUB continuent de conserver les SVG eux-mêmes.

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

Les documents SVG exportés en PDF sont rendus avec une seule session Google Chrome
pour tout l'ouvrage, comme dans le lecteur web. Inkscape n'est pas utilisé, car son
moteur peut déplacer les textes et les polices intégrées de certaines publications.

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
Le premier écran permet de choisir **Français**, **English**, **Русский** ou
**中文**. Pour une commande directe, utilisez par exemple `--language en`,
`--language ru` ou `--language zh`.
Le choix recommandé **Original** conserve un PDF en PDF, un EPUB en EPUB et regroupe
des pages image en CBZ. Les mêmes formats restent disponibles sans entrer dans les
options avancées; celles-ci servent aux sélecteurs, compteurs et réglages du lecteur.
Si l'URL contient plusieurs volumes ou chapitres, le menu affiche les parties
détectées et demande lesquelles prendre. Le choix par défaut est seulement la
première partie; saisissez `all` pour tout extraire.
Sous Windows, les résultats sont créés à la racine du disque système :

```text
C:\Extractions\Manga\
└── Titre-du-livre-Chapter-1\
    ├── pages.json
    └── Titre-du-livre-Chapter-1.cbz
```

Le titre fourni par le lecteur ou ses métadonnées est préféré aux identifiants
techniques de l'URL. Si un dossier homonyme appartient déjà à une autre source,
KomaForge crée automatiquement un suffixe (`-2`, `-3`, etc.) au lieu d'écraser
l'ouvrage existant. Une relance de la même source peut en revanche reprendre son
propre dossier.

Avec l'URL d'une œuvre contenant plusieurs chapitres :

```text
C:\Extractions\Manga\
└── Titre-de-loeuvre\
    ├── publication.json
    └── chapters\
        ├── 001-Chapitre-1.cbz
        ├── 002-Chapitre-2.cbz
        └── 003-Chapitre-3.cbz
```

Lorsqu'un lecteur expose des volumes plutôt que des chapitres, ils restent nommés
comme tels :

```text
C:\Extractions\Manga\Titre-de-loeuvre\
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

# Interface anglaise
komaforge "https://votre-site.com/document" --inspect --language en
```

Après l'installation, cette forme fonctionne aussi :

```powershell
komaforge "https://votre-site.com/document" --format epub
```

Sans URL, le menu interactif ouvert par KomaForge réunit désormais l’extraction
guidée, les options avancées, le catalogue des sources, la bibliothèque locale et
la file d’attente. Les commandes détaillées ci-dessous restent disponibles pour
les scripts et l’automatisation.

## Bibliothèque locale

KomaForge construit automatiquement un index SQLite à partir des manifestes déjà
présents lorsqu’il manque. Chaque extraction réussie actualise ensuite cet index.
Les manifestes restent la source de vérité : l’index peut être supprimé et recréé à
tout moment, sans modifier les livres ni les archives.

```powershell
komaforge library rebuild
komaforge library add "https://votre-site.com/oeuvre" --format original
komaforge library list
komaforge library search "titre"
komaforge library publications --json
komaforge library downloaded
komaforge library continue
komaforge library read IDENTIFIANT_PUBLICATION
komaforge library open IDENTIFIANT_PUBLICATION
komaforge library status
komaforge library track IDENTIFIANT_PUBLICATION
komaforge library tracked
komaforge library categories
komaforge library category-add "À lire" IDENTIFIANT_PUBLICATION
komaforge library category-members "À lire"
komaforge library category-remove "À lire" IDENTIFIANT_PUBLICATION
komaforge library category-delete "À lire"
komaforge library unread
komaforge library unread --publication-id IDENTIFIANT_PUBLICATION
komaforge library mark-read IDENTIFIANT_PUBLICATION
komaforge library mark-unread IDENTIFIANT_PUBLICATION
komaforge library update
komaforge library update --publication-id IDENTIFIANT_PUBLICATION
komaforge library sync
komaforge library sync --publication-id IDENTIFIANT_PUBLICATION --limit 100
komaforge library updates
komaforge library updates-seen
komaforge library history
komaforge library progress IDENTIFIANT_PUBLICATION IDENTIFIANT_PARTIE 12
```

Par défaut, la commande lit `C:\Extractions\Manga` sous Windows et place l’index
dans `C:\Extractions\Manga\.komaforge\library.sqlite`. `--root` permet de choisir
une autre bibliothèque et `--index` un autre fichier SQLite. L’option `--json`
fournit une sortie stable pour une future interface ou un autre outil local.
Le tableau `library status` réunit dans ce même format stable la santé de l’index,
les téléchargements disponibles, les publications suivies, les catégories, les
parties non lues, l’historique et le nombre de travaux dans chaque état de la file.

Lorsqu’une même source possède plusieurs anciens manifestes, la reconstruction
garde une seule publication canonique. Elle privilégie d’abord la couverture
explicitement prouvée, puis son état, l’intégrité vérifiable de son artefact et sa
date. Les anciennes URL de lecteur eBooks sont rapprochées des fiches produit par
leur identifiant de livre, ce qui empêche un ancien aperçu déclaré complet de
masquer un diagnostic plus récent comme `11/62`. Les URL de
ressources portant des jetons temporaires ne sont pas copiées dans l’index.
Le suivi et la progression sont conservés séparément dans
`.komaforge/state.sqlite`; reconstruire `library.sqlite` ne les efface pas. Les
identifiants de publication nécessaires au suivi sont disponibles avec
`komaforge library publications --json`. La commande `library add` réunit
l’extraction, l’indexation et le suivi dans une seule opération ; elle ne suit rien
si l’extraction est refusée ou incomplète. La vue `unread` liste chaque partie non
terminée et sa dernière position enregistrée, globalement ou pour une publication.
`mark-read` et `mark-unread` appliquent le statut à toute une publication ;
`--part-id` permet de viser seulement une partie. Remettre en non-lu efface la
progression concernée sans retirer la publication du suivi.
`library update` ajoute une vérification pour chaque publication suivie sans créer de
doublon lorsqu’une vérification identique est déjà en attente ou en cours.
`library sync` effectue ce même travail puis exécute, dans une limite explicite, les
vérifications et téléchargements de mise à jour. Les inspections indépendantes déjà
présentes dans la file ne sont pas consommées par cette synchronisation. Sa sortie
JSON sépare vérifications, téléchargements, nouveautés, échecs et travaux restants.
Lorsqu’une vérification découvre de nouvelles parties, `library updates` les liste
séparément du statut de lecture. `library updates-seen` les marque comme consultées
sans les marquer comme lues et sans supprimer les téléchargements planifiés.
`downloaded` ne retient que les artefacts encore présents et `history` résout la
progression persistante vers les titres de publication et de partie actuels.
Les catégories servent à organiser une même publication suivie dans plusieurs
listes locales, par exemple `À lire`, `En cours` ou `Favoris`. Elles sont conservées
dans `state.sqlite`, survivent à la reconstruction de l’index et peuvent aussi être
gérées depuis le menu Bibliothèque. Retirer une publication du suivi supprime ses
classements ; supprimer une catégorie ne supprime ni la publication ni son archive.
`read` ouvre les CBZ et les dossiers d’images dans le lecteur local de KomaForge.
Il fonctionne hors ligne sur `127.0.0.1`, avec une adresse de session aléatoire,
sans téléverser les pages. La position est enregistrée automatiquement ; les
flèches, Page précédente/suivante, Début, Fin, `F` et `Q` sont utilisables au
clavier. Le bouton **Fermer** ou `Q` arrête aussi le serveur local.
`continue` rouvre en priorité la partie inachevée consultée le plus récemment ;
à défaut, elle choisit la première partie non lue de la publication suivie la plus
récente. Pour une œuvre composée de plusieurs chapitres, chaque partie est associée
à sa propre archive avant l’ouverture afin de ne pas reprendre le mauvais CBZ.
`open` confie le premier artefact disponible à l’application locale associée à son
format. PDF, EPUB et CBR restent ainsi confiés à leur lecteur natif tant que leur
rendu interne n’est pas pris en charge. Le chemin doit rester dans le dossier de la
publication ; un ancien manifeste qui tente d’en sortir est refusé.

Les opérations différées utilisent une seconde base, indépendante de l’index :

```powershell
komaforge jobs add "https://votre-site.com/document" --action inspect
komaforge jobs add "https://votre-site.com/oeuvre" --action download --format cbz --chapters "1-5"
komaforge jobs add "https://votre-site.com/oeuvre" --action update
komaforge jobs list
komaforge jobs run-next
komaforge jobs run-all --limit 100
komaforge jobs retry IDENTIFIANT
komaforge jobs cancel IDENTIFIANT
```

La file accepte `inspect`, `download` et `update`. Elle conserve l’état et le nombre
de tentatives après un redémarrage, mais refuse les URL contenant des identifiants,
des jetons temporaires ou une session de lecteur eBooks. Une URL produit stable est
requise afin qu’aucun secret de session ne soit écrit dans SQLite.
`run-next` exécute les trois types de travaux avec le moteur existant. Une mise à
jour inspecte la publication, compare ses parties au manifeste indexé et place
uniquement les nouvelles parties dans la file de téléchargement. Une partie déjà
en attente ou en cours n’est pas ajoutée une seconde fois. Si la publication n’est
pas encore dans la bibliothèque, la vérification échoue explicitement.
`run-all` traite la file en série, y compris les téléchargements créés par une
vérification de mise à jour, avec une limite explicite qui empêche une boucle sans
fin de monopoliser l’application.
Une file placée dans `BIBLIOTHÈQUE/.komaforge/jobs.sqlite` dirige automatiquement
ses sorties vers cette bibliothèque. Pour une file stockée ailleurs, utilisez
`komaforge jobs run-all --root BIBLIOTHÈQUE`; un `--output` défini sur un travail
reste toujours prioritaire.

Les adaptateurs disponibles et leurs capacités peuvent être interrogés sans ouvrir
de navigateur :

```powershell
komaforge sources list
komaforge sources list --status validated
komaforge sources list --status degraded
komaforge sources list --status experimental
komaforge sources list --integration generic
komaforge sources list --access session_dependent
komaforge sources families
komaforge sources candidates
komaforge sources match "https://global.manga-up.com/manga/126"
komaforge sources search "Fullmetal Alchemist" --source mangadex
komaforge sources popular --source mangadex
komaforge sources latest --source mangadex
```

`list` sépare désormais trois informations qui ne signifient pas la même chose :
la compatibilité (`validated`, `degraded`, `experimental` ou `offline`),
l’intégration (`specialized` ou `generic`) et l’accès observé (`full`,
`source_limited`, `session_dependent` ou `variable`).
`families` garde séparées les stratégies réutilisables (lecteur paginé, vertical,
document direct ou parties sélectionnables). `candidates` liste les sites déjà
observés avec le fallback mais qui n’ont pas encore d’adaptateur spécialisé.
SushiScan et MangaReader.pro peuvent ainsi être marqués compatibles et validés tout
en restant honnêtement décrits comme des intégrations génériques. La date du dernier
contrôle live est publiée afin qu’un statut ancien ne soit pas pris pour une garantie.
La commande `match` montre clairement
si l’URL utilise une source spécialisée ou le fallback web générique. Elle ne
contacte pas le site et ne masque donc jamais l’échec ultérieur d’un adaptateur
reconnu. Un statut décrit la fiabilité de l’adaptateur, pas la complétude d’un livre :
la couverture reste consignée séparément dans le manifeste.
Calaméo, Manga UP et eBooks.com alimentent maintenant réellement le moteur par
leurs modèles normalisés de publication et de partie. Une source spécialisée
reconnue qui échoue produit donc son propre diagnostic au lieu de retomber
silencieusement sur la détection web générique. Core conserve la navigation, la
validation des ressources et la création des formats afin que ces garanties restent
communes à toutes les sources. Le chargement d’une publication et de ses parties
passe par le même contrat applicatif pour tous les adaptateurs ; ajouter une source
spécialisée ne nécessite plus d’ajouter son identifiant dans l’orchestrateur.

MangaDex est la première source à exposer la recherche, les œuvres populaires et
les dernières mises à jour à distance. Son adaptateur utilise l’API publique,
conserve l’attribution MangaDex et les noms des groupes de traduction dans les
métadonnées, puis demande le manifeste MangaDex@Home seulement pour les chapitres
sélectionnés. Son statut reste `experimental` pendant l’élargissement des tests
réels. Toute utilisation doit respecter la
[politique officielle de l’API MangaDex](https://gitlab.com/mangadex-pub/mangadex-api-docs/-/blob/main/index.md),
notamment les crédits, les demandes de retrait et l’interdiction d’en tirer un
service publicitaire ou payant.
Les commandes séparées `komaforge-library`, `komaforge-jobs` et
`komaforge-sources` restent installées pour les scripts existants.

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

KomaForge réutilise par défaut un profil Chrome dédié dans le dossier de données
local de l'utilisateur. Les validations et consentements déjà traités peuvent ainsi
survivre à une relance sans toucher au profil Chrome personnel. `--profile-dir`
permet de choisir un autre emplacement. Dans le menu, si une vérification reste
visible, KomaForge demande de la terminer dans Chrome avant d'analyser le document.

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
| `--profile-dir DOSSIER` | Remplace l'emplacement du profil KomaForge persistant |
| `--allow-host cdn.exemple.com` | Autorise explicitement un CDN externe vérifié |
| `--workers 6` | Télécharge de 1 à 12 images en parallèle (6 par défaut) |
| `--pdf` | Ancien alias de `--format pdf` |
| `--chrome CHEMIN` | Utilise un autre emplacement de Chrome |
| `--output DOSSIER` | Remplace le dossier de sortie automatique |

## Détection automatique : limites assumées

L'URL reste l'entrée principale : KomaForge inspecte le lecteur réellement ouvert
au lieu d'imposer une liste de sites qui deviendrait vite obsolète. Les adaptateurs
spécialisés complètent cette détection pour les sources connues ; le moteur générique
reste disponible pour essayer une URL inconnue sans prétendre offrir son catalogue.

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
Avec `--inspect`, cette reconstruction reste entièrement en mémoire : elle permet de
valider la couverture complète sans créer de PDF ni de manifeste.
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
