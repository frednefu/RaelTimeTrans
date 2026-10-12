from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizeGrip, QMainWindow
from PySide6.QtCore import Qt, QPoint, QSize, QRect, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QFontMetrics
import math

from config import config
from PySide6.QtWidgets import QApplication

# 调试开关，控制是否输出调试信息
DEBUG_MODE = False

# 左右边距（左边另有一段逐词留白，见 REVEAL_LEFT_MARGIN）
LAYOUT_MARGIN = 2

# 行与行、行与边框之间统一留的空隙：按字号算（见 `_row_gap`），上/中/下三处一样宽。
# 行距的这个比例再小就挤了，再大就显空——字号一改三处一起跟着变。
ROW_GAP_RATIO = 0.5
MIN_ROW_GAP = 6

# 逐词行左边的额外留白（标签自身的内边距之外）：词贴着窗边不好看
REVEAL_LEFT_MARGIN = 32

# 换句时整块上滚一行用多久（毫秒）。太长能看到中间过程，太短就像直接跳。
REVEAL_SCROLL_MS = 200

# 译文行框里最多留几行（超出的往上滚，见 `_sync_translation_scroll`）。
# 2026-10 从 2 改成 3：**多出来的那一行留给"上一句"**——原来译文行只有当前这一句，
# 下一句译文一到就整行覆盖，长译文还没看完就没了（用户报的"还没看完就显示下一行，
# 应该向上滚动"）。3 行 = 上一句译文 1 行（超长截断，像原文行那样）+ 当前句 2 行
# （太长就在这两行里往上滚）。想退回旧行为把这个数改回 2 即可。
TRANSLATION_ROWS = 3
# 译文行一次滚动最长多久（毫秒）：整句译文一下折成很多行时按行数延时滑过去，
# 免得看着像瞬移；一行的滚动仍是 REVEAL_SCROLL_MS，和原文行一个手感。
MAX_TRANSLATION_SCROLL_MS = 600


