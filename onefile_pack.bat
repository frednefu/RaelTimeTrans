@echo off
chcp 65001 > nul
setlocal

echo ===========================================
echo Packaging Real-time Translation (OneFile)
echo ===========================================
echo.

:: 清理之前的构建
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RealTimeTranslation.spec del RealTimeTranslation.spec

:: 确保Subtitles目录存在
if not exist Subtitles mkdir Subtitles

:: 使用onefile模式构建单个可执行文件
echo Building application in one-file mode...
pyinstaller --name RealTimeTranslation ^
  --onefile ^
  --windowed ^
  --noconfirm ^
  --add-data "LICENSE;." ^
  --add-data "README.md;." ^
  --add-data "Subtitles;Subtitles" ^
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

:: 创建一个版本文件
echo Creating version file...
echo RealTimeTranslation v1.0.0 > dist\version.txt

:: 创建说明文件
echo Copying documentation...
copy README.md dist\ > nul
copy LICENSE dist\ > nul

:: 创建发布目录
echo Creating release package...
if not exist release mkdir release

:: 清理旧的发布包
if exist release\RealTimeTranslation.zip del release\RealTimeTranslation.zip

:: 创建发布包
powershell -Command "Compress-Archive -Path 'dist\*' -DestinationPath 'release\RealTimeTranslation.zip'" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  echo [WARNING] Failed to create ZIP file. The EXE is still available in the dist directory.
) else (
  echo ZIP package created: release\RealTimeTranslation.zip
)

echo.
echo Packaging completed successfully!
echo Application can be found at: dist\RealTimeTranslation.exe
echo.
pause 