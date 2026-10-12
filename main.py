import sys

# 放在最前面：标准流句柄失效时（重定向到已关闭的管道、没有控制台等），
# 工作线程里任何一句 print/警告都会抛 OSError [WinError 6]，把整次识别结果
# 一起毁掉。包一层之后写失败只丢日志，不影响识别。
from safe_stream import install_safe_streams
install_safe_streams()

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from model_residency import model_residency

def main():
    app = QApplication(sys.argv)
    # 退出时兜一道：主窗口的 closeEvent 只覆盖"正常关窗"，崩溃退出、任务管理器结束、
    # 系统注销这些路径都不经过它，而 Ollama 那边的模型会一直挂到 keep_alive 到期。
    # 这里是"进程要走了"的最后一个通知点，放掉比不放好（失败也不抛，见 model_residency）。
    app.aboutToQuit.connect(lambda: model_residency.release_all(force=True))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 