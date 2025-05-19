@echo off
call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans
python check_gpu.py
pause 