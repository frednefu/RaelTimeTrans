import torch
import whisper
import numpy as np
from config import config

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
        """处理音频数据"""
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
                "tiny": 16000,    # 1秒
                "base": 16000,    # 1秒
                "small": 16000,   # 1秒
                "medium": 16000,  # 1秒
                "large": 16000    # 1秒
            }.get(self.current_model_name, 16000)
            
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
                
                result = model.transcribe(
                    whisper_input,
                    language=source_language if source_language != "auto" else None,
                    task="transcribe"
                )
                
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
                "language": detected_language
            }
            
        except Exception as e:
            print(f"识别音频错误: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # 如果是large模型并出错，可以添加详细日志
            if self.current_model_name == "large":
                print(f"Large模型错误详情 - 音频数据形状: {audio_data.shape if isinstance(audio_data, np.ndarray) else '未知'}")
            
            # 发生错误时返回空结果
            return {
                "text": "",
                "language": None
            }
            
    def update_model(self, model_name):
        """更新模型配置"""
        # 只更新配置，不立即加载模型
        config.set("whisper_model", model_name)
        # 清除当前模型引用，下次使用时会加载新模型
        self.model = None
        self.current_model_name = None
        print(f"模型配置已更新为: {model_name}，将在下次使用时加载")
            
    def update_device(self, use_gpu):
        """更新设备设置"""
        if use_gpu and not torch.cuda.is_available():
            print("警告: 请求使用GPU但CUDA不可用，将使用CPU")
            use_gpu = False
            
        new_device = "cuda" if use_gpu else "cpu"
        if new_device != self.device:
            self.device = new_device
            config.set("use_gpu", use_gpu)
            config.set("device", self.device)
            print(f"切换到设备: {self.device}")
            # 清除当前模型引用，下次使用时会在新设备上加载
            self.model = None
            self.current_model_name = None 