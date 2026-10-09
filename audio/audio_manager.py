import os
import re
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
from audio.audio_timeline import TimedWord, WordSegment, AudioSegmentTask
from config import config  # 添加 config 导入

# 添加UI线程分离的队列
ui_update_queue = queue.Queue()

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

# 逐词字幕的时间轴：TimedWord / WordSegment / AudioSegmentTask 定义在
# audio_timeline 里（时间一律用"采集块号"，1 块 ≈ 64ms），见该模块的说明。

# 监听时，输出设备自身还有一小段缓冲（PortAudio + 驱动），用户实际上比
# playback_queue 的消费位置再晚听到这么多块。64ms 一块，取 2 块（约 128ms）——
# 这个量级对字幕对齐已经足够，不必去精确测量设备缓冲。
_OUTPUT_BUFFER_CHUNKS = 2

# 播放位置最多落后采集这么多块（约 2 秒）。播放线程卡死时 playback_queue 会一直
# 堆积，不设上限的话字幕会被甩到几秒之后。
_MAX_LAG_CHUNKS = 32

# WDM-KS 会把未解析的资源串原样吐出来：
#   "耳机 (@System32\drivers\bthhfenum.sys,#2;%1 Hands-Free%0\r\n;(AirPods Pro))"
_RESOURCE_STRING_RE = re.compile(r'@[^;]*;%\d+\s*([^%]*)%0[\s;,]*\(([^)]*)\)')


