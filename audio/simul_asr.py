"""流式识别引擎（SimulStreaming / AlignAtt 策略）：边说边出"已确认前缀"

上游的接口是"喂一块音频 → 解一次 → 拿到当前这一段假设"。直接照直觉用会踩三个坑，
都是 `check_simul_stream.py` 在本机实测出来的（那份探针留着，改这里之前先跑它）：

1. **它每次只回当前这一段**：第 1 次提交给 "Roger,"，第 2 次只给 "over, alpha" —— 上一段
   的词已经交出去了。所以这里必须把各段**攒起来**，否则屏幕上只剩最后半句。去重按词起点
   的秒数（上游保证时间轴单调不减，同一段被重复提交时词的起点一模一样）。
2. **词时间是绝对流时间**：`begin_utterance(offset_sec)` 内部走 `online.init(offset=…)`，
   于是词起点就是"整条流的第几秒"。调用方按 `_timed_words(words, 0)` 一步换算成采集块号，
   中间不用再补 offset。
3. **`finish()` 不是"整句重来一遍"**：它只解最后那一段，而且尾部静音多一点就会吐
   `[static]` 这种噪音幻觉（实测：尾部留 1.9 秒底噪 → "[static]"，掐到 1.2 秒 → 空）。
   所以这里把 `finish()` 的结果**并进**累积值，噪音幻觉整段丢掉（`looks_like_noise`）；
   终稿文本始终是"攒出来的那一整句"，不是它那个返回值。

本机实测的耗材（small、GTX 1070 Ti）：实时倍率 0.15~0.26，单次 `process_iter()` 150~270ms，
词起点误差中位 80~140ms，与 EuroLLM-Q8 同驻（整卡 5.3/8.2GB）不 OOM。**第一次解码要
~0.8 秒**（编译 CUDA 内核），所以开始翻译前必须先 `warmup()`，否则第一句话会卡住。

这个类**只在流式识别线程里用**（`AudioManager._stream_recognize`），内部不上锁：
喂音频、提交、收尾都由同一个线程按队列顺序做。
"""
import os
import re
import sys
import time
import traceback
from collections import namedtuple

import numpy as np

SAMPLE_RATE = 16000          # 上游把这个采样率写死在 OnlineProcessorInterface 里
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "whisper")

# whisper 对着静音/底噪"说"出来的东西：整个输出就是一对括号（或音符）包着的噪音标记
_NOISE_TOKEN = re.compile(r"^\s*[\[\(（【♪][^\]\)）】♪]{0,20}[\]\)）】♪]\s*$")

# 拼接两段文本时不加空格的前导字符（上游分段自带前后标点，硬加空格会变成 "five , nine"）
_NO_SPACE_BEFORE = "，。！？、；：,.!?;:…—）)】]}"


# 一个词：文本 + 它在**音频流**里的绝对起止秒数（换算成采集块号由调用方做）
StreamWord = namedtuple('StreamWord', ['text', 'start', 'end'])

# 一句话到目前为止的结果。words 是整句话攒下来的词（不是最后那一段）；
# end_sec 是"这句话已经喂到流里的哪个位置"，给界面定裁剪框的右边界用。
StreamResult = namedtuple('StreamResult', ['text', 'words', 'start_sec', 'end_sec',
                                           'is_final'])


def looks_like_noise(text):
    """整段输出是不是"噪音幻觉"（[static] / [BLANK_AUDIO] / ♪，或者干脆没有字母数字）

    这种文本绝不能进字幕 —— 它不是识别结果，是模型对着静音编的。
    """
    text = (text or "").strip()
    if not text:
        return True
    if _NOISE_TOKEN.match(text):
        return True
    return not any(ch.isalnum() for ch in text)


def join_parts(parts):
    """把各段的文本拼成整句（段首是标点时中间不加空格）"""
    out = ""
    for part in parts:
        part = (part or "").strip()
        if not part:
            continue
        if out and part[0] not in _NO_SPACE_BEFORE:
            out += " "
        out += part
    return out


