@echo off
setlocal enabledelayedexpansion

:: 设置环境名称和Python版本
set ENV_NAME=realtimetrans
set PY_VERSION=3.8

echo =====================================================
echo 实时翻译软件 - 环境准备
echo =====================================================

:: 检查conda是否已安装
call conda --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Conda未安装或未正确配置。
    echo 请按照以下步骤安装并配置Conda:
    echo 1. 下载Miniconda: https://docs.conda.io/en/latest/miniconda.html
    echo 2. 安装Miniconda (选择添加到PATH选项)
    echo 3. 重新启动计算机
    echo 4. 再次运行此脚本
    pause
    exit /b 1
)

echo Conda已安装，正在检查环境...

:: 检查环境是否存在
call conda env list | findstr /C:"%ENV_NAME%" >nul
if %ERRORLEVEL% neq 0 (
    echo 创建新的Conda环境: %ENV_NAME%...
    call conda create -y -n %ENV_NAME% python=%PY_VERSION%
    if %ERRORLEVEL% neq 0 (
        echo 创建环境失败！
        pause
        exit /b 1
    )
    
    echo 环境创建成功，正在安装依赖...
    :: 激活环境并安装依赖
    call conda activate %ENV_NAME%
    
    :: 安装PyPI包依赖
    echo 安装依赖包...
    call pip install torch==2.0.1 torchaudio==2.0.2
    call pip install openai-whisper==20231117
    call pip install python-dotenv==1.0.0 pydub==0.25.1
    
    :: 尝试从conda安装pyaudio（可能更容易安装）
    call conda install -y -c conda-forge pyaudio
    if %ERRORLEVEL% neq 0 (
        echo 尝试从PyPI安装PyAudio...
        call pip install pyaudio
        if %ERRORLEVEL% neq 0 (
            echo 警告: PyAudio安装失败。您可能需要手动安装。
            echo 请访问: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
            echo 下载适合您系统的PyAudio wheel文件，然后使用pip install命令安装。
            pause
        )
    )
    
    :: 安装其他依赖
    call pip install sounddevice==0.4.6 PyQt6==6.5.2 googletrans==4.0.0-rc1
    
    :: 如果需要初始化一些设置，可以在这里添加
    echo 环境配置完成！
) else (
    echo 找到现有环境 %ENV_NAME%，正在激活...
)

:: 激活环境并运行应用
echo 正在启动实时翻译软件...
call conda activate %ENV_NAME%
python main.py

:: 如果程序异常退出，暂停以便查看错误
if %ERRORLEVEL% neq 0 (
    echo 程序异常退出，错误代码: %ERRORLEVEL%
    pause
)

endlocal 