# Backward-compatible wrapper. Opens the CRM root so saved sessions go to dashboard.
$script = Join-Path $PSScriptRoot "open-app.ps1"
& $script
