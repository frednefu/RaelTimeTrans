@echo off
echo Fixing PyQt6 installation...
call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans

echo Uninstalling PyQt6...
pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-sip

echo Installing Visual C++ Redistributable if missing...
echo Please manually install the Visual C++ Redistributable if prompted.
start https://aka.ms/vs/17/release/vc_redist.x64.exe

echo Installing PyQt6 with latest compatible version...
pip install PyQt6==6.4.0

echo Testing PyQt6 installation...
python -c "import PyQt6; print('PyQt6 imported successfully'); from PyQt6.QtWidgets import QApplication; print('QtWidgets imported successfully')"

if %ERRORLEVEL% neq 0 (
    echo PyQt6 installation test failed.
    echo Trying alternative version...
    pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-sip
    pip install PyQt6==6.2.0
    
    echo Testing alternative version...
    python -c "import PyQt6; print('PyQt6 imported successfully'); from PyQt6.QtWidgets import QApplication; print('QtWidgets imported successfully')"
    
    if %ERRORLEVEL% neq 0 (
        echo PyQt6 still not working.
        echo Please make sure Visual C++ Redistributable is installed on your system.
    ) else (
        echo PyQt6 6.2.0 is working!
    )
) else (
    echo PyQt6 6.4.0 is working!
)

pause 