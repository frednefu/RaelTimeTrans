@echo off
call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans
echo Running application with trace...
python -m trace --trace main.py > trace.log 2>&1
echo Trace output saved to trace.log
pause 