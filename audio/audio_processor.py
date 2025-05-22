import torch
import whisper
import numpy as np
from config import config
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor, Future

class WhisperThreadPool:
    """Whisper模型线程池，用于在后台线程中处理音频识别任务"""
    
    def __init__(self, max_workers=2):
        """初始化线程池"""
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
            task_timeout = 10  # 减少超时时间到10秒，更快地取消卡住的任务
            
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
            
            # 检查任务是否运行时间过长
            elif hasattr(self, 'task_start_times') and task_id in self.task_start_times:
                task_run_time = current_time - self.task_start_times[task_id]
                if task_run_time > task_timeout:
                    print(f"警告: 任务 {task_id} 运行时间过长 ({task_run_time:.1f}秒)，可能已卡住，尝试取消")
                    try:
                        # 尝试取消任务
                        future.cancel()
                        print(f"已取消任务 {task_id}")
                        
                        # 创建错误结果
                        error_result = {
                            "error": "任务运行超时",
                            "task_id": task_id
                        }
                        
                        # 调用回调通知
                        callback = self.callbacks.get(task_id) or self.result_callback
                        if callback:
                            try:
                                print(f"调用回调函数通知任务 {task_id} 超时")
                                callback(error_result)
                            except Exception as e:
                                print(f"调用超时回调出错: {str(e)}")
                        
                        # 将任务标记为已完成
                        completed_tasks.append(task_id)
                        
                        # 移除任务开始时间记录
                        self.task_start_times.pop(task_id, None)
                    except Exception as e:
                        print(f"取消任务 {task_id} 时出错: {str(e)}")
        
        # 移除已完成的任务
        for task_id in completed_tasks:
            self.futures.pop(task_id, None)
            # 同时移除回调映射
            self.callbacks.pop(task_id, None)
        
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
                language=source_language if source_language != "auto" else None,
                task="transcribe"
            )
            
            # 计算处理时间
            proc_time = int((time.time() - start_time) * 1000)
            
            # 获取识别结果
            text = result.get("text", "").strip()
            detected_lang = result.get("language", "unknown")
            
            print(f"任务 {task_id} 完成: 耗时={proc_time}ms, 语言={detected_lang}, 文本长度={len(text)}")
            if text:
                print(f"识别文本: '{text[:50]}...'")
            else:
                print(f"警告: 识别结果为空文本")
                
                # 如果是空文本但有有效的音频，可能需要返回一个占位符文本
                # 这样UI可以显示有声音被检测到了
                if np.max(np.abs(audio_data)) > 0.05:  # 降低阈值，更容易生成占位符
                    print(f"音频信号强度足够，但未识别出文本，使用占位符")
                    text = "[声音]"  # 使用一个占位符
            
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
                    language=source_language if source_language != "auto" else None,
                    task="transcribe"
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
            
            # 清理识别文本
            if transcribed_text:
                # 去除常见的无意义词语
                common_noise_words = [
                    "thank you", "thanks", "thank you for watching", "thanks for watching",
                    "谢谢观看", "谢谢收看", "感谢观看", "感谢收看",
                    "please subscribe", "subscribe", "like", "comment",
                    "请订阅", "请点赞", "请评论"
                ]
                
                # 转换为小写进行比较
                text_lower = transcribed_text.lower()
                
                # 检查并移除无意义词语
                for noise in common_noise_words:
                    if noise in text_lower:
                        transcribed_text = transcribed_text.replace(noise, "").strip()
                
                # 移除多余的空格
                transcribed_text = " ".join(transcribed_text.split())
                
                # 如果清理后文本为空，返回空字符串
                if not transcribed_text.strip():
                    transcribed_text = ""
                    
                # 如果文本被清理了，记录一下
                if transcribed_text != result.get("text", ""):
                    print(f"文本已清理，清理后: '{transcribed_text}'")
            
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