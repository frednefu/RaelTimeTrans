@echo off
chcp 65001 > nul
setlocal

:: 日志文件
set LOG_FILE=build_log.txt
echo Build started at %date% %time% > %LOG_FILE%

echo ========================================
echo Simple Real-time Translation App Builder
echo ========================================
echo.

:: 清理旧文件
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist RealTimeTranslation.spec del RealTimeTranslation.spec

:: 创建必要的目录
if not exist Subtitles mkdir Subtitles

:: 找出Python路径和DLL位置
echo Finding Python path...
for /f "tokens=*" %%p in ('where python') do (
  set PYTHON_PATH=%%~dp
  goto :found_python
)

:found_python
echo Python found at: %PYTHON_PATH%
set DLL_PATH=%PYTHON_PATH%python38.dll

:: 检查Python DLL
if not exist "%DLL_PATH%" (
  echo Warning: python38.dll not found at %DLL_PATH%
  set DLL_PATH=
  echo Looking for alternative Python DLL locations...
  
  if exist "%PYTHON_PATH%DLLs\python38.dll" (
    set DLL_PATH=%PYTHON_PATH%DLLs\python38.dll
    echo Found in DLLs subfolder
  )
  
  if "%DLL_PATH%"=="" (
    echo Warning: python38.dll not found - package may not work correctly.
    echo This error will be logged to build_log.txt
    echo ERROR: python38.dll not found >> %LOG_FILE%
  )
)

:: 开始打包
echo.
echo Starting PyInstaller packaging...
echo.

:: 构建PyInstaller命令
set PYINSTALLER_CMD=pyinstaller --name RealTimeTranslation --onefile --windowed --noconfirm

:: 添加数据文件
set PYINSTALLER_CMD=%PYINSTALLER_CMD% --add-data "LICENSE;." --add-data "README.md;." --add-data "Subtitles;Subtitles"

:: 如果找到DLL，添加它
if not "%DLL_PATH%"=="" (
  set PYINSTALLER_CMD=%PYINSTALLER_CMD% --add-binary "%DLL_PATH%;."
  echo Including Python DLL from: %DLL_PATH%
)

:: 添加隐藏导入
set PYINSTALLER_CMD=%PYINSTALLER_CMD% --hidden-import=whisper --hidden-import=whisper.tokenizer --hidden-import=torch --hidden-import=numpy --hidden-import=PySide6 --hidden-import=googletrans

:: 添加主脚本
set PYINSTALLER_CMD=%PYINSTALLER_CMD% main.py

:: 执行命令
echo Executing: %PYINSTALLER_CMD%
%PYINSTALLER_CMD% >> %LOG_FILE% 2>&1

if %ERRORLEVEL% NEQ 0 (
  echo.
  echo [ERROR] Packaging failed. See %LOG_FILE% for details.
  echo Complete error log has been saved to %LOG_FILE%
  echo.
  goto :exit
)

echo.
echo Packaging completed successfully!
echo Application can be found at: dist\RealTimeTranslation.exe
echo.

:: 添加额外文件
echo Adding version file...
echo RealTimeTranslation v1.0.0 > dist\version.txt

:exit
echo.
echo Press any key to exit...
pause > nul
exit /b 