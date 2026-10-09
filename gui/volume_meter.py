from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPen


class VolumeMeter(QWidget):
    """分段式音量表（VU meter），显示 0.0~1.0 的音量等级"""

    def __init__(self, parent=None, tooltip="音量"):
        super().__init__(parent)
        self._level = 0.0
        self._segments = 24
        self.setFixedSize(120, 22)
        self.setToolTip(tooltip)

    def set_level(self, level):
        """设置音量等级（0.0~1.0）"""
        level = max(0.0, min(1.0, level))
        # 使用 sqrt 曲线，让较小的声音也可见
        display = level ** 0.5
        if abs(display - self._level) < 0.004:
            return
        self._level = display
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        inset = 2.0

        # 底色与边框：没有信号时也要看得见这是一个控件，
        # 否则未点亮的格子接近透明，无信号时就等于"没有音量控件"
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 3, 3)

        gap = 2
        track_w = w - inset * 2
        seg_w = (track_w - gap * (self._segments - 1)) / self._segments
        seg_h = h - inset * 2 - 2
        lit = int(round(self._level * self._segments))

        for i in range(self._segments):
            ratio = i / self._segments
            if ratio < 0.6:
                color = QColor(76, 175, 80)      # 绿色
            elif ratio < 0.85:
                color = QColor(255, 193, 7)      # 琥珀色
            else:
                color = QColor(244, 67, 54)      # 红色

            x = inset + i * (seg_w + gap)
            y = (h - seg_h) / 2
            if i < lit:
                painter.setBrush(color)
            else:
                # 未点亮的格子保持可见的灰底
                painter.setBrush(QColor(128, 128, 128, 110))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, y, seg_w, seg_h), 1.5, 1.5)

        painter.end()
