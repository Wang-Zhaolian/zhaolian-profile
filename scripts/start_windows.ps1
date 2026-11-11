$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'ZhaolianProfile\runtime\windows'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$logPath = Join-Path $runtimeRoot 'startup.log'
try {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        $candidate = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local\bin\uv.exe'
        if (Test-Path -LiteralPath $candidate) { $uvPath = $candidate }
        else { throw 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ and try again.' }
    } else { $uvPath = $uv.Source }
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $runtimeRoot 'venv'
    & $uvPath sync --project $projectRoot --frozen --no-dev --python 3.14 *> $logPath
    if ($LASTEXITCODE -ne 0) { throw "Runtime setup failed. See $logPath" }
    $python = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\pythonw.exe'
    Start-Process -FilePath $python -ArgumentList ('"' + (Join-Path $projectRoot 'start.pyw') + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Zhaolian Profile') | Out-Null
}
