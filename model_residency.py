"""模型驻留与显存回收的协调中心（全局单例 `model_residency`）

**为什么要有这个模块。** 这台机器只有 8 GB 显存，上面要同时跑识别（whisper）和翻译
（Ollama 里的 EuroLLM）。原来的做法是"谁用谁自己管"——于是出现了两个后果：

1. 流式识别引擎每次点「开始翻译」都新建一份（`audio/audio_manager.py`），停止时没人
   放掉，`SimulStreamingEngine.unload()` 写好了却零调用点；
2. Ollama 那边每次请求都续 `keep_alive`，应用里根本没有"卸载"这条路，切过模型的机器
   上实测 EuroLLM(1.73GB) + Spark(3.52GB) 同时驻留，再用一会儿就变成"显存占满、
   Ollama 把模型挤回 CPU"，13 tok/s 的翻译当然句句超时。

所以这里做一件很小的事：**记住谁在占显存、闲了多久、该不该放**。显存里"现在有什么"
只有这一个出口——界面那行状态、「释放显存」按钮、闲置自动卸载都读它。

**刻意零依赖**：只 import 标准库，绝不 import `audio/` / `translation/` / `torch`。
`audio/`、`translation/`、`gui/` 三方都要 import 它，一旦互相牵连就是循环导入；离屏
检查脚本也要能单独 import 它。torch 只在 `free_cuda_cache()` / `cuda_memory_mib()`
里惰性 import。

**`release_fn` 的契约**（调用方必须遵守）：

- 必须是**幂等**且**不抛异常**的（本模块也会兜住异常，只记进 `last_release_error`）。
- 必须是"查当前状态"的**薄绑定方法**（例如 `AudioManager._release_stream_engine`），
  **不许闭包捕获某个具体的引擎对象**——引擎会因为参数签名变化而重建，闭包捕获的那个
  早就不是当前在用的了。
- 内部不要再调 `touch()`（本模块在卸载期间会忽略 touch，见 `_Entry.releasing`）。
"""

import gc
import threading
import time


class _Entry:
    """一个可回收对象的账目"""

    __slots__ = ("key", "label", "kind", "release_fn", "guard_fn", "idle_timeout",
                 "device", "last_used", "resident", "releasing", "release_count",
                 "last_release_error")

    def __init__(self, key, label, release_fn, kind, idle_timeout, device, guard_fn):
        self.key = key
        self.label = label
        self.release_fn = release_fn
        self.kind = kind
        self.idle_timeout = idle_timeout
        self.device = device
        self.guard_fn = guard_fn
        self.last_used = time.time()
        self.resident = False        # 还没用过，先当作没占着
        self.releasing = False
        self.release_count = 0
        self.last_release_error = None

    def idle_seconds(self, now=None):
        return max(0.0, (now or time.time()) - self.last_used)


