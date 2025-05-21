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
from audio.audio_processor import AudioProcessor
from config import config  # 添加 config 导入

# 调试开关，控制是否输出调试信息到控制台
DEBUG_MODE = True

# 配置日志记录
logger = logging.getLogger('whisper_model')
logger.setLevel(logging.INFO)

# 创建文件处理器
file_handler = logging.FileHandler('whisper_model.log', mode='a', encoding='utf-8')
file_handler.setLevel(logging.INFO)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# 添加处理器到日志记录器
logger.addHandler(file_handler)

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
        self.playback_thread = None  # 新增：专门用于音频播放的线程
        self.stream = None
        self.pyaudio_instance = None
        self.detected_language = None  # 存储检测到的语言
        
        # 音频数据队列，用于从录音线程传递到播放线程
        self.playback_queue = queue.Queue(maxsize=1000)  # 限制队列大小以防内存占用过高
        
        # 使用AudioProcessor处理音频识别
        self.audio_processor = AudioProcessor()
        
        # 记录当前模型名称，仅用于UI显示
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
        
        # 音频延迟缓冲区
        self.audio_delay_enabled = False
        self.audio_delay_ms = 0
        self.audio_buffer = deque()
        
        # 从配置文件读取模型设置
        self.current_model_name = config.get("whisper_model", "base")
        
        # 初始化 PyAudio
        self._init_pyaudio()
        
    def _init_pyaudio(self):
        """初始化 PyAudio 实例"""
        try:
            if self.pyaudio_instance is None:
                self.pyaudio_instance = pyaudio.PyAudio()
                print("PyAudio 实例初始化成功")
        except Exception as e:
            print(f"初始化 PyAudio 失败: {str(e)}")
            self.pyaudio_instance = None
            
    def _cleanup_pyaudio(self):
        """清理 PyAudio 实例"""
        try:
            # 先停止所有活动的流
            if hasattr(self, 'stream') and self.stream:
                try:
                    if self.stream.is_active():
                        self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    print(f"关闭输入流时出错: {str(e)}")
                finally:
                    self.stream = None
                    
            if hasattr(self, 'output_stream') and self.output_stream:
                try:
                    if self.output_stream.is_active():
                        self.output_stream.stop_stream()
                    self.output_stream.close()
                except Exception as e:
                    print(f"关闭输出流时出错: {str(e)}")
                finally:
                    self.output_stream = None
            
            # 清理缓冲区
            if hasattr(self, 'audio_buffer'):
                self.audio_buffer.clear()
            
            # 最后终止 PyAudio 实例
            if self.pyaudio_instance:
                self.pyaudio_instance.terminate()
                self.pyaudio_instance = None
                print("PyAudio 实例已清理")
        except Exception as e:
            print(f"清理 PyAudio 实例时出错: {str(e)}")
            
    def load_model(self, model_name, callback=None):
        """
        更新模型配置并立即加载模型
        
        参数:
            model_name (str): 模型名称 (tiny, base, small, medium, large)
            callback (function): 可选的回调函数，模型加载完成后调用
            
        返回:
            bool: 配置是否成功更新和模型是否成功加载
        """
        try:
            # 记录开始加载
            print(f"开始加载模型 {model_name}")
            
            # 更新配置和当前模型名称记录
            config.set("whisper_model", model_name) # 确保配置文件也被更新
            self.current_model_name = model_name
            
            # 更新处理器中的模型配置
            self.audio_processor.update_model(model_name)
            
            # 立即加载模型 - 这会阻塞直到模型加载完成
            start_time = time.time()
            model = self.audio_processor.get_model()
            load_time = time.time() - start_time
            
            # 记录加载时间
            logger.info(f"模型 {model_name} 已成功加载，用时 {load_time:.2f} 秒")
            print(f"模型 {model_name} 已成功加载，用时 {load_time:.2f} 秒")
            
            # 获取实际加载的模型名称（可能与请求的不同，比如自动降级）
            actual_model_name = self.audio_processor.current_model_name or model_name
            self.current_model_name = actual_model_name
            
            # 如果提供了回调函数，则调用它
            if callback:
                try:
                    print(f"直接调用回调函数: model_name={actual_model_name}, success=True")
                    callback(actual_model_name, True)
                except Exception as callback_error:
                    print(f"调用回调函数出错: {str(callback_error)}")
            
            # 模型加载成功
            return True
            
        except Exception as e:
            error_msg = f"加载模型 {model_name} 失败: {str(e)}"
            logger.error(error_msg)
            print(error_msg)
            
            # 重置当前模型名称
            self.current_model_name = None
            
            # 如果提供了回调函数，通知加载失败
            if callback:
                try:
                    print(f"直接调用回调函数(失败): model_name={model_name}, success=False")
                    callback(model_name, False)
                except Exception as callback_error:
                    print(f"调用回调函数出错: {str(callback_error)}")
                
            return False
    
    def get_input_devices(self):
        """获取系统上可用的音频输入设备列表"""
        p = pyaudio.PyAudio()
        devices = []
        
        try:
            for i in range(p.get_device_count()):
                try:
                    device_info = p.get_device_info_by_index(i)
                    if device_info['maxInputChannels'] > 0:
                        # 处理设备名称可能的编码问题
                        device_name = device_info['name']
                        
                        # 如果设备名称包含特殊字符或可能导致乱码的字符，尝试清理
                        try:
                            # 尝试解码/编码设备名称以验证其有效性
                            if isinstance(device_name, bytes):
                                device_name = device_name.decode('utf-8', errors='ignore')
                            
                            # 过滤掉一些已知问题的字符序列
                            import re
                            # 删除特殊控制字符
                            device_name = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', device_name)
                            # 删除一些常见的乱码标志
                            device_name = re.sub(r'[\uFFFD\uFFFE\uFFFF]', '', device_name)
                            
                            # 如果设备名称中包含系统路径，这可能表明有问题
                            if '@System32\\' in device_name or '\\??\\' in device_name:
                                # 尝试提取一个更友好的名称
                                friendly_parts = re.findall(r'#(\w+)$|%(\w+)|\\(\w+)\)', device_name)
                                if friendly_parts:
                                    # 使用找到的所有非空部分
                                    friendly_name = ''.join([part for group in friendly_parts for part in group if part])
                                    if friendly_name:
                                        device_name = f"音频设备 {friendly_name}"
                                    else:
                                        device_name = f"音频设备 {i}"
                                else:
                                    device_name = f"音频设备 {i}"
                            
                            # 确保最终名称不为空
                            if not device_name.strip():
                                device_name = f"音频设备 {i}"
                                
                        except Exception as e:
                            print(f"处理设备名称时出错: {str(e)}")
                            device_name = f"音频设备 {i}"
                        
                        # 添加设备信息到列表
                        devices.append(f"{device_name} (Index: {i})")
                except Exception as e:
                    print(f"获取设备 {i} 信息时出错: {str(e)}")
                    devices.append(f"未知设备 {i} (Index: {i})")
        except Exception as e:
            print(f"枚举音频设备时出错: {str(e)}")
        
        p.terminate()
        return devices
    
    def get_output_devices(self):
        """获取系统上可用的音频输出设备列表"""
        p = pyaudio.PyAudio()
        devices = []
        
        try:
            for i in range(p.get_device_count()):
                try:
                    device_info = p.get_device_info_by_index(i)
                    if device_info['maxOutputChannels'] > 0:
                        # 处理设备名称可能的编码问题
                        device_name = device_info['name']
                        
                        # 如果设备名称包含特殊字符或可能导致乱码的字符，尝试清理
                        try:
                            # 尝试解码/编码设备名称以验证其有效性
                            if isinstance(device_name, bytes):
                                device_name = device_name.decode('utf-8', errors='ignore')
                            
                            # 过滤掉一些已知问题的字符序列
                            import re
                            # 删除特殊控制字符
                            device_name = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', device_name)
                            # 删除一些常见的乱码标志
                            device_name = re.sub(r'[\uFFFD\uFFFE\uFFFF]', '', device_name)
                            
                            # 如果设备名称中包含系统路径，这可能表明有问题
                            if '@System32\\' in device_name or '\\??\\' in device_name:
                                # 尝试提取一个更友好的名称
                                friendly_parts = re.findall(r'#(\w+)$|%(\w+)|\\(\w+)\)', device_name)
                                if friendly_parts:
                                    # 使用找到的所有非空部分
                                    friendly_name = ''.join([part for group in friendly_parts for part in group if part])
                                    if friendly_name:
                                        device_name = f"音频设备 {friendly_name}"
                                    else:
                                        device_name = f"音频设备 {i}"
                                else:
                                    device_name = f"音频设备 {i}"
                            
                            # 确保最终名称不为空
                            if not device_name.strip():
                                device_name = f"音频设备 {i}"
                                
                        except Exception as e:
                            print(f"处理设备名称时出错: {str(e)}")
                            device_name = f"音频设备 {i}"
                        
                        # 添加设备信息到列表
                        devices.append(f"{device_name} (Index: {i})")
                except Exception as e:
                    print(f"获取设备 {i} 信息时出错: {str(e)}")
                    devices.append(f"未知设备 {i} (Index: {i})")
        except Exception as e:
            print(f"枚举音频设备时出错: {str(e)}")
        
        p.terminate()
        return devices
    
    def start_recording(self, input_device, output_device=None):
        """开始录音并识别语音"""
        if self.is_running:
            return
        
        # 确保之前的资源已清理
        self._cleanup_pyaudio()
        
        # 确保 PyAudio 实例存在
        self._init_pyaudio()
        if self.pyaudio_instance is None:
            print("无法启动录音：PyAudio 实例初始化失败")
            return
            
        self.is_running = True
        self.input_device = input_device
        self.output_device = output_device
        
        # 重置时间统计
        self.recognition_delay = 0
        
        # 从配置中读取延迟设置
        self.audio_delay_enabled = config.get("audio_delay_enabled", False)
        self.audio_delay_ms = config.get("audio_delay_ms", 0) if self.audio_delay_enabled else 0
        
        # 提取设备索引
        try:
            # 尝试从字符串中提取设备索引
            import re
            input_index_match = re.search(r'Index: (\d+)', input_device)
            if input_index_match:
                self.input_device_index = int(input_index_match.group(1))
                print(f"使用输入设备索引: {self.input_device_index}")
            else:
                print(f"无法从'{input_device}'提取输入设备索引，使用默认设备")
                self.input_device_index = None
            
            # 处理输出设备索引
            if output_device:
                output_index_match = re.search(r'Index: (\d+)', output_device)
                if output_index_match:
                    self.output_device_index = int(output_index_match.group(1))
                    print(f"使用输出设备索引: {self.output_device_index}")
                else:
                    print(f"无法从'{output_device}'提取输出设备索引，不使用输出设备")
                    self.output_device_index = None
            else:
                self.output_device_index = None
        except Exception as e:
            print(f"提取设备索引时出错: {str(e)}")
            self.input_device_index = None
            self.output_device_index = None
        
        # 启动字幕记录
        self.subtitle_manager.start_recording()
        
        # 启动录音线程 - 只负责录制音频并送入队列
        self.recording_thread = threading.Thread(target=self._record_audio)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
        # 启动识别线程 - 只负责从队列获取音频并进行识别
        self.recognition_thread = threading.Thread(target=self._recognize_audio)
        self.recognition_thread.daemon = True
        self.recognition_thread.start()
        
        # 如果启用了音频监听，则启动播放线程
        if config.get("monitor_enabled", False) and output_device:
            self.playback_thread = threading.Thread(target=self._playback_audio)
            self.playback_thread.daemon = True
            self.playback_thread.start()
        
        print(f"开始录音 - 输入设备: {input_device}, 输出设备: {output_device}")
        if self.audio_delay_enabled:
            print(f"音频延迟已启用: {self.audio_delay_ms} 毫秒")
            
    def stop_recording(self):
        """停止录音和识别"""
        self.is_running = False
        
        # 停止字幕记录
        self.subtitle_manager.stop_recording()
        
        # 等待线程结束
        for thread in [self.recording_thread, self.recognition_thread, self.playback_thread]:
            if thread:
                try:
                    thread.join(timeout=1)
                except Exception as e:
                    print(f"等待线程结束时出错: {str(e)}")
        
        # 清理资源
        self._cleanup_pyaudio()
            
    def _record_audio(self):
        """录制音频 - 只负责采集音频并送入队列"""
        try:
            # 获取当前配置的音频延迟设置
            delay_enabled = config.get("audio_delay_enabled", False)
            delay_ms = config.get("audio_delay_ms", 0)
            monitor_enabled = config.get("monitor_enabled", False)
            
            print(f"音频设置: 延迟={delay_enabled}, 延迟时间={delay_ms}ms, 监听={monitor_enabled}")
            
            # 记录开始时间
            recognition_start_time = time.time()
            
            # 创建音频流
            try:
                if self.pyaudio_instance is None:
                    print("PyAudio 实例不存在，尝试重新初始化")
                    self._init_pyaudio()
                    if self.pyaudio_instance is None:
                        print("无法创建音频流：PyAudio 实例初始化失败")
                        return
                
                # 创建输入流
                self.stream = self.pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=self.sample_rate,
                    input=True,
                    frames_per_buffer=self.chunk_size,
                    input_device_index=self.input_device_index if hasattr(self, 'input_device_index') else None
                )
                
                print(f"音频输入流创建成功: 采样率={self.sample_rate}, 通道数={self.channels}, 块大小={self.chunk_size}")
            except Exception as e:
                print(f"创建音频流失败: {str(e)}")
                return
            
            # 音频识别缓冲区
            recognition_buffer = []
            recognition_buffer_duration = 0  # 当前缓冲区时长（秒）
            
            # 性能监控变量
            frame_count = 0
            start_performance_time = time.time()
            
            # 减少record_seconds，降低延迟
            record_seconds = 1.5  # 优化: 减少每次处理的时间
            
            while self.is_running:
                try:
                    # 读取音频数据
                    audio_data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    
                    # 性能监控
                    frame_count += 1
                    if frame_count % 100 == 0:  # 每100帧输出一次性能信息
                        current_time = time.time()
                        elapsed = current_time - start_performance_time
                        fps = 100 / elapsed if elapsed > 0 else 0
                        if DEBUG_MODE:
                            print(f"音频处理性能: {fps:.2f} 帧/秒")
                        start_performance_time = current_time
                    
                    # 将音频数据转换为numpy数组
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    
                    # 检查音频数据是否有效
                    if np.max(np.abs(audio_array)) < 100:  # 如果音量太小，可能是静音
                        # 即使是静音也要放入播放队列，保持连续性
                        if monitor_enabled:
                            try:
                                # 非阻塞方式放入队列，如果队列满则跳过
                                self.playback_queue.put(audio_data, block=False)
                            except queue.Full:
                                # 队列已满，跳过此帧
                                pass
                        continue
                    
                    # 如果启用了监听，将原始音频数据放入播放队列
                    if monitor_enabled:
                        try:
                            # 非阻塞方式放入队列，如果队列满则跳过
                            self.playback_queue.put(audio_data, block=False)
                        except queue.Full:
                            # 队列已满，跳过此帧
                            pass
                    
                    # 转换为float32并归一化（用于识别）
                    audio_float = audio_array.astype(np.float32) / 32768.0
                    
                    # 将音频数据添加到识别缓冲区
                    recognition_buffer.append(audio_float)
                    recognition_buffer_duration += self.chunk_size / self.sample_rate
                    
                    # 当识别缓冲区达到指定时长时进行处理
                    if recognition_buffer_duration >= record_seconds:
                        # 合并音频数据
                        recognition_data = np.concatenate(recognition_buffer)
                        
                        # 将音频数据放入识别队列 - 直接传递NumPy数组，而不是字节
                        self.audio_queue.put((recognition_data, time.time()))
                        
                        # 清空缓冲区，但保留最后0.2秒的数据，减少延迟
                        overlap_samples = int(0.2 * self.sample_rate)
                        if len(recognition_buffer) > 0:
                            recognition_buffer = [recognition_buffer[-1]]  # 只保留最后一个块
                            recognition_buffer_duration = self.chunk_size / self.sample_rate
                    
                except Exception as e:
                    print(f"处理音频数据时出错: {str(e)}")
                    continue
                    
        except Exception as e:
            print(f"录制音频时出错: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            # 关闭输入流
            if hasattr(self, 'stream') and self.stream:
                try:
                    if self.stream.is_active():
                        self.stream.stop_stream()
                    self.stream.close()
                    self.stream = None
                except Exception as e:
                    print(f"关闭音频输入流时出错: {str(e)}")
            
    def _playback_audio(self):
        """专门的音频播放线程 - 只负责播放音频，与识别完全分离"""
        try:
            # 获取延迟设置
            delay_enabled = config.get("audio_delay_enabled", False)
            delay_ms = config.get("audio_delay_ms", 0)
            
            # 创建输出流
            try:
                # 如果PyAudio实例不存在，初始化它
                if self.pyaudio_instance is None:
                    self._init_pyaudio()
                    if self.pyaudio_instance is None:
                        print("无法创建音频输出流：PyAudio实例初始化失败")
                        return
                
                # 创建输出流
                output_stream = self.pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=self.sample_rate,
                    output=True,
                    frames_per_buffer=self.chunk_size,
                    output_device_index=self.output_device_index if hasattr(self, 'output_device_index') else None
                )
                
                print(f"音频输出流创建成功: 采样率={self.sample_rate}, 通道数={self.channels}")
            except Exception as e:
                print(f"创建音频输出流失败: {str(e)}")
                return
            
            # 延迟缓冲区
            delay_buffer = deque(maxlen=10000)  # 足够大的缓冲区
            
            # 如果启用延迟，计算延迟帧数并预填充缓冲区
            delay_frames = 0
            if delay_enabled and delay_ms > 0:
                delay_frames = int((delay_ms / 1000.0) * self.sample_rate / self.chunk_size)
                print(f"播放线程: 延迟设置为 {delay_frames} 帧 (约 {delay_ms} 毫秒)")
                
                # 预填充静音
                silent_frame = bytes(self.chunk_size * self.channels * 2)  # 16位音频 = 2字节/样本
                for _ in range(delay_frames):
                    delay_buffer.append(silent_frame)
                print(f"播放线程: 已预填充 {delay_frames} 帧静音数据")
            
            # 播放循环
            while self.is_running:
                try:
                    # 从队列获取音频数据（最多等待0.1秒）
                    try:
                        audio_data = self.playback_queue.get(timeout=0.1)
                    except queue.Empty:
                        # 队列为空，播放静音保持连续性
                        if output_stream.is_active():
                            silent_frame = bytes(self.chunk_size * self.channels * 2)
                            if delay_enabled and delay_ms > 0:
                                # 添加静音帧到延迟缓冲区
                                delay_buffer.append(silent_frame)
                                if len(delay_buffer) > 0:
                                    output_stream.write(delay_buffer.popleft())
                            else:
                                output_stream.write(silent_frame)
                        continue
                    
                    # 延迟播放逻辑
                    if delay_enabled and delay_ms > 0:
                        # 将新数据添加到延迟缓冲区
                        delay_buffer.append(audio_data)
                        # 始终播放最早的帧，保持连续流动
                        if len(delay_buffer) > 0:
                            output_stream.write(delay_buffer.popleft())
                    else:
                        # 直接播放，无延迟
                        output_stream.write(audio_data)
                    
                    # 标记此任务完成
                    self.playback_queue.task_done()
                    
                except Exception as e:
                    print(f"播放音频时出错: {str(e)}")
                    time.sleep(0.01)  # 防止错误循环消耗CPU
            
        except Exception as e:
            print(f"音频播放线程出错: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            # 关闭输出流
            if 'output_stream' in locals() and output_stream:
                try:
                    if output_stream.is_active():
                        output_stream.stop_stream()
                    output_stream.close()
                except Exception as e:
                    print(f"关闭音频输出流时出错: {str(e)}")
            
            print("音频播放线程已结束")
            
    def _recognize_audio(self):
        """使用Whisper模型识别音频"""
        while self.is_running or not self.audio_queue.empty():
            try:
                # 尝试从队列获取音频数据和开始时间（等待最多0.5秒）
                audio_data, start_time = self.audio_queue.get(timeout=0.5)
                
                # 检查是否是large模型，如果是则需要更谨慎地处理数据
                is_large_model = self.current_model_name == "large"
                
                try:
                    # 直接使用NumPy数组，不需要再次转换
                    audio_np = audio_data
                    
                    # 确保数据类型正确
                    if audio_np.dtype != np.float32:
                        audio_np = audio_np.astype(np.float32)
                    
                    # 确保音频数据在[-1, 1]范围内
                    max_abs = np.max(np.abs(audio_np))
                    if max_abs > 1.0:
                        audio_np = audio_np / max_abs
                    
                    # 确保数据是一维数组
                    if len(audio_np.shape) > 1:
                        audio_np = audio_np.flatten()
                    
                    # 对于large模型，可能需要额外检查
                    if is_large_model:
                        # 检查数据长度是否合适
                        if len(audio_np) < self.sample_rate:  # 小于1秒
                            logger.warning(f"音频片段过短: {len(audio_np)/self.sample_rate:.2f}秒，可能无法识别")
                            # 复制数据以达到最小长度
                            repeats = int(np.ceil(self.sample_rate / max(1, len(audio_np))))
                            audio_np = np.tile(audio_np, repeats)[:self.sample_rate]
                    
                    # 输出音频数据的统计信息（仅在调试模式下）
                    if DEBUG_MODE:
                        print(f"准备识别的音频: 形状={audio_np.shape}, 类型={audio_np.dtype}, 最大值={np.max(audio_np)}, 最小值={np.min(audio_np)}")
                    
                    # 开始计时
                    rec_start = time.time()
                    
                    # 使用AudioProcessor处理音频识别
                    recognition_result = self.audio_processor.process_audio(audio_np)
                    
                    # 计算处理时间
                    proc_time = int((time.time() - rec_start) * 1000)
                    
                    # 从结果中提取文本和语言
                    text = recognition_result.get("text", "")
                    detected_language = recognition_result.get("language")
                    
                    # 保存检测到的语言代码
                    self.detected_language = detected_language
                    
                    if DEBUG_MODE:
                        print(f"检测到语言: {detected_language}, 文本: {text[:50] if text else '无'}")
                    
                    # 如果有有效文本，保存结果
                    if text:
                        # 计算延迟（毫秒）- 使用处理时间而非总时间
                        self.recognition_delay = proc_time
                        
                        # 保存识别结果
                        result = RecognitionResult(text=text, language=detected_language, delay_ms=proc_time)
                        self.result_queue.append(result)
                        self.text_queue.append(text)
                        
                        # 添加到字幕管理器
                        self.subtitle_manager.add_subtitle(text)
                        
                        # 记录日志
                        if DEBUG_MODE:
                            print(f"识别文本: {text[:50]}... (延迟: {proc_time}ms, 语言: {detected_language})")
                        logger.info(f"识别文本: {text[:50]}... (延迟: {proc_time}ms, 语言: {detected_language})")
                
                except Exception as inner_e:
                    error_msg = f"音频数据处理错误: {str(inner_e)}"
                    logger.error(error_msg)
                    if DEBUG_MODE or is_large_model:
                        print(error_msg)
                        
                        # 对于large模型，提供更详细的错误信息
                        if is_large_model:
                            import traceback
                            print(f"Large模型处理详细错误信息:")
                            traceback.print_exc()
                
                # 标记任务完成
                self.audio_queue.task_done()
                
            except queue.Empty:
                # 队列为空，继续等待
                continue
            except Exception as e:
                # 记录错误但继续处理
                error_msg = f"音频识别错误: {str(e)}"
                logger.error(error_msg)
                if DEBUG_MODE:
                    print(error_msg)
                # 确保任务被标记为完成
                try:
                    self.audio_queue.task_done()
                except:
                    pass
    
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