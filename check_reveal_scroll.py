"""检查原文两行 + 换句向上滚一行是否真的对（离屏跑，不需要音频/Whisper）

用法：
    python check_reveal_scroll.py            # 用固定的测试字号/窗口大小（14/19/1000×131）
    python check_reveal_scroll.py --live     # 不覆盖字号/字体/窗口大小，直接验 settings.json 里那套

直接往 `SubtitleWindow.set_original_words` 喂一串脚本化的句子（词一个个到），每到
关键时刻把字幕窗 `grab()` 成图片扫一遍像素，用"文字行（ink band）的位置"判断几何
对不对：

- 静止时正好两行文字，行距 = `QFontMetrics.lineSpacing()`；
- 第一行贴着裁剪框顶边（上面不留内边距），逐词增长时两行位置一动不动；
- 上/中/下三处间隙一样宽、且按字号算（`ROW_GAP_RATIO` × 行距）：窗口高度正好等于
  "三处间隙 + 各行"，不夹着多余的空白；字号改大间隙跟着变大，用户把窗口拉高时多
  出来的空间三处平分（不是全堆在原文和译文中间）；
- 留白：第一行最左文字像素落在"布局左边距 + 内边距 + `REVEAL_LEFT_MARGIN`"上（间隙
  加在裁剪框外面，见 `SubtitleWindow._apply_row_gaps`；加在框里会让上一行滚不干净）；
- 第一句换第二句时不滚（那时框里只有一行，滚了会空一下），第二句起才滚；
- 滚动过程中不超过两行、位置只往上走，滚完停在同一位置（接缝不跳）；
- 目标语言选"不翻译"时也是两行；
- 译文行按同一套几何（左对齐 + 视口）：折的比两行少就按实际行数给盒（一行译文一个行距
  高），超过两行就**不再撑高窗口**、内容整体上滚，屏幕上留的永远是最后两行（偏移 =
  (行数 − 2) × 行距）；滚动是滑上去的（不是瞬移）；切走模式或清空译文后偏移归零。

只读 settings.json，绝不写：要改的配置项直接写 `config.settings`（内存里），不走
`config.set`。（唯一的写是 `config` 导入时补齐缺失的默认项。）
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 必须赶在导入 PySide6 之前

from PySide6.QtCore import Qt, QPoint  # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from config import config  # noqa: E402
from gui.subtitle_window import (  # noqa: E402
    SubtitleWindow, REVEAL_SCROLL_MS, REVEAL_LEFT_MARGIN,
    ROW_GAP_RATIO, MIN_ROW_GAP, TRANSLATION_ROWS, MAX_TRANSLATION_SCROLL_MS,
)

# 测试用的三句话（英文，跟真实场景一致）
S1 = "alpha bravo charlie delta echo"
S2 = "foxtrot golf hotel india juliet"
S3 = "kilo lima mike november oscar"

# 文字行位置比较的公差：同一个字体的两行里，"最高那个字"是升部还是 x 高会差一两
# 个像素（升部字母之间也不一样高），几何对不对看 1px 就够。
TOL = 1

# 左右留白比较的公差：字形在字身框里的左右边距随字体不同（黑体的汉字几乎贴边、
# Arial 的拉丁字母留一点空），同样一个左边界量出来会差几个像素。
LEFT_TOL = 4


def use_config(**values):
    """只在内存里改配置（不写 settings.json）——这脚本不该动用户的设置"""
    for key, value in values.items():
        config.settings[key] = value


def ink_bands(window):
    """扫一遍窗口，返回有文字的行区间 [(y0, y1), ...]（y 是窗口坐标）

    背景是半透明的黑（alpha 150），文字是不透明的白/黄。所以"alpha 接近满"的像素
    就是文字（含抗锯齿边缘）。一行里只要有一个文字像素，这行就算在这一段里。
    """
    image = window.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    buffer = image.constBits()

    bands = []
    current = None
    for y in range(height):
        row = y * stride
        has_ink = False
        for x in range(width):
            # ARGB32：每像素 4 字节，第 4 个是 alpha
            if buffer[row + x * 4 + 3] >= 250:
                has_ink = True
                break
        if has_ink and current is None:
            current = y
        elif not has_ink and current is not None:
            bands.append((current, y))
            current = None
    if current is not None:
        bands.append((current, height))
    return bands


def tops(bands):
    """每一行文字的顶边（行距/位置都在这个量上看）"""
    return [y0 for y0, _ in bands]


def ink_left(window, band):
    """某一行文字里最左边那个文字像素的 x（看左边留白留够没有）"""
    image = window.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    stride = image.bytesPerLine()
    buffer = image.constBits()
    y0, y1 = band
    for x in range(image.width()):
        for y in range(y0, y1):
            if buffer[y * stride + x * 4 + 3] >= 250:
                return x
    return None


def same_tops(a, b, tol=TOL):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def gaps(window):
    """上、中、下三处间隙（窗口坐标下的像素数）

    上 = 原文裁剪框顶边离窗口顶边；中 = 原文框底边到译文框顶边；下 = 译文框底边到窗口
    底边。"原文和译文之间空好几行"就是中间这一处的锅，三处该一样宽。
    """
    original = window.original_view.mapTo(window, QPoint(0, 0))
    translation = window.translation_view.mapTo(window, QPoint(0, 0))
    top = original.y()
    middle = translation.y() - (original.y() + window.original_view.height())
    bottom = window.height() - (translation.y() + window.translation_view.height())
    return top, middle, bottom


def base_gap(window):
    """三处间隙的基准值（按字号算的那个）：`ROW_GAP_RATIO` × 较小的行距"""
    pitches = [QFontMetrics(label.font()).lineSpacing()
               for label in (window.original_label, window.translation_label)]
    return max(MIN_ROW_GAP, round(min(pitches) * ROW_GAP_RATIO))


class Checker:
    """小断言收集器：全跑完再报，免得第一个错把后面的检查全挡掉"""

    def __init__(self):
        self.failures = []
        self.checks = 0

    def check(self, ok, message):
        self.checks += 1
        print(f"  [{'通过' if ok else '不通过'}] {message}")
        if not ok:
            self.failures.append(message)

    def report(self):
        print("-" * 60)
        if self.failures:
            print(f"{self.checks} 项检查里 {len(self.failures)} 项不通过：")
            for failure in self.failures:
                print(f"  - {failure}")
            return 1
        print(f"{self.checks} 项检查全部通过")
        return 0


def main():
    # 逐词/模式/目标语言无论如何都要摆成"两行逐词"那套；字号、字体、窗口大小默认
    # 用固定值（结果好对照），`--live` 则原样用 settings.json 里的
    settings = {"word_by_word_enabled": True, "subtitle_mode": "both",
                "target_language": "zh", "position": "bottom"}
    if "--live" not in sys.argv[1:]:
        # `window_height_auto` 也要钉住：它是"用户拖过窗口右下角"之后被写进
        # settings.json 的运行态（本机实测就是 false）。不钉的话这一项从用户的配置文件
        # 里随机读，脚本里的 window_height=131 就变成"故意定的高度"，"窗口贴着内容"
        # 那几项必然不通过 —— 而且和代码有没有改过毫无关系。
        settings.update(original_font_size=14, translation_font_size=19,
                        original_font_family="Arial", translation_font_family="黑体",
                        window_width=1000, window_height=131, window_height_auto=True)
    use_config(**settings)
    # 高度是用户定的（window_height_auto=False）时，"窗口正好贴着内容"这类检查没有
    # 意义：那时窗口高度本来就该由用户说了算，多出来的空间三处平分。--live 下会碰到。
    fit_checks_apply = bool(config.get("window_height_auto", True))

    QApplication.instance() or QApplication([])
    window = SubtitleWindow()
    window.show()
    QTest.qWait(200)  # 让布局/显示事件走完

    checker = Checker()

    def check_fit(message):
        """窗口高度是不是正好贴着内容

        高度由用户定的时候（`window_height_auto=false`：他在设置里改过高度，或拖过
        窗口右下角）这一项不适用——那时窗口本来就该保持他定的高度，多出来的空间三处
        平分，而不是被收掉。
        """
        if not fit_checks_apply:
            print(f"  [跳过] {message}（window_height_auto=false，高度是用户定的）")
            return
        checker.check(abs(window.height() - window._required_height()) <= 1, message)

    pitch = QFontMetrics(window.original_label.font()).lineSpacing()
    view_top = window.original_view.mapTo(window, QPoint(0, 0)).y()
    print(f"原文行距（QFontMetrics.lineSpacing）: {pitch}px")
    print(f"裁剪框在窗口里的顶边: y={view_top}")
    print(f"滚动时长: {REVEAL_SCROLL_MS}ms")
    print("-" * 60)

    # 1) 第一句：框里只有一行，贴着裁剪框顶边
    window.set_original_words(S1, "", 1)
    QTest.qWait(50)
    first = ink_bands(window)
    print(f"第一句静止: {first}（裁剪框内容高度 "
          f"{window.original_view._content_height}px = 2 × 行距）")
    checker.check(len(first) == 1, f"第一句只有一行文字（实测 {len(first)} 行）")
    # 文字顶边离框顶的距离 = 字体自己的行内空白（Arial 14 实测 9px：lineSpacing 22
    # 比 height() 19 多的那点 + 升部到字面的空当）。要是内边距还留着 12px，这个差
    # 会是 21 上下——用 14 当界就能分清"顶边对齐"和"还垫着内边距"。
    checker.check(0 <= first[0][0] - view_top <= 14,
                  f"第一行贴着裁剪框顶边（框顶 y={view_top}，文字顶 y={first[0][0]}，"
                  f"差 {first[0][0] - view_top}px；留着 12px 内边距的话是 21px）")
    # 1b) 留白：上/中/下三处间隙一样宽（不能中间空出一大块），按字号算，
    #     窗口高度正好等于"三处间隙 + 各行"，不夹多余的空白
    top_gap, middle_gap, bottom_gap = gaps(window)
    expected_gap = base_gap(window)
    print(f"三处间隙: 上={top_gap} 中={middle_gap} 下={bottom_gap}"
          f"（基准 {window._row_gap()}，期望 {expected_gap}）")
    checker.check(top_gap == middle_gap == bottom_gap,
                  f"上/中/下三处间隙一样宽（上={top_gap} 中={middle_gap} 下={bottom_gap}）")
    checker.check(window._row_gap() == expected_gap,
                  f"间隙按字号算 = {ROW_GAP_RATIO} × 较小行距（期望 {expected_gap}，"
                  f"实测 {window._row_gap()}）")
    check_fit(f"窗口高度正好是内容需要的高度，没有多余空白（窗口 {window.height()}，"
              f"需要 {window._required_height()}）")
    label = window.original_label
    text_left = window.original_view.mapTo(window, QPoint(0, 0)).x() \
        + window._label_padding(label) + REVEAL_LEFT_MARGIN
    left = ink_left(window, first[0])
    print(f"第一行最左文字像素: x={left}（内边距 {window._label_padding(label)} + "
          f"左边留白 {REVEAL_LEFT_MARGIN} → 期望 ≥ {text_left}）")
    checker.check(left is not None and 0 <= left - text_left <= 4,
                  f"文字从左边留白之后开始（期望 x≈{text_left}，实测 x={left}；"
                  f"字面自带的左边空当最多 4px）")

    # 2) 换到第二句：这时框里只有一行，不该滚——第二句直接长在下面
    window.set_original_words("foxtrot", S1, 2)
    QTest.qWait(50)
    grew = ink_bands(window)
    print(f"第二句开始: {grew}")
    checker.check(len(grew) == 2, f"第二句开始后正好两行（实测 {len(grew)} 行）")
    checker.check(window.original_view._offset == 0,
                  "第一句换第二句没有滚动（框里只有一行，滚了会空一下）")
    checker.check(grew[0][0] == first[0][0],
                  f"第一行没挪窝（第一句顶 y={first[0][0]} → 现在 y={grew[0][0]}）")
    checker.check(abs((grew[1][0] - grew[0][0]) - pitch) <= TOL,
                  f"两行行距 {pitch}px（实测 {grew[1][0] - grew[0][0]}）")

    # 3) 同一句里词继续往右边长：两行位置一动不动
    window.set_original_words("foxtrot golf hotel", S1, 2)
    QTest.qWait(50)
    grown = ink_bands(window)
    print(f"第二句长到三个词: {grown}")
    checker.check(same_tops(tops(grown), tops(grew)),
                  f"逐词增长时两行位置不变（{tops(grew)} → {tops(grown)}）")

    # 4) 换到第三句：这次框里已经有两行了 → 整块上滚一行
    before = ink_bands(window)
    window.set_original_words("kilo", S2, 3)
    frames = [("0ms", ink_bands(window))]
    elapsed = 0
    step = 20
    while elapsed < REVEAL_SCROLL_MS + 60:
        QTest.qWait(step)
        elapsed += step
        frames.append((f"{elapsed}ms", ink_bands(window)))
    for label, bands in frames:
        print(f"  滚动 {label}: {bands}")

    mid_frames = frames[1:-1]
    after = frames[-1][1]
    checker.check(all(len(bands) <= 2 for _, bands in frames),
                  "滚动全程不超过两行（第三行被裁剪框切掉）")
    checker.check(window.original_view._offset == 0, "滚完偏移归零")
    checker.check(len(after) == 2, f"滚完正好两行（实测 {len(after)} 行）")
    checker.check(all(tops(bands) == sorted(tops(bands)) for _, bands in frames),
                  f"滚动中位置只往上走（中途 {mid_frames[len(mid_frames) // 2]}）")
    checker.check(same_tops(tops(after), tops(before)),
                  f"滚完停在滚动前的位置、不跳（滚动前 {tops(before)} → "
                  f"滚动后 {tops(after)}）")

    window.set_original_words("kilo lima mike", S2, 3)
    QTest.qWait(50)
    final = ink_bands(window)
    checker.check(same_tops(tops(final), tops(before)),
                  f"滚完继续逐词长，位置依旧不变（{tops(final)}）")
    checker.check("\n" in window.original_label.text(),
                  "原文标签里确实是两行文本（上一句 + 当前句）")
    checker.check(bool(window.original_label.alignment() & Qt.AlignmentFlag.AlignTop),
                  "逐词行是顶对齐（滚一行才能把上一行整行送出去）")

    # 5) 滚动没跑完就切模式：动画要收掉，偏移归零
    window.set_original_words("quebec", S3, 4)
    QTest.qWait(REVEAL_SCROLL_MS // 3)
    window.set_subtitle_mode("original")
    QTest.qWait(30)
    checker.check(window.original_view._offset == 0, "切模式时滚动被收掉、偏移归零")

    # 6) "不翻译"模式：屏幕上只剩原文，照样两行
    use_config(target_language="none")
    window.set_subtitle_mode("both")
    window.reset_reveal_layout()
    window.set_original_words(S1, "", 11)
    QTest.qWait(50)
    window.set_original_words("foxtrot", S1, 12)
    QTest.qWait(50)
    disabled_bands = ink_bands(window)
    print(f"不翻译模式: {disabled_bands}, 译文行可见={window.translation_label.isVisible()}")
    checker.check(len(disabled_bands) == 2,
                  f"不翻译模式也是两行（实测 {len(disabled_bands)} 行）")
    checker.check(not window.translation_label.isVisible(), "不翻译模式译文行是藏着的")

    # 7) 关掉逐词显示：退回整句通路，但**照样左对齐**（跟逐词行、译文行一个规矩）；
    #    一行文本时标签填满裁剪框、不裁剪
    use_config(target_language="zh", word_by_word_enabled=False)
    window.reset_reveal_layout()
    window.set_subtitle_mode("both")
    window.update_text(original_text="THIS IS A WHOLE SENTENCE",
                       translation_text="这是一整句译文")
    QTest.qWait(50)
    sentence_bands = ink_bands(window)
    print(f"整句通路: {sentence_bands}")
    checker.check(window.original_view._content_height == 0
                  and window.translation_view._content_height == 0,
                  "整句通路：两个裁剪框的内容高度都是 0（标签填满，不裁剪）")
    checker.check(bool(window.original_label.alignment() & Qt.AlignmentFlag.AlignLeft),
                  "整句通路：原文也是左对齐（不再居中——原文行只有一种排版）")
    checker.check(not (window.original_label.alignment() & Qt.AlignmentFlag.AlignTop),
                  "整句通路：原文不是顶对齐（那是逐词两行模式才要的）")
    original_left = ink_left(window, sentence_bands[0]) if sentence_bands else None
    original_pad = window._label_padding(window.original_label)
    view_left = window.original_view.mapTo(window, QPoint(0, 0)).x()
    print(f"整句原文最左文字: x={original_left}（期望 ≥ "
          f"{view_left + original_pad + REVEAL_LEFT_MARGIN}）")
    checker.check(original_left is not None
                  and 0 <= original_left - (view_left + original_pad + REVEAL_LEFT_MARGIN) <= LEFT_TOL,
                  f"整句原文从左边留白之后开始（实测 x={original_left}）")
    checker.check(len(sentence_bands) == 2, f"整句通路原文和译文都看得见（{len(sentence_bands)} 行）")
    sentence_gaps = gaps(window)
    checker.check(sentence_gaps[0] == sentence_gaps[1] == sentence_gaps[2],
                  f"整句通路三处间隙也还是一样宽（{sentence_gaps}）")
    checker.check(int(QFontMetrics(window.original_label.font()).lineSpacing()) == pitch,
                  "整句通路行距不变")

    # 7b) 整句原文折成两行：高度得按**实测折行数**给（左对齐的标签没有"按折行数兜底"
    #     那一手，见 `adjustLabelHeights`），窗口跟着长高——不然后半截会被裁掉
    one_line_required = window._required_height()
    wrapped_sentence = "THIS IS A WHOLE SENTENCE THAT IS LONG ENOUGH TO WRAP INTO " \
                       "TWO LINES FOR SURE, AND MAYBE EVEN LONGER THAN THAT"
    while True:
        window.update_text(original_text=wrapped_sentence, translation_text="")
        lines_wrapped = window._label_text_lines(window.original_label)
        if lines_wrapped >= 2 or len(wrapped_sentence) > 4000:
            break
        wrapped_sentence += " AND IT KEEPS GOING ON AND ON"
    QTest.qWait(50)
    wrapped_bands = ink_bands(window)
    print(f"整句原文折行: {lines_wrapped} 行，行盒 "
          f"{window.original_view.minimumHeight()}px（行距 {pitch}px），文字行 {wrapped_bands}")
    checker.check(lines_wrapped >= 2, f"这句原文确实折成了多行（实测 {lines_wrapped} 行）")
    checker.check(window.original_view.minimumHeight() >= lines_wrapped * pitch,
                  f"原文行盒按实测折行数给高度（盒 "
                  f"{window.original_view.minimumHeight()}px ≥ {lines_wrapped * pitch}px）")
    checker.check(window.original_view._content_height == lines_wrapped * pitch,
                  f"内容高度 = 行数 × 行距（{window.original_view._content_height}px），"
                  f"偏移才是 0")
    checker.check(window.original_view._offset == 0,
                  f"整句原文不滚动（偏移 {window.original_view._offset}px）")
    checker.check(len(wrapped_bands) == lines_wrapped,
                  f"折出来的每一行都露得出来、没被裁（实测 {len(wrapped_bands)} 行，"
                  f"该有 {lines_wrapped} 行）")
    checker.check(window._required_height() > one_line_required,
                  f"行数变多，窗口需要的高度跟着涨（{one_line_required} → "
                  f"{window._required_height()}px）")
    check_fit(f"窗口高度贴在内容上（窗口 {window.height()}，需要 "
              f"{window._required_height()}）")
    window.update_text(original_text="THIS IS A WHOLE SENTENCE",
                       translation_text="这是一整句译文")
    QTest.qWait(50)

    # 8) 再打开逐词：两行模式要能回来
    use_config(word_by_word_enabled=True)
    window.clear_translation()  # 上一节留下的整句译文先撤掉，免得扫进文字行里
    window.reset_reveal_layout()
    window.set_original_words(S1, "", 21)
    window.set_original_words("foxtrot", S1, 22)
    QTest.qWait(50)
    checker.check(window.original_view._content_height == 2 * pitch,
                  f"重新打开逐词后内容高度回到两行（{window.original_view._content_height}px）")
    checker.check(len(ink_bands(window)) == 2, "重新打开逐词后又是两行文字")

    # 8b) 译文行和原文行一个规矩：左对齐，行盒最多两行（见 `_set_translation_rows`）
    long_translation = ("这是一句很长很长的译文，一千像素宽也放不下，必须折成两行才"
                        "显示得完，用来检查行盒有没有按行数给够高度。")
    window.update_text(translation_text=long_translation)
    QTest.qWait(50)
    wrapped = ink_bands(window)
    translation_pitch = QFontMetrics(window.translation_label.font()).lineSpacing()
    lines_2 = window._label_text_lines(window.translation_label)
    required_2line = window._required_height()
    print(f"译文折行: {wrapped}，{lines_2} 行，行盒 {window.translation_view.minimumHeight()}px"
          f"（行距 {translation_pitch}px）")
    checker.check(lines_2 == 2, f"这句译文要占两行（实测 {lines_2} 行）")
    checker.check(bool(window.translation_label.alignment() & Qt.AlignmentFlag.AlignLeft),
                  "译文行是左对齐（和原文行一样）")
    checker.check(bool(window.translation_label.alignment() & Qt.AlignmentFlag.AlignTop),
                  "译文行是顶对齐（尾窗滚动的前提）")
    checker.check(window.translation_view.minimumHeight() == lines_2 * translation_pitch,
                  f"译文行盒按 min(行数, {TRANSLATION_ROWS}) 给高度"
                  f"（{window.translation_view.minimumHeight()}px，期望 "
                  f"{lines_2 * translation_pitch}px）")
    checker.check(window.translation_view._content_height == lines_2 * translation_pitch,
                  f"内容高度按实际行数（{window.translation_view._content_height}px）")
    checker.check(window.translation_view._offset == 0, "两行还没超出框，不滚")
    checker.check(len(wrapped) == 2 + lines_2,
                  f"原文两行 + 译文两行都看得见、没被裁（实测 {len(wrapped)} 行文字）")
    checker.check(wrapped[-1][1] - wrapped[-1][0] >= wrapped[-2][1] - wrapped[-2][0] - 2,
                  f"译文最后一行没被裁掉半截（最后一行 {wrapped[-1][1] - wrapped[-1][0]}px vs "
                  f"上一行 {wrapped[-2][1] - wrapped[-2][0]}px）")
    check_fit(f"译文折成两行后窗口跟着变高（窗口 {window.height()}，需要 "
              f"{window._required_height()}）")
    checker.check(abs(ink_left(window, wrapped[-1]) - ink_left(window, wrapped[1])) <= LEFT_TOL,
                  f"译文行和原文行的左边界对齐（译文 {ink_left(window, wrapped[-1])}px vs "
                  f"原文 {ink_left(window, wrapped[1])}px）")

    # 8c) 译文超过两行：框还是两行高，内容整体上滚，屏幕上留的是最后两行
    scrolled_text = long_translation + ("再多说几句，让这句译文长出第三行来，"
                                        "看看超出的部分是不是往上滚出去了。")
    while True:
        window.update_text(translation_text=scrolled_text)
        lines_n = window._label_text_lines(window.translation_label)
        if lines_n >= 3:
            break
        if len(scrolled_text) > 4000:      # 字体环境差太多时别把脚本挂在这儿
            break
        scrolled_text += "再加一句，保证它一定能折到三行以上。"
    QTest.qWait(100 + MAX_TRANSLATION_SCROLL_MS)
    scrolled = ink_bands(window)
    translation_view_top = window.translation_view.mapTo(window, QPoint(0, 0)).y()
    translation_view_bottom = translation_view_top + window.translation_view.height()
    print(f"译文超两行: {lines_n} 行，行盒 {window.translation_view.minimumHeight()}px，"
          f"内容 {window.translation_view._content_height}px，偏移 {window.translation_view._offset}px"
          f"，文字行 {scrolled}（框 {translation_view_top}~{translation_view_bottom}）")
    checker.check(lines_n >= 3, f"这一句译文至少三行（实测 {lines_n} 行）")
    checker.check(window.translation_view.minimumHeight() == TRANSLATION_ROWS * translation_pitch,
                  f"超两行时行盒仍是两行高（{window.translation_view.minimumHeight()}px，"
                  f"期望 {TRANSLATION_ROWS * translation_pitch}px）")
    checker.check(window.translation_view._content_height == lines_n * translation_pitch,
                  f"内容高度按实际行数（{window.translation_view._content_height}px，"
                  f"期望 {lines_n * translation_pitch}px）")
    checker.check(window.translation_view._offset == (lines_n - TRANSLATION_ROWS) * translation_pitch,
                  f"滚了 {lines_n - TRANSLATION_ROWS} 个行距（偏移 "
                  f"{window.translation_view._offset}px，期望 "
                  f"{(lines_n - TRANSLATION_ROWS) * translation_pitch}px）")
    checker.check(abs(window._required_height() - required_2line) <= 1,
                  f"多出来的行不撑高窗口（需要 {window._required_height()}px，"
                  f"两行时是 {required_2line}px）")
    checker.check(len(scrolled) == 2 + TRANSLATION_ROWS,
                  f"屏幕上只剩原文两行 + 译文两行（实测 {len(scrolled)} 行文字）")
    tail_tops = tops(scrolled[2:]) if len(scrolled) > 2 else [-1]
    checker.check(abs(tail_tops[0] - translation_view_top) <= TOL,
                  f"露出来的是最后两行：第一行正好贴住译文框顶（{tail_tops[0]} vs "
                  f"框顶 {translation_view_top}）")
    checker.check(scrolled and scrolled[-1][1] <= translation_view_bottom + TOL,
                  f"最后一行整行都在框里（底 {scrolled[-1][1] if scrolled else '-'} ≤ "
                  f"框底 {translation_view_bottom}）")

    # 8d) 流式那样一行一行长出来：1 行给 1 行盒，2 行给 2 行盒，再多才滚
    window.clear_translation()
    QTest.qWait(50)
    checker.check(window.translation_view.minimumHeight() == translation_pitch
                  and window.translation_view._content_height == 0
                  and window.translation_view._offset == 0,
                  f"一行译文：一行高的盒、内容高度 0（标签填满）、不滚"
                  f"（盒 {window.translation_view.minimumHeight()}px，"
                  f"内容 {window.translation_view._content_height}px，"
                  f"偏移 {window.translation_view._offset}px）")
    required_1line = window._required_height()
    window.update_text(translation_text=long_translation)
    QTest.qWait(50)
    checker.check(window.translation_view._offset == 0
                  and window.translation_view._content_height == 2 * translation_pitch,
                  f"长到两行：盒高两行、不滚（偏移 {window.translation_view._offset}px）")
    checker.check(abs(window._required_height() - required_2line) <= 1
                  and abs(required_2line - required_1line - translation_pitch) <= 1,
                  f"从 1 行长到 2 行时窗口正好高一个行距"
                  f"（{required_1line} → {window._required_height()}px，"
                  f"行距 {translation_pitch}px）")
    window.update_text(translation_text=scrolled_text)
    QTest.qWait(100)
    mid_offset = window.translation_view._offset
    QTest.qWait(MAX_TRANSLATION_SCROLL_MS + 100)
    end_offset = window.translation_view._offset
    print(f"增长到 {lines_n} 行时滚动：中途偏移 {mid_offset}px → 终点 {end_offset}px")
    checker.check(0 < mid_offset < end_offset,
                  f"超出的部分是滑上去的、不是瞬移（中途 {mid_offset}px → 终点 {end_offset}px）")

    # 8e) 切走 / 清空：偏移必须归零（留着会把下一句短译文顶出框外）
    window.set_subtitle_mode("original")
    QTest.qWait(30)
    checker.check(window.translation_view._offset == 0
                  and window.translation_view._content_height == 0,
                  f"切到「仅显示原文」：译文行的偏移和内容高度都归零"
                  f"（偏移 {window.translation_view._offset}px，"
                  f"内容 {window.translation_view._content_height}px）")
    window.set_subtitle_mode("both")
    window.update_text(translation_text=scrolled_text)
    QTest.qWait(100 + MAX_TRANSLATION_SCROLL_MS)
    checker.check(window.translation_view._offset > 0, "切回两行模式后滚动位置又对上了")
    window.clear_translation()
    QTest.qWait(30)
    checker.check(window.translation_view._offset == 0, "清空译文后偏移归零")
    window.set_original_words("foxtrot golf", S1, 22)  # 把译文行清掉，回到纯原文
    QTest.qWait(50)

    # 9) 字号变大 → 间隙一起变大（自适应），窗口高度还是"三处 + 各行"
    small_gap = window._row_gap()
    bigger_font = QFont(config.get("original_font_family", "Arial"),
                        window.original_label.font().pointSize() + 8)
    window.original_label.setFont(bigger_font)
    window.adjustLabelHeights()
    window._fit_window_height()
    QTest.qWait(50)
    big_window_gaps = gaps(window)
    print(f"原文 {bigger_font.pointSize()} 号字: 行距 "
          f"{QFontMetrics(bigger_font).lineSpacing()}px, 间隙 {window._row_gap()}px"
          f"（原来 {small_gap}px）, 窗口高 {window.height()}px")
    checker.check(window._row_gap() > small_gap,
                  f"字号变大，间隙跟着变大（{small_gap} → {window._row_gap()}）")
    checker.check(big_window_gaps[0] == big_window_gaps[1] == big_window_gaps[2],
                  f"换字号后三处间隙照样一样宽（{big_window_gaps}）")
    check_fit(f"换字号后窗口还是贴着内容（窗口 {window.height()}，"
              f"需要 {window._required_height()}）")

    # 10) 用户把窗口拉高：多出来的空间三处平分，而不是全堆在原文和译文中间
    window.resize(window.width(), window.height() + 90)
    QTest.qWait(50)
    tall_gaps = gaps(window)
    print(f"窗口拉高 90px 后: 三处间隙 {tall_gaps}（基准 {window._row_gap()}）")
    checker.check(tall_gaps[0] == tall_gaps[1] == tall_gaps[2],
                  f"拉高后三处间隙仍然一样宽（{tall_gaps}）")
    checker.check(tall_gaps[1] > window._row_gap(),
                  f"多出来的空间分到了三处（上={tall_gaps[0]} > 基准 {window._row_gap()}），"
                  f"不是原样堆在中间")
    checker.check(window._row_gap_current - window._row_gap() >= 25,
                  f"多出来的 90px 是三处平分的（每处多 "
                  f"{window._row_gap_current - window._row_gap()}px，该在 30px 上下）")

    # 11) 「仅显示译文」：逐词原文一个字都不许上屏。以前它会"借"译文标签占位（那时
    #     原文行是藏着的），于是用户先看到一句原文——还穿着译文的颜色和字号——等译文
    #     回来再被顶掉。
    use_config(target_language="zh", word_by_word_enabled=True)
    window.reset_reveal_layout()
    window.set_subtitle_mode("both")
    window.clear_translation()
    window.set_original_words(S1, "", 41)
    window.set_original_words("foxtrot", S1, 42)
    QTest.qWait(50)
    window.set_original_words("golf", S2, 43)      # 换句 → 起一段上滚动画
    QTest.qWait(REVEAL_SCROLL_MS // 3)
    checker.check(window._scroll_anim is not None, "上滚动画正在跑（下一步看它被收掉）")
    window.set_subtitle_mode("translated")
    QTest.qWait(REVEAL_SCROLL_MS + 60)
    checker.check(window._scroll_anim is None and window._reveal_pending is None,
                  "切进「仅显示译文」：滚动收掉，攒在半路的半截文本也丢掉")
    checker.check(window.original_view._offset == 0,
                  f"滚动偏移归零（{window.original_view._offset}px）")
    checker.check(window.original_label.text() == "",
                  f"原文标签被清空（实测 {window.original_label.text()!r}）")

    window.set_original_words("alpha bravo", "", 51)
    QTest.qWait(50)
    checker.check(window.translation_label.text() == "",
                  f"逐词原文不再借译文标签占位（实测 "
                  f"{window.translation_label.text()!r}）")
    checker.check(window.original_label.text() == "",
                  f"原文标签也没写（实测 {window.original_label.text()!r}）")
    silent_bands = ink_bands(window)
    checker.check(silent_bands == [],
                  f"说话期间屏幕上不冒原文，等译文（实测 {silent_bands} 行文字）")

    window.update_text(translation_text="阿尔法 布拉沃")
    QTest.qWait(50)
    checker.check(window.translation_label.text() == "阿尔法 布拉沃",
                  f"整句译文到了才出现（实测 {window.translation_label.text()!r}）")
    checker.check(bool(window.translation_label.alignment() & Qt.AlignmentFlag.AlignLeft),
                  "译文行按译文视口排版（左对齐 + 溢出上滚）")
    checker.check(len(ink_bands(window)) == 1,
                  f"这时屏幕上只有译文那一行（实测 {ink_bands(window)}）")

    return checker.report()


if __name__ == "__main__":
    sys.exit(main())
