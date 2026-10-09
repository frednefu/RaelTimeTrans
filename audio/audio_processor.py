import torch
import whisper
import numpy as np
from config import config
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor, Future

# 业余无线电场景的 initial_prompt。
#
# Whisper 会把 initial_prompt 当作解码的"前文"，等于给模型一个领域词表：
# 实测同一段 13 秒语音，small 模型的词错率从 14.3% 降到 7.1%，并且能把
# "Five Niner" 正确识别成 "five nine"（术语库的信号报告转换依赖这个，识别成
# "59 or"/"五人" 就没法还原了）。
#
# 改这段 prompt 前请先看下面三条踩过的坑：
#
# 1. Whisper 只取 prompt 编码后**最后** 224 个 token，写在前面会被截掉。
#    所以最重要的 NATO 字母解释法必须放在**最后**。
# 2. 不要往里拼术语库的原始词条。术语库里有一长串生造的 Q 码
#    （QUA/QUD/QUF/…/QUR），拼进去之后模型会在**正常语音里**吐幻觉：实测把
#    "CQ CQ CQ … standing by" 识别成了 "CQ, QU, QU, QU, … QUN, standing by"，
#    凭空多出 "QU"、"QUN"。词表不是越长越好。
# 3. 术语之间用空格分隔、不要用逗号：prompt 里的逗号会被输出模仿，整句被
#    逗号切碎（"CQ, CQ, CQ, this is, Alpha…"）。
#
# 呼号是靠字母解释法读出来的（"Alpha Bravo Five Niner" = AB59），把字母表放在
# 最后对呼号识别的帮助最大。
HAM_RADIO_PROMPT = (
    "Amateur radio contact between two stations. They exchange callsigns and "
    "signal reports such as five nine, then sign off with 73. Words that often "
    "appear are CQ QRZ QTH QSL QRM QRN QRP QSY roger copy over out standing by "
    "calling this is signal report readability strength tone antenna "
    "transceiver frequency dipole repeater callsign mobile portable. "
    "NATO phonetic alphabet: Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel "
    "India Juliett Kilo Lima Mike November Oscar Papa Quebec Romeo Sierra Tango "
    "Uniform Victor Whiskey X-ray Yankee Zulu"
)

_prompt_cache = None

# Whisper 对静音和噪声的典型幻觉输出。这些词一旦混进字幕，看起来就是"识别不
# 准确"，实际上模型在那段音频里根本没听到人说话。
_HALLUCINATION_PHRASES = [
    "thank you", "thanks", "thank you for watching", "thanks for watching",
    "please subscribe", "subscribe", "like and subscribe",
    "谢谢观看", "谢谢收看", "感谢观看", "感谢收看",
    "请订阅", "请点赞", "请评论", "字幕由", "字幕志愿者",
]

# 整条结果正好等于这些词时判定为幻觉（识别到纯静音时 Whisper 常吐这几个词）。
# 用整条相等而不是包含来判断，避免误杀 "roger"、"over" 这类真实通联用语。
_WHOLE_RESULT_HALLUCINATIONS = {
    "you", "thank you", "thanks", "thank you.", "bye", "bye.", "okay", "okay.",
    "please", "please.", "yeah", "yeah.", "so", "so.", "oh", "oh.",
    "thank you very much", "thank you very much.", "you're welcome",
    "♪", ".", ",", "...", "!", "?",
}


def _is_repetition_loop(text):
    """判断识别结果是不是重复循环的乱码

    噪声段会让 Whisper 陷入复读，输出 "ʰʰʰʰʰʰ…"、"විවිවිවි…" 这种整条几乎只有
    一两个字符的内容。正常语句不可能长这样（字符种类必然很丰富）。
    """
    if len(text) < 8:
        return False
    if len(set(text)) <= 4:
        return True
    # 单个字符连续重复太多次
    run = 1
    for prev, cur in zip(text, text[1:]):
        run = run + 1 if cur == prev else 1
        if run >= 8:
            return True
    return False


