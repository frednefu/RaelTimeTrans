# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Windows 桌面实时语音翻译工具：捕获麦克风或系统声音 → OpenAI Whisper 识别 → 检测源语言 → Google 翻译 → 悬浮字幕窗口显示，并可选保存 SRT 字幕。面向业余无线电通信场景（内置术语库）。

## Commands

Python 运行环境在 conda 环境 `realtimetrans` 中（环境名保存在 `conda_env.txt`，Conda 位于 `C:\ProgramData\miniconda3`）。所有 Python 命令需在该环境内执行，例如：

```powershell
C:\ProgramData\miniconda3\Scripts\activate.bat realtimetrans
python main.py
```

- 启动应用：`python main.py`（或 `start.bat`，提供正常/调试启动菜单）。入口是 `main.py`。
- 一键安装：`install.bat`（创建 conda 环境 + 依赖 + ffmpeg + GPU 支持）。修复依赖：`FixDependencies.bat`。
- 检查 GPU/CUDA：`python check_gpu.py`
- 排查"监听没声音"：`python check_audio_output.py [设备名关键词 | --index N]`，用同一段"嘀"声依次走 MME/WASAPI/DirectSound 几种播法，靠"响几声"判断是哪一层没出声。
- 运行测试：根目录下的 `test_*.py` 是独立的 `unittest` 脚本，直接运行单个文件，无统一测试框架：

```powershell
python test_term_replacement.py
python test_phonetic_conversion.py
python test_translation.py
python test_word_reveal.py      # 逐词字幕的显示调度（无音频/Whisper 依赖）
```

- 检查逐词时间轴：`python check_word_timestamps.py <wav> [模型] [设备]`
- 量同步误差是谁的锅：`python check_word_alignment.py [模型] [间隔秒 ...]`。用 Windows 自带语音合成把词按固定间隔摆好（真实起点已知），再跑一遍识别，打印"Whisper 给的词起点 vs 真值"的误差——用来分清"字幕对不上声音"是识别的时间轴不准，还是我们自己的播放进度算错了。

## Architecture

顶层是 `main.py` → `QApplication` + `gui/main_window.py` 的 `MainWindow`。各包职责：

- `gui/main_window.py` — 主窗口，承载所有设置项与"开始/停止翻译"按钮。通过 `QTimer`（200ms）轮询 `AudioManager`：先按播放进度推进逐词原文，再取最新整句识别文本交给后台翻译线程 `translation/translation_worker.py`，译文回来再补上（翻译不在 GUI 线程里做）。
- `gui/subtitle_window.py` — 无边框、置顶、半透明的悬浮字幕窗 `SubtitleWindow`，独立于主窗口，显示原文/译文。`set_original_words` 专门给逐词通路用（含逐词行的左对齐排版）。
- `gui/word_reveal.py` — `WordReveal`：拿带块号的词表 + 当前播放位置，算出"这一刻该显示到哪个词"（连同上那句的全文，给界面摆两行用），返回 None 表示不用重绘。纯逻辑（无 Qt/音频依赖）。单测见 `test_word_reveal.py`。
- `audio/audio_timeline.py` — 逐词字幕的时间轴数据结构（`TimedWord`/`WordSegment`/`AudioSegmentTask`），刻意做成不引入 whisper/torch 的叶子模块，供界面和单测导入。
- `audio/audio_manager.py` — `AudioManager`，音频管线编排中心。三条线程：录音（`_record_audio`，做音量 VAD 分段）→ 识别（`_recognize_audio`）→ 播放（`_playback_audio`，仅监听系统声音时）。用 `queue.Queue` 在线程间传 NumPy 音频数据。
- `audio/audio_processor.py` — `AudioProcessor`（Whisper 模型加载、CUDA/CPU 选择、降级逻辑）+ `WhisperThreadPool`（后台异步识别，带超时取消）。同步 `process_audio` 与异步 `process_audio_async(callback)` 两套接口。
- `translation/subtitle_manager.py` — `SubtitleManager`，基于 `googletrans` 的翻译，含翻译缓存与延迟统计。
- `translation/term_manager.py` — `TermManager`，业余无线电术语处理：信号报告转换（"five nine"→"59"）、字母解释法呼号还原（"Alpha Bravo"→"AB"）、术语占位符保护。
- `translation/subtitle_file_manager.py` — `SubtitleFileManager`，将识别结果写为 `Subtitles/*.srt`。
- `config.py` — 全局单例 `config`，JSON 持久化到 `settings.json`，自动补齐默认项。

