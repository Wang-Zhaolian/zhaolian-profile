param([switch]$NoDialog)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
# Avoid AppData redirection by packaged terminal hosts. This is a managed cache.
$runtimeRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.cache\ZhaolianProfile\windows'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$temporaryRoot = Join-Path $runtimeRoot 'tmp'
New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
$env:TEMP = $temporaryRoot
$env:TMP = $temporaryRoot
$env:UV_CACHE_DIR = Join-Path $runtimeRoot 'uv-cache'
$env:UV_LINK_MODE = 'copy'
$env:PYTHONDONTWRITEBYTECODE = '1'
$logPath = Join-Path $runtimeRoot 'startup.log'
$environmentPath = Join-Path $runtimeRoot 'venv'
$python = Join-Path $environmentPath 'Scripts\python.exe'
$stampPath = Join-Path $runtimeRoot 'dependencies.sha256'

function Invoke-Setup([string]$Executable, [string[]]$Arguments) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $projectRoot -RedirectStandardOutput $logPath -RedirectStandardError ($logPath + '.details') -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Runtime setup failed. See $logPath.details" }
}

try {
    $expected = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'uv.lock') -Algorithm SHA256).Hash
    $ready = (Test-Path -LiteralPath $python) -and (Test-Path -LiteralPath $stampPath) -and ((Get-Content -LiteralPath $stampPath -Raw).Trim() -eq $expected)
    if (-not $ready) {
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        $uvPath = if ($uv) { $uv.Source } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local\bin\uv.exe' }
        if (-not (Test-Path -LiteralPath $uvPath)) { throw 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ and try again.' }
        if (-not (Test-Path -LiteralPath $python)) {
            Invoke-Setup $uvPath @('python', 'install', '3.14')
            Invoke-Setup $uvPath @('python', 'find', '3.14')
            $basePython = [System.IO.File]::ReadAllText($logPath).Trim()
            Invoke-Setup $basePython @('-m', 'venv', '--without-pip', ('"' + $environmentPath + '"'))
        }
        $requirements = Join-Path $runtimeRoot 'requirements.txt'
        Invoke-Setup $uvPath @('export', '--project', ('"' + $projectRoot + '"'), '--frozen', '--no-dev', '--no-emit-project', '--output-file', ('"' + $requirements + '"'))
        Invoke-Setup $uvPath @('pip', 'sync', '--python', ('"' + $python + '"'), ('"' + $requirements + '"'))
        [System.IO.File]::WriteAllText($stampPath, $expected)
    }
    $pythonw = Join-Path $environmentPath 'Scripts\pythonw.exe'
    Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $projectRoot 'start.pyw') + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden
} catch {
    if ($NoDialog) { Write-Error $_.Exception.Message; exit 1 }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Zhaolian Profile') | Out-Null
}
