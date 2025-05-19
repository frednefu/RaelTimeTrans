@echo off
chcp 65001 > nul
setlocal

:: 清理之前的构建
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RealTimeTranslation.spec del RealTimeTranslation.spec

:: 确保Subtitles目录存在
if not exist Subtitles mkdir Subtitles

:: 获取Python安装目录，用于添加DLL文件
for /f "tokens=*" %%a in ('where python') do (
  set python_path=%%~dpa
)

echo Using Python from: %python_path%

:: 使用完整命令一步构建可执行文件
echo Starting PyInstaller packaging...
pyinstaller --name RealTimeTranslation ^
  --windowed ^
  --noconfirm ^
  --add-data "LICENSE;." ^
  --add-data "README.md;." ^
  --add-data "Subtitles;Subtitles" ^
  --add-binary "%python_path%python38.dll;." ^
  --hidden-import=whisper ^
  --hidden-import=whisper.tokenizer ^
  --hidden-import=torch ^
  --hidden-import=numpy ^
  --hidden-import=PySide6 ^
  --hidden-import=googletrans ^
  main.py

if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Packaging failed! Check the error messages above.
  pause
  exit /b 1
)

echo.
echo Packaging completed successfully!
echo Application can be found at: dist\RealTimeTranslation\RealTimeTranslation.exe
echo.
pause 