class ModelResidency:
    """全局模型驻留/显存回收协调器

    - `register` 登记一个"能被卸载的东西"，附上它的卸载函数；
    - `touch` 表示"刚用过"，重置闲置计时（工作线程里放心调）；
    - `release` / `release_others` / `release_all` 立刻放掉；
    - `sweep` 由界面定时器驱动，把闲置超时的放掉。

    `guard_fn() -> bool` 返回 False 时，`release`/`release_others`/`release_all`/`sweep`
    一律**跳过**这一项（用于"正在识别时不许卸 ASR"）。`force=True` 可以无视 guard。
    """

    def __init__(self):
        self._entries = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 登记

    def register(self, key, label, release_fn, kind="", idle_timeout=None,
                 device="cuda", guard_fn=None):
        """登记一个可回收对象（同一个 key 重复登记 = 覆盖）

        idle_timeout 单位秒；None 或 <=0 表示"不参与闲置自动卸载"。
        """
        with self._lock:
            self._entries[key] = _Entry(key, label, release_fn, kind,
                                        idle_timeout, device, guard_fn)

    def unregister(self, key):
        """只摘账目，不调用 release_fn（调用方自己已经卸过了）"""
        with self._lock:
            self._entries.pop(key, None)

    def set_idle_timeout(self, key, seconds):
        """改某一项的闲置超时（设置面板里改了就重设一次）"""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.idle_timeout = seconds

    def set_idle_timeout_all(self, seconds):
        with self._lock:
            for entry in self._entries.values():
                entry.idle_timeout = seconds

    # ------------------------------------------------------------ 记账

    def touch(self, key):
        """"刚用过"：标记为驻留中并重置闲置计时

        卸载过程中（`releasing`）忽略——否则 release_fn 内部顺手 touch 一下，
        这一项立刻又变成"驻留着"，下一次 sweep 就再也不会放它。
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.releasing:
                return
            entry.resident = True
            entry.last_used = time.time()

    def mark_released(self, key):
        """不加计时地标记为"没占着"（例如加载失败、被上游自己卸掉了）"""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.resident = False

    # ------------------------------------------------------------ 释放

    def _should_skip(self, entry):
        if entry.guard_fn is not None:
            try:
                if not entry.guard_fn():
                    return True
            except Exception as e:
                # guard 自己出错不该拦着回收，放行并记下来
                entry.last_release_error = "guard_fn 出错（已放行）：%s" % e
        return False

    def release(self, key, force=False):
        """立刻放掉一项，返回是否真的调了 release_fn

        跳过的情况：没登记、已经不在驻留状态、或 guard 说现在不能卸（除非 force）。
        **release_fn 抛异常时把 resident 改回去**：模型没真卸掉，账上却记成"已经没占着"，
        那它就再也不会被回收了 —— 这一轮改动要修的正是这种静默的漏。
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.releasing:
                return False
            if not entry.resident:
                return False
            if not force and self._should_skip(entry):
                entry.last_release_error = "跳过：当前状态不允许卸载"
                return False
            entry.releasing = True
            entry.resident = False
            entry.last_used = time.time()

        # release_fn 在锁外执行：它可能耗时（empty_cache / HTTP），也可能回调本模块
        try:
            entry.release_fn()
        except Exception as e:
            with self._lock:
                entry.releasing = False
                entry.resident = True       # 没卸成功：还当它占着，下次再试
            entry.last_release_error = "%s: %s" % (type(e).__name__, e)
            return False
        with self._lock:
            entry.releasing = False
            entry.release_count += 1
            entry.last_release_error = None
        return True

    def release_others(self, keep=(), force=False):
        """放掉除 `keep` 之外的所有登记项，返回实际放掉的数量

        keep 用 key 的集合显式给出（如 `{"asr_simul", "llm"}`）——比"按前缀保留"好懂，
        也不会误伤。
        """
        keep = set(keep)
        with self._lock:
            keys = [k for k, e in self._entries.items() if k not in keep and e.resident]
        return sum(1 for key in keys if self.release(key, force=force))

    def release_all(self, force=False):
        """放掉所有驻留项。返回 `(已释放数, 被 guard 跳过数)`——界面要报给用户看"""
        with self._lock:
            keys = [k for k, e in self._entries.items() if e.resident]
        released = skipped = 0
        for key in keys:
            if self.release(key, force=force):
                released += 1
            else:
                with self._lock:
                    entry = self._entries.get(key)
                    still_resident = entry is not None and entry.resident
                if still_resident:
                    skipped += 1
        return released, skipped

    def sweep(self, now=None):
        """闲置超时的逐个放掉，返回放掉的数量（界面定时器调）"""
        now = now or time.time()
        with self._lock:
            due = [k for k, e in self._entries.items()
                   if e.resident and e.idle_timeout and e.idle_timeout > 0
                   and e.idle_seconds(now) >= e.idle_timeout]
        released = 0
        for key in due:
            if self.release(key):
                released += 1
                with self._lock:
                    entry = self._entries.get(key)
                    label = entry.label if entry else key
                print(f"显存回收：{label} 闲置超过 {self._idle_limit(key)} 秒，已卸载")
        return released

    def _idle_limit(self, key):
        entry = self._entries.get(key)
        return int(entry.idle_timeout) if entry and entry.idle_timeout else 0

    # ------------------------------------------------------------ 查询

    def snapshot(self, now=None):
        """给界面/检查脚本看的账目快照（按登记顺序）"""
        now = now or time.time()
        with self._lock:
            return [{
                "key": e.key,
                "label": e.label,
                "kind": e.kind,
                "resident": e.resident,
                "idle_seconds": int(e.idle_seconds(now)),
                "idle_timeout": e.idle_timeout,
                "device": e.device,
                "release_count": e.release_count,
                "last_release_error": e.last_release_error,
            } for e in self._entries.values()]

    def describe(self):
        """一行文字，给界面状态行用（如"流式识别: 驻留(闲 12s)｜本地翻译: 已卸载"）"""
        now = time.time()
        parts = []
        for entry in self.snapshot(now):
            if entry["resident"]:
                text = "驻留(闲 %ds)" % entry["idle_seconds"]
            else:
                text = "已卸载"
            parts.append("%s: %s" % (entry["label"], text))
        return "｜".join(parts)


# 全局单例：`audio/`、`translation/`、`gui/` 共用这一份账目
model_residency = ModelResidency()


# ── torch 相关的两个小工具（torch 惰性 import，本模块才能被离屏脚本安全导入）──

def free_cuda_cache():
    """把已经没人引用的显存真正还给驱动

    torch 的缓存分配器在对象被回收后**不会**立刻把块还给驱动，它留着给自己复用。
    所以只 `del` 对象是看不到显存下降的，必须显式 `empty_cache()`；而 `empty_cache()`
    只能回收"已经没人引用"的块，因此前面一定要 `gc.collect()` 先把引用环断干净
    （实测漏掉 gc.collect() 时 `unload()` 后仍有几百 MiB 拿不回来）。

    返回是否真的跑了一次 empty_cache。
    """
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            return True
    except Exception as e:
        print(f"释放 CUDA 缓存失败（忽略）：{e}")
    return False


def cuda_memory_mib():
    """当前进程占用的显存，返回 `(已分配 MiB, 已保留 MiB)`；没有 CUDA 则 None

    **判断有没有真的释放要看"已分配"**（`memory_allocated`），不是 `nvidia-smi`：
    保留块不一定会立刻还给驱动，`nvidia-smi` 上的数字会滞后。
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        mib = 1024.0 * 1024.0
        return (torch.cuda.memory_allocated() / mib,
                torch.cuda.memory_reserved() / mib)
    except Exception:
        return None
