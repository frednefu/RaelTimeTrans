@echo off
call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans
echo Running application with debug output...
python -v main.py 2> error.log
echo Any errors will be saved to error.log
pause 