def clean_device_name(name):
    """清理设备名称：修复中文乱码、解析资源串、移除控制字符

    中文乱码来自"UTF-8 字节被当成 GBK 解码"：耳机(UTF-8 E8 80 B3 E6 9C BA)
    会显示成 "鑰虫満"。还原办法是把字符串按 GBK 编回字节再按 UTF-8 解码。
    对本来就正常的中文名（如"扬声器"）这一步会因 UnicodeDecodeError 失败，
    因此只在还原确实成功且结果不同时才采用——实测 60 个设备名，16 个乱码名
    全部还原正确，6 个正常名无一被改动。
    """
    if isinstance(name, bytes):
        for encoding in ('utf-8', 'gbk', 'latin-1'):
            try:
                name = name.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    name = str(name)

    # 1. 修复中文乱码（耳机 -> 鑰虫満）
    try:
        repaired = name.encode('gbk').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        repaired = None
    if repaired and repaired != name:
        name = repaired

    # 2. WDM-KS 的未解析资源串：@...;%1 Hands-Free%0;(AirPods Pro) -> AirPods Pro (Hands-Free)
    match = _RESOURCE_STRING_RE.search(name)
    if match:
        label = match.group(1).strip()
        device = match.group(2).strip()
        name = name[:match.start()] + (f"{device} ({label})" if label else device) + name[match.end():]

    # 3. 去掉控制字符（\r\n 之类）并压缩空白
    name = ''.join(ch if ch >= ' ' else ' ' for ch in name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


# 设备名末尾这些括号里装的是驱动/接口的样板描述，对"这是哪台设备"没有任何区分价值，
# 只是把下拉框撑长："DELL S2721DGF (NVIDIA High Definition Audio)" -> "DELL S2721DGF"
# 而 "(AirPods Pro)" "(ToDesk Virtual Audio)" 这类才是真正区分设备的部分，必须留下。
_BOILERPLATE_WORD_RE = re.compile(
    r'high definition audio|display audio|realtek|usb audio|wave mapper|bluetooth audio',
    re.IGNORECASE,
)


def _split_trailing_group(text):
    """拆出末尾那个成对的括号组，返回 (括号前的内容, 括号组)；没有则返回 (text, None)

    要处理嵌套："Speakers (Realtek(R) Audio)" 的末尾括号组是整段
    "(Realtek(R) Audio)"，不是里面那个 "(R)"。
    """
    stripped = text.rstrip()
    if not stripped.endswith(')'):
        return text, None
    close = len(stripped) - 1
    depth = 0
    for i in range(close, -1, -1):
        if stripped[i] == ')':
            depth += 1
        elif stripped[i] == '(':
            depth -= 1
            if depth == 0:
                return stripped[:i].rstrip(), stripped[i:]
    return text, None


def display_device_name(name):
    """把设备名整理成适合下拉菜单显示的样子（只用于显示，不参与匹配）

    设备列表走 MME，名字被系统截断到 31 字符，末尾常留下半个括号
    （"Realtek HD Audio 2nd output (Re"），看着像坏了；再叠上驱动样板名就更乱。
    这里把这两样都去掉，剩下的部分足够用户认出设备，同名设备靠索引区分。
    """
    original = clean_device_name(name)
    text = original

    # 1. 去掉末尾的驱动样板括号（可能叠了好几层，如 "... (Realtek(R) Audio)"）
    while True:
        head, group = _split_trailing_group(text)
        if group is None or not _BOILERPLATE_WORD_RE.search(group):
            break
        text = head

    # 2. 去掉末尾被截断的半个括号："... (Re" / "... (VB-Audio Virtual C"
    open_index = text.rfind('(')
    if open_index != -1 and text.find(')', open_index) == -1:
        text = text[:open_index]

    # 3. 万一整串都被去掉了（极端情况），保留原始名，别显示成空白
    return text.strip() or original


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
        # 语种检测是逐段做的，单段音频（1~7 秒）偶尔会判错，界面上就会看到
        # "英语/德语"来回跳。这里对最近几段做个多数表决，让显示稳定下来。
        self._language_votes = deque(maxlen=5)
        
        # 音频数据队列，用于从录音线程传递到播放线程
        self.playback_queue = queue.Queue(maxsize=1000)  # 限制队列大小以防内存占用过高
        
        # 使用AudioProcessor处理音频识别
        self.audio_processor = AudioProcessor()
        
        # 确保线程池已启动
        if hasattr(self.audio_processor, 'thread_pool') and not self.audio_processor.thread_pool.is_running:
            self.audio_processor.thread_pool.start()
            print("在AudioManager初始化中启动Whisper线程池")
        
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

        # 采集时钟：本轮录音读到的音频块数（1 块 ≈ 64ms）。逐词字幕的所有时间
        # 换算都以它为准，start_recording 时归零。
        self.captured_chunks = 0
        # 逐词片段队列：识别结果里的词级时间轴，界面按播放进度取用
        self.word_queue = deque(maxlen=16)
        # 预览识别是否正在跑（同一时刻只允许一个，绝不排队）
        self._partial_inflight = False


        # 从配置文件读取模型设置
        self.current_model_name = config.get("whisper_model", "base")
        
        # 初始化 PyAudio
        self._init_pyaudio()
        
        # 添加UI更新标志和时间控制
        self.last_ui_update_time = time.time()
        self.ui_update_interval = 0.1  # 100ms更新一次UI

        # 输入音量监听（用于界面音量表）
        self.input_volume = 0.0
        self._input_volume_time = 0.0
        self._volume_monitor_running = False
        self._volume_monitor_thread = None
        self._volume_monitor_index = None
        self._volume_monitor_stream = None
        # 监听代次：每次开关监听自增，旧线程凭此判断自己是否已被替换
        self._volume_monitor_token = 0

        # 输出（播放）音量（用于界面音量表）
        self.output_volume = 0.0
        self._output_volume_time = 0.0
        # 播放失败时的原因（None 表示正常），界面据此提示"为什么没声音"
        self.output_error = None
        # 播放线程的停止信号（与 is_running 分离，便于运行中单独开关监听）
        self._playback_stop_event = None
        # 本次监听已成功写出的音频帧数（一直在涨就说明数据确实送进了设备）
        self.playback_frames_written = 0
        # 本次监听实际打开的设备和它的索引，供界面显示
        self.monitor_device_name = None
        self.monitor_device_index = None
        # 最近一次"测试"音实际播放到的设备（界面用来显示"到底响在哪"）
        self.test_tone_device = None
        self.test_tone_index = None

        print("AudioManager初始化完成")
        
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
        """获取系统上可用的音频输入设备列表（返回 '名称 (Index: N)' 格式）

        名字经过 display_device_name 整理，只为了让下拉框好看；匹配设备时用的是
        原始名字（resolve_device_index 里的模糊匹配兼容两者）。
        """
        devices = self._enumerate_devices(want_input=True)
        return [f"{display_device_name(name)} (Index: {index})" for name, index in devices]

    def get_output_devices(self):
        """获取系统上可用的音频输出设备列表（返回 '名称 (Index: N)' 格式）"""
        devices = self._enumerate_devices(want_input=False)
        return [f"{display_device_name(name)} (Index: {index})" for name, index in devices]

    def _enumerate_devices(self, want_input):
        """
        枚举音频设备。

        采集和播放都统一用 MME——本机实测各主机 API 的表现：

        - MME：可用——read() 会真正阻塞等待新采样，返回的是新鲜数据；支持 16kHz
          （Whisper 所需的固定采样率），播放时由系统负责重采样到设备原生采样率。
          缺点是设备名被截断到 31 字符。
        - DirectSound：能打开、能写入、设备名完整，但本机送不出声音——实测向
          DirectSound 设备写入 880Hz 测试音，用虚拟声卡回环采集到的峰值只有 1
          （纯静音，正常应约 8000）；采集侧也同样失效：read() 不阻塞（实测读 8 次
          仅耗时 0.000 秒，正常应为 0.512 秒），并把所有设备的旧缓冲区原样反复返回
          （不同设备读到完全相同的数据），导致音量表在任何设备上都一直显示有信号。
        - WASAPI：设备只接受原生采样率（44.1/48kHz），16kHz 打开报
          -9997 Invalid sample rate。
        - WDM-KS：打开报 -9999 Unanticipated host error，且名称为乱码。

        因此两个方向都用 MME。代价是设备名被截断：名称相近的设备在列表里可能显示成
        同一条（例如两台型号相同的显示器），需要靠"先单独测试再选定"来区分。

        在单一主机 API 下不去重——每个物理设备只出现一次，而去重会误合并同名但实际
        不同的设备（例如两个型号相同的显示器）。若首选主机 API 不可用或为空，则回退到
        遍历全部主机 API 并按名称去重，以消除跨 API 的重复条目。
        """
        p = pyaudio.PyAudio()
        try:
            wanted_host = 'MME'
            preferred_host = None
            try:
                for h in range(p.get_host_api_count()):
                    host_name = (p.get_host_api_info_by_index(h).get('name') or '').strip()
                    if wanted_host.lower() in host_name.lower():
                        preferred_host = h
                        break
            except Exception:
                preferred_host = None

            if preferred_host is not None:
                items = self._collect_devices(p, want_input, host_filter=preferred_host, dedup=False)
                if items:
                    return items

            return self._collect_devices(p, want_input, host_filter=None, dedup=True)
        finally:
            p.terminate()

    def _collect_devices(self, p, want_input, host_filter, dedup):
        """收集指定类型的音频设备，返回 [(名称, index), ...]，可选按名称去重"""
        seen = set()
        result = []
        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
            except Exception:
                continue

            if host_filter is not None and info.get('hostApi') != host_filter:
                continue

            channels = info.get('maxInputChannels', 0) if want_input else info.get('maxOutputChannels', 0)
            if channels <= 0:
                continue

            name = self._clean_device_name(info.get('name', ''))
            if not name or self._is_pseudo_device(name):
                continue

            if dedup:
                key = name.strip().lower()
                if key in seen:
                    continue
                seen.add(key)

            result.append((name, i))

        return result

    def _clean_device_name(self, name):
        """清理设备名称（见模块级 clean_device_name）"""
        return clean_device_name(name)

    def _is_pseudo_device(self, name):
        """判断是否为伪设备（声音映射器 / 主声音驱动程序 / 无友好名的空端点）"""
        lower = name.lower()
        markers = (
            '声音映射器', 'sound mapper',
            '主声音捕获驱动程序', '主声音驱动程序',
            'primary sound capture driver', 'primary sound driver',
        )
        for marker in markers:
            if marker in lower:
                return True
        if name.endswith('()'):
            return True
        return False

    def start_recording(self, input_device, output_device=None):
        """开始录音并识别语音"""
        if self.is_running:
            return

        # 停止独立的音量监听线程，释放输入设备
        self.stop_input_monitor()

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

        # 重置逐词字幕的时间轴与待显示队列
        self.captured_chunks = 0
        self.word_queue.clear()
        self._partial_inflight = False

        # 提取设备索引（按名字重新匹配，不信任标签里的旧索引）
        try:
            self.input_device_index = self.resolve_device_index(input_device, want_input=True)
            if self.input_device_index is None:
                print(f"无法从'{input_device}'解析输入设备，使用默认设备")
            else:
                print(f"使用输入设备索引: {self.input_device_index}")

            if output_device:
                self.output_device_index = self.resolve_device_index(output_device)
                print(f"使用输出设备索引: {self.output_device_index}")
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
        if config.get("monitor_enabled", False):
            self.set_monitor_enabled(True)

        print(f"开始录音 - 输入设备: {input_device}, 输出设备: {output_device}")

    def set_monitor_enabled(self, enabled):
        """开关"监听系统声音"（把采集到的音频送到输出设备）

        运行中也能随时切换：勾选立即开始播放，取消立即停止，不必停机重启。
        未运行时什么也不做，等 start_recording 按配置统一启动。
        """
        if not self.is_running:
            return False
        if enabled:
            return self._start_playback()
        self._stop_playback()
        return True

    def _start_playback(self):
        """启动播放线程；已在播放则先停掉，确保按当前输出设备重新打开"""
        if not self.is_running:
            return False

        self._stop_playback()

        # 每次开播都按名字重新解析：设备列表可能已经变了，旧索引会指到别的设备
        if self.output_device:
            self.output_device_index = self.resolve_device_index(self.output_device)
            self._warn_if_index_stale(self.output_device, self.output_device_index)

        if self.output_device_index is None:
            self.output_error = "没有选择输出设备"
            print("监听已启用，但没有可用的输出设备，声音无法播放")
            return False

        # 丢掉上一轮残留的音频，避免重新开启时先蹦出旧声音
        while True:
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break

        self.output_error = None
        self.playback_frames_written = 0
        self.monitor_device_index = self.output_device_index
        self.monitor_device_name = self.describe_output_device(self.output_device_index)
        stop_event = threading.Event()
        self._playback_stop_event = stop_event
        self.playback_thread = threading.Thread(
            target=self._playback_audio, args=(stop_event,),
            name="audio-playback", daemon=True
        )
        self.playback_thread.start()
        return True

    def _stop_playback(self):
        """停止播放线程并归零输出音量表"""
        stop_event = self._playback_stop_event
        if stop_event is not None:
            stop_event.set()
        self._playback_stop_event = None

        thread = self.playback_thread
        self.playback_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
            if thread.is_alive():
                print("警告: 播放线程未能在 1 秒内结束")

        self.output_volume = 0.0
        self._output_volume_time = 0.0

    def get_output_error(self):
        """返回最近一次播放失败的原因，正常时为 None"""
        return self.output_error

    def describe_output_device(self, index):
        """按索引查设备名（用于界面显示"正在往哪个设备放"），查不到返回 None

        注意：索引在每次运行/插拔后都可能变，这里只是把即将打开的那个索引翻成名字，
        查到的名字仅用于显示和排查，不参与设备选择。
        """
        if index is None:
            return None
        try:
            if self.pyaudio_instance is None:
                self._init_pyaudio()
            info = self.pyaudio_instance.get_device_info_by_index(int(index))
            return clean_device_name(info.get("name") or "")
        except Exception:
            return None

    def get_monitor_device_name(self):
        """返回本次监听实际打开的设备名（未监听时为 None）"""
        return self.monitor_device_name

    def get_monitor_device_index(self):
        """返回本次监听实际打开的设备索引（未监听时为 None）"""
        return self.monitor_device_index

    def get_playback_frames_written(self):
        """返回本次监听已成功写出的音频帧数"""
        return self.playback_frames_written

    def set_output_device(self, output_device):
        """切换输出设备；正在监听时立刻用新设备重开输出流"""
        self.output_device = output_device
        self.output_device_index = self.resolve_device_index(output_device)
        if self.is_running and config.get("monitor_enabled", False):
            self.set_monitor_enabled(True)

    def play_test_tone(self, output_device, seconds=0.6):
        """向指定输出设备播放一小段测试音，用于确认监听是否真的出声

        先同步打开输出流（失败要立刻告诉用户），再在后台线程里写数据播放，
        避免界面卡顿。返回 (是否打开成功, 错误信息)。
        """
        index = self.resolve_device_index(output_device)

        p = pyaudio.PyAudio()
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self.chunk_size,
                output_device_index=index
            )
        except Exception as e:
            p.terminate()
            message = f"无法打开输出设备: {e}"
            print(f"测试音播放失败 - {message}")
            self.output_error = message
            return False, message

        # 界面标签里的索引可能是旧的，实际打开的是这个索引/设备，报给用户看
        actual_name = None
        try:
            actual_name = clean_device_name(
                p.get_device_info_by_index(index)['name']) if index is not None else '系统默认输出设备'
        except Exception:
            actual_name = None
        self.test_tone_device = actual_name
        self.test_tone_index = index

        def _play():
            try:
                # 两个短促的提示音，比单音更容易分辨
                t = np.arange(int(self.sample_rate * seconds)) / self.sample_rate
                tone = (0.25 * 32767 * np.sin(2 * np.pi * 880 * t)).astype(np.int16).tobytes()
                silence = bytes(int(self.sample_rate * 0.15) * 2)
                for _ in range(2):
                    stream.write(tone)
                    stream.write(silence)
                # 等缓冲区放完再关，避免把最后一段声音掐掉
                time.sleep(0.2)
                self.output_error = None
                print(f"测试音已播放到输出设备: {actual_name or output_device or '默认设备'}"
                      f"（索引 {index}，界面标签是「{output_device}」）")
            except Exception as e:
                self.output_error = f"写入输出设备失败: {e}"
                print(f"测试音播放失败 - {self.output_error}")
            finally:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
                p.terminate()

        threading.Thread(target=_play, name="output-test-tone", daemon=True).start()
        return True, None

    def stop_recording(self):
        """停止录音和识别"""
        if not self.is_running:
            print("录音未运行，无需停止")
            return
            
        print("开始停止录音和识别...")
        self.is_running = False

        # 先单独停播放线程（它有自己的停止信号），再统一 join
        self._stop_playback()

        # 停止字幕记录
        self.subtitle_manager.stop_recording()

        # 等待线程结束
        for thread in [self.recording_thread, self.recognition_thread]:
            if thread and thread.is_alive():
                try:
                    print(f"等待线程 {thread.name} 结束...")
                    thread.join(timeout=1)
                    if thread.is_alive():
                        print(f"线程 {thread.name} 超时未结束")
                except Exception as e:
                    print(f"等待线程结束时出错: {str(e)}")
        
        # 确保音频处理器的线程池停止
        if hasattr(self.audio_processor, 'thread_pool'):
            try:
                self.audio_processor.thread_pool.stop()
                print("Whisper线程池已停止")
            except Exception as e:
                print(f"停止Whisper线程池时出错: {str(e)}")
        
        # 清理资源
        self._cleanup_pyaudio()

        # 归零音量表，避免停止后界面仍显示有信号
        self.input_volume = 0.0
        self._input_volume_time = 0.0
        self.output_volume = 0.0
        self._output_volume_time = 0.0

        print("录音和识别已完全停止")
            
    def _record_audio(self):
        """录制音频 - 只负责采集音频并送入队列"""
        try:
            monitor_enabled = config.get("monitor_enabled", False)
            # 逐词开关每隔一会儿在循环里重新读一次（见下），勾选框改了就生效，
            # 不必停下来重新开始
            word_by_word = config.get("word_by_word_enabled", True)
            partial_interval = max(0.3, config.get("partial_interval_ms", 1000) / 1000.0)

            print(f"音频设置: 监听={monitor_enabled}, 逐词显示={word_by_word}"
                  + (f", 预览识别间隔={partial_interval:.1f}秒" if word_by_word else ""))
            
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

            # ── 逐词字幕的时间轴 ──────────────────────────────────────────
            # buffer_start_chunk / buffer_end_chunk 是当前缓冲区首尾在采集时间轴
            # 上的块号。识别结果里的词时间是"相对这段音频开头"的秒数，加上
            # buffer_start_chunk 就换算成了绝对位置，可以直接和播放位置比较。
            buffer_start_chunk = self.captured_chunks
            buffer_end_chunk = self.captured_chunks
            # 同一句话的预览识别与最终识别共用这个编号，便于归组/替换
            utterance_id = 0
            last_partial_time = 0.0

            # 记录上次提交的时间
            last_submission_time = time.time()

            # 性能监控变量
            frame_count = 0
            start_performance_time = time.time()
            last_progress_time = time.time()
            
            # 语音分段参数
            max_record_seconds = 7.0  # 最长一段音频，超过就强制切（Whisper 的窗口是 30 秒）
            min_record_seconds = 1.0  # 一段至少要有这么长才值得送去识别

            # 静音检测参数
            silence_duration_for_break = 0.5  # 连续静音超过这个时长就认为一句话说完了
            required_silence_frames = max(1, int(self.sample_rate / self.chunk_size * silence_duration_for_break))

            # 音频缓冲区大小限制。注意必须覆盖 max_record_seconds，否则缓冲区会先被
            # 这里的"防内存泄漏"逻辑从头部裁掉：原来写死 30 帧（0.064 秒/帧）只能存
            # 1.92 秒，于是 max_record_seconds=5 永远不可能触发，每次提交给 Whisper
            # 的都只有最近 1.9 秒的音频——前面说的话被整段丢掉，这才是识别不准的主因。
            max_recognition_buffer_items = int(
                max_record_seconds * self.sample_rate / self.chunk_size) + 10

            # 噪声底噪估计：用最近若干帧峰值的低分位数动态估计，而不是写死一个
            # 绝对阈值。写死的话（原来是 100，只有满量程的 0.3%）：
            #   - 真实麦克风的底噪通常就有一两百，会被当成"一直在说话"，
            #     静音帧永远清零，句子结束永远不触发，只能在超时处被硬切在词中间；
            #   - 虚拟声卡（VB-Cable 之类）底噪是数字零，阈值又完全够用。
            # 用低分位数就能同时适应这两种情况。
            noise_reference = deque(maxlen=150)  # 约 9.6 秒
            noise_floor = 0.0
            min_noise_floor = 150  # 底噪下限，避免在绝对安静时阈值退化成 0
            noise_ratio = 3.0     # 超过底噪这么多倍才算有人说话
            # 打开音频流后的前几帧是未初始化的（实测第一帧峰值可到 7827，之后都是 1），
            # 直接丢弃，否则会被当成"检测到语音"，接着 0.5 秒静音就判成一句话结束，
            # 把一段几乎全静的音频送进 Whisper 触发幻觉。
            warmup_frames = 5

            # 说话起始需要连续多少帧超过阈值才算数（滤掉单个脉冲）
            onset_frames_needed = 2
            onset_frames = 0

            # 是否有足够音量的标志
            has_sufficient_volume = False

            # 静音检测参数
            silence_frames = 0
            speech_detected = False  # 是否已检测到语音开始
            # 本段中"有语音"的帧数，用于判断这段音频是否值得送去识别
            voiced_frames_in_segment = 0
            
            while self.is_running:
                try:
                    # 读取音频数据
                    audio_data = self.stream.read(self.chunk_size, exception_on_overflow=False)

                    # 采集时钟：每读到一块就推进一格（丢弃的预热帧也要算，
                    # 否则时间轴会比真实时间快/慢）
                    self.captured_chunks += 1

                    # 性能监控
                    frame_count += 1
                    current_time = time.time()
                    
                    # 每5秒打印一次进度
                    if current_time - last_progress_time > 5 and DEBUG_MODE:
                        last_progress_time = current_time
                        print(f"录音进度正常，已处理 {frame_count} 帧")
                    
                    # 每100帧输出一次性能信息
                    if frame_count % 100 == 0:
                        elapsed = current_time - start_performance_time
                        fps = 100 / elapsed if elapsed > 0 else 0
                        if DEBUG_MODE:
                            print(f"音频处理性能: {fps:.2f} 帧/秒")
                        start_performance_time = current_time
                    
                    # 检查是否为信号报告的数字单词序列
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)

                    # 更新输入音量（用于界面音量表）
                    self._update_input_volume(self.meter_level(audio_data))

                    # 丢弃流刚打开时的未初始化数据（同时用它初始化底噪参考）
                    if frame_count <= warmup_frames:
                        continue

                    # 本帧峰值（int16 量纲）
                    current_volume = int(np.max(np.abs(audio_array)))

                    # 用低分位数（约 15%）估计噪声底噪：语音只占一小部分时间，
                    # 低分位数基本落在纯噪声帧上。
                    noise_reference.append(float(current_volume))
                    if len(noise_reference) >= 20:
                        sorted_ref = sorted(noise_reference)
                        noise_floor = sorted_ref[max(0, int(len(sorted_ref) * 0.15) - 1)]

                    speech_threshold = max(noise_floor * noise_ratio, min_noise_floor)
                    is_silent = current_volume <= speech_threshold

                    # 检测静音/语音
                    if not is_silent:  # 检测到声音
                        onset_frames += 1
                        if not speech_detected and onset_frames >= onset_frames_needed:
                            print(f"检测到语音开始，音量: {current_volume}, 判定阈值: {speech_threshold:.0f}, 底噪: {noise_floor:.0f}")
                            speech_detected = True
                            # 新的一句话：编号加一，这一句的预览/最终结果都归到它名下
                            utterance_id += 1
                        if speech_detected:
                            silence_frames = 0  # 重置静音计数
                            has_sufficient_volume = True
                            voiced_frames_in_segment += 1
                    else:  # 检测到静音
                        onset_frames = 0
                        if speech_detected:  # 只有在已经检测到语音的情况下才累计静音
                            silence_frames += 1
                            if DEBUG_MODE and silence_frames % 10 == 0:
                                print(f"静音检测: 已连续 {silence_frames} 帧静音, 需要 {required_silence_frames} 帧才算句子结束")
                    
                    # 如果监听启用，将原始音频数据放入播放队列
                    if monitor_enabled:
                        try:
                            # 非阻塞方式放入队列，如果队列满则跳过
                            self.playback_queue.put(audio_data, block=False)
                        except queue.Full:
                            # 队列已满，跳过此帧
                            if DEBUG_MODE and frame_count % 200 == 0:
                                print("播放队列已满，跳过部分帧")
                    
                    # 转换为float32并归一化（用于识别）
                    audio_float = audio_array.astype(np.float32) / 32768.0
                    
                    # 将音频数据添加到识别缓冲区
                    # 缓冲区是空的（刚开始录，或刚提交完一段）：这一块就是新起点。
                    # 起点必须跟着真正进缓冲区的数据走，不能按"上一段结尾 +1"推算，
                    # 否则预热帧（前 5 帧被丢弃）或丢帧会让整段词的时间轴偏移几十毫秒，
                    # 字幕就会整体偏早/偏晚。
                    if not recognition_buffer:
                        buffer_start_chunk = self.captured_chunks
                    recognition_buffer.append(audio_float)
                    recognition_buffer_duration += self.chunk_size / self.sample_rate
                    buffer_end_chunk = self.captured_chunks

                    # 限制识别缓冲区大小，防止内存泄漏（正常情况下不会触发，
                    # 因为一旦达到 max_record_seconds 就会被提交）
                    while len(recognition_buffer) > max_recognition_buffer_items:
                        removed_duration = len(recognition_buffer[0]) / self.sample_rate
                        recognition_buffer.pop(0)
                        # 丢掉的这块不再属于缓冲区，起点跟着往后挪
                        buffer_start_chunk += 1
                        recognition_buffer_duration -= removed_duration
                        if DEBUG_MODE and frame_count % 500 == 0:
                            print(f"缓冲区过大，已移除最早的 {removed_duration:.2f} 秒数据")

                    # ── 预览识别：说话过程中先看个大概 ────────────────────────
                    # 整句识别要等 0.5 秒静音才提交，等结果回来这句话早播完了，
                    # 所以整句结果只能"一下子全冒出来"。要让字幕一个词一个词跟着
                    # 语音走，就得在说话的同时用当前缓冲区先跑一次识别。
                    # 预览只喂逐词显示（绝不进字幕文件、不触发翻译），
                    # 最终结果到达时会把这一段整句替换掉。
                    # 开关每帧重读：正在跑的时候勾掉/勾上就生效，不用重开
                    word_by_word = config.get("word_by_word_enabled", True)
                    if (word_by_word and speech_detected and silence_frames == 0
                            and recognition_buffer_duration >= 1.0
                            and self.audio_queue.qsize() < 2
                            and current_time - last_partial_time >= partial_interval):
                        if self._partial_inflight:
                            # 上一次预览还没回来：识别跟不上，说明这台机器跑不动
                            # 这个间隔，拉长到最多 3 秒，别让预览抢走整句识别的资源
                            if current_time - last_partial_time > 2 * partial_interval:
                                partial_interval = min(partial_interval * 2, 3.0)
                                last_partial_time = current_time
                                print(f"预览识别跟不上，间隔放宽到 {partial_interval:.1f} 秒")
                        else:
                            self._submit_partial(
                                np.concatenate(recognition_buffer),
                                utterance_id, buffer_start_chunk, buffer_end_chunk
                            )
                            last_partial_time = current_time


                    # 判断是否需要提交音频进行处理的条件:
                    # 1. 缓冲区达到最大时长限制 - 强制提交
                    max_duration_reached = recognition_buffer_duration >= max_record_seconds

                    # 2. 检测到足够长的语音后接一个停顿 - 自然句子结束
                    sentence_end_detected = (speech_detected and
                                            recognition_buffer_duration >= min_record_seconds and
                                            silence_frames >= required_silence_frames)

                    # 3. 兜底：连续说了很久都没有停顿（比如现场噪声一直高于阈值），
                    #    至少每 4 秒交一次，避免字幕长时间不更新
                    current_time = time.time()
                    time_since_last_submission = current_time - last_submission_time
                    stalled_submit = (has_sufficient_volume and
                                      recognition_buffer_duration >= 4.0 and
                                      time_since_last_submission > 4.0)

                    # 每300帧打印一次分段状态
                    if speech_detected and frame_count % 300 == 0:
                        print(f"语音分段状态: 缓冲区={recognition_buffer_duration:.2f}秒, 连续静音={silence_frames}帧/{required_silence_frames}帧, 最大时长达到={max_duration_reached}, 句子结束={sentence_end_detected}, 兜底提交={stalled_submit}")

                    # 根据上述条件决定是否提交音频
                    if max_duration_reached or sentence_end_detected or stalled_submit:
                        # 合并音频数据
                        recognition_data = np.concatenate(recognition_buffer)

                        audio_length_sec = len(recognition_data) / self.sample_rate
                        audio_max_volume = float(np.max(np.abs(recognition_data)))
                        # 用整段 RMS 判断"有没有人说话"，而不是峰值：
                        # 峰值会被单个脉冲（例如流打开时的爆音）带过去，
                        # 于是一段几乎全静的音频也被送去识别并触发幻觉。
                        audio_rms = float(np.sqrt(np.mean(np.square(recognition_data))))
                        print(f"准备处理音频段: 长度={audio_length_sec:.2f}秒, 峰值={audio_max_volume:.4f}, "
                              f"RMS={audio_rms:.5f}, 有语音帧数={voiced_frames_in_segment}")

                        submitted = False
                        if not has_sufficient_volume or voiced_frames_in_segment < 2:
                            # 整段都没检测到语音：直接丢弃，不送识别。
                            # 这类音频交给 Whisper 只会换来幻觉文本。
                            print(f"音频片段内未检测到语音，丢弃 ({audio_length_sec:.2f}秒)")
                            submitted = True  # 已经"处理"过了，需要清空缓冲区
                        elif audio_rms < 0.0015:
                            # RMS 太低说明基本是噪声底噪，识别出来也没意义
                            print(f"音频片段 RMS 过低 ({audio_rms:.5f})，丢弃")
                            submitted = True
                        else:
                            try:
                                # 带上这段音频在采集时间轴上的位置，识别回来后才
                                # 知道"这些词是在什么时候说的"
                                task = AudioSegmentTask(
                                    data=recognition_data,
                                    submit_time=time.time(),
                                    start_chunk=buffer_start_chunk,
                                    end_chunk=buffer_end_chunk,
                                    utterance_id=utterance_id,
                                )
                                # 队列大小限制，避免堆积太多待处理任务
                                if self.audio_queue.qsize() < 5:
                                    print(f"提交音频段到识别队列: 长度={audio_length_sec:.2f}秒, 队列大小={self.audio_queue.qsize()}, 峰值={audio_max_volume:.4f}")
                                    self.audio_queue.put(task)
                                    submitted = True
                                    last_submission_time = time.time()
                                else:
                                    # 队列已满说明识别跟不上：丢弃最旧的一段，保证最新的
                                    # 语音一定能进去（旧代码在这里直接跳过，而且下面还会把
                                    # 缓冲区清空，等于白白丢掉一段语音）
                                    try:
                                        dropped = self.audio_queue.get_nowait()
                                        self.audio_queue.task_done()
                                        print(f"识别队列已满，丢弃最旧的一段({len(dropped.data)/self.sample_rate:.2f}秒)后提交")
                                    except queue.Empty:
                                        pass
                                    self.audio_queue.put(task)
                                    submitted = True
                                    last_submission_time = time.time()
                            except Exception as e:
                                print(f"提交音频段失败: {str(e)}")

                        if submitted:
                            # 只有真正处理过这段音频才清空缓冲区。
                            # 旧代码不管有没有提交都清空，还只保留 0.2 秒重叠——
                            # 既把被判"太短/太轻"的语音整段丢掉，又因为重叠部分
                            # 没有去重而制造重复词（实测词错率 10.4% → 14.6%）。
                            recognition_buffer = []
                            recognition_buffer_duration = 0
                            # 起点不用在这里算：缓冲区一空，下一块进来时会自己
                            # 认成新起点（见上面 append 之前的那段）
                            silence_frames = 0
                            speech_detected = False
                            onset_frames = 0
                            voiced_frames_in_segment = 0
                            has_sufficient_volume = False
                            print("音频段处理完毕，缓冲区已重置")

                    
                except Exception as e:
                    print(f"处理音频数据时出错: {str(e)}")
                    time.sleep(0.01)  # 短暂暂停，避免错误循环消耗CPU
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
            
            print("录音线程已结束")
            
    def _playback_audio(self, stop_event=None):
        """专门的音频播放线程 - 只负责播放音频，与识别完全分离

        采一块、播一块，不做任何人为延迟：字幕是按真实播放进度对齐的
        （见 get_play_position_chunks），音频再延迟只会让人听到的声音更晚。
        """
        try:
            # 创建输出流
            try:
                # 如果PyAudio实例不存在，初始化它
                if self.pyaudio_instance is None:
                    self._init_pyaudio()
                    if self.pyaudio_instance is None:
                        self.output_error = "PyAudio 实例初始化失败"
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

                # 记下真正打开的设备名，界面上直接显示，避免"以为在放耳机其实在放显示器"
                self.monitor_device_index = self.output_device_index
                self.monitor_device_name = self.describe_output_device(self.output_device_index)

                print(f"音频输出流创建成功: 采样率={self.sample_rate}, 通道数={self.channels}, "
                      f"设备索引={self.output_device_index}, 设备名={self.monitor_device_name}")
            except Exception as e:
                self.output_error = f"无法打开输出设备: {e}"
                print(f"创建音频输出流失败: {str(e)}")
                return

            last_error_log_time = 0.0  # 播放出错时限制日志频率

            # 播放循环：is_running 表示整体在录音，stop_event 表示监听被单独关掉
            while self.is_running and not (stop_event is not None and stop_event.is_set()):
                try:
                    # 从队列获取音频数据（最多等待0.1秒）
                    try:
                        audio_data = self.playback_queue.get(timeout=0.1)
                    except queue.Empty:
                        # 队列为空，播放静音保持连续性
                        if output_stream.is_active():
                            silent_frame = bytes(self.chunk_size * self.channels * 2)
                            output_stream.write(silent_frame)
                        self._update_output_volume(0.0)
                        continue

                    # 直接播放，不做人为延迟
                    output_stream.write(audio_data)

                    # 写成功之后才更新音量表——这样音量表反映的是真正写进输出设备的
                    # 数据，不会出现"音量表在动但耳机没声音"的误导
                    self._update_output_volume(self.meter_level(audio_data))
                    self.output_error = None
                    # 计数：一直在涨说明数据确实在往设备里送
                    self.playback_frames_written += 1

                    # 标记此任务完成
                    self.playback_queue.task_done()

                except Exception as e:
                    # 播放失败要让用户知道：音量表归零并在界面上提示原因
                    self.output_error = f"播放失败: {e}"
                    self._update_output_volume(0.0)
                    now = time.time()
                    if now - last_error_log_time > 5.0:
                        last_error_log_time = now
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

            # 线程结束（停止翻译或单独关掉监听）后音量表归零
            self.output_volume = 0.0
            self._output_volume_time = 0.0
            print("音频播放线程已结束")
            
    def _timed_words(self, words, start_chunk):
        """把词时间（相对音频段开头的秒数）换算成采集时间轴上的块号"""
        timed = []
        for word in words or []:
            try:
                start = start_chunk + int(round(
                    float(word["start"]) * self.sample_rate / self.chunk_size))
                end = start_chunk + int(round(
                    float(word["end"]) * self.sample_rate / self.chunk_size))
            except (KeyError, TypeError, ValueError):
                continue
            timed.append(TimedWord(word.get("word", ""), start, max(start, end)))
        return timed

    def _submit_partial(self, audio_snapshot, utterance_id, start_chunk, end_chunk):
        """提交一次预览识别（说话过程中先看个大概）

        结果只进逐词显示通道：不进 text_queue、不进字幕文件、不触发翻译。
        半截句子的错误识别只会在屏幕上闪一下，最终结果一到就被整句替换。
        """
        self._partial_inflight = True

        def on_partial_complete(result, utterance=utterance_id,
                                seg_start=start_chunk, seg_end=end_chunk):
            try:
                if "error" in result:
                    return
                words = self._timed_words(result.get("words"), seg_start)
                if not words:
                    return
                self.word_queue.append(WordSegment(
                    utterance_id=utterance, words=words,
                    start_chunk=words[0].start_chunk, end_chunk=seg_end,
                    is_final=False, text=result.get("text", ""),
                ))
                if DEBUG_MODE:
                    print(f"[预览识别] 第{utterance}句: {len(words)}个词, "
                          f"块 {seg_start}~{seg_end}")
            finally:
                self._partial_inflight = False

        try:
            task_id = self.audio_processor.process_audio_async(
                audio_snapshot, on_partial_complete, kind="partial")
        except Exception as e:
            print(f"提交预览识别失败: {str(e)}")
            self._partial_inflight = False
            return

        if task_id is None and self._partial_inflight:
            # 线程池正忙着整句识别：这次预览直接跳过。预览永远不排队，
            # 否则它会排在整句结果前面，把真正的字幕往后拖。
            self._partial_inflight = False

    def _recognize_audio(self):
        """使用Whisper模型识别音频"""
        # 最大队列长度 - 超过此长度时将自动丢弃旧的音频数据
        max_queue_size = 5  # 增加队列长度，允许更多音频等待处理
        
        # 添加计数器记录处理的任务数
        processed_count = 0
        
        # 定期打印状态信息
        last_status_time = time.time()
        
        print(f"识别线程已启动，正在等待音频数据...")
        
        while self.is_running or not self.audio_queue.empty():
            try:
                # 减少状态打印频率，减轻日志压力
                current_time = time.time()
                if current_time - last_status_time > 10:  # 每10秒打印一次状态，原为5秒
                    queue_size = self.audio_queue.qsize()
                    print(f"识别线程状态: 队列中有 {queue_size} 个音频段等待处理，已处理 {processed_count} 个任务")
                    last_status_time = current_time
                
                # 检查队列大小，如果太多，清除旧的音频数据
                if self.audio_queue.qsize() > max_queue_size:
                    dropped_count = 0
                    while self.audio_queue.qsize() > 2:  # 保留最新的两条，以保持连续性
                        try:
                            self.audio_queue.get_nowait()
                            self.audio_queue.task_done()
                            dropped_count += 1
                        except queue.Empty:
                            break
                    
                    print(f"队列过长，丢弃了 {dropped_count} 条旧的音频数据")
                
                # 尝试从队列获取音频数据（等待最多0.5秒）
                try:
                    task = self.audio_queue.get(timeout=0.5)
                    audio_data = task.data
                    wait_time = time.time() - task.submit_time
                    print(f"从队列获取到音频数据，等待时间: {wait_time:.2f}秒, 数据形状: {audio_data.shape}, 大小: {audio_data.size}, 最大值: {np.max(np.abs(audio_data)):.4f}")
                    processed_count += 1
                except queue.Empty:
                    # 队列为空，继续等待
                    continue
                
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
                    
                    # 确保音频数据是一维数组
                    if len(audio_np.shape) > 1:
                        audio_np = audio_np.flatten()
                        print(f"已将多维音频数据展平为一维数组: {audio_np.shape}")
                    
                    # 检查音频质量并输出详细信息
                    rms = np.sqrt(np.mean(np.square(audio_np)))
                    print(f"音频质量检查: 长度={len(audio_np)/self.sample_rate:.2f}秒, 最大值={max_abs:.4f}, RMS={rms:.4f}")
                    
                    # 检查是否有明显的信号
                    has_signal = max_abs > 0.01 and rms > 0.005
                    if not has_signal:
                        print(f"警告: 音频信号非常弱，可能无法识别出文本 (max={max_abs:.4f}, rms={rms:.4f})")
                    else:
                        print(f"音频信号检测: 有效信号，可以进行识别")
                    
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
                    
                    # 定义结果回调函数，在异步处理完成后处理结果
                    # 时间信息用默认参数绑死：回调是异步的，可能在这轮循环结束
                    # 之后才执行，直接引用外层变量会读到下一段音频的值
                    def on_recognition_complete(result, utterance=task.utterance_id,
                                                seg_start=task.start_chunk,
                                                seg_end=task.end_chunk):
                        try:
                            print(f"收到识别结果回调: result_id={result.get('task_id')}")
                            
                            # 检查是否有错误
                            if "error" in result:
                                error_msg = f"音频识别错误: {result['error']}"
                                logger.error(error_msg)
                                if DEBUG_MODE:
                                    print(error_msg)
                                return
                            
                            # 从结果中提取数据
                            text = result.get("text", "")
                            detected_language = result.get("language")
                            proc_time = result.get("delay_ms", 0)
                            
                            print(f"解析识别结果: text='{text[:30]}...', language={detected_language}, delay={proc_time}ms")
                            
                            # 保存检测到的语言代码
                            self.detected_language = detected_language
                            if detected_language and detected_language != "unknown":
                                self._language_votes.append(detected_language)
                            
                            if DEBUG_MODE:
                                print(f"检测到语言: {detected_language}, 文本: {text[:50] if text else '无'}")
                            
                            # 如果有有效文本，保存结果
                            if text:
                                print(f"有效文本，准备保存结果")
                                # 保存识别延迟
                                self.recognition_delay = proc_time
                                
                                # 保存识别结果 - 使用线程安全的方式
                                try:
                                    result_obj = RecognitionResult(text=text, language=detected_language, delay_ms=proc_time)
                                    self.result_queue.append(result_obj)
                                    self.text_queue.append(text)
                                    print(f"已保存到文本队列，当前队列长度: {len(self.text_queue)}")
                                    
                                    # 添加到字幕管理器
                                    self.subtitle_manager.add_subtitle(text)
                                    print(f"已添加到字幕管理器")

                                    # 逐词显示：最终结果的词表替换掉同一句的预览结果
                                    words = self._timed_words(result.get("words"), seg_start)
                                    if words:
                                        self.word_queue.append(WordSegment(
                                            utterance_id=utterance, words=words,
                                            start_chunk=words[0].start_chunk,
                                            end_chunk=seg_end,
                                            is_final=True, text=text,
                                        ))
                                        if DEBUG_MODE:
                                            print(f"逐词显示: 第{utterance}句最终结果 "
                                                  f"{len(words)}个词, 块 {seg_start}~{seg_end}")
                                    
                                    # 将UI更新任务放入UI更新队列，不直接在这里更新
                                    ui_update_queue.put(("text_update", text))
                                    
                                    # 记录日志
                                    if DEBUG_MODE:
                                        print(f"识别文本: {text[:50]}... (延迟: {proc_time}ms, 语言: {detected_language})")
                                    logger.info(f"识别文本: {text[:50]}... (延迟: {proc_time}ms, 语言: {detected_language})")
                                except Exception as e:
                                    print(f"保存结果时出错: {str(e)}")
                            else:
                                print("警告: 识别结果没有有效文本")
                        except Exception as callback_error:
                            logger.error(f"处理识别结果回调时出错: {str(callback_error)}")
                            if DEBUG_MODE:
                                print(f"处理识别结果回调时出错: {str(callback_error)}")
                            # 打印更详细的错误信息
                            import traceback
                            traceback.print_exc()
                    
                    # 直接使用新的接口，传递回调函数
                    # 不再需要事先设置全局回调
                    task_id = self.audio_processor.process_audio_async(audio_np, on_recognition_complete)
                    if DEBUG_MODE:
                        print(f"提交异步处理任务，ID: {task_id}")
                
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
        """获取最新识别的文本

        这个方法现在被界面以 200ms 的节奏轮询，所以日志要按 DEBUG_MODE 控制，
        否则控制台每秒刷 5 次"文本队列长度"。
        """
        if not self.text_queue:
            if DEBUG_MODE:
                print("文本队列为空，返回 None")
            return None

        # 返回最新一条文本
        latest_text = self.text_queue[-1]
        if DEBUG_MODE:
            print(f"从文本队列获取最新文本: '{latest_text[:30]}...'")
        return latest_text
        
    def take_word_segments(self):
        """取走待显示的逐词片段（界面主线程调用，取走即清空）"""
        if not self.word_queue:
            return []
        segments = list(self.word_queue)
        self.word_queue.clear()
        return segments

    def get_captured_chunks(self):
        """本轮录音已采集的音频块数（1 块 = 1024 样本 ≈ 64ms）"""
        return self.captured_chunks

    def get_play_position_chunks(self):
        """用户"此刻听到"的音频在采集时间轴上的块号

        监听开启时，播放队列里堆的正是"已经采集、还没送进输出设备"的音频，
        用户听到的就是队列最前面那一块，再补上输出设备自身的缓冲（几块）。
        监听关闭时用户直接听电台声音，按实时采集算——也就是零延迟。

        这个值取代了原来那个"手动加音频延迟"的滑块：延迟是多少不用猜，
        数一数还有多少块没播出去就知道了，而且每时每刻都在自动更新。
        """
        position = self.captured_chunks
        thread = self.playback_thread
        if thread is not None and thread.is_alive() and self.output_error is None:
            lag = self.playback_queue.qsize() + _OUTPUT_BUFFER_CHUNKS
            position -= min(lag, _MAX_LAG_CHUNKS)
        return max(0, position)

    def get_detected_language(self):
        """获取检测到的语言代码

        返回最近几段的多数表决结果，避免逐段检测偶发判错时界面上的语言标签乱跳。
        """
        if self._language_votes:
            return max(set(self._language_votes), key=self._language_votes.count)
        return self.detected_language
        
    def get_recognition_delay(self):
        """获取语音识别的延迟（毫秒）"""
        return self.recognition_delay

    def get_input_volume(self):
        """获取当前输入音量（0.0~1.0，用于界面音量表）"""
        # 超过 0.5 秒没有新的采样数据（监听/录音已停止或设备无数据）就归零，
        # 避免音量表停留在旧值上一直显示"有信号"
        if time.time() - self._input_volume_time > 0.5:
            return 0.0
        return self.input_volume

    def get_output_volume(self):
        """获取当前输出（播放）音量（0.0~1.0，用于界面音量表）"""
        if time.time() - self._output_volume_time > 0.5:
            return 0.0
        return self.output_volume

    def _update_input_volume(self, peak):
        """更新输入音量：快速上升、缓慢下降，呈现平滑的 VU 表效果"""
        self._input_volume_time = time.time()
        if peak > self.input_volume:
            self.input_volume = min(peak, 1.0)
        else:
            self.input_volume = max(0.0, self.input_volume * 0.9)

    def _update_output_volume(self, peak):
        """更新输出（播放）音量：快速上升、缓慢下降，呈现平滑的 VU 表效果"""
        self._output_volume_time = time.time()
        if peak > self.output_volume:
            self.output_volume = min(peak, 1.0)
        else:
            self.output_volume = max(0.0, self.output_volume * 0.9)

    @staticmethod
    def meter_level(data):
        """由原始 PCM 数据计算音量表电平（0.0~1.0）。

        先去掉直流分量再取 RMS，而不是直接取绝对值峰值：DirectSound 等驱动在
        音频流刚打开时返回的首批数据是未初始化的，带有明显的直流偏置甚至满量程
        的孤立采样。若按峰值计算，音量表会在每次打开流（例如切换设备）时瞬间冲
        到满格，看起来"选哪个设备都有信号"。
        """
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if arr.size == 0:
            return 0.0
        arr = arr - arr.mean()
        rms = float(np.sqrt(np.mean(arr * arr))) / 32768.0
        # RMS 数值偏小，乘 2 后更接近听感上的响度
        return min(rms * 2.0, 1.0)

    def _parse_device_index(self, device):
        """从 '名称 (Index: N)' 字符串中解析设备索引"""
        m = re.search(r'Index: (\d+)', device or '')
        return int(m.group(1)) if m else None

    @staticmethod
    def _device_label_to_name(device):
        """把 '耳机 (AirPods Pro) (Index: 22)' 还原成设备名 '耳机 (AirPods Pro)'"""
        return re.sub(r'\s*\(Index:\s*\d+\)\s*$', '', device or '').strip()

    @staticmethod
    def _device_name_key(name):
        """设备名归一化，便于比较（忽略大小写和多余空白）"""
        return re.sub(r'\s+', ' ', (name or '')).strip().lower()

    def resolve_device_index(self, device, want_input=False):
        """把界面上的设备标签解析成"此刻真的有效"的设备索引。

        标签里的 Index 只是生成设备列表那一刻的快照：插拔耳机、蓝牙连上/断开、
        虚拟声卡启停，都会让后面所有设备的索引整体错位。实测插一次蓝牙耳机，
        同一个索引就会从"耳机"变成"显示器"。所以这里一律按设备名重新枚举匹配，
        只有名字也找不到时才退回标签里的旧索引。
        """
        if not device:
            return None

        want_key = self._device_name_key(self._device_label_to_name(device))
        if not want_key:
            return self._parse_device_index(device)

        try:
            if self.pyaudio_instance is None:
                self._init_pyaudio()
            if self.pyaudio_instance is not None:
                # 和界面列表用同一个主机 API（两个方向都是 MME），否则同名设备可能
                # 匹配到另一个 API 的条目，索引含义就和界面不一致了。
                # 这里按名字找 MME 的序号，而不是写死 0——主机 API 的顺序由 PortAudio
                # 决定，写死会在别的机器上匹配错。
                wanted_host = None
                for h in range(self.pyaudio_instance.get_host_api_count()):
                    host_name = (self.pyaudio_instance.get_host_api_info_by_index(h).get('name') or '')
                    if 'mme' in host_name.lower():
                        wanted_host = h
                        break
                exact, fuzzy = [], []
                for i in range(self.pyaudio_instance.get_device_count()):
                    info = self.pyaudio_instance.get_device_info_by_index(i)
                    channel_key = 'maxInputChannels' if want_input else 'maxOutputChannels'
                    if info.get(channel_key, 0) <= 0:
                        continue
                    name_key = self._device_name_key(clean_device_name(info.get('name') or ''))
                    host_api = info.get('hostApi')
                    if name_key == want_key:
                        exact.append((host_api, i))
                    elif want_key in name_key or name_key in want_key:
                        fuzzy.append((host_api, i))
                # 自己用的主机 API 下的同名条目（名字可能完整、也可能被截断，
                # 所以精确和模糊两组都要看）。不能只看精确匹配那一组就返回：MME 把
                # 名字截断到 31 字符，完整名反而只存在于 DirectSound 条目里，先看
                # exact 会挑中那个送不出声音的 API。
                preferred = [i for candidates in (exact, fuzzy)
                             for host_api, i in candidates if host_api == wanted_host]

                # 名字一模一样的设备（两台同型号显示器在列表里显示成同一条）只能靠
                # 标签里的索引区分。索引虽然会变，但"那个索引现在仍指向一台同名设备"
                # 就说明它还没错位，用它——否则选有音箱的那台、声音会跑到没音箱的
                # 那台去，而且完全没提示。
                label_index = self._parse_device_index(device)
                if label_index is not None and label_index in preferred:
                    return label_index
                if preferred:
                    return preferred[0]

                # 自己用的接口下没有同名条目，才退回别的接口
                for candidates in (exact, fuzzy):
                    if candidates:
                        return candidates[0][1]
        except Exception as e:
            print(f"按名字匹配设备时出错（退回标签里的索引）: {e}")

        index = self._parse_device_index(device)
        if index is not None:
            print(f"警告: 找不到名为'{self._device_label_to_name(device)}'的设备，"
                  f"退回标签里的索引 {index}（可能已经指向别的设备）")
        return index

    def _warn_if_index_stale(self, device, resolved):
        """标签里的索引和实际解析出来的不一致时提醒一下（设备列表变过）"""
        label_index = self._parse_device_index(device)
        if resolved is not None and label_index is not None and label_index != resolved:
            print(f"提示: 「{self._device_label_to_name(device)}」在列表里的旧索引是 {label_index}，"
                  f"设备已变动，实际使用索引 {resolved}")

    def start_input_monitor(self, input_device):
        """开启独立的输入音量监听线程（不进行识别，仅供音量表显示）"""
        if self.is_running:
            return
        index = self.resolve_device_index(input_device, want_input=True)
        if index is None:
            self.stop_input_monitor()
            return
        if self._volume_monitor_running and self._volume_monitor_index == index:
            return
        self.stop_input_monitor()

        if self.pyaudio_instance is None:
            self._init_pyaudio()
        if self.pyaudio_instance is None:
            return

        # 优先用录音所用的采样率，这样音量表反映的就是识别时的真实电平；
        # 设备不支持时再退回它自己的默认采样率（否则会 -9997 Invalid sample rate）。
        rates = [self.sample_rate]
        try:
            info = self.pyaudio_instance.get_device_info_by_index(index)
            default_rate = info.get('defaultSampleRate')
            if default_rate and int(default_rate) not in rates:
                rates.append(int(default_rate))
        except Exception:
            pass
        if 44100 not in rates:
            rates.append(44100)

        stream = None
        last_error = None
        opened_rate = self.sample_rate
        for rate in rates:
            try:
                stream = self.pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=rate,
                    input=True,
                    frames_per_buffer=self.chunk_size,
                    input_device_index=index,
                )
                opened_rate = rate
                break
            except Exception as e:
                last_error = e
        if stream is None:
            print(f"开启音量监听失败: {last_error}")
            return

        self._volume_monitor_index = index
        self._volume_monitor_running = True
        self._volume_monitor_stream = stream
        self._volume_monitor_token += 1
        token = self._volume_monitor_token
        self._volume_monitor_thread = threading.Thread(
            target=self._volume_monitor_loop, args=(stream, token, opened_rate),
            name="input-volume-monitor", daemon=True
        )
        self._volume_monitor_thread.start()

    def _volume_monitor_loop(self, stream, token, rate):
        """音量监听线程：持续读取输入并更新音量"""
        try:
            # 丢弃流刚打开时的数据：驱动尚未填充真实采样，读到的是带直流偏置的
            # 垃圾数据，会让音量表一开始就冲到满格（切换设备时尤其明显）
            discard_until = time.time() + 0.15
            chunk_seconds = self.chunk_size / float(rate or self.sample_rate)
            last_data = None
            # 用代次 token 而不是全局开关判断退出：全局开关在切换设备时会被
            # 立刻重新置 True，会让尚未退出的旧线程继续从旧设备读数
            while self._volume_monitor_token == token:
                started = time.time()
                try:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                except Exception:
                    break
                if self._volume_monitor_token != token:
                    break
                # 部分驱动（DirectSound 下的虚拟设备）在没有真实数据时不会阻塞，
                # 而是立刻把上一次的缓冲区原样再返回一遍。逐字节相同的相邻数据块
                # 说明没有新的采样——按静音处理，既让无信号时音量表能回落，也避免
                # 把驱动复用的垃圾缓冲区当成信号。
                fresh = data != last_data
                last_data = data
                if time.time() >= discard_until:
                    level = self.meter_level(data) if fresh else 0.0
                    self._update_input_volume(level)
                # read 不阻塞时上面的循环会空转占满 CPU，按帧时长节流
                elapsed = time.time() - started
                if elapsed < chunk_seconds:
                    time.sleep(chunk_seconds - elapsed)
        finally:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def stop_input_monitor(self):
        """停止输入音量监听线程"""
        # 先让旧线程失效（token 变化），再关闭它的流以解除阻塞中的 read
        self._volume_monitor_token += 1
        self._volume_monitor_running = False
        stream = self._volume_monitor_stream
        self._volume_monitor_stream = None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
        thread = self._volume_monitor_thread
        if thread and thread.is_alive():
            thread.join(timeout=1)
        self._volume_monitor_thread = None
        self._volume_monitor_index = None
        # 归零并向界面报告"无信号"，避免切换设备后残留上一个设备的音量
        self.input_volume = 0.0
        self._input_volume_time = 0.0

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

    # 注：这里原有一个 _audio_callback（PyAudio 回调式录音）已删除。
    # 它从来没被用上（录音走 _record_audio 的阻塞式 read），而且它往
    # audio_queue 里放的是裸数组，与新的事件结构（AudioSegmentTask）不一致；
    # 语音活动检测的参数全部在 _record_audio 内部，删掉它与那四个模块级常量。