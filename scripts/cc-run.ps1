# Helper: run CC with a task file as prompt argument
param(
    [string]$TaskFile,
    [string]$WatchDir
)

$CC = "C:\Users\Administrator\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
$task = Get-Content $TaskFile -Raw -Encoding UTF8

Write-Host "Running CC with task..."
& $CC $task --dangerously-skip-permissions --add-dir $WatchDir