### 关键数据流

音频 → 录音线程（VAD 分段）→ `audio_queue` → 识别线程 → `WhisperThreadPool` 异步识别 → 回调 → `result_queue`/`text_queue` → 主线程 `QTimer` 轮询 → `SubtitleManager.translate` → `SubtitleWindow.update_text`。

### 翻译管线（顺序固定）

`SubtitleManager.translate` 内依次执行：信号报告转换 → `direct_translate`（整词术语直译）→ 字母解释法呼号还原 → `preprocess_ham_radio_terms`（术语替换为 `__TERM_N__` 占位符）→ `googletrans` 翻译 → `restore_ham_radio_terms`（还原占位符）。

### 音频时钟与逐词字幕（原文跟着语音一个词一个词出现）

原来"整句识别完才显示"的原因：整句要等 0.5 秒静音才提交识别，结果回来时这句话早播完了。要做到逐词，必须**边说边识别**，并把词对齐到"用户此刻听到的音频"上。

- **绝对采集块号**：`AudioManager.captured_chunks` 是录音开始以来读到的块数（1 块 = 1024 样本 ≈ 64ms），只增不减，相当于本轮录音的时钟。音频段带着 `start_chunk`/`end_chunk`/`utterance_id` 进识别队列；词时间由 `_timed_words` 换算成 `start_chunk + round(word.start * 16000 / 1024)`。
- **播放位置**：`get_play_position_chunks()` = 采集块号 − 播放队列积压（`playback_queue.qsize() + _OUTPUT_BUFFER_CHUNKS`，上限 `_MAX_LAG_CHUNKS`）。监听关闭或播放线程已死时按实时采集算。**这就是"变动的延迟"的正解**：不用手动填滑块，数一数还有多少块没播出去就知道了。（`audio_delay_enabled/audio_delay_ms` 那套手动延迟已删除。）
- **预览识别**（`kind="partial"`）：说话过程中每 `partial_interval_ms`（默认 1000ms）用当前缓冲区快照跑一次识别，只喂逐词显示。它**绝不排队**（线程池忙就跳过这一帧，`process_audio_async` 返回 None）、**绝不进 `text_queue`/SRT/翻译**——半截句子的错识别只能在屏幕上闪一下，最终结果一到就整句替换。
- **显示**：`WordReveal.tick_line(play_chunk)` 选"起点不晚于播放位置的最近一段"，把起点已过的词拼成一行，另外给出**上一句的全文**（`previous_text`）。识别慢了会一次补齐（不卡住、不倒着走），一句话说完而下一句未开始则继续显示上一句；当前行文本、上一句文本、句号三者都没变就返回 None，界面不会无端重排。（`tick()` 是只返回文本的旧接口，单测在用。）
- **排版**（`SubtitleWindow.set_original_words`）：逐词行固定**左对齐**（`_apply_reveal_layout` 设 `AlignLeft|AlignVCenter`），新词在右边接着长，左边的字一动不动——居中会每多一个字就把整行重排一次，看着一直在抖。不挪标签本身（标签仍占满整行、超长照旧换行），只用样式表给文字留出固定的左边留白：`_label_stylesheet` 写的是 `padding: Npx; padding-left: (N+REVEAL_LEFT_MARGIN)px;`（长写覆盖简写），所有标签样式都从这一个出口走，免得别处设颜色时把这个留白抹掉。整句通路（原文整句/译文，走 `_set_sentence_text`）写进来的文本一律恢复居中排版——"仅显示译文"模式下逐词原文刚占着译文行。
- **原文两行**（上一句 + 当前句）：`_compose_reveal_text` 把上一句按 `_reveal_avail_width`（标签宽 − 左右内边距 − 左边留白）用 `QFontMetrics.elidedText` 截断，再和当前句用 `\n` 拼成两行——上一句在上、当前句在下，便于顺着上下文听（像 YouTube）。宽度必须按左边留白一起扣，宽一点点上一句就会折成两行、把当前句挤出可见范围。只有原文行这么做（`_reveal_two_lines()`：逐词开着、没选"不翻译"、且不是"仅显示译文"模式）。
- **窗口高度**：两行原文 + 译文比用户设的 `window_height`（settings.json 现为 80）高，所以原文标签的最小高度按两行算（`adjustLabelHeights`），窗口在 `show()`/`showEvent`/`set_subtitle_mode` 里按 `max(window_height, _required_height())` 撑高（`_fit_window_height`），否则第二行会被切掉。逐词开关关掉时 `reset_reveal_layout` 把两行恢复居中并把高度退回用户设置。
- **不翻译**（目标语言选"不翻译"→ `target_language = "none"`）：只走原文通路，不提交翻译请求，字幕窗只留原文行（`SubtitleWindow.translation_disabled` 会强制隐藏译文行）。
- 排查工具：`python check_word_timestamps.py <wav> [模型] [设备]` 打印每词时间轴，用来区分"逐词不生效"是模型问题还是设置问题。开关 `word_by_word_enabled=False` 可完全退回整句行为。

