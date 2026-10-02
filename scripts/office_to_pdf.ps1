param(
  [Parameter(Mandatory = $true)][string]$InputPath,
  [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$extension = [System.IO.Path]::GetExtension($InputPath).ToLowerInvariant()
$application = $null
$document = $null

try {
  switch ($extension) {
    '.docx' {
      $application = New-Object -ComObject Word.Application
      $application.Visible = $false
      $application.DisplayAlerts = 0
      $application.AutomationSecurity = 3
      $document = $application.Documents.Open($InputPath, $false, $true, $false)
      $document.ExportAsFixedFormat($OutputPath, 17)
    }
    '.xlsx' {
      $application = New-Object -ComObject Excel.Application
      $application.Visible = $false
      $application.DisplayAlerts = $false
      $application.AskToUpdateLinks = $false
      $application.AutomationSecurity = 3
      $document = $application.Workbooks.Open($InputPath, 0, $true)
      $document.ExportAsFixedFormat(0, $OutputPath)
    }
    '.pptx' {
      $application = New-Object -ComObject PowerPoint.Application
      $application.DisplayAlerts = 1
      $document = $application.Presentations.Open($InputPath, $true, $false, $false)
      $document.SaveAs($OutputPath, 32)
    }
    default { throw 'Unsupported Office file extension.' }
  }
}
finally {
  if ($document -ne $null) {
    try {
      if ($extension -eq '.docx') { $document.Close(0) }
      elseif ($extension -eq '.xlsx') { $document.Close($false) }
      elseif ($extension -eq '.pptx') { $document.Close() }
    } catch { }
  }
  if ($application -ne $null) {
    try {
      if ($extension -eq '.docx') { $application.Quit() }
      elseif ($extension -eq '.xlsx') { $application.Quit() }
      elseif ($extension -eq '.pptx') { $application.Quit() }
    } catch { }
    try { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($application) } catch { }
  }
}
