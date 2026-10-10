# KomaForge portable pour Windows

1. Extrayez toute l'archive ZIP dans un dossier.
2. Lancez `KomaForge.exe`, ou installez le raccourci avec PowerShell :
   `powershell -ExecutionPolicy Bypass -File .\Install-KomaForge.ps1`.

Python est inclus. Google Chrome reste necessaire ; WinRAR est facultatif pour CBR.
Les resultats restent dans `C:\Extractions\Manga` et le profil dans
`%LOCALAPPDATA%\KomaForge\ChromeProfile`.

Pour une mise a jour, telechargez la nouvelle archive depuis les Releases GitHub,
verifiez son empreinte avec `Get-FileHash -Algorithm SHA256`, puis executez son
script d'installation. Chaque version est rangee dans un dossier distinct ; les
donnees de lecture ne sont pas remplacees. Aucun telechargement automatique de
code n'a lieu au demarrage.

Un dossier d'installation personnalise est possible avec
`Install-KomaForge.ps1 -InstallRoot "$env:USERPROFILE\Apps\KomaForge\Releases"`.
Le raccourci pointe directement sur la version installee et ne depend pas du dossier
depuis lequel l'installation a ete lancee.

L'executable n'est pas signe avec un certificat commercial. Les sources et
SHA256SUMS.txt permettent de verifier la provenance du paquet.
