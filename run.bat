@echo off
chcp 65001 >nul
cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 goto console
start "" pythonw "%~dp0main.py"
exit /b 0

:console
where python >nul 2>nul
if errorlevel 1 (
    echo 没有找到 Python。请先安装 Python 3.9+（安装时勾选 Add python.exe to PATH）。
    pause
    exit /b 1
)
python "%~dp0main.py"
pause
