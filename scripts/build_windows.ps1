$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

& uv sync --extra dev --extra build
if ($LASTEXITCODE -ne 0) { throw 'Could not install the desktop build dependencies.' }

$buildId = Get-Date -Format 'yyyyMMdd-HHmmss'
$buildDist = Join-Path $projectRoot "dist\releases\$buildId"
New-Item -ItemType Directory -Path $buildDist -Force | Out-Null
& '.venv\Scripts\pyinstaller.exe' --noconfirm --clean --distpath $buildDist --workpath 'build\pyinstaller' 'academic-profile.spec'
if ($LASTEXITCODE -ne 0) { throw 'The Windows desktop build failed.' }

$executable = Join-Path $buildDist 'AcademicProfile-0.1.0\AcademicProfile-0.1.0.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw "Build output not found: $executable" }

$desktopPath = [Environment]::GetFolderPath('Desktop')
$productName = -join ([char[]]@(0x662D, 0x6FC2, 0x5B66, 0x672F, 0x6863, 0x6848))
$productDescription = -join ([char[]]@(0x6253, 0x5F00, 0x672C, 0x673A, 0x662D, 0x6FC2, 0x5B66, 0x672F, 0x6863, 0x6848, 0x5E73, 0x53F0))
$shortcutPath = Join-Path $desktopPath ($productName + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $executable
$shortcut.Arguments = "--home `"$projectRoot`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$executable,0"
$shortcut.Description = $productDescription
$shortcut.Save()

Write-Output "Desktop shortcut created: $shortcutPath"
Write-Output "Application folder: $(Split-Path -Parent $executable)"
