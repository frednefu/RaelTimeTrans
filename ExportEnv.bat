@echo off
setlocal enabledelayedexpansion

:: Set environment name and Conda path
set ENV_NAME=realtimetrans
set CONDA_PATH=C:\ProgramData\miniconda3
set CONDA_EXE=%CONDA_PATH%\Scripts\conda.exe

echo =====================================================
echo Real-time Translation Software - Export Environment
echo =====================================================

:: Check if conda is installed
if not exist "%CONDA_EXE%" (
    echo Conda executable not found at %CONDA_EXE%
    echo Please install Miniconda: https://docs.conda.io/en/latest/miniconda.html
    echo Run FixDependencies.bat first after installation
    pause
    exit /b 1
)

:: Check if the environment exists
if not exist "%USERPROFILE%\.conda\envs\%ENV_NAME%" (
    echo Environment %ENV_NAME% does not exist!
    choice /C YN /M "Run FixDependencies.bat to create environment? (Y=Yes, N=No)"
    if errorlevel 2 (
        echo Please run FixDependencies.bat first to create the environment
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

:: Choose export format
echo Please select export format:
echo 1. Export as environment.yml (recommended for conda environment recreation)
echo 2. Export as requirements.txt (for pip installation)
echo 3. Export both formats
choice /C 123 /M "Select export format (1-3)"

set EXPORT_CHOICE=%ERRORLEVEL%

if %EXPORT_CHOICE% equ 1 (
    :: Export conda environment
    echo Exporting environment to environment.yml...
    "%CONDA_EXE%" env export -n %ENV_NAME% > environment.yml
    if %ERRORLEVEL% neq 0 (
        echo Failed to export environment!
        pause
        exit /b 1
    )
    echo Environment configuration exported to environment.yml
)

if %EXPORT_CHOICE% equ 2 (
    :: Export pip dependencies
    echo Exporting pip dependencies to requirements.txt...
    call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%
    call pip freeze > requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo Failed to export dependencies!
        pause
        exit /b 1
    )
    echo Pip dependencies exported to requirements.txt
)

if %EXPORT_CHOICE% equ 3 (
    :: Export conda environment
    echo Exporting environment to environment.yml...
    "%CONDA_EXE%" env export -n %ENV_NAME% > environment.yml
    if %ERRORLEVEL% neq 0 (
        echo Failed to export environment!
        pause
        exit /b 1
    )
    
    :: Export pip dependencies
    echo Exporting pip dependencies to requirements.txt...
    call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%
    call pip freeze > requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo Failed to export dependencies!
        pause
        exit /b 1
    )
    
    echo Environment configuration exported to environment.yml
    echo Pip dependencies exported to requirements.txt
)

echo Complete!
echo You can use these files to recreate the environment on another machine:
echo - Using conda: conda env create -f environment.yml
echo - Using pip: pip install -r requirements.txt

pause
endlocal 