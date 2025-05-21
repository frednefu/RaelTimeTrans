import json
import os
import traceback

class Config:
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
            "window_width": 800,  # 字幕窗口宽度
            "window_height": 200,   # 字幕窗口高度
            "subtitle_mode": "translated",  # 字幕显示模式：original=只显示原文，translated=只显示译文，both=同时显示
            "input_device": "",  # 输入设备
            "output_device": "",  # 输出设备
            "monitor_enabled": False,  # 是否监听系统声音
            "audio_delay_enabled": False,  # 是否启用音频延迟
            "audio_delay_ms": 0,  # 音频延迟毫秒数
            "main_window_width": 800,  # 主窗口宽度
            "main_window_height": 600,   # 主窗口高度
            "show_audio_stats": True,  # 是否显示音频数据统计信息 - 修改为默认开启
        }
        self.settings = self.load_settings()
        
        # 确保所有默认设置项都存在于加载的设置中
        self.ensure_all_settings_exist()

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
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置文件时出错: {e}")

    def ensure_all_settings_exist(self):
        """确保所有默认设置项都存在于当前设置中"""
        needs_save = False
        for key, value in self.default_settings.items():
            if key not in self.settings:
                self.settings[key] = value
                needs_save = True
        
        # 如果有缺失项，立即保存更新后的设置
        if needs_save:
            self.save_settings()

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