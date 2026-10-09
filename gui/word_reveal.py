"""逐词字幕：决定"此刻这一行该显示到哪个词"

字幕要跟着**听到的声音**走，而不是跟着识别结果到达的时刻走——识别结果总比语音
晚（模型要算完这一句），按到达时刻显示就只能整句一下子蹦出来。

办法是把两条时间轴对齐到同一个刻度上：**采集块号**（1 块 = 1024 样本 ≈ 64ms）。

- 每个词都有绝对起止块号（AudioManager 按"音频段起始块号 + 词在段内的秒数"换算好）
- 界面每隔一小会儿问一次 AudioManager："用户现在听到哪一块了？"
  （监听时是播放进度，没监听时就是实时采集）
- 播放位置越过某个词的起点，这个词就该出现；已经过去的一律立刻补齐，
  所以识别慢的时候字幕会"追赶"，不会卡住，也不会倒着走。

这样既不需要手动填延迟，也不会因为队列深浅变化而漂移——延迟是多少，
数一数还有多少块没播出去就知道了。
"""
from collections import OrderedDict, namedtuple

# 此刻该显示的一行：当前句已经念到的词 + 上一句的全文 + 属于哪一句话。
# previous_text 交给界面显示在上一行（两行原文，便于顺着上下文听，像 YouTube 那样）。
RevealLine = namedtuple('RevealLine', ['text', 'previous_text', 'utterance_id'])


class WordReveal:
    """把"识别出来的词"按播放进度一个个显示出来"""

    def __init__(self, max_segments=16):
        # utterance_id -> WordSegment。同一句话的最终结果会覆盖它的预览结果。
        self._segments = OrderedDict()
        self._max_segments = max_segments
        # 上一次交出去的内容（当前文本 + 上一句文本 + 句子号），一样就不用重画
        self._last_key = None

    def add_segment(self, segment):
        """收下一个片段（预览或最终结果）"""
        existing = self._segments.get(segment.utterance_id)
        if existing is not None and existing.is_final and not segment.is_final:
            # 已经有这句的最终结果了，迟到的预览不要覆盖它
            return
        self._segments[segment.utterance_id] = segment
        while len(self._segments) > self._max_segments:
            self._segments.popitem(last=False)

    def tick_line(self, play_chunk):
        """返回此刻该显示的内容（`RevealLine`）；没变化时返回 None

        选段规则：起点不晚于播放位置的、最近的那一段。效果是
        - 播放到某句话中间 → 显示这句话，词一个个冒出来
        - 一句话说完、下一句还没开始 → 继续显示上一句，画面不会闪空
        - 迟到的旧片段不会把新句子顶掉（按起始块号挑最近的）

        同时给出上一句的全文（`previous_text`），界面把它放在上一行当上下文。
        """
        if play_chunk is None:
            return None

        segment = self._pick_segment(play_chunk)
        if segment is None:
            # 播放位置还没到任何一句话的起点（刚开始录音，或在长静音里）
            return None

        words = [w.text for w in segment.words if w.start_chunk <= play_chunk]
        text = " ".join(words).strip()
        if not text:
            # 这句话刚开始、还一个词都没到显示时间：保持上一行，别闪空
            return None

        previous = self._pick_previous(segment)
        previous_text = " ".join(w.text for w in previous.words).strip() if previous else ""

        key = (text, previous_text, segment.utterance_id)
        if key == self._last_key:
            return None
        self._last_key = key
        return RevealLine(text, previous_text, segment.utterance_id)

    def tick(self, play_chunk):
        """只要文本的老接口（单测和"不关心排版"的调用方用）"""
        line = self.tick_line(play_chunk)
        return line.text if line else None

    def _pick_segment(self, play_chunk):
        """挑出播放位置对应的那一段：起点不晚于它的、最近的一段"""
        segment = None
        for candidate in sorted(self._segments.values(), key=lambda s: s.start_chunk, reverse=True):
            if candidate.start_chunk <= play_chunk:
                segment = candidate
                break
        return segment

    def _pick_previous(self, segment):
        """这一句之前的那一句：起点比它早、且离它最近的一段"""
        previous = None
        for candidate in self._segments.values():
            if candidate.start_chunk >= segment.start_chunk:
                continue
            if previous is None or candidate.start_chunk > previous.start_chunk:
                previous = candidate
        return previous

    def reset(self):
        """开始新一次录音时清空（否则上一轮的句子可能被重新"选中"显示）"""
        self._segments.clear()
        self._last_key = None
