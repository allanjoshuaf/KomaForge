# Changelog

Toutes les modifications notables de KomaForge sont consignées ici.

## Version locale en cours

- récupération du premier chargement SSL défaillant dans Chrome ;
- profil Calaméo avec nombre de pages et CDN vérifiés ;
- suppression exacte de `SPECIMEN` par défaut et option répétable `--watermark-text` ;
- remplacement du rendu Inkscape par l'impression PDF de Chrome issue du prototype validé.

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
