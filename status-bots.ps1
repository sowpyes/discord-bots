. "$PSScriptRoot\common-bots.ps1"

$rows = @()
foreach ($key in @("lavalink", "music-bot", "drawing-bot")) {
    $svc = $Services[$key]
    $status = Get-ServiceStatus -ServiceKey $key

    $uptime = if ($status.Running -and $status.StartTime) {
        $span = (Get-Date) - $status.StartTime
        "{0:d2}:{1:d2}:{2:d2}" -f [int]$span.TotalHours, $span.Minutes, $span.Seconds
    } else { "-" }

    $rows += [PSCustomObject]@{
        服務     = $svc.DisplayName
        狀態     = if ($status.Running) { "Running" } else { "Stopped" }
        PID      = if ($status.Running) { $status.ProcessId } else { "-" }
        啟動時間 = if ($status.Running -and $status.StartTime) { $status.StartTime.ToString("yyyy-MM-dd HH:mm:ss") } else { "-" }
        執行時長 = $uptime
        來源     = if ($status.Running) { $status.Source } else { "-" }
    }

    if ($status.Warning) { Write-Warning "$($svc.DisplayName): $($status.Warning)" }
}

$rows | Format-Table -AutoSize

$portOpen = Test-Port2333
Write-Host ""
Write-Host "Lavalink port 2333: $(if ($portOpen) { 'OPEN' } else { 'CLOSED' })"