## 需要注意的约定与陷阱

- **`settings.json` 是运行时的活配置**，被 git 跟踪，`config.set()` 每次都会立即写回文件。改动配置逻辑时留意兼容旧字段（`main_window.py` 的 `check_and_update_settings` 负责旧版本迁移）。**写文件必须原子**（`save_settings` 先写 `settings.json.tmp` 再 `os.replace`，另有 `_write_lock` 防多线程互踩）：曾经直接 `open('w')` 把文件截成 0 字节，结果所有设置静默回落到默认值（模型从 tiny 变 base）；`load_settings` 现在遇到坏文件会打印错误并留一份 `.broken` 备份，不再默默用默认值。
- **工作线程里绝不能让 print/警告抛异常**：标准流句柄失效时（重定向到已关闭的管道、无控制台），线程里的任何一句 print、tqdm 进度条或 `warnings.warn` 都会抛 `OSError [WinError 6] 句柄无效`，把整次识别结果一起毁掉（`main.py` 为此最先执行 `install_safe_streams()`，`safe_stream.SafeStream` 把写失败降级为丢弃）。Whisper 侧尤其注意 **`transcribe_options` 里必须 `verbose=None`**：进度条的开关条件是 `disable=verbose is not False`，也就是说 `verbose=False` 反而会打开进度条，而进度条写 stderr。本机 Triton 不可用，词对齐会走慢速 numpy DTW 并在 stderr 发一条 `Failed to launch Triton kernels` 警告，也走同一层兜底。
- **音频一律走 MME 主机接口**（`AudioManager._enumerate_devices`）。本机实测（虚拟声卡回环验证）：DirectSound 能打开、能写入、能读设备名，但送出去的全是静音，采集侧同样失效；WASAPI 只接受设备原生采样率，16kHz 报 -9997。所以两个方向都用 MME，代价是设备名被截断到 31 字符。**若将来要换主机接口，先跑 `check_audio_output.py` 用耳朵+回环确认能出声，别只看 `p.open()` 是否成功**——DirectSound 就是这样骗过人的。
- **设备索引不可信，一律按名字重新解析**（`AudioManager.resolve_device_index`）：标签里的 `(Index: N)` 只是生成列表那一刻的快照，插拔耳机/蓝牙都会让索引整体错位。播放/录音前都按名字重新匹配，匹配时**先在自己用的那个主机 API 里找**（MME 名字被截断，完整名反而只存在于 DirectSound 条目里，先看完全匹配会挑到那个不出声的 API）。**唯一的例外是名字完全相同的设备**（两台同型号显示器，MME 截断后显示成同一条）：这时若标签里的索引仍指向一台同名设备就采用它，否则选同名设备里的第一台——实测两台 DELL 里只有接了音箱那台出声，不认索引就会把声音送进没音箱的那台且毫无提示。
- **Windows 特化**：设备名有两层处理——`clean_device_name` 修乱码/资源串（参与匹配），`display_device_name` 再去掉驱动样板名与被截断的半个括号（只用于下拉框显示，如 `DELL S2721DGF (NVIDIA High Defi` → `DELL S2721DGF`）。所以判断"是不是虚拟声卡/显示器接口"必须看原始名（`MainWindow._raw_device_name`），整理过的显示名里已经没有 `NVIDIA High Definition` 这些关键词了。此外：用 `os.startfile` 打开目录/文件；批处理脚本仅面向 Windows。
- **Whisper 版本：环境里是 `openai-whisper==20231117`**（`requirements.txt` 同步），torch 2.0.1+cu118。**20250625 升过一次、已回退**：它的 SDPA 路径在 torch 2.0.1 上跑不通，运行两分钟内 `direct_error.log` 就攒了 39 条 traceback（`RuntimeError: Expected key.size(1) == value.size(1)`、`cannot reshape tensor of 0 elements into shape [1, 0, 12, -1]`；而且崩过一次之后 `find_alignment` 注册的 cross-attention hook 会残留下来，`timing.py` 里那句 `QKs.__setitem__(index, outs[-1][0])` 接着报 `TypeError: 'NoneType' object is not subscriptable`）。**症状是逐词字幕消失、整句一次性蹦出来**：预览识别（`kind="partial"`）出错时在 `on_partial_complete` 里被静默丢弃，`WordReveal` 拿不到词，只有最终整句的结果到了屏幕上才有字。**要再升级得先把 torch 升上去**（或者强制 `use_sdpa=False`）。升级也换不来精度：两个版本的 `find_alignment`（softmax + 中值滤波 + DTW）、`_ALIGNMENT_HEADS`、模型 URL 完全一致。**词与声音对不上时别指望换版本解决**：实测（`check_word_alignment.py`）词起点误差随词间静音变长而变大——间隔 0.6 秒平均早 308ms，1.5 秒平均早 1032ms（DTW 会把一个词的跨度铺到前面的静音上），而同一份数据的**词中点**误差只有 12ms/432ms。间隔很小（正常说话）时起点误差不大，那时字幕偏了要查播放延迟的估算（`_OUTPUT_BUFFER_CHUNKS` 只按 2 块 ≈128ms 算，蓝牙耳机实际输出延迟远不止，字幕会整体偏晚）。要真正做到 YouTube 那样的对齐得换强制对齐方案（WhisperX 一类，wav2vec2 音素级对齐），不是换 Whisper 版本。
- **从文件识别要有 `ffmpeg.exe` 在 PATH 上**（`check_word_timestamps.py`、`check_word_alignment.py`）：20231117 经 `ffmpeg-python`（`openai-whisper` 的依赖，装它时自带）调 ffmpeg，20250625 改成直接 `subprocess` 调，两者都要那个二进制。conda 里的那份在 `envs\realtimetrans\Library\bin`，只有激活环境（`start.bat` / `activate.bat`）才在 PATH 里；直接用 `envs\...\python.exe` 跑脚本要自己把这个目录加进 PATH。实时识别传的是 NumPy 数组，不走这条路。
- **Whisper 模型**：默认缓存于 `~/.cache/whisper`，首次使用自动下载。`load_model` 对 large 模型有 GPU 显存不足降级 medium/CPU 的逻辑。
- **翻译依赖网络**（Google 翻译免费接口），无网络或限流时翻译会失败——`translate` 失败时回退返回原文/已处理文本，而非抛异常。
- **调试日志**：`audio/audio_manager.py` 内 `DEBUG_MODE = True` 会向控制台输出大量日志（日志同时写入 `whisper_model.log`）；`gui/main_window.py` 的 `DEBUG_MODE = False`。
- 术语库位于 `translation/resources/ham_radio_terms.json`，可通过编辑 JSON 扩展，`TermManager` 负责加载/校验/保存。
