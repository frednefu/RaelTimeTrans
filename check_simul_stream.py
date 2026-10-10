"""SimulStreaming 流式识别的可行性探针：这台老机器上到底跑不跑得动

Stage 2 要把"整句批处理识别（0.5 秒静音才提交 + 整句 whisper）"换成 SimulStreaming 的
**流式解码**（AlignAtt 策略），边说边出**已确认前缀**，再把这个前缀交给本地 EuroLLM
边翻边长。整套东西压在一个假设上：上游那份代码（ufal/simulstreaming）能在**本机的老环境**
里跑起来 —— torch 2.0.1+cu118、sm_61（没有 Tensor Core、没有 BF16）、Python 3.8。
这个假设不成立，Stage 2 一天都不该开工。这个脚本就是那道闸门，之后留作诊断脚本。

五个必须回答的问题（就是下面几节）：

1. **装得上吗**：从 ~/.cache/whisper 直接加载 small.pt（不重新下载）、跑通一次流式推理。
   注意 `PaddedAlignAttWhisper` 是拿 `model_path` 的**目录**当 `download_root`、拿 basename
   当模型名去找 .pt 的，所以指到缓存目录就等于复用现有模型文件（但那份文件必须和上游
   URL 里的 sha256 一致，否则它照样会重下）。
2. **多快**：每次 `process_iter()` 的耗时与**实时倍率**（< 1 才跟得上说话；单次耗时还必须
   小于提交间隔，否则字还没出来就欠账了）。另外单独量一次**预热**的代价：第一次解码要
   ~1 秒（CUDA 内核编译），Stage 2 得在开始翻译前先热一下，不然第一句话会卡住。
3. **时间轴是不是绝对的**（Stage 2 的命根子）：`init(offset=T)` 之后词起点必须是"整条流的
   绝对秒数"。音频管理器里只有一步换算（`_timed_words`：
   `start_chunk + round(word.start*16000/1024)`），它默认词时间已经是绝对的。这里拿
   `check_word_alignment.py` 那套**词位置已知**的合成语音当真值：把 offset 设成 2.5 秒，
   再看识别出的词是落在"真值 + 2.5"上（绝对），还是落在"真值"上（从 0 起算的相对时间）。
4. **终稿靠不靠得住**：`finish()` 是拿整段音频一把解码（不再按注意力截断），尾部那段静音
   会被 whisper 当成"有内容"而胡说（本机实测：尾部留 1.4 秒底噪时终稿出来的是 "[static]"，
   把前面认出来的词全丢了）。应用里句尾由 VAD 判定、尾部静音不多，所以这里也量一遍
   "把尾部静音掐到 0.5 秒"之后终稿是否正常。**Stage 2 必须据此决定终稿要不要兜底。**
5. **显存够不够与 EuroLLM 同驻 + 有没有炸**：GTX 1070 Ti 只有 8GB，EuroLLM-Q8 常驻约 3.5GB，
   所以先在只有 whisper 的情况下量一遍，再把 EuroLLM 拉进显存重跑一遍。triton 在 sm_61 上
   必然不可用（`timing.py` 会发一条 "Failed to launch Triton kernels" 并退到慢速 numpy 内核），
   确认它只是慢，不是崩。

用法：

    python check_simul_stream.py                     # small，自动找库，跑全流程
    python check_simul_stream.py medium              # 换模型（专门看显存够不够）
    python check_simul_stream.py --lib <目录>        # 指定含 simulstreaming 包的源码目录
    python check_simul_stream.py --no-eurollm        # 跳过"与 EuroLLM 同驻"那一段
    python check_simul_stream.py --wav <文件>        # 用自己的音频（16k 单声道 wav）
    python check_simul_stream.py --frame-threshold 4,12,25   # 比不同注意力阈值下的字延迟
    python check_simul_stream.py --language auto             # 不指定语种（应用默认走这条）
    python check_simul_stream.py --long-sec 25               # 加测"连着说 25 秒"的单次提交耗时
                                                             # （simul_max_utterance_sec 的依据）

真值那一段要用 Windows 自带的语音合成（SAPI），没有它就只能看时间轴是否单调。
"""
import os
import re
import subprocess
import sys
import tempfile
import time
import warnings

