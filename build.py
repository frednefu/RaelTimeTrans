import os
import sys
import shutil
import subprocess
from pathlib import Path

# 应用程序信息
APP_NAME = "实时翻译"
APP_VERSION = "1.0.0"
MAIN_SCRIPT = "main.py"

# 打包前清理
def clean_build():
    """清理之前的构建文件"""
    dirs_to_clean = ["build", "dist", f"{APP_NAME}.spec"]
    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            if os.path.isdir(dir_path):
                shutil.rmtree(dir_path)
                print(f"已删除目录: {dir_path}")
            else:
                os.remove(dir_path)
                print(f"已删除文件: {dir_path}")

# 确保存在必要的目录和依赖
def prepare_environment():
    """准备打包环境"""
    # 创建Subtitles目录（如果不存在）
    if not os.path.exists("Subtitles"):
        os.makedirs("Subtitles")
        print("已创建Subtitles目录")
    
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
        "--add-data", "LICENSE;.",
        "--add-data", "README.md;.",
        # 添加必要的目录
        "--add-data", "Subtitles;Subtitles",
        # 确保whisper能够正确导入
        "--hidden-import=whisper",
        "--hidden-import=whisper.tokenizer",
        "--hidden-import=torch",
        "--hidden-import=numpy",
        "--hidden-import=PyQt6",
        "--hidden-import=PySide6",
        "--hidden-import=googletrans",
        # 入口脚本
        MAIN_SCRIPT
    ]
    
    # 过滤掉空参数
    cmd = [arg for arg in cmd if arg]
    
    # 执行打包命令
    print("开始打包应用程序...")
    print(f"执行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=True)
    
    if result.returncode == 0:
        print("打包成功!")
        # 创建版本信息文件
        with open(os.path.join("dist", APP_NAME, "version.txt"), "w", encoding="utf-8") as f:
            f.write(f"{APP_NAME} v{APP_VERSION}")
        # 复制其他必要的文件
        for file in ["README.md", "LICENSE"]:
            if os.path.exists(file):
                shutil.copy(file, os.path.join("dist", APP_NAME))
        print(f"应用程序位置: {os.path.abspath(os.path.join('dist', APP_NAME, APP_NAME + '.exe'))}")
    else:
        print("打包失败!")
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
打包完成!
应用程序已打包完成，可以在以下位置找到:
dist/{APP_NAME}/{APP_NAME}.exe

您可以将整个 dist/{APP_NAME} 目录分发给用户。
""")
    else:
        print("打包过程中发生错误!")

if __name__ == "__main__":
    main() 