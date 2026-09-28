# Changelog

Toutes les modifications notables de KomaForge sont consignées ici.

## Non publié

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
