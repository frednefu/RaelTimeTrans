@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: Set default values
set DEFAULT_ENV_NAME=realtimetrans
set CONDA_PATH=C:\ProgramData\miniconda3
set CONDA_EXE=%CONDA_PATH%\Scripts\conda.exe
set ENV_FILE=conda_env.txt

echo =====================================================
echo        REALTIME TRANSLATION INSTALLER
echo =====================================================
echo.

:: Check if Conda exists
echo Checking Conda installation...
if not exist "%CONDA_EXE%" (
    echo Conda not found at default location, trying alternatives...
    if exist "C:\ProgramData\Anaconda3\Scripts\conda.exe" (
        set CONDA_PATH=C:\ProgramData\Anaconda3
        set CONDA_EXE=!CONDA_PATH!\Scripts\conda.exe
    ) else if exist "%USERPROFILE%\Anaconda3\Scripts\conda.exe" (
        set CONDA_PATH=%USERPROFILE%\Anaconda3
        set CONDA_EXE=!CONDA_PATH!\Scripts\conda.exe
    ) else if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" (
        set CONDA_PATH=%USERPROFILE%\miniconda3
        set CONDA_EXE=!CONDA_PATH!\Scripts\conda.exe
    ) else (
        echo Conda not found. Please install Miniconda: https://docs.conda.io/en/latest/miniconda.html
        pause
        exit /b 1
    )
)

echo Using Conda: %CONDA_EXE%
echo.

:: Select environment name
set ENV_NAME=%DEFAULT_ENV_NAME%
if exist "%ENV_FILE%" (
    for /f "usebackq delims=" %%a in ("%ENV_FILE%") do (
        set CURRENT_ENV=%%a
    )
    echo Current environment name: !CURRENT_ENV!
    echo.
)

echo Please select Conda environment:
echo [1] Use default name (%DEFAULT_ENV_NAME%)
echo [2] Enter custom name
echo.
set ENV_CHOICE=
set /p ENV_CHOICE=Select option [1-2]: 

if "%ENV_CHOICE%"=="2" (
    set CUSTOM_ENV=
    set /p CUSTOM_ENV=Enter environment name: 
    if not "!CUSTOM_ENV!"=="" (
        set ENV_NAME=!CUSTOM_ENV!
    )
)

echo Selected environment name: %ENV_NAME%

:: Save environment name to file
echo %ENV_NAME%> "%ENV_FILE%"
echo Environment name saved to %ENV_FILE%
echo.

:: Check if environment exists
echo Checking conda environment...
call "%CONDA_EXE%" info --envs > conda_tmp.txt

findstr /C:"%ENV_NAME%" conda_tmp.txt > nul
if %ERRORLEVEL% EQU 0 (
    echo Environment %ENV_NAME% already exists
    choice /C YN /M "Delete existing environment and recreate? (Y=Yes, N=No)"
    if errorlevel 2 (
        echo Continuing with existing environment
    ) else (
        echo Removing environment %ENV_NAME%...
        call "%CONDA_EXE%" env remove -n %ENV_NAME% -y
        echo Creating new environment...
        call "%CONDA_EXE%" create -y -n %ENV_NAME% python=3.8
    )
) else (
    echo Environment %ENV_NAME% does not exist
    echo Creating new Conda environment: %ENV_NAME%...
    call "%CONDA_EXE%" create -y -n %ENV_NAME% python=3.8
)
del conda_tmp.txt

echo Activating environment %ENV_NAME%...
call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%

echo Environment %ENV_NAME% activated
echo Current Python version: 
python --version
echo Current pip location:
where pip
echo.

:: Check for NVIDIA GPU
echo Checking NVIDIA GPU...
nvidia-smi >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo No NVIDIA GPU detected.
    echo Will install CPU version of dependencies.
    set GPU_AVAILABLE=0
) else (
    echo NVIDIA GPU detected!
    echo Will install GPU accelerated version.
    set GPU_AVAILABLE=1
)
echo.

:: Install dependencies
echo Please select installation options:
echo [1] Full installation (all components)
echo [2] Basic dependencies only
echo [3] FFMPEG only
echo [4] GPU support only
echo.
set INSTALL_CHOICE=
set /p INSTALL_CHOICE=Select option [1-4]: 

if "%INSTALL_CHOICE%"=="3" goto install_ffmpeg
if "%INSTALL_CHOICE%"=="4" goto install_gpu

:install_deps
echo.
echo =====================================================
echo                INSTALLING BASIC DEPENDENCIES
echo =====================================================
echo.

if exist requirements.txt (
    echo Installing dependencies from requirements.txt...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo Failed to install from requirements.txt, will try individual packages
    ) else (
        echo Basic dependencies installed successfully!
        goto check_ffmpeg
    )
)

echo Installing required packages...

echo Installing PySide6...
pip install PySide6==6.5.0

