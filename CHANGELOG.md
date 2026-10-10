# Changelog

Toutes les modifications notables de KomaForge sont consignées ici.

## 0.5.0 — 2026-10-10

- distribution Windows portable avec Python inclus, empreinte SHA-256 et installation
  du raccourci principal dans un dossier de version isolé ; les mises à jour restent
  explicites et ne remplacent ni les archives ni les données de lecture ;
- séparation de l'extraction d'une partie, des documents directs, des contrôles de
  lecteur, de la navigation eBooks et de la collecte d'images ; les anciens imports
  restent compatibles et l'orchestrateur ne contient plus les implémentations propres
  à chaque famille de lecteur ;
- diagnostics de couverture, conversion, transport et progression traduits en
  français, anglais, russe et chinois ; sortie UTF-8 sur les deux flux Windows ;
- capture Scribd limitée au rectangle de la page dans une fenêtre adaptée, contrôle
  des couches de texte conservé et libération des données image pendant l'inspection ;
- validation navigateur supplémentaire de la lecture, de la fermeture, de la reprise
  persistante et de la fin de lecture ; scénarios d'extraction réutilisables contre
  l'exécutable portable, pas seulement contre les sources Python ;
- refus de la conversion d'une section XHTML invalide : un PDF imprimant l'erreur
  du navigateur n'est plus présenté comme une conversion réussie ;

- la production des PDF/EPUB directs et celle des archives issues de pages image
  vivent maintenant dans des services séparés de l'orchestrateur principal ;
- la planification des chapitres, volumes et documents ainsi que l'état des
  manifestes (`complete`, `incomplete`, `limited_by_source`) sont centralisés dans
  des modules indépendants et couverts par des tests dédiés ;
- les validations réelles du 9 octobre confirment Calaméo `144/144`, SushiScan
  `241/241`, MangaReader.pro `109/109`, Scribd `231/231`, la récupération PDF
  eBooks `393/393` et le refus correct de l'aperçu EPUB `11/62` ;
- les titres en alphabet cyrillique, chinois et autres écritures Unicode gardent
  désormais un nom de dossier lisible au lieu de se réduire à quelques chiffres ;
- les manifestes tiers sûrs peuvent maintenant être activés explicitement comme
  sources déclaratives : aucun code externe n’est chargé, leurs domaines sont
  routés vers les familles génériques intégrées et leurs autorisations réseau
  alimentent la liste fermée des hôtes de ressources ;
- Scribd possède maintenant un adaptateur séparé : chaque conteneur `outer_page_N`
  est rendu avec sa couche de texte et ses illustrations, les pages déjà capturées
  sont libérées pour stabiliser la mémoire, et la référence testée retrouve 231
  pages visuellement lisibles sur 231 ;
- les verrous Scribd demandant une publicité sont détectés avant et après la capture,
  y compris lorsque le flou est porté par un parent ou injecté pendant le défilement ;
  le contenu flouté n'est plus annoncé comme une page réussie, et `--wait-for-user`
  permet de terminer le parcours officiel dans Chrome lorsqu'il est disponible ;
- une page Scribd qui annonce du texte mais produit une image blanche est maintenant
  recapturée par le chemin de secours, puis refusée si elle reste vide ; un dépôt
  publicitaire de 224 conteneurs ne peut donc plus être annoncé comme un livre complet ;
- les anciennes URL Scribd `/doc/<id>` utilisent le même adaptateur spécialisé et
  les mêmes contrôles que les URL actuelles `/document/<id>` ;
- `KOMAFORGE_OUTPUT_ROOT` permet à un lanceur de test d'isoler totalement ses
  extractions de celles de l'application stable ;
- MGU Russian Store : les fiches de livres numériques sont reconnues comme des
  pages d’achat dont les fichiers sont livrés par e-mail ; KomaForge refuse
  désormais explicitement la photo commerciale au lieu d’en faire une fausse page ;
- le chargement progressif ignore les images cachées instables et ne confond plus
  un bouton « Show full title » avec un contrôle de mode de lecture ;
