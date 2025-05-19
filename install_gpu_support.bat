@echo off
echo ==========================================================
echo 安装GPU支持的组件 - 适用于CUDA 11.8及以上
echo ==========================================================

call C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans

REM 检查NVIDIA驱动是否安装
echo 检查NVIDIA驱动...
nvidia-smi >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo 警告: 无法检测到NVIDIA驱动或GPU。
    echo 请确保您已安装最新的NVIDIA显卡驱动，否则GPU加速将无法生效。
    echo NVIDIA驱动下载: https://www.nvidia.com/download/index.aspx
    echo.
    echo 是否仍然继续安装? 即使没有GPU也可以继续，但不会有加速效果。
    choice /C YN /M "继续安装? (Y=是, N=否)"
    if errorlevel 2 (
        echo 安装已取消。
        goto end
    )
)

echo.
echo 步骤1: 卸载当前的PyTorch版本
pip uninstall -y torch torchvision torchaudio

echo.
echo 步骤2: 安装CUDA版PyTorch
echo 安装CUDA 11.8版本的PyTorch...
pip install torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2+cu118 --index-url https://download.pytorch.org/whl/cu118

echo.
echo 步骤3: 安装ffmpeg
echo 安装ffmpeg供音频处理使用...
pip install ffmpeg-python
conda install -y -c conda-forge ffmpeg

echo.
echo 步骤4: 更新和重新安装其他组件
pip install -U openai-whisper pydub PyAudio sounddevice PySide6 googletrans==4.0.0-rc1 python-dotenv

echo.
echo 步骤5: 检查安装结果
python check_gpu.py

echo.
echo 步骤6: 刷新设置
echo 刷新设置以确保应用程序使用GPU...
if exist "settings.json" (
    echo 备份当前设置...
    copy "settings.json" "settings_backup.json" >nul
    echo 修改设置文件...
    python -c "import json; f=open('settings.json', 'r', encoding='utf-8'); data=json.load(f); f.close(); data['use_gpu']=True; data['device']='cuda'; f=open('settings.json', 'w', encoding='utf-8'); json.dump(data, f, ensure_ascii=False, indent=4); f.close(); print('设置已更新')"
)

echo.
echo ==========================================================
echo 安装完成！
echo.
echo 如果上方显示"CUDA是否可用: True"，则表示GPU支持已成功安装。
echo 现在您可以运行应用程序，将会自动使用GPU加速。
echo.
echo 提示:
echo - 如果显示"CUDA是否可用: False"，请检查您的显卡驱动是否安装正确。
echo - 进入应用程序后，确认"使用GPU加速"选项已勾选。
echo ==========================================================

:end
pause 