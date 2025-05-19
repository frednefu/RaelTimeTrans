@echo off
setlocal EnableDelayedExpansion

echo ========================================
echo 实时翻译应用程序打包工具
echo ========================================
echo.

:: 检查Python环境
echo 检查Python环境...
python --version > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未检测到Python。请确保已安装Python并添加到系统PATH中。
    goto :error
)

:: 检查是否安装了PyInstaller
echo 检查PyInstaller...
python -c "import PyInstaller" > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [警告] 未检测到PyInstaller。尝试安装...
    pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo [错误] 安装PyInstaller失败。
        goto :error
    )
    echo PyInstaller安装成功。
)

echo.
echo 开始打包应用程序...
echo.

:: 执行打包脚本
python build.py
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 打包过程中发生错误。
    goto :error
)

echo.
echo 打包过程完成！
echo.
echo 您可以在 dist\实时翻译\ 目录中找到可执行文件。
echo.
goto :end

:error
echo.
echo 打包过程失败。请检查上述错误信息。
exit /b 1

:end
echo 按任意键退出...
pause > nul
exit /b 0 