- `doctor` fournit un diagnostic local et sans écriture de Chrome, des dépendances,
  des dossiers, des schémas SQLite et des manifestes tiers depuis la commande ou
  le menu principal ;
- les manifestes de sources tierces peuvent être inspectés depuis la commande et
  le menu sans charger de code ; leur schéma refuse notamment les points d’entrée
  exécutables, l’accès aux fichiers et les collisions avec les sources intégrées ;
- le chargement progressif ne confond plus un nombre d’images stable avec la fin
  du lecteur tant que la position de défilement continue d’avancer ;
- les lecteurs Blob, manifestes de chapitre, paginés et verticaux sont maintenant
  routés par des stratégies de famille isolées et testables, hors de l’orchestrateur
  de détection monolithique ;
- l'inspection et la récupération explicitement autorisée des arbres PDF détachés
  vivent maintenant dans un service structurel indépendant, avec leurs tests
  unitaires exécutés sans démarrer les scénarios navigateur ;
- le téléchargement PDF dans la session du navigateur, sa reprise par segments et
  sa validation vivent maintenant dans un service de transport séparé, tout en
  conservant les anciens points d'import d'`engine` ;
- la récupération et la validation EPUB utilisent désormais leur propre service de
  transport, sans dépendre des constantes internes du chemin PDF ;
- l'observation des réponses PDF, EPUB et JSON du lecteur ainsi que le calcul du
  total annoncé vivent maintenant dans un service de métadonnées réseau testable ;
- le téléchargement des pages, sa reprise vérifiée, la liste fermée des hôtes et le
  repli navigateur sont isolés dans un service dédié, sans changer l'API historique ;
- le cycle de vie du profil Chrome, l'attente de son interface de contrôle et la
  navigation avec récupération SSL bornée sont regroupés dans un service navigateur ;
- la découverte des liens de chapitre, contrôles de volume et documents uniques
  suit désormais le même contrat de stratégie, hors de l’adaptateur web générique ;
- la liste des nouveautés expose maintenant l’état réel de leur téléchargement,
  et le lecteur peut ouvrir directement une partie choisie depuis la commande ou
  le menu Bibliothèque ;
- les nouveautés peuvent être filtrées par publication et acquittées partie par
  partie ; le menu ne marque la sélection comme consultée qu’après sa lecture ;
- la bibliothèque peut maintenant synchroniser en une commande les publications
  suivies : vérifications et nouveaux téléchargements sont exécutés dans une limite
  bornée, sans consommer les inspections indépendantes déjà présentes dans la file ;
- une inspection PDF autorisée peut maintenant reconstruire et recompter en mémoire
  un arbre de pages détaché, sans écrire d’artefact ni de manifeste ;
- un résultat de recherche, de popularité ou de nouveautés peut être choisi depuis
  le menu Sources, puis ajouté et suivi explicitement dans la bibliothèque ;
- le diagnostic d’une URL SushiScan ou MangaReader.pro conserve désormais le statut
  validé du site tout en exposant son routage par l’adaptateur web générique ;
- `sources status` fournit un résumé stable des états et capacités du catalogue, et
  les dates de vérification reflètent les six inspections réelles du 28 septembre ;
- les mises à jour d’une œuvre regroupent leurs nouvelles parties dans un seul
  téléchargement et fusionnent le manifeste avec les archives déjà présentes, au
  lieu de créer des publications de chapitre isolées ;
- MangaDex fournit maintenant recherche, populaires, dernières mises à jour,
  catalogue de chapitres et pages originales MangaDex@Home, avec attribution de
  la source et des groupes de traduction conservée dans les métadonnées ;
- les adaptateurs peuvent désormais fournir leurs ressources à Core par le contrat
  commun, sans branche propre à chaque nouveau site dans l’orchestrateur ;
- les nouvelles parties détectées sont conservées dans une liste persistante,
  distincte des non-lus, consultable et acquittable depuis la commande ou le menu ;
