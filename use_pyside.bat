@echo off
echo Switching from PyQt6 to PySide6...
call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans

echo Uninstalling PyQt6...
pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-sip

echo Installing PySide6...
pip install PySide6==6.5.0

echo Testing PySide6 installation...
python -c "import PySide6; print('PySide6 imported successfully'); from PySide6.QtWidgets import QApplication; print('QtWidgets imported successfully')"

if %ERRORLEVEL% neq 0 (
    echo PySide6 installation test failed.
    echo Trying older version...
    pip uninstall -y PySide6
    pip install PySide6==6.2.4
    
    echo Testing older version...
    python -c "import PySide6; print('PySide6 imported successfully'); from PySide6.QtWidgets import QApplication; print('QtWidgets imported successfully')"
    
    if %ERRORLEVEL% neq 0 (
        echo PySide6 still not working.
        echo Please make sure Visual C++ Redistributable is installed on your system.
    ) else (
        echo PySide6 6.2.4 is working!
        echo Now we need to update the code to use PySide6 instead of PyQt6
    )
) else (
    echo PySide6 6.5.0 is working!
    echo Now we need to update the code to use PySide6 instead of PyQt6
)

pause 