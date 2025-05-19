@echo off

echo ========================================
echo Minimal PyInstaller Build Script
echo ========================================
echo.

echo Cleaning old build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RealTimeTranslation.spec del RealTimeTranslation.spec

echo Creating output directory...
if not exist Subtitles mkdir Subtitles

echo.
echo Building application (one-file mode)...
echo.

pyinstaller --name RealTimeTranslation --onefile --windowed --noconfirm --add-data "LICENSE;." --add-data "README.md;." --add-data "Subtitles;Subtitles" --hidden-import=whisper --hidden-import=whisper.tokenizer --hidden-import=torch --hidden-import=numpy --hidden-import=PySide6 --hidden-import=googletrans main.py

if errorlevel 1 (
  echo.
  echo Error: The PyInstaller command failed.
  pause
  exit /b 1
)

echo.
echo Build completed successfully!
echo The executable is available at dist\RealTimeTranslation.exe
echo.

echo Creating version file...
echo v1.0.0 > dist\version.txt

echo.
echo Press any key to exit...
pause > nul 