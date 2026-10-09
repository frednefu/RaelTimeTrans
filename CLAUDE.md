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
```

## Architecture

顶层是 `main.py` → `QApplication` + `gui/main_window.py` 的 `MainWindow`。各包职责：

- `gui/main_window.py` — 主窗口，承载所有设置项与"开始/停止翻译"按钮。通过 `QTimer`（500ms）轮询 `AudioManager` 取最新识别文本，然后调用 `SubtitleManager.translate` 翻译并更新字幕窗口。
- `gui/subtitle_window.py` — 无边框、置顶、半透明的悬浮字幕窗 `SubtitleWindow`，独立于主窗口，显示原文/译文。
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

## 需要注意的约定与陷阱

- **`settings.json` 是运行时的活配置**，被 git 跟踪，`config.set()` 每次都会立即写回文件。改动配置逻辑时留意兼容旧字段（`main_window.py` 的 `check_and_update_settings` 负责旧版本迁移）。
- **音频一律走 MME 主机接口**（`AudioManager._enumerate_devices`）。本机实测（虚拟声卡回环验证）：DirectSound 能打开、能写入、能读设备名，但送出去的全是静音，采集侧同样失效；WASAPI 只接受设备原生采样率，16kHz 报 -9997。所以两个方向都用 MME，代价是设备名被截断到 31 字符。**若将来要换主机接口，先跑 `check_audio_output.py` 用耳朵+回环确认能出声，别只看 `p.open()` 是否成功**——DirectSound 就是这样骗过人的。
- **设备索引不可信，一律按名字重新解析**（`AudioManager.resolve_device_index`）：标签里的 `(Index: N)` 只是生成列表那一刻的快照，插拔耳机/蓝牙都会让索引整体错位。播放/录音前都按名字重新匹配，匹配时**先在自己用的那个主机 API 里找**（MME 名字被截断，完整名反而只存在于 DirectSound 条目里，先看完全匹配会挑到那个不出声的 API）。**唯一的例外是名字完全相同的设备**（两台同型号显示器，MME 截断后显示成同一条）：这时若标签里的索引仍指向一台同名设备就采用它，否则选同名设备里的第一台——实测两台 DELL 里只有接了音箱那台出声，不认索引就会把声音送进没音箱的那台且毫无提示。
- **Windows 特化**：设备名有两层处理——`clean_device_name` 修乱码/资源串（参与匹配），`display_device_name` 再去掉驱动样板名与被截断的半个括号（只用于下拉框显示，如 `DELL S2721DGF (NVIDIA High Defi` → `DELL S2721DGF`）。所以判断"是不是虚拟声卡/显示器接口"必须看原始名（`MainWindow._raw_device_name`），整理过的显示名里已经没有 `NVIDIA High Definition` 这些关键词了。此外：用 `os.startfile` 打开目录/文件；批处理脚本仅面向 Windows。
- **Whisper 模型**：默认缓存于 `~/.cache/whisper`，首次使用自动下载。`load_model` 对 large 模型有 GPU 显存不足降级 medium/CPU 的逻辑。
- **翻译依赖网络**（Google 翻译免费接口），无网络或限流时翻译会失败——`translate` 失败时回退返回原文/已处理文本，而非抛异常。
- **调试日志**：`audio/audio_manager.py` 内 `DEBUG_MODE = True` 会向控制台输出大量日志（日志同时写入 `whisper_model.log`）；`gui/main_window.py` 的 `DEBUG_MODE = False`。
- 术语库位于 `translation/resources/ham_radio_terms.json`，可通过编辑 JSON 扩展，`TermManager` 负责加载/校验/保存。
