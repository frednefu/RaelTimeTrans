@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

echo ========================================
echo Real-time Translation App Packager
echo ========================================
echo.

:: 检查Python环境
echo Checking Python environment...
python --version > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not detected. Please ensure Python is installed and added to your PATH.
    goto :error
)

:: 检查是否安装了PyInstaller
echo Checking PyInstaller...
python -c "import PyInstaller" > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] PyInstaller not detected. Attempting to install...
    pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install PyInstaller.
        goto :error
    )
    echo PyInstaller installed successfully.
)

echo.
echo Starting packaging process...
echo.

:: 执行打包脚本
python build.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] An error occurred during the packaging process.
    goto :error
)

echo.
echo Packaging process completed!
echo.
echo You can find the executable in the dist\RealTimeTranslation\ directory.
echo.
goto :end

:error
echo.
echo Packaging process failed. Please check the error messages above.
exit /b 1

:end
echo Press any key to exit...
pause > nul
exit /b 0 