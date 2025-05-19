import os
import sys
import shutil
import subprocess
from pathlib import Path

# 应用程序信息
APP_NAME = "RealTimeTranslation"
APP_VERSION = "1.0.0"
MAIN_SCRIPT = "main.py"

# 获取Python库路径
PYTHON_LIB_PATH = os.path.dirname(sys.executable)

# 打包前清理
def clean_build():
    """清理之前的构建文件"""
    dirs_to_clean = ["build", "dist", f"{APP_NAME}.spec"]
    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            if os.path.isdir(dir_path):
                shutil.rmtree(dir_path)
                print(f"Deleted directory: {dir_path}")
            else:
                os.remove(dir_path)
                print(f"Deleted file: {dir_path}")

# 确保存在必要的目录和依赖
def prepare_environment():
    """准备打包环境"""
    # 创建Subtitles目录（如果不存在）
    if not os.path.exists("Subtitles"):
        os.makedirs("Subtitles")
        print("Created Subtitles directory")
    
    # 复制许可证和说明文件到打包位置
    if not os.path.exists("dist"):
        os.makedirs("dist")

# 打包应用
def build_app():
    """使用PyInstaller打包应用"""
    # 设置PyInstaller命令
    cmd = [
        "pyinstaller",
        "--name", APP_NAME,
        "--icon=icon.ico" if os.path.exists("icon.ico") else "",
        "--windowed",  # 不显示控制台窗口
        "--noconfirm",  # 覆盖现有文件
        "--paths", PYTHON_LIB_PATH,  # 添加Python库路径
        "--add-binary", f"{PYTHON_LIB_PATH}\\python38.dll;.",  # 显式包含Python DLL
        "--add-data", "LICENSE;.",
        "--add-data", "README.md;.",
        # 添加必要的目录
        "--add-data", "Subtitles;Subtitles",
        # 确保whisper能够正确导入
        "--hidden-import=whisper",
        "--hidden-import=whisper.tokenizer",
        "--hidden-import=torch",
        "--hidden-import=numpy",
        # 只保留PySide6，移除PyQt6
        "--hidden-import=PySide6",
        "--hidden-import=googletrans",
        # 入口脚本
        MAIN_SCRIPT
    ]
    
    # 过滤掉空参数
    cmd = [arg for arg in cmd if arg]
    
    # 执行打包命令
    print("Starting application packaging...")
    print(f"Executing command: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=True)
    
    if result.returncode == 0:
        print("Packaging successful!")
        # 创建版本信息文件
        with open(os.path.join("dist", APP_NAME, "version.txt"), "w", encoding="utf-8") as f:
            f.write(f"{APP_NAME} v{APP_VERSION}")
        # 复制其他必要的文件
        for file in ["README.md", "LICENSE"]:
            if os.path.exists(file):
                shutil.copy(file, os.path.join("dist", APP_NAME))
        print(f"Application location: {os.path.abspath(os.path.join('dist', APP_NAME, APP_NAME + '.exe'))}")
    else:
        print("Packaging failed!")
        return False
    
    return True

# 主函数
def main():
    # 清理之前的构建
    clean_build()
    
    # 准备环境
    prepare_environment()
    
    # 执行打包
    if build_app():
        print(f"""
Packaging complete!
The application has been packaged and can be found at:
dist/{APP_NAME}/{APP_NAME}.exe

You can distribute the entire dist/{APP_NAME} directory to users.
""")
    else:
        print("An error occurred during packaging!")

if __name__ == "__main__":
    main() 