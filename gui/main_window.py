from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QComboBox, QLabel, QSlider, QColorDialog,
                            QGroupBox, QCheckBox, QSpinBox, QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QColor
import os
import whisper
import torch
import threading
import time
from PySide6.QtWidgets import QApplication

from audio.audio_manager import AudioManager
from translation.subtitle_manager import SubtitleManager
from gui.subtitle_window import SubtitleWindow
from config import config

# 调试开关，控制是否输出调试信息到控制台
DEBUG_MODE = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实时翻译")
        self.setMinimumSize(800, 600)
        
        # 应用保存的窗口大小
        saved_width = config.get("main_window_width", 800)
        saved_height = config.get("main_window_height", 600)
        self.resize(saved_width, saved_height)
        
        # 初始化音频和字幕管理器
        self.audio_manager = AudioManager()
        self.subtitle_manager = SubtitleManager()
        
        # 创建字幕窗口
        self.subtitle_window = SubtitleWindow()
        
        # 初始化UI
        self.init_ui()
        
        # 启动定时器定期更新翻译结果
        self.timer = QTimer()
        self.timer.setInterval(250)  # 增加到250ms
        self.timer.timeout.connect(self.update_subtitles)
        
        # 记录上次更新UI的时间，避免过于频繁的更新
        self.last_update_time = 0
        self.ui_update_interval = 300  # 300ms最小UI更新间隔
        
        # 创建初始化标志，避免重复初始化模型
        self.model_initialized = False
        
        # 模型加载状态跟踪
        self.model_loading = False
        self.model_loading_complete = False
        self.current_loading_model = None
        
        # 检查并确保所有设置项存在，处理旧版本兼容性
        self.check_and_update_settings()
        
    def check_and_update_settings(self):
        """检查并更新设置，处理旧版本兼容性问题"""
        # 处理旧版本中单一字体大小设置的迁移
        if "font_size" in config.settings and (
            "original_font_size" not in config.settings or 
            "translation_font_size" not in config.settings
        ):
            old_font_size = config.get("font_size", 24)
            # 使用旧设置初始化新的分离设置
            config.set("original_font_size", old_font_size)
            config.set("translation_font_size", old_font_size)
            
        # 确保原文颜色设置存在
        if "original_font_color" not in config.settings:
            # 默认使用淡黄色作为原文颜色
            config.set("original_font_color", "#FFFF99")
            
        # 确保所有必要的设置存在于配置文件中
        for key, value in {
            "original_font_size": 24,
            "translation_font_size": 24,
            "font_color": "white",
            "original_font_color": "#FFFF99",
            "window_width": 800,
            "window_height": 200,
            "subtitle_mode": "translated"
        }.items():
            if key not in config.settings:
                config.set(key, value)
                
        # 强制同步到文件
        config.sync_to_file()
        
        if DEBUG_MODE:
            print("设置检查与更新完成")
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # 音频设备选择部分
        device_group = QGroupBox("音频设备设置")
        device_layout = QVBoxLayout()
        
        input_layout = QHBoxLayout()
        input_label = QLabel("输入设备:")
        self.input_device_combo = QComboBox()
        input_layout.addWidget(input_label)
        input_layout.addWidget(self.input_device_combo)
        
        output_layout = QHBoxLayout()
        output_label = QLabel("输出设备:")
        self.output_device_combo = QComboBox()
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_device_combo)
        
        self.monitor_checkbox = QCheckBox("监听系统声音")
        
        # 添加延迟控制部分
        delay_layout = QHBoxLayout()
        self.audio_delay_checkbox = QCheckBox("添加音频延迟")
        self.audio_delay_checkbox.setToolTip("延迟音频播放以匹配字幕显示")
        
        delay_label = QLabel("延迟(ms):")
        self.audio_delay_slider = QSlider(Qt.Orientation.Horizontal)
        self.audio_delay_slider.setMinimum(0)
        self.audio_delay_slider.setMaximum(5000)  # 最大5秒延迟
        self.audio_delay_slider.setSingleStep(50)
        self.audio_delay_slider.setPageStep(200)
        self.audio_delay_slider.setToolTip("调整音频延迟时间（毫秒）")
        
        self.audio_delay_value_label = QLabel("0")
        self.audio_delay_value_label.setMinimumWidth(40)
        
        # 音频数据统计选项
        self.show_audio_stats_checkbox = QCheckBox("显示音频数据统计信息")
        self.show_audio_stats_checkbox.setChecked(config.get("show_audio_stats", False))
        self.show_audio_stats_checkbox.setToolTip("显示详细的音频数据统计信息（用于调试）")
        self.show_audio_stats_checkbox.stateChanged.connect(self.on_show_audio_stats_changed)
        
        delay_layout.addWidget(self.audio_delay_checkbox)
        delay_layout.addWidget(delay_label)
        delay_layout.addWidget(self.audio_delay_slider)
        delay_layout.addWidget(self.audio_delay_value_label)
        
        device_layout.addLayout(input_layout)
        device_layout.addLayout(output_layout)
        device_layout.addWidget(self.monitor_checkbox)
        device_layout.addLayout(delay_layout)
        device_layout.addWidget(self.show_audio_stats_checkbox)
        device_group.setLayout(device_layout)
        
        # 翻译设置部分
        translation_group = QGroupBox("翻译设置")
        translation_layout = QVBoxLayout()
        
        # 源语言设置
        source_layout = QHBoxLayout()
        source_label = QLabel("源语言:")
        source_label.setFixedWidth(60)  # 固定宽度
        
        # 创建一个容器用于语言信息和延迟信息
        source_info_layout = QHBoxLayout()
        source_info_layout.setContentsMargins(0, 0, 0, 0)
        source_info_layout.setSpacing(5)
        
        # 添加检测到的语言标签
        self.detected_language_label = QLabel("")
        self.detected_language_label.setStyleSheet("color: blue;")
        self.detected_language_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)  # 右对齐
        
        # 添加识别延迟标签
        self.recognition_delay_label = QLabel("")
        self.recognition_delay_label.setStyleSheet("color: gray;")
        self.recognition_delay_label.setMinimumWidth(100)  # 设置最小宽度
        self.recognition_delay_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)  # 右对齐
        
        # 创建一个弹性占位符来推动内容向右对齐
        source_info_layout.addStretch(1)  # 添加弹性空间在左侧
        source_info_layout.addWidget(self.detected_language_label)
        source_info_layout.addWidget(self.recognition_delay_label)
        
        # 语言选择框
        self.source_language_combo = QComboBox()
        self.source_language_combo.addItems(["自动检测", "英语", "中文", "日语", "韩语", "法语", "德语", "俄语", "西班牙语"])
        self.source_language_combo.setCurrentText(config.get("source_language", "自动检测"))
        self.source_language_combo.currentTextChanged.connect(self.on_source_language_changed)
        self.source_language_combo.setFixedWidth(120)  # 固定宽度
        
        source_layout.addWidget(source_label)
        source_layout.addLayout(source_info_layout, 1)  # 给予弹性比例
        source_layout.addWidget(self.source_language_combo)
        
        # 目标语言设置
        target_layout = QHBoxLayout()
        target_label = QLabel("目标语言:")
        target_label.setFixedWidth(60)  # 固定宽度
        
        # 创建一个容器用于翻译延迟信息
        target_info_layout = QHBoxLayout()
        target_info_layout.setContentsMargins(0, 0, 0, 0)
        target_info_layout.setSpacing(5)
        
        # 添加翻译延迟标签
        self.translation_delay_label = QLabel("")
        self.translation_delay_label.setStyleSheet("color: gray;")
        self.translation_delay_label.setMinimumWidth(100)  # 设置最小宽度
        self.translation_delay_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)  # 右对齐
        
        # 创建一个弹性占位符来推动内容向右对齐
        target_info_layout.addStretch(1)  # 添加弹性空间在左侧
        target_info_layout.addWidget(self.translation_delay_label)
        
        # 语言选择框
        self.target_language_combo = QComboBox()
        self.target_language_combo.addItems(["不翻译", "中文", "英语", "日语", "韩语", "法语", "德语", "俄语", "西班牙语"])
        
        # 设置默认的目标语言
        saved_target_lang = config.get("target_language", "zh")
        if saved_target_lang == "none":  # 如果保存的是 "none"，表示"不翻译"
            self.target_language_combo.setCurrentText("不翻译")
        else:
            # 映射语言代码到显示名称
            lang_code_to_name = {
                "zh": "中文",
                "en": "英语",
                "ja": "日语",
                "ko": "韩语",
                "fr": "法语",
                "de": "德语",
                "ru": "俄语",
                "es": "西班牙语"
            }
            self.target_language_combo.setCurrentText(lang_code_to_name.get(saved_target_lang, "中文"))
        
        self.target_language_combo.currentTextChanged.connect(self.on_target_language_changed)
        self.target_language_combo.setFixedWidth(120)  # 固定宽度
        
        target_layout.addWidget(target_label)
        target_layout.addLayout(target_info_layout, 1)  # 给予弹性比例
        target_layout.addWidget(self.target_language_combo)
        
        translation_layout.addLayout(source_layout)
        translation_layout.addLayout(target_layout)
        translation_group.setLayout(translation_layout)
        
        # 字幕样式设置部分
        subtitle_group = QGroupBox("字幕样式")
        subtitle_layout = QVBoxLayout()
        
        # 原文字体大小设置
        original_font_size_layout = QHBoxLayout()
        original_font_size_label = QLabel("原文字体大小:")
        self.original_font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.original_font_size_slider.setRange(10, 50)
        self.original_font_size_slider.setValue(24)
        self.original_font_size_slider.valueChanged.connect(self.update_subtitle_preview)
        original_font_size_layout.addWidget(original_font_size_label)
        original_font_size_layout.addWidget(self.original_font_size_slider)
        
        # 译文字体大小设置
        translation_font_size_layout = QHBoxLayout()
        translation_font_size_label = QLabel("译文字体大小:")
        self.translation_font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.translation_font_size_slider.setRange(10, 50)
        self.translation_font_size_slider.setValue(24)
        self.translation_font_size_slider.valueChanged.connect(self.update_subtitle_preview)
        translation_font_size_layout.addWidget(translation_font_size_label)
        translation_font_size_layout.addWidget(self.translation_font_size_slider)
        
        # 原文颜色设置
        original_color_layout = QHBoxLayout()
        original_color_label = QLabel("原文颜色:")
        self.original_color_button = QPushButton()
        self.original_color_button.setStyleSheet("background-color: white;")
        self.original_color_button.clicked.connect(self.select_original_color)
        original_color_layout.addWidget(original_color_label)
        original_color_layout.addWidget(self.original_color_button)
        
        # 译文颜色设置
        color_layout = QHBoxLayout()
        color_label = QLabel("译文颜色:")
        self.color_button = QPushButton()
        self.color_button.setStyleSheet("background-color: white;")
        self.color_button.clicked.connect(self.select_color)
        color_layout.addWidget(color_label)
        color_layout.addWidget(self.color_button)
        
        position_layout = QHBoxLayout()
        position_label = QLabel("字幕位置:")
        self.position_combo = QComboBox()
        self.position_combo.addItems(["顶部", "中间", "底部"])
        self.position_combo.setCurrentIndex(2)  # 默认底部
        self.position_combo.currentIndexChanged.connect(self.update_subtitle_preview)
        position_layout.addWidget(position_label)
        position_layout.addWidget(self.position_combo)
        
        # 字幕显示模式设置
        subtitle_mode_layout = QHBoxLayout()
        subtitle_mode_layout.addWidget(QLabel("显示模式:"))
        self.subtitle_mode_combo = QComboBox()
        self.subtitle_mode_combo.addItems(["仅显示译文", "仅显示原文", "同时显示原文和译文"])
        
        # 设置初始选择
        mode_map = {
            "translated": "仅显示译文",
            "original": "仅显示原文",
            "both": "同时显示原文和译文"
        }
        current_mode = config.get("subtitle_mode", "translated")
        self.subtitle_mode_combo.setCurrentText(mode_map.get(current_mode, "仅显示译文"))
        self.subtitle_mode_combo.currentTextChanged.connect(self.on_subtitle_mode_changed)
        subtitle_mode_layout.addWidget(self.subtitle_mode_combo)
        
        # 字幕窗口大小设置
        window_size_layout = QHBoxLayout()
        window_size_layout.addWidget(QLabel("窗口宽度:"))
        self.window_width_spin = QSpinBox()
        self.window_width_spin.setRange(10, 1920)
        self.window_width_spin.setValue(config.get("window_width", 800))
        self.window_width_spin.valueChanged.connect(self.on_window_width_changed)
        window_size_layout.addWidget(self.window_width_spin)

        window_size_layout.addWidget(QLabel("窗口高度:"))
        self.window_height_spin = QSpinBox()
        # 设置最小值为1，允许非常小的高度
        self.window_height_spin.setRange(1, 600)
        self.window_height_spin.setValue(config.get("window_height", 200))
        self.window_height_spin.valueChanged.connect(self.on_window_height_changed)
        window_size_layout.addWidget(self.window_height_spin)

        subtitle_layout.addLayout(original_font_size_layout)
        subtitle_layout.addLayout(translation_font_size_layout)
        subtitle_layout.addLayout(original_color_layout)
        subtitle_layout.addLayout(color_layout)
        subtitle_layout.addLayout(position_layout)
        subtitle_layout.addLayout(subtitle_mode_layout)
        subtitle_layout.addLayout(window_size_layout)
        subtitle_group.setLayout(subtitle_layout)
        
        # 控制按钮部分
        control_layout = QHBoxLayout()
        self.start_button = QPushButton("开始翻译")
        self.start_button.clicked.connect(self.toggle_translation)
        self.preview_button = QPushButton("预览字幕")
        self.preview_button.clicked.connect(self.preview_subtitles)
        
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.preview_button)
        
        # 字幕预览区域
        preview_group = QGroupBox("字幕预览")
        preview_group.setObjectName("字幕预览")
        preview_layout = QVBoxLayout()
        
        # 原文预览标签
        self.original_preview = QLabel("Original text will appear here")
        self.original_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_preview.setFont(QFont("Arial", 18))
        self.original_preview.setStyleSheet("color: white; background-color: black; padding: 5px;")
        self.original_preview.setWordWrap(True)

        # 译文预览标签
        self.subtitle_preview = QLabel("字幕将显示在这里")
        self.subtitle_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_preview.setFont(QFont("Arial", 24))
        self.subtitle_preview.setStyleSheet("color: white; background-color: black; padding: 5px;")
        self.subtitle_preview.setWordWrap(True)

        # 根据当前字幕模式添加适当的预览标签
        subtitle_mode = config.get("subtitle_mode", "translated")
        if subtitle_mode == "original" or subtitle_mode == "both":
            preview_layout.addWidget(self.original_preview)
        if subtitle_mode == "translated" or subtitle_mode == "both":
            preview_layout.addWidget(self.subtitle_preview)

        preview_group.setLayout(preview_layout)
        
        # 添加所有元素到主布局
        main_layout.addWidget(device_group)
        main_layout.addWidget(translation_group)
        main_layout.addWidget(subtitle_group)
        main_layout.addLayout(control_layout)
        main_layout.addWidget(preview_group)
        
        # 初始化音频设备列表
        self.populate_audio_devices()
        
        # 创建Whisper模型设置组
        model_group = QGroupBox("Whisper模型设置")
        model_layout = QVBoxLayout()
        
        # 模型选择
        model_layout.addWidget(QLabel("选择模型:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large"])
        self.model_combo.setCurrentText(config.get("whisper_model", "base"))
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        model_layout.addWidget(self.model_combo)
        
        # 模型状态标签
        self.model_status_label = QLabel()
        self.model_status_label.setStyleSheet("margin-top: 5px;")
        model_layout.addWidget(self.model_status_label)
        
        # GPU设置
        self.gpu_check = QCheckBox("使用GPU加速")
        self.gpu_check.setChecked(config.get("use_gpu", True))
        self.gpu_check.stateChanged.connect(self.on_gpu_changed)
        model_layout.addWidget(self.gpu_check)
        
        # 打开模型文件夹按钮
        self.open_model_dir_button = QPushButton("打开模型文件夹")
        self.open_model_dir_button.clicked.connect(self.open_model_folder)
        model_layout.addWidget(self.open_model_dir_button)
        
        model_group.setLayout(model_layout)
        main_layout.addWidget(model_group)
        
        # 应用保存的设置
        self.apply_saved_settings()
        
        # 更新模型状态显示
        self.update_model_status()
        
    def closeEvent(self, event):
        """程序关闭时的处理"""
        # 停止录音和翻译
        try:
            if self.audio_manager.is_running:
                self.audio_manager.stop_recording()
        except Exception as e:
            print(f"关闭录音时出错: {str(e)}")
        
        # 关闭字幕窗口
        self.subtitle_window.close()
        
        # 清除检测到的语言标签和延迟信息
        self.detected_language_label.setText("")
        self.recognition_delay_label.setText("")
        self.translation_delay_label.setText("")
        
        # 确保所有设置都被保存
        self.save_all_settings()
        
        # 调用父类方法关闭窗口
        super().closeEvent(event)
    
    def save_all_settings(self):
        """保存所有当前设置到配置文件"""
        try:
            # 保存界面设置
            config.set("original_font_size", self.original_font_size_slider.value())
            config.set("translation_font_size", self.translation_font_size_slider.value())
            
            # 获取颜色设置
            original_color_style = self.original_color_button.styleSheet()
            original_color = original_color_style.split(":")[-1].strip("; ")
            
            color_style = self.color_button.styleSheet()
            translation_color = color_style.split(":")[-1].strip("; ")
            
            config.set("original_font_color", original_color)
            config.set("font_color", translation_color)
            
            # 保存窗口尺寸设置
            config.set("window_width", self.window_width_spin.value())
            config.set("window_height", self.window_height_spin.value())
            
            # 保存主窗口尺寸
            config.set("main_window_width", self.width())
            config.set("main_window_height", self.height())
            
            # 强制同步到文件
            config.sync_to_file()
            
            if DEBUG_MODE:
                print("所有设置已保存")
                
        except Exception as e:
            print(f"保存设置时出错: {str(e)}")
    
    def populate_audio_devices(self):
        """填充音频设备列表"""
        input_devices = self.audio_manager.get_input_devices()
        output_devices = self.audio_manager.get_output_devices()
        
        self.input_device_combo.clear()
        self.input_device_combo.addItems(input_devices)
        
        self.output_device_combo.clear()
        self.output_device_combo.addItems(output_devices)
        
        # 加载上次使用的设备设置
        saved_input = config.get("input_device", "")
        if saved_input and saved_input in input_devices:
            self.input_device_combo.setCurrentText(saved_input)
        
        saved_output = config.get("output_device", "")
        if saved_output and saved_output in output_devices:
            self.output_device_combo.setCurrentText(saved_output)
        
        # 设置监听选项
        self.monitor_checkbox.setChecked(config.get("monitor_enabled", False))
        
        # 设置音频延迟选项
        self.audio_delay_checkbox.setChecked(config.get("audio_delay_enabled", False))
        
        # 设置延迟滑块值
        delay_ms = config.get("audio_delay_ms", 0)
        self.audio_delay_slider.setValue(delay_ms)
        self.audio_delay_value_label.setText(str(delay_ms))
        
        # 根据监听选项状态更新延迟控件的启用状态
        self.update_delay_controls_state()
        
        # 连接设置变更事件
        self.input_device_combo.currentTextChanged.connect(self.on_input_device_changed)
        self.output_device_combo.currentTextChanged.connect(self.on_output_device_changed)
        self.monitor_checkbox.stateChanged.connect(self.on_monitor_changed)
        self.audio_delay_checkbox.stateChanged.connect(self.on_audio_delay_checked)
        self.audio_delay_slider.valueChanged.connect(self.on_audio_delay_changed)
    
    def update_delay_controls_state(self):
        """根据监听选项的状态更新延迟控件的启用状态"""
        is_monitor_enabled = self.monitor_checkbox.isChecked()
        
        # 音频延迟功能只有在监听系统声音启用时才有效
        self.audio_delay_checkbox.setEnabled(is_monitor_enabled)
        
        # 延迟滑块和标签的启用状态取决于监听选项和延迟选项
        is_delay_enabled = is_monitor_enabled and self.audio_delay_checkbox.isChecked()
        self.audio_delay_slider.setEnabled(is_delay_enabled)
        
        # 更新控件提示
        if not is_monitor_enabled:
            self.audio_delay_checkbox.setToolTip("需要先启用监听系统声音")
        else:
            self.audio_delay_checkbox.setToolTip("延迟音频播放以匹配字幕显示")
            
    def on_audio_delay_checked(self, state):
        """音频延迟复选框状态变化的处理"""
        is_checked = state == Qt.CheckState.Checked.value
        config.set("audio_delay_enabled", is_checked)
        
        # 更新延迟滑块和标签的启用状态
        self.update_delay_controls_state()
        
        # 如果正在运行中，通知音频管理器更新延迟设置
        if self.audio_manager.is_running:
            self.update_audio_delay_settings()
    
    def on_audio_delay_changed(self, value):
        """音频延迟滑块值变化的处理"""
        # 更新标签显示
        self.audio_delay_value_label.setText(str(value))
        
        # 保存设置
        config.set("audio_delay_ms", value)
        
        # 如果正在运行中，通知音频管理器更新延迟设置
        if self.audio_manager.is_running:
            self.update_audio_delay_settings()
    
    def update_audio_delay_settings(self):
        """更新音频管理器的延迟设置"""
        is_delay_enabled = self.audio_delay_checkbox.isChecked()
        delay_ms = self.audio_delay_slider.value()
        
        # 如果音频管理器添加了延迟设置方法，则调用
        if hasattr(self.audio_manager, 'set_audio_delay'):
            if is_delay_enabled:
                self.audio_manager.set_audio_delay(delay_ms)
            else:
                self.audio_manager.set_audio_delay(0)
                
    def on_monitor_changed(self, state):
        """监听选项变更时的处理"""
        enabled = state == Qt.CheckState.Checked.value
        config.set("monitor_enabled", enabled)
        
        # 更新延迟控件的启用状态
        self.update_delay_controls_state()
    
    def select_original_color(self):
        """打开原文颜色选择对话框"""
        color = QColorDialog.getColor()
        if color.isValid():
            self.original_color_button.setStyleSheet(f"background-color: {color.name()};")
            # 更新字幕预览
            self.update_subtitle_preview()
    
    def select_color(self):
        """打开译文颜色选择对话框"""
        color = QColorDialog.getColor()
        if color.isValid():
            self.color_button.setStyleSheet(f"background-color: {color.name()};")
            # 更新字幕预览
            self.update_subtitle_preview()
    
    def update_subtitle_preview(self):
        """更新字幕预览和字幕窗口的样式"""
        # 获取当前设置的样式
        original_font_size = self.original_font_size_slider.value()
        translation_font_size = self.translation_font_size_slider.value()
        
        # 获取原文颜色
        original_color_style = self.original_color_button.styleSheet()
        original_color = original_color_style.split(":")[-1].strip("; ")
        
        # 获取译文颜色
        color_style = self.color_button.styleSheet()
        color = color_style.split(":")[-1].strip("; ")
        
        # 位置映射
        position_map = {
            "顶部": "top",
            "中间": "middle",
            "底部": "bottom"
        }
        position = position_map.get(self.position_combo.currentText(), "bottom")
        
        # 获取当前的字幕显示模式
        subtitle_mode = config.get("subtitle_mode", "translated")
        
        # 保存设置到配置
        config.set("original_font_size", original_font_size)
        config.set("translation_font_size", translation_font_size)
        config.set("font_color", color)
        config.set("original_font_color", original_color)
        config.set("position", position)
        # 手动触发配置同步写入
        config.sync_to_file()
        
        # 更新预览区域样式
        self.original_preview.setFont(QFont("Arial", original_font_size))
        self.original_preview.setStyleSheet(f"color: {original_color}; background-color: black; padding: 5px;")
        
        self.subtitle_preview.setFont(QFont("Arial", translation_font_size))
        self.subtitle_preview.setStyleSheet(f"color: {color}; background-color: black; padding: 5px;")
        
        # 清空预览区域布局
        preview_layout = self.findChild(QGroupBox, "字幕预览").layout()
        while preview_layout.count():
            item = preview_layout.takeAt(0)
            if item.widget():
                preview_layout.removeWidget(item.widget())
                item.widget().hide()
        
        # 根据字幕模式和目标语言设置添加相应的预览标签
        target_language = self.target_language_combo.currentText()
        is_translation_disabled = target_language == "不翻译"
        
        if subtitle_mode == "original" or (is_translation_disabled and subtitle_mode != "translated"):
            # 仅显示原文模式
            preview_layout.addWidget(self.original_preview)
            self.original_preview.show()
        elif subtitle_mode == "translated" and not is_translation_disabled:
            # 仅显示译文模式
            preview_layout.addWidget(self.subtitle_preview)
            self.subtitle_preview.show()
        elif subtitle_mode == "both" and not is_translation_disabled:
            # 同时显示原文和译文
            preview_layout.addWidget(self.original_preview)
            preview_layout.addWidget(self.subtitle_preview)
            self.original_preview.show()
            self.subtitle_preview.show()
        else:
            # 默认情况下显示原文
            preview_layout.addWidget(self.original_preview)
            self.original_preview.show()
        
        # 更新字幕窗口样式和模式
        self.subtitle_window.set_original_font_size(original_font_size)
        self.subtitle_window.set_translation_font_size(translation_font_size)
        self.subtitle_window.set_original_color(original_color)
        self.subtitle_window.set_translation_color(color)
        self.subtitle_window.set_position(position)
        self.subtitle_window.set_subtitle_mode(subtitle_mode)
        
        if DEBUG_MODE:
            print(f"更新字幕样式: 原文大小={original_font_size}, 译文大小={translation_font_size}, 原文颜色={original_color}, 译文颜色={color}, 位置={position}, 模式={subtitle_mode}")
    
    def toggle_translation(self):
        """切换翻译状态"""
        if self.audio_manager.is_running:
            # 停止翻译
            self.audio_manager.stop_recording()
            self.timer.stop()
            self.start_button.setText("开始翻译")
            self.subtitle_window.hide()
            
            # 保存字幕文件
            if self.audio_manager.is_subtitle_recording():
                QMessageBox.information(self, "字幕保存", "字幕已保存到 Subtitles 目录")
        else:
            # 检查是否选择了输入设备
            if not self.input_device_combo.currentText():
                QMessageBox.warning(self, "错误", "请选择输入设备")
                return
            
            # 确定输出设备
            output_device = None
            if self.monitor_checkbox.isChecked() and self.output_device_combo.currentText():
                output_device = self.output_device_combo.currentText()
            
            # 启动翻译
            self.audio_manager.start_recording(
                self.input_device_combo.currentText(),
                output_device
            )
            
            # 设置音频延迟（如果启用）
            self.update_audio_delay_settings()
            
            # 启动定时器
            self.timer.start()
            
            # 更新按钮文本
            self.start_button.setText("停止翻译")
            
            # 显示字幕窗口
            self.subtitle_window.show()
    
    def preview_subtitles(self):
        """预览字幕效果"""
        # 更新字幕样式
        self.update_subtitle_preview()
        
        # 设置预览文本
        original_text = "This is a preview text for testing subtitle effect"
        translated_text = "这是一段预览字幕文本，用于测试字幕效果"
        
        # 在预览区域显示文本
        self.original_preview.setText(original_text)
        self.subtitle_preview.setText(translated_text)
        
        # 在字幕窗口中显示原文和译文
        self.subtitle_window.set_text(original_text, translated_text)
        
        # 确保字幕窗口可见
        if not self.subtitle_window.isVisible():
            self.subtitle_window.show()
        
        # 清除检测到的语言标签和延迟信息（因为是预览）
        self.detected_language_label.setText("")
        self.recognition_delay_label.setText("")
        self.translation_delay_label.setText("")
        
        # 5秒后自动隐藏字幕窗口
        QTimer.singleShot(5000, self.subtitle_window.hide)
    
    def update_subtitles(self):
        """更新字幕内容"""
        # 检查距离上次更新UI的时间间隔
        current_time = time.time() * 1000  # 转换为毫秒
        if current_time - self.last_update_time < self.ui_update_interval:
            # 如果更新太频繁，跳过此次更新
            return
        
        # 获取最新识别的文本
        text = self.audio_manager.get_latest_text()
        
        # 如果没有文本，不进行更新
        if not text:
            return
            
        # 记录当前显示的原文，用于比较是否变化
        current_original = self.original_preview.text()
        
        # 如果原文没有变化，只更新延迟信息，不进行完整UI更新
        if text == current_original:
            self.update_delay_info()
            return
            
        # 更新最后一次UI更新时间戳
        self.last_update_time = current_time
            
        # 更新原文预览
        self.original_preview.setText(text)
        
        # 获取当前字幕模式
        subtitle_mode = config.get("subtitle_mode", "translated")
        
        # 检查是否选择了"不翻译"
        target_language = self.target_language_combo.currentText()
        is_translation_disabled = target_language == "不翻译"
        
        # 优化：创建一个本地变量存储字幕文本，避免多次更新窗口
        original_text_for_subtitle = ""
        translation_text_for_subtitle = ""
        
        if is_translation_disabled:
            # 不翻译模式：直接使用原文，清空译文
            self.subtitle_preview.setText("")
            original_text_for_subtitle = text
        else:
            try:
                # 翻译文本
                translation = self.subtitle_manager.translate(text, target_language)
                
                # 将译文保存到音频管理器的字幕管理器中
                self.audio_manager.add_translated_text(text, translation)
                
                # 更新译文预览
                self.subtitle_preview.setText(translation)
                
                # 根据当前字幕模式准备字幕文本
                if subtitle_mode == "translated":
                    translation_text_for_subtitle = translation
                elif subtitle_mode == "original":
                    original_text_for_subtitle = text
                else:  # both
                    original_text_for_subtitle = text
                    translation_text_for_subtitle = translation
                
            except Exception as e:
                if DEBUG_MODE:
                    print(f"翻译错误: {e}")
                # 翻译出错时使用原文
                original_text_for_subtitle = text
        
        # 只在需要时更新字幕窗口，并且只更新一次
        self.subtitle_window.update_text(
            original_text=original_text_for_subtitle,
            translation_text=translation_text_for_subtitle
        )
        
        # 确保字幕窗口可见
        if not self.subtitle_window.isVisible():
            self.subtitle_window.show()
        
        # 更新语言识别标签
        self.update_detected_language_label()
        
        # 更新延迟信息
        self.update_delay_info()
    
    def update_detected_language_label(self):
        """更新检测到的语言标签"""
        language_code = self.audio_manager.get_detected_language()
        if language_code:
            language_name = self.subtitle_manager.get_language_name(language_code)
            self.detected_language_label.setText(f"[识别: {language_name}]")
            # 确保标签可见
            self.detected_language_label.setVisible(True)
            if DEBUG_MODE:
                print(f"显示检测到的语言标签: {language_code} -> {language_name}")
        else:
            self.detected_language_label.setText("")
            if DEBUG_MODE:
                print("未检测到语言，隐藏语言标签")
    
    def update_delay_info(self):
        """更新延迟信息标签"""
        # 获取识别延迟
        recognition_delay = self.audio_manager.get_recognition_delay()
        if recognition_delay > 0:
            # 格式化显示，保持统一格式
            if recognition_delay < 10000:  # 小于10秒
                self.recognition_delay_label.setText(f"[延迟: {recognition_delay}ms]")
            else:  # 大于等于10秒，显示为秒
                seconds = recognition_delay / 1000.0
                self.recognition_delay_label.setText(f"[延迟: {seconds:.1f}s]")
        else:
            self.recognition_delay_label.setText("")
        
        # 获取翻译延迟
        translation_delay = self.subtitle_manager.get_translation_delay()
        if translation_delay > 0:
            # 格式化显示，保持统一格式
            if translation_delay < 10000:  # 小于10秒
                self.translation_delay_label.setText(f"[延迟: {translation_delay}ms]")
            else:  # 大于等于10秒，显示为秒
                seconds = translation_delay / 1000.0
                self.translation_delay_label.setText(f"[延迟: {seconds:.1f}s]")
        else:
            self.translation_delay_label.setText("")
    
    def apply_saved_settings(self):
        """应用保存的设置"""
        # 加载配置并应用
        original_font_size = config.get("original_font_size", 24)
        translation_font_size = config.get("translation_font_size", 24)
        translation_color = config.get("font_color", "white")
        original_color = config.get("original_font_color", "white")
        position = config.get("position", "bottom")
        subtitle_mode = config.get("subtitle_mode", "translated")
        
        # 更新滑块值
        self.original_font_size_slider.setValue(original_font_size)
        self.translation_font_size_slider.setValue(translation_font_size)
        
        # 更新颜色按钮
        self.color_button.setStyleSheet(f"background-color: {translation_color};")
        self.original_color_button.setStyleSheet(f"background-color: {original_color};")
        
        # 更新位置下拉框
        position_map = {
            "top": "顶部",
            "middle": "中间", 
            "bottom": "底部"
        }
        self.position_combo.setCurrentText(position_map.get(position, "底部"))
        
        # 更新字幕模式下拉框
        mode_map = {
            "translated": "仅显示译文",
            "original": "仅显示原文",
            "both": "同时显示原文和译文"
        }
        self.subtitle_mode_combo.setCurrentText(mode_map.get(subtitle_mode, "仅显示译文"))
        
        # 更新字幕窗口
        self.subtitle_window.set_original_font_size(original_font_size)
        self.subtitle_window.set_translation_font_size(translation_font_size)
        self.subtitle_window.set_original_color(original_color)
        self.subtitle_window.set_translation_color(translation_color)
        self.subtitle_window.set_position(position)
        self.subtitle_window.set_subtitle_mode(subtitle_mode)
        
        # 将所有设置应用到窗口和预览
        self.update_subtitle_preview()
        
        if DEBUG_MODE:
            print(f"加载并应用设置: 原文大小={original_font_size}, 译文大小={translation_font_size}, 原文颜色={original_color}, 译文颜色={translation_color}, 位置={position}, 模式={subtitle_mode}")
    
    def on_model_changed(self, model):
        """模型改变时的处理"""
        # 检查是否与当前已加载的模型相同
        current_model = self.audio_manager.current_model_name
        if current_model == model:
            # 如果用户选择了已经加载的模型，不需要重新加载
            return
        
        # 如果当前有模型正在加载，不允许再次加载
        if self.model_loading:
            print(f"已有模型 {self.current_loading_model} 正在加载中，请等待完成")
            return
            
        # 保存设置
        config.set("whisper_model", model)
        
        # 设置模型加载状态
        self.model_loading = True
        self.model_loading_complete = False
        self.current_loading_model = model
        
        # 立即更新UI状态
        self.model_status_label.setText(f"正在切换到 {model} 模型...")
        self.model_status_label.setStyleSheet("color: blue;")
        
        # 禁用模型选择和按钮，避免用户重复操作
        self.model_combo.setEnabled(False)
        self.open_model_dir_button.setEnabled(False)
        
        # 创建异步任务加载模型
        self._load_model_async(model)
        
        # 在模型加载完成前，设置超时保护
        self._setup_timeout_protection(model)
    
    def _setup_timeout_protection(self, model_name):
        """设置模型加载的超时保护"""
        # 设置一个超时计时器，防止UI长时间被锁定
        # 只有当模型没有加载完成时才会触发解锁
        def check_timeout():
            if not self.model_loading_complete and self.current_loading_model == model_name:
                print(f"检测到模型 {model_name} 加载超时(最终保护机制)，强制解锁UI")
                self._force_unlock_ui(f"模型 {model_name} 加载超时，已解锁界面")
            else:
                print(f"模型 {model_name} 已经加载完成，无需超时解锁")
                
        # 设置超时检测 - 将超时时间延长到60秒，作为最终的保护机制
        # 正常情况下，回调应该在20秒超时检测前就执行
        QTimer.singleShot(60000, check_timeout)
    
    def _load_model_async(self, model_name):
        """异步加载模型"""
        # 在主线程中创建一个信号连接，确保可以安全地从工作线程触发UI更新
        from PySide6.QtCore import QObject, Signal, Slot
        
        # 创建一个信号对象用于线程间通信
        class CallbackHelper(QObject):
            # 定义信号
            callback_signal = Signal(str, bool)
            
            def __init__(self, parent, update_func):
                super().__init__(parent)
                self.update_func = update_func
                # 连接信号到更新函数
                self.callback_signal.connect(self._safe_update)
            
            @Slot(str, bool)
            def _safe_update(self, model_name, success):
                print(f"通过信号在主线程执行UI更新: 模型={model_name}, 成功={success}, 线程ID={threading.get_ident()}")
                try:
                    self.update_func(model_name, success)
                except Exception as e:
                    print(f"通过信号执行UI更新时出错: {str(e)}")
        
        # 创建帮助对象
        callback_helper = CallbackHelper(self, self._update_after_load)
        print(f"创建信号对象: {id(callback_helper)}")
        
        # 保存为实例变量以避免被垃圾回收
        self._current_callback_helper = callback_helper
        
        # 定义回调函数
        def load_callback(loaded_model_name, success):
            # 这个回调函数可能在工作线程中被调用
            current_thread_id = threading.get_ident()
            main_thread_id = threading.main_thread().ident
            print(f"收到模型加载回调: 模型={loaded_model_name}, 成功={success}, 当前线程ID={current_thread_id}, 主线程ID={main_thread_id}")
            
            # 始终通过信号机制触发主线程更新
            try:
                print(f"通过信号触发UI更新: helper={id(callback_helper)}")
                # 发送信号到主线程
                callback_helper.callback_signal.emit(loaded_model_name, success)
                print("信号已发送")
            except Exception as e:
                print(f"发送信号时出错: {str(e)}")
                # 紧急情况下使用QTimer尝试更新UI
                try:
                    print("使用QTimer备用方案")
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: self._force_unlock_ui(f"信号发送失败，使用备用更新: {str(e)}"))
                except Exception as timer_error:
                    print(f"QTimer备用方案也失败: {str(timer_error)}")
        
        # 创建异步线程加载模型
        def load_thread_func():
            try:
                print(f"开始加载模型: {model_name}, 线程ID={threading.get_ident()}")
                
                # 加载模型，传入回调函数
                result = self.audio_manager.load_model(model_name, load_callback)
                
                print(f"模型加载线程执行完成，结果: {result}, 线程ID={threading.get_ident()}")
                
                # 设置一个备用检查，以防回调失败
                def check_callback_timeout():
                    if self.model_loading and self.current_loading_model == model_name:
                        print(f"警告: 回调可能没有正确执行，手动触发UI更新")
                        # 直接发送信号
                        try:
                            callback_helper.callback_signal.emit(model_name, result)
                        except Exception as e:
                            print(f"备用触发信号失败: {str(e)}")
                            # 最后的备用方案
                            QTimer.singleShot(0, lambda: self._force_unlock_ui("回调超时，强制解锁UI"))
                
                # 设置5秒的备用检查
                QTimer.singleShot(5000, check_callback_timeout)
                
            except Exception as e:
                print(f"模型加载线程出错: {str(e)}")
                # 确保UI在任何情况下都会被解锁
                QTimer.singleShot(0, lambda: self._force_unlock_ui(f"加载模型 {model_name} 出错: {str(e)}"))
        
        # 启动线程
        print(f"启动模型加载线程, 主线程ID={threading.get_ident()}")
        loading_thread = threading.Thread(target=load_thread_func)
        loading_thread.daemon = True
        loading_thread.start()
    
    def _run_in_main_thread(self, model_name, success):
        """确保在主线程中执行UI更新"""
        # 这个方法应该仅用于直接从非主线程调用的情况
        # 我们修改了audio_manager.py，所以通常不需要这个方法了
        # 但保留它以防万一
        print(f"在主线程中执行UI更新: 模型={model_name}, 成功={success}")
        # 调用UI更新方法
        self._update_after_load(model_name, success)
    
    @Slot(str, bool)
    def _update_after_load(self, model_name, success):
        """模型加载完成后更新UI"""
        current_thread_id = threading.get_ident()
        main_thread_id = threading.main_thread().ident
        print(f"执行UI更新: 模型={model_name}, 成功={success}, 当前线程ID={current_thread_id}, 是主线程={current_thread_id == main_thread_id}")
        
        # 此方法应该只在主线程中调用
        if current_thread_id != main_thread_id:
            print("严重错误: 在非主线程中调用了_update_after_load")
            # 发送到主线程，不直接返回，继续尝试处理
            QTimer.singleShot(0, lambda: self._update_after_load(model_name, success))
        
        try:
            # 检查状态，如果已经完成则跳过更新
            if not self.model_loading:
                print(f"警告: 模型已不在加载状态，跳过更新 (model_loading={self.model_loading})")
                return
            
            print(f"UI更新前状态: model_loading={self.model_loading}, complete={self.model_loading_complete}, 模型={self.current_loading_model}")
            
            # 立即更新UI状态
            self.model_combo.setEnabled(True)
            self.open_model_dir_button.setEnabled(True)
            
            # 标记加载完成
            self.model_loading_complete = True
            self.model_loading = False
            self.current_loading_model = None if not success else model_name
            
            # 确保立即处理UI事件
            QApplication.processEvents()
            
            # 根据加载结果更新UI
            if success:
                # 获取实际加载的模型名称
                actual_model_name = self.audio_manager.current_model_name
                print(f"加载成功，实际模型={actual_model_name}")
                
                # 更新标签和样式
                if actual_model_name and actual_model_name != model_name:
                    self.model_status_label.setText(f"模型 {model_name} 已降级到 {actual_model_name}")
                    self.model_status_label.setStyleSheet("color: orange;")
                    # 更新下拉框选择
                    self.model_combo.blockSignals(True)
                    self.model_combo.setCurrentText(actual_model_name)
                    self.model_combo.blockSignals(False)
                    # 显示警告
                    QMessageBox.warning(self, "模型降级", 
                                    f"模型 {model_name} 已降级为 {actual_model_name}")
                else:
                    self.model_status_label.setText(f"模型 {model_name} 已成功加载")
                    self.model_status_label.setStyleSheet("color: green;")
            else:
                # 加载失败
                self.model_status_label.setText(f"模型 {model_name} 加载失败")
                self.model_status_label.setStyleSheet("color: red;")
                QMessageBox.warning(self, "模型加载失败", f"加载模型 {model_name} 失败")
            
            # 更新配置
            if success and self.audio_manager.current_model_name:
                config.set("whisper_model", self.audio_manager.current_model_name)
            
            # 再次确保UI更新
            QApplication.processEvents()
            
            print(f"UI更新完成: model_loading={self.model_loading}, complete={self.model_loading_complete}, UI状态={self.model_status_label.text()}")
        
        except Exception as e:
            print(f"UI更新过程中出错: {str(e)}")
            # 确保UI状态恢复
            self._force_unlock_ui(f"UI更新出错: {str(e)}")
    
    def on_gpu_changed(self, state):
        """GPU设置改变时的处理"""
        use_gpu = state == Qt.CheckState.Checked.value
        config.set("use_gpu", use_gpu)
        config.set("device", "cuda" if use_gpu else "cpu")
    
    def on_window_width_changed(self, width):
        """窗口宽度设置变更时的处理"""
        # 保存设置到配置
        config.set("window_width", width)
        
        if DEBUG_MODE:
            print(f"主窗口: 设置字幕窗口宽度为 {width}px")
        
        # 更新字幕窗口尺寸
        if hasattr(self, 'subtitle_window'):
            # 强制关闭再显示字幕窗口，确保新设置生效
            was_visible = self.subtitle_window.isVisible()
            if was_visible:
                self.subtitle_window.hide()
            
            # 设置宽度
            self.subtitle_window.on_window_width_changed(width)
            
            # 如果之前是可见的，则重新显示
            if was_visible:
                self.subtitle_window.show()
            
        if DEBUG_MODE:
            print(f"主窗口: 字幕窗口宽度设置为 {width}px")

    def on_window_height_changed(self, height):
        """窗口高度设置变更时的处理"""
        # 保存设置到配置
        config.set("window_height", height)
        
        if DEBUG_MODE:
            print(f"主窗口: 设置字幕窗口高度为 {height}px")
        
        # 更新字幕窗口尺寸
        if hasattr(self, 'subtitle_window'):
            # 强制关闭再显示字幕窗口，确保新设置生效
            was_visible = self.subtitle_window.isVisible()
            if was_visible:
                self.subtitle_window.hide()
            
            # 设置高度
            self.subtitle_window.on_window_height_changed(height)
            
            # 如果之前是可见的，则重新显示
            if was_visible:
                self.subtitle_window.show()
            
        if DEBUG_MODE:
            print(f"主窗口: 字幕窗口高度设置为 {height}px")
    
    def on_source_language_changed(self, language):
        """源语言改变时的处理"""
        # 将中文语言名称转换为语言代码
        language_map = {
            "自动检测": "auto",
            "英语": "en",
            "中文": "zh",
            "日语": "ja",
            "韩语": "ko",
            "法语": "fr",
            "德语": "de",
            "俄语": "ru",
            "西班牙语": "es"
        }
        config.set("source_language", language_map.get(language, "auto"))
        
    def on_target_language_changed(self, language):
        """目标语言改变时的处理"""
        # 将中文语言名称转换为语言代码
        language_map = {
            "不翻译": "none",  # 特殊值，表示不翻译
            "中文": "zh",
            "英语": "en",
            "日语": "ja",
            "韩语": "ko",
            "法语": "fr",
            "德语": "de",
            "俄语": "ru",
            "西班牙语": "es"
        }
        
        lang_code = language_map.get(language, "zh")
        config.set("target_language", lang_code)
        
        # 显示或隐藏翻译延迟标签
        if lang_code == "none":
            self.translation_delay_label.hide()
        else:
            self.translation_delay_label.show()
            
        if DEBUG_MODE:
            print(f"目标语言切换到: {language} (代码: {lang_code})")

    def open_model_folder(self):
        # whisper模型默认缓存目录
        model_dir = os.path.expanduser("~/.cache/whisper")
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)
        os.startfile(model_dir)

    def update_model_status(self):
        """更新模型状态显示"""
        # 如果模型正在加载中，不要覆盖状态信息
        if "正在切换" in self.model_status_label.text() or "正在加载" in self.model_status_label.text():
            return
            
        # 如果显示的是加载成功或失败信息，也不要立即覆盖
        if ("已成功加载" in self.model_status_label.text() or 
            "加载失败" in self.model_status_label.text()):
            # 仅在combo box当前模型与显示不匹配时才更新
            model_name = self.model_combo.currentText()
            if model_name not in self.model_status_label.text():
                pass  # 继续更新
            else:
                return  # 保持当前状态显示
                
        model_name = self.model_combo.currentText()
        model_dir = os.path.expanduser("~/.cache/whisper")
        found = False
        
        # 检查模型文件是否存在
        if os.path.exists(model_dir):
            for fname in os.listdir(model_dir):
                if model_name in fname:
                    found = True
                    break
        
        # 生成状态文本
        status_text = ""
        if found:
            status_text = f"模型已下载"
        else:
            status_text = f"模型未下载"
        
        # 如果有当前加载的模型，显示它
        current_model = None
        if hasattr(self.audio_manager, 'current_model_name') and self.audio_manager.current_model_name:
            current_model = self.audio_manager.current_model_name
            status_text += f" (当前使用: {current_model})"
            
            # 同步更新下拉框选择的模型与当前使用的模型
            if current_model != model_name:
                # 暂时阻断信号以避免触发 on_model_changed
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentText(current_model)
                self.model_combo.blockSignals(False)
                # 更新当前模型名称
                model_name = current_model
        
        # 设置标签文本和样式
        self.model_status_label.setText(status_text)
        
        # 根据状态设置标签颜色
        if found:
            self.model_status_label.setStyleSheet("color: green;")
        else:
            self.model_status_label.setStyleSheet("color: orange;")
        
        # 确保配置文件与当前模型同步
        if current_model and current_model != config.get("whisper_model"):
            config.set("whisper_model", current_model)
        
        # 记录日志
        if DEBUG_MODE:
            print(f"模型状态: {model_name} - {status_text}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 保存主窗口大小
        config.set("main_window_width", self.width())
        config.set("main_window_height", self.height())

    def on_subtitle_mode_changed(self, mode_text):
        """字幕模式改变时的处理"""
        mode_map = {
            "仅显示译文": "translated",
            "仅显示原文": "original",
            "同时显示原文和译文": "both"
        }
        mode = mode_map.get(mode_text, "translated")
        config.set("subtitle_mode", mode)
        
        # 更新字幕窗口模式
        self.subtitle_window.set_subtitle_mode(mode)
        
        # 更新预览区域
        self.update_subtitle_preview()
        
        if DEBUG_MODE:
            print(f"字幕模式更改为: {mode}")

    def on_input_device_changed(self, device):
        """输入设备变更时的处理"""
        config.set("input_device", device)
        
    def on_output_device_changed(self, device):
        """输出设备变更时的处理"""
        config.set("output_device", device)

    def _load_initial_model(self, model_name):
        """加载初始模型"""
        if DEBUG_MODE:
            print(f"正在加载配置的模型: {model_name}")
        
        # 禁用模型选择和按钮，避免用户重复操作
        self.model_combo.setEnabled(False)
        self.open_model_dir_button.setEnabled(False)
        
        # 使用状态标签显示加载状态
        self.model_status_label.setText(f"正在加载模型: {model_name}...")
        self.model_status_label.setStyleSheet("color: blue;")
        
        # 创建异步线程加载模型
        def load_thread_func():
            # 加载模型
            success = self.audio_manager.load_model(model_name)
            
            # 记录结果
            if success:
                if DEBUG_MODE:
                    print(f"成功加载模型: {model_name}")
                # 在主线程中显示结果
                QTimer.singleShot(0, lambda: self._update_after_load(model_name, success))
            else:
                if DEBUG_MODE:
                    print(f"加载模型失败: {model_name}")
                # 在主线程中显示结果
                QTimer.singleShot(0, lambda: self._update_after_load(model_name, success))
        
        # 启动线程
        loading_thread = threading.Thread(target=load_thread_func)
        loading_thread.daemon = True
        loading_thread.start()

    def _force_unlock_ui(self, error_message=None):
        """强制解锁UI，无论发生什么情况"""
        # 记录解锁操作
        print(f"强制解锁UI: {error_message or '无错误消息'}")
        
        try:
            # 重新启用所有控件
            self.model_combo.setEnabled(True)
            self.open_model_dir_button.setEnabled(True)
            
            # 强制应用控件状态
            QApplication.processEvents()
            
            # 重置模型加载状态
            self.model_loading = False
            self.model_loading_complete = True  # 标记为完成，避免超时检测再次触发
            
            # 如果提供了错误消息，则显示错误状态
            if error_message:
                self.model_status_label.setText(error_message)
                self.model_status_label.setStyleSheet("color: red;")
                print(f"UI强制解锁: {error_message}")
            else:
                # 更新正常状态
                current_model = self.audio_manager.current_model_name or config.get("whisper_model", "base")
                self.model_status_label.setText(f"当前模型: {current_model}")
                self.model_status_label.setStyleSheet("color: green;") 
            
            # 确保下拉框选择与当前模型一致
            if self.audio_manager.current_model_name:
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentText(self.audio_manager.current_model_name)
                self.model_combo.blockSignals(False)
            
            # 再次强制更新UI
            QApplication.processEvents()
            
            print(f"UI解锁完成，新状态: 按钮可用={self.model_combo.isEnabled()}, 状态文本='{self.model_status_label.text()}'")
        
        except Exception as e:
            print(f"强制解锁UI时出错: {str(e)}")
            # 最后的尝试 - 无条件启用所有控件
            try:
                self.model_combo.setEnabled(True)
                self.open_model_dir_button.setEnabled(True)
                self.model_status_label.setText("UI解锁失败，请重启应用")
                self.model_status_label.setStyleSheet("color: red;")
                QApplication.processEvents()
            except:
                pass 
                pass 

    def on_show_audio_stats_changed(self, state):
        """音频数据统计选项改变时的处理"""
        show_stats = state == Qt.CheckState.Checked.value
        config.set("show_audio_stats", show_stats)
        
        if DEBUG_MODE:
            print(f"音频数据统计选项更改为: {show_stats}")
