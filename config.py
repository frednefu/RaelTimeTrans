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
            # 说话过程中每隔多少毫秒提交一次预览识别（逐词显示靠它）
            "partial_interval_ms": 1000,
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