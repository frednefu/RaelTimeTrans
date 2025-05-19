@echo off
call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans
python -c "import sys; print('Python version:', sys.version)"
python -c "import PyQt6; print('PyQt6 imported successfully'); from PyQt6.QtWidgets import QApplication; print('QtWidgets imported successfully')"
pause 