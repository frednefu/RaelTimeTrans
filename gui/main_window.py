from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QComboBox, QLabel, QSlider, QColorDialog,
                            QGroupBox, QCheckBox, QSpinBox, QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, QTimer
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
        self.timer.setInterval(100)  # 100ms
        self.timer.timeout.connect(self.update_subtitles)
        
        # 创建初始化标志，避免重复初始化模型
        self.model_initialized = False
        
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
        
        device_layout.addLayout(input_layout)
        device_layout.addLayout(output_layout)
        device_layout.addWidget(self.monitor_checkbox)
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
        
        font_size_layout = QHBoxLayout()
        font_size_label = QLabel("字体大小:")
        self.font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_size_slider.setRange(10, 50)
        self.font_size_slider.setValue(24)
        self.font_size_slider.valueChanged.connect(self.update_subtitle_preview)
        font_size_layout.addWidget(font_size_label)
        font_size_layout.addWidget(self.font_size_slider)
        
        color_layout = QHBoxLayout()
        color_label = QLabel("字体颜色:")
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
        self.window_width_spin.setRange(200, 1920)
        self.window_width_spin.setValue(config.get("window_width", 800))
        self.window_width_spin.valueChanged.connect(self.on_window_width_changed)
        window_size_layout.addWidget(self.window_width_spin)

        window_size_layout.addWidget(QLabel("窗口高度:"))
        self.window_height_spin = QSpinBox()
        self.window_height_spin.setRange(50, 600)
        self.window_height_spin.setValue(config.get("window_height", 200))
        self.window_height_spin.valueChanged.connect(self.on_window_height_changed)
        window_size_layout.addWidget(self.window_height_spin)

        subtitle_layout.addLayout(font_size_layout)
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
        self.audio_manager.stop_recording()
        
        # 关闭字幕窗口
        self.subtitle_window.close()
        
        # 清除检测到的语言标签和延迟信息
        self.detected_language_label.setText("")
        self.recognition_delay_label.setText("")
        self.translation_delay_label.setText("")
        
        # 调用父类方法关闭窗口
        super().closeEvent(event)
        
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
        
        # 连接设置变更事件
        self.input_device_combo.currentTextChanged.connect(self.on_input_device_changed)
        self.output_device_combo.currentTextChanged.connect(self.on_output_device_changed)
        self.monitor_checkbox.stateChanged.connect(self.on_monitor_changed)
    
    def select_color(self):
        """打开颜色选择对话框"""
        color = QColorDialog.getColor()
        if color.isValid():
            self.color_button.setStyleSheet(f"background-color: {color.name()};")
            # 更新字幕预览
            self.update_subtitle_preview()
    
    def update_subtitle_preview(self):
        """更新字幕预览和字幕窗口的样式"""
        # 获取当前设置的样式
        font_size = self.font_size_slider.value()
        color_style = self.color_button.styleSheet()
        color = color_style.split(":")[-1].strip("; ")
        
        # 位置映射
        position_map = {
            "顶部": "top",
            "中间": "middle",
            "底部": "bottom"
        }
        position = position_map.get(self.position_combo.currentText(), "bottom")
        
        # 保存设置到配置
        config.set("font_size", font_size)
        config.set("font_color", color)
        config.set("position", position)
        
        # 更新预览区域样式
        self.original_preview.setFont(QFont("Arial", font_size))
        self.original_preview.setStyleSheet(f"color: {color}; background-color: black; padding: 5px;")
        
        self.subtitle_preview.setFont(QFont("Arial", font_size))
        self.subtitle_preview.setStyleSheet(f"color: {color}; background-color: black; padding: 5px;")
        
        # 根据当前模式更新预览区域的可见性
        subtitle_mode = config.get("subtitle_mode", "translated")
        
        # 清空预览区域布局
        preview_layout = self.findChild(QGroupBox, "字幕预览").layout()
        while preview_layout.count():
            item = preview_layout.takeAt(0)
            if item.widget():
                preview_layout.removeWidget(item.widget())
                item.widget().hide()
        
        # 根据字幕模式添加相应的预览标签
        if subtitle_mode == "original" or subtitle_mode == "both":
            preview_layout.addWidget(self.original_preview)
            self.original_preview.show()
        if subtitle_mode == "translated" or subtitle_mode == "both":
            preview_layout.addWidget(self.subtitle_preview)
            self.subtitle_preview.show()
        
        # 更新字幕窗口样式和模式
        self.subtitle_window.set_font_size(font_size)
        self.subtitle_window.set_color(color)
        self.subtitle_window.set_position(position)
        
        if DEBUG_MODE:
            print(f"更新字幕样式: 大小={font_size}, 颜色={color}, 位置={position}, 模式={subtitle_mode}")
    
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
        self.subtitle_window.show()
        
        # 清除检测到的语言标签和延迟信息（因为是预览）
        self.detected_language_label.setText("")
        self.recognition_delay_label.setText("")
        self.translation_delay_label.setText("")
        
        # 5秒后自动隐藏字幕窗口
        QTimer.singleShot(5000, self.subtitle_window.hide)
    
    def update_subtitles(self):
        """更新字幕内容"""
        # 获取最新识别的文本
        text = self.audio_manager.get_latest_text()
        
        # 如果没有文本，或者文本和上次相同，则不更新
        if not text:
            return
            
        # 记录当前显示的原文和译文，用于比较是否变化
        current_original = self.original_preview.text()
        
        # 如果原文没有变化，可能不需要更新
        if text == current_original:
            # 仍然更新延迟信息
            self.update_detected_language_label()
            self.update_delay_info()
            return
            
        # 更新原文预览
        self.original_preview.setText(text)
        
        # 检查是否选择了"不翻译"
        target_language = self.target_language_combo.currentText()
        if target_language == "不翻译":
            # 直接使用原文，不进行翻译
            # 更新字幕窗口
            subtitle_mode = config.get("subtitle_mode", "translated")
            if subtitle_mode in ["translated", "both"]:
                self.subtitle_window.update_text(text)
            elif subtitle_mode == "original":
                self.subtitle_window.update_text(text)
                
            # 清空译文预览
            self.subtitle_preview.setText("")
        else:
            try:
                # 翻译文本
                translation = self.subtitle_manager.translate(text, target_language)
                
                # 将译文保存到音频管理器的字幕管理器中
                self.audio_manager.add_translated_text(text, translation)
                
                # 更新译文预览
                self.subtitle_preview.setText(translation)
                
                # 更新字幕窗口
                subtitle_mode = config.get("subtitle_mode", "translated")
                if subtitle_mode == "translated":
                    self.subtitle_window.update_text(translation)
                elif subtitle_mode == "original":
                    self.subtitle_window.update_text(text)
                else:  # both
                    combined_text = f"{text}\n{translation}"
                    self.subtitle_window.update_text(combined_text)
                
            except Exception as e:
                if DEBUG_MODE:
                    print(f"翻译错误: {e}")
        
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
        else:
            self.detected_language_label.setText("")
    
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
        font_size = config.get("font_size", 24)
        font_color = config.get("font_color", "white")
        position = config.get("position", "bottom")
        subtitle_mode = config.get("subtitle_mode", "translated")
        
        # 更新滑块值
        self.font_size_slider.setValue(font_size)
        
        # 更新颜色按钮
        self.color_button.setStyleSheet(f"background-color: {font_color};")
        
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
        self.subtitle_window.set_font_size(font_size)
        self.subtitle_window.set_color(font_color)
        self.subtitle_window.set_position(position)
        self.subtitle_window.set_subtitle_mode(subtitle_mode)
        
        # 将所有设置应用到窗口和预览
        self.update_subtitle_preview()
        
        if DEBUG_MODE:
            print(f"加载并应用设置: 大小={font_size}, 颜色={font_color}, 位置={position}, 模式={subtitle_mode}")
    
    def on_model_changed(self, model):
        """模型改变时的处理"""
        # 保存设置
        config.set("whisper_model", model)
        
        # 更新状态显示
        self.update_model_status()
        
        # 判断是否需要重新加载模型
        if self.audio_manager.current_model_name != model:
            # 创建状态标签显示加载中
            self.model_status_label.setText(f"正在切换到 {model} 模型...")
            self.model_status_label.setStyleSheet("color: blue;")
            
            # 禁用模型选择和按钮，避免用户重复操作
            self.model_combo.setEnabled(False)
            self.open_model_dir_button.setEnabled(False)
            
            # 创建异步任务加载模型，并使用QTimer确保UI不被阻塞
            QTimer.singleShot(100, lambda: self._load_model_async(model))
    
    def _load_model_async(self, model_name):
        """异步加载模型"""
        # 创建异步线程加载模型
        def load_thread_func():
            # 加载模型
            success = self.audio_manager.load_model(model_name)
            
            # 在主线程中显示结果
            QTimer.singleShot(0, lambda: self._update_after_load(model_name, success))
        
        # 启动线程
        loading_thread = threading.Thread(target=load_thread_func)
        loading_thread.daemon = True
        loading_thread.start()
    
    def _update_after_load(self, model_name, success):
        """模型加载完成后更新UI"""
        # 重新启用控件
        self.model_combo.setEnabled(True)
        self.open_model_dir_button.setEnabled(True)
        
        # 显示加载结果
        if success:
            QMessageBox.information(self, "模型加载成功", f"模型 {model_name} 已成功加载。")
        else:
            QMessageBox.warning(self, "模型加载失败", 
                              f"加载模型 {model_name} 失败。\n\n将使用当前可用模型: {self.audio_manager.current_model_name or '无'}\n\n请检查网络连接或模型文件。")
        
        # 更新模型状态标签
        self.update_model_status()
    
    def on_gpu_changed(self, state):
        """GPU设置改变时的处理"""
        use_gpu = state == Qt.CheckState.Checked.value
        config.set("use_gpu", use_gpu)
        config.set("device", "cuda" if use_gpu else "cpu")
    
    def on_window_width_changed(self, width):
        config.set("window_width", width)
        self.subtitle_window.on_window_width_changed(width)

    def on_window_height_changed(self, height):
        config.set("window_height", height)
        self.subtitle_window.resize(self.subtitle_window.width(), height)
    
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
        
    def on_monitor_changed(self, state):
        """监听选项变更时的处理"""
        enabled = state == Qt.CheckState.Checked.value
        config.set("monitor_enabled", enabled)

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