. "$PSScriptRoot\common-bots.ps1"

Write-Host "=== 1/4 Lavalink ==="
$lavalinkStatus = Get-ServiceStatus -ServiceKey "lavalink"
if ($lavalinkStatus.Running) {
    Write-Host "已在執行中，跳過啟動 (PID=$($lavalinkStatus.ProcessId), 來源=$($lavalinkStatus.Source))"
    if ($lavalinkStatus.Warning) { Write-Warning $lavalinkStatus.Warning }
} else {
    $javaCandidates = Get-ChildItem -Path (Join-Path $RepoRoot "music-bot\jdk17") -Filter "java.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*\bin\java.exe" }
    if (-not $javaCandidates) {
        Write-Error "找不到 Java (music-bot/jdk17/*/bin/java.exe)。"
        exit 1
    }
    $javaExe = $javaCandidates[0].FullName
    $lavalinkDir = Join-Path $RepoRoot "music-bot\lavalink"

    if (-not (Test-Path (Join-Path $lavalinkDir "Lavalink.jar"))) {
        Write-Error "找不到 music-bot/lavalink/Lavalink.jar。"
        exit 1
    }
    if (-not (Test-Path (Join-Path $lavalinkDir "application.yml"))) {
        Write-Error "找不到 music-bot/lavalink/application.yml，請先從 application.yml.example 複製並設定密碼。"
        exit 1
    }

    $proc = Start-TrackedProcess -ServiceKey "lavalink" -FilePath $javaExe -ArgumentList @("-jar", "Lavalink.jar") -WorkingDirectory $lavalinkDir
    Write-Host "已啟動 (PID=$($proc.ProcessId))"
}

Write-Host "=== 2/4 等待 Lavalink port 2333 ==="
if (Wait-Port2333 -TimeoutSec 30) {
    Write-Host "port 2333 已就緒"
} else {
    Write-Error "port 2333 在 30 秒內未就緒，中止啟動 music-bot / drawing-bot。請檢查 run/lavalink.stderr.log"
    exit 1
}

Write-Host "=== 3/4 Music Bot ==="
$musicStatus = Get-ServiceStatus -ServiceKey "music-bot"
if ($musicStatus.Running) {
    Write-Host "已在執行中，跳過啟動 (PID=$($musicStatus.ProcessId), 來源=$($musicStatus.Source))"
    if ($musicStatus.Warning) { Write-Warning $musicStatus.Warning }
} else {
    $musicDir = Join-Path $RepoRoot "music-bot"
    $musicPython = Join-Path $musicDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $musicPython)) {
        Write-Error "找不到 $musicPython，請先建立 music-bot 的 .venv。"
        exit 1
    }
    if (-not (Test-Path (Join-Path $musicDir ".env"))) {
        Write-Error "找不到 music-bot/.env。"
        exit 1
    }
    $proc = Start-TrackedProcess -ServiceKey "music-bot" -FilePath $musicPython -ArgumentList @("bot.py") `
        -WorkingDirectory $musicDir -ExtraEnv @{ PYTHONUTF8 = "1"; PYTHONIOENCODING = "utf-8" }
    Write-Host "已啟動 (PID=$($proc.ProcessId))"
}

Write-Host "=== 4/4 Drawing Bot ==="
$drawStatus = Get-ServiceStatus -ServiceKey "drawing-bot"
if ($drawStatus.Running) {
    Write-Host "已在執行中，跳過啟動 (PID=$($drawStatus.ProcessId), 來源=$($drawStatus.Source))"
    if ($drawStatus.Warning) { Write-Warning $drawStatus.Warning }
} else {
    $drawDir = Join-Path $RepoRoot "drawing-bot"
    $drawPython = Join-Path $drawDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $drawPython)) {
        Write-Error "找不到 $drawPython，請先建立 drawing-bot 的 .venv。"
        exit 1
    }
    if (-not (Test-Path (Join-Path $drawDir ".env"))) {
        Write-Error "找不到 drawing-bot/.env。"
        exit 1
    }
    $proc = Start-TrackedProcess -ServiceKey "drawing-bot" -FilePath $drawPython -ArgumentList @("bot.py") `
        -WorkingDirectory $drawDir -ExtraEnv @{ PYTHONUTF8 = "1"; PYTHONIOENCODING = "utf-8" }
    Write-Host "已啟動 (PID=$($proc.ProcessId))"
}

Write-Host ""
Write-Host "=== 完成，執行 status-bots.ps1 可查看目前狀態 ==="
