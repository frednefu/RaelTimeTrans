"""反复「开始/停止翻译」会不会把显存攒满——量一遍，并打印每一步的账

用法：
    python check_gpu_reclaim.py [--cycles 5] [--backend simul|batch] [--model small]
                                [--device 名字关键词] [--skip-ollama] [--keep-warm]

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
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

def run_cycle(manager, device, seconds):
    """真实地开始一轮录音、等一会儿、再停止（和用户点按钮是同一套动作）"""
    manager.start_recording(device)
    started = manager.is_running
    time.sleep(seconds)
    manager.stop_recording()
    return started


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=5, help="做几轮开始/停止")
    parser.add_argument("--backend", default="simul", choices=["simul", "whisper_batch"])
    parser.add_argument("--model", default="", help="流式模型（不给就用配置里的 simul_model）")
    parser.add_argument("--device", default="", help="输入设备名的关键词（不给就用配置里那个）")
    parser.add_argument("--seconds", type=float, default=1.5, help="每轮录多久")
    parser.add_argument("--skip-ollama", action="store_true", help="跳过本地大模型那一段")
    parser.add_argument("--skip-sweep", action="store_true", help="跳过闲置自动回收那一段")
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
        run_cycle(manager, device, args.seconds)
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
            started = run_cycle(manager, device, args.seconds)
            alloc, reserved = cuda_mib()
            used, total = nvidia_smi_mib() or (None, None)
            engine_after = manager.stream_engine
            threads = stream_threads()
            rows.append({"index": index, "alloc": alloc, "reserved": reserved,
                         "threads": threads, "smi": used, "engine": engine_after,
                         "load_ms": getattr(engine_after, "load_ms", None)})
            note("第 %d 轮：started=%s 已分配 %s 保留 %s 卡上 %s 线程 %d 引擎 %s 加载 %s"
                 % (index, started, fmt(alloc), fmt(reserved), fmt(used), threads,
                    "复用" if engine_after is engine_before else "新建",
                    ("复用" if getattr(engine_after, "load_ms", None) == load_ms_before
                     else "%s ms" % getattr(engine_after, "load_ms", "?"))))

        print("— 判定 —")
        check(all(row["threads"] <= 1 for row in rows),
              "每轮结束时活着的流式识别线程数不超过 1（实测 %s）"
              % [row["threads"] for row in rows])
        if args.backend == "simul":
            check(all(row["engine"] is rows[0]["engine"] for row in rows),
                  "第 2 轮起复用同一个引擎对象（不重新加载模型）")
            check(len({row["engine"] for row in rows}) == 1,
                  "整个过程中只存在一份流式引擎（签名没变就不该重建）")
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
