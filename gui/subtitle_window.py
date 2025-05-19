from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizeGrip
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QFont, QColor, QFontMetrics
from config import config

# 调试开关，控制是否输出调试信息
DEBUG_MODE = False

class SubtitleWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        
        # 设置窗口透明
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 创建布局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)  # 减少标签之间的间距
        
        # 创建原文标签
        self.original_label = QLabel("")
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_label.setWordWrap(True)
        
        # 创建译文标签
        self.translated_label = QLabel("")
        self.translated_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.translated_label.setWordWrap(True)
        
        # 从配置加载设置
        self.font_size = config.get("font_size", 24)
        self.font_color = config.get("font_color", "white")
        self.position = config.get("position", "bottom")
        self.subtitle_mode = config.get("subtitle_mode", "translated")
        
        # 设置默认窗口大小
        self.max_width = config.get("window_width", 800)
        self.resize(self.max_width, config.get("window_height", 200))
        
        # 添加大小调整手柄
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background-color: rgba(255, 255, 255, 50);")
        
        # 根据字幕模式添加相应的标签
        self.update_layout()
        
        # 应用初始样式
        self.update_style()
        
        # 用于窗口拖动
        self.dragging = False
        self.drag_position = QPoint()
        
        if DEBUG_MODE:
            print(f"字幕窗口初始化: 大小={self.width()}x{self.height()}, 字体={self.font_size}, 颜色={self.font_color}, 模式={self.subtitle_mode}")
    
    def update_layout(self):
        """根据字幕模式更新布局"""
        # 清空当前布局
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item.widget():
                self.main_layout.removeWidget(item.widget())
        
        # 确保所有标签都可见
        self.original_label.show()
        self.translated_label.show()
        
        # 根据字幕模式添加标签
        if self.subtitle_mode == "original":
            self.main_layout.addWidget(self.original_label)
            self.translated_label.hide()
        elif self.subtitle_mode == "translated":
            self.main_layout.addWidget(self.translated_label)
            self.original_label.hide()
        elif self.subtitle_mode == "both":
            self.main_layout.addWidget(self.original_label)
            self.main_layout.addWidget(self.translated_label)
        
        # 添加大小调整手柄
        self.main_layout.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        
        if DEBUG_MODE:
            print(f"更新字幕布局: 模式={self.subtitle_mode}, 原文标签可见={self.original_label.isVisible()}, 译文标签可见={self.translated_label.isVisible()}")
        
        # 调整窗口布局
        self.adjustSize()
        
    def set_subtitle_mode(self, mode):
        """设置字幕显示模式"""
        if mode in ["original", "translated", "both"] and mode != self.subtitle_mode:
            self.subtitle_mode = mode
            config.set("subtitle_mode", mode)
            self.update_layout()
            self.update_style()
            if DEBUG_MODE:
                print(f"字幕显示模式变更为: {mode}")
            
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
        # 保存新的窗口大小
        config.set("window_width", self.width())
        config.set("window_height", self.height())
        
        # 保证窗口大小变化时字体等样式同步更新
        self.update_style()
        
        if DEBUG_MODE:
            print(f"字幕窗口大小变化: {self.width()}x{self.height()}")
        
    def set_text(self, original_text="", translated_text=""):
        """设置字幕文本，支持原文和译文分别设置"""
        text_changed = False
        
        # 只有当文本内容真正变化时才更新
        if original_text and original_text != self.original_label.text():
            self.original_label.setText(original_text)
            text_changed = True
            if DEBUG_MODE:
                print(f"设置原文: {original_text[:20]}...")
        
        if translated_text and translated_text != self.translated_label.text():
            self.translated_label.setText(translated_text)
            text_changed = True
            if DEBUG_MODE:
                print(f"设置译文: {translated_text[:20]}...")
        
        # 文本变化后确保布局正确更新
        if text_changed:
            # 不需要每次都更新布局，只在首次或模式变更时需要
            # self.update_layout()
            self.adjust_width_to_content()
    
    def adjust_width_to_content(self):
        """根据文本内容调整窗口宽度，尽量不换行但不超过最大宽度"""
        # 计算所需的宽度
        font = QFont("Arial", self.font_size)
        font_metrics = QFontMetrics(font)
        
        # 获取当前显示的文本
        texts = []
        if self.original_label.isVisible() and self.original_label.text():
            texts.append(self.original_label.text())
        if self.translated_label.isVisible() and self.translated_label.text():
            texts.append(self.translated_label.text())
        
        # 计算所需宽度（考虑padding和边距）
        required_width = 0
        padding = 20  # 考虑padding的两侧共20像素
        
        for text in texts:
            # 计算文本宽度
            text_width = font_metrics.horizontalAdvance(text) + padding
            required_width = max(required_width, text_width)
        
        # 限制在最大宽度范围内
        new_width = min(required_width, self.max_width)
        
        # 设置窗口宽度
        if new_width > 0:
            current_height = self.height()
            self.resize(new_width, current_height)
            if DEBUG_MODE:
                print(f"调整字幕窗口宽度: {new_width}px")
            
            # 重新定位窗口以确保居中
            self.update_position()
    
    def set_font_size(self, size):
        """设置字体大小"""
        if self.font_size != size:
            self.font_size = size
            config.set("font_size", size)
            self.update_style()
            if DEBUG_MODE:
                print(f"字幕字体大小变化: {size}")
    
    def set_color(self, color):
        """设置字体颜色"""
        if self.font_color != color:
            self.font_color = color
            config.set("font_color", color)
            self.update_style()
            if DEBUG_MODE:
                print(f"字幕颜色变化: {color}")
    
    def set_position(self, position):
        """设置字幕位置"""
        if self.position != position:
            self.position = position
            config.set("position", position)
            self.update_position()
            if DEBUG_MODE:
                print(f"字幕位置变化: {position}")
    
    def update_style(self):
        """更新字幕样式"""
        font = QFont("Arial", self.font_size)
        
        # 对原文标签应用样式
        self.original_label.setFont(font)
        self.original_label.setStyleSheet(f"""
            color: {self.font_color};
            background-color: rgba(0, 0, 0, 150);
            padding: 10px;
            border-radius: 5px;
        """)
        
        # 对译文标签应用样式
        self.translated_label.setFont(font)
        self.translated_label.setStyleSheet(f"""
            color: {self.font_color};
            background-color: rgba(0, 0, 0, 150);
            padding: 10px;
            border-radius: 5px;
        """)
        
        # 确保位置更新
        self.update_position()
    
    def update_position(self):
        """根据设置的位置在屏幕上定位窗口"""
        from PySide6.QtWidgets import QApplication
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().geometry()
        width = screen.width()
        height = screen.height()
        
        # 计算窗口大小
        window_width = self.width()
        window_height = self.height()
        
        # 根据设置的位置计算窗口位置
        if self.position == "top":
            x = (width - window_width) // 2
            y = height // 10
        elif self.position == "middle":
            x = (width - window_width) // 2
            y = (height - window_height) // 2
        else:  # bottom
            x = (width - window_width) // 2
            y = height - window_height - height // 10
        
        self.move(x, y)
        if DEBUG_MODE:
            print(f"字幕窗口位置更新: 位置={self.position}, 坐标=({x},{y})")
    
    def showEvent(self, event):
        """窗口显示时的事件处理"""
        super().showEvent(event)
        self.update_position()
    
    def keyPressEvent(self, event):
        """按下ESC键时关闭窗口"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def update_text(self, text):
        """更新文本显示（兼容方法，等同于设置文本）"""
        # 检查是否需要更新
        if self.subtitle_mode == "original":
            # 如果已经显示的内容与新内容相同，不更新
            if self.original_label.text() == text:
                return
            self.set_text(original_text=text)
        elif self.subtitle_mode == "translated":
            # 如果已经显示的内容与新内容相同，不更新
            if self.translated_label.text() == text:
                return
            self.set_text(translated_text=text)
        elif self.subtitle_mode == "both":
            # 尝试分割文本（如果是组合的文本）
            if "\n" in text:
                parts = text.split("\n", 1)
                orig = parts[0]
                trans = parts[1] if len(parts) > 1 else ""
                
                # 如果原文和译文都没变，不更新
                if self.original_label.text() == orig and self.translated_label.text() == trans:
                    return
                
                self.set_text(original_text=orig, translated_text=trans)
            else:
                # 如果译文没变，不更新
                if self.translated_label.text() == text:
                    return
                self.set_text(translated_text=text)
        
        # 保证窗口显示
        if not self.isVisible():
            self.show()

    def on_window_width_changed(self, width):
        """最大宽度设置变更"""
        self.max_width = width
        config.set("window_width", width)
        
        # 如果当前宽度大于新的最大宽度，调整当前宽度
        if self.width() > width:
            self.resize(width, self.height())
        
        # 根据内容重新调整宽度
        self.adjust_width_to_content()
        print(f"字幕窗口最大宽度设置: {width}px") 