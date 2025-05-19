import json
import os

class Config:
    def __init__(self):
        self.config_file = "settings.json"
        self.default_settings = {
            "whisper_model": "base",  # 默认使用base模型
            "font_size": 24,
            "font_color": "white",
            "position": "bottom",
            "use_gpu": True,  # 默认使用GPU
            "device": "cuda",  # 默认使用CUDA
            "source_language": "auto",  # 源语言，默认自动检测
            "target_language": "zh",  # 目标语言，默认中文
            "window_width": 800,  # 字幕窗口宽度
            "window_height": 200,   # 字幕窗口高度
            "subtitle_mode": "translated",  # 字幕显示模式：original=只显示原文，translated=只显示译文，both=同时显示
            "input_device": "",  # 输入设备
            "output_device": "",  # 输出设备
            "monitor_enabled": False,  # 是否监听系统声音
            "main_window_width": 800,  # 主窗口宽度
            "main_window_height": 600   # 主窗口高度
        }
        self.settings = self.load_settings()

    def load_settings(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return self.default_settings.copy()
        return self.default_settings.copy()

    def save_settings(self):
        """保存配置到文件"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=4)

    def get(self, key, default=None):
        """获取配置项"""
        return self.settings.get(key, default)

    def set(self, key, value):
        """设置配置项"""
        self.settings[key] = value
        self.save_settings()

# 创建全局配置实例
config = Config() 