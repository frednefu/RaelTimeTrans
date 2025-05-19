@echo off
setlocal

:: 设置环境名称
set ENV_NAME=realtimetrans

echo =====================================================
echo 导出Conda环境配置: %ENV_NAME%
echo =====================================================

:: 检查conda是否已安装
call conda --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Conda未安装或未正确配置。
    echo 请先运行start.bat安装Conda并设置环境。
    pause
    exit /b 1
)

:: 检查环境是否存在
call conda env list | findstr /C:"%ENV_NAME%" >nul
if %ERRORLEVEL% neq 0 (
    echo 环境%ENV_NAME%不存在！
    echo 请先运行start.bat创建环境。
    pause
    exit /b 1
)

:: 导出环境配置
echo 正在导出环境配置到environment.yml...
call conda env export -n %ENV_NAME% > environment.yml
if %ERRORLEVEL% neq 0 (
    echo 导出环境失败！
    pause
    exit /b 1
)

echo 环境配置已导出到environment.yml
echo 您可以使用此文件在其他机器上重建环境:
echo conda env create -f environment.yml
pause

endlocal 