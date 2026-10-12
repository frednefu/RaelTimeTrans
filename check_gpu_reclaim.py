"""反复「开始/停止翻译」会不会把显存攒满——量一遍，并打印每一步的账

用法：
    python check_gpu_reclaim.py [--cycles 5] [--backend simul|batch] [--model small]
                                [--device 名字关键词] [--skip-ollama] [--keep-warm]
                                [--skip-paths] [--slow-warmup 5] [--settle 10]

用户报的现象是"反复点开始/停止多次之后 GPU 被占满、原文和译文都不流畅"。这个脚本
就是拿真人点按钮的那套动作（`AudioManager.start_recording` / `stop_recording`）连做
N 轮，每轮记下四个数，看它们会不会爬：

1. **活着的 `audio-stream-recognize` 线程数**——必须每轮回到 1。
   改造前 `_prepare_streaming` 会无条件清空 `stream_queue`，把上一轮还没被消费的
   `"stop"` 一起吞了，旧线程（daemon）于是永不退出：抱着旧引擎占显存，还和新线程抢
   同一个队列的事件（屏幕上是乱句/重复/丢句）。
2. **`torch.cuda.memory_allocated()` / `memory_reserved()`**——不逐轮上涨。
   判断"有没有真释放"要看 allocated（`memory_reserved` 只是缓存分配器留着自用的块，
   会滞后）。
3. **本轮是不是复用了同一个引擎对象、加载耗时是不是 0**——验"签名一致就复用"。
   改造前每次开始都新建一份，代价是 2.5 秒加载 + 1.4 GB 重载，首句必卡。
   判它之前**等上一轮的流式线程退干净**（`--settle`）：旧线程还活着时重建引擎是
   设计内的兜底（轮次号在 join 之前就自增，见 `check_join_race`），那一轮不算违规。
4. **`model_residency` 账本**——谁在驻留、闲了多久、被放掉过几次。

结尾做一次 `release_all() + free_cuda_cache()`，看 `memory_allocated` 回不回落到基线；
然后**再热一轮、把闲置超时压到 1 秒、手动 sweep()**，验"闲置到点自动卸"这条路上
真正的 `_release_stream_engine` 确实把显存放下了（单测里那是假回调，证不到这一步）。

Ollama 那一段（`--skip-ollama` 可跳过）：`unload()` 之后 `/api/ps` 名单里确实没有它了、
`unload_others(keep)` 只留 keep、连不上服务时这几步都返回 False **且不抛异常**。

**这个脚本会真的录音**（每轮一两秒，房间的底噪），也会真的加载/卸载识别模型。
它会改 settings.json 里的 `asr_backend` 和（给了 `--model` 时的）`simul_model`
（跑之前备份、`finally` 原样放回），不改别的；`--keep-warm` 表示结束时**故意不卸**
（想接着手动跑主程序看看手感时用）。

`--model` 是给"量真实代价"用的：本机配置里 `simul_model` 可能是个 tiny，
那小得看不出问题（加载 0.5 s、153 MiB）；要照 CLAUDE.md 记的那个配置量就得
`--model small`（加载约 2.5 s、约 1.4 GB）。

**除了上面这条最短路径，脚本还会各造一次"只有真失败/真竞态/真漏账才走得到"的路**
（`--skip-paths` 全跳过）——用户报的"不是每次都撑满"恰恰发生在这些路上，而上面那 N 轮
（没语音、不失败、不建界面）一个都碰不到：

- **失败回退**（`check_failure_fallback`）：给引擎注入一次 `commit()` 异常。改造前失败
  分支只置 `_stream_state="failed"` 就返回，那份 whisper 留在显存里，而录音线程下一块
  音频就回退整句识别、把**另一份** whisper 加载进来——本轮同时驻留两份（8 GB 卡上就是
  那一下 OOM）。这里验它当场就没了。
- **冷启时「停 → 立刻再开」**（`check_join_race`）：把第一份引擎的预热人为拖慢
  （`--slow-warmup`，模拟大模型/慢磁盘），让 3 秒的 join 必定超时。改造前旧线程若恰好
  在 join 判定之后、轮次号自增之前退出，它以为自己"还是当前这一轮" → 不卸引擎，那个
  对象连同显存从此没人引用、`empty_cache()` 也从没跑过。这里验轮次号确实在 join 之前
  自增、被丢下的引擎真的卸过、收尾后显存回到基线。
- **账本漏账**（`check_batch_ledger`）：整句后端下**只加载、不产出文本**。账本原来只认
  "识别出文本"过的项，于是预览/静音/识别异常这几条路上模型占着显存而账上写着没占，
  `sweep()` / `release_all()` 全跳过它。这里验加载完就上了账、而且真放得掉。
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402  （失败回退那一段要塞一块假音频进队列）

FAILED = []


def check(ok, message):
    print(f"  [{'通过' if ok else '不通过'}] {message}")
    if not ok:
        FAILED.append(message)


def note(message):
    print(f"  · {message}")


# ── 量显存的三种口径 ────────────────────────────────────────────────────

def cuda_mib():
    """本进程占的显存 (已分配, 已保留)；没有 CUDA 返回 (None, None)"""
    try:
        import torch
        if not torch.cuda.is_available():
            return None, None
        mib = 1024.0 * 1024.0
        return torch.cuda.memory_allocated() / mib, torch.cuda.memory_reserved() / mib
    except Exception:
        return None, None


def nvidia_smi_mib():
    """整张卡被占了多少（含别的进程）。拿不到返回 None。

    这个数字会滞后于 `empty_cache()`，而且要跟 Ollama 之类的别的进程分账，
    所以只打印出来做参考，判定一律用 `memory_allocated`。
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        used, total = out.stdout.strip().split("\n")[0].split(",")
        return int(used), int(total)
    except Exception:
        return None


