import torch
import whisper
import numpy as np
from config import config

class AudioProcessor:
    def __init__(self):
        self.model = None
        # 检查CUDA是否可用
        self.device = "cuda" if config.get("use_gpu", True) and torch.cuda.is_available() else "cpu"
        print(f"使用设备: {self.device}")
        if self.device == "cuda":
            # 打印GPU信息
            print(f"GPU: {torch.cuda.get_device_name(0)}")
        self.load_model()
        
    def load_model(self):
        """加载Whisper模型"""
        model_name = config.get("whisper_model", "base")
        print(f"加载Whisper模型: {model_name} 到 {self.device}")
        self.model = whisper.load_model(model_name, device=self.device)
        
    def process_audio(self, audio_data):
        """处理音频数据"""
        if self.model is None:
            self.load_model()
            
        try:
            # 获取源语言设置
            source_language = config.get("source_language", "auto")
            
            # 使用Whisper模型进行识别 - 不要手动转为tensor
            # whisper.transcribe会自动处理数据并放在正确的设备上
            result = self.model.transcribe(
                audio_data,
                language=source_language if source_language != "auto" else None,
                task="transcribe"
            )
            
            return result["text"]
        except Exception as e:
            print(f"识别音频错误: {str(e)}")
            return ""
            
    def update_model(self, model_name):
        """更新模型"""
        if self.model is None or config.get("whisper_model") != model_name:
            config.set("whisper_model", model_name)
            self.load_model()
            
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
            self.load_model() 