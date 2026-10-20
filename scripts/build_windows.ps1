param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& uv sync --frozen --extra dev --extra build
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not $SkipTests) {
    & uv run pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed. Packaging stopped.' }
}
& uv run python scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'Third-party notice collection failed.' }
$buildDist = Join-Path $projectRoot 'dist\public-0.3.0'
if (Test-Path -LiteralPath $buildDist) { throw 'Release directory already exists. Use a new empty directory.' }
& uv run pyinstaller --noconfirm --clean --distpath $buildDist --workpath 'build\pyinstaller' academic-profile.spec
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
$appFolder = Join-Path $buildDist 'ZhaolianProfile-0.3.0'
$guideName = -join ([char[]]@(0x5F00, 0x59CB, 0x4F7F, 0x7528))
Copy-Item -LiteralPath (Join-Path $projectRoot ('docs\' + $guideName + '.txt')) -Destination $appFolder
Copy-Item -LiteralPath (Join-Path $projectRoot 'THIRD_PARTY_NOTICES.md') -Destination $appFolder
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\third-party-licenses') -Destination $appFolder -Recurse
$archive = Join-Path $buildDist 'ZhaolianProfile-0.3.0-windows-x64.zip'
Compress-Archive -LiteralPath $appFolder -DestinationPath $archive
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText((Join-Path $buildDist 'SHA256SUMS.txt'), "$hash  ZhaolianProfile-0.3.0-windows-x64.zip`n", [System.Text.UTF8Encoding]::new($false))
Write-Output "Release archive: $archive"
Write-Output 'The desktop shortcut has not been changed.'
