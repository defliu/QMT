# CC Watcher - full capability mode
#
# Passes task as a command-line argument so CC starts in interactive mode
# with full CLI: plugins, /slash commands, hooks, memory
#
# Start: powershell -File D:\QMT_STRATEGIES\scripts\cc-watcher.ps1

param(
    [string]$WatchDir = "D:\QMT_STRATEGIES",
    [int]$PollSeconds = 2
)

$taskFile = Join-Path $WatchDir ".hermes_task.txt"
$helper = Join-Path $WatchDir "scripts\cc-run.ps1"

Write-Host ""
Write-Host "CC Watcher - full mode started"
Write-Host "  Watching: $WatchDir\.hermes_task.txt"
Write-Host "  Poll: ${PollSeconds}s"
Write-Host ""

$count = 0

while ($true) {
    if (Test-Path $taskFile) {
        $task = Get-Content $taskFile -Raw
        Remove-Item $taskFile -Force

        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] New task -> opening CC window"
        $taskPreview = $task.Substring(0, [Math]::Min(80, $task.Length))
        Write-Host "  Task: $taskPreview..."

        # Write task to UTF-8 file
        $promptFile = Join-Path $WatchDir ".hermes_prompt_$timestamp.md"
        [System.IO.File]::WriteAllText($promptFile, $task, [System.Text.Encoding]::UTF8)

        # .bat just calls the PowerShell helper - no escaping issues
        $batContent = "@echo off`r`n"
        $batContent += "title CC-TASK-$timestamp`r`n"
        $batContent += "cd /d `"$WatchDir`"`r`n"
        $batContent += "echo ---- CC task $timestamp ----`r`n"
        $batContent += "echo.`r`n"
        $batContent += "powershell -NoProfile -ExecutionPolicy Bypass -File `"$helper`" -TaskFile `"$promptFile`" -WatchDir `"$WatchDir`"`r`n"
        $batContent += "echo.`r`n"
        $batContent += "echo ---- CC exited ----`r`n"
        $batContent += "pause`r`n"
        $batContent += "del /f /q `"$batFile`" >nul 2>&1`r`n"
        
        $batFile = Join-Path $WatchDir ".hermes_run_$timestamp.bat"
        [System.IO.File]::WriteAllText($batFile, $batContent, [System.Text.Encoding]::ASCII)

        Start-Process cmd -ArgumentList "/c `"$batFile`""

        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Window opened - CC in full interactive mode"
        Write-Host ""
    }

    Start-Sleep -Seconds $PollSeconds
    $count++
    if ($count % 30 -eq 0) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Watching... (checked $count times)"
    }
}