def transcribe_options(source_language, device="cpu"):
    """统一的 Whisper 解码参数

    同步/异步两条路径共用，避免两处参数不一致。

    关于几个刻意没动的参数：
    - beam_size 保持默认（贪心）：实测 beam_size=5 词错率没有变化，耗时却翻了
      一倍（0.68s → 1.38s），实时场景不值得。
    - language=None 时由 Whisper 自己检测语种；实测 2.5 秒英语片段和 6.4 秒中文
      片段都能判对，所以"自动检测"可以放心用。
    """
    return dict(
        language=source_language if source_language not in ("auto", None, "") else None,
        task="transcribe",
        initial_prompt=build_initial_prompt(),
        # 每段音频是独立的，不应该拿上一段的结果当上下文：分包处本来就可能丢掉
        # 半句话，condition_on_previous_text 在这种情况下会反复"复读"上一段
        # （实测出现 "calling calling CQ" 这类重复）。
        condition_on_previous_text=False,
        # 解码失败（压缩比异常/平均对数概率过低）时按这个温度序列退火重试，
        # 这是抑制幻觉和乱码循环的主要手段
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        compression_ratio_threshold=2.4,
        logprob_threshold=-1.0,
        # 判定"这段没有语音"的阈值。命中时 Whisper 直接返回空文本——这正是过去
        # 用 "[声音]" 占位符想解决的问题，但占位符会一路进到翻译管线翻出垃圾字幕，
        # 所以改用 Whisper 自己的机制。
        no_speech_threshold=0.6,
        fp16=(device == "cuda"),
        verbose=False,
    )


def clean_transcribed_text(text):
    """清掉识别结果里的幻觉短语、复读乱码和纯标点"""
    if not text:
        return ""

    cleaned = " ".join(text.split())

    # 整条就是常见的静音幻觉词
    if cleaned.lower().strip(" .,!?") in {w.strip(" .,!?") for w in
                                          _WHOLE_RESULT_HALLUCINATIONS}:
        return ""

    lowered = cleaned.lower()
    # 先长后短：否则 "thank you" 会先把 "thank you for watching" 咬掉一半，
    # 剩下 "for watching"
    for phrase in sorted(_HALLUCINATION_PHRASES, key=len, reverse=True):
        if phrase in lowered:
            # 用大小写不敏感的方式整段去掉
            idx = lowered.find(phrase)
            while idx != -1:
                cleaned = cleaned[:idx] + cleaned[idx + len(phrase):]
                lowered = cleaned.lower()
                idx = lowered.find(phrase)
            cleaned = " ".join(cleaned.split())

    if _is_repetition_loop(cleaned):
        return ""

    if not any(ch.isalnum() for ch in cleaned):
        return ""
    return cleaned.strip()


def build_initial_prompt():
    """构造 Whisper 的 initial_prompt，只构造一次"""
    global _prompt_cache
    if _prompt_cache is None:
        _prompt_cache = HAM_RADIO_PROMPT
    return _prompt_cache


