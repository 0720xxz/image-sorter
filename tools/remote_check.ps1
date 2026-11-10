# 在 Windows 服务器上跑一遍自检：解压、导入检查、单元测试。
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File remote_check.ps1
$ErrorActionPreference = 'Continue'
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$home_dir = $env:USERPROFILE
$base = 'C:\PhotoSort'
$zip = Join-Path $home_dir 'image-sorter.zip'

Write-Output "=== HOST ==="
Write-Output "user: $(whoami)"
Write-Output "os:   $([System.Environment]::OSVersion.VersionString)"

if (-not (Test-Path $zip)) {
    Write-Output "ZIP MISSING: $zip"
    exit 2
}

New-Item -ItemType Directory -Force -Path $base | Out-Null
Expand-Archive -Path $zip -DestinationPath $base -Force
Set-Location (Join-Path $base 'image-sorter')
Write-Output "cwd:  $(Get-Location)"

$python = 'C:\Program Files\python\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

Write-Output ''
Write-Output '=== PYTHON ==='
& $python -V 2>&1

Write-Output ''
Write-Output '=== IMPORT ==='
& $python -c "import imagesorter, imagesorter.exif, imagesorter.gui, imagesorter.dates, imagesorter.scanner, imagesorter.organizer, main; print('import ok')" 2>&1

Write-Output ''
Write-Output '=== TESTS ==='
& $python -m unittest discover -s tests -t . 2>&1

Write-Output ''
Write-Output '=== EXIT ==='
Write-Output "code=$LASTEXITCODE"
