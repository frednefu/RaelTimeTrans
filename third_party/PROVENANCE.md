# third_party/ 里的东西从哪来

## simulstreaming（流式识别）

- **上游**：https://github.com/ufal/SimulStreaming （MIT，见 `simulstreaming/LICENCE.txt`）
- **pin 的提交**：`077ea37d5ab4ff98bc567e4507f140dc4e5d5ad6`（2026-06-19，"Merge pull request #44"）
- **取的时间**：2026-10-10
- **为什么要用它**：AlignAtt 策略的流式解码，边说边出**已确认前缀**。这是"原文跟着语音一个词
  一个词出现"从"整句识别完才显示"里解放出来的关键（现有 `_submit_partial` 是每 1 秒把整个
  缓冲区重识别一遍，识别慢了就整句一起蹦出来）。可行性验证见 `check_simul_stream.py`
  的文件头与结论：本机 torch 2.0.1+cu118 / sm_61 上实时倍率 0.15~0.22，词时间是**绝对流时间**
  （实测中位误差 80~140ms），与 EuroLLM 同驻不 OOM。
- **为什么整段拷进来而不是 pip 装**：它不在 PyPI 上；而且这条路**不需要任何新 pip 依赖**
  （只用 torch / numpy / tiktoken / regex / more_itertools，本机都有），正好绕开"Python 3.8
  装不上 2025 年的轮子"这个死结（faster-whisper / ctranslate2 / transformers 一个都不用碰）。
  上游自己带了一份 whisper fork（`simul_whisper/whisper/`），所以用的不是环境里那个
  `openai-whisper`，两者互不干扰。

### 拷了什么

```
simulstreaming_whisper.py                 上游仓库根的驱动文件（SimulWhisperASR / SimulWhisperOnline，
                                          以及 init(offset=)/insert_audio_chunk/process_iter/finish）
simulstreaming/LICENCE.txt                上游 MIT 许可证，原样
simulstreaming/whisper/token_buffer.py
simulstreaming/whisper/whisper_streaming/base.py
simulstreaming/whisper/simul_whisper/**   含它自带的 whisper fork 与 assets/
                                          （gpt2.tiktoken / multilingual.tiktoken / mel_filters.npz，
                                          按路径加载，所以必须一起拷）
```

### 没拷什么（用不到，且会拖进额外依赖）

- `simulstreaming/whisper/whisper_streaming/` 里的 `whisper_online_main.py`、`whisper_server.py`、
  `silero_vad_iterator.py`、`vac_online_processor.py`：我们不做 VAD（句尾仍由 `AudioManager`
  自己的能量 VAD 判），也不走它的管道/服务端；拷了会把 silero（要 **librosa/soundfile**）拉进来。
- `simulstreaming/translate/`（另一个方向的翻译）、`simulstreaming/utils/`。
- 上游仓库根的 CLI 脚本（`simulstreaming_whisper.py` 里的 `__main__` 段不执行；它的 argparse
  用了 Python 3.9 才有的 `BooleanOptionalAction`，本环境是 3.8 —— **只在这个模块被当成脚本
  跑、或调用 `simulwhisper_args()` 时才会求值**，我们两个都不做）。

### 我们的改动

**源码一行没改**（`diff -r` 与上游逐字节一致）。只有一处删除：
`simul_whisper/whisper/assets/.history-machacek` —— 上游误提交的一份作者 shell 历史文件
（内容是 `cp ../../new-whisper/assets/mel_filters.npz .` 之类），不是代码，删掉。

### 升级时注意

1. 重新拉一份上游，`diff -r` 看改动，按上面两张清单重新拷，更新这里的 commit 与日期。
2. 跑 `python check_simul_stream.py` 复核：实时倍率、词时间是否是绝对流时间
   （`init(offset=T)` 那条）、显存、Triton 警告。这几项任何一项变了都要回头看我们的集成代码。
3. `frame_threshold` 越大字延迟越大但重解码越少；上游 CLI 默认 25，我们默认 12
   （实测最长字延迟 0.63s vs 0.95s，实时倍率 0.19 vs 0.15，都有余量）。
