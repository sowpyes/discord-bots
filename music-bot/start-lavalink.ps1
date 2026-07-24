$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$lavalinkDir = Join-Path $root "lavalink"
$lavalinkJar = Join-Path $lavalinkDir "Lavalink.jar"
$appYml = Join-Path $lavalinkDir "application.yml"

$javaCandidates = Get-ChildItem -Path (Join-Path $root "jdk17") -Filter "java.exe" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\bin\java.exe" }

if (-not $javaCandidates) {
    Write-Error "找不到 Java (music-bot/jdk17/*/bin/java.exe)。請先安裝/解壓縮 Java 17+ 到 jdk17/ 目錄。"
    exit 1
}
$javaExe = $javaCandidates[0].FullName

if (-not (Test-Path $lavalinkJar)) {
    Write-Error "找不到 $lavalinkJar，請先下載 Lavalink.jar 到 lavalink/ 目錄。"
    exit 1
}

if (-not (Test-Path $appYml)) {
    Write-Error "找不到 $appYml，請先複製 lavalink/application.yml.example 為 application.yml 並設定密碼。"
    exit 1
}

Write-Host "Using Java: $javaExe"
Write-Host "Starting Lavalink..."

Set-Location $lavalinkDir
& $javaExe -jar "Lavalink.jar"