def stream_threads():
    """现在活着几条流式识别线程（按名字找）"""
    return sum(1 for t in threading.enumerate()
               if t.name == "audio-stream-recognize" and t.is_alive())


def fmt(value, unit="MiB"):
    return "—" if value is None else "%.0f %s" % (value, unit)


# ── 一轮开始/停止 ───────────────────────────────────────────────────────

def run_cycle(manager, device, seconds, settle_timeout=10.0):
    """真实地开始一轮录音、等一会儿、再停止（和用户点按钮是同一套动作）

    停完之后**等上一轮的流式线程退干净**（用户实际也是看着界面停住、再点开始的），
    返回 `(started, settle_secs)`——`settle_secs` 是等到它退出的秒数，超时没等到就是
    None。不等也能跑（join 超时会重建引擎），但那样"复用同一份"就没法判了：重建在
    "旧线程还没退"时是设计内的兜底，见 `check_join_race`。
    """
    manager.start_recording(device)
    started = manager.is_running
    time.sleep(seconds)
    manager.stop_recording()
    started_at = time.time()
    if wait_for(lambda: stream_threads() == 0, settle_timeout, interval=0.05):
        return started, time.time() - started_at
    return started, None


def wait_for(predicate, timeout, interval=0.1):
    """等一个条件成立，返回是否等到（轮询）"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def wait_stream_ready(manager, timeout=90.0):
    """等流式线程把模型加载/预热完（`_stream_state` 变成 ready）"""
    return wait_for(lambda: manager._stream_state == "ready", timeout)


def ledger(key):
    """账本里某一项的当前快照（没登记过就是 None）"""
    from model_residency import model_residency
    for entry in model_residency.snapshot():
        if entry["key"] == key:
            return entry
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=5, help="做几轮开始/停止")
    parser.add_argument("--backend", default="simul", choices=["simul", "whisper_batch"])
    parser.add_argument("--model", default="", help="流式模型（不给就用配置里的 simul_model）")
    parser.add_argument("--device", default="", help="输入设备名的关键词（不给就用配置里那个）")
    parser.add_argument("--seconds", type=float, default=1.5, help="每轮录多久")
    parser.add_argument("--settle", type=float, default=10.0,
                        help="每轮停下后最多等几秒让流式线程退干净（等到了才判「复用同一份」）")
    parser.add_argument("--skip-ollama", action="store_true", help="跳过本地大模型那一段")
    parser.add_argument("--skip-sweep", action="store_true", help="跳过闲置自动回收那一段")
    parser.add_argument("--skip-paths", action="store_true",
                        help="跳过失败回退 / join 竞态 / 账本漏账这三段")
    parser.add_argument("--slow-warmup", type=float, default=5.0,
                        help="join 竞态那一段里，第一份引擎的预热人为拖多久（秒）")
    parser.add_argument("--keep-warm", action="store_true", help="结束时故意不卸模型")
    args = parser.parse_args()

    from config import config
    from model_residency import model_residency, free_cuda_cache

    backup = "settings.json.reclaim-backup"
    original_backend = config.get("asr_backend", "whisper_batch")
    original_simul_model = config.get("simul_model", "")
    shutil.copyfile("settings.json", backup)
    manager = None
    baseline = None
    try:
        config.set("asr_backend", args.backend)
        if args.model:
            # 只改这一轮用的键：流式模型单独一个键，动它不影响用户选的整句模型
            config.set("simul_model", args.model)

        from audio.audio_manager import AudioManager
        manager = AudioManager()

        print("— 环境 —")
        device = args.device or config.get("input_device", "")
        devices = manager.get_input_devices()
        note("可用输入设备 %d 个" % len(devices))
        if device:
            match = [d for d in devices if device.lower() in d.lower()]
            device = match[0] if match else (devices[0] if devices else "")
        else:
            match = [d for d in devices if config.get("input_device", "") and
                     config.get("input_device").lower() in d.lower()]
            device = match[0] if match else (devices[0] if devices else "")
        if not device:
            print("  找不到音频输入设备：这个脚本要真录一小段音才能走完 start_recording。")
            print("  插上麦克风/虚拟声卡，或用 --device 指一个名字关键词。")
            return 2
        note("用输入设备：%s" % device)
        note("识别后端：%s" % args.backend)
        used, total = nvidia_smi_mib() or (None, None)
        note("nvidia-smi：%s / %s" % (fmt(used), fmt(total, "MiB 总")))

        # 先加载一轮、停掉，作为基线：这一轮之后模型是"驻留着"的状态，
        # 后面的轮次应该完全不再涨。
        print("— 基线（第 0 轮：先把它热起来）—")
        _, baseline_settle = run_cycle(manager, device, args.seconds, args.settle)
        baseline_alloc, _ = cuda_mib()
        engine_after_baseline = manager.stream_engine
        note("引擎 %s，已分配 %s，线程 %d 条"
             % ("已建" if engine_after_baseline is not None else "未建",
                fmt(baseline_alloc), stream_threads()))

        print("— %d 轮开始/停止 —" % args.cycles)
        rows = []
        for index in range(1, args.cycles + 1):
            engine_before = manager.stream_engine
            load_ms_before = getattr(engine_before, "load_ms", None)
            started, settle = run_cycle(manager, device, args.seconds, args.settle)
            alloc, reserved = cuda_mib()
            used, total = nvidia_smi_mib() or (None, None)
            engine_after = manager.stream_engine
            threads = stream_threads()
            rows.append({"index": index, "alloc": alloc, "reserved": reserved,
                         "threads": threads, "smi": used, "engine": engine_after,
                         "settle": settle, "settled": settle is not None,
                         "load_ms": getattr(engine_after, "load_ms", None)})
            note("第 %d 轮：started=%s 已分配 %s 保留 %s 卡上 %s 线程 %d 引擎 %s 加载 %s"
                 "（停完等到线程退出用了 %s）"
                 % (index, started, fmt(alloc), fmt(reserved), fmt(used), threads,
                    "复用" if engine_after is engine_before else "新建",
                    ("复用" if getattr(engine_after, "load_ms", None) == load_ms_before
                     else "%s ms" % getattr(engine_after, "load_ms", "?")),
                    "—" if settle is None else "%.1fs" % settle))

        print("— 判定 —")
        check(all(row["threads"] <= 1 for row in rows),
              "每轮结束时活着的流式识别线程数不超过 1（实测 %s）"
              % [row["threads"] for row in rows])
        if args.backend == "simul":
            # 复用只在"上一轮的线程已经退干净"时才判——那时重建就是漏了。上一轮线程
            # 还没退（join 超时那一支）时重建是设计内的兜底：轮次号在 join 之前就自增，
            # 旧线程一退就自己卸引擎，这一轮拿的是干净的一份（`check_join_race` 专门验）。
            prev_settled = baseline_settle is not None
            rebuilt_where = []
            for row in rows:
                if row["engine"] is not rows[0]["engine"] and prev_settled:
                    rebuilt_where.append(row["index"])
                prev_settled = row["settled"]
            slow = [row["index"] for row in rows if not row["settled"]]
            if slow:
                note("第 %s 轮停下后线程没在 %.0f 秒内退出，那几轮重建引擎是设计内的兜底"
                     % (slow, args.settle))
            else:
                note("每轮停下后线程都自己退干净了（最慢 %.1fs，重新开始就是复用同一份）"
                     % max([r["settle"] for r in rows if r["settled"]] or [0.0]))
            check(all(row["engine"] is not None for row in rows),
                  "每轮结束时手上都有一份引擎（不是 None）")
            check(not rebuilt_where,
                  "上一轮线程已经退干净时，这一轮一律复用同一个引擎（违规：%s）"
                  % (rebuilt_where or "无"))
            allowed = 1 + len(slow)
            check(len({row["engine"] for row in rows}) <= allowed,
                  "整个过程中不存在多余的流式引擎（引擎对象 %d 份，上限 %d）"
                  % (len({row["engine"] for row in rows}), allowed))
        if baseline_alloc is not None and rows:
            drift = max(row["alloc"] for row in rows) - baseline_alloc
            check(drift < 64,
                  "反复启停没有让「已分配」显存上涨（最大偏差 %.0f MiB）" % drift)
            tail = rows[-1]["alloc"] - baseline_alloc
            check(tail <= 16, "最后一轮的「已分配」已经回到基线水平（差 %.0f MiB）" % tail)

        print("— 账本 —")
        for entry in model_residency.snapshot():
            timeout = entry["idle_timeout"]
            note("%s：%s，闲 %ds，超时 %s，释放过 %d 次%s"
                 % (entry["label"], "驻留" if entry["resident"] else "已卸载",
                    entry["idle_seconds"],
                    "从不" if timeout in (None, 0) else "%ss" % timeout,
                    entry["release_count"],
                    "" if not entry["last_release_error"]
                    else "（上次失败：%s）" % entry["last_release_error"]))
        # 这个脚本不建主窗口，所以账本上的闲置超时还是登记时的默认值 None ——
        # 真正把 `model_idle_unload_sec` 写进账本的是 `MainWindow._apply_residency_settings`。
        if any(e["idle_timeout"] in (None, 0) for e in model_residency.snapshot()):
            note("（没建主窗口，闲置超时还是默认的「从不」；"
                 "主窗口起来时会按 model_idle_unload_sec 写进来）")
        note("汇总：" + model_residency.describe())

        print("— 释放显存 —")
        released, skipped = model_residency.release_all(force=True)
        free_cuda_cache()
        time.sleep(0.5)
        alloc, reserved = cuda_mib()
        note("放下 %d 项、跳过 %d 项；已分配 %s，保留 %s" % (released, skipped,
                                                          fmt(alloc), fmt(reserved)))
        if baseline_alloc is not None:
            check(alloc is not None and alloc < 64,
                  "release_all 之后「已分配」回到基线（%.0f MiB）" % (alloc or 0))
        check(stream_threads() == 0, "没有残留的流式识别线程（实测 %d）" % stream_threads())
        check(manager.stream_engine is None, "账本放下之后 manager 手上的引擎也是空的")
        resident_after = [e["label"] for e in model_residency.snapshot() if e["resident"]]
        check(not resident_after, "账本上不再有驻留项（实际：%s）" % (resident_after or "无"))

        # 上面那 N 轮是最短路径（没语音、不失败、不建界面），下面三段各造一次
        # "只有真失败/真竞态/真漏账才走得到"的路。放在这里是因为它们自己会反复
        # 装卸模型、改账本，不该混进上面那串"逐轮不许涨"的采样里。
        if not args.skip_paths:
            check_failure_fallback(manager, device, args)
            check_join_race(manager, device, args)
            check_batch_ledger(manager)

        if args.backend == "simul" and not args.skip_sweep:
            check_idle_sweep(manager, device, args.seconds)

        if not args.skip_ollama:
            check_ollama(config)

        print()
        if FAILED:
            print("不通过 %d 项：" % len(FAILED))
            for item in FAILED:
                print("  - %s" % item)
            return 1
        print("全部通过")
        return 0
    finally:
        # 原样放回 settings.json（MainWindow 的 resizeEvent 之类会写它，我们只改了后端）
        try:
            shutil.copyfile(backup, "settings.json")
            os.remove(backup)
        except OSError as error:
            print("还原 settings.json 失败：%s" % error)
        if manager is not None:
            try:
                if manager.is_running:
                    manager.stop_recording()
                if not args.keep_warm:
                    model_residency.release_all(force=True)
                    manager.audio_processor.cleanup()
                    free_cuda_cache()
            except Exception as error:
                print("收尾失败（忽略）：%s" % error)
        # 内存里那两份也放回去：`config.set` 会把**整个** settings 字典重写一遍，
        # 只还原文件、忘了内存，下一次 set 又把它写脏了。
        if config.get("simul_model") != original_simul_model:
            config.set("simul_model", original_simul_model)
        if config.get("asr_backend") != original_backend:
            config.set("asr_backend", original_backend)


def check_idle_sweep(manager, device, seconds):
    """闲置到点自动卸：走一遍真的释放回调

    单测（`test_model_residency.py`）里的释放回调是个假计数器，只能证明"该放的时候
    账本调了它"。这里要证的是另一半：`_release_stream_engine` 真把 CUDA 上的模型
    放下去了、`memory_allocated` 真的回落——**自动回收不是纸上谈兵**。

    做法：再热一轮（这次引擎是冷的，会真加载），把超时压到 1 秒，等过了再 `sweep()`
    （主程序里是 2 秒一次的 `_residency_timer` 在调它，这里手动触发）。
    """
    # 这两个在 `main()` 里是局部名字，这里得自己拿一份（和 `check_ollama` 一个写法）
    from model_residency import model_residency, free_cuda_cache

    print("— 闲置自动回收（真卸一次）—")
    run_cycle(manager, device, seconds)
    hot, _ = cuda_mib()
    note("又热了一轮：已分配 %s，引擎 %s"
         % (fmt(hot), "在" if manager.stream_engine is not None else "空"))
    for entry in model_residency.snapshot():
        model_residency.set_idle_timeout(entry["key"], 1)
    time.sleep(1.2)
    freed = model_residency.sweep()
    free_cuda_cache()
    time.sleep(0.3)
    cold, _ = cuda_mib()
    note("超时 1 秒后 sweep 放下 %d 项；已分配 %s" % (freed, fmt(cold)))

    check(freed >= 1, "闲置到点后 sweep 真的放下了东西（放下 %d 项）" % freed)
    check(manager.stream_engine is None, "sweep 之后 manager 手上的引擎也空了")
    check(cold is not None and hot is not None and cold < hot - 100,
          "sweep 之后「已分配」掉下来了（%s → %s）" % (fmt(hot), fmt(cold)))


# ── 只有真失败 / 真竞态 / 真漏账才走得到的三条路 ─────────────────────────

def check_failure_fallback(manager, device, args):
    """流式引擎中途失败：它必须**当场**从显存里下去

    改造前失败分支只置 `_stream_state="failed"` 就 `return`，`finally` 又因为"还是
    当前这一轮"而不卸——失败的那份 whisper（约 1.4 GB）留在显存里；紧接着录音线程
    看到 `_stream_live()` 变 False 就回退整句识别，把**另一份** whisper 加载进来。
    于是这一轮同时驻留两份识别模型（8 GB 卡上就是那一下 OOM），要等下一次点「开始」
    才自愈。有真实语音才会走到 `commit()`，所以上面那 N 轮一轮都碰不到这个分支。

    做法：注入一次 `commit()` 异常（等价于解码真的报错），看引擎有没有当场消失。
    """
    from model_residency import model_residency, free_cuda_cache

    if args.backend != "simul":
        return
    print("— 流式失败回退（注入一次 commit 异常）—")
    manager.audio_processor.release_model()
    model_residency.release_all(force=True)
    free_cuda_cache()
    time.sleep(0.5)
    idle_alloc, _ = cuda_mib()

    # 先热一轮（引擎是冷的，会真加载），顺手量出"一份 whisper 有多大"
    run_cycle(manager, device, args.seconds)
    loaded = wait_for(lambda: manager.stream_engine is not None
                      and manager.stream_engine.ready, 120)
    if not loaded:
        check(False, "流式引擎没能在 120 秒内加载起来（状态 %s），这一段跳过"
              % manager._stream_state)
        return
    hot, _ = cuda_mib()
    one = None if (hot is None or idle_alloc is None) else hot - idle_alloc
    note("一份 whisper 约占 %s（空载 %s，加载后 %s）" % (fmt(one), fmt(idle_alloc), fmt(hot)))

    # 再开一轮：这次是复用那个热引擎的，起来很快
    manager.start_recording(device)
    if not wait_stream_ready(manager, 60):
        check(False, "复用引擎的这一轮没能就绪（状态 %s），这一段跳过"
              % manager._stream_state)
        manager.stop_recording()
        return

    engine = manager.stream_engine
    before_fail, _ = cuda_mib()

    def exploding_commit():
        raise RuntimeError("注入的提交异常（验显存回收用）")

    # 让它"攒够一个提交间隔"并且解一次就炸
    engine.ready_to_commit = lambda: True
    engine.commit = exploding_commit
    # 从队列外面塞一个 begin 事件（等价于录音线程的 VAD 认出了一句语音）。
    # 真喂一块静音：`begin_utterance` 照样走一遍上游的 init(offset=…)。
    manager._stream_begin(manager.stream_queue, 999, 0.0,
                          [np.zeros(1024, dtype=np.float32)])

    failed = wait_for(lambda: manager._stream_state == "failed", 20)
    check(failed, "注入的 commit 异常把流式状态打成 failed（现在 %s）"
          % manager._stream_state)
    time.sleep(0.3)
    free_cuda_cache()
    time.sleep(0.3)
    after_fail, _ = cuda_mib()

    check(manager.stream_engine is None,
          "失败之后 manager 手上的引擎已经空了（不能留到下一轮）")
    entry = ledger("asr_simul")
    check(entry is not None and not entry["resident"],
          "账本上 `asr_simul` 已经记成没占着（resident=%s）"
          % (entry["resident"] if entry else "无此项"))
    check(manager._stream_live() is False,
          "`_stream_live()` 变 False：录音线程下一块音频就改走整句识别")
    if one is not None and after_fail is not None:
        check(after_fail < idle_alloc + one * 0.4,
              "失败的那份 whisper 真从显存里走了（%s → %s）"
              % (fmt(before_fail), fmt(after_fail)))
    else:
        note("没有 CUDA，显存那几项跳过（账本那几项上面已经验过）")

    manager.stop_recording()
    wait_for(lambda: stream_threads() == 0, 15)


def check_join_race(manager, device, args):
    """冷启时「停 → 立刻再开」撞上还在预热的旧线程（join 超时那一支）

    `_prepare_streaming` 收上一轮时 `join(timeout=3)` 超时是常有的事（模型大、磁盘慢），
    这时它只能"不交接旧引擎、本轮重建"。改造前的问题在**次序**：轮次号是在 join **之后**
    才自增的，于是旧线程只要恰好在这两步之间退出，它退出时看到的还是"我是当前这一轮"
    → 不卸引擎；而 `self.stream_engine` 已经被新引擎覆盖，那个旧对象连同它 1.4 GB 显存
    从此谁都不再引用，`free_cuda_cache()` 也从没跑过——`nvidia-smi` 就一直高着，这就是
    "不是每次都撑满"里最难复现的那一条。

    做法：把**第一份**引擎的预热人为拖慢（`--slow-warmup`），让 join 必定超时；然后
    "停 → 立刻再开"，全程采样线程数与显存。
    """
    from model_residency import model_residency, free_cuda_cache

    if args.backend != "simul":
        return
    print("— 冷启时「停 → 立刻再开」（join 超时那一支）—")
    manager.audio_processor.release_model()
    model_residency.release_all(force=True)
    free_cuda_cache()
    time.sleep(0.5)
    cold, _ = cuda_mib()

    # 只拖慢第一份引擎：它的预热会一直卡在 sleep 里，3 秒的 join 必定超时
    real_new_engine = manager._new_stream_engine
    created = []

    def slow_new_engine():
        engine = real_new_engine()
        if not created:
            created.append(engine)
            real_warmup = engine.warmup

            def slow_warmup(*a, **kw):
                time.sleep(args.slow_warmup)
                return real_warmup(*a, **kw)

            engine.warmup = slow_warmup
        return engine

    # 顺便验那句次序：轮次号必须在 join **之前**自增（这里取最后一次叫停时的值，
    # 也就是新一轮 `_prepare_streaming` 第 1 步那次）
    seen = {}
    real_signal = manager._signal_stream_stop

    def probing_signal():
        seen["round_at_signal"] = manager._stream_round
        return real_signal()

    samples = []
    stop_sampler = threading.Event()

    def sampler():
        while not stop_sampler.is_set():
            alloc, reserved = cuda_mib()
            samples.append((stream_threads(), alloc, reserved))
            stop_sampler.wait(0.1)

    manager._new_stream_engine = slow_new_engine
    manager._signal_stream_stop = probing_signal
    try:
        manager.start_recording(device)
        time.sleep(0.5)                 # 旧线程正卡在 slow_warmup 里
        manager.stop_recording()
        time.sleep(0.5)
        sampler_thread = threading.Thread(target=sampler, daemon=True)
        sampler_thread.start()
        manager.start_recording(device)

        check(seen.get("round_at_signal") == manager._stream_round,
              "轮次号在 join 之前就自增了（叫停时 %s，新一轮 %s）"
              % (seen.get("round_at_signal"), manager._stream_round))
        alive = stream_threads()
        check(alive >= 2, "确实撞上了 join 超时那一支（此刻活着 %d 条流式线程）" % alive)

        ready = wait_stream_ready(manager, 120)
        settled = wait_for(lambda: stream_threads() == 1, 40)
        time.sleep(0.5)
        stop_sampler.set()
        sampler_thread.join(timeout=3)

        max_threads = max((s[0] for s in samples), default=0)
        allocs = [s[1] for s in samples if s[1] is not None]
        max_alloc = max(allocs) if allocs else None
        hot, _ = cuda_mib()
        own = None if (hot is None or cold is None) else hot - cold
        note("采样 %d 次：最多 %d 条流式线程，峰值已分配 %s（一份 whisper 约 %s）"
             % (len(samples), max_threads, fmt(max_alloc), fmt(own)))

        check(ready, "新一轮照样起来了（状态 %s）" % manager._stream_state)
        check(settled, "旧线程自己退干净了（现在 %d 条）" % stream_threads())
        entry = ledger("asr_simul")
        check(entry is not None and entry["release_count"] >= 1,
              "被丢下的那份引擎真的卸过（release_count=%s）"
              % (entry["release_count"] if entry else "无此项"))
        # 这一支**允许短暂重叠**：新线程不等旧线程（那正是超时的意义），旧线程还在
        # 加载时新的也开始加载。要证的是"有上限、不失控"，不是"从不同驻"。
        if max_alloc is not None and own is not None and own > 0:
            check(max_alloc <= cold + own * 2.2 + 64,
                  "折腾期间显存最多两份 whisper 的量（峰值 %s）" % fmt(max_alloc))

        manager.stop_recording()
        wait_for(lambda: stream_threads() == 0, 20)
        model_residency.release_all(force=True)
        free_cuda_cache()
        time.sleep(0.5)
        final, final_reserved = cuda_mib()
        # **这一条才是关键**：改造前那个被丢下的引擎谁也引用不到，这里会停在
        # "基线 + 一份 whisper"，而且怎么点「释放显存」都下不去。
        if final is not None and cold is not None:
            check(final <= cold + 64,
                  "折腾完之后显存回到基线（%s → %s，保留 %s）"
                  % (fmt(cold), fmt(final), fmt(final_reserved)))
        else:
            note("没有 CUDA，显存那几项跳过")
    finally:
        manager._new_stream_engine = real_new_engine
        manager._signal_stream_stop = real_signal
        stop_sampler.set()


def check_batch_ledger(manager):
    """"加载了整句模型但没产出文本"也必须在账本上

    账本原来只认 `touch`（= 识别出文本）过的项，于是预览识别、静音段、识别异常这几条
    路径上，整句模型**占着显存而账上写着没占**：`release_others` / `release_all` /
    `sweep` 一律跳过它，连界面上的「释放显存」按钮都放不掉。修法是在**加载完成那一刻**
    就记账（`AudioProcessor._mark_model_resident`）。

    做法最直接：`get_model()` 加载一次、一个字的音频都不喂。与后端无关（走到这条路
    的恰恰是流式失败回退之后的那一轮）。
    """
    from model_residency import model_residency, free_cuda_cache

    print("— 账本：只加载、不产出文本的整句模型 —")
    manager.audio_processor.release_model()
    model_residency.release_all(force=True)
    free_cuda_cache()
    time.sleep(0.5)
    idle_alloc, _ = cuda_mib()
    on_gpu = getattr(manager.audio_processor, "device", "cpu") == "cuda"
    if not on_gpu:
        note("整句模型跑在 CPU 上：显存那几项跳过，账本那几项照验")

    from config import config

    model_name = config.get("whisper_model", "base")
    manager.audio_processor.get_model()
    hot, _ = cuda_mib()
    entry = ledger("asr_batch")
    check(manager.audio_processor.model is not None,
          "整句模型 %s 已加载进 AudioProcessor" % model_name)
    if on_gpu:
        check(hot is not None and idle_alloc is not None and hot > idle_alloc + 20,
              "它确实占了显存（%s → %s）" % (fmt(idle_alloc), fmt(hot)))
    check(entry is not None and entry["resident"],
          "一个字的文本都没产出，账本上照样记着它占着（resident=%s）"
          % (entry["resident"] if entry else "无此项"))

    previous = entry["idle_timeout"] if entry else None
    model_residency.set_idle_timeout("asr_batch", 1)
    time.sleep(1.2)
    freed = model_residency.sweep()
    free_cuda_cache()
    time.sleep(0.3)
    after_sweep, _ = cuda_mib()
    check(freed >= 1, "闲置到点后 sweep 放得掉它（放了 %d 项）" % freed)
    check(manager.audio_processor.model is None,
          "模型已经从 AudioProcessor 上卸下来了")
    if on_gpu:
        check(after_sweep is not None and idle_alloc is not None
              and after_sweep <= idle_alloc + 20,
              "sweep 之后显存回到加载前（%s → %s）" % (fmt(hot), fmt(after_sweep)))

    # 「释放显存」按钮走的是 release_all(force=True)：再加载一次验这条路
    manager.audio_processor.get_model()
    released, _ = model_residency.release_all(force=True)
    free_cuda_cache()
    time.sleep(0.3)
    after_all, _ = cuda_mib()
    check(released >= 1, "release_all 也放得掉它（放了 %d 项）" % released)
    check(manager.audio_processor.model is None,
          "「释放显存」这条路真的把模型卸下来了")
    if on_gpu:
        check(after_all is not None and idle_alloc is not None
              and after_all <= idle_alloc + 20,
              "release_all 之后显存也回到加载前（%s）" % fmt(after_all))
    model_residency.set_idle_timeout("asr_batch", previous or 0)


def check_ollama(config):
    """本地大模型那一段：真的卸得掉、清得掉，连不上也不抛异常"""
    print("— 本地大模型（Ollama）—")
    from translation.local_llm_translator import LocalLLMTranslator

    translator = LocalLLMTranslator()
    resident = translator.resident_models()
    if resident is None:
        note("连不上 %s：跳过这一段（last_error=%s）"
             % (config.get("local_llm_url", ""), translator.last_error))
        check(translator.unload() is False, "连不上时 unload() 返回 False")
        check(translator.unload_others(keep=None) == 0, "连不上时 unload_others() 返回 0")
        return

    for name, size, expires in resident:
        note("驻留：%s %.0f MiB，到期 %s" % (name, size, expires))

    model = config.get("local_llm_model", "")
    if not model:
        note("没有配置本地模型名，跳过")
        return
    if model not in [item[0] for item in resident]:
        note("%s 现在不在显存里：先热一下再验卸载" % model)
        ok, message = translator.preload()
        note("preload：%s（%s）" % (ok, message))
        if not ok:
            check(False, "preload 失败，没法验卸载：%s" % message)
            return

    check(translator.unload(model), "unload(%s) 成功" % model)
    time.sleep(0.5)
    names = [item[0] for item in (translator.resident_models() or [])]
    check(model not in names, "卸完之后 /api/ps 名单里没有它了（现在：%s）" % (names or "空"))

    # 关键：卸掉当前模型必须清掉"热过"的记忆，否则下一句按 3 秒超时发、必然回落
    check(translator._warm_model is None,
          "卸掉当前模型之后 _warm_model 已清（下一句会按冷加载放宽超时）")

    before = translator.unload_others(keep=None)
    note("unload_others(keep=None) 卸掉 %d 个" % before)
    remaining = [item[0] for item in (translator.resident_models() or [])]
    check(not remaining, "清场之后显存里没有模型了（现在：%s）" % (remaining or "空"))

    translator.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
