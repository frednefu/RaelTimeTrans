"""把翻译放到后台线程执行。

原来翻译是在 GUI 线程的 500ms 定时器里同步调的，而 googletrans 走的是 Google
免费接口，实测单句要 2.1~2.7 秒。后果有两个：

1. 每识别出一句文本，界面就要卡住两秒多（音量表、按钮响应一起停摆）；
2. 更关键的是，原文和译文是在同一次刷新里一起送进字幕窗口的，所以**原文也
   必须等译文算完才显示**——这就是"原文不实时"的直接原因。

改成后台线程之后，原文一识别出来就上屏，译文算好了再补上。

流式识别（见 audio/simul_asr.py）之后多了一种请求：**前缀翻译**。边上屏边
翻译同一句话的半截原文（kind="prefix"），定稿后再翻整句（kind="final"）。
两者走同一个线程、同一个队列，靠 kind 区分；关键是积压时**优先保终稿**——
把终稿丢掉只翻前缀的话，那句的正式译文就永远不来了（`_coalesce` 那里现在
"终稿一条都不丢、只丢被取代的前缀"）。
"""

import itertools
import queue
import threading

# 前缀请求与终稿请求的标签（kind）
KIND_PREFIX = "prefix"
KIND_FINAL = "final"


class TranslationWorker:
    """单线程翻译队列

    只用一个工作线程：googletrans 的 Translator 实例不一定线程安全，而且并发
    调用对方接口只会更容易被限流。
    """

    def __init__(self, translate_func):
        """
        参数:
            translate_func: callable(text, target_language) -> str
        """
        self._translate = translate_func
        self._requests = queue.Queue()
        self._results = queue.Queue()
        self._counter = itertools.count(1)
        self._thread = None
        self._running = False
        self.skipped_requests = 0  # 因积压被跳过的请求数（仅用于日志/诊断）

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="translation-worker",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        """停掉工作线程并清空队列

        线程是 daemon 且只等 1 秒：手上那条已经发出去的请求可能还没回来（冷加载最长
        120 秒），所以**不能靠 stop 来停住"继续向服务发请求"**——那一段由显存账本的
        闲置自动卸载兜住（见 model_residency）。

        队列必须抽干：残留的请求会在下次「开始翻译」时被这条线程重新捡起来翻，翻完
        的译文又没人认领（序号早已作废），白占一次推理、还顺手把模型的 keep_alive
        续上。`request()` 自己会 `start()`，所以抽干不会影响下次使用。
        """
        self._running = False
        thread = self._thread
        self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=1)
        self.clear_pending()

    def clear_pending(self):
        """抽干待翻请求与没人取的结果（停止翻译时调）"""
        for q in (self._requests, self._results):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def request(self, text, target_language, kind=KIND_FINAL):
        """提交一次翻译请求，返回请求序号

        kind="prefix" 表示这是流式识别过程中"已确认前缀"的半截句子（只喂显示），
        kind="final" 是定稿的整句（要落盘、要覆盖前缀译文）。
        """
        self.start()
        seq = next(self._counter)
        self._requests.put((seq, text, target_language, kind))
        return seq

    def poll(self):
        """取出已完成的翻译结果，返回 [(seq, text, translation, kind), ...]"""
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                return results

    def _run(self):
        while self._running:
            try:
                request = self._requests.get(timeout=0.2)
            except queue.Empty:
                continue

            for job in self._coalesce(request):
                if not self._running:
                    return
                seq, text, target, kind = job
                try:
                    translation = self._translate(text, target)
                except Exception as e:
                    print(f"后台翻译失败: {str(e)}")
                    translation = ""
                self._results.put((seq, text, translation, kind))

    def _coalesce(self, request):
        """把积压的一批请求压成"真正要翻的那几条"，返回按顺序要执行的作业表

        积压说明识别速度已经超过翻译速度了，继续逐条补翻只会让字幕越来越滞后。但
        **能丢的只有前缀**（后到的前缀本来就是"更长的同一句话"，界面只显示最新那条），
        **终稿一个都不能丢**：终稿是这句话唯一一次正式翻译，丢了它这一句就永远只有
        原文（用户报的"有时候直接显示原文"里就有这条，本机 SRT 里出现过连缺五句）。
        原来这里只保留"最后一条终稿"，同一批里的其它终稿直接扔掉，正是那个形状。

        于是：全部终稿照翻，前缀只留最新的一条（终稿在的话它其实也已经作废了，
        留着只是给下一句的逐词显示多一份料）。
        """
        pending = []
        while True:
            try:
                pending.append(self._requests.get_nowait())
            except queue.Empty:
                break
        batch = [request] + pending
        finals = [item for item in batch if item[3] == KIND_FINAL]
        prefixes = [item for item in batch if item[3] != KIND_FINAL]
        keep = finals + (prefixes[-1:] if prefixes else [])
        dropped = len(batch) - len(keep)
        if dropped > 0:
            self.skipped_requests += dropped
            print(f"翻译积压，跳过 {dropped} 条被取代的前缀，"
                  f"翻 {len(keep)} 条（终稿 {len(finals)} 条、前缀 {len(keep) - len(finals)} 条）")
        return keep
