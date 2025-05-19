@echo off
setlocal enabledelayedexpansion

:: Set environment name and path
set ENV_NAME=realtimetrans
set CONDA_PATH=C:\ProgramData\miniconda3
set CONDA_EXE=%CONDA_PATH%\Scripts\conda.exe

echo =====================================================
echo Real-time Translation Software - Launcher
echo =====================================================

:: Check if conda exists
if not exist "%CONDA_EXE%" (
    echo Conda executable not found at %CONDA_EXE%
    echo Please install Miniconda and run FixDependencies.bat first
    pause
    exit /b 1
)

:: Check if the environment exists
if not exist "%USERPROFILE%\.conda\envs\%ENV_NAME%" (
    echo Environment %ENV_NAME% does not exist
    choice /C YN /M "Run FixDependencies.bat to create environment now? (Y=Yes, N=No)"
    if errorlevel 2 (
        echo Please run FixDependencies.bat first to create the required environment
        pause
        exit /b 1
    ) else (
        echo Running FixDependencies.bat...
        call FixDependencies.bat
        
        :: Check again if environment was created
        if not exist "%USERPROFILE%\.conda\envs\%ENV_NAME%" (
            echo Environment creation failed
            pause
            exit /b 1
        )
    )
)

:: Activate environment
echo Activating environment %ENV_NAME%...
call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%

:: Check if main program file exists
if not exist "main.py" (
    echo Error: main.py file not found
    echo Please make sure you are running this script from the correct directory
    pause
    exit /b 1
)

:: Run application
echo Starting Real-time Translation Software...
python main.py

:: Check program exit status
if %ERRORLEVEL% neq 0 (
    echo Program exited abnormally, error code: %ERRORLEVEL%
    echo If this is a dependency issue, please run FixDependencies.bat
    
    choice /C YN /M "View detailed error information? (Y=Yes, N=No)"
    if errorlevel 1 (
        if errorlevel 2 (
            echo Exiting program
        ) else (
            echo Running in debug mode...
            python -v main.py
            pause
        )
    )
) else (
    echo Program exited normally
)

pause
endlocal 