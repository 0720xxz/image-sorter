# 验证 .bat 入口脚本能在 cmd.exe 下真正跑起来，再跑极限场景。
$ErrorActionPreference = 'Continue'
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$project = 'C:\PhotoSort\image-sorter'
$python = 'C:\Program Files\python\python.exe'
Set-Location $project

Write-Output '=== BAT: verify.bat ==='
# verify.bat 结尾有 pause，用 echo 顶掉，避免挂住
cmd /c "echo. | verify.bat" 2>&1 | Select-Object -Last 25
Write-Output "verify_exit=$LASTEXITCODE"

Write-Output ''
Write-Output '=== BAT: run.bat ==='
cmd /c "run.bat" 2>&1 | Select-Object -Last 8
Write-Output "run_exit=$LASTEXITCODE"
Start-Sleep -Seconds 6
$procs = Get-Process pythonw -ErrorAction SilentlyContinue
if ($procs) {
    Write-Output ("pythonw running: {0}" -f (($procs | Select-Object -ExpandProperty Id) -join ','))
    $procs | Stop-Process -Force
} else {
    Write-Output 'pythonw not running'
}

Write-Output ''
Write-Output '=== STRESS ==='
& $python 'tools\stress_windows.py' 2>&1
Write-Output "stress_exit=$LASTEXITCODE"

Write-Output ''
Write-Output '=== END ==='