class RevealViewport(QWidget):
    """固定高度的裁剪框：里面装一个行标签，靠移动这个标签来滚动

    Qt 里子部件天然被父部件的矩形裁掉，越过顶边就看不见了——所以"定高的窗口 +
    里面一个可以往上挪的标签"就是一个滚动框，不用碰 paintEvent。

    内容高度（`set_content_height`）设成两行时，标签只占上半部分：新句子开始时把
    标签整体上移一个行距，上一句顶出去、当前句升到第一行，再把新文本写进去（见
    `SubtitleWindow.set_original_words`）。设成 0 表示"标签填满裁剪框"，整句通路
    （居中的整句原文/译文）走这条，偏移恒为 0，跟没这层一样。
    """

    def __init__(self, child):
        super().__init__()
        self._child = child
        child.setParent(self)
        self._content_height = 0
        self._offset = 0

    def set_content_height(self, height):
        """内容（子标签）的高度；0 = 跟着裁剪框的高度走"""
        height = int(height)
        if height != self._content_height:
            self._content_height = height
            self._place_child()

    def set_scroll_offset(self, offset):
        """内容整体上移多少像素（滚动动画每帧调这里）"""
        if offset != self._offset:
            self._offset = offset
            self._place_child()

    def scroll_offset(self):
        """当前偏移（算下一段滚动从哪儿起步用）"""
        return self._offset

    def reset_scroll(self):
        """回到没滚过的样子"""
        self.set_scroll_offset(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_child()

    def _place_child(self):
        height = self._content_height or self.height()
        self._child.setGeometry(0, -int(round(self._offset)), self.width(), height)


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
        # 边距与间距的三处空隙由 `_apply_row_gaps` 统一定（上/中/下一样宽，按字号算），
        # 这里先给个最小值，免得窗口还没排过版时贴着边
        layout.setContentsMargins(LAYOUT_MARGIN, LAYOUT_MARGIN, LAYOUT_MARGIN, LAYOUT_MARGIN)
        layout.setSpacing(0)
        
        # 从配置获取字体类型
        original_font_family = config.get("original_font_family", "Arial")
        translation_font_family = config.get("translation_font_family", "黑体")
        
        # 创建两个标签，分别用于显示原文和译文
        self.original_label = QLabel()
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_label.setWordWrap(True)
        # QLabel 的 indent 默认是 -1：左对齐时它会按字体再垫半个 "x" 宽（本机离屏
        # 字体是 9px，真 Arial 是 3px）。逐词行要按"内边距 + REVEAL_LEFT_MARGIN"精确
        # 摆字，这点浮动会让左边留白对不上（`_reveal_avail_width` 也会算宽一点），
        # 所以显式置 0。居中排版（整句通路）本来就不受 indent 影响，行为不变。
        self.original_label.setIndent(0)
        
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
        self.translation_label.setIndent(0)  # 同上：左边留白要按内边距精确算
        
        # 设置初始字体
        translation_font = QFont(translation_font_family, 24)
        self.translation_label.setFont(translation_font)
        # 计算最小高度
        metrics = QFontMetrics(translation_font)
        line_height = metrics.height()
        self.translation_label.setMinimumHeight(line_height + 20)
        self.translation_label.setStyleSheet("color: white; background-color: transparent; padding: 12px;")
        
        # 每个标签各装进一个裁剪框（逐词换句时靠它滚动，见 RevealViewport）
        self.original_view = RevealViewport(self.original_label)
        self.translation_view = RevealViewport(self.translation_label)

        # 添加裁剪框到布局（标签在里面，位置由裁剪框给）
        layout.addWidget(self.original_view)
        layout.addWidget(self.translation_view)

        # 逐词行的排版状态：左边留多少白（见 set_original_words）。
        # 标签本身照旧占满整行、文本超长照样换行，只有文字整体右移。
        self._original_inset = 0
        self._translation_inset = 0
        self._original_padding = 12
        self._translation_padding = 12
        self.original_color = "white"
        self.translation_color = "white"

        # 换句滚动状态：上一个 utterance_id、动画期间攒下的最新文本、正在滚的裁剪框
        # 和动画本身（见 set_original_words / _start_reveal_scroll）
        self._reveal_utterance_id = None
        self._reveal_pending = None
        self._scroll_view = None
        self._scroll_anim = None

        # 译文行的滚动状态（见 `_set_translation_rows`）。和原文行那套分开放：
        # 两行可能同时在滚，而且译文不用"滚动期间不动文本"那一招——它的文本随时
        # 可以换，只挪偏移，不会露出错的中间帧。
        self._t_scroll_anim = None
        self._t_scroll_target = 0

        # 译文行的"上一句 + 当前句"（见 `_update_translation_line`）。`_translation_prev`
        # 是上一句的译文（显示在框顶那一行、超长截断），`_translation_current` 是当前句
        # 还没组合的译文原文（组合后的文本在标签里，不能拿标签文本当"当前句"用）。
        # `_translation_current_final` / `_translation_key` 决定"新文本是同一句的更新
        # （替换）还是新的一句（把当前这行降级成上一句）"。
        self._translation_prev = ""
        self._translation_current = ""
        self._translation_current_final = False
        self._translation_key = None

        # 布局状态：当前三处间隙多大（见 `_apply_row_gaps`）、窗口高度是不是跟着内容
        # 自动走（用户自己改过高度就锁定，见 `_fit_window_height`）、以及这次 resize
        # 是不是我们算出来的（用来区分用户拖右下角）
        self._row_gap_current = 0
        self.window_height_auto = True
        self._auto_resize_depth = 0

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
        # 高度是不是用户定的：没定过就跟着内容自动走（见 `_fit_window_height`）
        self.window_height_auto = bool(config.get("window_height_auto", True))
        
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

        # 字号变了：行高、裁剪框高度、可滚的一行（行距）都跟着重算
        self.adjustLabelHeights()
        # 三处间隙是按行距算的，窗口高度也跟着内容走
        self._fit_window_height()

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

        # 字号变了：行高和裁剪框高度跟着重算
        self.adjustLabelHeights()
        self._fit_window_height()

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
        # 切进"仅显示译文"时逐词原文整条通路都不上屏（见 `_word_reveal_visible`）：那条
        # 攒在半路上的文本正是**不该出现**的原文，所以滚动是"停掉"而不是"停掉再贴上"
        # （`apply_pending=False`）。
        hide_original = not self._word_reveal_visible()
        self._stop_reveal_scroll(apply_pending=not hide_original)
        if hide_original:
            self._reveal_pending = None
            self._reveal_utterance_id = None
            # 原文行在这个模式下不显示：清空它，免得切回"两者"时闪一眼上一句旧文本
            self.original_label.setText("")
        # "上一句译文"同理：切到"不翻译"/"仅显示原文"时它不该留在框里
        if self.translation_disabled() or mode == "original":
            self._reset_translation_lines()
            if self.translation_label.text():
                self.translation_label.setText("")
        # 更新标签可见性
        self.update_labels_visibility()
        # 上下内边距是按模式定的（两行模式下是 0，见 `_label_vpadding`），模式一换
        # 样式得重上一遍，不然会留着上一个模式的边距
        self._refresh_label_styles()
        # 行数变了（原文行要不要两行），窗口高度跟着调
        self.adjustLabelHeights()
        self._fit_window_height()
    
    def translation_disabled(self):
        """目标语言选了"不翻译"：只解析原文，不产生译文"""
        return config.get("target_language", "en") == "none"

    def _word_reveal_visible(self):
        """逐词原文该不该上屏

        "仅显示译文"模式下屏幕上只许有译文：说话期间那一行宁可空着，也不能先冒一句
        原文出来（文案、字体颜色、字号都是原文那一套，看着就像串台）。
        "不翻译"是个例外：目标语言是"不翻译"时模式虽然还叫"仅显示译文"，但那时屏幕上
        本来就只该有原文（`_visible_labels` 也是这么判的）。
        """
        return not (self.subtitle_mode == "translated" and not self.translation_disabled())

    def _visible_labels(self):
        """按当前模式该显示哪几行"""
        if self.translation_disabled() or self.subtitle_mode == "original":
            # "不翻译"模式：只有原文行，"不翻译"时译文行没有内容可显示
            return [self.original_label]
        if self.subtitle_mode == "translated":
            return [self.translation_label]
        return [self.original_label, self.translation_label]  # both

    def update_labels_visibility(self):
        """根据字幕模式更新标签的可见性（裁剪框跟着一起显隐）"""
        visible = self._visible_labels()
        for label in (self.original_label, self.translation_label):
            label.setVisible(label in visible)
            self._label_view(label).setVisible(label in visible)

    def _label_view(self, label):
        """标签所在的裁剪框"""
        return self.original_view if label is self.original_label else self.translation_view
    
    def update_text(self, original_text=None, translation_text=None,
                    translation_key=None, translation_final=False):
        """更新字幕文本

        `translation_key` / `translation_final` 只给译文行用：**同一句的前缀译文和
        整句译文共用一把 key**，字幕窗据此决定新文本是"替换当前这一行"还是"新的一句"
        （后者把当前这行降级成上一句、留在框顶那一行，见 `_update_translation_line`）。
        不给 key（旧调用、检查脚本）时按"原地替换"处理，行为与原来一致。

        `translation_text` 传空串等于**什么都不做**（以前它会清空译文行）：译文行的
        "上一句"是字幕窗自己攒的，随手清掉就没有上下文可翻了。要真清空请调
        `clear_translation()`。
        """
        # 检查是否需要更新
        needs_update = False

        # 检查是否是单个参数调用（兼容旧版本接口）
        if translation_text is None and isinstance(original_text, str):
            # 单参数调用，把这一串当原文显示
            if DEBUG_MODE:
                print(f"单参数调用 update_text: {original_text}")

            # 检查原文是否发生变化
            if original_text != self.original_label.text():
                needs_update = True
                self._set_sentence_text(self.original_label, original_text)
        else:
            # 双参数调用，分别设置原文和译文
            if DEBUG_MODE:
                print(f"双参数调用 update_text: 原文={original_text}, 译文={translation_text}")

            # 设置原文（如果提供）
            if original_text is not None and original_text != self.original_label.text():
                needs_update = True
                self._set_sentence_text(self.original_label, original_text)

            # 设置译文（如果提供）
            if translation_text is not None:
                if self._update_translation_line(translation_text, translation_key,
                                                 translation_final):
                    needs_update = True
        # 注意：这里**没有**"翻译模式下还没译文就拿原文顶上去"那一手（原来有）。那一手
        # 正是"仅显示译文时先冒一句原文、还穿着译文的颜色和字号"的由来——原文行那时是
        # 藏着的，所以顶替的是译文行。现在译文行只由真正的译文（含"边说边译"的前缀）
        # 写；译文没到就让它空着。
        
        # 只有在文本发生变化时才调整标签高度和更新UI
        if needs_update:
            # 确保标签高度正确
            self.adjustLabelHeights()

            # 确保窗口显示
            if not self.isVisible():
                self.show()

            # 更新标签的可见性
            self.update_labels_visibility()
            # 译文折行时行盒会变高，窗口跟着收/放（用户自己定过高度就按他的来）
            self._fit_window_height()
    
    def _label_stylesheet(self, color, padding, inset, vpadding=None):
        """标签样式：padding-left 单独写一行覆盖 padding 简写

        效果是文字整块右移 inset 像素，标签自己还是占满整行（超长文本照旧在右边
        换行）。逐词行就靠它做到"左边留白固定、新词往右边长"，而不用挪标签。

        `vpadding` 是上下内边距（两行逐词行给 0，见 `_label_vpadding`）；左右一律
        用 `padding`，因为 `_reveal_avail_width` 按它算上一句的截断宽度。
        """
        if vpadding is None:
            vpadding = padding
        return (f"color: {color}; background-color: transparent; "
                f"padding: {vpadding}px {padding}px; padding-left: {padding + inset}px; "
                f"border-radius: 5px;")

    def _refresh_label_styles(self):
        self.original_label.setStyleSheet(self._label_stylesheet(
            self.original_color, self._original_padding, self._original_inset,
            self._label_vpadding(self.original_label)))
        self.translation_label.setStyleSheet(self._label_stylesheet(
            self.translation_color, self._translation_padding, self._translation_inset,
            self._label_vpadding(self.translation_label)))

    def _label_padding(self, label):
        """标签的左右内边距（原文字号和译文字号各有一套）"""
        return (self._original_padding if label is self.original_label
                else self._translation_padding)

    def _label_vpadding(self, label):
        """标签的上下内边距：逐词两行模式下一律是 0

        文字上下的空白全部交给布局的三处间隙（`_apply_row_gaps`），它按字号算、上
        中下一样宽——标签自己再垫一层内边距的话，原文和译文各自的上下就不一样宽了
        （原文贴着框顶、译文却缩在框中间），"三处间隙一致"就无从谈起。

        左对齐那行还有第二个理由（`AlignLeft` 这一条单独判）：两行模式下文字第一
        行得贴住裁剪框顶边，整体上移一个行距才能把上一行整行送出框外；上面留着内边
        距的话，滚完后上一行还剩十来个像素的字形挂在顶上，一直挂到动画结束、提交新
        文本那一帧才消失——看着像闪了一下。
        """
        if label.alignment() & Qt.AlignmentFlag.AlignLeft:
            return 0
        if self._reveal_two_lines():
            return 0  # 两行模式下译文行也把上下空白交给布局的间隙
        return self._label_padding(label)

    def _translation_reveal(self):
        """译文行是否按原文那套排版（左对齐 + 超出两行往上滚）

        只看模式和配置就能判，不用记"这一行现在装的是什么"：译文行可见（"两者"/
        "仅显示译文"，且不是"不翻译"）时它就是个正经的视口。逐词原文**从不**再用译文
        行占位（见 `_word_reveal_visible`），所以这里不再需要按逐词开关分情况。
        """
        return not (self.translation_disabled() or self.subtitle_mode == "original")

    def _update_translation_line(self, translation, key=None, is_final=False):
        """写译文行：新的一句到了，把上一句留在框顶那一行（不再整行清掉）

        什么时候"翻页"（当前这行降级成"上一句"）只有两条判据：

        - **整句译文到达**：当前这行本身就装着一句整句译文、而且不是同一句
          （`key` 不同，或者调用方根本没给 key）→ 翻页；否则原地替换。
          同一句的"前缀译文 → 整句译文"共用一把 key，所以终稿是**替换**那半截，
          不是把它顶到上面去（那样屏幕上会出现两遍几乎一样的话）。
        - **前缀译文到达**：当前这行装着整句译文（只能是上一句的，同一句的整句
          不可能先于它的前缀）→ 先把整句顶上去，再原地写前缀。

        返回 True 表示这一行确实变了（调用方要重排）。文本没变直接返回 False：
        200ms 轮询会反复叫它，无端重排会让滚动动画一直重启。
        """
        if not translation or translation == self._translation_current:
            return False

        rotate = False
        if self._translation_current:
            if is_final:
                same_sentence = (key is not None and key == self._translation_key)
                rotate = self._translation_current_final and not same_sentence
            else:
                rotate = self._translation_current_final
        if rotate:
            self._translation_prev = self._translation_current
        self._translation_current = translation
        self._translation_current_final = bool(is_final)
        if key is not None:
            self._translation_key = key

        # 标签里装的是"上一句 + 当前句"的组合文本，`_translation_current` 才是当前句
        # （拿标签文本当当前句用，下一次比较就会把组合整段当"新文本"）。
        self._set_sentence_text(self.translation_label, self._compose_translation_text())
        return True

    def _compose_translation_text(self):
        """译文行的组合文本：当前句在下面，上一句截断成一行放上面

        和原文行（`_compose_reveal_text`）同一个道理：上一句太长就截断加省略号，
        保证当前句永远看得见。上一句那一行在译文行归视口管时才给（见
        `_translation_reveal`），否则整句通路是居中的，两行组合反而别扭。
        """
        prev = self._translation_prev
        if not prev or not self._translation_reveal():
            return self._translation_current
        metrics = QFontMetrics(self.translation_label.font())
        prev = metrics.elidedText(prev, Qt.TextElideMode.ElideRight,
                                  self._reveal_avail_width(self.translation_label))
        return f"{prev}\n{self._translation_current}"

    def _set_label_inset(self, label, inset):
        if label is self.original_label:
            self._original_inset = inset
        else:
            self._translation_inset = inset

    def _get_label_inset(self, label):
        return self._original_inset if label is self.original_label else self._translation_inset

    def _reveal_alignment(self, label):
        """逐词行的对齐：左边固定 + 两行模式下顶对齐

        左上角对齐；两行模式下必须顶对齐，理由见 `_label_vpadding`（滚一行要正好
        把上一行送出框外，内容就得从框顶边开始）。
        """
        if label is self.original_label:
            if self._reveal_two_lines():
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        # 译文行：顶对齐是"尾窗滚动"的前提——每行都得落在行距的整数倍上，`VCenter`
        # 那点取整误差会让滚完之后最后一行差一两像素（见 `_label_vpadding`）
        if self._translation_reveal():
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    def _apply_reveal_layout(self, label):
        """逐词行：文字左对齐 + 固定的左边留白

        左对齐是关键：词一个个往右边加，左边一动不动。要是居中，每多一个字整行就
        重新排一次，看着一直在抖。
        """
        align = self._reveal_alignment(label)
        if (self._get_label_inset(label) == REVEAL_LEFT_MARGIN
                and label.alignment() == align):
            return  # 已经摆好了，不用重新上样式（样式一改就会重绘）
        self._set_label_inset(label, REVEAL_LEFT_MARGIN)
        label.setAlignment(align)
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
        """整句通路写文本：按这一行该有的排版恢复对齐

        原文行一律左对齐（和逐词行、译文行一致）；译文行归译文视口管时也是左对齐，
        盒高与滚动位置由随后的 `adjustLabelHeights` → `_set_translation_rows` 定。
        剩下的情况（译文行在译文不可见时，反正是藏着的）才是居中排版。
        """
        label.setText(text)
        if label is self.original_label or self._translation_reveal():
            self._apply_reveal_layout(label)
        else:
            self._apply_sentence_layout(label)

    def _reveal_avail_width(self, label):
        """逐词行的文字实际能占的宽度：标签宽度扣掉左右内边距和左边的额外留白

        截断上一句时要按这个宽度算，宽一点点它就会折成两行，把当前句挤出去。
        """
        padding = self._label_padding(label)
        width = label.width()
        if width <= 1:
            # 还没排过版（字幕窗第一次显示之前），先按窗口宽度估
            width = max(self.width(), self.window_width) - 2 * LAYOUT_MARGIN
        return max(1, width - 2 * padding - REVEAL_LEFT_MARGIN)

    def _reveal_two_lines(self):
        """原文行是否按"上一句 + 当前句"两行显示（逐词模式、且原文行没被藏起来）

        "不翻译"模式下照样两行：那时屏幕上只有原文，"上一句"更是唯一的上下文。
        """
        return (config.get("word_by_word_enabled", True)
                and self.subtitle_mode != "translated")

    def _reveal_line_pitch(self, label):
        """逐词行一行文字真正占的高度（= 字体行距）

        不能用 `QFontMetrics.height()`：Arial 14 的 height 是 19，而两行文字之间
        实际隔 22 像素。滚动距离必须正好等于行距，否则动画结束那一帧和提交后的画
        面对不上，会跳一下。
        """
        return QFontMetrics(label.font()).lineSpacing()

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
        """逐词开关被关掉/重新开录时调用：把排版恢复成该有的样子，窗口高度跟着回退

        原文行不再"恢复居中"：它跟逐词行是同一个左对齐排版（`_apply_reveal_layout`），
        居中的话勾一次逐词开关就会把它居中回去，和关掉逐词后的整句原文（也是左对齐）
        对不上。译文行只有在不归它管（见 `_translation_reveal`）时才恢复居中。
        """
        self._stop_reveal_scroll()
        self._stop_translation_scroll(reset=True)
        # 新的一轮："上一句译文"是上一轮的，不能留着
        self._reset_translation_lines()
        self._reveal_utterance_id = None
        self._apply_reveal_layout(self.original_label)
        if not self._translation_reveal():
            self._set_label_inset(self.translation_label, 0)
            self.translation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_label_styles()
        self.adjustLabelHeights()
        self._fit_window_height()

    def set_original_words(self, original_text, previous_text=None, utterance_id=None):
        """逐词显示原文：把"此刻已经念到的词"拼成一行写上去

        排版固定左对齐：新词在右边接着加，左边一动不动。`previous_text` 是上一句的
        全文，显示在上面那一行当上下文（见 `_compose_reveal_text`）。

        换句时不是直接改文本，而是先把整块往上滚一行、滚完再写新文本：上一句滚出
        去、当前句升到第一行、新句在第二行接着逐词长（见 `_start_reveal_scroll`）。

        文本没变就直接返回（逐词只会变长），200ms 轮询不会反复重绘。

        当前模式不许逐词原文上屏时（"仅显示译文"，见 `_word_reveal_visible`）整条通路
        直接返回：说话期间那一行就让它空着，等整句译文到了再出现。
        """
        if not original_text or not self._word_reveal_visible():
            return

        target = self.original_label
        text = self._compose_reveal_text(target, original_text, previous_text)

        # 换句：上一句正占着第一行，而这句话是新的一句 → 整块上滚一行。
        # 框里只有一行时不用滚（`"\n"` 那一项）：那是这一轮的第一句，它本来就待在
        # 第一行，新句子直接长在下面就是对的——滚反而会把唯一那一行送出框外，空
        # 一下再回来。
        new_utterance = (utterance_id is not None
                         and self._reveal_utterance_id is not None
                         and utterance_id != self._reveal_utterance_id)
        self._reveal_utterance_id = utterance_id

        if (new_utterance and previous_text and self._reveal_two_lines()
                and "\n" in target.text()):
            self._reveal_pending = text
            if self._start_reveal_scroll(self._label_view(target)):
                return  # 滚完由 `_finish_reveal_scroll` 把文本贴上去
            self._reveal_pending = None  # 动画起不来（算不出行距）就别把文本丢了

        if self._scroll_anim is not None:
            # 正在滚：文本先攒着，滚完再贴（滚动中途改文本，画面会跳）
            self._reveal_pending = text
            return

        self._set_reveal_text(text)

    def _set_reveal_text(self, text):
        """逐词行的文本落到标签上：排版、高度、显隐一起跟上

        模式中途换成"仅显示译文"时这一帧可能已经不该显示了（`_word_reveal_visible`）：
        把攒下的文本丢掉、别的什么都不做——原文标签由 `set_subtitle_mode` 清空。
        """
        if not self._word_reveal_visible():
            self._reveal_pending = None
            return
        target = self.original_label
        if text != target.text():
            target.setText(text)
        self._apply_reveal_layout(target)
        self.adjustLabelHeights()
        # 行数/字号变了，窗口跟着内容收放（用户自己定过高度就按他的来）
        self._fit_window_height()

        if not self.isVisible():
            self.show()

        self.update_labels_visibility()

    def _start_reveal_scroll(self, view):
        """把裁剪框里的内容整体上滚一行；已经在滚就直接返回

        滚动距离正好一个行距，于是动画最后一帧和"提交新文本后"的画面一致，接缝看
        不出来。返回 False 表示起不动（没有行距可算），调用方自己把文本贴上去。
        """
        pitch = self._reveal_line_pitch(self.original_label)
        if pitch <= 0:
            return False
        if self._scroll_anim is not None:
            return True  # 上一句的滚动还没结束，等它滚完一并提交

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(float(pitch))
        anim.setDuration(REVEAL_SCROLL_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda value: view.set_scroll_offset(float(value)))
        anim.finished.connect(self._finish_reveal_scroll)
        self._scroll_view = view
        self._scroll_anim = anim
        anim.start()
        return True

    def _finish_reveal_scroll(self):
        """动画放完了（`finished` 信号）"""
        self._stop_reveal_scroll()

    def _stop_reveal_scroll(self, apply_pending=True):
        """停掉滚动（放完了也算）：偏移归零，攒下的新文本立刻贴上

        切字幕模式、重开一轮录音时也要叫一下，免得动画停在半路上、画面歪着。
        `apply_pending=False` 表示窗口正在藏起来，文本就别贴了（见 `hideEvent`）。
        """
        anim = self._scroll_anim
        self._scroll_anim = None
        if anim is not None:
            anim.stop()
            anim.deleteLater()

        view = self._scroll_view
        self._scroll_view = None
        if view is not None:
            view.reset_scroll()

        text = self._reveal_pending
        self._reveal_pending = None
        if text is not None and apply_pending:
            self._set_reveal_text(text)

    def _set_translation_rows(self):
        """译文行的盒高与滚动位置（左对齐 + 超出两行往上滚，见 `_translation_reveal`）

        这里同时是**对账点**：切字幕模式、改字号、重开一轮都会走到 `adjustLabelHeights`，
        但那几处未必先写过译文，所以排版也得在这儿一并摆好（`_apply_reveal_layout` 已经
        摆好了会直接返回）。
        """
        if not self._translation_reveal():
            # 这一行可能刚从左对齐/滚动状态里出来：偏移不清零，短文本会被顶到框外
            # （`_place_child` 在内容高度 0 时按框高走，偏移还挂在上一次的位置上）
            self._stop_translation_scroll(reset=True)
            self._set_label_rows(self.translation_label, 1)
            return
        self._apply_reveal_layout(self.translation_label)
        lines = self._label_text_lines(self.translation_label)
        self._set_label_rows(self.translation_label, min(lines, TRANSLATION_ROWS),
                             content_lines=lines)
        self._sync_translation_scroll(lines)

    def _sync_translation_scroll(self, lines):
        """让译文行滚到"最后两行"那一屏

        目标偏移 = (行数 − 2) × 行距：内容比框多一行就上滚一个行距，屏幕上留的永远是
        最新写出来的那两行。先把当前偏移夹进 [0, 目标]，文本变短时不会出现"内容比偏移
        还短、屏幕上空一块"。

        目标没变就什么都不做：逐词通道每 200ms 叫一次 `adjustLabelHeights`，无脑重启
        动画的话，一次 600ms 的滚动会被切成一段段、永远走不完。
        """
        view = self.translation_view
        pitch = self._reveal_line_pitch(self.translation_label)
        target = 0 if pitch <= 0 else max(0, lines - TRANSLATION_ROWS) * pitch
        if self._t_scroll_anim is not None and target == self._t_scroll_target:
            return
        start = min(view.scroll_offset(), target)
        self._t_scroll_target = target
        anim = self._t_scroll_anim
        self._t_scroll_anim = None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        if pitch <= 0 or start == target:
            view.set_scroll_offset(target)
            return
        # 一行一行长出来（逐词/流式前缀）就是一个行距、200ms，和原文行一个手感；
        # 整句终稿一次折很多行时按行数延时，免得看着像瞬移
        duration = int(min(MAX_TRANSLATION_SCROLL_MS,
                           REVEAL_SCROLL_MS * abs(target - start) / pitch))
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(target))
        anim.setDuration(max(1, duration))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda value: view.set_scroll_offset(float(value)))
        anim.finished.connect(self._finish_translation_scroll)
        self._t_scroll_anim = anim
        anim.start()

    def _finish_translation_scroll(self):
        """译文行的滚动画完了：落到整像素上（动画最后一帧是浮点）"""
        anim = self._t_scroll_anim
        self._t_scroll_anim = None
        if anim is not None:
            anim.deleteLater()
        self.translation_view.set_scroll_offset(self._t_scroll_target)

    def _stop_translation_scroll(self, reset=False):
        """停掉译文行的滚动

        `reset=False` 保留偏移：窗口藏起来时文本没变，再显出来还得指着尾窗那一屏
        （原文行不一样——它滚完要回 0 再贴新文本）。
        """
        anim = self._t_scroll_anim
        self._t_scroll_anim = None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        if reset:
            self._t_scroll_target = 0
            self.translation_view.set_scroll_offset(0)

    def clear_translation(self):
        """清空译文行（切到"不翻译"时，把上一句译文从屏幕上撤掉）"""
        # 行一空，滚动就没了意义：偏移不清零，下一句短译文会被顶到框外。
        # 盒高也得跟着收回来（`_set_translation_rows` 是对账点），不然这行会一直
        # 挂着上一句折行时撑出来的高度，直到下一轮 QTimer 轮询才发现。
        self._stop_translation_scroll(reset=True)
        self._reset_translation_lines()
        if self.translation_label.text():
            self.translation_label.setText("")
        self._set_translation_rows()
        self.update_labels_visibility()

    def _reset_translation_lines(self):
        """把"上一句 + 当前句"那套状态清干净（切模式、重开一轮、清空译文时用）

        只清状态、不动标签文本：调用方各有各的写法（`clear_translation` 要把标签
        清空，`reset_reveal_layout` 只是重排）。
        """
        self._translation_prev = ""
        self._translation_current = ""
        self._translation_current_final = False
        self._translation_key = None

    def set_text(self, original_text="", translation_text=""):
        """设置预览文本"""
        # 设置标签文本
        if original_text is not None:
            self._set_sentence_text(self.original_label, original_text)

        if translation_text is not None:
            # 预览是一句定死的话，不参与"上一句"那套翻页（见 `_update_translation_line`）：
            # 不清掉的话，预览之后第一句真译文的 key/整句标记会和它对上/对不上地乱翻页
            self._reset_translation_lines()
            self._translation_current = translation_text
            self._set_sentence_text(self.translation_label, translation_text)

        # 确保标签高度正确
        self.adjustLabelHeights()

        # 更新标签可见性
        self.update_labels_visibility()

        # 确保窗口可见
        if not self.isVisible():
            self.show()

        # 窗口按内容收/放（预览长句折行时撑高；用户自己定过高度就按他的来）
        self._fit_window_height()
    
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
        """字幕窗口高度设置变更（用户在设置里明确改的高度：锁定，不再自动贴内容）"""
        # 保存高度到实例变量
        self.window_height = height
        self._lock_window_height(height)

        # 保存设置到配置
        from config import config
        config.set("window_height", height)
        # 强制同步到文件
        config.sync_to_file()

        # 直接应用新高度(保持当前宽度)
        current_width = self.width()
        self.resize(current_width, height)
        # 高度是用户定的：多出来的空间三处平分（见 `_apply_row_gaps`）
        self._apply_row_gaps(height)

        if DEBUG_MODE:
            print(f"字幕窗口高度设置: {height}px")

    def _lock_window_height(self, height):
        """记下用户明确指定的高度：之后 `_fit_window_height` 不再把它拉回内容高度

        同时把高度记进 `self.window_height`（拖右下角这条路上 `resize` 重写没被走到，
        不记的话 `_fit_window_height` 会拿旧值把窗口拉回去）。已经锁上就直接返回：
        用户拖动时每个像素都会发一个 resizeEvent，不必每个都写一遍配置文件。
        """
        from config import config
        self.window_height = height
        if not self.window_height_auto:
            return
        self.window_height_auto = False
        config.set("window_height_auto", False)

    def resize(self, *args, **kwargs):
        """重写resize方法以确保尺寸变更时更新内部记录的尺寸并强制应用尺寸

        `_auto_resize_depth`（可重入计数）用来区分"这个尺寸是我们自己按内容算的"和
        "用户拖右下角拖出来的"——后者要锁定高度（见 `resizeEvent`）。注意 Qt 里
        `setFixedSize` 走的是 C++ 的 resize（`QWidget.resize` 不是虚函数），所以包住
        整个函数体，光包 `super().resize()` 盖不住它。
        """
        self._auto_resize_depth += 1
        try:
            return self._resize_impl(*args, **kwargs)
        finally:
            self._auto_resize_depth -= 1

    def _resize_impl(self, *args, **kwargs):
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
        self._fit_window_height()

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
        """根据字幕模式更新布局（当前没人调用，留着）

        注意：往布局里加的是**裁剪框**而不是标签本身——标签已经归裁剪框管了，
        把它塞回布局会从裁剪框里被"抢走"，逐词滚动就没了。
        """
        # 清空当前布局
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                self.layout().removeWidget(item.widget())

        # 确保所有标签都可见
        self.original_label.show()
        self.translation_label.show()

        # 根据字幕模式添加裁剪框
        if self.subtitle_mode == "original":
            self.layout().addWidget(self.original_view)
            self.translation_view.hide()
        elif self.subtitle_mode == "translated":
            self.layout().addWidget(self.translation_view)
            self.original_view.hide()
        elif self.subtitle_mode == "both":
            self.layout().addWidget(self.original_view)
            self.layout().addWidget(self.translation_view)

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

        # 高度变了：三处间隙跟着重摆（用户把窗口拖高时，多出来的空间三处平分，
        # 而不是全堆在原文和译文中间）。按住鼠标拖右下角拖出来的尺寸才算"用户定的
        # 高度"——Qt 自己发的那种 resize（显示/隐藏过程中的尺寸对齐）不该把高度
        # 锁死，否则窗口就再也不跟着内容的多少收放了。
        if getattr(self, "subtitle_mode", None) is None:
            return  # 还在 __init__ 里，布局没搭好
        if (self._auto_resize_depth == 0
                and QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._lock_window_height(event.size().height())
        self._apply_row_gaps(event.size().height())

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
        
        # 确保标签高度正确，并按内容定窗口高度（`_fit_window_height` 里会用到
        # setFixedSize 那种精确尺寸；两行原文 + 译文比用户设的高度还高时按需撑高，
        # 不然第二行会被切掉）
        self.adjustLabelHeights()
        self._fit_window_height()
        # setFixedSize 走的是 C++ 的 resize：不套 `_auto_set_fixed_size` 的话，
        # 这一下会被当成"用户把窗口拖成了这个高度"，高度就再也不自动贴内容了
        self._auto_set_fixed_size(self.window_width,
                                  max(self.window_height, self._required_height()))

        # 应用后恢复可调整大小
        QApplication.processEvents()
        self.setMinimumSize(1, 1)
        self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX
        self._apply_row_gaps(self.height())
        
        # 更新位置
        self.update_position()
        
        if DEBUG_MODE:
            print(f"字幕窗口showEvent完成: 显示后尺寸 {self.width()}x{self.height()}")
    
    def hideEvent(self, event):
        """窗口藏起来时把没滚完的动画收掉：偏移归零，攒下的文本丢掉

        这里不能贴文本：`_set_reveal_text` 见窗口不可见会顺手把它 show 出来，字幕
        窗就关不掉了。丢掉的那句下一帧逐词刷新自然会补上。
        """
        super().hideEvent(event)
        self._stop_reveal_scroll(apply_pending=False)
        # 译文行不用 reset：文本没变，再显出来还得指着尾窗那一屏
        self._stop_translation_scroll()

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
        """一行文字占的高度

        逐词行（左对齐）正好一个行距：那种排版上下内边距是 0、文字第一行贴着框
        顶，盒子多出一个像素都会漏到原文和译文中间（之前按 `height() + 上下内边距`
        算，比行距高出一大截，中间就空出了好几行——这次要修的就是它）。

        整句通路（居中）得连上下内边距一起算：标签盒要是比"文字 + 内边距"还矮，
        字会被裁掉半截。
        """
        pitch = self._reveal_line_pitch(label)
        if label.alignment() & Qt.AlignmentFlag.AlignLeft:
            return pitch
        return pitch + 2 * int(self._label_vpadding(label))

    def _row_gap(self):
        """上、中、下三处间隙的基准值：按字号算，三处都用它

        行距的一半（原文、译文各一个行距，取小的那个），字号一改跟着变，不用手填。
        """
        pitches = [self._reveal_line_pitch(label)
                   for label in (self.original_label, self.translation_label)]
        pitches = [pitch for pitch in pitches if pitch > 0]
        if not pitches:
            return MIN_ROW_GAP
        return max(MIN_ROW_GAP, round(min(pitches) * ROW_GAP_RATIO))

    def _label_text_lines(self, label):
        """这个标签里的文本实际要占几行

        整句通路的文本可能折行，盒子得给够行数，不然长句会被裁掉；译文行走视口通路
        时更要紧——滚动距离就是按行数算的（见 `_sync_translation_scroll`），少算一行
        最后一截就露不出来。宽度还不知道时（窗口没排过版）按一行算。
        """
        text = label.text()
        if label.alignment() & Qt.AlignmentFlag.AlignLeft:
            # 左对齐的行左边还多一块留白（见 `_reveal_avail_width`）：按居中那套量会
            # 宽出一截、行数就少一行
            width = self._reveal_avail_width(label)
        else:
            width = label.width() - 2 * self._label_padding(label)
        if not text or width <= 1:
            return 1
        metrics = QFontMetrics(label.font())
        wrapped = metrics.boundingRect(QRect(0, 0, width, 0),
                                       Qt.TextFlag.TextWordWrap, text)
        return max(1, math.ceil(wrapped.height() / max(1, metrics.lineSpacing())))

    def _set_label_rows(self, label, lines, content_lines=None):
        """一个标签按几行留高度

        高度预算（`_label_line_height` × 行数）记在**裁剪框**上：窗口高度看的是它
        （`_required_height`），标签自己的高度由裁剪框给（`RevealViewport`）。两行
        模式下再把内容高度设成正好 2 × 行距——多出来的第三行露不出来，滚一行也正
        好把上一行整行送出框外。

        `lines` 是**框**里放几行（窗口高度看这个）；`content_lines` 是**内容**实际几行
        （滚动距离看这个），默认跟 `lines` 一样——原文行就是这么用的；译文行框封顶两
        行、内容按实际行数（见 `_set_translation_rows`）。
        """
        view = self._label_view(label)
        # 逐词行永远是"上一句\n当前句"两行，行数就是外面传进来的；整句通路的文本会
        # 折行，按实际行数给高度，免得被裁
        if not label.alignment() & Qt.AlignmentFlag.AlignLeft:
            lines = max(lines, self._label_text_lines(label))
        if content_lines is None:
            content_lines = lines
        budget = int(self._label_line_height(label) * lines)
        view.setMinimumHeight(budget)
        label.setMinimumHeight(0)  # 高度由裁剪框给，别留个下限挡着滚动
        # 只有正走逐词排版（左对齐）的那一行才按内容行数给标签高度：整句通路的文本
        # （含预览按钮）写进来时得让它铺满（内容高度 0），不然长句子会被裁掉
        if content_lines > 1 and label.alignment() & Qt.AlignmentFlag.AlignLeft:
            view.set_content_height(int(self._reveal_line_pitch(label) * content_lines))
        else:
            view.set_content_height(0)  # 标签填满裁剪框，偏移恒为 0

    def _rows_height(self):
        """当前可见的几行加起来多高（不含任何间隙）"""
        return sum(self._label_view(label).minimumHeight() for label in self._visible_labels())

    def _apply_row_gaps(self, window_height):
        """把上、中、下三处间隙摆成一样宽

        三处都从 `_row_gap()` 起算；窗口比内容高时（用户把窗口调高了）多出来的那部分
        三处平分，而不是全堆在原文和译文之间——那样看着像排版错了，现在只是留白大一
        点。间隙加在裁剪框**外面**（布局的边距与间距），框顶跟着下移，上一行滚出去还
        是切得干干净净（做成标签的上内边距就会剩一截字挂在框顶，见 `_label_vpadding`）。
        """
        layout = self.centralWidget().layout() if self.centralWidget() else None
        if layout is None:
            return
        gap = max(self._row_gap(), (int(window_height) - self._rows_height()) // 3)
        self._row_gap_current = gap
        layout.setContentsMargins(LAYOUT_MARGIN, gap, LAYOUT_MARGIN, gap)
        layout.setSpacing(gap)

    def adjustLabelHeights(self):
        """根据当前字体调整各行的盒高，并把三处间隙重摆一遍

        原文行在逐词模式下要放两行（上一句 + 当前句），高度按两行算——窗口高度
        不够时由 `_fit_window_height` 把窗口撑高，不然第二行会被切掉。关掉逐词之后
        原文走整句通路，也得按**实际折行数**给高度：`_set_label_rows` 那个"按实测
        折行数兜底"只对非左对齐的标签生效，而原文行现在是左对齐的（见
        `_set_sentence_text`），不在这儿量一次，折成两行的长句会被裁成一行。
        间隙依赖窗口高度（多出来的空间三处平分），所以这里先按当前高度摆一次，
        `_fit_window_height` 改了高度会再摆一次。
        """
        lines = 2 if self._reveal_two_lines() else max(
            1, self._label_text_lines(self.original_label))
        self._set_label_rows(self.original_label, lines)
        # 译文行：框封顶两行、超出往上滚；不归译文管时（"不翻译"/"仅显示原文"）还是
        # 老样子一行、居中
        self._set_translation_rows()
        self._apply_row_gaps(self.height())

        if DEBUG_MODE:
            print(f"调整标签高度: 原文高度={self.original_view.minimumHeight()}({lines}行), "
                  f"译文高度={self.translation_view.minimumHeight()}, "
                  f"三处间隙={self._row_gap_current}")

    def _required_height(self):
        """内容正好放得下需要的高度 = 三处间隙（基准值）+ 各可见行"""
        return self._rows_height() + 3 * self._row_gap()

    def _fit_window_height(self):
        """按内容调窗口高度：默认贴着内容走，用户明确设过高度才按他设的来

        用户没设过高度（`window_height_auto`）时高度 = 内容需要的高度，并把算出来的
        值写回 `window_height`——否则配置文件里那个"上次自动算出来的高度"会一直被当
        成用户的要求，内容变小了窗口也不跟着收，下面挂一大片空白，多出来的空间还被
        摊到原文和译文之间（这正是"中间空了好几行"的由来）。用户自己在设置里改高度、
        或拖右下角改了高度之后，就按他的来（`_apply_row_gaps` 把多出来的空间三处平分）。
        """
        if not self.isVisible():
            return
        required = self._required_height()
        if self.window_height_auto or self.window_height < required:
            height = required
            self.window_height = height  # 写回，别让旧值下次又被当成用户的要求
        else:
            height = self.window_height
        if height != self.height():
            self.resize(self.window_width, height)
            self.update_position()
        self._apply_row_gaps(height)

    def _auto_set_fixed_size(self, width, height):
        """我们自己的精确尺寸（`setFixedSize`）——期间来的 resizeEvent 不算"用户拖的"

        Qt 里 `setFixedSize` 走的是 C++ 的 resize（`QWidget.resize` 不是虚函数），
        到不了 `resize` 那个重写里，`_auto_resize_depth` 也就盖不住它。平时这么一下
        本来也不会被当成"用户拖的"（`resizeEvent` 还要看鼠标键按着没有），但用户正好
        按着鼠标的时候（比如刚拖完右下角）就会认错，所以这里也记一笔深度（见
        `_lock_window_height`）。
        """
        self._auto_resize_depth += 1
        try:
            self.setFixedSize(width, height)
        finally:
            self._auto_resize_depth -= 1
