param(
    [string]$Pattern = "PERF|失败|failed|ERROR|WARNING|model_not_found|elapsed_ms"
)

$root = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$logs = @(
    Join-Path $root "backend.err.log"
    Join-Path $root "backend.out.log"
    Join-Path $root "frontend.err.log"
    Join-Path $root "frontend.out.log"
) | Where-Object { Test-Path -LiteralPath $_ }

if (-not $logs) {
    Write-Host "No log files found. Start backend/frontend first."
    exit 1
}

Write-Host "Watching logs:"
$logs | ForEach-Object { Write-Host "  $_" }
Write-Host "Filter: $Pattern"
Write-Host ""

Get-Content -LiteralPath $logs -Wait -Tail 80 | Select-String -Pattern $Pattern