- une file rangée dans une bibliothèque personnalisée conserve désormais les
  téléchargements générés dans cette même bibliothèque ;
- les sous-commandes JSON configurent explicitement UTF-8 sous Windows afin que
  titres, auteurs et métadonnées multilingues restent affichables ;
- une publication entière ou une partie précise peut être marquée lue ou non lue
  depuis la commande et le menu, sans modifier ses archives ni son suivi ;
- le tableau de bord repose maintenant sur un instantané applicatif commun au menu
  et à `library status --json`, incluant téléchargements, suivis, catégories,
  non-lus, historique et file par statut ;
- Calaméo, Manga UP et eBooks.com fournissent maintenant leurs publications
  normalisées au moteur d’extraction ; l’échec d’une source reconnue reste explicite
  et ne déclenche pas de fallback générique silencieux ;
- eBooks conserve le titre capturé sur la fiche produit lorsque le lecteur affiche
  seulement un titre générique, et retire le suffixe auteur propre aux métadonnées
  de page sans modifier le titre de l’œuvre ;
- la dernière lecture inachevée peut être reprise directement ; les œuvres
  multi-parties rouvrent désormais l’archive correspondant exactement au chapitre
  choisi au lieu de supposer que le premier fichier convient ;
- une couverture de catalogue prouvée au niveau de l’œuvre prévaut maintenant sur
  un ancien manifeste qui déclarait à tort un chapitre isolé comme publication
  complète ;
- les publications suivies peuvent maintenant être rangées dans plusieurs
  catégories locales, gérées depuis la commande ou le menu Bibliothèque et
  conservées lors de la reconstruction de l’index ;
- un lecteur local intégré ouvre maintenant les CBZ et dossiers d’images, reprend
  la dernière page, enregistre la progression et reste utilisable au clavier sur
  ordinateur comme sur écran étroit ; PDF, EPUB et CBR conservent l’ouverture
  native explicite ;
- les statuts de source distinguent maintenant la compatibilité, le type
  d’intégration et les conditions d’accès ; SushiScan et MangaReader.pro sont
  répertoriés comme validés via le moteur générique ;
- l’index de bibliothèque est créé lorsqu’il manque et actualisé automatiquement
  après une extraction réussie ;
- les travaux `update` inspectent la publication indexée, comparent ses parties et
  mettent uniquement les nouveautés en file, sans doublonner un téléchargement
  déjà en attente ;
- la commande et le menu `library add` enchaînent extraction, indexation et suivi
  d’une publication depuis son URL, sans enregistrer un échec comme un ajout ;
- la bibliothèque expose la liste des parties non lues, avec la dernière position
  enregistrée pour les lectures commencées ;
- toutes les publications suivies, ou une seule publication choisie, peuvent être
  placées en file de mise à jour sans créer de vérifications actives en doublon ;
- la file peut être exécutée entièrement en série avec une limite de sécurité, y
  compris les téléchargements ajoutés par les vérifications de mise à jour ;
- les listes locales incluent maintenant les téléchargements encore disponibles et
  l’historique de lecture résolu vers les publications actuelles ;
- le tableau de bord affiche aussi le nombre de parties non lues et les travaux en
  attente ou échoués ;
- la reconstruction préfère les manifestes possédant une couverture explicite et
  regroupe les anciennes sessions eBooks avec leur fiche produit ; un vieux succès
  sans total connu ne peut plus masquer un diagnostic récent `11/62` ;
- les anciens titres d’interstitiel tels que `Just a moment` sont réparés depuis
  l’URL stable au lieu d’apparaître dans la bibliothèque ;
- un téléchargement peut être ouvert depuis la commande ou le menu Bibliothèque ;
  les chemins d’artefact sortant du dossier de publication sont refusés ;
- le menu interactif donne maintenant accès aux sources, aux familles de lecteurs,
  au diagnostic d’URL, à la bibliothèque locale et à la file d’attente persistante ;
- la bibliothèque peut être reconstruite, parcourue, recherchée et suivie sans
  quitter l’interface ; la progression de lecture y est également enregistrable ;
