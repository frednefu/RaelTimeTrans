import json
import os
import shutil
import threading
import traceback

class Config:
    # 写文件用的锁：识别线程、翻译线程里都会调 config.set，
    # 两个线程同时 open(..., 'w') 会把文件截断成半截。
    _write_lock = threading.Lock()

    def __init__(self):
        self.config_file = "settings.json"
        self.default_settings = {
            "whisper_model": "base",  # 默认使用base模型
            "font_size": 24,          # 兼容旧版本
            "original_font_size": 24, # 原文字体大小
            "translation_font_size": 24, # 译文字体大小
            "font_color": "white",     # 译文颜色
            "original_font_color": "#FFFF99",  # 原文颜色，默认浅黄色
            "original_font_family": "Arial",  # 原文字体类型
            "translation_font_family": "黑体",  # 译文字体类型，默认黑体
            "position": "bottom",
            "use_gpu": True,  # 默认使用GPU
            "device": "cuda",  # 默认使用CUDA
            "source_language": "auto",  # 源语言，默认自动检测
            "target_language": "zh",  # 目标语言，默认中文
            # 翻译后端：local = 本机大模型（translation/local_llm_translator.py 调 Ollama /
            # llama-server），google = googletrans 的公网免费接口（实测单句 2.1~2.7 秒、会被限流、
            # 断网即废）。默认走本地。
            "translation_backend": "local",
            "local_llm_url": "http://127.0.0.1:11434",  # 本地推理服务的地址
            # 接口类型：ollama = Ollama 原生接口（能设 keep_alive、返回耗时明细）；
            # openai = OpenAI 兼容接口（llama.cpp 的 llama-server 用这个）
            "local_llm_api": "ollama",
            "local_llm_model": "cas/eurollm-1.7b-instruct-q8:latest",
            "local_llm_timeout_ms": 3000,   # 单句翻译超时，超了就按失败回落
            # 模型在显存/内存里保留多久。闲置被卸掉后下一句要重新加载（冷加载实测 6.5 秒，
            # 这也是第一次翻译特别慢的原因），所以默认留得久一点。
            "local_llm_keep_alive": "30m",
            "local_llm_num_predict": 256,   # 单句译文最多生成多少 token
            "local_llm_num_ctx": 2048,      # 上下文窗口大小
            "local_llm_temperature": 0.0,   # 翻译要的是稳定，默认贪心解码
            "local_llm_fallback_to_google": False,  # 本地失败时是否自动改走谷歌

            # ── 显存回收（见 model_residency.py）──────────────────────────
            # 反复"开始/停止"之后显存被占满，根因是模型没人放掉。这套开关管的是
            # "闲下来之后要不要主动还"：停止翻译时模型**故意留着**（下一轮直接复用，
            # 省掉 2.5 秒加载 + 1.4 GB 重载），真正放掉交给下面这几个。
            "model_idle_unload_enabled": True,     # 关掉 = 只手动点「释放显存」才放
            # 闲置多久就把模型放掉（秒，0 = 不按闲置放）。识别模型和本地大模型共用一个值：
            # 两者对用户的语义都是"停下来之后别占着显卡"，多一个旋钮只会让人不知道该调哪个。
            # 注意这与 local_llm_keep_alive 是两回事：那个管 Ollama 自己那份策略，
            # 这个管的是"应用停下来之后别占着显卡"。
            "model_idle_unload_sec": 300,
            # 换本地模型时先把它之外的驻留模型清掉：8GB 卡上多个模型同驻会让 Ollama
            # 为了腾地方把正在用的那个挤掉重载（日志 aborting load），表现为"某些句子
            # 突然回落成原文"。
            "unload_previous_llm_on_switch": True,

            "window_width": 800,  # 字幕窗口宽度
            "window_height": 200,   # 字幕窗口高度
            # 窗口高度是否跟着内容自动走：True 时高度 = 上/中/下三处间隙 + 各行，
            # 字号/行数一变窗口跟着收放。用户在设置里改过高度、或拖过窗口右下角，
            # 这里会变成 False，之后一律按他定的高度来（多出来的空间三处平分）。
            "window_height_auto": True,
            "subtitle_mode": "translated",  # 字幕显示模式：original=只显示原文，translated=只显示译文，both=同时显示
            "input_device": "",  # 输入设备
            "output_device": "",  # 输出设备
            "monitor_enabled": False,  # 是否监听系统声音
            # 原文字幕逐词显示：边说边识别，字幕跟着听到的语音一个词一个词冒出来。
            # 关闭则退回"整句识别完再一次性显示"。
            "word_by_word_enabled": True,
            # 译文字幕逐词显示：原文还在一段段往外确认的时候，先把半截句子送去翻译，
            # 译文跟着原文一起长；关闭则只在整句定稿时翻一次（更稳、请求更少）。
            # 流式识别后端用引擎的"已确认前缀"；整句后端用逐词通路已经念出来的半句
            # （所以整句后端下还要勾着「原文逐词显示」才有东西可翻）。
            # 旧键 `simul_simultaneous_translate`（只在流式后端下有效的"边说边翻译"）
            # 由 `_migrate_settings` 迁到这里，见那里。
            "translation_word_by_word": True,
            # 说话过程中每隔多少毫秒提交一次预览识别（逐词显示靠它）。
            # 只在整句识别后端下用；流式识别后端自己就是边说边出，不需要它。
            "partial_interval_ms": 1000,

            # ── 流式识别（SimulStreaming，见 audio/simul_asr.py）──────────────
            # whisper_batch = 今天的整句识别（安全默认）；simul = 边说边出已确认前缀。
            # 改这一项要重新"开始翻译"才生效。
            "asr_backend": "whisper_batch",
            # 流式用的模型。复用 ~/.cache/whisper 下同名 .pt（没有才下载）。
            # small 实测实时倍率 0.15~0.22（GTX 1070 Ti），medium 要实测显存。
            "simul_model": "small",
            # 攒够这么多毫秒的音频才提交一次解码（本机单次 150~270ms，间隔太小会
            # 让 GPU 一直忙、间隔太大译文出得慢）
            "simul_commit_interval_ms": 800,
            # 注意力阈值（帧）：离音频末尾这么近的帧不解码，末尾未确认的词一律截断。
            # 越大越稳但字延迟越大（实测最长字延迟 0.63s@12 vs 0.95s@25），
            # 上游命令行默认 25，这里用 12。
            "simul_frame_threshold": 12,
            # 引擎最少要攒这么多毫秒的音频才肯解码（短于此的句子出不了词）
            "simul_min_chunk_ms": 600,
            # 上游的 never_fire：调试用，正常保持 False
            "simul_never_fire": False,
            # 给模型的历史上下文上限（token）；0 = 不限制
            "simul_max_context_tokens": 0,
            # 一句话最长多少秒就强制收尾（全程不停口时靠它把长句切成句）。
            # 注意：每次提交都要把当前这段音频重新过一遍编码器，句子越长单次提交
            # 越慢（真实语音实测：5 秒 245ms → 28 秒最慢 330ms，定稿 222ms）。
            # **别用"同一批词重复摆"的合成音频去量**：重复内容会把
            # 解码带进死循环，定稿一次 75 秒，数字全不可信（见 check_simul_stream.py）。
            # 2026-10 从 25 收到 12：引擎**每句话只检测一次语言**，中英交替时后半段
            # 解不出来就卡着不动，上限越大卡得越久（另外还有停滞看门狗兜底，见
            # audio_manager._STREAM_STALL_COMMITS）。12 秒的单次提交实测仍在 300ms 内。
            "simul_max_utterance_sec": 12,
            # 前缀翻译的节流间隔（毫秒）：太密只会让翻译线程空转。
            # "前缀"= 还没定稿的半截原文（流式的已确认前缀 / 整句后端的半截识别），
            # 见 `translation_word_by_word`。
            "simul_prefix_interval_ms": 800,
            "main_window_width": 800,  # 主窗口宽度
            "main_window_height": 600,   # 主窗口高度
            "show_audio_stats": True,  # 是否显示音频数据统计信息 - 修改为默认开启
        }
        self.settings = self.load_settings()
        
        # 确保所有默认设置项都存在于加载的设置中
        self.ensure_all_settings_exist()

    def load_settings(self):
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            return self.default_settings.copy()
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # 以前这里默默吞掉异常返回默认值：文件坏了看不出来，
            # 界面上只表现为"设置全变回默认"（模型从 tiny 变回 base 之类）。
            # 现在留一份 .broken 备份并明确报出来，免得用户以为自己改的设置丢了。
            print(f"读取配置文件失败，改用默认设置: {e}")
            traceback.print_exc()
            try:
                shutil.copyfile(self.config_file, self.config_file + ".broken")
                print(f"原文件已备份为 {self.config_file}.broken")
            except OSError as backup_error:
                print(f"备份原文件失败: {backup_error}")
            return self.default_settings.copy()

    def save_settings(self):
        """保存配置到文件（原子写：先写临时文件，成功后再替换）

        直接 open(..., 'w') 会先把 settings.json 截成 0 字节再慢慢写，
        中途出错或进程被杀就只剩一个空文件（本机实测发生过一次，
        代价是所有设置悄悄回落到默认值）。改成写 .tmp 再 os.replace：
        只有整份 JSON 写完才会替换正式文件，任何一步失败都保留上一份完整配置。
        """
        tmp_file = self.config_file + ".tmp"
        try:
            with self._write_lock:
                with open(tmp_file, 'w', encoding='utf-8') as f:
                    json.dump(self.settings, f, ensure_ascii=False, indent=4)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_file, self.config_file)
        except Exception as e:
            print(f"保存配置文件时出错: {e}")
            traceback.print_exc()
            try:
                os.remove(tmp_file)
            except OSError:
                pass

    def ensure_all_settings_exist(self):
        """确保所有默认设置项都存在于当前设置中"""
        needs_save = self._migrate_settings()
        for key, value in self.default_settings.items():
            if key not in self.settings:
                self.settings[key] = value
                needs_save = True

        # 如果有缺失项，立即保存更新后的设置
        if needs_save:
            self.save_settings()

    def _migrate_settings(self):
        """旧键迁移：`simul_simultaneous_translate` → `translation_word_by_word`

        原来那个"边说边翻译"只在流式识别后端下有效（整句后端根本取不到半截原文）；
        现在译文逐词/逐句是个通用选项，两种后端都吃，键也跟着改名。

        必须赶在 `ensure_all_settings_exist` 补默认值**之前**读旧键：补完默认值之后
        新键就"已经存在"了，用户原来关掉的那个开关会被默认的 True 顶掉。

        返回 True 表示动过设置（调用方要落盘）。
        """
        if ("translation_word_by_word" not in self.settings
                and "simul_simultaneous_translate" in self.settings):
            self.settings["translation_word_by_word"] = bool(
                self.settings["simul_simultaneous_translate"])
            return True
        return False

    def get(self, key, default=None):
        """获取配置项，如果不存在则返回默认值"""
        return self.settings.get(key, default)

    def set(self, key, value):
        """设置配置项"""
        self.settings[key] = value
        self.save_settings()  # 立即保存到文件
    
    def sync_to_file(self):
        """强制将所有设置同步到文件"""
        self.save_settings()

# 创建全局配置实例
config = Config() 