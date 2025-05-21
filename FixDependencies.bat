@echo off
setlocal enabledelayedexpansion

:: Set environment name and Conda path
set ENV_NAME=realtimetrans
set CONDA_PATH=C:\ProgramData\miniconda3
set CONDA_EXE=%CONDA_PATH%\Scripts\conda.exe

echo =====================================================
echo Real-time Translation Software - Environment Setup
echo =====================================================

:: Check if conda is installed
if not exist "%CONDA_EXE%" (
    echo Conda executable not found at %CONDA_EXE%
    echo Please install Miniconda from: https://docs.conda.io/en/latest/miniconda.html
    echo Run this script again after installation
    pause
    exit /b 1
)

:: Check if the environment already exists by looking at the directory
if exist "%USERPROFILE%\.conda\envs\%ENV_NAME%" (
    echo Environment %ENV_NAME% already exists
    choice /C YN /M "Delete existing environment and recreate? (Y=Yes, N=No)"
    if errorlevel 2 (
        echo Continuing with existing environment
    ) else (
        echo Removing environment %ENV_NAME%...
        "%CONDA_EXE%" env remove -n %ENV_NAME% -y
        echo Creating new environment...
        "%CONDA_EXE%" create -y -n %ENV_NAME% python=3.8
    )
) else (
    echo Environment %ENV_NAME% does not exist
    choice /C YN /M "Create new environment? (Y=Yes, N=No)"
    if errorlevel 2 (
        echo Operation cancelled
        pause
        exit /b 0
    ) else (
        echo Creating new Conda environment: %ENV_NAME%...
        "%CONDA_EXE%" create -y -n %ENV_NAME% python=3.8
    )
)

echo Activating environment %ENV_NAME%...
call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%

echo Environment %ENV_NAME% activated
echo Current Python: 
where python

echo Current pip:
where pip

:: Install dependencies
echo Ready to install dependencies
choice /C YN /M "Install dependencies from requirements.txt? (Y=Yes, N=No)"
if errorlevel 2 (
    echo Skipping dependency installation
) else (
    echo Installing dependencies...
    
    if exist requirements.txt (
        echo Using requirements.txt to install dependencies
        pip install -r requirements.txt
        if %ERRORLEVEL% neq 0 (
            echo Failed to install from requirements.txt, trying individual packages
            choice /C YN /M "Continue with manual installation of each package? (Y=Yes, N=No)"
            if errorlevel 2 (
                echo Installation cancelled
                pause
                exit /b 1
            )
        ) else (
            echo Dependencies installed successfully!
            pause
            exit /b 0
        )
    ) else (
        echo requirements.txt file not found, will install packages manually
    )
    
    echo Installing packages individually...
    
    echo Installing PyQt6...
    pip install PyQt6==6.5.2
    
    echo Installing torch and torchaudio...
    pip install torch==2.0.1 torchaudio==2.0.2
    
    echo Installing whisper...
    pip install openai-whisper==20231117
    
    echo Installing python-dotenv and pydub...
    pip install python-dotenv==1.0.0 pydub==0.25.1
    
    echo Installing PyAudio...
    pip install pyaudio
    if %ERRORLEVEL% neq 0 (
        echo Trying to install PyAudio from conda-forge...
        "%CONDA_EXE%" install -y -c conda-forge pyaudio
        if %ERRORLEVEL% neq 0 (
            echo Warning: PyAudio installation failed. You may need to install it manually.
            echo Please visit: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
            echo Download the appropriate PyAudio wheel file for your system, then install it using pip install.
            pause
        )
    )
    
    echo Installing sounddevice...
    pip install sounddevice==0.4.6
    
    echo Installing googletrans...
    pip install googletrans==4.0.0-rc1
)

echo All operations completed
echo You can now run RunApp.bat to start the application
pause

endlocal 