$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "=== 1/4 啟動 Lavalink (獨立視窗) ==="
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "start-lavalink.ps1") -WindowStyle Normal | Out-Null

Write-Host "=== 2/4 等待 Lavalink 就緒 (port 2333) ==="
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:2333/version" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {}
}

if (-not $ready) {
    Write-Error "Lavalink 在 30 秒內未就緒，請檢查另一個視窗的錯誤訊息，再重新執行。"
    exit 1
}
Write-Host "=== 3/4 Lavalink 已就緒 (port 2333) ==="

Write-Host "=== 4/4 啟動 Music Bot ==="
& (Join-Path $root "start-music-bot.ps1")
