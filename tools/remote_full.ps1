# 一次连接完成：更新代码、跑单测、极限场景、.bat 入口。
$ErrorActionPreference = 'Continue'
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$zip = Join-Path $env:USERPROFILE 'image-sorter.zip'
$base = 'C:\PhotoSort'

Write-Output '=== HOST ==='
Write-Output "user: $(whoami)  os: $([System.Environment]::OSVersion.VersionString)"

New-Item -ItemType Directory -Force -Path $base | Out-Null
Expand-Archive -Path $zip -DestinationPath $base -Force
Set-Location (Join-Path $base 'image-sorter')

$python = 'C:\Program Files\python\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python -V 2>&1

Write-Output ''
Write-Output '=== UNIT TESTS ==='
& $python -m unittest discover -s tests -t . 2>&1 | Select-Object -Last 6

Write-Output ''
Write-Output '=== STRESS (long path / readonly / 0 byte / cjk / 500 files) ==='
& $python 'tools\stress_windows.py' 2>&1
Write-Output "stress_exit=$LASTEXITCODE"

Write-Output ''
Write-Output '=== BAT ENTRY: verify.bat ==='
cmd /c "echo. | verify.bat" 2>&1 | Select-Object -Last 14
Write-Output "verify_exit=$LASTEXITCODE"

Write-Output ''
Write-Output '=== END ==='
