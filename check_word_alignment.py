"""量一量 Whisper 的词时间轴准不准（对着已知位置的合成语音）

逐词字幕"跟声音对不上"时，先分清是谁的错：

- **Whisper 给的词起点本身就偏** → 换模型、升级版本都救不回来，要准就得换强制
  对齐（WhisperX 那类用 wav2vec2 做音素级对齐的方案）。
- **Whisper 的起点是准的** → 那是我们自己的播放进度算错了，去查
  `audio_manager._OUTPUT_BUFFER_CHUNKS`：它只按 2 块（128ms）估算输出设备自身的
  缓冲，蓝牙耳机（AirPods 这类）实际输出延迟远不止这些，字幕就会整体偏晚。

做法：用 Windows 自带的语音合成（SAPI）把几个单词各念成一个 wav，按固定间隔拼成
一条音频，每个词的真实起点就是"间隔 × 序号 + 这段语音自己的起音点"。再按应用同一
套 `transcribe_options()` 跑识别，把 Whisper 给的词起点和真值对比——差多少毫秒，
就是同步误差里 Whisper 那一份。

用法：
    python check_word_alignment.py                 # base 模型，间隔 0.3/0.6/1.5 秒
    python check_word_alignment.py small           # 换模型
    python check_word_alignment.py base 0.5 1.0    # 只跑指定间隔
只依赖 Windows 自带组件，不改 settings.json。
"""
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
import whisper

from audio.audio_processor import transcribe_options

SAMPLE_RATE = 16000
WORDS = ["roger", "over", "alpha", "bravo", "five", "niner"]
DEFAULT_GAPS = [0.3, 0.6, 1.5]
# 真实场景里词与词之间是本底噪声（电台底噪/房间底噪），不是数字静音：
# 数字静音会让对齐彻底失去参照，量出来的误差比实际用起来更大。
NOISE_DB = -40.0

_PS_SYNTH = """Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$en = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'en*' }} | Select-Object -First 1
if ($en) {{ $s.SelectVoice($en.VoiceInfo.Name) }}
foreach ($w in @({words})) {{
    $s.SetOutputToWaveFile((Join-Path '{out}' "$w.wav"))
    $s.Speak($w)
    $s.SetOutputToNull()
}}
$s.Dispose()
"""


def synth_words(outdir, words=WORDS):
    """用 SAPI 把每个词各念一个 wav（合成不了就返回空，由调用方决定怎么办）"""
    names = ",".join(f"'{w}'" for w in words)
    script = _PS_SYNTH.format(words=names, out=outdir.replace("\\", "\\\\"))
    path = os.path.join(outdir, "synth.ps1")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
                   check=False, capture_output=True)
    clips = [os.path.join(outdir, f"{w}.wav") for w in words]
    return clips if all(os.path.exists(c) for c in clips) else []


def read_clip(path):
    """读一个 16 位 PCM wav，转成 16kHz 单声道 float32"""
    with wave.open(path, "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        channels = wav.getnchannels()
        rate = wav.getframerate()
    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        n = int(len(data) * SAMPLE_RATE / rate)
        data = np.interp(np.linspace(0, len(data) - 1, n),
                         np.arange(len(data)), data).astype(np.float32)
    return data


def first_voiced(samples, rel=0.08):
    """这段音频从第几秒开始真的有人声（按 10ms 能量包络的头一次起跳）"""
    win = SAMPLE_RATE // 100
    if len(samples) < win:
        return 0.0
    rms = np.array([np.sqrt((samples[i:i + win] ** 2).mean())
                    for i in range(0, len(samples) - win, win)])
    active = rms > max(rms.max() * rel, 1e-4)
    idx = int(np.argmax(active)) if active.any() else 0
    return idx * 0.01


def build_grid(clips, gap, rng):
    """把词按固定间隔摆好，返回（音频, 每个词的真实起点）"""
    total = int(SAMPLE_RATE * (gap * (len(clips) - 1) + 2.0))
    buf = np.zeros(total, dtype=np.float32)
    truth = []
    for i, clip in enumerate(clips):
        samples = read_clip(clip)
        samples = samples[:int(SAMPLE_RATE * min(gap, 0.9))]  # 别蹭到下一个词的位置
        start = int(i * gap * SAMPLE_RATE)
        buf[start:start + len(samples)] += samples
        truth.append(i * gap + first_voiced(samples))
    buf += rng.normal(0, 10 ** (NOISE_DB / 20), total).astype(np.float32)
    return np.clip(buf, -1.0, 1.0), truth


def measure(model, clips, gap, rng):
    """跑一遍识别，返回 (词数, 起点误差ms, 中点误差ms)"""
    audio, truth = build_grid(clips, gap, rng)
    result = model.transcribe(audio, **transcribe_options("auto", device=model.device.type))
    got = [(w["word"].strip(), w["start"], w["end"])
           for seg in result["segments"] for w in seg.get("words", [])]
    if len(got) != len(truth):
        return len(got), None, None, result["text"].strip()

    starts = np.array([g[1] for g in got])
    mids = np.array([(g[1] + g[2]) / 2 for g in got])
    truth = np.array(truth)
    return len(got), (starts - truth) * 1000, (mids - truth) * 1000, result["text"].strip()


def main():
    args = sys.argv[1:]
    model_name = args[0] if args else "base"
    gaps = [float(a) for a in args[1:]] or DEFAULT_GAPS

    outdir = tempfile.mkdtemp(prefix="whisper_align_")
    clips = synth_words(outdir)
    if not clips:
        print("语音合成失败：需要 Windows 自带的 SAPI 语音（System.Speech）。")
        return 1

    device = "cuda" if _cuda_ok() else "cpu"
    print(f"whisper {whisper.__version__}，模型 {model_name}，设备 {device}")
    print(f"词间间隔 {gaps} 秒，底噪 {NOISE_DB}dB，合成音频在 {outdir}\n")
    print(f"{'间隔':>6} {'词数':>5} {'起点误差(平均/最大)':>22} {'中点误差(平均/最大)':>22}")
    print("-" * 62)

    model = whisper.load_model(model_name, device=device)
    rng = np.random.default_rng(0)
    for gap in gaps:
        count, start_err, mid_err, text = measure(model, clips, gap, rng)
        if start_err is None:
            print(f"{gap:6.1f} {count:5} 词数对不上（真值 {len(clips)}），识别: {text!r}")
            continue
        print(f"{gap:6.1f} {count:5} {start_err.mean():+9.0f}ms /{np.abs(start_err).max():8.0f}ms"
              f" {mid_err.mean():+15.0f}ms /{np.abs(mid_err).max():8.0f}ms")

    print("-" * 62)
    print("起点误差是负的 = Whisper 说这个词开始得比实际早（字幕会抢在声音前面）。")
    print("误差跟着间隔变大 = 词间静音越长偏得越多，这是 cross-attention + DTW 对齐")
    print("本身的性质，换模型/升级版本都不改变；要准只能上强制对齐（WhisperX 一类）。")
    print("间隔很小（正常说话）时起点误差不大，那同步偏了就得看播放延迟的估算。")
    return 0


def _cuda_ok():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
