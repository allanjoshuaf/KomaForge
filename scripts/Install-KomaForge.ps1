param([string]$Version = "")
$ErrorActionPreference = "Stop"

$source = $PSScriptRoot
$executable = Join-Path $source "KomaForge.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "KomaForge.exe est absent. Extrayez toute l'archive avant l'installation."
}
$reported = & $executable --version
if ($LASTEXITCODE -ne 0 -or $reported -notmatch '^komaforge (\d+\.\d+\.\d+)$') {
    throw "Impossible de verifier la version de KomaForge.exe"
}
$actualVersion = $Matches[1]
if ($Version -and $Version -ne $actualVersion) { throw "Version demandee differente de l'executable" }
$Version = $actualVersion
$base = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "KomaForge\Releases"
$destination = Join-Path $base $Version
if (-not (Test-Path -LiteralPath $destination)) {
    $staging = Join-Path $base "$Version-install-$([Guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $staging -Recurse
    Move-Item -LiteralPath $staging -Destination $destination
} else {
    foreach ($file in (Get-ChildItem -LiteralPath $source -File -Recurse -Force)) {
        $relative = $file.FullName.Substring($source.Length).TrimStart('\')
        $existing = Join-Path $destination $relative
        if (-not (Test-Path -LiteralPath $existing -PathType Leaf) -or
            (Get-FileHash -LiteralPath $existing -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash) {
            throw "La version $Version existe avec un contenu different. Rien n'a ete remplace."
        }
    }
}
$installed = Join-Path $destination "KomaForge.exe"
if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) { throw "Installation incomplete" }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop "KomaForge.lnk"))
$shortcut.TargetPath = $installed
$shortcut.WorkingDirectory = $destination
$shortcut.IconLocation = "$installed,0"
$shortcut.WindowStyle = 1
$shortcut.Description = "KomaForge $Version"
$shortcut.Save()
Write-Host "KomaForge $Version est installe. Ouvrez KomaForge sur le Bureau."
Write-Host "Les archives, le profil Chrome et la bibliotheque conservent leurs emplacements."
