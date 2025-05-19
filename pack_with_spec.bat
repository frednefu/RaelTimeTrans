@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

echo ========================================
echo Real-time Translation App Packager (Using Spec)
echo ========================================
echo.

:: 检测是否已安装Conda
where conda >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Conda not found. Please install Conda first.
    goto :error
)

:: 查询当前激活的环境
echo Checking for active Conda environment...
for /f "tokens=*" %%a in ('conda info --envs ^| findstr "*"') do (
    set env_line=%%a
)

if not defined env_line (
    echo [WARNING] No active Conda environment detected.
    
    :: 列出可用的环境
    echo Available environments:
    conda env list
    
    :: 提示用户输入环境名称
    set /p env_name=Enter environment name to activate (or press Enter to create a new one): 
    
    if "!env_name!"=="" (
        echo Creating a new environment...
        set env_name=realtimetrans
        conda create -y -n !env_name! python=3.8
    )
    
    :: 激活环境
    echo Activating environment !env_name!...
    call conda activate !env_name!
) else (
    echo Active environment detected: !env_line!
)

:: 检查PyInstaller
echo Checking PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] PyInstaller not found in current environment. Installing...
    pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install PyInstaller.
        goto :error
    )
    echo PyInstaller installed successfully.
)

:: 检查项目依赖
echo Checking project dependencies...
python -c "import whisper, torch, PySide6, googletrans" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Some project dependencies are missing. Installing from requirements.txt...
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install dependencies.
        goto :error
    )
    echo Dependencies installed successfully.
)

echo.
echo Starting packaging process using spec file...
echo.

:: 清理之前的构建
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: 使用spec文件打包
echo Building with PyInstaller using spec file...
pyinstaller RealTimeTranslation.spec --noconfirm
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
pause >nul
exit /b 0 