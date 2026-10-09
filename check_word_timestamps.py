"""检查 Whisper 的词级时间轴是否正常（逐词字幕的前提）

用法：
    python check_word_timestamps.py                      # 用一段合成的"语音"跑通流程
    python check_word_timestamps.py 录音.wav              # 拿真实录音看每词时间
    python check_word_timestamps.py 录音.wav small cuda   # 指定模型和设备

直接用项目自己的 transcribe_options()（就是识别时用的那套解码参数），所以这里
能跑出词时间，就意味着实时字幕也能拿到。不改 settings.json，模型和设备只对本
次运行有效。

输出每词的起止秒数，判断标准：
- words 非空、start 单调不减 → 逐词字幕能一个词一个词冒出来；
- 一个词都没有 → 逐词显示会退化（整句一次性出现），要查 word_timestamps 支持；
- 第一个词不从 0 附近开始 → 音频开头有大段静音，属正常，字幕跟着静音一起等。
"""
import os
import sys
import wave

import numpy as np
import whisper

from audio.audio_processor import extract_word_timings, transcribe_options

SAMPLE_RATE = 16000


def load_wav(path):
    """读一个 WAV 文件，转成 whisper 要的 float32 单声道"""
    with wave.open(path, 'rb') as wav:
        if wav.getsampwidth() != 2:
            raise ValueError("只支持 16 位 PCM 的 WAV")
        frames = wav.readframes(wav.getnframes())
        channels = wav.getnchannels()

    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data


def make_test_tone(seconds=4.0):
    """没有 WAV 时的兜底：一段带包络的扫频音，能跑通流程但识别不出词"""
    t = np.linspace(0, seconds, int(SAMPLE_RATE * seconds), endpoint=False)
    envelope = np.minimum(1.0, np.minimum(t * 4, (seconds - t) * 4))
    tone = 0.3 * envelope * np.sin(2 * np.pi * (220 + 200 * t / seconds) * t)
    return tone.astype(np.float32)


def main():
    args = sys.argv[1:]
    path = args[0] if args else None
    model_name = args[1] if len(args) > 1 else "tiny"
    device = args[2] if len(args) > 2 else "cpu"

    if path:
        if not os.path.exists(path):
            print(f"找不到文件: {path}")
            return 1
        audio = load_wav(path)
        source = path
    else:
        audio = make_test_tone()
        source = "内置测试音（识别不出词是正常的，只看流程通不通）"

    print(f"音频来源: {source}")
    print(f"时长: {len(audio) / SAMPLE_RATE:.2f} 秒, 采样率: {SAMPLE_RATE}Hz")
    print(f"模型: {model_name}, 设备: {device}")
    print("-" * 60)

    model = whisper.load_model(model_name, device=device)
    result = model.transcribe(audio, **transcribe_options("auto", device=device))

    print(f"识别文本: {(result.get('text') or '').strip() or '(空)'}")

    words = extract_word_timings(result)
    if not words:
        print("\n没有词级时间轴 —— 逐词显示无法工作。")
        print("检查 whisper 版本是否是 requirements.txt 里的 openai-whisper==20231117，")
        print("以及 word_timestamps 是否还在 transcribe_options() 里。")
        return 1

    print(f"\n词级时间轴（共 {len(words)} 个词）:")
    last_start = -1.0
    monotonic = True
    for word in words:
        start, end = word["start"], word["end"]
        if start < last_start:
            monotonic = False
        last_start = start
        print(f"  {start:7.2f}s ~ {end:7.2f}s  {word['word']}")

    print("-" * 60)
    print(f"时间单调递增: {'是' if monotonic else '否（异常）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
