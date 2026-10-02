$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

& uv sync --extra dev --extra build
if ($LASTEXITCODE -ne 0) { throw 'Could not install the desktop build dependencies.' }

& '.venv\Scripts\pyinstaller.exe' --noconfirm --clean --distpath 'dist' --workpath 'build\pyinstaller' 'academic-profile.spec'
if ($LASTEXITCODE -ne 0) { throw 'The Windows desktop build failed.' }

$executable = Join-Path $projectRoot 'dist\AcademicProfile\AcademicProfile.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw "Build output not found: $executable" }

$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Academic Profile.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $executable
$shortcut.Arguments = "--home `"$projectRoot`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = '打开本机学术履历平台'
$shortcut.Save()

Write-Output "Desktop shortcut created: $shortcutPath"
Write-Output "Application folder: $(Split-Path -Parent $executable)"
