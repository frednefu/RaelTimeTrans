import os
import time
import threading
import queue
import numpy as np
import whisper
import sounddevice as sd
import pyaudio
from pydub import AudioSegment
from collections import deque, namedtuple
import logging
from translation.subtitle_file_manager import SubtitleFileManager
import torch

# 调试开关，控制是否输出调试信息到控制台
DEBUG_MODE = False

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='whisper_model.log',
    filemode='a'
)
logger = logging.getLogger('whisper_model')

# 用于存储识别结果和时间信息的数据结构
RecognitionResult = namedtuple('RecognitionResult', ['text', 'language', 'delay_ms'])

class AudioManager:
    def __init__(self):
        self.is_running = False
        self.input_device = None
        self.output_device = None
        self.audio_queue = queue.Queue()
        self.text_queue = deque(maxlen=5)  # 保存最近5条识别的文本
        self.result_queue = deque(maxlen=5)  # 保存最近5条识别结果（含延迟信息）
        self.recording_thread = None
        self.recognition_thread = None
        self.stream = None
        self.pyaudio_instance = None
        self.detected_language = None  # 存储检测到的语言
        self.model = None
        self.current_model_name = None
        
        # 时间统计
        self.recognition_delay = 0  # 识别延迟（毫秒）
        
        # 音频参数
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 1024
        self.record_seconds = 3  # 每次处理3秒的音频
        
        # 字幕文件管理器
        self.subtitle_manager = SubtitleFileManager()
        
        # 从配置文件读取模型设置并加载模型
        from config import config
        model_name = config.get("whisper_model", "base")
        self.load_model(model_name)
        
    def load_model(self, model_name):
        """
        加载指定的Whisper模型
        
        参数:
            model_name (str): 模型名称 (tiny, base, small, medium, large)
            
        返回:
            bool: 是否成功加载模型
        """
        if self.current_model_name == model_name and self.model is not None:
            logger.info(f"模型 {model_name} 已经加载，不需要重新加载")
            return True
            
        try:
            logger.info(f"开始加载模型: {model_name}")
            # 检查模型文件是否存在
            model_dir = os.path.expanduser("~/.cache/whisper")
            model_exists = False
            
            if os.path.exists(model_dir):
                for fname in os.listdir(model_dir):
                    if model_name in fname:
                        model_exists = True
                        break
            
            if not model_exists:
                logger.warning(f"模型文件 {model_name} 不存在，将下载模型(这可能需要一些时间)")
            
            # 从配置获取设备设置
            from config import config
            use_gpu = config.get("use_gpu", True)
            device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
            
            if DEBUG_MODE:
                print(f"加载模型 {model_name} 使用设备: {device}")
                
            # 加载模型，指定设备
            self.model = whisper.load_model(model_name, device=device)
            self.current_model_name = model_name
            logger.info(f"成功加载模型: {model_name}, 设备: {device}")
            return True
        except Exception as e:
            error_msg = f"加载模型 {model_name} 失败: {str(e)}"
            logger.error(error_msg)
            if DEBUG_MODE:
                print(error_msg)
                
            # 如果当前没有模型，则尝试加载base模型作为后备
            if self.model is None:
                try:
                    logger.info("尝试加载备用模型: base")
                    self.model = whisper.load_model("base")
                    self.current_model_name = "base"
                    logger.info("成功加载备用模型: base")
                except Exception as e2:
                    logger.critical(f"加载备用模型也失败: {str(e2)}")
            return False
    
    def get_input_devices(self):
        """获取系统上可用的音频输入设备列表"""
        p = pyaudio.PyAudio()
        devices = []
        
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                devices.append(f"{device_info['name']} (Index: {i})")
        
        p.terminate()
        return devices
    
    def get_output_devices(self):
        """获取系统上可用的音频输出设备列表"""
        p = pyaudio.PyAudio()
        devices = []
        
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            if device_info['maxOutputChannels'] > 0:
                devices.append(f"{device_info['name']} (Index: {i})")
        
        p.terminate()
        return devices
    
    def start_recording(self, input_device, output_device=None):
        """开始录音并识别语音"""
        if self.is_running:
            return
        
        self.is_running = True
        self.input_device = input_device
        self.output_device = output_device
        
        # 重置时间统计
        self.recognition_delay = 0
        
        # 提取设备索引
        input_index = int(input_device.split("Index: ")[-1].rstrip(")"))
        output_index = int(output_device.split("Index: ")[-1].rstrip(")")) if output_device else None
        
        # 启动字幕记录
        self.subtitle_manager.start_recording()
        
        # 启动录音线程
        self.recording_thread = threading.Thread(target=self._record_audio, args=(input_index, output_index))
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
        # 启动识别线程
        self.recognition_thread = threading.Thread(target=self._recognize_audio)
        self.recognition_thread.daemon = True
        self.recognition_thread.start()
    
    def stop_recording(self):
        """停止录音和识别"""
        self.is_running = False
        
        # 停止字幕记录
        self.subtitle_manager.stop_recording()
        
        if self.stream and self.stream.is_active():
            self.stream.stop_stream()
            self.stream.close()
        
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()
            self.pyaudio_instance = None
        
        # 等待线程结束
        if self.recording_thread:
            self.recording_thread.join(timeout=1)
        
        if self.recognition_thread:
            self.recognition_thread.join(timeout=1)
    
    def _record_audio(self, input_index, output_index=None):
        """录制音频并放入队列"""
        self.pyaudio_instance = pyaudio.PyAudio()
        
        # 准备音频缓冲区
        frames = []
        buffer_seconds = 0
        
        # 创建音频流
        def callback(in_data, frame_count, time_info, status):
            frames.append(in_data)
            return (in_data, pyaudio.paContinue)
        
        self.stream = self.pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            output=output_index is not None,
            input_device_index=input_index,
            output_device_index=output_index,
            frames_per_buffer=self.chunk_size,
            stream_callback=callback if output_index else None
        )
        
        if not output_index:
            self.stream.start_stream()
        
        # 循环录制直到停止
        while self.is_running:
            if not output_index:
                data = self.stream.read(self.chunk_size)
                frames.append(data)
            
            # 计算已录制的时间
            buffer_seconds = len(frames) * self.chunk_size / self.sample_rate
            
            # 如果已经录制足够长度，则处理并发送到识别队列
            if buffer_seconds >= self.record_seconds:
                # 将帧组合成一个音频段
                audio_data = b''.join(frames)
                
                # 记录音频段的开始时间，用于计算延迟
                start_time = time.time()
                
                # 发送到识别队列（包含时间戳）
                self.audio_queue.put((audio_data, start_time))
                
                # 清空缓冲区，保留最后0.5秒的数据（可能有未完成的句子）
                overlap_frames = int(0.5 * self.sample_rate / self.chunk_size)
                frames = frames[-overlap_frames:] if overlap_frames < len(frames) else []
            
            # 短暂休眠以减少CPU使用
            time.sleep(0.01)
    
    def _recognize_audio(self):
        """使用Whisper模型识别音频"""
        while self.is_running or not self.audio_queue.empty():
            try:
                # 尝试从队列获取音频数据和开始时间（等待最多0.5秒）
                audio_data, start_time = self.audio_queue.get(timeout=0.5)
                
                # 将二进制音频数据转换为NumPy数组
                audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
                
                # 确保模型已加载
                if self.model is None:
                    logger.error("无法进行语音识别：模型未加载")
                    self.audio_queue.task_done()
                    continue
                
                # 使用Whisper模型进行语音识别
                result = self.model.transcribe(audio_np, fp16=False)
                
                # 获取识别的文本
                text = result["text"].strip()
                
                # 获取检测到的语言
                language_code = result.get("language", None)
                if language_code:
                    self.detected_language = language_code
                    logger.info(f"检测到语言: {self.detected_language}")
                
                if text:
                    # 计算识别延迟（从录音到识别完成的时间）
                    end_time = time.time()
                    delay_ms = int((end_time - start_time) * 1000)
                    
                    # 保存识别结果及延迟信息
                    self.recognition_delay = delay_ms
                    logger.info(f"语音识别延迟: {delay_ms}ms")
                    
                    # 将识别的文本添加到队列
                    self.text_queue.append(text)
                    
                    # 将完整识别结果添加到结果队列
                    result = RecognitionResult(text=text, language=language_code, delay_ms=delay_ms)
                    self.result_queue.append(result)
                    
                    # 添加到字幕管理器
                    self.subtitle_manager.add_subtitle(text)
                    
                    logger.debug(f"识别文本: {text[:50]}...")
                
                # 标记任务完成
                self.audio_queue.task_done()
                
            except queue.Empty:
                # 队列为空，等待更多音频数据
                pass
            except Exception as e:
                error_msg = f"识别音频错误: {e}"
                logger.error(error_msg)
                print(error_msg)
    
    def get_latest_text(self):
        """获取最新识别的文本"""
        if not self.text_queue:
            return None
        
        # 返回最新一条文本
        return self.text_queue[-1]
        
    def get_detected_language(self):
        """获取检测到的语言代码"""
        return self.detected_language
        
    def get_recognition_delay(self):
        """获取语音识别的延迟（毫秒）"""
        return self.recognition_delay

    def add_translated_text(self, original_text, translated_text):
        """
        添加翻译后的文本到字幕管理器
        
        参数:
            original_text (str): 原始文本
            translated_text (str): 翻译后的文本
        """
        if self.is_running and translated_text and original_text:
            # 检查原文是否匹配当前最新文本
            latest_text = self.get_latest_text()
            if latest_text and original_text == latest_text:
                self.subtitle_manager.add_subtitle(original_text, translated_text)
            else:
                # 如果不是最新文本，尝试查找匹配的原文进行更新
                for i in range(len(self.text_queue)):
                    if self.text_queue[i] == original_text:
                        self.subtitle_manager.add_subtitle(original_text, translated_text)
                        break
            
    def is_subtitle_recording(self):
        """检查是否正在记录字幕"""
        return self.subtitle_manager.is_recording() 