class WhisperThreadPool:
    """Whisper模型线程池，用于在后台线程中处理音频识别任务"""

    def __init__(self, max_workers=1):
        """初始化线程池

        max_workers 固定为 1：模型只有一个，两个 worker 并发调用同一个 model
        会争抢显存、拖慢单次识别，而且结果回调的顺序没有保证（字幕可能乱序）。
        small 模型在这台机器上一次 5 秒片段约 0.35 秒，单 worker 完全跟得上。
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="whisper_worker")
        self.task_queue = queue.Queue()
        self.result_callback = None
        self.is_running = False
        self.worker_thread = None
        
        # 用于跟踪当前正在执行的任务
        self.current_task = None
        self.current_future = None
        
        # 添加任务计数和状态追踪
        self.task_count = 0
        self.futures = {}  # 存储任务ID到Future的映射
        self.callbacks = {}  # 存储任务ID到回调函数的映射
        self._slow_task_warned = set()  # 已告警过的慢任务，避免反复刷屏
    
    def start(self):
        """启动线程池工作线程"""
        if not self.is_running:
            self.is_running = True
            print(f"启动Whisper线程池，线程ID: {threading.get_ident()}")
            self.worker_thread = threading.Thread(target=self._process_tasks, daemon=True)
            self.worker_thread.start()
            print("Whisper线程池已启动")
            
            # 等待一小段时间确保线程启动
            time.sleep(0.1)
            
            # 检查线程是否真的启动了
            if self.worker_thread.is_alive():
                print(f"确认Whisper工作线程已成功启动，线程ID: {self.worker_thread.ident}")
            else:
                print("警告: Whisper工作线程启动失败!")
        else:
            print("Whisper线程池已经在运行中")
    
    def stop(self):
        """停止线程池工作线程"""
        self.is_running = False
        if self.worker_thread:
            try:
                # 等待工作线程终止，但最多等待2秒
                self.worker_thread.join(timeout=2)
                print("Whisper线程池已停止")
            except Exception as e:
                print(f"停止Whisper线程池时出错: {str(e)}")
        
        # 取消所有正在执行的任务
        for future in self.futures.values():
            if not future.done():
                future.cancel()
        
        # 清空任务队列
        while not self.task_queue.empty():
            try:
                self.task_queue.get_nowait()
                self.task_queue.task_done()
            except queue.Empty:
                break
        
        # 清空回调和任务映射
        self.callbacks.clear()
        self.futures.clear()
    
    def _process_tasks(self):
        """处理任务队列中的任务 - 完全非阻塞方式"""
        while self.is_running:
            try:
                # 检查已完成的任务并处理结果
                self._check_completed_futures()
                
                # 如果线程池已满，不再提交新任务
                if len(self.futures) >= self.executor._max_workers:
                    time.sleep(0.01)  # 短暂暂停，避免CPU占用过高
                    continue
                
                # 从队列获取任务，最多等待0.1秒
                try:
                    task = self.task_queue.get(timeout=0.1)
                except queue.Empty:
                    # 队列为空，继续等待
                    continue
                
                # 提取任务信息
                audio_data, processor, task_id, source_language, callback = task
                
                try:
                    # 提交任务到线程池执行，但不等待结果
                    future = self.executor.submit(
                        self._run_whisper_task, 
                        audio_data, 
                        processor, 
                        task_id,
                        source_language
                    )
                    
                    # 存储Future对象和回调函数
                    self.futures[task_id] = future
                    if callback:
                        self.callbacks[task_id] = callback
                        print(f"已为任务 {task_id} 设置回调函数")
                    
                    # 任务已提交，标记完成
                    self.task_queue.task_done()
                    
                except Exception as e:
                    print(f"Whisper任务提交出错: {str(e)}")
                    self.task_queue.task_done()
                    
            except Exception as e:
                print(f"Whisper工作线程出错: {str(e)}")
                # 短暂延迟以避免CPU占用过高
                time.sleep(0.1)
    
    def _check_completed_futures(self):
        """检查已完成的Future并处理结果"""
        # 创建已完成任务ID的列表
        completed_tasks = []
        
        # 打印当前队列和任务状态
        if len(self.futures) > 0:
            print(f"当前有 {len(self.futures)} 个任务正在处理, futures={list(self.futures.keys())}")
            
            # 检查任务是否运行时间过长
            current_time = time.time()
            task_timeout = 30  # 仅用于告警：small/medium 模型正常远快于此
            
            # 记录当前时间戳
            if not hasattr(self, 'task_start_times'):
                self.task_start_times = {}
                # 为已有任务初始化开始时间
                for task_id in self.futures.keys():
                    self.task_start_times[task_id] = current_time
        
        # 检查所有Future
        for task_id, future in list(self.futures.items()):
            # 如果任务完成，处理结果
            if future.done():
                print(f"任务 {task_id} 已完成，获取结果")
                try:
                    # 获取结果，但不阻塞
                    result = future.result(timeout=0)
                    
                    # 打印结果
                    if result:
                        if "error" in result:
                            print(f"任务 {task_id} 出错: {result['error']}")
                        else:
                            text = result.get("text", "")
                            print(f"任务 {task_id} 完成: 耗时={result['delay_ms']}ms, 语言={result['language']}, 文本长度={len(text)}")
                            if text:
                                print(f"识别文本: '{text[:50]}...'")
                            else:
                                print(f"警告: 识别结果为空文本")
                    
                    # 使用对应任务的回调函数处理结果
                    callback = self.callbacks.get(task_id) or self.result_callback
                    if callback and result:
                        print(f"调用回调函数处理任务 {task_id} 的结果")
                        callback(result)
                        print(f"回调函数处理完成")
                    else:
                        if not callback:
                            print(f"警告: 任务 {task_id} 完成，但没有设置回调函数")
                        if not result:
                            print(f"警告: 任务 {task_id} 完成，但结果为空")
                        
                except Exception as e:
                    print(f"获取Whisper任务 {task_id} 结果出错: {str(e)}")
                
                # 将已完成的任务添加到列表
                completed_tasks.append(task_id)
                
                # 移除任务开始时间记录
                if hasattr(self, 'task_start_times'):
                    self.task_start_times.pop(task_id, None)
            
            # 检查任务是否运行时间过长。
            #
            # 这里只告警、不再取消：future.cancel() 对已经开始执行的任务是无效的，
            # 原来的写法只是把结果丢掉，而任务仍在 worker 里跑（白占资源、又静默
            # 少了一段字幕）。识别结果什么时候回来都比不来强——UI 层会按"是否还是
            # 最新一条"决定要不要显示。
            elif hasattr(self, 'task_start_times') and task_id in self.task_start_times:
                task_run_time = current_time - self.task_start_times[task_id]
                if task_run_time > task_timeout:
                    if task_id not in self._slow_task_warned:
                        self._slow_task_warned.add(task_id)
                        print(f"警告: 任务 {task_id} 运行时间已超过 {task_timeout} 秒 "
                              f"({task_run_time:.1f}秒)，识别较慢，等待其自然完成")
        
        # 移除已完成的任务
        for task_id in completed_tasks:
            self.futures.pop(task_id, None)
            # 同时移除回调映射
            self.callbacks.pop(task_id, None)
            self._slow_task_warned.discard(task_id)
        
        # 报告已完成的任务数
        if completed_tasks:
            print(f"已完成并移除 {len(completed_tasks)} 个任务: {completed_tasks}")
    
    def _run_whisper_task(self, audio_data, processor, task_id, source_language):
        """执行Whisper音频识别任务"""
        try:
            # 获取开始时间
            start_time = time.time()
            
            # 打印任务开始信息
            print(f"开始执行Whisper任务 {task_id}")
            
            # 获取模型
            try:
                model = processor.get_model()
                print(f"任务 {task_id} 成功获取模型: {processor.current_model_name}")
            except Exception as model_error:
                print(f"任务 {task_id} 获取模型失败: {str(model_error)}")
                return {
                    "error": f"获取模型失败: {str(model_error)}",
                    "task_id": task_id
                }
            
            # 检查音频数据是否有效
            if audio_data is None or len(audio_data) == 0:
                print(f"任务 {task_id} 音频数据无效")
                return {
                    "error": "音频数据无效",
                    "task_id": task_id
                }
            
            # 检查音频信号强度
            if isinstance(audio_data, np.ndarray) and audio_data.size > 0:
                max_val = np.max(np.abs(audio_data))
                rms = np.sqrt(np.mean(np.square(audio_data)))
                print(f"任务 {task_id} 音频信号: 最大值={max_val:.4f}, RMS={rms:.4f}")
                
                # 降低信号阈值，允许处理更多声音
                if max_val < 0.008 or rms < 0.004:
                    print(f"任务 {task_id} 警告: 音频信号非常弱")
            
            # 执行识别
            print(f"任务 {task_id} 开始执行Whisper识别 (语言: {source_language})")
            result = model.transcribe(
                audio_data,
                **transcribe_options(source_language,
                                     getattr(processor, "device", "cpu"))
            )

            # 计算处理时间
            proc_time = int((time.time() - start_time) * 1000)

            # 获取识别结果
            raw_text = result.get("text", "").strip()
            text = clean_transcribed_text(raw_text)
            detected_lang = result.get("language", "unknown")
            if raw_text and not text:
                print(f"任务 {task_id} 识别结果被判定为幻觉噪声，已丢弃: {raw_text!r}")

            print(f"任务 {task_id} 完成: 耗时={proc_time}ms, 语言={detected_lang}, 文本长度={len(text)}")
            if text:
                print(f"识别文本: '{text[:50]}...'")
            else:
                print(f"未识别出文本（可能是静音或噪声）")

            # 返回结果
            return {
                "text": text,
                "language": detected_lang,
                "delay_ms": proc_time,
                "task_id": task_id
            }
            
        except Exception as e:
            print(f"Whisper任务 {task_id} 执行失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "error": str(e),
                "task_id": task_id
            }
    
    def process_audio(self, audio_data, processor, source_language="auto", callback=None):
        """将音频处理任务提交到线程池
        
        参数:
            audio_data (np.ndarray): 音频数据
            processor (AudioProcessor): 音频处理器实例
            source_language (str): 源语言
            callback (function): 针对此任务的回调函数
            
        返回:
            str: 任务ID
        """
        # 生成任务ID
        self.task_count += 1
        task_id = f"task_{int(time.time() * 1000)}_{self.task_count}"
        
        # 检查线程池是否运行
        if not self.is_running:
            self.start()
        
        # 记录任务开始时间
        if not hasattr(self, 'task_start_times'):
            self.task_start_times = {}
        self.task_start_times[task_id] = time.time()
        
        # 打印音频数据信息
        if isinstance(audio_data, np.ndarray):
            audio_max = np.max(np.abs(audio_data)) if audio_data.size > 0 else 0
            audio_rms = np.sqrt(np.mean(np.square(audio_data))) if audio_data.size > 0 else 0
            print(f"提交音频任务 {task_id}: 形状={audio_data.shape}, 最大值={audio_max:.4f}, RMS={audio_rms:.4f}")
            
            # 检查是否是静音音频
            if audio_max < 0.01 or audio_rms < 0.005:
                print(f"警告: 音频任务 {task_id} 似乎是静音或信号很弱")
        
        # 提交任务到队列，包含回调函数
        self.task_queue.put((audio_data, processor, task_id, source_language, callback))
        
        print(f"已将任务 {task_id} 提交到队列，当前队列大小: {self.task_queue.qsize()}")
        return task_id
    
    def set_result_callback(self, callback):
        """设置全局结果回调函数，当任务没有特定回调时使用
        
        参数:
            callback (function): 结果回调函数，接收result参数
        """
        if callback:
            callback_name = callback.__name__ if hasattr(callback, '__name__') else 'unnamed_callback'
            print(f"设置全局结果回调函数: {callback_name}")
            self.result_callback = callback
        else:
            print("警告: 尝试设置空的回调函数")
    
    def is_busy(self):
        """检查线程池是否正在处理任务"""
        return not self.task_queue.empty() or len(self.futures) > 0
    
    def get_queue_size(self):
        """获取当前队列中的任务数量"""
        return self.task_queue.qsize() + len(self.futures)

class AudioProcessor:
    def __init__(self):
        self.model = None
        self.current_model_name = None
        # 检查CUDA是否可用
        self.device = "cuda" if config.get("use_gpu", True) and torch.cuda.is_available() else "cpu"
        print(f"使用设备: {self.device}")
        if self.device == "cuda":
            # 打印GPU信息
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            
        # 创建Whisper线程池
        self.thread_pool = WhisperThreadPool(max_workers=2)
        
        # 确保线程池立即启动
        self.thread_pool.start()
        print("AudioProcessor初始化完成，Whisper线程池已启动")
    
    def get_model(self):
        """获取当前配置的模型，如果需要则加载"""
        try:
            model_name = config.get("whisper_model", "base")
            # 检查是否需要重新加载模型
            need_reload = (self.model is None or self.current_model_name != model_name)
            
            # 检查设备选择
            desired_device = config.get("device", "cuda" if config.get("use_gpu", True) else "cpu")
            device_changed = hasattr(self, 'device') and self.device != desired_device
            
            if need_reload or device_changed:
                # 特殊处理large模型
                is_large_model = model_name == "large"
                
                # 检查GPU内存是否足够（如果使用GPU）
                if desired_device == "cuda" and torch.cuda.is_available():
                    # 对于large模型，检查GPU内存
                    if is_large_model:
                        # large模型可能需要至少5GB的GPU内存
                        free_memory = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()
                        free_memory_gb = free_memory / (1024**3)
                        print(f"可用GPU内存: {free_memory_gb:.2f} GB")
                        
                        # 如果内存小于4GB，警告并切换到CPU
                        if free_memory_gb < 4:
                            print(f"警告: GPU内存不足({free_memory_gb:.2f}GB)，large模型需要至少4GB。切换到CPU...")
                            desired_device = "cpu"
                            config.set("device", "cpu")
                            self.device = "cpu"
                    
                # 更新设备设置
                self.device = desired_device
                
                # 释放之前的模型以节省内存
                if self.model is not None:
                    del self.model
                    import gc
                    gc.collect()
                    if self.device == "cuda":
                        torch.cuda.empty_cache()
                
                print(f"加载Whisper模型: {model_name} 到 {self.device}")
                
                try:
                    # 尝试加载模型
                    self.model = whisper.load_model(model_name, device=self.device)
                    self.current_model_name = model_name
                    print(f"模型 {model_name} 加载完成")
                except Exception as load_error:
                    # 如果是large模型加载失败，尝试降级到medium
                    if is_large_model:
                        print(f"Large模型加载失败({str(load_error)})，尝试降级到medium...")
                        try:
                            self.model = whisper.load_model("medium", device=self.device)
                            self.current_model_name = "medium"
                            print(f"降级到medium模型加载完成")
                            # 更新配置
                            config.set("whisper_model", "medium")
                        except Exception as fallback_error:
                            print(f"降级到medium模型也失败: {str(fallback_error)}")
                            raise  # 重新抛出异常
                    else:
                        # 不是large模型，直接抛出错误
                        raise
        
            return self.model
        except Exception as e:
            print(f"加载Whisper模型失败: {str(e)}")
            # 重置模型状态
            self.model = None
            self.current_model_name = None
            # 重新抛出异常以便上层函数处理
            raise
    
    def process_audio(self, audio_data):
        """处理音频数据 - 同步版本，直接返回结果
        
        注意：此方法会阻塞调用线程，应考虑使用process_audio_async代替
        """
        try:
            # 获取源语言设置
            source_language = config.get("source_language", "auto")
            
            # 打印源语言设置
            print(f"当前源语言设置: {source_language}")
            
            # 每次处理都获取当前配置的模型
            model = self.get_model()
            
            # 记录输入音频的基本信息
            print(f"处理音频数据: 类型={type(audio_data)}, 是否为numpy数组={isinstance(audio_data, np.ndarray)}")
            if isinstance(audio_data, np.ndarray):
                print(f"输入音频: 形状={audio_data.shape}, 类型={audio_data.dtype}, 最大值={np.max(audio_data):.6f}, 最小值={np.min(audio_data):.6f}")
            
            # 确保音频数据是numpy数组
            if not isinstance(audio_data, np.ndarray):
                print(f"警告: 输入的音频数据不是numpy数组，而是 {type(audio_data)}")
                audio_data = np.array(audio_data, dtype=np.float32)
            
            # 确保音频数据的形状正确
            if len(audio_data.shape) > 1:
                print(f"警告: 音频数据是多维的 {audio_data.shape}，将其展平")
                audio_data = audio_data.flatten()
            
            # 根据模型大小设置最小音频长度
            min_audio_length = {
                "tiny": 8000,     # 0.5秒
                "base": 8000,     # 0.5秒
                "small": 12000,   # 0.75秒
                "medium": 16000,  # 1秒
                "large": 16000    # 1秒
            }.get(self.current_model_name, 8000)  # 默认0.5秒，减少最小长度要求
            
            # 检查音频长度，如果太短，添加静音
            if len(audio_data) < min_audio_length:
                print(f"警告: 音频数据过短 {len(audio_data)}，添加静音填充")
                padding = np.zeros(min_audio_length - len(audio_data), dtype=np.float32)
                audio_data = np.concatenate([audio_data, padding])
            
            # 确保音频数据是float32类型
            if audio_data.dtype != np.float32:
                print(f"警告: 音频数据类型不是float32，而是 {audio_data.dtype}，将其转换")
                audio_data = audio_data.astype(np.float32)
            
            # 确保音频数据在[-1, 1]范围内
            max_abs = np.max(np.abs(audio_data))
            if max_abs > 1.0:
                print(f"警告: 音频数据超出[-1,1]范围，最大绝对值是 {max_abs}，将其归一化")
                audio_data = audio_data / max_abs
            
            # 检查音频是否有信号（避免全0或接近0的数据）
            rms = np.sqrt(np.mean(np.square(audio_data)))
            if rms < 0.001:  # 非常小的RMS值表示几乎没有声音
                print(f"警告: 音频信号非常弱 (RMS = {rms:.6f})，可能无法识别")
            else:
                print(f"音频信号强度 RMS = {rms:.6f}")
            
            # 记录音频数据的统计信息，但仅在启用时显示
            if config.get("show_audio_stats", False):
                print(f"音频数据统计: 类型={audio_data.dtype}, 形状={audio_data.shape}, 最小值={np.min(audio_data)}, 最大值={np.max(audio_data)}")
            
            # 总是打印处理后的音频信息
            print(f"处理后的音频: 形状={audio_data.shape}, 类型={audio_data.dtype}, 最大值={np.max(audio_data):.6f}, 最小值={np.min(audio_data):.6f}")
            
            # 在调用Whisper模型前进行最终检查
            if not isinstance(audio_data, np.ndarray):
                print("致命错误: 在调用Whisper前，音频数据仍然不是numpy数组")
                audio_data = np.array(audio_data, dtype=np.float32)
            
            # 确保不会传递列表给Whisper
            whisper_input = audio_data
            if isinstance(whisper_input, list):
                print("致命错误: whisper_input是列表类型，将其转换为numpy数组")
                whisper_input = np.array(whisper_input, dtype=np.float32)
            
            # 使用Whisper模型进行识别，使用直接的变量而不是可能变化的引用
            try:
                print(f"开始使用Whisper模型识别音频 (模型: {self.current_model_name}, 设备: {self.device})")
                
                start_time = time.time()
                result = model.transcribe(
                    whisper_input,
                    **transcribe_options(source_language, self.device)
                )
                # 计算处理时间
                proc_time = int((time.time() - start_time) * 1000)
                
                print(f"Whisper模型识别完成")
            except Exception as model_error:
                print(f"Whisper模型错误: {str(model_error)}")
                print(f"输入数据信息: 类型={type(whisper_input)}, 是否为numpy={isinstance(whisper_input, np.ndarray)}")
                if isinstance(whisper_input, np.ndarray):
                    print(f"Numpy数组信息: 形状={whisper_input.shape}, 类型={whisper_input.dtype}")
                raise
            
            # 返回文本内容和检测到的语言代码
            detected_language = result.get("language")
            transcribed_text = result.get("text", "")
            
            print(f"Whisper识别结果: 语言={detected_language}, 文本='{transcribed_text}'")
            
            # 清理识别文本（去掉幻觉短语）
            if transcribed_text:
                cleaned_text = clean_transcribed_text(transcribed_text)
                if cleaned_text != transcribed_text:
                    print(f"文本已清理，清理后: '{cleaned_text}'")
                transcribed_text = cleaned_text

            return {
                "text": transcribed_text,
                "language": detected_language,
                "delay_ms": proc_time
            }
            
        except Exception as e:
            print(f"处理音频数据时出错: {str(e)}")
            return {"error": str(e)}
    
    def process_audio_async(self, audio_data, callback=None):
        """异步处理音频数据，不阻塞调用线程
        
        参数:
            audio_data (np.ndarray): 音频数据
            callback (function): 可选的回调函数，处理完成后调用
            
        返回:
            str: 任务ID
        """
        # 获取源语言设置
        source_language = config.get("source_language", "auto")
        
        # 预处理音频数据
        try:
            # 确保音频数据是numpy数组
            if not isinstance(audio_data, np.ndarray):
                audio_data = np.array(audio_data, dtype=np.float32)
            
            # 确保音频数据的形状正确
            if len(audio_data.shape) > 1:
                audio_data = audio_data.flatten()
            
            # 确保音频数据是float32类型
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)
            
            # 检查音频质量
            max_abs = np.max(np.abs(audio_data))
            rms = np.sqrt(np.mean(np.square(audio_data)))
            duration = len(audio_data) / 16000  # 假设采样率为16kHz
            
            print(f"音频质量检查: 时长={duration:.2f}秒, 最大值={max_abs:.4f}, RMS={rms:.4f}")
            
            # 检查音频是否有足够的音量 - 降低阈值以处理更多音频
            if max_abs < 0.003 or rms < 0.0015:
                print(f"音频信号太弱，跳过处理: max={max_abs:.4f}, rms={rms:.4f}")
                if callback:
                    callback({
                        "error": "音频信号太弱，无法识别",
                        "text": "",
                        "language": None,
                        "delay_ms": 0
                    })
                return None
            
            # 确保音频数据在[-1, 1]范围内
            max_abs = np.max(np.abs(audio_data))
            if max_abs > 1.0:
                audio_data = audio_data / max_abs
                
            # 根据模型大小设置最小音频长度
            min_audio_length = {
                "tiny": 8000,     # 0.5秒
                "base": 8000,     # 0.5秒
                "small": 12000,   # 0.75秒
                "medium": 16000,  # 1秒
                "large": 16000    # 1秒
            }.get(self.current_model_name, 8000)  # 默认0.5秒
            
            # 检查音频长度，如果太短，添加静音
            if len(audio_data) < min_audio_length:
                padding = np.zeros(min_audio_length - len(audio_data), dtype=np.float32)
                audio_data = np.concatenate([audio_data, padding])
                print(f"音频过短，已添加静音填充至 {len(audio_data)/16000:.2f} 秒")
            
        except Exception as e:
            print(f"预处理音频数据时出错: {str(e)}")
            if callback:
                callback({"error": str(e)})
            return None
        
        # 记录回调函数信息
        if callback:
            print(f"设置异步处理回调函数: {callback.__name__ if hasattr(callback, '__name__') else 'unnamed_callback'}")
        else:
            print("警告: 没有提供回调函数，结果将丢失")
        
        # 直接将回调函数传递给线程池的process_audio方法
        task_id = self.thread_pool.process_audio(
            audio_data, 
            self, 
            source_language, 
            callback  # 直接传递回调函数
        )
        
        print(f"已提交异步任务: {task_id}, 回调函数: {'已设置' if callback else '未设置'}")
        return task_id
    
    def update_model(self, model_name):
        """更新模型设置"""
        config.set("whisper_model", model_name)
    
    def update_device(self, use_gpu):
        """更新设备设置"""
        config.set("use_gpu", use_gpu)
        config.set("device", "cuda" if use_gpu else "cpu")
    
    def cleanup(self):
        """清理资源"""
        if hasattr(self, 'thread_pool'):
            self.thread_pool.stop()
        # 释放模型
        if self.model is not None:
            del self.model
            self.model = None
            import gc
            gc.collect()
            if self.device == "cuda":
                torch.cuda.empty_cache() 