@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: 设置默认值
set DEFAULT_ENV_NAME=realtimetrans
set CONDA_PATH=C:\ProgramData\miniconda3
set CONDA_EXE=%CONDA_PATH%\Scripts\conda.exe
set ENV_FILE=conda_env.txt

echo =====================================================
echo        实时翻译应用程序 - 启动工具
echo =====================================================
echo.

:: 检查环境文件
if exist "%ENV_FILE%" (
    set /p ENV_NAME=<"%ENV_FILE%"
    echo 使用环境: %ENV_NAME%
) else (
    echo 未找到环境配置文件，使用默认环境: %DEFAULT_ENV_NAME%
    set ENV_NAME=%DEFAULT_ENV_NAME%
)

:: 检查Conda安装
if not exist "%CONDA_EXE%" (
    echo 未找到Conda，尝试其他Conda位置...
    
    if exist "C:\ProgramData\Anaconda3\Scripts\conda.exe" (
        set CONDA_PATH=C:\ProgramData\Anaconda3
        set CONDA_EXE=C:\ProgramData\Anaconda3\Scripts\conda.exe
        echo 找到Conda: %CONDA_EXE%
    ) else (
        echo 未找到Conda安装。
        echo 请先运行install.bat安装所需环境。
        pause
        exit /b 1
    )
)

:: 检查环境是否存在
if not exist "%USERPROFILE%\.conda\envs\%ENV_NAME%" (
    echo 环境 %ENV_NAME% 不存在！
    echo 请先运行install.bat创建环境。
    pause
    exit /b 1
)

echo 正在激活环境 %ENV_NAME%...
call "%CONDA_PATH%\Scripts\activate.bat" %ENV_NAME%

:: 检查必要文件
if not exist "main.py" (
    echo 错误: 未找到main.py文件！
    echo 请确保您在正确的目录中运行此脚本。
    pause
    exit /b 1
)

:: 创建必要目录
if not exist "Subtitles" mkdir Subtitles
if not exist "audio" mkdir audio

:: 显示启动选项
echo.
echo 请选择启动选项:
echo [1] 正常启动
echo [2] 调试模式启动
echo [3] 退出
echo.
set /p START_CHOICE=请选择选项 [1-3]: 

if "%START_CHOICE%"=="2" goto debug_mode
if "%START_CHOICE%"=="3" goto end

:: 正常启动
echo.
echo 正在启动实时翻译应用程序...
python main.py
goto end

:debug_mode
echo.
echo 正在调试模式下启动应用程序...
python main.py --debug
goto end

:end
echo.
echo 程序已退出。


endlocal 