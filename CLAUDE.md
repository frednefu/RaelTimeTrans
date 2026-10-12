# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Windows 桌面实时语音翻译工具：捕获麦克风或系统声音 → Whisper 识别（整句批处理；或切 SimulStreaming **流式**边说边出）→ 检测源语言 → 翻译（默认本机 EuroLLM，可切 Google；原译文各自可选"逐词"——半截句子先翻先显示）→ 悬浮字幕窗口显示，并可选保存 SRT 字幕。面向业余无线电通信场景（内置术语库）。

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
python test_prefix_translation.py   # 「译文逐词显示」的界面调度（半截译文/终稿的先后次序）
python test_text_guards.py      # 「这段不是人话」判据（幻觉/复读；不含音频/Whisper/网络）
python test_model_residency.py  # 显存账本（全用假的释放回调，不碰显卡）
```

- 检查逐词时间轴：`python check_word_timestamps.py <wav> [模型] [设备]`
- 查本地翻译为什么慢/为什么丢术语/换个模型为什么失败：`python check_local_translate.py [模型名] [--no-google] [--no-cold]`。逐句计时并打印 tok/s（**GPU 约 95 tok/s；掉到 13 tok/s 就是没吃上显卡**）、验术语（59/CQ/73/收到）有没有出现在译文里**并拒收"提示词残渣"**（`ECHO_MARKERS`：思考型模型会把 `来源：…` 这套脚手架一起吐出来）、把服务地址指到死端口确认"连不上也不抛异常、回落已处理原文"、**把模型卸掉并把单句超时压到 300ms 证明冷加载不算进单句超时**（`--no-cold` 跳过这项，它会真的装卸模型），最后和谷歌后端同一句对比耗时。跑的时候会临时改 `settings.json` 里的服务地址/模型/超时，退出前恢复。
- 查流式识别（SimulStreaming）在这台机器上跑不跑得动、快不快：`python check_simul_stream.py [模型] [--long-sec 12] [--no-eurollm]`。它量的是当初拦住 Stage 2 的那几个数：加载与预热耗时、单次提交耗时与实时倍率、**词时间是不是绝对流时间**（拿 `check_word_alignment.py` 那套真值验）、终稿靠不靠得住、与 EuroLLM 同驻会不会 OOM；`--long-sec` 加测"连着说 N 秒"的单次提交耗时（`simul_max_utterance_sec` 的依据，**必须用真实语音**，见下）。
- 量同步误差是谁的锅：`python check_word_alignment.py [模型] [间隔秒 ...]`。用 Windows 自带语音合成把词按固定间隔摆好（真实起点已知），再跑一遍识别，打印"Whisper 给的词起点 vs 真值"的误差——用来分清"字幕对不上声音"是识别的时间轴不准，还是我们自己的播放进度算错了。
- 检查原文两行 / 换句滚动 / 译文行溢出上滚：`python check_reveal_scroll.py`。离屏（`QT_QPA_PLATFORM=offscreen`）喂一串脚本化的句子，每隔 20ms `grab()` 一次扫像素，用文字行的位置验几何：行距 = `lineSpacing()`、第一行贴框顶、逐词增长时位置不动、滚动全程不超两行且滚完停在原位、不翻译模式也两行、整句通路不被裁剪，以及上/中/下三处间隙相等、窗口高度正好贴内容、间隙随字号变（`--live` 用 settings.json 里那套）。译文行那几项按"框 = min(行数,3) 行、内容按实际行数、偏移 = (行数−3)×行距"验，外加**换句后上一句译文还留在框里**（不是被清掉）、同来源的新译文原地替换、`clear_translation` 连上一句一起清、切模式后偏移归零。另验两条**不是几何的**：关掉「原文逐词显示」后原文整句也左对齐（用左边第一个墨点验），且折成两行的整句不被裁、窗口跟着长；「仅显示译文」下逐词原文一个字都不许上屏（说话期间整窗无墨），译文只在整句译文到了才出现。不带音频/Whisper。
- 检查设置面板：`python check_settings_ui.py`。离屏建一次 `MainWindow`（不启音视频/识别），验整页在 `QScrollArea` 里、左右两列、"高级设置"默认收起、启动尺寸夹到屏幕可用区域，以及合并后的「语音识别设置」：只有一个模型下拉、候选随后端变、**流式后端下回填整句模型名不许写进 `simul_model`**、流式那几行按后端显隐，以及两个逐词开关（「原文逐词显示」/「译文逐词显示」）都在、勾选状态来自配置，旧的「边说边翻译」已经不存在、`simul_prefix_spin`（译文刷新间隔）两种后端下都看得见；末尾还验显存回收那几个控件——切到 Google 后「显存」状态行和「释放显存」按钮**照样在**（它们不在本地模型那一块里），闲置卸载旋钮/「自动回收」勾选状态来自配置，取消勾选会把账本三项的超时都设成 0（只认手动）；最后验**「显示音频数据统计信息」勾上之后界面上真的有数**：统计行和复选框在同一个组里、显隐跟着复选框走，喂一块假音频（`_update_audio_stats`）就显示采样率/块大小/本块峰值 RMS/本轮已采集秒数/底噪与判定阈值，停采半秒后瞬时值回零而本轮累计留着。脚本会写 settings.json（`resizeEvent` 存窗口大小），跑完原样放回。
- 查反复启停会不会把显存占满：`python check_gpu_reclaim.py [--cycles 5] [--backend simul|batch] [--model small] [--device 关键词] [--skip-ollama] [--skip-sweep] [--skip-paths] [--slow-warmup 5] [--settle 10] [--keep-warm]`。真录音、真装卸模型，每轮打印"活着的 `audio-stream-recognize` 线程数 / `memory_allocated` / `memory_reserved` / nvidia-smi / 引擎是复用还是新建 / 加载耗时 / 停完等到线程退出用了几秒"，判定线程数每轮回到 0~1、每轮手上都有一份引擎、**上一轮线程已经退干净时这一轮一律复用同一个引擎**（`--settle` 秒内没等到就只记一笔，那时重建是设计内的兜底——见下面 join 竞态那条，重建次数也有上限）、已分配显存不逐轮上涨；然后 `release_all(force=True) + free_cuda_cache()` 看回不回落到基线；再**热一轮 + 把闲置超时压到 1 秒 + 手动 `sweep()`**（单测里释放回调是假的计数器，只有这里能证明自动回收真把显存放下了）；最后验 Ollama 的 `unload` / `unload_others`（卸完 `/api/ps` 里确实没了、`_warm_model` 已清、连不上时返回 False/0 且不抛异常）。**照 CLAUDE.md 记的那套配置量就得给 `--model small`**——本机 settings.json 里 `simul_model` 可能是个 tiny（加载 536 ms / 153 MiB），小得看不出问题。脚本会改 settings.json 的 `asr_backend`（给了 `--model` 时还有 `simul_model`），跑之前备份、`finally` 原样放回（**内存里那两份也要放回去**：`config.set` 会把整个 settings 字典重写一遍，只还原文件、忘了内存，下一次 `set` 又把它写脏了）。
- **上面那 N 轮只是最短路径**（没语音、不失败、不建界面），所以脚本另外各造一次"只有真失败/真竞态/真漏账才走得到"的路（`--skip-paths` 全跳过）——用户报的"不是每次都撑满"恰恰在这些路上：
  - **失败回退**（`check_failure_fallback`）：注入一次 `commit()` 异常（`engine.ready_to_commit = lambda: True` + `engine.commit` 抛错，再从 `stream_queue` 外面塞一个 `begin` 事件当"VAD 认出了一句语音"）。验状态变 `failed`、`manager.stream_engine` 当场变 None、账本 `asr_simul` 记成没占着、`_stream_live()` 变 False、显存掉回空载。**改造前失败分支只置状态就 return**，失败的 whisper 留在显存里，紧接着回退整句识别又会加载**另一份**——两份同驻直到下次点开始。
  - **冷启时「停 → 立刻再开」**（`check_join_race`）：把**第一份**引擎的 `warmup` 人为拖慢（`--slow-warmup`，模拟大模型/慢磁盘）让 3 秒的 join 必定超时。验轮次号在 join **之前**就自增（`_signal_stream_stop` 那一刻的值就等于新一轮的 `_stream_round`）、确实有两条线程同时活着（说明真进了超时那一支）、旧线程自己退干净、被丢下的引擎 `release_count ≥ 1`、峰值显存有两份的上限、**折腾完回到基线**。这一支允许短暂重叠（新线程不等旧线程正是超时的意义），要证的是"有上限、且被丢下的那个会自己收尾"。
  - **账本漏账**（`check_batch_ledger`）：整句后端下**只 `get_model()` 加载、一个字的音频都不喂**。验加载完就上了账（`resident=True`）、`sweep()` 放得掉、再加载一次 `release_all(force=True)`（「释放显存」按钮走的就是它）也放得掉、两次都回到加载前的显存。**改造前只有"识别出文本"才记账**，于是预览/静音/识别异常这几条路上模型占着显存而账上写着没占，谁都不回收。
- 显存账本的单测（不碰显卡/音频/Qt，全用假的释放回调）：`python test_model_residency.py`

## Architecture

顶层是 `main.py` → `QApplication` + `gui/main_window.py` 的 `MainWindow`。各包职责：

- `gui/main_window.py` — 主窗口，承载所有设置项与"开始/停止翻译"按钮。通过 `QTimer`（200ms）轮询 `AudioManager`：先按播放进度推进逐词原文，再取最新整句识别文本交给后台翻译线程 `translation/translation_worker.py`，译文回来再补上（翻译不在 GUI 线程里做）；另有一路「译文逐词显示」（`translation_word_by_word`，两种识别后端都有）：把还没定稿的**半截原文**节流后送去翻译，译文跟着原文一起长（`_update_prefix_translation`，见"译文逐词显示"一节）。**设置面板**（`init_ui`）：整页装在 `QScrollArea` 里（一屏放不下就滚动，不裁内容），分组排成**左右两列**，"高级设置"（`QGroupBox` 可勾选 + 内部容器 `setVisible`，Qt 的勾选框自己不会折叠内容）默认收起，装的是不常改的项——流式的提交间隔/注意力阈值/一句话最长、本地服务的地址/接口类型/单句超时、字幕窗口宽高。启动尺寸按 `primaryScreen().availableGeometry()` 夹一下（本机存过 897×1360，比 1080p 屏还高）。「音频设备设置」组里那个只读标签 `audio_stats_label` 走**另一个 80ms 定时器**（`volume_timer`，和音量表同一个节拍）——200ms 的翻译定时器只在翻译进行中才跑，统计却要看"停了之后归零"（见「陷阱」里 `show_audio_stats` 那条）。
- **「语音识别设置」是合并出来的**（`_build_asr_group`）：整句 Whisper 和流式 SimulStreaming 共用一个**模型下拉** `asr_model_combo`，候选按后端取（`ASR_MODEL_CHOICES`：整句 tiny~large / 流式 tiny~medium），值各写各的键（`whisper_model` / `simul_model`）——所以配置不迁移、两个后端都记得自己选的模型。`on_asr_model_changed` 分派：整句沿用 `on_model_changed`（立刻加载进显存），流式只存配置。**坑在回填**：`_update_after_load` / `update_model_status` / `_force_unlock_ui` 会把"实际加载的整句模型"写回下拉，流式后端下这个下拉显示的是流式模型，直接写就会经信号把整句模型名写进 `simul_model`，所以那几处一律走 `_sync_asr_model_combo()`（非整句后端直接返回），而"整句的模型名"读 `_batch_model_name()` 而不是下拉文本。流式那两行（流式状态，及高级里的流式参数）与整句的状态行由 `_update_stream_controls_enabled()` 按后端显隐（以前是置灰）；**「译文刷新间隔」不在流式那一组里**——从前的「边说边翻译」只在流式后端下有效，现在的「译文逐词显示」（见下）两种后端都吃，所以节流间隔也跟着搬进公共的高级设置。
- `gui/subtitle_window.py` — 无边框、置顶、半透明的悬浮字幕窗 `SubtitleWindow`，独立于主窗口，显示原文/译文。两个标签各装在一个定高裁剪框 `RevealViewport` 里（换句时靠它整块上滚一行）；`set_original_words` 专门给逐词通路用（含逐词行的左对齐排版与两行上下文）。**原文行一律左对齐**（逐词行和整句行都是），**「仅显示译文」下逐词原文一个字都不上屏**（`_word_reveal_visible()`）——见"音频时钟与逐词字幕"一节。**译文行跟原文行一个待遇**：左对齐 + 折行超过两行时往上滚（`_translation_reveal` 判"这行归译文视口管吗"，`_set_translation_rows` 是对账点），不再把窗口撑高（见"音频时钟与逐词字幕"一节）。
- `gui/word_reveal.py` — `WordReveal`：拿带块号的词表 + 当前播放位置，算出"这一刻该显示到哪个词"（连同上那句的全文，给界面摆两行用），返回 None 表示不用重绘。纯逻辑（无 Qt/音频依赖）。单测见 `test_word_reveal.py`。
- `audio/audio_timeline.py` — 逐词字幕的时间轴数据结构（`TimedWord`/`WordSegment`/`AudioSegmentTask`），刻意做成不引入 whisper/torch 的叶子模块，供界面和单测导入。
- `audio/audio_manager.py` — `AudioManager`，音频管线编排中心。整句通路三条线程：录音（`_record_audio`，做音量 VAD 分段）→ 识别（`_recognize_audio`）→ 播放（`_playback_audio`，仅监听系统声音时）。用 `queue.Queue` 在线程间传 NumPy 音频数据。流式通路（`asr_backend="simul"`）另加一条 `_stream_recognize`（见"流式识别"一节），此时前两条线程里的整句识别部分空转。
- `audio/simul_asr.py` — `SimulStreamingEngine`，把 vendored 的 SimulStreaming（AlignAtt）包成"喂一块 → 攒够就解 → 出已确认前缀 / 句尾定稿"的接口。只被 `_stream_recognize` 那一条线程调用，内部不上锁。上游那三个坑写在文件头。
- `third_party/` — vendored 的 ufal/simulstreaming（MIT，来源与改动见 `third_party/PROVENANCE.md`），只有流式识别用得到。
- `audio/audio_processor.py` — `AudioProcessor`（Whisper 模型加载、CUDA/CPU 选择、降级逻辑）+ `WhisperThreadPool`（后台异步识别，带超时取消）。同步 `process_audio` 与异步 `process_audio_async(callback)` 两套接口。
- `translation/subtitle_manager.py` — `SubtitleManager`，翻译管线编排：术语处理（`TermManager`）+ 传输层（第 5 步按 `translation_backend` 分派到本地模型或 googletrans）+ 整段结果的 LRU 缓存 + 延迟统计。
- `translation/local_llm_translator.py` — `LocalLLMTranslator`，**默认的翻译后端**：HTTP 调本机的 Ollama（或 llama.cpp 的 llama-server）。含探活 `health()`、预热 `preload()`（真跑一步 `num_predict=1`，加载期选项与真翻译一致）、真翻一句的 `self_test()`（界面"测试连接"用，把加载与翻译两段耗时分开报）、耗时明细 `last_stats`；方法一律不抛异常，失败只记 `last_error` 并返回 None。**"用完就还"也是这一侧的活**：`unload()` / `unload_others()` / `resident_models()`（见"显存回收"一节）。
- `text_guards.py` — 根目录下的纯逻辑判据（**不 import 任何东西，连 Qt/torch 都不碰**）：`clean_transcribed_text`（幻觉短语 / 括号噪声 / 复读乱码 / 纯标点）、`is_repetition_loop`、`find_repeating_unit` / `is_phrase_repetition`、`is_redundant_segment`、`truncate_repetition`、`normalize_text`。**放在根目录而不是 `audio/`**：整句识别（`audio/audio_processor`）、流式识别（`audio/simul_asr` 的 `_absorb` 与终稿）、译文侧（`translation/echo_guard`）三处都要用，塞进任何一边都会绕出循环导入（先例是 `model_residency.py`）。判据的分寸见下面"这段不是人话"一节，单测 `test_text_guards.py`。
- `translation/echo_guard.py` — 译文侧的"提示词残渣"过滤：`strip_echo`（剥掉 `来源：` / `中文：` / `English:` 这类脚手架与被回显的原文，**只剥前后缀、不动正文**）与 `is_echo`（译文和原文一字不差且够长 → 当失败）。`LocalLLMTranslator._translate_one` 拿到 `content` 后过这一道；`check_local_translate.py` 的 `ECHO_MARKERS` 复用同一份常量，不再各写一份。判据共用 `text_guards.normalize_text`。
- `model_residency.py` — 全局单例 `model_residency`：**谁在占显存、什么时候该放**的唯一账本（`register`/`touch`/`release`/`release_all`/`sweep`/`snapshot`/`describe`）。刻意不认识任何具体类（释放回调是调用方给的薄绑定方法），所以不引入 `audio/ ↔ translation/` 的循环导入，界面和单测也能安全导入它；配套的 `free_cuda_cache()`（`gc.collect()` + 惰性 import torch + `empty_cache()`）和 `cuda_memory_mib()` 同理。详见"显存回收"一节。
- `translation/term_manager.py` — `TermManager`，业余无线电术语处理：信号报告转换（"five nine"→"59"）、字母解释法呼号还原（"Alpha Bravo"→"AB"）、术语占位符保护。
- `translation/subtitle_file_manager.py` — `SubtitleFileManager`，将识别结果写为 `Subtitles/*.srt`。
- `config.py` — 全局单例 `config`，JSON 持久化到 `settings.json`，自动补齐默认项。

### 关键数据流

整句识别（`asr_backend="whisper_batch"`，默认）：音频 → 录音线程（VAD 分段）→ `audio_queue` → 识别线程 → `WhisperThreadPool` 异步识别 → 回调 → `result_queue`/`text_queue` → 主线程 `QTimer` 轮询 → `SubtitleManager.translate` → `SubtitleWindow.update_text`。

流式识别（`asr_backend="simul"`）：音频 → 录音线程（VAD 只用来定句子的起止）→ `stream_queue` → `_stream_recognize` 线程 → 引擎攒够就解 → **前缀**（只喂 `word_queue` + `get_committed_prefix()`，界面拿去「译文逐词显示」）／**终稿**（走上面那条一模一样的出口，含 SRT）→ 主线程 `QTimer` 轮询。

### 翻译管线（顺序固定）

`SubtitleManager.translate` 内依次执行：信号报告转换 → `direct_translate`（整词术语直译）→ 字母解释法呼号还原 → `preprocess_ham_radio_terms`（术语替换为 `__TERM_N__` 占位符）→ **`_transport_translate`（第 5 步的传输，按 `config["translation_backend"]` 分派：`local` = 本机 EuroLLM（默认），`google` = googletrans 公网接口）** → `restore_ham_radio_terms`（还原占位符）。除第 5 步外，其余各步两套后端共用，一行未动。

第 5 步失败仍然**抛异常**，由原来的 `except` 接住、回落成原文（字幕不会崩）。回落走的是 `SubtitleManager._fallback_text`：**先把 `__TERM_N__` 还原回术语再返回**——原来直接返回 `processed_text`（占位符替换之后、还原之前的状态），屏幕上就出现 `__TERM_0__` 这种字样（本机 SRT 实测两条）。缓存的是**整段管线的最终结果**（键 = 后端签名 + 目标语言 + 原文），只有走完全程的结果才进缓存；后端签名含引擎/地址/模型名，所以换引擎或换模型不会命中旧译文。

### 译文为什么有时候是原文（五条链，逐条断掉了）

用户报的"翻译过程中有时候直接显示原文"，本机 SRT 语料（12 个文件 81 条）里有 14 条（17%）根本没有译文，`145930` 那份连缺五句。查下来是五条独立的链，现在都有闸：

1. **同语种短路**（`MainWindow._is_same_language`）：原来只要"5 票多数"投出来的语种等于目标语言，就**把原文当译文上屏、连翻译请求都不发**。双语交替的材料很容易被投成目标语言，于是整段原文就那样上了屏。现在**只有用户显式指定了源语言**（`source_language != "auto"`）才允许这条短路；`auto` 一律照常翻译，旁边补一行打印让这条路径在日志里看得见。
2. **回落时占位符没还原** → `_fallback_text`（见上）。
3. **提示词残渣**：`来源：…`、`中文：` 这类脚手架（本机 SRT 里 11 条）。原来这套常量只活在 `check_local_translate.py` 里，生产代码一个字都没用。现在 `LocalLLMTranslator._translate_one` 拿到 `content` 先过 `translation/echo_guard.strip_echo`（剥前缀，**不是整句丢掉**——剥完译文通常还在），并把"译文与输入一字不差"的回显当失败。
4. **退化重复输出**（"笨拙的笨拙的…"×60）：`_ollama_options` 除了 `temperature: 0.0` 再加 `repeat_penalty`（约 1.15）与 `repeat_last_n`；输出侧再过一道 `text_guards.truncate_repetition`（只砍开头的重复，不动后半句）。
5. **整批终稿被丢掉**（最直接的一条）：`translation_worker._coalesce` 在积压时**只保留最后一个 final**、其余整句直接丢——那几句就永远只有原文。现在 **final 一个都不丢**（能丢的只有同类里被更新文本取代的旧项），前缀照旧"后到覆盖先到"。

另外 `_translate_segments`（带术语的句子要发 N+1 个请求）原来有一段没翻成就整句返回 None，现在**按冷加载放宽重试一次**，仍失败才整句回落，`last_error` 里记清是哪一段。

### 本地翻译（EuroLLM，默认后端）

- 走 **Ollama 的 HTTP 接口**（`POST /api/chat`，另支持 `local_llm_api="openai"` 指向 llama-server 的 `/v1/chat/completions`），**不需要任何新的 pip 依赖**（只用 `requests`），也就绕开了 Python 3.8 装不上新轮子的死结。默认 `cas/eurollm-1.7b-instruct-q8:latest`，本机实测 GPU 上 **100 tok/s、单句 76~285ms（平均 162ms）**，而 googletrans 是 2.1~2.7 秒（`check_local_translate.py` 里能两者对比着看）。
- **提示词必须按 EuroLLM 官方格式**：指令在 user 回合里，写成 `Translate the following English source text to Chinese:\nEnglish: …\nChinese:`（源语言未知时用 `Source:`）。换成"system 里讲一段话"的自由写法，1.7B 会答非所问。system 只放"只输出译文"这条纪律。
- **术语标记绝不出现在提示词里**（`_translate_segments`）：实测 1.7B 对 `__TERM_0__` 极不老实——同一个标记出现两次会被**合并成一个**（"CQ CQ … CQ CQ" 只剩一个 CQ）、标记后面跟着括号注释（"73（最好的祝福）"）时会连标记一起吃掉、即便数量对**位置也不对**（标记被挪到句尾）。所以做法是**把标记当分隔符切开，只把中间的纯文本片段发给模型，标记由我们自己拼回去**，位置和数量都确定，第 6 步的 `restore_ham_radio_terms` 照旧把术语贴回来。代价是带 N 个术语的句子要发 N+1 个请求（都是短句，实测每条 100~200ms）。标记后面那份重复的括号注释（`_strip_glosses`）也要先摘掉，否则会被当成正文再翻一遍。
- `keep_alive` 别去掉：模型闲置 5 分钟就被 Ollama 卸掉，下一句要重新加载（**冷加载实测 6.5 秒**，这也是"第一次翻译特别慢"的原因）。
- **冷加载不能算进"单句超时"**（`_LOAD_READ_TIMEOUT_S` = 120 秒 / `_warm_model` / `preload()`）：`requests` 的读超时管的是"等到第一个字节"，而模型从磁盘进显存全发生在第一个字节之前。实测冷加载 **1.7B-Q8 1.4 秒、9B-Q4（5.6GB）10.8 秒、Spark-1.7B 4.4 秒**，而 `local_llm_timeout_ms` 默认 3000 —— 换个模型之后第一句必然以 ReadTimeout 告终、回落成原文，**这就是"切其他模型测试失败"的原因，不是提示词的问题**（9B 热起来单句只要 0.5 秒、译文正确）。做法：记一个 `_warm_model`，没热过的第一次请求用 120 秒兜底，成功之后回到配置里的单句超时；**热着超时说明模型其实早被卸了**，这时把 `_warm_model` 清掉，下一次请求自动按加载放宽（丢一句，但会自己爬起来）。
- **`preload()` 必须是"真跑一步最小生成"（`num_predict=1`），且 options 与真翻译逐字一致**（都走 `_ollama_options`）。两个坑实测都踩过：① `/api/generate` 不带 prompt（"只加载不生成"）同样花掉整个加载时间，却不保证模型留在显存里；② `num_ctx` 这类**加载期**参数两边不一样时，Ollama 会在紧接着的翻译请求上把刚加载好的 runner 卸掉重载（`-c 2048`，实测 5.06 秒），客户端一超时断开，Ollama 连这次重载也取消（日志：`aborting load` / `context canceled`），最后显存里什么都不剩 —— 表现为"preload 报已就绪、紧接着按热模型发请求还是超时"。排查这类问题**先看 Ollama 自己的日志**（`%LOCALAPPDATA%\Ollama\server.log`），它会写明是加载、换参数重载还是被取消。
- **思考型模型要显式关掉思考**（payload 里的 `"think": False`）：Spark-X2.5、DeepSeek-R1 这类默认先把推理写进 `message.thinking`，实测 Spark-1.7B 把 256 个 token（`num_predict` 上限）全烧在思考上，`content` 是空串、`done_reason='length'`，字幕上什么都拿不到。加上 `think: false` 之后有输出了，但 **Spark-X2.5 仍然不适合当翻译**：它会把提示词脚手架一起吐出来（"收到，来源：罗杰，收到，。"、"您的信号是59\n。中文"），`check_local_translate.py` 的 `ECHO_MARKERS`（现在复用 `translation/echo_guard.py` 那一份常量，生产代码同一道闸）专门拒收这类残渣。EuroLLM-1.7B/9B 实测都接受这个字段（不支持的模型会忽略它），所以无脑加；OpenAI 兼容那条路不加（那边开关思考是 chat template 的事，多塞字段可能被严格的实现拒掉）。
- **输出侧有两道闸**（都在 `_translate_one` 拿回 `content` 之后）：`translation/echo_guard.strip_echo` 剥掉提示词脚手架（`来源：`/`中文：`/`English:` 那套，以及被回显的原文），`is_echo` 把"和原文一字不差且够长"的回显判成**失败**（交给重试/回落，而不是把英文当译文上屏）；`_ollama_options` 加 `repeat_penalty: 1.15` / `repeat_last_n: 64` 压退化的复读，输出再经 `text_guards.truncate_repetition` 兜一道。**剥前缀 ≠ 整句丢弃**：剥完译文通常还在，整句丢掉等于这句白翻。
- 界面上的"测试连接"先 `preload()` 把加载单独做完、单独计时，再按 3000ms 真翻一句，所以报出来的是"**加载 N ms，翻译 M ms，tok/s**"三段 —— 不然 9B 光加载就 10.8 秒，报出来的"耗时"分不清是加载还是翻译。


### 音频时钟与逐词字幕（原文跟着语音一个词一个词出现）

原来"整句识别完才显示"的原因：整句要等 0.5 秒静音才提交识别，结果回来时这句话早播完了。要做到逐词，必须**边说边识别**，并把词对齐到"用户此刻听到的音频"上。

- **绝对采集块号**：`AudioManager.captured_chunks` 是录音开始以来读到的块数（1 块 = 1024 样本 ≈ 64ms），只增不减，相当于本轮录音的时钟。音频段带着 `start_chunk`/`end_chunk`/`utterance_id` 进识别队列；词时间由 `_timed_words` 换算成 `start_chunk + round(word.start * 16000 / 1024)`。
- **播放位置**：`get_play_position_chunks()` = 采集块号 − 播放队列积压（`playback_queue.qsize() + _OUTPUT_BUFFER_CHUNKS`，上限 `_MAX_LAG_CHUNKS`）。监听关闭或播放线程已死时按实时采集算。**这就是"变动的延迟"的正解**：不用手动填滑块，数一数还有多少块没播出去就知道了。（`audio_delay_enabled/audio_delay_ms` 那套手动延迟已删除。）
- **预览识别**（`kind="partial"`）：说话过程中每 `partial_interval_ms`（默认 1000ms）用当前缓冲区快照跑一次识别，只喂逐词显示。它**绝不排队**（线程池忙就跳过这一帧，`process_audio_async` 返回 None）、**绝不进 `text_queue`/SRT/翻译**——半截句子的错识别只能在屏幕上闪一下，最终结果一到就整句替换。
- **显示**：`WordReveal.tick_line(play_chunk)` 选"起点不晚于播放位置的最近一段"，把起点已过的词拼成一行，另外给出**上一句的全文**（`previous_text`）。识别慢了会一次补齐（不卡住、不倒着走），一句话说完而下一句未开始则继续显示上一句；当前行文本、上一句文本、句号三者都没变就返回 None，界面不会无端重排。（`tick()` 是只返回文本的旧接口，单测在用。）
- **排版**（`SubtitleWindow.set_original_words`）：逐词行固定**左对齐**（`_apply_reveal_layout` 设 `AlignLeft|` 垂直方向见下条），新词在右边接着长，左边的字一动不动——居中会每多一个字就把整行重排一次，看着一直在抖。不挪标签本身（标签仍占满整行、超长照旧换行），只用样式表给文字留出固定的左边留白：`_label_stylesheet` 写的是 `padding: 上下 Npx; padding-left: (N+REVEAL_LEFT_MARGIN)px;`（长写覆盖简写，`REVEAL_LEFT_MARGIN = 32`），所有标签样式都从这一个出口走，免得别处设颜色时把这个留白抹掉。**标签还必须 `setIndent(0)`**：`QLabel.indent` 默认 −1，左对齐时它按字体再垫半个 `"x"` 宽（本机离屏字体 9px、真 Arial 3px，逐词行实测就是这样多出 9px），左边留白就成了"跟着字体环境浮动"的数，`_reveal_avail_width` 也会算宽一点（截断的上一句可能因此折成两行）；居中排版不受 `indent` 影响。**原文行一律走这套左对齐排版**，不只是逐词行：`_set_sentence_text` 里 `label is self.original_label` 就调 `_apply_reveal_layout`，`reset_reveal_layout` 也不再把它居中回去（以前勾一次逐词开关就把原文居中回来了）；只有**译文标签在译文视口下**才也是左对齐（见"译文行也是裁剪框视口"一条，否则下一次按行数对账会量错行数），其余情况（译文标签不可见等）仍走 `_apply_sentence_layout` 居中。关掉「原文逐词显示」后原文就是"整句、左对齐、折几行就几行高"。
- **裁剪框**（`RevealViewport`）：每个标签都装在一个定高的裁剪框里，框里**不用布局**，标签的位置由 `_place_child` 给（`set_content_height(h)` 定内容高度、`set_scroll_offset(o)` 把内容整体上移 o）。裁剪是白送的：Qt 里子部件天然被父部件矩形裁掉。整句通路的内容高度是 0（标签填满裁剪框、偏移恒 0），所以这层对它完全透明。**窗口高度链路看的是裁剪框**（`adjustLabelHeights` → `_set_label_rows` 设裁剪框的 `minimumHeight`，`_required_height` 求和）——别去设标签自己的 `minimumHeight`，那是 `_place_child` 给的高度下限，设大了标签就压不下去、裁剪失效。
- **原文两行**（上一句 + 当前句）：`_compose_reveal_text` 把上一句按 `_reveal_avail_width`（标签宽 − 左右内边距 − 左边留白）用 `QFontMetrics.elidedText` 截断，再和当前句用 `\n` 拼成两行——上一句在上、当前句在下，便于顺着上下文听（像 YouTube）。宽度必须按左边留白一起扣，宽一点点上一句就会折成两行、把当前句挤出可见范围。只有原文行这么做（`_reveal_two_lines()`：逐词开着、且不是"仅显示译文"模式；**"不翻译"模式下也算**——那时屏幕上只有原文，上一句更是唯一的上下文）。
- **两行模式下必须顶对齐 + 上下内边距 0**（`_reveal_alignment` / `_label_vpadding`）：内容高度 = **2 × 行距**（多出来的第三行露不出来），文字第一行贴住框顶边，于是滚一个行距正好把上一行整行送出框外、当前句落到提交后它自己的位置上。行距要用 `QFontMetrics.lineSpacing()`（Arial 14 是 **22**），**不是 `height()`**（19，差 3px，滚动距离一差接缝就跳）。也别想着用负 `contentsMargins` 上移：Qt 会把上边距夹成 0，实测只表现为"高度缩了再居中"的 10px 位移。两行模式（`_reveal_two_lines()`）下**译文行的上下内边距也是 0**，而译文视口下的译文行是左对齐的，`_label_vpadding` 先判 `AlignLeft` 所以同样是 0：文字上下的空白全交给布局的三处间隙，标签自己再垫一层，原文和译文各自的上下就不一样宽了；对左对齐的译文行还多一层理由——留了上内边距，滚完之后最后一行就落不到框顶那个整行距的位置上。
- **上/中/下三处间隙一样宽、按字号算**（`_apply_row_gaps` / `_row_gap`）：上 = 窗口顶边到原文框、中 = 原文框到译文框、下 = 译文框到窗口底边，三处都取 `max(MIN_ROW_GAP, round(较小行距 × ROW_GAP_RATIO))`（字号一改一起变，不用手填），分别落在布局的 `contentsMargins` 上边距、`spacing`、下边距上。窗口比内容高时多出来的部分**三处平分**（`(窗口高 − 行高之和) // 3`），不是全堆在原文和译文中间——那正是"中间空了好几行"的由来。间隙必须加在裁剪框**外面**：做成标签的上内边距（框内加白），上一行滚完还剩一截字形挂在框顶，一直挂到提交新文本那一帧才消失（看着就是闪一下）。
- **行盒高度按行距算，不按字号盒子**（`_label_line_height`）：逐词行正好一个行距（上下内边距 0），整句通路（居中）才是 `行距 + 上下内边距`——标签盒比"文字 + 内边距"矮，字就会被裁掉半截。整句通路按实际折行数给高度（`_label_text_lines` 用 `QFontMetrics.boundingRect` 量）——**只有还走整句排版的那条路是这样**；译文行归译文视口管时框高封顶 `TRANSLATION_ROWS` 行、再长往上滚（见下一条），窗口只在 1→2→3 行那两下各长一个行距。**原文行左对齐之后这里有个坑**：`adjustLabelHeights` 的行数原本写死 `lines = 2 if _reveal_two_lines() else 1`，靠 `_set_label_rows`（只对**非左对齐**标签生效）自动抬到实测折行数——原文一左对齐，那个兜底就失效了，折成两行的整句会被裁成一行。所以非两行模式下取 `max(1, self._label_text_lines(self.original_label))`。
- **换句向上滚一行**（`set_original_words` + `_start_reveal_scroll`）：触发信号是 `utterance_id` 变化（`RevealLine` 早就带着它，界面以前没用），且要 `previous_text` 非空、两行模式、**当前框里已经有 `\n`（两行）**——这一轮的第一句不滚：它本来就占着第一行，滚了只会把唯一那行送出框外空一下。动画是 `QVariantAnimation`（OutCubic，`REVEAL_SCROLL_MS = 200`），距离 = 一个行距。**动画期间不动文本**，新文本只存进 `_reveal_pending`，`finished` 时偏移归零再一起贴上（滚动中途改文本画面会跳）——延迟 ≤200ms 而新句第一个词本来就要 1s 上下才识别出来，肉眼无感。切模式（`set_subtitle_mode`）、重开一轮（`reset_reveal_layout`）、窗口藏起来（`hideEvent`）都要 `_stop_reveal_scroll()`，免得动画停在半路。`hideEvent` 那里要 `apply_pending=False`：`_set_reveal_text` 见窗口不可见会 `show()`，等于关不掉。
- **译文行也是裁剪框视口**（左对齐 + 溢出往上滚，`_translation_reveal` / `_set_translation_rows` / `_sync_translation_scroll`）：以前译文走整句通路——居中、折几行就把窗口撑高几行（「译文逐词显示」开着时每 800ms 长一段，窗口就一跳一跳地变高）。现在**框里最多留 3 行，内容按实际行数摆，偏移让最后 3 行正对着框**，行距一律用 `_reveal_line_pitch`（= `lineSpacing()`）：

  | 折行数 N | 框高（裁剪框 `minimumHeight`） | 内容高（标签） | 偏移 |
  |---|---|---|---|
  | 1 | 1 个行距 | **0**（标签填满框，`RevealViewport` 的既有契约） | 0 |
  | 2 | 2 个行距 | 2 个行距 | 0 |
  | 3 | 3 个行距 | 3 个行距 | 0 |
  | ≥4 | 3 个行距 | N 个行距 | (N−3) 个行距 |

  框高取 `min(N, 3)` 而不是死钉 3 行：钉死的话一行译文要么上面空两个行距、要么下面空两个行距，上/中/下三处间隙的视觉平衡就破了（几何相等但字的位置差一两个行距）。代价是**译文从 1 行涨到 3 行时窗口各高一个行距**（三处平分，`bottom` 定位下顶边上移）；不想要这点起伏就把 `min(lines, TRANSLATION_ROWS)` 换成 `TRANSLATION_ROWS`，代价是那个视觉不平衡。`TRANSLATION_ROWS` 是唯一开关，改回 2 就退回旧行为。

  - **译文行保留上一句**（用户报的"译文很长时还没看完就显示下一行了"）：这行现在是**上一句译文 + 当前句译文**的组合，跟原文行同构。`_update_translation_line(translation, key, is_final)` 决定要不要轮换：**当前这句是终稿（`_translation_current_final`）且来源（`key`）变了** → 旧的整句进 `_translation_prev`、新的落到当前行；**前缀盖在终稿上**（同一句又送了一次半截的）只改当前行不轮换。`key` 由界面传（`_apply_translation` / `_apply_prefix_translation` 拿得到 `src_text`），判据是"这条译文属于哪句原文"而不是"文本像不像"——翻译器会重写前缀，按 `startswith` 分派反而认错。组合文本由 `_compose_translation_text()` 出：`elidedText(上一句, _reveal_avail_width)` + `\n` + 当前句（截断复用原文行那套 `QFontMetrics.elidedText`）。
  - **"清空译文行"是显式动作**：`clear_translation()`（切「不翻译」时走它）把上一句和当前句一起清掉；`update_text(translation_text="")` 现在是**什么都不做**（以前它会清空译文行——那正是"上一句被清掉、来不及看"的形状），`_show_original_text` 也因此只传 `original_text`。`set_subtitle_mode` / `reset_reveal_layout`（重开一轮）都要 `_reset_translation_lines()`，`hideEvent` 只停滚不 reset（文本没变，再显出来还得指着尾窗那一屏）。

  - `_translation_reveal()` 是**无状态判据**：`not translation_disabled() and subtitle_mode != "original"`，就这一句，没有例外。不用记"这行现在装的是谁"，模式和配置就能推出来。（以前还有一条例外：`translated` 模式下逐词原文会**借译文标签**占位，那一行归逐词通道管、整句译文只能居中——见下面"仅显示译文"一条，这个借用已经删掉了。）
  - 由此 `_reveal_alignment` 的译文分支是 `AlignLeft|AlignTop`（**顶对齐是尾窗滚动的前提**，`AlignVCenter` 的取整误差会让滚完的最后一行差一两像素）；`_label_vpadding` 对左对齐标签返回 0，所以译文框 = 行数 × 行距，一格不多。
  - `_label_text_lines` 在左对齐标签上按 `_reveal_avail_width`（标签宽 − 内边距 − 左边留白）量：按居中口径量会**少算一行**，而偏移是拿行数算的，少一行最后一截就露不出来。
  - `_set_label_rows(label, lines, content_lines=None)` 把**框**里几行（窗口高度看它）和**内容**几行（滚动距离看它）分开，默认相等 → 原文行的调用逐字节不变。
  - `_sync_translation_scroll(lines)`：目标 = `(lines − TRANSLATION_ROWS) × 行距`，先把当前偏移**夹进 `[0, 目标]`** 再动（文本变短时不会出现"内容比偏移还短、屏幕空一块"）；**目标没变就直接返回**（`adjustLabelHeights` 每 200ms 被逐词通道叫一次，无脑重启动画会让一次 600ms 的滚动永远走不完）；动画是 `QVariantAnimation`（OutCubic），时长 `min(MAX_TRANSLATION_SCROLL_MS = 600, 200 × 跳过的行数)`——逐词/前缀那样一行行长出来的是 200ms，和原文行一个手感，整句终稿一次折很多行时按行数延时滑过去，不至瞬移。**不判断"新文本是不是旧文本的延长"**：翻译器会重写前缀，按 `startswith` 分派反而认错，上面"夹住 + 目标没变就返回"对延长和替换一视同仁。
  - 状态只有 `_t_scroll_anim` / `_t_scroll_target`，和原文行的 `_scroll_anim` / `_scroll_view` / `_reveal_pending` **完全分开**（两行可能同时在滚）；译文行也不需要 `_reveal_pending` 那套"滚动期间不动文本"——它只挪偏移，中途换文本不会露出错的中间帧。
  - `_set_translation_rows()` 是**对账点**：切模式、改字号、重开一轮未必先写过译文，所以排版也在这儿一并摆好（`adjustLabelHeights` 每轮叫它）。非译文视口的分支必须 `_stop_translation_scroll(reset=True)` 把偏移清 0——`_place_child` 在内容高度 0 时按框高走，残留的旧偏移会把短文本顶出框外。`clear_translation`（切"不翻译"）也自己调一次对账，不等下一轮轮询。`hideEvent` 只停**不 reset**（文本没变，再显出来还得指着尾窗那一屏；原文行不一样——它滚完要归零再贴新文本），`reset_reveal_layout` 则 reset。
- **窗口高度默认贴着内容走**（`window_height_auto` / `_fit_window_height`）：`_required_height()` = 三处间隙 + 各可见裁剪框的最小高度，高度就是它——字号/行数一变，窗口跟着收放（译文行只在 1~3 行之间变，再长往上滚），不会在原文和译文之间挂一片空白。`window_height_auto = False` 表示"高度是用户定的"：设置里改过高度（`on_window_height_changed` → `_lock_window_height`）或**按住鼠标**拖右下角（`resizeEvent` 里查 `QApplication.mouseButtons()`）之后就是这种状态，之后一律按他定的高度来（多出来的空间三处平分）。为什么要看鼠标键：Qt 自己在显示/隐藏过程中发的 resize 不该被当成"用户拖的"，否则高度一次就锁死、再也不跟着内容走。另外 Qt 的 `setFixedSize` 走的是 C++ 的 `resize`（`QWidget.resize` 不是虚函数），绕不过我们的重写，所以 `showEvent` 里那次精确尺寸要用 `_auto_set_fixed_size` 包一下（`_auto_resize_depth` 计数），不然同样会被当成用户拖的。
- **仅显示译文**（`subtitle_mode == "translated"`）：屏幕上**只**有译文，说话期间那一行是空的，原文一个字都不上屏。判据是 `_word_reveal_visible()` ＝ `not (subtitle_mode == "translated" and not translation_disabled())`：`set_original_words` / `_set_reveal_text` 开头照它直接返回（后者顺带丢掉 `_reveal_pending`），`set_subtitle_mode` 切进来时停滚 + 丢 `_reveal_pending` + 把原文标签清空（免得切回"两者"时闪一眼上一句旧文本）。**这里曾经有三处来源让原文先冒出来、还穿着译文的字体颜色/字号**：① 逐词通路**借译文标签**（`_reveal_label`）——译文标签被原文占了，颜色字号自然整套都用译文的；② `update_text` 单参数版在 `translated` 模式下照样写译文行；③ `update_text` 双参数版"没有译文就先拿原文顶一下"；外加 `_show_original_text` 在 `translated` 模式下也照写。四处全删了，所以**不管谁调用，`translated` 模式下译文行只可能由真译文写入**。（"不翻译"是例外：`translation_disabled()` 时模式虽然也是"仅显示译文"，但屏幕上本来就该只有原文，所以不屏蔽。）
- **不翻译**（目标语言选"不翻译"→ `target_language = "none"`）：只走原文通路，不提交翻译请求，字幕窗只留原文行（`SubtitleWindow.translation_disabled` 会强制隐藏译文行）。
- 排查工具：`python check_word_timestamps.py <wav> [模型] [设备]` 打印每词时间轴，用来区分"逐词不生效"是模型问题还是设置问题；`python check_reveal_scroll.py`（`--live` 用 settings.json 里那套字号/窗口）离屏喂一串脚本化的句子、扫像素验几何（行距、贴顶、滚完不跳、不翻译模式也两行、整句通路不被裁剪），并逐个量：上/中/下三处间隙必须相等、等于 `_row_gap()` 那个按字号算的基准、窗口高度正好是 `_required_height()`，字号改大时间隙跟着变大，把窗口拉高 90px 后三处各分到 30px；译文行那几项按上表验——框 = `min(行数,3)` 行、内容按实际行数、偏移 = `(行数−3)×行距`，可见的正是最后三行、首行贴框顶、窗口高度不变（滚动不吃窗口高度）、`clear_translation` 后偏移归零（连上一句一起清）、1→2→3 行各只长一个行距、4 行以上时偏移是渐变而非瞬移、切模式后偏移归零，**换句后上一句译文仍留在框里**（新译文到达时旧的那句往上顶，不是整行消失）、同来源的新译文原地替换；还验"关掉逐词后原文整句也左对齐、折两行不被裁、窗口跟着长"和"仅显示译文下说话期间整窗无墨、译文只在整句译文到了才出现"。开关 `word_by_word_enabled=False` 可完全退回整句原文行为，`translation_word_by_word=False` 可完全退回整句译文行为。**本机 settings.json 里 `window_height_auto` 是 `false`**（用户手动拖过高度），所以脚本非 `--live` 那套会显式把它钉成 `True`（否则量"窗口高度 = `_required_height()`"必挂），`--live` 遇到用户锁了高度就把这几项标成`[跳过]`并说明原因，不再误报不通过。

### 流式识别（SimulStreaming，`asr_backend="simul"`）

默认仍是 `asr_backend="whisper_batch"`（就是上面这一整套）。切到 `simul` 后，识别改由 `audio/audio_manager.py` 的 `_stream_recognize` 线程负责：录音线程**不再提交整句识别**，只把音频一块块喂过去（`_stream_begin` / `_stream_chunk` / `_stream_end` 三个事件走 `stream_queue`），引擎攒够 `simul_commit_interval_ms` 就解一次，每次给出"已确认前缀"（算法是上游的 AlignAtt：离音频末尾 `simul_frame_threshold` 帧以内的部分不解码、末尾未确认的词一律截断，所以前缀只会往后长、不会缩）。

- **时钟仍然只有 `captured_chunks`**：引擎侧的词时间是**绝对流时间**（`begin_utterance(offset_sec)` 内部调上游的 `online.init(offset=…)`），`_stream_timed_words` 一步换算成采集块号（`round(秒 × 16000 / 1024)`），与整句那条路同一个参照系——`WordReveal` / `SubtitleWindow.set_original_words` 的签名和语义**一行都没动**，流式只是更频繁地喂非 final 的 `WordSegment`（与 `kind="partial"` 完全同构）。
- **前缀只喂显示，SRT 只认终稿**：前缀（`is_final=False`）只进 `word_queue` 和 `get_committed_prefix()`（界面拿去「译文逐词显示」，见下一节）；终稿（`is_final=True`）走和整句识别**完全一样**的出口（`text_queue` / `result_queue` / `add_subtitle` / `ui_update_queue`），所以 `Subtitles/*.srt` 里永远只有整句。`get_committed_prefix()` 返回 `(utterance_id, text)`。
- **自动回退**：引擎加载/预热失败、或连续 3 次提交出错 → `_stream_state="failed"`，录音线程从下一块音频起改走整句识别。它全程照常攒 `recognition_buffer`，所以一段音频都不会丢，也不需要回滚任何状态；界面「流式状态」那行显示原因。**回退的同时必须把失败的引擎卸掉**（`_retire_failed_engine`：`engine.unload()` + `model_residency.mark_released("asr_simul")` + 把 `stream_engine` 置 None）。原来只置状态就 `return`，`finally` 又因为"还是当前这一轮"而不卸——失败的那份 whisper 留在显存里，而下一块音频立刻回退整句识别、把**另一份** whisper 加载进来，本轮就同时驻留两份（各约 1.4 GB），8 GB 卡上就是"显存被撑爆"的那一下，要等下次点「开始」才自愈。`unload()` 幂等，`finally` 再调一次无害。
- **"这段不是人话"的闸门流式也要过**（原来一行都没接）：① `_absorb` 里新段若与已确认前缀尾部重复（`is_redundant_segment`）就丢弃、**不算进展**——它同时是下面看门狗的输入；② 终稿写 SRT/上屏之前过一遍 `clean_transcribed_text`（`[MUSIC PLAYING] [MUSIC PLAYING]`、"In +1. The I come 7 -1 -1-0- S" 这类对着噪声编出来的东西原来直接进了字幕和 SRT）。判据全在根目录的 `text_guards.py`，**整句那条路的调用点逐字未动**。
- **停滞看门狗**（`_STREAM_STALL_COMMITS = 3`，约 2.4 秒）：上游的 SimulStreaming **每句话只检测一次语言并锁死**，只有 `refresh_segment`（由上游的 `init()`/`finish()` 调）才把它清回 None；而断句靠 0.5 秒静音——中英交替不断句时，一整段锁一种语言，另一种语言解不出来，前缀就反复停在同一个词上（用户看到的就是原文一直重复显示 "youtube"），一直卡到 `simul_max_utterance_sec` 上限。做法是**协作式切句**：流式线程连续 3 次提交前缀没变长（或连着 3 次一个字都没解出来）→ 置 `_stream_stall_break`；**录音线程**在下一块音频处 `_consume_stream_stall_break()` 按"句尾"处理（投 `end`、清缓冲区、回到等起点），下一个起点照常投 `begin` → 引擎 `begin_utterance` → 上游 `init(offset=…)` → `detected_language` 清空 → **语言重新检测**。切句只能由录音线程做，因为 `begin` 是它按 VAD 起点发的。形状照抄录音线程里那个 `stalled_submit`（那个在流式下关着）。代价是偶尔把一句完整的话劈成两半。
- **`simul_max_utterance_sec` 默认 12**（原来 25）：卡住的代价上限跟着看门狗一起压小；高级设置里照旧可改。
- **`whisper_batch` 下新增代码一律不执行**：`_record_audio` 里每处流式分支都先问 `_stream_live()`（引擎在且没崩）。这是"两边行为逐字节一致"的保证。
- **每 4 秒的兜底提交（`stalled_submit`）在流式下关掉**：字幕本来就是边走边出，不存在"长时间不更新"；而每 4 秒硬切一刀会把连着的句子劈成两半、接缝处还丢两块。长句交给 `simul_max_utterance_sec`。
- **纯静音攒到上限不给引擎发"句结束"**：一轮里没有语音起点时 `begin` 从没发过，引擎那边没在跟，只清缓冲区（否则每 25 秒白叫一次定稿）。
- **实测代价**（`python check_simul_stream.py small --long-sec 12`，small + GTX 1070 Ti + 真实语音）：单次提交 190~330 ms（提交间隔 800 ms；原表是按 28 秒的长句量的，上限已压到 `simul_max_utterance_sec = 12`，口径跟着改），定稿 150~220 ms，torch 峰值 1403 MiB；加载 2.5 s、预热 0.9 s（第一次解码要编译 CUDA 内核，所以开始翻译前先 `warmup()`，这期间音频排着队，就绪后一口气追平）。**显存**：流式模式下不会去加载整句模型（`audio_queue` 全程空转），但用户之前手动加载过的那个仍占着显存；流式 small 1.4 GB + EuroLLM-Q8 1.65 GB 同驻没问题。
- **量长句的代价必须用真实语音，不能用"同一批词重复摆"**：重复内容会把贪婪解码带进重复死循环（实测 20 秒的重复词表被识别成 141 个词 ≈ 7 词/秒，正常语速 2.6），而 `finish()` 内部写死了 `frames_threshold=4`（比我们的 12 松得多），一旦解不出句尾就一路解到 448 token 上限，词对齐的张量跟着涨到 GB 级——定稿一次 **75 秒**、吃掉 5 GB 显存（`check_simul_stream.py` 的 `synth_passage` 就是为此用 SAPI 念整段真实话）。
- 第三方源码在 `third_party/`（ufal/simulstreaming，MIT，来源与改动见 `third_party/PROVENANCE.md`），它内部按 `simulstreaming.*` 绝对导入，路径由 `audio/simul_asr.py` 的 `add_library_to_path()` 插到 `sys.path` 最前（认"同目录下既有 `simulstreaming/` 包又有 `simulstreaming_whisper.py`"这种长相，也可以用 `SIMULSTREAMING_HOME` 指到别处）。
- **引擎会在多轮「开始/停止」之间复用**（签名不变就不重建，第二轮点开始立刻出字），停止只记一笔"刚用过"、不立刻卸；什么时候真卸、卸载的回调怎么写，见下面"显存回收"一节。
- **改 `audio/simul_asr.py` 之前先跑 `check_simul_stream.py`**：它把上游那三个坑都量过一遍（每次只回当前这一段、词时间是绝对流时间、`finish()` 不能当整句重来且尾部静音会吐 `[static]`），数字变了说明上游或环境变了。

### 译文逐词显示（`translation_word_by_word`，两种后端都吃）

原文有「原文逐词显示」，译文有对仗的**「译文逐词显示」**（`translation_word_by_word`，默认勾上）：勾着的时候**还没定稿的半截原文**也送去翻译，译文跟着原文一段段长出来；不勾就退回"整句定稿才翻一次"（更稳、请求更少）。**这里的"半截原文"两种后端来源不同**（`_update_prefix_translation` 按 `_asr_backend()` 二选一）：

- 流式后端：引擎的 `get_committed_prefix()`（只增不减的已确认前缀）；
- 整句后端：**逐词通路已经念出来的那半句**——`update_subtitles` 第 0 步把 `take_word_segments()` 拿到的 `WordSegment` 顺手记进 `_prefix_source_utterance` / `_prefix_source_text`（词表拼起来就是；**音频管线一行没动**，这些段本来就只喂显示）。所以整句后端下**还要勾着「原文逐词显示」才有东西可翻**——不勾就没有半截原文，一个请求都不发。

- **只上屏**：前缀走 `KIND_PREFIX`，按 `simul_prefix_interval_ms`（界面「译文刷新间隔」，在公共的高级设置里）节流；译文只改译文行，**不进 SRT、不进 `text_queue`**。整句定稿一到就把这批请求作废（`_prefix_requests.clear()`）；迟到的前缀译文、以及**上一句**的前缀译文（`_prefix_utterance`）都丢掉——否则会盖回一个更短的版本、或贴到下一句的原文下面。
- **`_finalized_utterance` 是第二道闸**：整句定稿是"词表 + 整句文本"**同一次回调**发出来的（`audio_manager.py` 里那个回调同时 `add_word_segment(is_final=True)` 和进 `text_queue`），所以清空 `_prefix_requests` 只挡住已经在路上的；逐词通路那一刻还在显示这句话的半句，第 3 步会**再送一次半截的**，而翻译线程优先保终稿（`translation_worker._run`），那个迟到的前缀译文正好落在正式译文**之后**、把它盖掉。所以第 0 步额外记下 `_finalized_utterance`，`_update_prefix_translation` 见到当前句号就是它就返回。依据是"逐词显示跟着播放位置走、而播放位置永远落后于采集"——刚定稿的那句不可能已经被逐词通路翻过去了，所以这个闸不会误伤下一句。
- **开关关掉时连在路上的都要丢**：`torch` 那侧的处理在结果分支里（丢 `KIND_PREFIX` 结果），不是靠"不再发新的"就完事。
- **单测**：`python test_prefix_translation.py`（12 项，用 `MainWindow.__new__` 造空壳，不启 Qt）。
- 整句后端的半截文本每约 1 秒一条短请求（EuroLLM 实测 150~200ms/句），代价与"识别量翻倍"同量级；半截译文会进 `SubtitleManager` 的 LRU 缓存（键＝原文），只是多几条短条目，无正确性影响。
- 逐句模式（不勾）下浮窗在"说话中"是空白的——这本来就是"只显示译文 + 等整句"的含义；勾上就有东西看了。
- **旧键 `simul_simultaneous_translate`**（只在流式后端下有效的「边说边翻译」复选框）已删除，由 `config.py` 的 `_migrate_settings()` 迁到新键（以旧值为初始值，所以原来关着的用户升级后还是关着）。迁移**必须赶在 `ensure_all_settings_exist` 补默认值之前**读旧键：补完默认值新键就"已经存在"了，用户关掉的那个开关会被默认的 `True` 顶掉。

### 「这段不是人话」：幻觉与复读的判据（`text_guards.py`）

静音段和音乐段上 Whisper 会自己编东西，噪声段会让它陷进复读，双语交替被语种锁死时流式引擎会反复吐同一个词。**这些判据以前只活在整句识别那一条路上**（`audio_processor` 里的私有函数），流式一行都没接，译文侧（`echo_guard`）又是另一份写得不一样的常量。现在三处共用一个根目录模块 `text_guards.py`（纯逻辑、不 import 任何东西），**整句那条路的调用点逐字未动**：

- `clean_transcribed_text(text)` — 整条结果的闸：已知幻觉短语（`谢谢观看`、`please subscribe` 一类）、括号噪声（`[MUSIC PLAYING]`、`(欢快的音乐)`，只删括号那一段、句子里别处照留）、字符级复读（`is_repetition_loop`）、短语级复读（`is_phrase_repetition`）、纯标点 → 返回空串表示"丢掉别上屏"。整句识别和流式终稿都过它（流式终稿原来直接进 SRT）。
- **判据的分寸是这一节的重点：宁可漏，不能误伤通联用语**。`CQ CQ CQ`、`very very good`、`Roger roger`、`59 59`、`no no no`、`九 九 九` 都必须放行——它们是业余无线电的正常话。做法是三道限：① 重复**必须到 3 遍**（`MIN_REPEATS`）才算；② 重复单元的**权重**要够（`_unit_weight`：汉字算 2、西文算 1，门槛 `MIN_UNIT_WEIGHT = 4`）——按"字符数"算对中文不公平（`笨拙的` 只有 3 个字符，当年就是这么漏掉 `笨拙的×3` 的）；③ `find_repeating_unit` 既要认空格分词的西文（`youtube youtube youtube`），也要认**没空格的中文**（`compact` 那一遍）。
- **"字符种类少"绝不等于复读**：早期判据是"没有空格且 ≤4 种字符"，把真实结果 `detected`（d/e/t/c 四种）、`assesses` 一起杀了——整句识别是**整条结果**过闸，误杀就是整条字幕没了（本机 SRT 里就有两条 `detected`）。现在收紧成"没有空格且 **≤2** 种字符"（`ʰʰʰʰ…`、`aaaa…` 这类真乱码）。
- `is_redundant_segment(text, parts)` — 给流式 `_absorb` 用：新段与**已确认前缀的尾部几段**归一化后相同（或本身是重复）→ 这一帧没有进展。**只比尾部**（很早以前说过的词再说一遍是正常的），空文本算"没有进展"（停滞看门狗就靠这个判"卡住了"），一两个字符的段（`59`、`73`）不参与比对。
- `truncate_repetition(text)` — 只砍**开头**就是重复的那种退化输出（`笨拙的`×60 → `笨拙的`）；重复段不在开头就原样返回（宁可漏，不可误砍半句正常译文）。
- 单测：`python test_text_guards.py`（含"通联用语不许误伤"那一组，改判据之前先看它）。

### 显存回收（`model_residency`）：反复启停不再累积

**症状**：反复点「开始/停止翻译」多次后 GPU 被占满（本机实测 `nvidia-smi` 7836/8192 MiB，`ollama ps` 里 EuroLLM-Q8 1.65 GB 与 Spark-X2.5-1.7B 3.5 GB **同时挂在卡上**），原文和译文都不流畅（卡顿/译文质量差/识别错漏三种症状一起来的）。根因四条，全改掉了：

1. **流式引擎每轮新建、从不卸载、旧线程不退出**（主因）。
   - `_prepare_streaming` 命中签名就**复用**上一轮的引擎对象（签名 = 模型名 + 界面能改的那几个流式参数 + 语种等），省掉每轮 2.5 秒加载 + 1.4 GB 重载——这就是"第二轮点开始立刻出字"。
   - 签名不符才建新引擎对象（**建对象是廉价的、不含加载**），旧引擎作为 `retired` 交给**流式线程**：线程开头先 `retired.unload()` 再 `warmup()` 新的 → **任何时刻卡上只有一份 whisper**，不会 OOM；卸载放在线程里做，界面线程不会被 `empty_cache()` 卡住。
   - **每轮的队列和停止 Event 归这一轮**：新建 `queue.Queue()` / `threading.Event()` 一并传给线程，旧线程捕获的是旧对象，永远读不到新一轮的事件。**删掉了那段无条件清空 `stream_queue` 的代码**——它会把上一轮还没被消费的 `"stop"` 一起吞掉，旧 daemon 线程于是永不退出：抱着旧引擎占显存，还和新线程抢同一个队列（屏幕上是乱句/重复/丢句）。这是"识别错漏多"的一条直接来源。
   - 线程循环同时看队列和 Event（`while not stop.is_set(): queue.get(timeout=0.2)`），退出条件不再只依赖队列里那一条 `"stop"`。
   - `SimulStreamingEngine.unload()` 补 `gc.collect()` 再 `empty_cache()`（引用没断干净拿不回全部显存）；`warmup()` 加 `_warmed` 短路（热引擎约 0.3 秒）。
2. **Ollama 侧原本没有任何卸载通路**（`check_local_translate.py` 里那个 `unload_model()` 主程序从不调用）。现在：`unload(model)` = `POST /api/generate {"model": m, "keep_alive": 0}`（OpenAI 兼容那条路没有通用卸载通路 → 返回 False 并说明）；`unload_others(keep)` 卸掉除 keep 之外的驻留模型；`resident_models()` 读 `GET /api/ps`。**换模型 / 点「测试连接」前先 `unload_others(新模型)`**（`preload()` 开头就做，开关 `unload_previous_llm_on_switch`）——8 GB 卡上多模型同驻会让 Ollama 把刚加载的挤掉再重载（见别处的 `aborting load`），表现就是"某些句子回落成原文"。生产代码里的 `unload()` **不同步轮询 `/api/ps`**（会卡界面），"是不是真卸掉了"交给 `check_gpu_reclaim.py` 去查。
3. **「停止翻译」原本什么都不回收**：现在停止分支会 `translation_worker.stop()`，而它同时把 `_requests`/`_results` 抽干——以前只把 `_running` 置 False，残留请求还在队列里，线程继续向 Ollama 发请求、不断续期 `keep_alive`（"闲置 30 分钟自动释放"因此几乎不发生）。注意工作线程是 daemon + `join(timeout=1)`，手上那条冷翻译最长 120 秒，**stop 兜不住它**，这一段正是闲置 sweep 要接住的。
4. 杂项：`ui_update_queue` 改有界（`maxsize=64`，满了一律丢弃——它只被 put 从不被 get）；`whisper_model.log` 加轮转（5 MB × 1 份备份）；`WhisperThreadPool(max_workers=2)` → 1（与它自己的 docstring 一致）并给 `get_model()` 加锁（切模型时两个 worker 会各加载一份、丢一份）；播放流存进 `self.output_stream` 让 `_cleanup_pyaudio` 关得到；`requirements.txt` 补 `requests`（**它本来就装上了**——googletrans 的依赖，所以"本地翻译不需要任何新 pip 依赖"这句依然成立）。

**第二轮又补了四条"只有真失败 / 真竞态 / 真漏账才触发"的漏口**（用户复测后仍报"还是有机会撑满，但不是每次都撑满"——因为这四条都藏在条件分支里，上面那条最短路径一条都碰不到；探针见 `check_gpu_reclaim.py --skip-paths`）：

5. **流式引擎中途失败后不卸载**（主因）：失败的 whisper 留在显存里，下一块音频立刻回退整句识别、又加载**另一份**，本轮同时驻留两份。→ `_retire_failed_engine()`，见"流式识别"一节。
6. **`_prepare_streaming` 收上一轮时的 join 竞态**：`_stream_round += 1` **挪到 `thread.join()` 之前**。旧线程的中途检查和 `finally` 都拿自己捕获的轮次号与 `self._stream_round` 比，先自增就能让它必定看到"我已经不是当前这一轮了"，于是不论从哪个分支退出都会自己 `unload()`。放在 join 之后有个真实的窗口：join 超时判成 `exited=False` → 不交接旧引擎 → `self.stream_engine` 被新引擎覆盖，而旧线程恰好在这两步之间退出，它退出时 `current()` 还是真 → 不卸；那个引擎对象连同 1.4 GB 显存从此谁都不再引用，`free_cuda_cache()` 也从没跑过，`nvidia-smi` 就一直高着（冷启、join 必超时的时候最容易撞上——这就是"不是每次都撑满"里最难复现的那条）。`exited=False` 时补一条日志（不再静默）。**代价是复用判据要多看一条 `self.stream_engine.ready`**：旧线程如果在 join 期间才退出，它的 `finally` 已经把那份引擎卸空了（"卸"是正确的——它不是当前这一轮），这时光比签名会误判成"复用"，日志写着复用、实际在 `warmup()` 里默默重加载。`ready` 为假就走重建那一支（`exited=True` → 把空引擎交给新线程 `unload()`（幂等）+ 建新的），日志和账本就都诚实了。
7. **账本漏账：加载了但没产出文本的整句模型永远不在账上**：`release_others` / `release_all` / `sweep` 的判据都要求 `resident`，而 `resident` 只在 `touch()`（= 识别出文本）里置真，预览识别的回调**不 touch**——于是"加载了整句模型但没产出文本"（预览、静音、识别异常）的路径上，模型**占着显存而账上写着没占**，连「释放显存」按钮都放不掉。→ `AudioProcessor._mark_model_resident()`，在**加载完成那一刻**（`_get_model_locked` 的两个返回点）就 `model_residency.touch("asr_batch")`。
8. **两处"差一点就对了"**：① `_release_stale_models(force=True)` 在 `is_running=True` 时绕过 guard，上一轮流式线程没退干净时会把它**正在用**的引擎抽走——现在 force 之前先看流式线程活不活，活着就跳过 `asr_simul` 只放别的；② Ollama 的 `/api/ps` 报的 `name` 可能带 `:tag`，而 keep 用的是配置里的裸名字，比较不归一化就匹配失败、老模型留下来与新模型同驻（→ 又撞上"挤掉重载 → 回落成原文"），现在比较前统一归一化（`_model_key`）。

**停止 = 只记一笔「刚用过」，不立刻卸**（这是"反复启停不卡"的关键：模型留在卡上给下一轮复用）。真卸载只有三条路：闲置到点自动 sweep、「释放显存」按钮、参数或模型变更。由此：

- **账本**：`register(key, label, release_fn, kind, idle_timeout, guard_fn)`，key 是 `asr_simul` / `asr_batch` / `llm`。`release_fn` **必须是"读当前状态"的薄绑定方法**（如 `_release_stream_engine`），**不许闭包捕获具体引擎对象**——引擎会按签名重建，捕获住的那个早就不是当前的了。`guard_fn` 挡住"正在识别时不许卸"（`lambda: not self.is_running`）。
- **`release()` 失败要把 `resident` 改回 True**：模型没真卸掉、账上却记成"已经没占着"，那它就再也不会被回收——这一轮修的正是这种静默的漏。而 `guard_fn` 自己抛异常要**放行**（记一笔然后照样卸），不能被一个坏 guard 拦住回收。
- 配置三项：`model_idle_unload_enabled`（关掉 = 只认手动点「释放显存」）、`model_idle_unload_sec`（默认 300）、`unload_previous_llm_on_switch`。**识别模型和本地大模型共用这一个秒数**——界面上就一个旋钮，配两个键等于撒谎。`MainWindow._apply_residency_settings()` 在 `__init__` 里把秒数写进账本；**`register()` 的默认 `idle_timeout` 是 `None`（从不）**，所以不带界面的脚本（`check_gpu_reclaim.py`）看到的账本超时是「从不」，这是对的，不是没生效。
- 界面：本地模型那一块**之外**加一行「显存」（`residency_label`）+「释放显存」按钮（`on_release_gpu` 后台线程跑 `release_all()` + `free_cuda_cache()`）；「高级设置」里本地模型那组加闲置秒数旋钮 + 「自动回收」勾选框。那一行刻意不放进 `local_llm_box`：**它报的是整台机器的驻留情况，识别模型才是大头的占位者**，换翻译引擎不该把它藏起来。
- `main.py` 里 `app.aboutToQuit` → `release_all(force=True)`：`closeEvent` 覆盖不到崩溃/被杀/注销这几条路。`closeEvent` 自己在原有的 `gc.collect() + empty_cache()` **之前**先 `release_all(force=True)` + `close_local()`。
- **`_stream_live()` 必须带后端守卫**（`self.asr_backend == "simul" and …`）：引擎保活之后，切回整句后端时 `stream_engine` 不再是 None，旧判据会让整句通路误以为流式还活着。加了守卫之后 batch 下返回值与以前**完全相同**（`stream_engine` 本来是 None），"整句行为逐字节不变"这条承诺得以保持。`get_stream_status()` 同理。
- **`unload()` 成功卸掉当前模型时必须清 `_warm_model`**，否则闲置卸载之后下一句仍按"热模型"用 3 秒超时发，而模型其实要冷加载（1.7B-Q8 实测 1.4 秒、9B 10.8 秒）→ 必然 ReadTimeout → 第 5 步回落成**英文原文**上屏。这是"译文质量差 / 屏幕混英文"的另一条来源。改服务地址或接口类型时也要 `forget_warm()`。
- **`requests.Session` 的实例属性不能叫 `self._session`**：和 `_session()` 方法同名，直接把方法盖成 `None`，报 `'NoneType' object is not callable`——本机实测的症状是 `check_gpu_reclaim.py` 的 Ollama 那一段整段静默地走"连不上"分支。属性名是 `self._http_session`。`_request()` 对**超时不重试**（超时是有意义的结论），只有连接类错误才丢会话重试一次。

**实测**（`python check_gpu_reclaim.py --cycles 4 --model small`，GTX 1070 Ti）：small 加载 2224 ms、预热 569 ms；4 轮启停线程数 `[0,0,0,0]`、引擎对象 1 份（复用）、已分配**恒定 933 MiB**（偏差 0）；`release_all()` 后回到 8 MiB；把闲置超时压到 1 秒再 `sweep()`，932 MiB 真的放成 8 MiB 且 `manager.stream_engine` 变 None。**这个探针本身会飘**：另一次同样的 `--cycles 4` 里前两轮的流式线程停完 3 秒内没退出（`[1,1,0,0]`），那两轮于是走了 join 超时那一支（重建引擎、旧的自己卸掉），显存那几项照样全过——所以现在**先等 `--settle`（默认 10 秒）再判"复用"**，没等到的那几轮只记一笔、不判违规（重建是设计内的兜底，`check_join_race` 专门验那条路）。

**三条条件路径的实测**（同机、`--model small --skip-ollama --skip-sweep`，一份 whisper 约 924 MiB）：失败回退——注入 `commit` 异常后状态变 `failed`、引擎当场变 None、账本记成没占着、显存 **932 MiB → 8 MiB**；join 竞态——确实两条线程同活（真进了超时那一支），旧线程自己退干净、`release_count=2`、峰值 1236 MiB（≈1.2 份，有上限）、折腾完 **8 MiB → 8 MiB**；账本漏账——`get_model()` 加载 base 后**一个字的音频都没喂**，账上照样 `resident=True`（8 → 287 MiB），`sweep()` 和 `release_all(force=True)` 各放掉一次、每次都回到 8 MiB。

## 需要注意的约定与陷阱

- **`settings.json` 是运行时的活配置**，被 git 跟踪，`config.set()` 每次都会立即写回文件。改动配置逻辑时留意兼容旧字段（`main_window.py` 的 `check_and_update_settings` 负责旧版本迁移）。**写文件必须原子**（`save_settings` 先写 `settings.json.tmp` 再 `os.replace`，另有 `_write_lock` 防多线程互踩）：曾经直接 `open('w')` 把文件截成 0 字节，结果所有设置静默回落到默认值（模型从 tiny 变 base）；`load_settings` 现在遇到坏文件会打印错误并留一份 `.broken` 备份，不再默默用默认值。
- **工作线程里绝不能让 print/警告抛异常**：标准流句柄失效时（重定向到已关闭的管道、无控制台），线程里的任何一句 print、tqdm 进度条或 `warnings.warn` 都会抛 `OSError [WinError 6] 句柄无效`，把整次识别结果一起毁掉（`main.py` 为此最先执行 `install_safe_streams()`，`safe_stream.SafeStream` 把写失败降级为丢弃）。Whisper 侧尤其注意 **`transcribe_options` 里必须 `verbose=None`**：进度条的开关条件是 `disable=verbose is not False`，也就是说 `verbose=False` 反而会打开进度条，而进度条写 stderr。本机 Triton 不可用，词对齐会走慢速 numpy DTW 并在 stderr 发一条 `Failed to launch Triton kernels` 警告，也走同一层兜底。
- **「显示音频数据统计信息」原来是勾了什么都不发生**：配置键 `show_audio_stats` 只被 `audio/audio_processor.py` 里那段**已经不跑的**同步 `process_audio`（`WhisperThreadPool` 走的是 `process_audio_async`，从不读它）打印一行控制台日志，界面上**从来没有任何显示的地方**。现在的落点：`AudioManager` 在 `_record_audio` 每块（那里本来就在算音量）更新一帧 `_audio_stats` 快照（采样率、块大小、本块峰值/RMS、本轮已采集秒数、本轮语音时长、底噪与判定阈值），`get_audio_stats()` 读它；界面「音频设备设置」组里加只读标签 `audio_stats_label`（等宽字体、可选中复制），**显隐跟着复选框走**（都从配置初始化，不各读一遍），节拍用**音量表那个 80ms 定时器**而不是 200ms 的翻译定时器——后者只在翻译进行中才跑，而统计恰恰要看"停了之后归零"（录音一停，超过 0.5 秒没更新就把峰值/RMS 报成 0，本轮累计留着）。那段死代码保持原样（同步接口仍可用），只补了注释。
- **音频一律走 MME 主机接口**（`AudioManager._enumerate_devices`）。本机实测（虚拟声卡回环验证）：DirectSound 能打开、能写入、能读设备名，但送出去的全是静音，采集侧同样失效；WASAPI 只接受设备原生采样率，16kHz 报 -9997。所以两个方向都用 MME，代价是设备名被截断到 31 字符。**若将来要换主机接口，先跑 `check_audio_output.py` 用耳朵+回环确认能出声，别只看 `p.open()` 是否成功**——DirectSound 就是这样骗过人的。
- **设备索引不可信，一律按名字重新解析**（`AudioManager.resolve_device_index`）：标签里的 `(Index: N)` 只是生成列表那一刻的快照，插拔耳机/蓝牙都会让索引整体错位。播放/录音前都按名字重新匹配，匹配时**先在自己用的那个主机 API 里找**（MME 名字被截断，完整名反而只存在于 DirectSound 条目里，先看完全匹配会挑到那个不出声的 API）。**唯一的例外是名字完全相同的设备**（两台同型号显示器，MME 截断后显示成同一条）：这时若标签里的索引仍指向一台同名设备就采用它，否则选同名设备里的第一台——实测两台 DELL 里只有接了音箱那台出声，不认索引就会把声音送进没音箱的那台且毫无提示。
- **Windows 特化**：设备名有两层处理——`clean_device_name` 修乱码/资源串（参与匹配），`display_device_name` 再去掉驱动样板名与被截断的半个括号（只用于下拉框显示，如 `DELL S2721DGF (NVIDIA High Defi` → `DELL S2721DGF`）。所以判断"是不是虚拟声卡/显示器接口"必须看原始名（`MainWindow._raw_device_name`），整理过的显示名里已经没有 `NVIDIA High Definition` 这些关键词了。此外：用 `os.startfile` 打开目录/文件；批处理脚本仅面向 Windows。
- **Whisper 版本：环境里是 `openai-whisper==20231117`**（`requirements.txt` 同步），torch 2.0.1+cu118。**20250625 升过一次、已回退**：它的 SDPA 路径在 torch 2.0.1 上跑不通，运行两分钟内 `direct_error.log` 就攒了 39 条 traceback（`RuntimeError: Expected key.size(1) == value.size(1)`、`cannot reshape tensor of 0 elements into shape [1, 0, 12, -1]`；而且崩过一次之后 `find_alignment` 注册的 cross-attention hook 会残留下来，`timing.py` 里那句 `QKs.__setitem__(index, outs[-1][0])` 接着报 `TypeError: 'NoneType' object is not subscriptable`）。**症状是逐词字幕消失、整句一次性蹦出来**：预览识别（`kind="partial"`）出错时在 `on_partial_complete` 里被静默丢弃，`WordReveal` 拿不到词，只有最终整句的结果到了屏幕上才有字。**要再升级得先把 torch 升上去**（或者强制 `use_sdpa=False`）。升级也换不来精度：两个版本的 `find_alignment`（softmax + 中值滤波 + DTW）、`_ALIGNMENT_HEADS`、模型 URL 完全一致。**词与声音对不上时别指望换版本解决**：实测（`check_word_alignment.py`）词起点误差随词间静音变长而变大——间隔 0.6 秒平均早 308ms，1.5 秒平均早 1032ms（DTW 会把一个词的跨度铺到前面的静音上），而同一份数据的**词中点**误差只有 12ms/432ms。间隔很小（正常说话）时起点误差不大，那时字幕偏了要查播放延迟的估算（`_OUTPUT_BUFFER_CHUNKS` 只按 2 块 ≈128ms 算，蓝牙耳机实际输出延迟远不止，字幕会整体偏晚）。要真正做到 YouTube 那样的对齐得换强制对齐方案（WhisperX 一类，wav2vec2 音素级对齐），不是换 Whisper 版本。
- **从文件识别要有 `ffmpeg.exe` 在 PATH 上**（`check_word_timestamps.py`、`check_word_alignment.py`）：20231117 经 `ffmpeg-python`（`openai-whisper` 的依赖，装它时自带）调 ffmpeg，20250625 改成直接 `subprocess` 调，两者都要那个二进制。conda 里的那份在 `envs\realtimetrans\Library\bin`，只有激活环境（`start.bat` / `activate.bat`）才在 PATH 里；直接用 `envs\...\python.exe` 跑脚本要自己把这个目录加进 PATH。实时识别传的是 NumPy 数组，不走这条路。
- **Whisper 模型**：默认缓存于 `~/.cache/whisper`，首次使用自动下载。`load_model` 对 large 模型有 GPU 显存不足降级 medium/CPU 的逻辑。
- **翻译依赖网络**（Google 翻译免费接口），无网络或限流时翻译会失败——`translate` 失败时回退返回原文/已处理文本，而非抛异常。**默认后端已经换成不依赖网络的本地 EuroLLM**（见"本地翻译"小节）；`translation_backend="google"` 才走这条公网路，界面上"翻译设置 → 翻译引擎"可以随时切。
- **本地翻译要有一个在跑的本机推理服务**（默认 Ollama 的 `http://127.0.0.1:11434`）。服务没起来、模型没拉下来、超时，都只记 `last_error` 并**抛给第 5 步的 except 去回落**（返回已处理文本），界面不崩但字幕会是原文；界面上"翻译设置 → 本地状态 / 测试连接"能直接看出是哪种情况。本机实测 EuroLLM-1.7B-Q8 在 GTX 1070 Ti 上是 100% GPU、约 3497 MiB 显存。
- **换模型报"测试失败"先怀疑加载，不要先改提示词**（`alibayram/erurollm-9b-instruct`、`SparkLLM/Spark-X2.5-1.7B` 都实测过）：9B 是纯冷加载比单句超时长（10.8 秒 vs 3000ms），Spark 是思考型模型把 token 全花在 `message.thinking` 上。两者的修法都在代码里（长超时 + `think:false`），提示词一个字没动。**这两条只对"能翻译的模型"成立**：Spark-X2.5 修完照样吐提示词残渣，不适合当翻译后端。
- **动过 Ollama 的加载期参数（`local_llm_num_ctx` 等）或 `local_llm_keep_alive` 之后，先跑一次 `preload()`（界面"测试连接"）**，否则下一次真翻译会撞上"换参数重载"。同一张显卡上驻留多个模型时，Ollama 会挑着卸（实测 8GB 卡上 qwen2.5 与 EuroLLM 同驻没问题，但加载大模型会挤掉小模型）。**现在我们自己会主动清场**：换模型/点测试连接前 `unload_others()`、闲置 `model_idle_unload_sec` 秒后自动卸、界面「释放显存」一按全放掉（见"显存回收"一节）。
- **判断"显存被谁占了"先看 `ollama ps` 和 `model_residency.describe()`，别只看 nvidia-smi**：识别模型（流式 small 约 1.4 GB）和本地大模型（EuroLLM-Q8 约 1.65 GB）是两笔独立的账，界面上「显存」那一行同时报这两笔；`nvidia-smi` 的数字还要跟别的进程分账，而且 `empty_cache()` 之后它会滞后一会儿才下来。
- **调试日志**：`audio/audio_manager.py` 内 `DEBUG_MODE = True` 会向控制台输出大量日志（日志同时写入 `whisper_model.log`）；`gui/main_window.py` 的 `DEBUG_MODE = False`。
- 术语库位于 `translation/resources/ham_radio_terms.json`，可通过编辑 JSON 扩展，`TermManager` 负责加载/校验/保存。