import torch

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1024                       # 和 AudioManager 一块一样（≈64ms）
CHUNK_MS = CHUNK_SAMPLES * 1000.0 / SAMPLE_RATE
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
DEFAULT_OFFSET = 2.5       # 假装这句话从流的第 2.5 秒开始 —— 用来验"词时间是绝对的"
DEFAULT_THRESHOLDS = [12, 25]
GAP = 0.6                  # 合成语音里词与词的间隔（正常语速）
MATCH_TOLERANCE = 0.35     # 词起点和真值差这么多秒以内就算对上了（词间隔 0.6 秒）
# whisper 对着静音/底噪的典型"输出"：整个输出就是一对括号包着的噪音标记（[static]、
# [BLANK_AUDIO]、[Music]、♪ 之类）。这种文本是幻觉，不是识别结果。
NOISE_TOKEN = re.compile(r"^\s*[\[\(（【♪][^\]\)）】♪]{0,20}[\]\)）】♪]\s*$")


def parse_args(argv):
    opts = {"model": "small", "lib": None, "wav": None, "offset": DEFAULT_OFFSET,
            "commit_ms": 1000.0, "chunk_ms": CHUNK_MS, "thresholds": list(DEFAULT_THRESHOLDS),
            "language": "en", "eurollm": True, "long_sec": 0.0}
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--lib", "--wav", "--offset", "--commit-ms", "--chunk-ms",
                   "--frame-threshold", "--language", "--long-sec"):
            if i + 1 >= len(argv):
                raise SystemExit("%s 后面要跟一个值" % arg)
            value = argv[i + 1]
            if arg == "--lib":
                opts["lib"] = value
            elif arg == "--wav":
                opts["wav"] = value
            elif arg == "--offset":
                opts["offset"] = float(value)
            elif arg == "--commit-ms":
                opts["commit_ms"] = float(value)
            elif arg == "--chunk-ms":
                opts["chunk_ms"] = float(value)
            elif arg == "--language":
                opts["language"] = value
            elif arg == "--long-sec":
                opts["long_sec"] = float(value)
            else:
                opts["thresholds"] = [int(v) for v in value.split(",") if v.strip()]
            i += 2
        elif arg == "--no-eurollm":
            opts["eurollm"] = False
            i += 1
        else:
            rest.append(arg)
            i += 1
    if rest:
        opts["model"] = rest[0]
    return opts


