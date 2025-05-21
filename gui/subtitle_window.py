from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizeGrip, QMainWindow
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QFont, QColor, QFontMetrics
from config import config
from PySide6.QtWidgets import QApplication

# 调试开关，控制是否输出调试信息
DEBUG_MODE = False

class SubtitleWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 设置窗口无边框和始终置顶，但使用Tool类型避免在任务栏显示
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        
        # 使用半透明背景而非完全透明
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 设置半透明黑色背景
        central_widget.setStyleSheet("background-color: rgba(0, 0, 0, 150);")
        
        # 禁用最小尺寸限制
        central_widget.setMinimumSize(1, 1)
        self.setMinimumSize(1, 1)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        # 减小布局边距，避免在小尺寸时没有显示空间
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        
        # 从配置获取字体类型
        original_font_family = config.get("original_font_family", "Arial")
        translation_font_family = config.get("translation_font_family", "黑体")
        
        # 创建两个标签，分别用于显示原文和译文
        self.original_label = QLabel()
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_label.setWordWrap(True)
        
        # 设置初始字体
        original_font = QFont(original_font_family, 24)
        self.original_label.setFont(original_font)
        # 计算最小高度
        metrics = QFontMetrics(original_font)
        line_height = metrics.height()
        self.original_label.setMinimumHeight(line_height + 20)
        self.original_label.setStyleSheet("color: white; background-color: transparent; padding: 12px;")
        
        self.translation_label = QLabel()
        self.translation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.translation_label.setWordWrap(True)
        
        # 设置初始字体
        translation_font = QFont(translation_font_family, 24)
        self.translation_label.setFont(translation_font)
        # 计算最小高度
        metrics = QFontMetrics(translation_font)
        line_height = metrics.height()
        self.translation_label.setMinimumHeight(line_height + 20)
        self.translation_label.setStyleSheet("color: white; background-color: transparent; padding: 12px;")
        
        # 添加标签到布局
        layout.addWidget(self.original_label)
        layout.addWidget(self.translation_label)
        
        # 初始化属性
        self.window_width = 800  # 默认窗口宽度
        self.window_height = 200  # 默认窗口高度
        self.position = "bottom"  # 默认位置
        self.dragging = False     # 拖动状态
        
        # 添加大小调整手柄
        self.size_grip = QSizeGrip(self)
        self.size_grip.setVisible(True)
        
        # 设置字幕模式（默认仅显示译文）
        self.subtitle_mode = "translated"
        
        # 更新标签的可见性
        self.update_labels_visibility()
        
        # 从配置加载设置
        self.apply_saved_settings()
    
    def apply_saved_settings(self):
        """应用保存的设置"""
        from config import config
        
        # 字体大小和字体类型
        original_font_size = config.get("original_font_size", 24)
        translation_font_size = config.get("translation_font_size", 24)
        original_font_family = config.get("original_font_family", "Arial")
        translation_font_family = config.get("translation_font_family", "黑体")
        
        # 创建完整字体对象
        original_font = QFont(original_font_family, original_font_size)
        translation_font = QFont(translation_font_family, translation_font_size)
        
        # 应用字体
        self.original_label.setFont(original_font)
        self.translation_label.setFont(translation_font)
        
        # 字体颜色
        translation_color = config.get("font_color", "white")
        original_color = config.get("original_font_color", "white")
        self.set_original_color(original_color)
        self.set_translation_color(translation_color)
        
        # 位置
        self.position = config.get("position", "bottom")
        
        # 窗口大小 - 从配置加载，但暂不应用(会在show事件中应用)
        self.window_width = config.get("window_width", 800)
        self.window_height = config.get("window_height", 200)
        
        # 字幕模式
        subtitle_mode = config.get("subtitle_mode", "translated")
        self.set_subtitle_mode(subtitle_mode)
        
        # 确保样式被完全应用
        self.update_style()
        
        # 调整文本标签高度
        self.adjustLabelHeights()
    
    def set_original_font_size(self, size):
        """设置原文字体大小"""
        # 从配置获取字体类型
        from config import config
        font_family = config.get("original_font_family", "Arial")
        
        # 创建新字体，保持字体类型不变
        font = QFont(font_family, size)
        self.original_label.setFont(font)
        
        # 根据字体大小调整标签高度适应文本
        metrics = QFontMetrics(font)
        line_height = metrics.height()
        self.original_label.setMinimumHeight(line_height + 20)  # 添加额外的上下填充
        
        # 保存设置
        config.set("original_font_size", size)
    
    def set_translation_font_size(self, size):
        """设置译文字体大小"""
        # 从配置获取字体类型
        from config import config
        font_family = config.get("translation_font_family", "黑体")
        
        # 创建新字体，保持字体类型不变
        font = QFont(font_family, size) 
        self.translation_label.setFont(font)
        
        # 根据字体大小调整标签高度适应文本
        metrics = QFontMetrics(font)
        line_height = metrics.height()
        self.translation_label.setMinimumHeight(line_height + 20)  # 添加额外的上下填充
        
        # 保存设置
        config.set("translation_font_size", size)
    
    def set_font_size(self, size):
        """设置字体大小（兼容旧版本）"""
        # 同时设置原文和译文字体大小
        self.set_original_font_size(size)
        self.set_translation_font_size(size)
    
    def set_original_color(self, color):
        """设置原文颜色"""
        self.original_color = color  # 保存为实例属性
        self.original_label.setStyleSheet(f"color: {color}; background-color: transparent;")
    
    def set_translation_color(self, color):
        """设置译文颜色"""
        self.translation_color = color  # 保存为实例属性
        self.translation_label.setStyleSheet(f"color: {color}; background-color: transparent;")
    
    def set_position(self, position):
        """设置字幕位置"""
        # 获取屏幕几何信息
        screen = QApplication.primaryScreen().geometry()
        
        # 窗口大小
        window_width = self.width()
        window_height = self.height()
        
        # 根据位置计算窗口坐标
        if position == "top":
            x = (screen.width() - window_width) // 2
            y = 50  # 距离顶部50像素
        elif position == "middle":
            x = (screen.width() - window_width) // 2
            y = (screen.height() - window_height) // 2
        else:  # bottom
            x = (screen.width() - window_width) // 2
            y = screen.height() - window_height - 100  # 距离底部100像素
        
        # 移动窗口
        self.move(x, y)
    
    def set_subtitle_mode(self, mode):
        """设置字幕模式"""
        self.subtitle_mode = mode
        # 更新标签可见性
        self.update_labels_visibility()
    
    def update_labels_visibility(self):
        """根据字幕模式更新标签的可见性"""
        if self.subtitle_mode == "translated":
            self.original_label.hide()
            self.translation_label.show()
        elif self.subtitle_mode == "original":
            self.original_label.show()
            self.translation_label.hide()
        else:  # both
            self.original_label.show()
            self.translation_label.show()
    
    def update_text(self, original_text=None, translation_text=None):
        """更新字幕文本"""
        # 检查是否需要更新
        needs_update = False
        
        # 获取当前字幕模式
        subtitle_mode = self.subtitle_mode
        
        # 检查是否是单个参数调用（兼容旧版本接口）
        if translation_text is None and isinstance(original_text, str):
            # 单参数调用，将原文作为译文显示
            if DEBUG_MODE:
                print(f"单参数调用 update_text: {original_text}")
            
            # 检查原文是否发生变化
            if original_text != self.original_label.text():
                needs_update = True
                self.original_label.setText(original_text)
            
            # 在翻译模式下，检查译文是否需要更新
            if subtitle_mode == "translated" and original_text != self.translation_label.text():
                needs_update = True
                self.translation_label.setText(original_text)
        else:
            # 双参数调用，分别设置原文和译文
            if DEBUG_MODE:
                print(f"双参数调用 update_text: 原文={original_text}, 译文={translation_text}")
            
            # 设置原文（如果提供）
            if original_text is not None and original_text != self.original_label.text():
                needs_update = True
                self.original_label.setText(original_text)
            
            # 设置译文（如果提供）
            if translation_text is not None and translation_text != self.translation_label.text():
                needs_update = True
                self.translation_label.setText(translation_text)
            
            # 特殊处理：如果在翻译模式但没有译文，则使用原文代替
            if (not translation_text and subtitle_mode == "translated" and 
                original_text and original_text != self.translation_label.text()):
                needs_update = True
                self.translation_label.setText(original_text)
        
        # 只有在文本发生变化时才调整标签高度和更新UI
        if needs_update:
            # 确保标签高度正确
            self.adjustLabelHeights()
            
            # 确保窗口显示
            if not self.isVisible():
                self.show()
            
            # 更新标签的可见性
            self.update_labels_visibility()
    
    def set_text(self, original_text="", translation_text=""):
        """设置预览文本"""
        # 设置标签文本
        if original_text is not None:
            self.original_label.setText(original_text)
        
        if translation_text is not None:
            self.translation_label.setText(translation_text)
        
        # 确保标签高度正确
        self.adjustLabelHeights()
        
        # 更新标签可见性
        self.update_labels_visibility()
        
        # 确保窗口可见
        if not self.isVisible():
            self.show()
            
        # 确保窗口尺寸正确
        self.resize(self.window_width, self.window_height)
    
    def on_window_width_changed(self, width):
        """字幕窗口宽度设置变更"""
        # 保存宽度到实例变量
        self.window_width = width
        
        # 保存设置到配置
        from config import config
        config.set("window_width", width)
        # 强制同步到文件
        config.sync_to_file()
        
        # 直接应用新宽度(保持当前高度)
        current_height = self.height()
        self.resize(width, current_height)
        
        if DEBUG_MODE:
            print(f"字幕窗口宽度设置: {width}px")
            
    def on_window_height_changed(self, height):
        """字幕窗口高度设置变更"""
        # 保存高度到实例变量
        self.window_height = height
        
        # 保存设置到配置
        from config import config
        config.set("window_height", height)
        # 强制同步到文件
        config.sync_to_file()
        
        # 直接应用新高度(保持当前宽度)
        current_width = self.width()
        self.resize(current_width, height)
        
        if DEBUG_MODE:
            print(f"字幕窗口高度设置: {height}px")

    def resize(self, *args, **kwargs):
        """重写resize方法以确保尺寸变更时更新内部记录的尺寸并强制应用尺寸"""
        if DEBUG_MODE:
            if len(args) >= 2:
                print(f"字幕窗口resize调用: 请求尺寸 {args[0]}x{args[1]}")
            else:
                print(f"字幕窗口resize调用: 参数 {args}")
        
        # 调用原始的resize方法
        super().resize(*args, **kwargs)
        
        # 强制立即重绘并处理事件，确保尺寸变更生效
        self.repaint()
        QApplication.processEvents()
        
        # 如果是两个参数形式的调用
        if len(args) >= 2:
            width, height = args[0], args[1]
            self.window_width = width
            self.window_height = height
            
            # 验证尺寸是否正确应用，如果不是，再次尝试
            actual_width, actual_height = self.width(), self.height()
            if actual_width != width or actual_height != height:
                if DEBUG_MODE:
                    print(f"字幕窗口尺寸不匹配，再次尝试: 期望 {width}x{height}, 实际 {actual_width}x{actual_height}")
                # 使用setFixedSize强制设置精确尺寸
                self.setFixedSize(width, height)
                # 应用后恢复可调整大小
                QApplication.processEvents()
                self.setMinimumSize(1, 1)
                self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX
        else:
            # 如果不是直接提供宽高的调用，则从当前尺寸更新
            self.window_width = self.width()
            self.window_height = self.height()
        
        if DEBUG_MODE:
            print(f"字幕窗口resize完成: 内部记录尺寸 {self.window_width}x{self.window_height}, 实际尺寸 {self.width()}x{self.height()}")

    def show(self):
        """显示窗口前先更新位置和尺寸"""
        # 确保窗口可见
        self.setVisible(True)
        
        # 应用保存的窗口尺寸
        self.resize(self.window_width, self.window_height)
        
        # 更新位置
        from config import config
        position = config.get("position", "bottom")
        self.set_position(position)
        
        # 确保窗口在顶层
        self.raise_()
        self.activateWindow()
        
        # 调用父类方法
        super().show()
        
        if DEBUG_MODE:
            print(f"字幕窗口显示: 尺寸 {self.window_width}x{self.window_height}, 位置 {position}")

    def update_layout(self):
        """根据字幕模式更新布局"""
        # 清空当前布局
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                self.layout().removeWidget(item.widget())
        
        # 确保所有标签都可见
        self.original_label.show()
        self.translation_label.show()
        
        # 根据字幕模式添加标签
        if self.subtitle_mode == "original":
            self.layout().addWidget(self.original_label)
            self.translation_label.hide()
        elif self.subtitle_mode == "translated":
            self.layout().addWidget(self.translation_label)
            self.original_label.hide()
        elif self.subtitle_mode == "both":
            self.layout().addWidget(self.original_label)
            self.layout().addWidget(self.translation_label)
        
        # 添加大小调整手柄
        self.layout().addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        
        if DEBUG_MODE:
            print(f"更新字幕布局: 模式={self.subtitle_mode}, 原文标签可见={self.original_label.isVisible()}, 译文标签可见={self.translation_label.isVisible()}")
        
        # 使用配置中的固定大小
        self.resize(self.window_width, self.window_height)
        
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if event.buttons() == Qt.MouseButton.LeftButton and self.dragging:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
            
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            event.accept()
            
    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)
        
        # 不再每次保存窗口大小，而是仅在用户通过UI明确设置时才保存
        # 防止宽度自动变化并频繁修改配置文件
        
        # 保证窗口大小变化时字体等样式同步更新
        self.update_style()
        
        if DEBUG_MODE:
            print(f"字幕窗口大小变化: {self.width()}x{self.height()}")
            
    def set_color(self, color):
        """设置字体颜色"""
        self.original_label.setStyleSheet(f"color: {color}; background-color: transparent;")
        self.translation_label.setStyleSheet(f"color: {color}; background-color: transparent;")
        self.update_style()
        if DEBUG_MODE:
            print(f"字幕颜色变化: {color}")
    
    def update_style(self):
        """更新字幕样式"""
        # 从配置获取颜色值和字体类型
        from config import config
        original_color = config.get("original_font_color", "white")
        translation_color = config.get("font_color", "white")
        original_font_family = config.get("original_font_family", "Arial")
        translation_font_family = config.get("translation_font_family", "黑体")
        
        # 获取当前字体大小
        original_font_size = self.original_label.font().pointSize()
        translation_font_size = self.translation_label.font().pointSize()
        
        # 创建完整字体对象
        original_font = QFont(original_font_family, original_font_size)
        translation_font = QFont(translation_font_family, translation_font_size)
        
        # 计算合适的填充值基于字体大小
        original_padding = max(10, original_font_size // 2)
        translation_padding = max(10, translation_font_size // 2)
        
        # 对原文标签应用样式
        self.original_label.setFont(original_font)
        self.original_label.setStyleSheet(f"""
            color: {original_color};
            background-color: transparent;
            padding: {original_padding}px;
            border-radius: 5px;
        """)
        
        # 对译文标签应用样式
        self.translation_label.setFont(translation_font)
        self.translation_label.setStyleSheet(f"""
            color: {translation_color};
            background-color: transparent;
            padding: {translation_padding}px;
            border-radius: 5px;
        """)
        
        # 确保位置更新
        self.update_position()
        
        if DEBUG_MODE:
            print(f"字幕窗口样式更新: 原文字体={original_font_family}, 译文字体={translation_font_family}, 原文颜色={original_color}, 译文颜色={translation_color}, 原文填充={original_padding}px, 译文填充={translation_padding}px")
    
    def update_position(self):
        """根据设置的位置在屏幕上定位窗口"""
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().geometry()
        screen_width = screen.width()
        screen_height = screen.height()
        
        # 使用当前实际窗口大小而不是保存的值，确保准确定位
        window_width = self.width()
        window_height = self.height()
        
        if DEBUG_MODE:
            print(f"字幕窗口定位: 当前尺寸 {window_width}x{window_height}, 屏幕 {screen_width}x{screen_height}")
        
        # 根据设置的位置计算窗口位置
        if self.position == "top":
            x = (screen_width - window_width) // 2
            y = 50  # 距离顶部50像素
        elif self.position == "middle":
            x = (screen_width - window_width) // 2
            y = (screen_height - window_height) // 2
        else:  # bottom
            x = (screen_width - window_width) // 2
            y = screen_height - window_height - 100  # 距离底部100像素
            # 如果窗口高度很小，确保不会超出屏幕底部
            if y < 0 or y >= screen_height:
                y = screen_height - window_height - 10
        
        # 确保窗口位置在屏幕内
        x = max(0, min(x, screen_width - window_width))
        y = max(0, min(y, screen_height - window_height))
        
        # 移动窗口
        self.move(x, y)
        
        if DEBUG_MODE:
            print(f"字幕窗口定位: 位置={self.position}, 坐标=({x},{y})")
    
    def showEvent(self, event):
        """窗口显示时的事件处理"""
        # 首先调用父类方法
        super().showEvent(event)
        
        if DEBUG_MODE:
            print(f"字幕窗口showEvent: 显示前尺寸 {self.width()}x{self.height()}, 目标尺寸 {self.window_width}x{self.window_height}")
        
        # 确保标签高度正确
        self.adjustLabelHeights()
        
        # 应用保存的窗口尺寸，使用setFixedSize确保精确尺寸
        self.setFixedSize(self.window_width, self.window_height)
        
        # 应用后恢复可调整大小
        QApplication.processEvents()
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX
        
        # 更新位置
        self.update_position()
        
        if DEBUG_MODE:
            print(f"字幕窗口showEvent完成: 显示后尺寸 {self.width()}x{self.height()}")
    
    def keyPressEvent(self, event):
        """按下ESC键时关闭窗口"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def close(self):
        """重写关闭事件，确保设置保存"""
        # 保存当前的窗口尺寸
        from config import config
        config.set("window_width", self.window_width)
        config.set("window_height", self.window_height)
        # 强制同步到文件
        config.sync_to_file()
        
        # 调用父类方法关闭窗口
        super().close()

    def adjustLabelHeights(self):
        """根据当前字体调整标签高度"""
        # 调整原文标签高度
        original_font = self.original_label.font()
        metrics = QFontMetrics(original_font)
        line_height = metrics.height()
        padding = max(10, original_font.pointSize() // 2)
        self.original_label.setMinimumHeight(line_height + padding * 2)
        
        # 调整译文标签高度
        translation_font = self.translation_label.font()
        metrics = QFontMetrics(translation_font)
        line_height = metrics.height()
        padding = max(10, translation_font.pointSize() // 2)
        self.translation_label.setMinimumHeight(line_height + padding * 2)
        
        if DEBUG_MODE:
            print(f"调整标签高度: 原文高度={self.original_label.minimumHeight()}, 译文高度={self.translation_label.minimumHeight()}") 