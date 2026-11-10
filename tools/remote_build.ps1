# 在 Windows 服务器上打包并冒烟测试。
$ErrorActionPreference = 'Continue'
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$python = 'C:\Program Files\python\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
Set-Location 'C:\PhotoSort\image-sorter'

Write-Output '=== PIP ==='
& $python -m pip --version 2>&1

Write-Output ''
Write-Output '=== INSTALL PYINSTALLER ==='
& $python -m pip install --disable-pip-version-check --quiet pyinstaller 2>&1 | Select-Object -Last 6
& $python -m PyInstaller --version 2>&1

Write-Output ''
Write-Output '=== BUILD ==='
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name ImageSorter main.py 2>&1 | Select-Object -Last 12

Write-Output ''
Write-Output '=== ARTIFACT ==='
if (Test-Path 'dist\ImageSorter.exe') {
    $f = Get-Item 'dist\ImageSorter.exe'
    Write-Output ("name: {0}" -f $f.Name)
    Write-Output ("size: {0:N0} bytes" -f $f.Length)
    Write-Output ("time: {0}" -f $f.LastWriteTime)
} else {
    Write-Output 'NO ARTIFACT'
}

Write-Output ''
Write-Output '=== CLI REAL RUN ==='
Remove-Item -Recurse -Force 'C:\PhotoSort\sample','C:\PhotoSort\out' -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path 'C:\PhotoSort\sample' | Out-Null
& $python -c "import sys; sys.path.insert(0,'tests'); import make_samples; from pathlib import Path; make_samples.make_samples(Path(r'C:\PhotoSort\sample')); print('samples ready')" 2>&1
& $python cli.py --source 'C:\PhotoSort\sample' --target 'C:\PhotoSort\out' --apply --limit 0 2>&1 | Select-Object -Last 10
Write-Output '--- out tree ---'
Get-ChildItem 'C:\PhotoSort\out' -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name
Write-Output '--- undo file ---'
Get-ChildItem 'C:\PhotoSort\out\.imagesorter_undo' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name

Write-Output ''
Write-Output '=== UNDO ==='
& $python cli.py --source 'C:\PhotoSort\sample' --target 'C:\PhotoSort\out' --undo-latest 2>&1 | Select-Object -Last 4
Write-Output '--- source restored ---'
(Get-ChildItem 'C:\PhotoSort\sample' -File -ErrorAction SilentlyContinue).Count

Write-Output ''
Write-Output '=== EXE START ==='
$p = Start-Process 'dist\ImageSorter.exe' -PassThru
Start-Sleep -Seconds 8
if ($p.HasExited) {
    Write-Output ("exe exited early, code={0}" -f $p.ExitCode)
} else {
    Write-Output ("exe alive, pid={0}" -f $p.Id)
    Stop-Process -Id $p.Id -Force
}

Write-Output ''
Write-Output '=== END ==='
