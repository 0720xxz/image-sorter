@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   图片整理工具 - 打包成 exe
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 python 命令。
    echo 请先安装 Python 3.9 或更高版本，安装时勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

echo [1/3] 安装打包工具 PyInstaller ...
python -m pip install --upgrade pip >nul
python -m pip install pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败，检查网络或换用国内镜像：
    echo        python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    pause
    exit /b 1
)

echo.
echo [2/3] 打包中（第一次会比较慢）...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name ImageSorter ^
    --hidden-import imagesorter.gui ^
    --hidden-import imagesorter.exif ^
    --hidden-import imagesorter.scanner ^
    --hidden-import imagesorter.organizer ^
    --hidden-import cli ^
    main.py
if errorlevel 1 (
    echo [错误] 打包失败，请把上面的报错发出来。
    pause
    exit /b 1
)

echo.
echo [3/3] 完成。
echo exe 位置: %~dp0dist\ImageSorter.exe
echo 这个 exe 可以单独复制到任意电脑运行，不需要安装 Python。
echo.
pause
