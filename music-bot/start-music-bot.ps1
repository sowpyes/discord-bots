$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
$envFile = Join-Path $root ".env"
$botScript = Join-Path $root "bot.py"

if (-not (Test-Path $pythonExe)) {
    Write-Error "找不到虛擬環境 Python：$pythonExe。請先執行：python -m venv .venv 並 pip install -r requirements.txt"
    exit 1
}

if (-not (Test-Path $envFile)) {
    Write-Error "找不到 $envFile。請先複製 .env.example 為 .env 並填入 DISCORD_TOKEN 與 LAVALINK_PASSWORD。"
    exit 1
}

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:2333/version" -UseBasicParsing -TimeoutSec 3 | Out-Null
    Write-Host "Lavalink (127.0.0.1:2333) 連線正常。"
} catch {
    Write-Warning "Lavalink (127.0.0.1:2333) 目前無法連線。請先執行 start-lavalink.ps1。Bot 仍會啟動，但語音功能會失敗直到 Lavalink 就緒。"
}

Set-Location $root
& $pythonExe $botScript