:: Always install CUDA-enabled PyTorch if GPU is available
if "%GPU_AVAILABLE%"=="1" (
    echo Installing GPU version of PyTorch with CUDA 11.8...
    pip uninstall -y torch torchvision torchaudio
    pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2+cu118 --index-url https://download.pytorch.org/whl/cu118
    
    :: Verify CUDA installation
    python -c "import torch; print('CUDA Enabled:', torch.cuda.is_available()); print('CUDA Version:', torch.version.cuda if torch.cuda.is_available() else 'N/A')"
) else (
    echo Installing CPU version of PyTorch...
    pip install torch==2.0.1 torchaudio==2.0.2
)

echo Installing Whisper...
pip install openai-whisper==20231117

echo Installing python-dotenv and pydub...
pip install python-dotenv==1.0.0 pydub==0.25.1

echo Installing PyAudio...
pip install pyaudio
if %ERRORLEVEL% neq 0 (
    echo Trying to install PyAudio from conda-forge...
    call "%CONDA_EXE%" install -y -c conda-forge pyaudio
    if %ERRORLEVEL% neq 0 (
        echo Warning: PyAudio installation failed. You may need to install it manually.
        echo Please visit: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
        echo Download a wheel file for your system and install with pip.
    )
)

echo Installing sounddevice...
pip install sounddevice==0.4.6

echo Installing googletrans...
pip install googletrans==4.0.0-rc1

echo Basic dependencies installation complete!
echo.

:check_ffmpeg
if "%INSTALL_CHOICE%"=="2" goto verify_gpu
if "%INSTALL_CHOICE%"=="3" goto install_ffmpeg
if "%INSTALL_CHOICE%"=="4" goto install_gpu

:install_ffmpeg
if not "%INSTALL_CHOICE%"=="3" (
    echo.
    echo =====================================================
    echo                  INSTALLING FFMPEG
    echo =====================================================
    echo.
)

echo Checking FFMPEG...
where ffmpeg >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo FFMPEG not found, installing...
    
    echo Downloading FFMPEG...
    powershell -Command "& {try { Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile 'ffmpeg.zip' } catch { Write-Host 'Download failed, check your network connection'; exit 1 }}"
    
    if not exist ffmpeg.zip (
        echo FFMPEG download failed, skipping installation
        goto check_gpu
    )
    
    echo Extracting FFMPEG...
    powershell -Command "& {try { Expand-Archive -Path 'ffmpeg.zip' -DestinationPath '.' -Force } catch { Write-Host 'Extraction failed'; exit 1 }}"
    
    if not exist "ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe" (
        echo FFMPEG extraction failed, skipping installation
        del ffmpeg.zip
        goto check_gpu
    )
    
    echo Moving FFMPEG to temp location...
    mkdir ffmpeg_temp 2>nul
    copy /Y "ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe" "ffmpeg_temp\ffmpeg.exe" >nul
    
    :: Try to add ffmpeg to environment variables
    echo Configuring FFMPEG...
    pip install ffmpeg-python
    
    :: Cleanup
    echo Cleaning up temporary files...
    rmdir /S /Q "ffmpeg-master-latest-win64-gpl" 2>nul
    del ffmpeg.zip 2>nul
    
    echo FFMPEG installation complete!
) else (
    echo FFMPEG is already installed!
)
echo.

:check_gpu
if "%INSTALL_CHOICE%"=="3" goto verify_gpu
if "%GPU_AVAILABLE%"=="0" (
    echo No NVIDIA GPU detected, skipping GPU support installation
    goto verify_gpu
)

:install_gpu
if not "%INSTALL_CHOICE%"=="4" (
    echo.
    echo =====================================================
    echo                INSTALLING GPU SUPPORT
    echo =====================================================
    echo.
)

echo Configuring GPU support...

:: Always reinstall PyTorch with CUDA support
echo Installing GPU version of PyTorch with CUDA 11.8...
pip uninstall -y torch torchvision torchaudio
pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2+cu118 --index-url https://download.pytorch.org/whl/cu118

:: Install CUDA extensions for Whisper
echo Installing CUDA extensions for Whisper...
pip install numba
pip install cupy-cuda11x

:: Configure settings file
if exist "settings.json" (
    echo Updating settings file to enable GPU...
    copy "settings.json" "settings_backup.json" >nul
    python -c "import json; f=open('settings.json', 'r', encoding='utf-8'); data=json.load(f); f.close(); data['use_gpu']=True; data['device']='cuda'; f=open('settings.json', 'w', encoding='utf-8'); json.dump(data, f, ensure_ascii=False, indent=4); f.close(); print('Settings updated, GPU enabled')"
)

:verify_gpu
echo.
echo =====================================================
echo                VERIFYING GPU SUPPORT
echo =====================================================
echo.

echo Checking GPU support...
python check_gpu.py

echo.
if "%GPU_AVAILABLE%"=="1" (
    echo Testing CUDA acceleration...
    python -c "import torch; print('PyTorch version:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('CUDA version:', torch.version.cuda if torch.cuda.is_available() else 'Not available'); print('GPU device count:', torch.cuda.device_count()); print('GPU device name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU')"
)

:end
echo.
echo =====================================================
echo                INSTALLATION COMPLETE!
echo =====================================================
echo.
echo Conda environment name: %ENV_NAME% (saved to %ENV_FILE%)
echo.
echo You can now run the application.
echo To start the application, use: start.bat
echo.
pause

endlocal 