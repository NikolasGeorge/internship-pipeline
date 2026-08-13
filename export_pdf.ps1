<#
  Export staged .docx resumes to PDF using Word itself.

  Job sites offer to convert uploads for you. Their converters reflow layout,
  and this resume's layout is load-bearing: right-aligned tab stops for dates,
  a bullet-separated contact line, and a length that sits close to one page.
  Exporting from Word gives byte-identical layout and lets us read the real
  page count instead of estimating it from character counts.

  Usage:  powershell -File export_pdf.ps1 [folder]
#>
param([string]$Folder = "tailored")

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir  = Join-Path $root $Folder
$docs = Get-ChildItem -Path $dir -Filter *.docx -File | Where-Object { $_.Name -notlike '~$*' }

if (-not $docs) { Write-Output "No .docx files in $dir"; exit 0 }

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$wdStatisticPages = 2
$wdFormatPDF = 17

try {
  foreach ($d in $docs) {
    $doc = $word.Documents.Open($d.FullName, $false, $true)   # read-only
    $pages = $doc.ComputeStatistics($wdStatisticPages)
    $pdf = [IO.Path]::ChangeExtension($d.FullName, ".pdf")
    $doc.SaveAs([ref]$pdf, [ref]$wdFormatPDF)
    $doc.Close($false)
    $flag = if ($pages -gt 1) { "  <-- SPILLS TO PAGE $pages" } else { "" }
    Write-Output ("{0,-62} {1} page(s){2}" -f $d.Name.Replace('Nikolas_George_',''), $pages, $flag)
  }
} finally {
  $word.Quit()
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
