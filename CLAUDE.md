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
```

- 检查逐词时间轴：`python check_word_timestamps.py <wav> [模型] [设备]`
- 查本地翻译为什么慢/为什么丢术语/换个模型为什么失败：`python check_local_translate.py [模型名] [--no-google] [--no-cold]`。逐句计时并打印 tok/s（**GPU 约 95 tok/s；掉到 13 tok/s 就是没吃上显卡**）、验术语（59/CQ/73/收到）有没有出现在译文里**并拒收"提示词残渣"**（`ECHO_MARKERS`：思考型模型会把 `来源：…` 这套脚手架一起吐出来）、把服务地址指到死端口确认"连不上也不抛异常、回落已处理原文"、**把模型卸掉并把单句超时压到 300ms 证明冷加载不算进单句超时**（`--no-cold` 跳过这项，它会真的装卸模型），最后和谷歌后端同一句对比耗时。跑的时候会临时改 `settings.json` 里的服务地址/模型/超时，退出前恢复。
- 查流式识别（SimulStreaming）在这台机器上跑不跑得动、快不快：`python check_simul_stream.py [模型] [--long-sec 28] [--no-eurollm]`。它量的是当初拦住 Stage 2 的那几个数：加载与预热耗时、单次提交耗时与实时倍率、**词时间是不是绝对流时间**（拿 `check_word_alignment.py` 那套真值验）、终稿靠不靠得住、与 EuroLLM 同驻会不会 OOM；`--long-sec` 加测"连着说 N 秒"的单次提交耗时（`simul_max_utterance_sec` 的依据，**必须用真实语音**，见下）。
- 量同步误差是谁的锅：`python check_word_alignment.py [模型] [间隔秒 ...]`。用 Windows 自带语音合成把词按固定间隔摆好（真实起点已知），再跑一遍识别，打印"Whisper 给的词起点 vs 真值"的误差——用来分清"字幕对不上声音"是识别的时间轴不准，还是我们自己的播放进度算错了。
- 检查原文两行 / 换句滚动 / 译文行溢出上滚：`python check_reveal_scroll.py`。离屏（`QT_QPA_PLATFORM=offscreen`）喂一串脚本化的句子，每隔 20ms `grab()` 一次扫像素，用文字行的位置验几何：行距 = `lineSpacing()`、第一行贴框顶、逐词增长时位置不动、滚动全程不超两行且滚完停在原位、不翻译模式也两行、整句通路不被裁剪，以及上/中/下三处间隙相等、窗口高度正好贴内容、间隙随字号变（`--live` 用 settings.json 里那套）。译文行那几项按"框 = min(行数,2) 行、内容按实际行数、偏移 = (行数−2)×行距"验。另验两条**不是几何的**：关掉「原文逐词显示」后原文整句也左对齐（用左边第一个墨点验），且折成两行的整句不被裁、窗口跟着长；「仅显示译文」下逐词原文一个字都不许上屏（说话期间整窗无墨），译文只在整句译文到了才出现。不带音频/Whisper。
- 检查设置面板：`python check_settings_ui.py`。离屏建一次 `MainWindow`（不启音视频/识别），验整页在 `QScrollArea` 里、左右两列、"高级设置"默认收起、启动尺寸夹到屏幕可用区域，以及合并后的「语音识别设置」：只有一个模型下拉、候选随后端变、**流式后端下回填整句模型名不许写进 `simul_model`**、流式那几行按后端显隐，以及两个逐词开关（「原文逐词显示」/「译文逐词显示」）都在、勾选状态来自配置，旧的「边说边翻译」已经不存在、`simul_prefix_spin`（译文刷新间隔）两种后端下都看得见。脚本会写 settings.json（`resizeEvent` 存窗口大小），跑完原样放回。

## Architecture

顶层是 `main.py` → `QApplication` + `gui/main_window.py` 的 `MainWindow`。各包职责：

- `gui/main_window.py` — 主窗口，承载所有设置项与"开始/停止翻译"按钮。通过 `QTimer`（200ms）轮询 `AudioManager`：先按播放进度推进逐词原文，再取最新整句识别文本交给后台翻译线程 `translation/translation_worker.py`，译文回来再补上（翻译不在 GUI 线程里做）；另有一路「译文逐词显示」（`translation_word_by_word`，两种识别后端都有）：把还没定稿的**半截原文**节流后送去翻译，译文跟着原文一起长（`_update_prefix_translation`，见"译文逐词显示"一节）。**设置面板**（`init_ui`）：整页装在 `QScrollArea` 里（一屏放不下就滚动，不裁内容），分组排成**左右两列**，"高级设置"（`QGroupBox` 可勾选 + 内部容器 `setVisible`，Qt 的勾选框自己不会折叠内容）默认收起，装的是不常改的项——流式的提交间隔/注意力阈值/一句话最长、本地服务的地址/接口类型/单句超时、字幕窗口宽高。启动尺寸按 `primaryScreen().availableGeometry()` 夹一下（本机存过 897×1360，比 1080p 屏还高）。
- **「语音识别设置」是合并出来的**（`_build_asr_group`）：整句 Whisper 和流式 SimulStreaming 共用一个**模型下拉** `asr_model_combo`，候选按后端取（`ASR_MODEL_CHOICES`：整句 tiny~large / 流式 tiny~medium），值各写各的键（`whisper_model` / `simul_model`）——所以配置不迁移、两个后端都记得自己选的模型。`on_asr_model_changed` 分派：整句沿用 `on_model_changed`（立刻加载进显存），流式只存配置。**坑在回填**：`_update_after_load` / `update_model_status` / `_force_unlock_ui` 会把"实际加载的整句模型"写回下拉，流式后端下这个下拉显示的是流式模型，直接写就会经信号把整句模型名写进 `simul_model`，所以那几处一律走 `_sync_asr_model_combo()`（非整句后端直接返回），而"整句的模型名"读 `_batch_model_name()` 而不是下拉文本。流式那两行（流式状态，及高级里的流式参数）与整句的状态行由 `_update_stream_controls_enabled()` 按后端显隐（以前是置灰）；**「译文刷新间隔」不在流式那一组里**——从前的「边说边翻译」只在流式后端下有效，现在的「译文逐词显示」（见下）两种后端都吃，所以节流间隔也跟着搬进公共的高级设置。
- `gui/subtitle_window.py` — 无边框、置顶、半透明的悬浮字幕窗 `SubtitleWindow`，独立于主窗口，显示原文/译文。两个标签各装在一个定高裁剪框 `RevealViewport` 里（换句时靠它整块上滚一行）；`set_original_words` 专门给逐词通路用（含逐词行的左对齐排版与两行上下文）。**原文行一律左对齐**（逐词行和整句行都是），**「仅显示译文」下逐词原文一个字都不上屏**（`_word_reveal_visible()`）——见"音频时钟与逐词字幕"一节。**译文行跟原文行一个待遇**：左对齐 + 折行超过两行时往上滚（`_translation_reveal` 判"这行归译文视口管吗"，`_set_translation_rows` 是对账点），不再把窗口撑高（见"音频时钟与逐词字幕"一节）。
- `gui/word_reveal.py` — `WordReveal`：拿带块号的词表 + 当前播放位置，算出"这一刻该显示到哪个词"（连同上那句的全文，给界面摆两行用），返回 None 表示不用重绘。纯逻辑（无 Qt/音频依赖）。单测见 `test_word_reveal.py`。
- `audio/audio_timeline.py` — 逐词字幕的时间轴数据结构（`TimedWord`/`WordSegment`/`AudioSegmentTask`），刻意做成不引入 whisper/torch 的叶子模块，供界面和单测导入。
- `audio/audio_manager.py` — `AudioManager`，音频管线编排中心。整句通路三条线程：录音（`_record_audio`，做音量 VAD 分段）→ 识别（`_recognize_audio`）→ 播放（`_playback_audio`，仅监听系统声音时）。用 `queue.Queue` 在线程间传 NumPy 音频数据。流式通路（`asr_backend="simul"`）另加一条 `_stream_recognize`（见"流式识别"一节），此时前两条线程里的整句识别部分空转。
- `audio/simul_asr.py` — `SimulStreamingEngine`，把 vendored 的 SimulStreaming（AlignAtt）包成"喂一块 → 攒够就解 → 出已确认前缀 / 句尾定稿"的接口。只被 `_stream_recognize` 那一条线程调用，内部不上锁。上游那三个坑写在文件头。
- `third_party/` — vendored 的 ufal/simulstreaming（MIT，来源与改动见 `third_party/PROVENANCE.md`），只有流式识别用得到。
- `audio/audio_processor.py` — `AudioProcessor`（Whisper 模型加载、CUDA/CPU 选择、降级逻辑）+ `WhisperThreadPool`（后台异步识别，带超时取消）。同步 `process_audio` 与异步 `process_audio_async(callback)` 两套接口。
- `translation/subtitle_manager.py` — `SubtitleManager`，翻译管线编排：术语处理（`TermManager`）+ 传输层（第 5 步按 `translation_backend` 分派到本地模型或 googletrans）+ 整段结果的 LRU 缓存 + 延迟统计。
- `translation/local_llm_translator.py` — `LocalLLMTranslator`，**默认的翻译后端**：HTTP 调本机的 Ollama（或 llama.cpp 的 llama-server）。含探活 `health()`、预热 `preload()`（真跑一步 `num_predict=1`，加载期选项与真翻译一致）、真翻一句的 `self_test()`（界面"测试连接"用，把加载与翻译两段耗时分开报）、耗时明细 `last_stats`；方法一律不抛异常，失败只记 `last_error` 并返回 None。
- `translation/term_manager.py` — `TermManager`，业余无线电术语处理：信号报告转换（"five nine"→"59"）、字母解释法呼号还原（"Alpha Bravo"→"AB"）、术语占位符保护。
- `translation/subtitle_file_manager.py` — `SubtitleFileManager`，将识别结果写为 `Subtitles/*.srt`。
- `config.py` — 全局单例 `config`，JSON 持久化到 `settings.json`，自动补齐默认项。

### 关键数据流

整句识别（`asr_backend="whisper_batch"`，默认）：音频 → 录音线程（VAD 分段）→ `audio_queue` → 识别线程 → `WhisperThreadPool` 异步识别 → 回调 → `result_queue`/`text_queue` → 主线程 `QTimer` 轮询 → `SubtitleManager.translate` → `SubtitleWindow.update_text`。

流式识别（`asr_backend="simul"`）：音频 → 录音线程（VAD 只用来定句子的起止）→ `stream_queue` → `_stream_recognize` 线程 → 引擎攒够就解 → **前缀**（只喂 `word_queue` + `get_committed_prefix()`，界面拿去「译文逐词显示」）／**终稿**（走上面那条一模一样的出口，含 SRT）→ 主线程 `QTimer` 轮询。

### 翻译管线（顺序固定）

`SubtitleManager.translate` 内依次执行：信号报告转换 → `direct_translate`（整词术语直译）→ 字母解释法呼号还原 → `preprocess_ham_radio_terms`（术语替换为 `__TERM_N__` 占位符）→ **`_transport_translate`（第 5 步的传输，按 `config["translation_backend"]` 分派：`local` = 本机 EuroLLM（默认），`google` = googletrans 公网接口）** → `restore_ham_radio_terms`（还原占位符）。除第 5 步外，其余各步两套后端共用，一行未动。

第 5 步失败仍然**抛异常**，由原来的 `except` 接住、返回已处理的文本（字幕不会崩）。缓存的是**整段管线的最终结果**（键 = 后端签名 + 目标语言 + 原文），只有走完全程的结果才进缓存；后端签名含引擎/地址/模型名，所以换引擎或换模型不会命中旧译文。

### 本地翻译（EuroLLM，默认后端）

- 走 **Ollama 的 HTTP 接口**（`POST /api/chat`，另支持 `local_llm_api="openai"` 指向 llama-server 的 `/v1/chat/completions`），**不需要任何新的 pip 依赖**（只用 `requests`），也就绕开了 Python 3.8 装不上新轮子的死结。默认 `cas/eurollm-1.7b-instruct-q8:latest`，本机实测 GPU 上 **100 tok/s、单句 76~285ms（平均 162ms）**，而 googletrans 是 2.1~2.7 秒（`check_local_translate.py` 里能两者对比着看）。
- **提示词必须按 EuroLLM 官方格式**：指令在 user 回合里，写成 `Translate the following English source text to Chinese:\nEnglish: …\nChinese:`（源语言未知时用 `Source:`）。换成"system 里讲一段话"的自由写法，1.7B 会答非所问。system 只放"只输出译文"这条纪律。
- **术语标记绝不出现在提示词里**（`_translate_segments`）：实测 1.7B 对 `__TERM_0__` 极不老实——同一个标记出现两次会被**合并成一个**（"CQ CQ … CQ CQ" 只剩一个 CQ）、标记后面跟着括号注释（"73（最好的祝福）"）时会连标记一起吃掉、即便数量对**位置也不对**（标记被挪到句尾）。所以做法是**把标记当分隔符切开，只把中间的纯文本片段发给模型，标记由我们自己拼回去**，位置和数量都确定，第 6 步的 `restore_ham_radio_terms` 照旧把术语贴回来。代价是带 N 个术语的句子要发 N+1 个请求（都是短句，实测每条 100~200ms）。标记后面那份重复的括号注释（`_strip_glosses`）也要先摘掉，否则会被当成正文再翻一遍。
- `keep_alive` 别去掉：模型闲置 5 分钟就被 Ollama 卸掉，下一句要重新加载（**冷加载实测 6.5 秒**，这也是"第一次翻译特别慢"的原因）。
- **冷加载不能算进"单句超时"**（`_LOAD_READ_TIMEOUT_S` = 120 秒 / `_warm_model` / `preload()`）：`requests` 的读超时管的是"等到第一个字节"，而模型从磁盘进显存全发生在第一个字节之前。实测冷加载 **1.7B-Q8 1.4 秒、9B-Q4（5.6GB）10.8 秒、Spark-1.7B 4.4 秒**，而 `local_llm_timeout_ms` 默认 3000 —— 换个模型之后第一句必然以 ReadTimeout 告终、回落成原文，**这就是"切其他模型测试失败"的原因，不是提示词的问题**（9B 热起来单句只要 0.5 秒、译文正确）。做法：记一个 `_warm_model`，没热过的第一次请求用 120 秒兜底，成功之后回到配置里的单句超时；**热着超时说明模型其实早被卸了**，这时把 `_warm_model` 清掉，下一次请求自动按加载放宽（丢一句，但会自己爬起来）。
- **`preload()` 必须是"真跑一步最小生成"（`num_predict=1`），且 options 与真翻译逐字一致**（都走 `_ollama_options`）。两个坑实测都踩过：① `/api/generate` 不带 prompt（"只加载不生成"）同样花掉整个加载时间，却不保证模型留在显存里；② `num_ctx` 这类**加载期**参数两边不一样时，Ollama 会在紧接着的翻译请求上把刚加载好的 runner 卸掉重载（`-c 2048`，实测 5.06 秒），客户端一超时断开，Ollama 连这次重载也取消（日志：`aborting load` / `context canceled`），最后显存里什么都不剩 —— 表现为"preload 报已就绪、紧接着按热模型发请求还是超时"。排查这类问题**先看 Ollama 自己的日志**（`%LOCALAPPDATA%\Ollama\server.log`），它会写明是加载、换参数重载还是被取消。
- **思考型模型要显式关掉思考**（payload 里的 `"think": False`）：Spark-X2.5、DeepSeek-R1 这类默认先把推理写进 `message.thinking`，实测 Spark-1.7B 把 256 个 token（`num_predict` 上限）全烧在思考上，`content` 是空串、`done_reason='length'`，字幕上什么都拿不到。加上 `think: false` 之后有输出了，但 **Spark-X2.5 仍然不适合当翻译**：它会把提示词脚手架一起吐出来（"收到，来源：罗杰，收到，。"、"您的信号是59\n。中文"），`check_local_translate.py` 的 `ECHO_MARKERS` 专门拒收这类残渣。EuroLLM-1.7B/9B 实测都接受这个字段（不支持的模型会忽略它），所以无脑加；OpenAI 兼容那条路不加（那边开关思考是 chat template 的事，多塞字段可能被严格的实现拒掉）。
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
- **行盒高度按行距算，不按字号盒子**（`_label_line_height`）：逐词行正好一个行距（上下内边距 0），整句通路（居中）才是 `行距 + 上下内边距`——标签盒比"文字 + 内边距"矮，字就会被裁掉半截。整句通路按实际折行数给高度（`_label_text_lines` 用 `QFontMetrics.boundingRect` 量）——**只有还走整句排版的那条路是这样**；译文行归译文视口管时框高封顶两行、再长往上滚（见下一条），窗口只在"1 行变 2 行"的那一下长一个行距。**原文行左对齐之后这里有个坑**：`adjustLabelHeights` 的行数原本写死 `lines = 2 if _reveal_two_lines() else 1`，靠 `_set_label_rows`（只对**非左对齐**标签生效）自动抬到实测折行数——原文一左对齐，那个兜底就失效了，折成两行的整句会被裁成一行。所以非两行模式下取 `max(1, self._label_text_lines(self.original_label))`。
- **换句向上滚一行**（`set_original_words` + `_start_reveal_scroll`）：触发信号是 `utterance_id` 变化（`RevealLine` 早就带着它，界面以前没用），且要 `previous_text` 非空、两行模式、**当前框里已经有 `\n`（两行）**——这一轮的第一句不滚：它本来就占着第一行，滚了只会把唯一那行送出框外空一下。动画是 `QVariantAnimation`（OutCubic，`REVEAL_SCROLL_MS = 200`），距离 = 一个行距。**动画期间不动文本**，新文本只存进 `_reveal_pending`，`finished` 时偏移归零再一起贴上（滚动中途改文本画面会跳）——延迟 ≤200ms 而新句第一个词本来就要 1s 上下才识别出来，肉眼无感。切模式（`set_subtitle_mode`）、重开一轮（`reset_reveal_layout`）、窗口藏起来（`hideEvent`）都要 `_stop_reveal_scroll()`，免得动画停在半路。`hideEvent` 那里要 `apply_pending=False`：`_set_reveal_text` 见窗口不可见会 `show()`，等于关不掉。
- **译文行也是裁剪框视口**（左对齐 + 溢出往上滚，`_translation_reveal` / `_set_translation_rows` / `_sync_translation_scroll`）：以前译文走整句通路——居中、折几行就把窗口撑高几行（「译文逐词显示」开着时每 800ms 长一段，窗口就一跳一跳地变高）。现在**框里最多留两行，内容按实际行数摆，偏移让最后两行正对着框**，行距一律用 `_reveal_line_pitch`（= `lineSpacing()`）：

  | 折行数 N | 框高（裁剪框 `minimumHeight`） | 内容高（标签） | 偏移 |
  |---|---|---|---|
  | 1 | 1 个行距 | **0**（标签填满框，`RevealViewport` 的既有契约） | 0 |
  | 2 | 2 个行距 | 2 个行距 | 0 |
  | ≥3 | 2 个行距 | N 个行距 | (N−2) 个行距 |

  框高取 `min(N, 2)` 而不是死钉 2 行：钉死的话一行译文要么上面空一个行距、要么下面空一个行距，上/中/下三处间隙的视觉平衡就破了（几何相等但字的位置差一个行距）。代价是**译文从 1 行变 2 行时窗口高一个行距**（三处平分，`bottom` 定位下顶边上移）；不想要这点起伏就把 `min(lines, TRANSLATION_ROWS)` 换成 `TRANSLATION_ROWS`，代价是那个视觉不平衡。

  - `_translation_reveal()` 是**无状态判据**：`not translation_disabled() and subtitle_mode != "original"`，就这一句，没有例外。不用记"这行现在装的是谁"，模式和配置就能推出来。（以前还有一条例外：`translated` 模式下逐词原文会**借译文标签**占位，那一行归逐词通道管、整句译文只能居中——见下面"仅显示译文"一条，这个借用已经删掉了。）
  - 由此 `_reveal_alignment` 的译文分支是 `AlignLeft|AlignTop`（**顶对齐是尾窗滚动的前提**，`AlignVCenter` 的取整误差会让滚完的最后一行差一两像素）；`_label_vpadding` 对左对齐标签返回 0，所以译文框 = 行数 × 行距，一格不多。
  - `_label_text_lines` 在左对齐标签上按 `_reveal_avail_width`（标签宽 − 内边距 − 左边留白）量：按居中口径量会**少算一行**，而偏移是拿行数算的，少一行最后一截就露不出来。
  - `_set_label_rows(label, lines, content_lines=None)` 把**框**里几行（窗口高度看它）和**内容**几行（滚动距离看它）分开，默认相等 → 原文行的调用逐字节不变。
  - `_sync_translation_scroll(lines)`：目标 = `(lines − 2) × 行距`，先把当前偏移**夹进 `[0, 目标]`** 再动（文本变短时不会出现"内容比偏移还短、屏幕空一块"）；**目标没变就直接返回**（`adjustLabelHeights` 每 200ms 被逐词通道叫一次，无脑重启动画会让一次 600ms 的滚动永远走不完）；动画是 `QVariantAnimation`（OutCubic），时长 `min(MAX_TRANSLATION_SCROLL_MS = 600, 200 × 跳过的行数)`——逐词/前缀那样一行行长出来的是 200ms，和原文行一个手感，整句终稿一次折很多行时按行数延时滑过去，不至瞬移。**不判断"新文本是不是旧文本的延长"**：翻译器会重写前缀，按 `startswith` 分派反而认错，上面"夹住 + 目标没变就返回"对延长和替换一视同仁。
  - 状态只有 `_t_scroll_anim` / `_t_scroll_target`，和原文行的 `_scroll_anim` / `_scroll_view` / `_reveal_pending` **完全分开**（两行可能同时在滚）；译文行也不需要 `_reveal_pending` 那套"滚动期间不动文本"——它只挪偏移，中途换文本不会露出错的中间帧。
  - `_set_translation_rows()` 是**对账点**：切模式、改字号、重开一轮未必先写过译文，所以排版也在这儿一并摆好（`adjustLabelHeights` 每轮叫它）。非译文视口的分支必须 `_stop_translation_scroll(reset=True)` 把偏移清 0——`_place_child` 在内容高度 0 时按框高走，残留的旧偏移会把短文本顶出框外。`clear_translation`（切"不翻译"）也自己调一次对账，不等下一轮轮询。`hideEvent` 只停**不 reset**（文本没变，再显出来还得指着尾窗那一屏；原文行不一样——它滚完要归零再贴新文本），`reset_reveal_layout` 则 reset。
- **窗口高度默认贴着内容走**（`window_height_auto` / `_fit_window_height`）：`_required_height()` = 三处间隙 + 各可见裁剪框的最小高度，高度就是它——字号/行数一变，窗口跟着收放（译文行只在 1 行↔2 行之间变，再长往上滚），不会在原文和译文之间挂一片空白。`window_height_auto = False` 表示"高度是用户定的"：设置里改过高度（`on_window_height_changed` → `_lock_window_height`）或**按住鼠标**拖右下角（`resizeEvent` 里查 `QApplication.mouseButtons()`）之后就是这种状态，之后一律按他定的高度来（多出来的空间三处平分）。为什么要看鼠标键：Qt 自己在显示/隐藏过程中发的 resize 不该被当成"用户拖的"，否则高度一次就锁死、再也不跟着内容走。另外 Qt 的 `setFixedSize` 走的是 C++ 的 `resize`（`QWidget.resize` 不是虚函数），绕不过我们的重写，所以 `showEvent` 里那次精确尺寸要用 `_auto_set_fixed_size` 包一下（`_auto_resize_depth` 计数），不然同样会被当成用户拖的。
- **仅显示译文**（`subtitle_mode == "translated"`）：屏幕上**只**有译文，说话期间那一行是空的，原文一个字都不上屏。判据是 `_word_reveal_visible()` ＝ `not (subtitle_mode == "translated" and not translation_disabled())`：`set_original_words` / `_set_reveal_text` 开头照它直接返回（后者顺带丢掉 `_reveal_pending`），`set_subtitle_mode` 切进来时停滚 + 丢 `_reveal_pending` + 把原文标签清空（免得切回"两者"时闪一眼上一句旧文本）。**这里曾经有三处来源让原文先冒出来、还穿着译文的字体颜色/字号**：① 逐词通路**借译文标签**（`_reveal_label`）——译文标签被原文占了，颜色字号自然整套都用译文的；② `update_text` 单参数版在 `translated` 模式下照样写译文行；③ `update_text` 双参数版"没有译文就先拿原文顶一下"；外加 `_show_original_text` 在 `translated` 模式下也照写。四处全删了，所以**不管谁调用，`translated` 模式下译文行只可能由真译文写入**。（"不翻译"是例外：`translation_disabled()` 时模式虽然也是"仅显示译文"，但屏幕上本来就该只有原文，所以不屏蔽。）
- **不翻译**（目标语言选"不翻译"→ `target_language = "none"`）：只走原文通路，不提交翻译请求，字幕窗只留原文行（`SubtitleWindow.translation_disabled` 会强制隐藏译文行）。
- 排查工具：`python check_word_timestamps.py <wav> [模型] [设备]` 打印每词时间轴，用来区分"逐词不生效"是模型问题还是设置问题；`python check_reveal_scroll.py`（`--live` 用 settings.json 里那套字号/窗口）离屏喂一串脚本化的句子、扫像素验几何（行距、贴顶、滚完不跳、不翻译模式也两行、整句通路不被裁剪），并逐个量：上/中/下三处间隙必须相等、等于 `_row_gap()` 那个按字号算的基准、窗口高度正好是 `_required_height()`，字号改大时间隙跟着变大，把窗口拉高 90px 后三处各分到 30px；译文行那几项按上表验——框 = `min(行数,2)` 行、内容按实际行数、偏移 = `(行数−2)×行距`，可见的正是最后两行、首行贴框顶、窗口高度不变（滚动不吃窗口高度）、`clear_translation` 后偏移归零、1 行→2 行只长一个行距、3 行时偏移是渐变而非瞬移、切模式后偏移归零；还验"关掉逐词后原文整句也左对齐、折两行不被裁、窗口跟着长"和"仅显示译文下说话期间整窗无墨、译文只在整句译文到了才出现"。开关 `word_by_word_enabled=False` 可完全退回整句原文行为，`translation_word_by_word=False` 可完全退回整句译文行为。

### 流式识别（SimulStreaming，`asr_backend="simul"`）

默认仍是 `asr_backend="whisper_batch"`（就是上面这一整套）。切到 `simul` 后，识别改由 `audio/audio_manager.py` 的 `_stream_recognize` 线程负责：录音线程**不再提交整句识别**，只把音频一块块喂过去（`_stream_begin` / `_stream_chunk` / `_stream_end` 三个事件走 `stream_queue`），引擎攒够 `simul_commit_interval_ms` 就解一次，每次给出"已确认前缀"（算法是上游的 AlignAtt：离音频末尾 `simul_frame_threshold` 帧以内的部分不解码、末尾未确认的词一律截断，所以前缀只会往后长、不会缩）。

- **时钟仍然只有 `captured_chunks`**：引擎侧的词时间是**绝对流时间**（`begin_utterance(offset_sec)` 内部调上游的 `online.init(offset=…)`），`_stream_timed_words` 一步换算成采集块号（`round(秒 × 16000 / 1024)`），与整句那条路同一个参照系——`WordReveal` / `SubtitleWindow.set_original_words` 的签名和语义**一行都没动**，流式只是更频繁地喂非 final 的 `WordSegment`（与 `kind="partial"` 完全同构）。
- **前缀只喂显示，SRT 只认终稿**：前缀（`is_final=False`）只进 `word_queue` 和 `get_committed_prefix()`（界面拿去「译文逐词显示」，见下一节）；终稿（`is_final=True`）走和整句识别**完全一样**的出口（`text_queue` / `result_queue` / `add_subtitle` / `ui_update_queue`），所以 `Subtitles/*.srt` 里永远只有整句。`get_committed_prefix()` 返回 `(utterance_id, text)`。
- **自动回退**：引擎加载/预热失败、或连续 3 次提交出错 → `_stream_state="failed"`，录音线程从下一块音频起改走整句识别。它全程照常攒 `recognition_buffer`，所以一段音频都不会丢，也不需要回滚任何状态；界面「流式状态」那行显示原因。
- **`whisper_batch` 下新增代码一律不执行**：`_record_audio` 里每处流式分支都先问 `_stream_live()`（引擎在且没崩）。这是"两边行为逐字节一致"的保证。
- **每 4 秒的兜底提交（`stalled_submit`）在流式下关掉**：字幕本来就是边走边出，不存在"长时间不更新"；而每 4 秒硬切一刀会把连着的句子劈成两半、接缝处还丢两块。长句交给 `simul_max_utterance_sec`。
- **纯静音攒到上限不给引擎发"句结束"**：一轮里没有语音起点时 `begin` 从没发过，引擎那边没在跟，只清缓冲区（否则每 25 秒白叫一次定稿）。
- **实测代价**（`python check_simul_stream.py small --long-sec 28`，small + GTX 1070 Ti + 真实语音）：单次提交 190~330 ms（28 秒时最慢 330 ms，提交间隔 800 ms），定稿 150~220 ms，torch 峰值 1403 MiB；加载 2.5 s、预热 0.9 s（第一次解码要编译 CUDA 内核，所以开始翻译前先 `warmup()`，这期间音频排着队，就绪后一口气追平）。**显存**：流式模式下不会去加载整句模型（`audio_queue` 全程空转），但用户之前手动加载过的那个仍占着显存；流式 small 1.4 GB + EuroLLM-Q8 1.65 GB 同驻没问题。
- **量长句的代价必须用真实语音，不能用"同一批词重复摆"**：重复内容会把贪婪解码带进重复死循环（实测 20 秒的重复词表被识别成 141 个词 ≈ 7 词/秒，正常语速 2.6），而 `finish()` 内部写死了 `frames_threshold=4`（比我们的 12 松得多），一旦解不出句尾就一路解到 448 token 上限，词对齐的张量跟着涨到 GB 级——定稿一次 **75 秒**、吃掉 5 GB 显存（`check_simul_stream.py` 的 `synth_passage` 就是为此用 SAPI 念整段真实话）。
- 第三方源码在 `third_party/`（ufal/simulstreaming，MIT，来源与改动见 `third_party/PROVENANCE.md`），它内部按 `simulstreaming.*` 绝对导入，路径由 `audio/simul_asr.py` 的 `add_library_to_path()` 插到 `sys.path` 最前（认"同目录下既有 `simulstreaming/` 包又有 `simulstreaming_whisper.py`"这种长相，也可以用 `SIMULSTREAMING_HOME` 指到别处）。
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

## 需要注意的约定与陷阱

- **`settings.json` 是运行时的活配置**，被 git 跟踪，`config.set()` 每次都会立即写回文件。改动配置逻辑时留意兼容旧字段（`main_window.py` 的 `check_and_update_settings` 负责旧版本迁移）。**写文件必须原子**（`save_settings` 先写 `settings.json.tmp` 再 `os.replace`，另有 `_write_lock` 防多线程互踩）：曾经直接 `open('w')` 把文件截成 0 字节，结果所有设置静默回落到默认值（模型从 tiny 变 base）；`load_settings` 现在遇到坏文件会打印错误并留一份 `.broken` 备份，不再默默用默认值。
- **工作线程里绝不能让 print/警告抛异常**：标准流句柄失效时（重定向到已关闭的管道、无控制台），线程里的任何一句 print、tqdm 进度条或 `warnings.warn` 都会抛 `OSError [WinError 6] 句柄无效`，把整次识别结果一起毁掉（`main.py` 为此最先执行 `install_safe_streams()`，`safe_stream.SafeStream` 把写失败降级为丢弃）。Whisper 侧尤其注意 **`transcribe_options` 里必须 `verbose=None`**：进度条的开关条件是 `disable=verbose is not False`，也就是说 `verbose=False` 反而会打开进度条，而进度条写 stderr。本机 Triton 不可用，词对齐会走慢速 numpy DTW 并在 stderr 发一条 `Failed to launch Triton kernels` 警告，也走同一层兜底。
- **音频一律走 MME 主机接口**（`AudioManager._enumerate_devices`）。本机实测（虚拟声卡回环验证）：DirectSound 能打开、能写入、能读设备名，但送出去的全是静音，采集侧同样失效；WASAPI 只接受设备原生采样率，16kHz 报 -9997。所以两个方向都用 MME，代价是设备名被截断到 31 字符。**若将来要换主机接口，先跑 `check_audio_output.py` 用耳朵+回环确认能出声，别只看 `p.open()` 是否成功**——DirectSound 就是这样骗过人的。
- **设备索引不可信，一律按名字重新解析**（`AudioManager.resolve_device_index`）：标签里的 `(Index: N)` 只是生成列表那一刻的快照，插拔耳机/蓝牙都会让索引整体错位。播放/录音前都按名字重新匹配，匹配时**先在自己用的那个主机 API 里找**（MME 名字被截断，完整名反而只存在于 DirectSound 条目里，先看完全匹配会挑到那个不出声的 API）。**唯一的例外是名字完全相同的设备**（两台同型号显示器，MME 截断后显示成同一条）：这时若标签里的索引仍指向一台同名设备就采用它，否则选同名设备里的第一台——实测两台 DELL 里只有接了音箱那台出声，不认索引就会把声音送进没音箱的那台且毫无提示。
- **Windows 特化**：设备名有两层处理——`clean_device_name` 修乱码/资源串（参与匹配），`display_device_name` 再去掉驱动样板名与被截断的半个括号（只用于下拉框显示，如 `DELL S2721DGF (NVIDIA High Defi` → `DELL S2721DGF`）。所以判断"是不是虚拟声卡/显示器接口"必须看原始名（`MainWindow._raw_device_name`），整理过的显示名里已经没有 `NVIDIA High Definition` 这些关键词了。此外：用 `os.startfile` 打开目录/文件；批处理脚本仅面向 Windows。
- **Whisper 版本：环境里是 `openai-whisper==20231117`**（`requirements.txt` 同步），torch 2.0.1+cu118。**20250625 升过一次、已回退**：它的 SDPA 路径在 torch 2.0.1 上跑不通，运行两分钟内 `direct_error.log` 就攒了 39 条 traceback（`RuntimeError: Expected key.size(1) == value.size(1)`、`cannot reshape tensor of 0 elements into shape [1, 0, 12, -1]`；而且崩过一次之后 `find_alignment` 注册的 cross-attention hook 会残留下来，`timing.py` 里那句 `QKs.__setitem__(index, outs[-1][0])` 接着报 `TypeError: 'NoneType' object is not subscriptable`）。**症状是逐词字幕消失、整句一次性蹦出来**：预览识别（`kind="partial"`）出错时在 `on_partial_complete` 里被静默丢弃，`WordReveal` 拿不到词，只有最终整句的结果到了屏幕上才有字。**要再升级得先把 torch 升上去**（或者强制 `use_sdpa=False`）。升级也换不来精度：两个版本的 `find_alignment`（softmax + 中值滤波 + DTW）、`_ALIGNMENT_HEADS`、模型 URL 完全一致。**词与声音对不上时别指望换版本解决**：实测（`check_word_alignment.py`）词起点误差随词间静音变长而变大——间隔 0.6 秒平均早 308ms，1.5 秒平均早 1032ms（DTW 会把一个词的跨度铺到前面的静音上），而同一份数据的**词中点**误差只有 12ms/432ms。间隔很小（正常说话）时起点误差不大，那时字幕偏了要查播放延迟的估算（`_OUTPUT_BUFFER_CHUNKS` 只按 2 块 ≈128ms 算，蓝牙耳机实际输出延迟远不止，字幕会整体偏晚）。要真正做到 YouTube 那样的对齐得换强制对齐方案（WhisperX 一类，wav2vec2 音素级对齐），不是换 Whisper 版本。
- **从文件识别要有 `ffmpeg.exe` 在 PATH 上**（`check_word_timestamps.py`、`check_word_alignment.py`）：20231117 经 `ffmpeg-python`（`openai-whisper` 的依赖，装它时自带）调 ffmpeg，20250625 改成直接 `subprocess` 调，两者都要那个二进制。conda 里的那份在 `envs\realtimetrans\Library\bin`，只有激活环境（`start.bat` / `activate.bat`）才在 PATH 里；直接用 `envs\...\python.exe` 跑脚本要自己把这个目录加进 PATH。实时识别传的是 NumPy 数组，不走这条路。
- **Whisper 模型**：默认缓存于 `~/.cache/whisper`，首次使用自动下载。`load_model` 对 large 模型有 GPU 显存不足降级 medium/CPU 的逻辑。
- **翻译依赖网络**（Google 翻译免费接口），无网络或限流时翻译会失败——`translate` 失败时回退返回原文/已处理文本，而非抛异常。**默认后端已经换成不依赖网络的本地 EuroLLM**（见"本地翻译"小节）；`translation_backend="google"` 才走这条公网路，界面上"翻译设置 → 翻译引擎"可以随时切。
- **本地翻译要有一个在跑的本机推理服务**（默认 Ollama 的 `http://127.0.0.1:11434`）。服务没起来、模型没拉下来、超时，都只记 `last_error` 并**抛给第 5 步的 except 去回落**（返回已处理文本），界面不崩但字幕会是原文；界面上"翻译设置 → 本地状态 / 测试连接"能直接看出是哪种情况。本机实测 EuroLLM-1.7B-Q8 在 GTX 1070 Ti 上是 100% GPU、约 3497 MiB 显存。
- **换模型报"测试失败"先怀疑加载，不要先改提示词**（`alibayram/erurollm-9b-instruct`、`SparkLLM/Spark-X2.5-1.7B` 都实测过）：9B 是纯冷加载比单句超时长（10.8 秒 vs 3000ms），Spark 是思考型模型把 token 全花在 `message.thinking` 上。两者的修法都在代码里（长超时 + `think:false`），提示词一个字没动。**这两条只对"能翻译的模型"成立**：Spark-X2.5 修完照样吐提示词残渣，不适合当翻译后端。
- **动过 Ollama 的加载期参数（`local_llm_num_ctx` 等）或 `local_llm_keep_alive` 之后，先跑一次 `preload()`（界面"测试连接"）**，否则下一次真翻译会撞上"换参数重载"。同一张显卡上驻留多个模型时，Ollama 会挑着卸（实测 8GB 卡上 qwen2.5 与 EuroLLM 同驻没问题，但加载大模型会挤掉小模型）。
- **调试日志**：`audio/audio_manager.py` 内 `DEBUG_MODE = True` 会向控制台输出大量日志（日志同时写入 `whisper_model.log`）；`gui/main_window.py` 的 `DEBUG_MODE = False`。
- 术语库位于 `translation/resources/ham_radio_terms.json`，可通过编辑 JSON 扩展，`TermManager` 负责加载/校验/保存。