def add_library_to_path(explicit=None):
    """把第三方源码目录插到 sys.path 最前（上游内部是按 `simulstreaming.*` 绝对导入的）

    认的是"同目录下既有 simulstreaming/ 包、又有 simulstreaming_whisper.py"这种长相：
    仓库里的 `third_party/`（见 third_party/PROVENANCE.md）和上游克隆目录都是这样。
    找不到返回 None。
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots = []
    if explicit:
        roots.append(explicit)
    env = os.environ.get("SIMULSTREAMING_HOME")
    if env:
        roots.append(env)
    roots.append(os.path.join(here, "third_party"))
    for root in roots:
        # 允许传包目录本身，也允许传仓库根
        for candidate in (root, os.path.dirname(os.path.abspath(root))):
            if (os.path.isfile(os.path.join(candidate, "simulstreaming_whisper.py")) and
                    os.path.isfile(os.path.join(candidate, "simulstreaming", "whisper",
                                                "whisper_streaming", "base.py"))):
                if candidate not in sys.path:
                    sys.path.insert(0, candidate)
                return candidate
    return None


class SimulStreamingEngine:
    """流式识别引擎。生命周期：load() → warmup() → 每句话 begin_utterance() → feed()* → commit()* → finalize()
    """

    def __init__(self, model="small", frame_threshold=12, commit_interval_ms=800,
                 min_chunk_ms=600, language="auto", audio_max_len=30.0, never_fire=False,
                 max_context_tokens=0, cache_dir=None, lib_dir=None, logdir=None):
        self.model_name = model
        self.frame_threshold = int(frame_threshold or 12)
        self.commit_interval_ms = int(commit_interval_ms or 800)
        self.min_chunk_ms = int(min_chunk_ms or 600)
        self.language = language or "auto"
        self.audio_max_len = float(audio_max_len or 30.0)
        self.never_fire = bool(never_fire)
        self.max_context_tokens = int(max_context_tokens or 0) or None
        self.cache_dir = cache_dir or _CACHE_DIR
        self.lib_dir = lib_dir
        self.logdir = logdir            # 上游默认会往工作目录写 wav，这里一律 None

        self.last_error = None          # 最近一次失败原因（界面要显示）
        self.load_ms = 0
        self.warmup_ms = 0
        self.commit_count = 0
        self.last_commit_ms = 0
        self.utterance_id = None

        self._asr = None
        self._online = None
        self._warmed = False            # CUDA 内核热过没有（见 warmup）
        self._words = []
        self._parts = []
        self._end_sec = 0.0
        self._pending_seconds = 0.0

    # ---------------------------------------------------------------- 装载

    @property
    def signature(self):
        """这一份引擎的"身份"：影响解码结果的构造参数全在里面

        `AudioManager` 靠它决定"能不能复用上一轮那个引擎"——签名一致就复用（省掉
        2.5 秒加载 + 1.4 GB 重载），不一致才卸掉重建。所以**任何会让解码行为改变的
        参数都必须进来**，否则改设置不生效（`commit_interval_ms` 虽是给调用方节流用的、
        不传给上游，但它同样得过期重建，一并算上）。

        `cache_dir` / `lib_dir` / `logdir` 属于环境而非调参，不进签名。
        """
        return (self.model_name, self.frame_threshold, self.commit_interval_ms,
                self.min_chunk_ms, self.language, self.audio_max_len,
                self.never_fire, self.max_context_tokens)

    @property
    def ready(self):
        return self._online is not None

    def model_path(self):
        return os.path.join(self.cache_dir, "%s.pt" % self.model_name)

    def load(self):
        """加载模型（懒加载：不调就不占显存）

        失败只记进 last_error、返回 False，**不抛异常** —— 仓库的约定是工作线程里任何
        异常都会毁掉整次识别，调用方靠 False 决定要不要退回整句识别。
        """
        if self._online is not None:
            return True
        try:
            lib = add_library_to_path(self.lib_dir)
            if lib is None:
                self.last_error = ("找不到流式识别源码（要 third_party/ 或 SIMULSTREAMING_HOME）")
                return False
            from simulstreaming_whisper import SimulWhisperASR, SimulWhisperOnline
            path = self.model_path()
            if not os.path.isfile(path):
                # 上游会自己去下载（和整句那条路一样，首次使用才下载）
                print("流式识别：本地没有 %s，交给上游下载" % path)
            started = time.time()
            self._asr = SimulWhisperASR(
                language=self.language,
                model_path=path,
                cif_ckpt_path=None,         # 没有 CIF 模型 → 末尾那个词一律截掉（前缀更稳）
                frame_threshold=self.frame_threshold,
                audio_max_len=self.audio_max_len,
                # 攒不够这么久的音频先不解码（上游 CLI 的 audio_min_len）
                audio_min_len=self.min_chunk_ms / 1000.0,
                segment_length=1.0,
                beams=1,
                task="transcribe",
                decoder_type="greedy",
                never_fire=self.never_fire,
                init_prompt=None,
                static_init_prompt=None,
                max_context_tokens=self.max_context_tokens,
                logdir=self.logdir,
            )
            self._online = SimulWhisperOnline(self._asr)
            self.load_ms = int((time.time() - started) * 1000)
            self.last_error = None
            return True
        except Exception as e:
            self._asr = self._online = None
            self.last_error = "流式识别模型加载失败：%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
            return False

    def unload(self):
        """把模型放掉（给显存腾地方：闲置回收、换参数重建、关窗口都走这里）

        必须先 `gc.collect()` 再 `empty_cache()`：torch 的缓存分配器只回收"已经没人
        引用"的块，而模型对象上挂着一圈引用（上游的 online/asr 互相指），不先断干净
        就有一大块拿不回来（实测漏掉这一步仍剩几百 MiB）。

        幂等：没加载过也能调。
        """
        self._asr = self._online = None
        self._warmed = False            # 模型没了，CUDA 内核得重编
        from model_residency import free_cuda_cache
        free_cuda_cache()

    def reset_session(self):
        """把"这一句话"的累积状态清掉（词表、文本、时间轴）

        正常路径用不上——`begin_utterance()` 自己会 `init(offset=…)` + `_reset()`。
        兜的是"上一轮没收尾干净就退出了"（超时未 join 的旧线程、异常退出）这种场景，
        复用引擎前顺手清一次。
        """
        self._reset()

    def warmup(self, seconds=1.5, force=False):
        """开始翻译前热一次：第一次解码要编译 CUDA 内核（本机实测 ~0.8 秒）

        走的是和正式识别一样的通路（init → insert_audio_chunk → process_iter），
        不是上游那个 `SimulWhisperASR.warmup()`（它直接往模型的音频缓冲区里塞东西，
        留下的状态会污染第一句话）。

        已经热过就直接返回（`force=True` 可以强制再热）：引擎复用时这一炮是白花的，
        而 `unload()` 会把 `_warmed` 清掉，所以"卸过再装"一定会重热，不会漏。
        """
        if self._warmed and not force:
            return True
        if not self.load():
            return False
        try:
            noise = np.random.default_rng(0).normal(
                0, 0.005, int(SAMPLE_RATE * seconds)).astype(np.float32)
            self._online.init(offset=0)
            step = SAMPLE_RATE // 10
            for start in range(0, len(noise), step):
                self._online.insert_audio_chunk(noise[start:start + step])
            started = time.perf_counter()
            self._online.process_iter()
            self.warmup_ms = int((time.perf_counter() - started) * 1000)
            self._reset()
            self._warmed = True
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = "流式识别预热失败：%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
            return False

    # ---------------------------------------------------------------- 一句话

    def begin_utterance(self, offset_sec, utterance_id=None):
        """开始一句话。offset_sec = 这句话在音频流里的起点秒数（词时间就从它起算）"""
        if not self.load():
            return False
        try:
            self._online.init(offset=float(offset_sec))
        except Exception as e:
            self.last_error = "流式识别开始新句失败：%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
            return False
        self._reset()
        self._end_sec = float(offset_sec)
        self.utterance_id = utterance_id
        return True

    def feed(self, chunk):
        """喂一块 16kHz 单声道 float32（AudioManager 的一块 = 1024 样本 ≈ 64ms）

        返回是否成功。`insert_audio_chunk` 只把数据挂进列表，真正花钱的是 commit()。
        """
        if self._online is None:
            return False
        try:
            block = np.ascontiguousarray(chunk, dtype=np.float32).reshape(-1)
            self._online.insert_audio_chunk(block)
        except Exception as e:
            self.last_error = "流式识别喂音频失败：%s: %s" % (type(e).__name__, e)
            return False
        self._pending_seconds += len(block) / float(SAMPLE_RATE)
        self._end_sec += len(block) / float(SAMPLE_RATE)
        return True

    def ready_to_commit(self):
        """攒够一个提交间隔了没有（对应 simul_commit_interval_ms）"""
        return self._pending_seconds * 1000.0 >= self.commit_interval_ms

    def commit(self):
        """解一次，返回**整句话到目前为止**的结果；还没有词就返回 None

        单次 150~270ms（small），所以调用方必须按 ready_to_commit() 节流，
        不能来一块解一次。
        """
        if self._online is None:
            return None
        started = time.perf_counter()
        try:
            out = self._online.process_iter()
        except Exception as e:
            self.last_error = "流式识别出错：%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
            self._pending_seconds = 0.0
            return None
        self.last_commit_ms = int((time.perf_counter() - started) * 1000)
        self.commit_count += 1
        self._pending_seconds = 0.0
        if out:
            self._absorb(out)
        if not self._words:
            return None
        return self._result(is_final=False)

    def finalize(self):
        """句尾收尾：把最后没提交的那点音频解掉，返回整句话的最终结果

        只把 `finish()` 的结果**并进**累积值；文本永远是我们攒出来的那一整句。
        一个词都没有（这句话太短，没到 audio_min_len）时返回 None。
        """
        if self._online is None:
            return None
        started = time.perf_counter()
        try:
            out = self._online.finish()
            if out:
                if looks_like_noise(out.get("text")):
                    # 尾部的 [static]/"." 是幻觉，它的"词"同样是幻觉产物，一起丢掉
                    out = {}
                self._absorb(out)
        except Exception as e:
            self.last_error = "流式识别收尾失败：%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
        self.last_commit_ms = int((time.perf_counter() - started) * 1000)
        self._pending_seconds = 0.0
        if not self._words:
            return None
        return self._result(is_final=True)

    @property
    def text(self):
        """到目前为止整句话的文本（各段拼起来）"""
        return join_parts(self._parts)

    @property
    def detected_language(self):
        """上游解析出来的语种代码（语种设为 auto 时才有意义），拿不到就返回 None

        界面上的"识别语种"标签和"源语言=目标语言就不用翻"这两处都靠它；上游每解完
        一段会清空再重新判一次，所以只在 commit() 之后读有意义。
        """
        model = getattr(self._online, "model", None) if self._online is not None else None
        return getattr(model, "detected_language", None)

    def status(self):
        """一句话状态（界面上"流式状态"标签用）"""
        if self.last_error:
            return "出错：%s" % self.last_error
        if self._online is None:
            return "未加载（%s）" % self.model_name
        return "运行中（%s，已提交 %d 次，上次 %d ms）" % (
            self.model_name, self.commit_count, self.last_commit_ms)

    # ---------------------------------------------------------------- 内部

    def _reset(self):
        self._words = []
        self._parts = []

    def _absorb(self, out):
        """把上游这一次的结果并进累积值（它只回当前这一段，见模块开头第 1 条）"""
        for word in (out or {}).get("words") or []:
            try:
                start = float(word["start"])
                end = float(word["end"])
            except (KeyError, TypeError, ValueError):
                continue
            text = (word.get("text") or word.get("word") or "").strip()
            if not text:
                continue
            if any(abs(start - seen.start) < 1e-6 for seen in self._words):
                continue                    # 同一段被重复提交过，别把同一个词攒两份
            self._words.append(StreamWord(text, start, max(start, end)))
        self._words.sort(key=lambda w: w.start)
        text = (out or {}).get("text") or ""
        if text.strip() and text.strip() not in self._parts:
            self._parts.append(text.strip())

    def _result(self, is_final):
        return StreamResult(
            text=self.text, words=list(self._words),
            start_sec=self._words[0].start if self._words else self._end_sec,
            end_sec=self._end_sec, is_final=is_final)
