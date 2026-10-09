import sys

# 放在最前面：标准流句柄失效时（重定向到已关闭的管道、没有控制台等），
# 工作线程里任何一句 print/警告都会抛 OSError [WinError 6]，把整次识别结果
# 一起毁掉。包一层之后写失败只丢日志，不影响识别。
from safe_stream import install_safe_streams
install_safe_streams()

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 