from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizeGrip, QMainWindow
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QFont, QColor, QFontMetrics
from config import config
from PySide6.QtWidgets import QApplication

# 调试开关，控制是否输出调试信息
DEBUG_MODE = False

# 逐词行左边的额外留白（标签自身的内边距之外）：词贴着窗边不好看
REVEAL_LEFT_MARGIN = 14

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
        
        # 逐词行的排版状态：左边留多少白（见 set_original_words）。
        # 标签本身照旧占满整行、文本超长照样换行，只有文字整体右移。
        self._original_inset = 0
        self._translation_inset = 0
        self._original_padding = 12
        self._translation_padding = 12
        self.original_color = "white"
        self.translation_color = "white"

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
        self._refresh_label_styles()

    def set_translation_color(self, color):
        """设置译文颜色"""
        self.translation_color = color  # 保存为实例属性
        self._refresh_label_styles()
    
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
        # 行数变了（原文行要不要两行），窗口高度跟着调
        self.adjustLabelHeights()
        self._fit_window_height()
    
    def translation_disabled(self):
        """目标语言选了"不翻译"：只解析原文，不产生译文"""
        return config.get("target_language", "en") == "none"

    def _visible_labels(self):
        """按当前模式该显示哪几行"""
        if self.translation_disabled() or self.subtitle_mode == "original":
            # "不翻译"模式：只有原文行，"不翻译"时译文行没有内容可显示
            return [self.original_label]
        if self.subtitle_mode == "translated":
            return [self.translation_label]
        return [self.original_label, self.translation_label]  # both

    def update_labels_visibility(self):
        """根据字幕模式更新标签的可见性"""
        visible = self._visible_labels()
        for label in (self.original_label, self.translation_label):
            label.setVisible(label in visible)
    
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
                self._set_sentence_text(self.original_label, original_text)

            # 在翻译模式下，检查译文是否需要更新
            if (subtitle_mode == "translated" and not self.translation_disabled()
                    and original_text != self.translation_label.text()):
                needs_update = True
                self._set_sentence_text(self.translation_label, original_text)
        else:
            # 双参数调用，分别设置原文和译文
            if DEBUG_MODE:
                print(f"双参数调用 update_text: 原文={original_text}, 译文={translation_text}")
            
            # 设置原文（如果提供）
            if original_text is not None and original_text != self.original_label.text():
                needs_update = True
                self._set_sentence_text(self.original_label, original_text)

            # 设置译文（如果提供）
            if translation_text is not None and translation_text != self.translation_label.text():
                needs_update = True
                self._set_sentence_text(self.translation_label, translation_text)

            # 特殊处理：如果在翻译模式但没有译文，则使用原文代替
            # （"不翻译"模式下不顶替：译文行本该是空的，而且它已被隐藏）
            if (not translation_text and subtitle_mode == "translated" and
                not self.translation_disabled() and
                original_text and original_text != self.translation_label.text()):
                needs_update = True
                self._set_sentence_text(self.translation_label, original_text)
        
        # 只有在文本发生变化时才调整标签高度和更新UI
        if needs_update:
            # 确保标签高度正确
            self.adjustLabelHeights()
            
            # 确保窗口显示
            if not self.isVisible():
                self.show()
            
            # 更新标签的可见性
            self.update_labels_visibility()
    
    def _label_stylesheet(self, color, padding, inset):
        """标签样式：padding-left 单独写一行覆盖 padding 简写

        效果是文字整块右移 inset 像素，标签自己还是占满整行（超长文本照旧在右边
        换行）。逐词行就靠它做到"左边留白固定、新词往右边长"，而不用挪标签。
        """
        return (f"color: {color}; background-color: transparent; "
                f"padding: {padding}px; padding-left: {padding + inset}px; "
                f"border-radius: 5px;")

    def _refresh_label_styles(self):
        self.original_label.setStyleSheet(self._label_stylesheet(
            self.original_color, self._original_padding, self._original_inset))
        self.translation_label.setStyleSheet(self._label_stylesheet(
            self.translation_color, self._translation_padding, self._translation_inset))

    def _reveal_label(self):
        """逐词原文写进哪个标签：原文行可见就写原文行；"仅显示译文"模式下原文行是
        隐藏的，就沿用整句通路的做法先写进译文行占位，等译文到达再替换"""
        if self.subtitle_mode == "translated" and not self.translation_disabled():
            return self.translation_label
        return self.original_label

    def _set_label_inset(self, label, inset):
        if label is self.original_label:
            self._original_inset = inset
        else:
            self._translation_inset = inset

    def _get_label_inset(self, label):
        return self._original_inset if label is self.original_label else self._translation_inset

    def _apply_reveal_layout(self, label):
        """逐词行：文字左对齐 + 固定的左边留白

        左对齐是关键：词一个个往右边加，左边一动不动。要是居中，每多一个字整行就
        重新排一次，看着一直在抖。
        """
        if (self._get_label_inset(label) == REVEAL_LEFT_MARGIN
                and label.alignment() & Qt.AlignmentFlag.AlignLeft):
            return  # 已经摆好了，不用重新上样式（样式一改就会重绘）
        self._set_label_inset(label, REVEAL_LEFT_MARGIN)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._refresh_label_styles()

    def _apply_sentence_layout(self, label):
        """整句通路写进来的文本一律居中排版

        逐词行可能刚把这个标签设成左对齐（"仅显示译文"模式下逐词原文先占着译文行），
        整句原文/译文写进来时得把它恢复成原来的样子。
        """
        if (self._get_label_inset(label) == 0
                and not label.alignment() & Qt.AlignmentFlag.AlignLeft):
            return
        self._set_label_inset(label, 0)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_label_styles()

    def _set_sentence_text(self, label, text):
        """整句通路写文本：顺带恢复居中排版"""
        label.setText(text)
        self._apply_sentence_layout(label)

    def _reveal_avail_width(self, label):
        """逐词行的文字实际能占的宽度：标签宽度扣掉左右内边距和左边的额外留白

        截断上一句时要按这个宽度算，宽一点点它就会折成两行，把当前句挤出去。
        """
        padding = (self._original_padding if label is self.original_label
                   else self._translation_padding)
        width = label.width()
        if width <= 1:
            # 还没排过版（字幕窗第一次显示之前），先按窗口宽度估
            width = max(self.width(), self.window_width) - 4  # 4 = 布局左右边距 2+2
        return max(1, width - 2 * padding - REVEAL_LEFT_MARGIN)

    def _reveal_two_lines(self):
        """原文行是否按"上一句 + 当前句"两行显示（逐词模式、且原文行看得见时）"""
        return (config.get("word_by_word_enabled", True)
                and not self.translation_disabled()
                and self.subtitle_mode != "translated")

    def _compose_reveal_text(self, target, current_text, previous_text):
        """拼出要写进标签的文本：当前句在新的一行，上一句在上面当上下文

        只有原文行显示两行（"仅显示译文"模式下逐词原文只是暂借译文行占位，
        待会儿整句译文要把它整行换掉）。上一句太长就截断加省略号，保证当前句
        永远看得见——总高两行才稳，跟 YouTube 的字幕框一个道理。
        """
        if not previous_text or target is not self.original_label or not self._reveal_two_lines():
            return current_text
        metrics = QFontMetrics(target.font())
        previous = metrics.elidedText(previous_text, Qt.TextElideMode.ElideRight,
                                      self._reveal_avail_width(target))
        return f"{previous}\n{current_text}"

    def reset_reveal_layout(self):
        """逐词开关被关掉时调用：把两行都恢复成居中，窗口高度也跟着回退"""
        self._set_label_inset(self.original_label, 0)
        self._set_label_inset(self.translation_label, 0)
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.translation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_label_styles()
        self.adjustLabelHeights()
        self._fit_window_height()

    def set_original_words(self, original_text, previous_text=None, utterance_id=None):
        """逐词显示原文：把"此刻已经念到的词"拼成一行写上去

        写哪一行跟整句原文的规矩一致（见 `_reveal_label`）。排版固定左对齐：
        新词在右边接着加，左边一动不动。`previous_text` 是上一句的全文，会显示在
        上面那一行当上下文（只有原文行、且逐词模式开着时）。

        文本没变就直接返回（逐词只会变长），200ms 轮询不会反复重绘。
        """
        if not original_text:
            return

        target = self._reveal_label()
        text = self._compose_reveal_text(target, original_text, previous_text)

        if text == target.text():
            self._apply_reveal_layout(target)
            return

        target.setText(text)
        self._apply_reveal_layout(target)
        self.adjustLabelHeights()

        if not self.isVisible():
            self.show()

        self.update_labels_visibility()

    def clear_translation(self):
        """清空译文行（切到"不翻译"时，把上一句译文从屏幕上撤掉）"""
        if self.translation_label.text():
            self.translation_label.setText("")
        self.update_labels_visibility()

    def set_text(self, original_text="", translation_text=""):
        """设置预览文本"""
        # 设置标签文本
        if original_text is not None:
            self._set_sentence_text(self.original_label, original_text)

        if translation_text is not None:
            self._set_sentence_text(self.translation_label, translation_text)

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

        # 应用保存的窗口尺寸（两行原文放不下时按需撑高）
        self.adjustLabelHeights()
        self.resize(self.window_width, max(self.window_height, self._required_height()))

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
        self.original_color = original_color
        self._original_padding = original_padding

        # 对译文标签应用样式
        self.translation_label.setFont(translation_font)
        self.translation_color = translation_color
        self._translation_padding = translation_padding

        self._refresh_label_styles()

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
        # （两行原文 + 译文比用户设的高度还高时按需撑高，不然第二行会被切掉）
        self.setFixedSize(self.window_width, max(self.window_height, self._required_height()))

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

    def _label_line_height(self, label):
        """一行文字需要的高度（字高 + 上下内边距）"""
        font = label.font()
        padding = max(10, font.pointSize() // 2)
        return QFontMetrics(font).height() + padding * 2

    def adjustLabelHeights(self):
        """根据当前字体调整标签高度

        原文行在逐词模式下要放两行（上一句 + 当前句），高度按两行算——窗口高度
        不够时由 `_fit_window_height` 把窗口撑高，不然第二行会被切掉。
        """
        lines = 2 if self._reveal_two_lines() else 1
        self.original_label.setMinimumHeight(self._label_line_height(self.original_label) * lines)
        self.translation_label.setMinimumHeight(self._label_line_height(self.translation_label))

        if DEBUG_MODE:
            print(f"调整标签高度: 原文高度={self.original_label.minimumHeight()}"
                  f"({lines}行), 译文高度={self.translation_label.minimumHeight()}")

    def _required_height(self):
        """按当前可见的行数算出窗口需要的总高度"""
        height = 4  # 布局上下边距 2+2
        for label in self._visible_labels():
            height += label.minimumHeight()
        return height

    def _fit_window_height(self):
        """窗口高度不够放不下时按需撑高（用户设的窗口高度当作下限）"""
        if not self.isVisible():
            return
        height = max(self.window_height, self._required_height())
        if height != self.height():
            self.resize(self.window_width, height)
            self.update_position()