- les inspections, téléchargements et vérifications de mise à jour peuvent être
  ajoutés, consultés, relancés ou annulés depuis le même menu ;
- eBooks : une activation Preview ignorée juste après la vérification d’accès est
  relancée une fois, sans deviner d’URL ni élargir le contenu autorisé ;
- nouveau menu terminal structuré, coloré lorsque le terminal le permet et
  utilisable sans couleur ; interface disponible en français, anglais, russe
  et chinois, y compris l'aide `--help` et les principaux diagnostics ;
- courte intro animée du terminal : une mascotte originale traverse la forge et
  allume le nom en moins de 200 ms ; image finale compacte en mode sans mouvement ;
- nettoyage robuste des profils Chrome temporaires sous Windows afin d'éviter
  l'accumulation de plusieurs gigaoctets dans `%TEMP%` ;
- Manga UP : lecture du catalogue officiel rendu par le serveur pour distinguer
  les sous-parties gratuites du catalogue complet. Une extraction publique est
  désormais marquée `limited_by_source` au lieu d'être annoncée comme l'œuvre
  complète, et les petites séries accessibles proposent `all` par défaut.

- nommage automatique des dossiers et fichiers à partir du vrai titre de l'ouvrage ;
- ajout du numéro de chapitre aux lecteurs dont l'URL représente un chapitre unique ;
- protection contre l'écrasement silencieux d'un autre ouvrage portant le même chemin technique ;
- reconnaissance d'une même source malgré le renouvellement de ses jetons temporaires ;
- refus automatique des cookies non essentiels sur les bandeaux connus, dont Cookiebot ;
- récupération des pages Calaméo depuis les ressources réellement chargées par Chrome ;
- blocage des faux titres d'interstitiel comme `Just a moment` ;
- découverte d'un lecteur eBooks uniquement depuis une action Preview/Read sample explicite ;
- PDF SVG imprimé en une seule session Chrome au lieu d'un processus par page ;
- conversion des SVG en PNG natifs pour rendre les CBZ et CBR compatibles avec les lecteurs courants.
- rejet des CTA Anime-Planet et lecture du manifeste ordonné de son lecteur paginé ;
- parcours des lecteurs virtualisés à URL `blob:`, avec conservation des octets WebP originaux ;
- distinction entre les écrans doubles d'un lecteur et ses fichiers de pages réels ;
- identification explicite du chapitre ouvert après un bouton `Start reading`.

## 0.4.0 - 2026-09-24

