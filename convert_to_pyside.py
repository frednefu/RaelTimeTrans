import os
import re

def convert_file(file_path):
    """转换单个文件的导入语句和API调用"""
    print(f"Converting {file_path}...")
    
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # 替换导入语句
    content = content.replace('from PySide6.', 'from PySide6.')
    content = content.replace('import PySide6.', 'import PySide6.')
    content = content.replace('import PySide6', 'import PySide6')
    
    # 替换exec()为exec_()在旧版本PySide6中可能需要
    content = re.sub(r'app\.exec\(\)', 'app.exec()', content)
    
    # 修复信号连接语法（PyQt6使用connect(handler)，而PySide6使用connect(handler)）
    # 这部分语法实际上是兼容的，不需要修改
    
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)
    
    print(f"Converted {file_path}")

def find_pyqt_files(directory):
    """查找所有可能包含PyQt代码的Python文件"""
    pyqt_files = []
    
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if 'PyQt6' in content:
                        pyqt_files.append(file_path)
    
    return pyqt_files

if __name__ == "__main__":
    # 从当前目录开始查找所有包含PyQt6的Python文件
    pyqt_files = find_pyqt_files('.')
    
    if not pyqt_files:
        print("No files containing PyQt6 found.")
        exit(0)
    
    print(f"Found {len(pyqt_files)} files containing PyQt6:")
    for file in pyqt_files:
        print(f"  - {file}")
    
    confirm = input("Do you want to convert these files to use PySide6? (y/n): ")
    if confirm.lower() != 'y':
        print("Conversion cancelled.")
        exit(0)
    
    for file in pyqt_files:
        convert_file(file)
    
    print("\nAll files converted successfully!")
    print("Don't forget to update your requirements.txt file to use PySide6 instead of PyQt6.") 