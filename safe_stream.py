"""把 stdout/stderr 包成"写不进去也不报错"的流

Windows 上标准流句柄失效时（重定向到已关闭的管道、进程没有控制台、被某些启动器
拉起），往它写任何东西都会抛 `OSError: [WinError 6] 句柄无效`。这本来只是丢掉
一句日志，但**工作线程里的 print / 进度条一抛异常，就会把整次识别结果一起毁掉**
——实测 Whisper 任务整个失败、候选文本全无，界面上只有"没有识别结果"。

所以启动时统一包一层：写失败就当没写，程序该跑还跑。
"""
import sys


class SafeStream:
    """包住真实流，write/flush 失败只丢弃，绝不向上抛"""

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        if self._stream is None:
            # 没有控制台（pythonw 之类），装作写成功
            return len(data)
        try:
            return self._stream.write(data)
        except (OSError, ValueError):
            return len(data) if isinstance(data, str) else 0

    def flush(self):
        if self._stream is None:
            return
        try:
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def __getattr__(self, name):
        # isatty/fileno/encoding 之类的属性照旧透给真实流
        stream = self._stream
        if stream is None:
            raise AttributeError(name)
        return getattr(stream, name)


def install_safe_streams():
    """启动时调用一次；已经包过就不重复包"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if isinstance(stream, SafeStream):
            continue
        setattr(sys, name, SafeStream(stream))