- récupération du premier chargement SSL défaillant dans Chrome ;
- profil Calaméo avec nombre de pages et CDN vérifiés ;
- suppression exacte de `SPECIMEN` par défaut et option répétable `--watermark-text` ;
- remplacement du rendu Inkscape par l'impression PDF de Chrome issue du prototype validé.
- modèle structuré œuvre → chapitres → pages dans les manifestes ;
- détection prudente des listes de chapitres sur les URL inconnues ;
- détection des menus dynamiques de volumes, tomes et chapitres ;
- conservation du vocabulaire `volume` et sortie dans un dossier `volumes` ;
- distinction entre le nombre d'images sources et le nombre inconnu de pages papier ;
- attente du chargement progressif avant de valider un compteur provisoire `1 / 1` ;
- attente des options ajoutées tardivement dans un menu de volumes ;
- affichage concis du mode de lecture et acceptation sûre des liens Markdown collés ;
- rejet absolu des logos, icônes, bannières et images héroïnes comme pages ;
- attente d'initialisation et diagnostic des lecteurs PDF rendus par canvas/iframe ;
- exploration récursive des Shadow DOM et des iframes accessibles ;
- activation ciblée des boutons de démarrage comme `Load preview` ;
- détection, validation et conservation du vrai PDF chargé par le navigateur ;
- comparaison avec les compteurs de pages tardifs trouvés dans les métadonnées JSON ;
- statut `incomplete` sans fichier de sortie lorsqu'un PDF ne couvre pas toute la publication ;
- suppression de `--allow-partial` : aucun document incomplet n'est conservé ;
- reconnaissance des arbres PDF détachés dont les pages visibles forment le préfixe ordonné ;
- récupération explicite et validée d'un arbre PDF détaché avec `--recover-detached-pdf` ;
- téléchargement segmenté et vérifié des gros PDF compatibles avec les plages d'octets ;
- proposition contextuelle de récupération dans le menu interactif après validation complète de l'arbre ;
- choix du format restauré dans le menu simple, avec `original` recommandé ;
- conservation automatique du conteneur natif : PDF, EPUB ou CBZ pour les pages image ;
- détection et validation des EPUB chargés par le lecteur, y compris leur spine OPF ;
- comparaison des fichiers EPUB présents avec tous les documents annoncés par leur table des matières ;
- diagnostic des entrées ZIP locales détachées et des données ajoutées après la fin du conteneur ;
- refus d'étiqueter comme complet un EPUB d'aperçu dont des chapitres annoncés sont absents ;
- conversion EPUB vers PDF avec Chrome et conversion documentaire vers des pages PNG à 200 ppp ;
- refus de produire un fichier basse qualité lorsqu'aucune page originale n'est exposée ;
- choix interactif des volumes après détection, avec la première partie par défaut ;
- interruption plus propre des boucles de chargement progressif.
- attente des lecteurs dont le contenu apparaît tardivement sans message `Loading` ;
- arrêt anticipé du défilement lorsque toutes les ressources attendues sont prêtes ;
- préférence pour une famille d'URL numérotée face aux vignettes et images d'interface ;
- détection des compteurs de forme `1/177` et correction par une séquence continue plus fiable ;
- autorisation automatique limitée aux CDN HTTPS dominants du groupe de pages sélectionné ;
- téléchargement parallèle réglable avec `--workers`, puis repli dans la session Chrome ;
- reprise liée à l'URL, au nom et au SHA-256 de chaque page, sans réutilisation d'un ancien placeholder ;
- échelle PDF stable à 96 ppp sans rééchantillonnage, y compris pour les bandeaux très bas ;
- tri documentaire explicite après les arrivées réseau parallèles ;
- sortie séparée par chapitre et sélection `--chapters all` ou `1-5,8` ;
- modes `--inspect`, `--scope document` et `--scope work` ;
- protection contre l'expansion involontaire d'une URL qui désigne déjà un chapitre ;
- retrait des filigranes demandés dans les SVG déjà présents lors d'une reprise ;
- poursuite des chapitres suivants lorsqu'un chapitre intermédiaire échoue.

## 0.3.1 - 2026-09-22

- correction du test du chemin de sortie Windows pour les validations Linux ;
- mise à jour des actions GitHub vers leurs versions actuelles ;
- validation de la branche principale et des demandes de fusion, sans doublon lors de la création d'une étiquette de version.

## 0.3.0 - 2026-09-22

- identification des ressources par signature plutôt que par extension ;
- prise en charge des SVG, vrais SVGZ/GZIP et faux `.svgz` non compressés ;
- décodage des images intégrées dans les URI `data:` ;
- inventaire SVG des balises, classes, textes et images Base64 ;
- détection des filigranes par texte, rareté, géométrie et largeur ;
- retrait facultatif des seuls candidats à confiance élevée ;
- PDF vectoriel pour les pages SVG avec Inkscape et pikepdf ;
- tests sur 145 SVG réels et scénario navigateur SVGZ complet.

## 0.2.0 - 2026-09-22

- identité KomaForge et licence MIT ;
- choix d'une sortie unique : CBZ, CBR, PDF, EPUB ou images ;
- conservation et vérification des octets originaux en CBZ et EPUB ;
- CBR réel via WinRAR/rar, sans faux ZIP renommé ;
- nettoyage sécurisé des fichiers de travail après validation.

## 0.1.0 - 2026-09-22

- extracteur Chrome/CDP validé ;
- détection automatique des pages et du mode de lecture ;
- reprise, contrôle des domaines, hashes et manifeste.