def find_library(explicit):
    """把"含 simulstreaming 包的源码目录"插到 sys.path 最前面（找不到返回 None）

    认的是上游仓库根这种长相（Stage 2 里 third_party/ 也是这个长相）：
    同目录下既有 simulstreaming/ 包，又有 simulstreaming_whisper.py。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    roots = []
    if explicit:
        roots.append(explicit)
    env = os.environ.get("SIMULSTREAMING_HOME")
    if env:
        roots.append(env)
    roots.append(os.path.join(here, "third_party"))
    for root in roots:
        # 允许把包目录本身、或它的父目录传进来
        for candidate in (root, os.path.dirname(os.path.abspath(root))):
            if (os.path.isfile(os.path.join(candidate, "simulstreaming_whisper.py")) and
                    os.path.isfile(os.path.join(candidate, "simulstreaming", "whisper",
                                                "whisper_streaming", "base.py"))):
                if candidate not in sys.path:
                    sys.path.insert(0, candidate)
                return candidate
    return None


def section_env():
    print("=" * 78)
    print("1/5 环境")
    print("-" * 78)
    print("  torch        : %s（CUDA %s，cudnn %s）"
          % (torch.__version__, torch.version.cuda, torch.backends.cudnn.version()))
    if not torch.cuda.is_available():
        print("  [失败] 没有可用的 CUDA —— 流式识别在 CPU 上跟不住实时，到此为止")
        return False
    props = torch.cuda.get_device_properties(0)
    print("  显卡         : %s（sm_%d%d，显存 %.1f GB）"
          % (torch.cuda.get_device_name(0), props.major, props.minor,
             props.total_memory / 2 ** 30))
    print("  算力         : 无 Tensor Core 的 sm_%d%d —— 上游不用 torch.compile/amp，只是慢"
          % (props.major, props.minor))
    return True


def load_engine(lib, model, threshold, language):
    """照上游 CLI 的组装方式造一个流式引擎

    不走它的 `simulwhisper_args()`：那个函数的 argparse 用了 Python 3.9 才有的
    `BooleanOptionalAction`（本环境是 3.8），而且我们要的参数比它少得多。
    """
    from simulstreaming_whisper import SimulWhisperASR, SimulWhisperOnline
    model_path = os.path.join(CACHE_DIR, model + ".pt")
    if not os.path.isfile(model_path):
        print("  [注意] %s 不在，上游会自己去下载（要联网）" % model_path)
    else:
        print("  复用现有模型文件: %s（%.0f MB）"
              % (model_path, os.path.getsize(model_path) / 2 ** 20))
    started = time.time()
    asr = SimulWhisperASR(
        language=language,
        model_path=model_path,
        cif_ckpt_path=None,      # 没有 CIF 模型 → 最后一个词一律截掉（前缀更稳，代价是短一点）
        frame_threshold=threshold,
        audio_max_len=30.0,
        audio_min_len=1.0,       # 攒够 1 秒才开始解码（上游 CLI 的默认值）
        segment_length=1.0,
        beams=1,
        task="transcribe",
        decoder_type="greedy",
        never_fire=False,
        init_prompt=None,
        static_init_prompt=None,
        max_context_tokens=None,
        logdir=None,             # 关掉落盘：上游默认会往工作目录写 logdir/seg_*/iter_*.wav
    )
    load_ms = (time.time() - started) * 1000
    print("  模型加载     : %.0f ms，载入后显存 %.0f MiB（峰值 %.0f MiB）"
          % (load_ms, torch.cuda.memory_allocated() / 2 ** 20,
             torch.cuda.max_memory_allocated() / 2 ** 20))
    print("  推理设置     : language=%s，frame_threshold=%d，without_timestamps=%s"
          % (language, threshold, asr.model.decode_options.without_timestamps))
    return asr, SimulWhisperOnline(asr)


def warmup(online, seconds=1.5):
    """先喂一段噪声跑一遍：第一次解码要编译 CUDA 内核，实测 ~1 秒

    走的是应用将来一样的通路（init → insert_audio_chunk → process_iter），
    不是上游那个 `SimulWhisperASR.warmup()`（它直接往模型缓冲区里塞音频，
    留下的状态会污染后面那一轮）。
    """
    import numpy as np
    noise = np.random.default_rng(0).normal(0, 0.005, int(SAMPLE_RATE * seconds)).astype(np.float32)
    online.init(offset=0)
    step = SAMPLE_RATE // 10
    for start in range(0, len(noise), step):
        online.insert_audio_chunk(noise[start:start + step])
    started = time.perf_counter()
    online.process_iter()
    cost = time.perf_counter() - started
    print("  预热         : 第一次解码 %.0f ms（之后每次就只要一两百毫秒）" % (cost * 1000))
    return cost


def build_test_audio():
    """合成一段词位置已知的音频，返回 (音频, 每个词的真实起点秒数)

    直接复用 check_word_alignment.py 那套：SAPI 把每个词各念一个 wav，按固定间隔摆好，
    每个词的真实起点 = 间隔 × 序号 + 这段语音自己的起音点。底噪 -40dB（不是数字静音，
    数字静音会让对齐失去参照）。
    """
    import check_word_alignment as cwa
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        clips = cwa.synth_words(tmp)
        if not clips:
            return None, None
        audio, truth = cwa.build_grid(clips, GAP, np.random.default_rng(20261010))
    return audio, truth


def read_wav(path):
    import check_word_alignment as cwa
    return cwa.read_clip(path), None


LONG_GAP = 0.45            # 长句测试的历史参数（现在是 SAPI 念整段话，见 synth_passage）
_LONG_PASSAGE = (
    "CQ CQ CQ, this is station Alpha Bravo Five Niner calling, and listening on the "
    "forty meter band. The weather here is cloudy with light rain, and the temperature "
    "is about eighteen degrees. My receiver is a small transceiver running one hundred "
    "watts into a dipole antenna. Please come back to me with your signal report and "
    "your location, over. ")
_LONG_PS = """Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$en = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'en*' }} | Select-Object -First 1
if ($en) {{ $s.SelectVoice($en.VoiceInfo.Name) }}
$s.SetOutputToWaveFile("{out}")
1..3 | ForEach-Object {{ $s.Speak("{text}") }}
$s.SetOutputToNull()
$s.Dispose()
"""


def synth_passage(outdir):
    """让 SAPI 把一整段话念三遍存成一个 wav（约 70 秒的自然连续语音）

    **长句测试必须用真实语音，不能用"同一批词重复摆"**：后者会让贪婪解码陷进重复
    循环（本机实测：20 秒的重复词表识别出 141 个词 ≈ 7 词/秒，正常语速只有 2.6），
    而 `finish()` 内部写死了 `frames_threshold=4`（比我们的 12 松得多），一旦解不
    出句尾就一路解到 448 token 上限，词对齐的张量跟着涨到 GB 级 —— 实测定稿一次
    要 75 秒、吃掉 5GB 显存。真实语音同一长度上是 150~190ms（见表）。
    """
    path = os.path.join(outdir, "passage.wav")
    script = os.path.join(outdir, "say.ps1")
    with open(script, "w", encoding="utf-8") as f:
        f.write(_LONG_PS.format(out=path.replace("\\", "\\\\"), text=_LONG_PASSAGE))
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", script], check=False, capture_output=True)
    return path if os.path.exists(path) else None


def build_long_audio(seconds):
    """造一段"连着说了很久"的真实语音，返回 (音频, None)

    内容不重复（SAPI 念一段话），长度靠截取 —— 内容重复会踩上面那条解码死循环。
    """
    import check_word_alignment as cwa
    with tempfile.TemporaryDirectory() as tmp:
        path = synth_passage(tmp)
        if not path:
            return None, None
        audio = cwa.read_clip(path)
    if len(audio) < seconds * SAMPLE_RATE:
        return None, None
    return audio[:int(seconds * SAMPLE_RATE)], None


def run_long(online, audio, opts):
    """长句：每次提交记一次耗时，看它什么时候追上提交间隔

    为什么单独量：上游每次 `process_iter()` 都要把**当前这一整段**重新过一遍编码器，
    所以单次提交耗时随句长涨。它一旦超过提交间隔（`simul_commit_interval_ms`），
    识别就跟不上语速了 —— 每解一次花的时间比这段时间里说进来的话还多，越欠越多。
    这就是 `simul_max_utterance_sec` 该定多大的依据（本机 small、真实语音实测：
    5→30 秒单次提交 245→285ms、定稿 143→189ms，所以 25 秒很宽裕）。
    """
    chunk = max(1, int(opts["chunk_ms"] * SAMPLE_RATE / 1000))
    commit_chunks = max(1, int(round(opts["commit_ms"] / opts["chunk_ms"])))
    online.init(offset=0.0)
    stream_pos = 0.0
    since_commit = 0.0
    rows = []
    for index, start in enumerate(range(0, len(audio), chunk)):
        block = audio[start:start + chunk]
        online.insert_audio_chunk(block)
        seconds = len(block) / float(SAMPLE_RATE)
        stream_pos += seconds
        since_commit += seconds
        if (index + 1) % commit_chunks:
            continue
        t0 = time.perf_counter()
        out = online.process_iter()
        cost = time.perf_counter() - t0
        rows.append((stream_pos, cost, len((out or {}).get("words") or [])))
        since_commit = 0.0
    t0 = time.perf_counter()
    final = online.finish()
    final_cost = time.perf_counter() - t0

    print("    已喂音频    单次提交   占间隔")
    for pos, cost, words in rows:
        print("    %7.2fs %8.0fms %7.0f%%%s"
              % (pos, cost * 1000, cost * 1000 / opts["commit_ms"] * 100.0,
                 "   ← 超过提交间隔，开始欠账" if cost * 1000 > opts["commit_ms"] else ""))
    over = sum(1 for _, cost, _ in rows if cost * 1000 > opts["commit_ms"])
    worst = max([cost for _, cost, _ in rows] or [0])
    print("    共 %.2f 秒：%d 次提交，单次最慢 %.0f ms（提交间隔 %.0f ms），"
          "超出 %d 次，终稿 %.0f ms"
          % (len(audio) / float(SAMPLE_RATE), len(rows), worst * 1000,
             opts["commit_ms"], over, final_cost * 1000))
    return {"rows": rows, "over": over, "worst": worst, "final_cost": final_cost,
            "seconds": len(audio) / float(SAMPLE_RATE)}


def nvidia_used():
    """整卡已用显存（MiB）—— 同驻检查看的是这个数，不是 torch 自己报的那个"""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            used, total = out.stdout.strip().splitlines()[0].split(",")
            return int(used), int(total)
    except Exception:
        pass
    return None, None


def run_stream(online, audio, opts, tag):
    """按 AudioManager 的节奏喂音频，返回这一轮的统计

    节奏是刻意照抄应用里的：一次 64ms（1024 样本），每 `commit_ms` 才调一次
    `process_iter()`（对应后续的 simul_commit_interval_ms）。要看的两个数：
    单次 `process_iter()` 的耗时，以及**最新词从"被念出来"到"能显示"隔了多久**
    （= 此刻的流位置 − 该词起点）—— 那就是流式识别这一环的延迟。

    **上游每次只回"当前这一段"的词和文本**（本机实测：第 1 次提交给 "Roger,"、
    第 2 次给 "over, alpha" —— 上一段的词就交出去了），所以跨段的词要自己攒：
    这里按 `start` 去重后累积成整句话的词表，`out["start"]/["end"]` 是这一段的绝对
    起止秒（也是绝对流时间）。应用里同样得攒，正好对应现在 `WordSegment` 那套。
    `finish()` 的结果单独记，见 finish_report 的说明。
    """
    chunk = max(1, int(opts["chunk_ms"] * SAMPLE_RATE / 1000))
    commit_chunks = max(1, int(round(opts["commit_ms"] / opts["chunk_ms"])))
    online.init(offset=opts["offset"])      # ← 关键：让词时间从"绝对流时间"起算
    print("  喂法: %d 样本/次（%.0f ms），每 %d 次提交一次（≈%.0f ms），offset=%.2fs"
          % (chunk, chunk * 1000.0 / SAMPLE_RATE, commit_chunks,
             commit_chunks * chunk * 1000.0 / SAMPLE_RATE, opts["offset"]))

    stream_pos = opts["offset"]             # 这条流已经走过多少秒（词时间的参照系）
    since_commit = 0.0
    calls = []                              # (提交耗时s, 覆盖音频s)
    all_words, segments, lags = [], [], []
    for index, start in enumerate(range(0, len(audio), chunk)):
        block = audio[start:start + chunk]
        online.insert_audio_chunk(block)
        seconds = len(block) / float(SAMPLE_RATE)
        stream_pos += seconds
        since_commit += seconds
        if (index + 1) % commit_chunks:
            continue
        t0 = time.perf_counter()
        out = online.process_iter()
        cost = time.perf_counter() - t0
        calls.append((cost, since_commit))
        if out:
            words = out.get("words") or []
            segments.append((out["start"], out["end"], out["text"].strip()))
            for word in words:              # 跨段自己攒（上游只回当前这一段）
                if not any(abs(word["start"] - seen["start"]) < 1e-6 for seen in all_words):
                    all_words.append(word)
            all_words.sort(key=lambda w: w["start"])
            newest = max(w["start"] for w in words)
            lags.append(stream_pos - newest)
            print("    [流位置 %5.2fs] 提交 %5.0f ms（+%.2fs 音频，实时倍率 %.3f）"
                  " 段[%.2f→%.2f] 最新词「%s」延迟 %.2fs → %s"
                  % (stream_pos, cost * 1000, since_commit,
                     cost / since_commit if since_commit else 0,
                     out["start"], out["end"], words[-1]["text"].strip(),
                     stream_pos - newest, out["text"].strip()))
        since_commit = 0.0

    t0 = time.perf_counter()
    final = online.finish()
    final_cost = time.perf_counter() - t0
    final_text = (final or {}).get("text", "").strip()
    final_words = (final or {}).get("words") or []
    print("    句尾终稿: %5.0f ms → %s" % (final_cost * 1000, final_text or "（空）"))

    audio_seconds = len(audio) / float(SAMPLE_RATE)
    total = sum(c for c, _ in calls)
    worst = max([c for c, _ in calls] or [0])
    print("  合计: %.2f 秒音频，%d 次提交，累计 %.0f ms，实时倍率 %.3f，"
          "单次最慢 %.0f ms，终稿 %.0f ms%s"
          % (audio_seconds, len(calls), total * 1000, total / audio_seconds,
             worst * 1000, final_cost * 1000,
             "，最长字延迟 %.2fs" % max(lags) if lags else ""))
    return {"tag": tag, "words": all_words, "segments": segments,
            "final_words": final_words, "final_text": final_text, "calls": calls,
            "rtf": total / audio_seconds if audio_seconds else 0, "worst": worst,
            "final_cost": final_cost, "max_lag": max(lags) if lags else 0.0}


def _hits(starts, expected, tolerance=MATCH_TOLERANCE):
    """expected 里有几个点在 starts 里找得到（差在容差内）"""
    return sum(1 for e in expected if any(abs(s - e) <= tolerance for s in starts))


def compare_words(words, truth, offset, label):
    """词起点 vs 真值：分辨"绝对流时间"和"从 0 起算的相对时间"

    判法不看词数对不对得上（分词和真值的粒度天然不同，"niner" 可能被切成
    "nine" + "er"），而是看这些词落在**哪一套时间轴上**：
    - 落在「真值 + offset」上 → 绝对流时间（Stage 2 的换算直接可用）；
    - 落在「真值」上 → 相对时间（换算还得自己补 offset）。
    offset 有 2.5 秒，两套时间轴差着 2.5 秒，容差 0.35 秒，不可能看错。
    """
    if not words:
        print("  [失败] %s：一个词都没识别出来" % label)
        return False
    starts = [w["start"] for w in words]
    print("  %s: %s" % (label, " ".join("%s@%.2f" % (w["text"].strip(), w["start"])
                                       for w in words)))
    monotonic = all(b >= a - 1e-9 for a, b in zip(starts, starts[1:]))
    if not monotonic:
        print("  [注意] 时间轴不是单调不减（上游本来会强制非递减，出现说明有问题）")
    if not truth:
        print("  （没有真值可比：只报时间轴本身）")
        return monotonic

    absolute_hits = _hits(starts, [t + offset for t in truth])
    relative_hits = _hits(starts, truth)
    print("  对真值（含 offset %.2fs）命中 %d/%d；当成「从 0 起算」只有 %d/%d"
          % (offset, absolute_hits, len(truth), relative_hits, len(truth)))
    nearest = [min(abs(s - (t + offset)) for t in truth) for s in starts]
    if nearest:
        nearest.sort()
        print("  每个词的最近邻误差: 中位 %.0f ms，最大 %.0f ms"
              % (nearest[len(nearest) // 2] * 1000, nearest[-1] * 1000))
    absolute = absolute_hits > relative_hits
    print("  → %s" % ("词时间是**绝对流时间**（offset 那一项在），"
                      "Stage 2 的 start_chunk 换算直接可用"
                      if absolute else
                      "词时间像是**从 0 起算的相对时间**（没有 offset 那一项），"
                      "Stage 2 的换算得自己补 offset"))
    return absolute and monotonic


def finish_report(result):
    """`finish()` 那段输出靠不靠得住

    `finish()` 是把当前缓冲区一把解码（不再按注意力截断），尾部那段静音会被 whisper
    当成有内容而胡说。而且它同样**只回最后这一段**，不是整句话 —— 所以终稿不能当成
    "整句重来一遍"，只能当成"最后那点没提交的音频的补充"。

    三种输出，三种处理（Stage 2 照这个来）：
    - 空 → 什么都不添，用攒好的前缀收尾（正常情况，尾部静音短的时候就是这样）；
    - `[static]` 这类方括号噪音标记 → 幻觉，**绝不能进字幕**；
    - 有真实新词 → 补进去。
    """
    text = result["final_text"]
    if not text:
        print("  [通过] 终稿为空 → 一个字都不添，攒好的前缀原样收尾")
        return True
    if NOISE_TOKEN.match(text):
        print("  [注意] 终稿是噪音幻觉「%s」：这种输出绝不能进字幕（Stage 2 见下）" % text)
        return False
    print("  [通过] 终稿有真实新词「%s」→ 补进去即可" % text)
    return True


def check_eurollm():
    """把本地 EuroLLM 拉进显存并真翻一句（同驻检查的前半截）"""
    from translation.local_llm_translator import LocalLLMTranslator
    translator = LocalLLMTranslator()
    ok, message = translator.self_test()
    print("  EuroLLM: %s —— %s" % ("正常" if ok else "失败", message))
    return ok


def main():
    opts = parse_args(sys.argv[1:])
    print("SimulStreaming 可行性探针（模型 %s）" % opts["model"])
    if not section_env():
        return 1

    lib = find_library(opts["lib"])
    if lib is None:
        print("\n[失败] 找不到 simulstreaming 源码。用 --lib 指定目录，"
              "或把源码放到 third_party/ 下。")
        return 1
    print("  代码来自     : %s" % lib)

    print("\n" + "=" * 78)
    print("2/5 载入模型 + 预热")
    print("-" * 78)
    torch.cuda.reset_peak_memory_stats()
    try:
        asr, online = load_engine(lib, opts["model"], opts["thresholds"][0], opts["language"])
        warmup(online)
    except Exception as e:
        print("  [失败] 模型装不上：%s: %s" % (type(e).__name__, e))
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 78)
    print("3/5 造一段词位置已知的音频")
    print("-" * 78)
    trimmed = None
    if opts["wav"]:
        audio, truth = read_wav(opts["wav"])
        print("  用 %s（%.2f 秒，无真值）" % (opts["wav"], len(audio) / float(SAMPLE_RATE)))
    else:
        audio, truth = build_test_audio()
        if audio is None:
            print("  [失败] SAPI 合成不出语音（见 check_word_alignment.py），也没给 --wav")
            return 1
        print("  %d 个词按 %.1f 秒间隔摆好，共 %.2f 秒，词的真实起点已知"
              % (len(truth), GAP, len(audio) / float(SAMPLE_RATE)))
        # 掐掉尾部静音的那一份：应用里句尾由 VAD 判定，喂给终稿的尾部不会有 1.4 秒底噪
        end = int((truth[-1] + 1.2) * SAMPLE_RATE)
        trimmed = audio[:end]
        print("  另做一份「掐掉尾部静音」的（%.2f 秒，最后一个词之后再留 %.1f 秒），用来测终稿"
              % (len(trimmed) / float(SAMPLE_RATE),
                 len(trimmed) / float(SAMPLE_RATE) - truth[-1]))

    print("\n" + "=" * 78)
    print("4/5 流式推理：耗时、实时倍率、词时间是否是绝对流时间")
    print("-" * 78)
    results = []
    for index, threshold in enumerate(opts["thresholds"]):
        if index:
            print()
        # frame_threshold 是构造时烘进 cfg 的，但 infer() 每次都现读 self.cfg，
        # 所以直接改它就能换档，不用把模型重新加载一遍
        asr.model.cfg.frame_threshold = threshold
        print("  —— frame_threshold=%d ——" % threshold)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                result = run_stream(online, audio, opts, threshold)
            except Exception as e:
                print("  [失败] 流式推理崩了：%s: %s" % (type(e).__name__, e))
                import traceback
                traceback.print_exc()
                return 1
        triton = sorted({str(w.message) for w in caught if "Triton" in str(w.message)})
        print("  Triton 警告: %s" % ("；".join(triton) if triton else "无（说明没走到那条退路）"))
        result["triton"] = bool(triton)
        print("  整句话攒出来的词表（应用里要显示的就是它）:")
        result["times_ok"] = compare_words(result["words"], truth, opts["offset"], "  词")
        result["final_ok"] = finish_report(result)
        result["hits"] = _hits([w["start"] for w in result["words"]],
                               [t + opts["offset"] for t in truth]) if truth else 0
        results.append(result)

    print("\n  各档对比（frame_threshold 越小 = 只看更靠后的音频 = 字延迟越小，"
          "但重解码更频繁；上游默认 25）:")
    for result in results:
        print("    threshold=%-3s 实时倍率 %.3f，单次最慢 %4.0f ms，终稿 %4.0f ms，"
              "最长字延迟 %.2fs"
              % (result["tag"], result["rtf"], result["worst"] * 1000,
                 result["final_cost"] * 1000, result["max_lag"]))

    # 尾部静音对终稿的影响（Stage 2 要不要给终稿兜底的依据）
    long_tail_ok = all(r["final_ok"] for r in results)
    trimmed_ok = None
    if trimmed is not None:
        print("\n  尾部静音的影响（同一个 threshold=%d，只把最后那个词之后的静音"
              "掐短一段）:" % opts["thresholds"][0])
        asr.model.cfg.frame_threshold = opts["thresholds"][0]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = run_stream(online, trimmed, opts, "trimmed")
        compare_words(result["words"], truth, opts["offset"], "  词")
        trimmed_ok = finish_report(result)

    # 长句的代价：simul_max_utterance_sec 该定多大（--long-sec 才跑，默认 25 秒）
    long_result = None
    if opts["long_sec"]:
        print("\n  长句的代价（这一项决定 simul_max_utterance_sec 定多大）:")
        print("    每次提交都要把当前这**一整段**重新过一遍编码器，所以句子越长单次提交"
              "越慢；\n    一旦慢过提交间隔（%.0f ms）就跟不上语速了。音频是 SAPI 念的"
              "一整段真实话\n    （**别用「同一批词重复摆」来测**：那会把解码带进重复死循环，"
              "数字全不可信，见 synth_passage）。" % opts["commit_ms"])
        audio_long, _ = build_long_audio(opts["long_sec"])
        if audio_long is None:
            print("    [跳过] SAPI 合成不出语音")
        else:
            asr.model.cfg.frame_threshold = opts["thresholds"][0]
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                long_result = run_long(online, audio_long, opts)

    torch.cuda.synchronize()
    peak_alone = torch.cuda.max_memory_allocated() / 2 ** 20
    used_alone, total_mib = nvidia_used()
    print("\n  显存: torch 峰值 %.0f MiB%s"
          % (peak_alone,
             "，整卡已用 %d / %d MiB" % (used_alone, total_mib) if used_alone else ""))

    eurollm_ok = None
    if opts["eurollm"]:
        print("\n" + "=" * 78)
        print("5/5 与 EuroLLM 同驻（8GB 卡上两个模型一起待着）")
        print("-" * 78)
        eurollm_ok = check_eurollm()
        used_both, total_mib = nvidia_used()
        print("  两个都载入后，整卡已用 %s MiB"
              % (("%d / %d" % (used_both, total_mib)) if used_both else "（nvidia-smi 不可用）"))
        torch.cuda.reset_peak_memory_stats()
        print("  同驻下再跑一遍流式推理（frame_threshold=%d）:" % opts["thresholds"][0])
        asr.model.cfg.frame_threshold = opts["thresholds"][0]
        try:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                result = run_stream(online, audio, opts, "eurollm")
            result["times_ok"] = compare_words(result["words"], truth,
                                               opts["offset"], "  词")
        except torch.cuda.OutOfMemoryError as e:
            print("  [失败] 显存不够（EuroLLM + whisper 同驻 OOM）：%s" % e)
            eurollm_ok = False
        except Exception as e:
            print("  [失败] 同驻时崩了：%s: %s" % (type(e).__name__, e))
            import traceback
            traceback.print_exc()
            eurollm_ok = False
        if eurollm_ok:
            print("  同驻峰值显存: torch %.0f MiB，整卡 %s MiB"
                  % (torch.cuda.max_memory_allocated() / 2 ** 20,
                     nvidia_used()[0] or "?"))

    print("\n" + "=" * 78)
    print("结论：拦路的（不通过就别开工 Stage 2）")
    print("-" * 78)
    verdicts = [
        ("装得上（torch 2.0.1 + sm_61 上加载 %s.pt 并跑通流式推理）" % opts["model"], True),
        ("跟得上说话（实时倍率 < 1）", all(r["rtf"] < 1 for r in results)),
        ("单次提交不欠账（最慢一次 < 提交间隔 %.0f ms）" % opts["commit_ms"],
         all(r["worst"] * 1000 < opts["commit_ms"] for r in results)),
        ("词时间是绝对流时间（Stage 2 的 start_chunk 换算直接可用）",
         all(r["times_ok"] for r in results)),
    ]
    if truth:
        verdicts.append(("攒出来的整句词表把真值全打中（%d 个词）" % len(truth),
                         all(r["hits"] == len(truth) for r in results)))
    if long_result is not None:
        verdicts.append(("长句（%.1f 秒）也不欠账（单次最慢 %.0f ms < 提交间隔 %.0f ms）"
                         % (long_result["seconds"], long_result["worst"] * 1000,
                            opts["commit_ms"]),
                         long_result["worst"] * 1000 < opts["commit_ms"]))
    if eurollm_ok is not None:
        verdicts.append(("与 EuroLLM 同驻不 OOM（整卡还剩 %s MiB）"
                         % ((nvidia_used()[1] - nvidia_used()[0]) if nvidia_used()[0] else "?"),
                         bool(eurollm_ok)))
    for name, ok in verdicts:
        print("  [%s] %s" % ("通过" if ok else "不通过", name))
    passed = all(ok for _, ok in verdicts)

    print("\n注意事项（不拦路，但 Stage 2 必须照这个写）")
    print("-" * 78)
    print("  · 上游每次只回**当前这一段**的词和文本（实测：第 1 次给 \"Roger,\"，"
          "第 2 次给 \"over, alpha\"），\n    所以 StreamEngine 必须按 start 去重、"
          "把各段的词攒成整句话，不能拿最后一次的返回值当整句。")
    print("  · finish() 也不能当\"整句重来一遍\"（它只解最后那一段）：尾部静音 1.9 秒时"
          "它输出 %s，\n    %s"
          % ("噪音幻觉" if not long_tail_ok else "正常",
             ("掐到 1.2 秒后%s —— 所以 finalize 里要按 [static] 这类噪音标记过滤，"
              "并在 VAD 判句尾时就把尾部静音收住。"
              % ("仍然会幻觉" if trimmed_ok is False else "就正常了"))))
    print("  · Triton 那条警告是预期内的（sm_61 上没有可用的 triton，中位滤波退到慢速"
          "numpy 内核），\n    只影响速度不影响结果 —— 上面的实时倍率就是在它生效的情况下量的。")
    print("\n%s" % ("全部通过 —— 可以开工 Stage 2。" if passed
                    else "有拦路项 —— 先别动 Stage 2（保留 Stage 1 的收益）。"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
