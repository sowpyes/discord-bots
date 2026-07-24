# Shared helpers for start-all-bots.ps1 / stop-all-bots.ps1 / status-bots.ps1
# Dot-source this file: . "$PSScriptRoot\common-bots.ps1"

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$Script:RepoRoot = $PSScriptRoot
$Script:RunDir = Join-Path $RepoRoot "run"
if (-not (Test-Path $RunDir)) {
    New-Item -ItemType Directory -Path $RunDir | Out-Null
}

$Script:Services = @{
    "lavalink" = @{
        DisplayName    = "Lavalink"
        PidFile        = Join-Path $RunDir "lavalink.pid.json"
        StdoutLog      = Join-Path $RunDir "lavalink.stdout.log"
        CmdlineMustHave = @("Lavalink.jar", "music-bot\jdk17")
    }
    "music-bot" = @{
        DisplayName    = "Music Bot"
        PidFile        = Join-Path $RunDir "music-bot.pid.json"
        StdoutLog      = Join-Path $RunDir "music-bot.stdout.log"
        CmdlineMustHave = @("music-bot\.venv\Scripts\python.exe", "bot.py")
    }
    "drawing-bot" = @{
        DisplayName    = "Drawing Bot"
        PidFile        = Join-Path $RunDir "drawing-bot.pid.json"
        StdoutLog      = Join-Path $RunDir "drawing-bot.stdout.log"
        CmdlineMustHave = @("drawing-bot\.venv\Scripts\python.exe", "bot.py")
    }
}

function Test-CommandLineMatch {
    param(
        [string]$CommandLine,
        [string[]]$MustHave
    )
    if (-not $CommandLine) { return $false }
    foreach ($needle in $MustHave) {
        if ($CommandLine -notlike "*$needle*") {
            return $false
        }
    }
    return $true
}

function Find-RunningServiceProcess {
    param([string]$ServiceKey)

    $svc = $Services[$ServiceKey]
    $procName = if ($ServiceKey -eq "lavalink") { "java.exe" } else { "python.exe" }

    # Get-CimInstance/WMI can occasionally return a stale/empty snapshot right after
    # another process was just started or stopped; retry once before concluding "not found".
    for ($attempt = 0; $attempt -lt 2; $attempt++) {
        $candidates = @(Get-CimInstance Win32_Process -Filter "Name = '$procName'" -ErrorAction SilentlyContinue |
            Where-Object { Test-CommandLineMatch -CommandLine $_.CommandLine -MustHave $svc.CmdlineMustHave })
        if ($candidates.Count -gt 0) { break }
        if ($attempt -eq 0) { Start-Sleep -Milliseconds 500 }
    }

    return @($candidates)
}

function Read-PidFile {
    param([string]$ServiceKey)
    $path = $Services[$ServiceKey].PidFile
    if (-not (Test-Path $path)) { return $null }
    try {
        return Get-Content -Path $path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Write-PidFile {
    param(
        [string]$ServiceKey,
        [int]$ProcessId,
        [string]$CommandLine,
        [datetime]$StartTime
    )
    $path = $Services[$ServiceKey].PidFile
    $obj = @{
        pid         = $ProcessId
        commandLine = $CommandLine
        startTime   = $StartTime.ToString("o")
    }
    $json = $obj | ConvertTo-Json
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $json, $enc)
}

function Remove-PidFile {
    param([string]$ServiceKey)
    $path = $Services[$ServiceKey].PidFile
    if (Test-Path $path) { Remove-Item -Path $path -Force }
}

function Get-ServiceStatus {
    <#
    Returns an object: @{ Running=bool; ProcessId=int|$null; StartTime=datetime|$null;
                          Source="pidfile"|"discovered"|$null; Warning=string|$null }
    Verification is always against the *live* CommandLine, never trust the pid file blindly.
    #>
    param([string]$ServiceKey)

    $svc = $Services[$ServiceKey]
    $result = @{
        Running   = $false
        ProcessId = $null
        StartTime = $null
        Source    = $null
        Warning   = $null
    }

    $pidFileObj = Read-PidFile -ServiceKey $ServiceKey
    if ($pidFileObj) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($pidFileObj.pid)" -ErrorAction SilentlyContinue
        if ($proc -and (Test-CommandLineMatch -CommandLine $proc.CommandLine -MustHave $svc.CmdlineMustHave)) {
            $result.Running = $true
            $result.ProcessId = $proc.ProcessId
            $result.StartTime = [datetime]$pidFileObj.startTime
            $result.Source = "pidfile"
            return $result
        } else {
            # stale pid file: pid gone, or reused by an unrelated process
            Remove-PidFile -ServiceKey $ServiceKey
        }
    }

    $discovered = Find-RunningServiceProcess -ServiceKey $ServiceKey
    if ($discovered.Count -ge 1) {
        $p = $discovered[0]
        $result.Running = $true
        $result.ProcessId = $p.ProcessId
        $result.StartTime = $p.CreationDate
        $result.Source = "discovered"
        if ($discovered.Count -gt 1) {
            $result.Warning = "發現 $($discovered.Count) 個符合的行程(預期只有 1 個)，可能有重複啟動。"
        }
        # adopt into pid file so stop/status stay consistent next time
        Write-PidFile -ServiceKey $ServiceKey -ProcessId $p.ProcessId -CommandLine $p.CommandLine -StartTime $p.CreationDate
    }

    return $result
}

function Test-Port2333 {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $task = $client.ConnectAsync("127.0.0.1", 2333)
        $ok = $task.Wait(1500)
        $connected = $ok -and $client.Connected
        $client.Close()
        return $connected
    } catch {
        return $false
    }
}

function Wait-Port2333 {
    param([int]$TimeoutSec = 30)
    for ($i = 0; $i -lt $TimeoutSec; $i++) {
        if (Test-Port2333) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-TrackedProcess {
    param(
        [string]$ServiceKey,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [hashtable]$ExtraEnv = @{}
    )

    $svc = $Services[$ServiceKey]

    foreach ($key in $ExtraEnv.Keys) {
        [Environment]::SetEnvironmentVariable($key, $ExtraEnv[$key], "Process")
    }

    $stdout = $svc.StdoutLog
    $stderrPath = $stdout -replace '\.log$', '.stderr.log'

    $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderrPath -PassThru

    Start-Sleep -Milliseconds 800
    $live = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue
    if (-not $live) {
        throw "$($svc.DisplayName) 啟動後立即結束，請檢查 $stderrPath"
    }

    Write-PidFile -ServiceKey $ServiceKey -ProcessId $live.ProcessId -CommandLine $live.CommandLine -StartTime $live.CreationDate
    return $live
}
