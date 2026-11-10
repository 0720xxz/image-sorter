@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   图片整理 - 本机自检
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 python。装 Python 3.9 以上，安装时勾选 Add python.exe to PATH。
    pause
    exit /b 1
)

python -V
echo.

echo [1/2] 导入检查
python -c "import imagesorter, imagesorter.exif, imagesorter.gui, main; print('  ok')"
if errorlevel 1 goto fail

echo [2/2] 单元测试
python -m unittest discover -s tests -t .
if errorlevel 1 goto fail

echo.
echo 全部通过。要打包 exe 就跑 build.bat。
pause
exit /b 0

:fail
echo.
echo 有失败项，看上面的输出。
pause
exit /b 1
