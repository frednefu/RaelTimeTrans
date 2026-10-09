"""逐词字幕调度的单元测试

不需要音频设备、不需要 Whisper：直接构造带块号的词表，验证
"播放位置推进时该显示哪些词"这一条逻辑。
"""
import unittest

from gui.word_reveal import WordReveal
from audio.audio_timeline import TimedWord, WordSegment


def segment(utterance_id, words, start_chunk=None, end_chunk=None, is_final=True):
    """构造一个片段：words 传 [(词, 起始块, 结束块), ...]"""
    timed = [TimedWord(text, start, end) for text, start, end in words]
    return WordSegment(
        utterance_id=utterance_id,
        words=timed,
        start_chunk=start_chunk if start_chunk is not None else timed[0].start_chunk,
        end_chunk=end_chunk if end_chunk is not None else timed[-1].end_chunk,
        is_final=is_final,
        text=" ".join(w.text for w in timed),
    )


class TestWordReveal(unittest.TestCase):
    def setUp(self):
        self.reveal = WordReveal()

    def test_reveals_word_by_word(self):
        """播放位置每越过一个词的起点，就多显示一个词"""
        self.reveal.add_segment(segment(1, [
            ("cq", 10, 14), ("cq", 15, 19), ("this", 20, 25), ("is", 26, 29),
        ]))

        self.assertIsNone(self.reveal.tick(9), "还没到第一个词，不该显示")
        self.assertEqual(self.reveal.tick(10), "cq")
        self.assertIsNone(self.reveal.tick(14), "没有新词就不该重复刷新")
        self.assertEqual(self.reveal.tick(15), "cq cq")
        self.assertEqual(self.reveal.tick(28), "cq cq this is")

    def test_catches_up_when_recognition_is_late(self):
        """识别结果来晚了：播放位置已经越过好几个词，要一次补齐"""
        self.reveal.add_segment(segment(1, [
            ("alpha", 10, 14), ("bravo", 15, 19), ("five", 20, 24),
        ]))
        # 结果到达时播放位置已经在第 3 个词上
        self.assertEqual(self.reveal.tick(20), "alpha bravo five")

    def test_keeps_last_sentence_until_next_one_starts(self):
        """一句话说完、下一句还没开始时，上一句要留在屏幕上"""
        self.reveal.add_segment(segment(1, [("roger", 10, 14), ("over", 15, 19)],
                                        end_chunk=24))
        self.assertEqual(self.reveal.tick(16), "roger over")
        # 播放位置越过了句子结尾、又没有新句子：tick 返回 None 表示"不用重画"，
        # 界面上仍是上一行
        self.assertIsNone(self.reveal.tick(23))

        # 下一句开始（起点 30），播放位置到 30 才切换
        self.reveal.add_segment(segment(2, [("qsl", 30, 34), ("thanks", 35, 40)]))
        self.assertIsNone(self.reveal.tick(29), "下一句还没开口，不该切换到空行")
        self.assertEqual(self.reveal.tick(30), "qsl")

    def test_final_result_replaces_preview(self):
        """最终结果到达时替换预览，且不倒退"""
        self.reveal.add_segment(segment(1, [("five", 10, 14), ("niner", 15, 19)],
                                        is_final=False))
        self.assertEqual(self.reveal.tick(12), "five")

        # 最终结果把预览认错的词改对了，已经显示过的词照旧显示
        self.reveal.add_segment(segment(1, [("five", 10, 14), ("nine", 15, 19)]))
        self.assertEqual(self.reveal.tick(16), "five nine")

    def test_late_preview_does_not_overwrite_final(self):
        """迟到的预览结果不能把已经到达的最终结果顶掉"""
        self.reveal.add_segment(segment(1, [("five", 10, 14), ("nine", 15, 19)]))
        self.reveal.add_segment(segment(1, [("five", 10, 14), ("niner", 15, 19)],
                                        is_final=False))
        self.assertEqual(self.reveal.tick(20), "five nine")

    def test_out_of_order_segments_pick_the_right_one(self):
        """乱序到达的旧片段不会把新句子顶掉"""
        # 新的一句先到（起点 30），旧的那句后到（起点 10）
        self.reveal.add_segment(segment(2, [("qsl", 30, 34)]))
        self.reveal.add_segment(segment(1, [("roger", 10, 14)]))
        self.assertEqual(self.reveal.tick(31), "qsl")
        # 播放位置回到旧句子上（例如音频被回放），仍然显示对应的那句
        self.assertEqual(self.reveal.tick(12), "roger")

    def test_no_output_before_first_word(self):
        """播放位置还没到任何词时不要返回空行（避免把上一行清掉）"""
        self.reveal.add_segment(segment(1, [("hello", 50, 55)]))
        self.assertIsNone(self.reveal.tick(0))
        self.assertIsNone(self.reveal.tick(49))

    def test_reset_clears_state(self):
        """重新开始录音后，上一轮的句子不能再被选中"""
        self.reveal.add_segment(segment(1, [("roger", 10, 14)]))
        self.assertEqual(self.reveal.tick(12), "roger")
        self.reveal.reset()
        self.assertIsNone(self.reveal.tick(12))

    def test_old_segments_are_dropped(self):
        """只保留最近若干句，长时间运行不会越积越多"""
        reveal = WordReveal(max_segments=3)
        for i in range(1, 8):
            reveal.add_segment(segment(i, [(f"w{i}", i * 10, i * 10 + 2)]))
        self.assertEqual(len(reveal._segments), 3)
        self.assertEqual(reveal.tick(72), "w7")

    def test_tick_line_carries_previous_sentence(self):
        """tick_line 除了当前这行，还要给出上一句的全文（显示在上一行当上下文）"""
        self.reveal.add_segment(segment(1, [("roger", 10, 14), ("over", 15, 19)]))
        line = self.reveal.tick_line(12)
        self.assertEqual(line.text, "roger")
        self.assertEqual(line.previous_text, "", "第一句没有上一句")
        self.assertEqual(line.utterance_id, 1)

        # 第一句说完、第二句开口：当前行是第二句，上一行是第一句全文
        self.reveal.add_segment(segment(2, [("qsl", 30, 34), ("thanks", 35, 40)]))
        line = self.reveal.tick_line(31)
        self.assertEqual(line.text, "qsl")
        self.assertEqual(line.previous_text, "roger over")

    def test_previous_line_follows_the_latest_content(self):
        """上一句的文本变了对（例如迟到的最终结果改正了错词），要跟着更新"""
        self.reveal.add_segment(segment(1, [("five", 10, 14), ("niner", 15, 19)],
                                        is_final=False))
        self.reveal.add_segment(segment(2, [("qsl", 30, 34)]))
        self.assertEqual(self.reveal.tick_line(31).previous_text, "five niner")

        self.reveal.add_segment(segment(1, [("five", 10, 14), ("nine", 15, 19)]))
        line = self.reveal.tick_line(31)
        self.assertIsNotNone(line, "上一行的文本变了，界面得重画")
        self.assertEqual(line.previous_text, "five nine")

    def test_no_previous_when_segments_are_apart(self):
        """播放位置挑中的是旧句子时，"上一句"是它自己前面那句，不是后面那句"""
        self.reveal.add_segment(segment(1, [("alpha", 10, 14)]))
        self.reveal.add_segment(segment(2, [("bravo", 30, 34)]))
        self.assertEqual(self.reveal.tick_line(12).previous_text, "")
        self.assertEqual(self.reveal.tick_line(32).previous_text, "alpha")


if __name__ == "__main__":
    unittest.main(verbosity=2)
