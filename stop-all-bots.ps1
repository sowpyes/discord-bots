. "$PSScriptRoot\common-bots.ps1"

$order = @("drawing-bot", "music-bot", "lavalink")

foreach ($key in $order) {
    $svc = $Services[$key]
    Write-Host "=== 停止 $($svc.DisplayName) ==="
    $status = Get-ServiceStatus -ServiceKey $key

    if (-not $status.Running) {
        Write-Host "目前沒有執行中的行程，略過。"
        continue
    }

    Write-Host "找到行程 PID=$($status.ProcessId)，CommandLine 已驗證符合本專案簽章，停止中..."
    try {
        Stop-Process -Id $status.ProcessId -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 500
        Remove-PidFile -ServiceKey $key
        Write-Host "已停止 (PID=$($status.ProcessId))"
    } catch {
        Write-Warning "停止 PID=$($status.ProcessId) 時發生錯誤：$($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "=== 完成 ==="
