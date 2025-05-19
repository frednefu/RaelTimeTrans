@echo off
call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans
echo Running application directly...
python main.py 2> direct_error.log
echo Error output saved to direct_error.log
@REM pause 