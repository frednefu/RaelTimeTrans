"""「译文逐词显示」（半截句子的前缀翻译）的界面调度测试

不启 Qt 窗口：直接用 `MainWindow.__new__` 造一个空壳，只把这条通路用得到的
几处接口换成假的（音频管理器、翻译线程、字幕窗口、两个预览标签），然后调**真的**
`update_subtitles` 走一遍分发。要盯住的是几件事：

1. 前缀**只在说得出新的半截原文时**才送翻，而且按 `simul_prefix_interval_ms` 节流。
   半截原文按识别后端二选一：流式取引擎的已确认前缀，整句取逐词通路已经念出来的
   那半句（所以整句后端下不勾「原文逐词显示」就没有来源，一个请求都不发）；
2. 前缀译文**只上屏**——绝不进 `add_translated_text`（那就是 SRT 落盘的入口）；
3. 整句定稿一到，这一句的前缀请求全部作废、后续也不再送（词表里的 `is_final`：
   回来得晚的半截译文不能把整句译文盖回一个更短的版本，也不能贴到下一句的原文上）；
4. "不翻译"模式、源语言=目标语言、以及把「译文逐词显示」关掉，这几条短路照旧生效
   ——开关关掉时，已经在路上的半截译文也要丢掉。

用法：`python test_prefix_translation.py`
"""

import unittest

import config as config_module
from audio.audio_timeline import TimedWord, WordSegment
from config import config
from gui.main_window import MainWindow
from gui.word_reveal import WordReveal
from translation.translation_worker import KIND_FINAL, KIND_PREFIX


class FakeLabel:
    """只记 setText/isVisible 的假标签"""

    def __init__(self, visible=True):
        self._visible = visible
        self.text = None

    def isVisible(self):
        return self._visible

    def setText(self, text):
        self.text = text


class FakeCombo:
    def __init__(self, text):
        self._text = text

    def currentText(self):
        return self._text


class FakeSubtitleWindow:
    """记下每一次 update_text（前缀译文必须只走这里）"""

    def __init__(self):
        self.calls = []

    def isVisible(self):
        return True

    def update_text(self, **kwargs):
        self.calls.append(kwargs)

    def set_original_words(self, *args):
        self.calls.append({"words": args})


class FakeAudioManager:
    """可编程的假音频管理器"""

    def __init__(self):
        self.latest_text = None
        self.prefix = (None, "")        # 流式后端：引擎给的"已确认前缀"
        self.detected_language = "en"
        self.segments = []              # 整句后端：逐词片段（前缀的来源）
        self.srt_rows = []          # add_translated_text = SRT 落盘

    # ---- update_subtitles 会用到的那几处 ----
    def take_word_segments(self):
        segments, self.segments = self.segments, []
        return segments

    def get_play_position_chunks(self):
        return 10 ** 9              # 词全都"已经播到"

    def get_latest_text(self):
        return self.latest_text

    def get_committed_prefix(self):
        return self.prefix

    def get_detected_language(self):
        return self.detected_language

    def add_translated_text(self, original, translated):
        self.srt_rows.append((original, translated))


class FakeSubtitleManager:
    _CODES = {"中文": "zh", "英语": "en", "不翻译": None}

    def get_language_code(self, name):
        return self._CODES.get(name, "en")

    def get_language_name(self, code):
        return code


class FakeTranslationWorker:
    """假翻译线程：request 记账，poll 交回预先摆好的结果"""

    def __init__(self):
        self.requests = []          # (seq, text, target, kind)
        self.results = []           # 待 poll 出来的 4 元组

    def request(self, text, target_language, kind=KIND_FINAL):
        seq = len(self.requests) + 1
        self.requests.append((seq, text, target_language, kind))
        return seq

    def poll(self):
        results, self.results = self.results, []
        return results


class PrefixTranslationTest(unittest.TestCase):

    def setUp(self):
        # 只改内存里的设置，绝不写 settings.json（config.set 会立刻落盘）
        self._saved = {k: config.settings.get(k) for k in
                       ("word_by_word_enabled", "translation_word_by_word",
                        "asr_backend", "simul_prefix_interval_ms")}
        config.settings["word_by_word_enabled"] = True
        config.settings["translation_word_by_word"] = True
        config.settings["asr_backend"] = "simul"
        config.settings["simul_prefix_interval_ms"] = 800

        mw = MainWindow.__new__(MainWindow)
        mw.audio_manager = FakeAudioManager()
        mw.subtitle_manager = FakeSubtitleManager()
        mw.translation_worker = FakeTranslationWorker()
        mw.word_reveal = WordReveal()
        mw.subtitle_window = FakeSubtitleWindow()
        mw.original_preview = FakeLabel(visible=False)
        mw.subtitle_preview = FakeLabel()
        mw.target_language_combo = FakeCombo("中文")
        mw.current_displayed_text = ""
        mw.current_displayed_translation = ""
        mw._prefix_requests = {}
        mw._prefix_text = ""
        mw._prefix_request_time = 0.0
        mw._prefix_utterance = None
        mw._prefix_source_utterance = None
        mw._prefix_source_text = ""
        mw._finalized_utterance = None
        # 这几处只管界面显示，和这条通路无关，打桩躲开
        mw.update_detected_language_label = lambda: None
        mw.update_delay_info = lambda: None
        mw.update_stream_status = lambda: None
        self.mw = mw

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                config.settings.pop(key, None)
            else:
                config.settings[key] = value

    # ---------------------------------------------------------------- 工具

    def _prefix_requests(self):
        return [r for r in self.mw.translation_worker.requests
                if r[3] == KIND_PREFIX]

    def _final_requests(self):
        return [r for r in self.mw.translation_worker.requests
                if r[3] == KIND_FINAL]

    # ---------------------------------------------------------------- 用例

    def test_prefix_is_sent_once_per_new_text(self):
        """同一段前缀只说一次；前缀长出新词才再送"""
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        self.assertEqual([r[1] for r in self._prefix_requests()], ["Roger"])

        self.mw.update_subtitles()          # 一模一样的前缀，不重复送
        self.assertEqual(len(self._prefix_requests()), 1)

        self.mw._prefix_request_time = 0.0  # 假装 800ms 已经过去
        self.mw.audio_manager.prefix = (1, "Roger over")
        self.mw.update_subtitles()
        self.assertEqual([r[1] for r in self._prefix_requests()],
                         ["Roger", "Roger over"])

    def test_prefix_is_throttled(self):
        """间隔没到就不送（前缀可能每 100ms 就长一个词，不能词词都送）"""
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        self.assertEqual(len(self._prefix_requests()), 1)

        self.mw.audio_manager.prefix = (1, "Roger over")
        self.mw.update_subtitles()          # 刚送过，间隔没到
        self.assertEqual(len(self._prefix_requests()), 1)
        # 文本没被记下，所以下一次还会拿这同一段去试（不会漏掉它）
        self.assertEqual(self.mw._prefix_text, "Roger")

    def test_prefix_translation_only_updates_the_translation_row(self):
        """前缀译文只上屏：不进 SRT、不写 text_queue"""
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        seq = self._prefix_requests()[0][0]

        self.mw.translation_worker.results = [(seq, "Roger", "罗杰", KIND_PREFIX)]
        self.mw.subtitle_window.calls.clear()
        self.mw.update_subtitles()

        self.assertEqual(self.mw.subtitle_window.calls,
                         [{"translation_text": "罗杰"}])
        self.assertEqual(self.mw.audio_manager.srt_rows, [])

    def test_final_invalidates_prefix_requests(self):
        """定稿一到，这一句的前缀请求作废：迟到的前缀译文不许盖回短版本"""
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        prefix_seq = self._prefix_requests()[0][0]

        # 整句定稿到了
        self.mw.audio_manager.latest_text = "Roger over alpha bra vo five nine er"
        self.mw.audio_manager.prefix = (None, "")
        self.mw.update_subtitles()
        self.assertEqual(self.mw._prefix_requests, {})
        self.assertEqual(self.mw._prefix_text, "")
        self.assertEqual(len(self._final_requests()), 1)

        # 定稿的整句译文回来 → 上屏 + 进 SRT
        final_seq = self._final_requests()[0][0]
        self.mw.translation_worker.results = [
            (prefix_seq, "Roger", "罗杰", KIND_PREFIX),          # 迟到的前缀译文
        ]
        self.mw.subtitle_window.calls.clear()
        self.mw.update_subtitles()
        self.assertEqual(self.mw.subtitle_window.calls, [])       # 被丢掉

        self.mw.translation_worker.results = [
            (final_seq, self.mw.audio_manager.latest_text, "罗杰，完毕，字母……", KIND_FINAL),
        ]
        self.mw.update_subtitles()
        self.assertEqual(self.mw.audio_manager.srt_rows,
                         [(self.mw.audio_manager.latest_text, "罗杰，完毕，字母……")])
        self.assertEqual(self.mw.subtitle_window.calls[-1],
                         {"translation_text": "罗杰，完毕，字母……"})

    def test_prefix_from_the_previous_sentence_is_dropped(self):
        """换句之后，上一句的前缀译文不能贴到这一句的原文下面"""
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        old_seq = self._prefix_requests()[0][0]

        self.mw.audio_manager.prefix = (2, "Alpha bravo")
        self.mw._prefix_request_time = 0.0
        self.mw.update_subtitles()
        self.assertEqual(self.mw._prefix_utterance, 2)

        self.mw.translation_worker.results = [(old_seq, "Roger", "罗杰", KIND_PREFIX)]
        self.mw.subtitle_window.calls.clear()
        self.mw.update_subtitles()
        self.assertEqual(self.mw.subtitle_window.calls, [])

    def test_no_translation_mode_skips_prefix(self):
        """"不翻译"模式一个前缀请求都不发"""
        self.mw.target_language_combo = FakeCombo("不翻译")
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        self.assertEqual(self._prefix_requests(), [])
        self.assertEqual(self.mw.subtitle_window.calls, [])

    def test_same_language_shows_prefix_without_translating(self):
        """源语言=目标语言：不请求翻译，直接把原文当前缀译文贴上"""
        self.mw.target_language_combo = FakeCombo("英语")
        self.mw.audio_manager.detected_language = "en"
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.subtitle_window.calls.clear()
        self.mw.update_subtitles()
        self.assertEqual(self._prefix_requests(), [])
        self.assertEqual(self.mw.subtitle_window.calls,
                         [{"translation_text": "Roger"}])

    def test_option_off_means_no_prefix(self):
        """关掉「译文逐词显示」就退回"定稿后才翻"：一个前缀请求都不发"""
        config.settings["translation_word_by_word"] = False
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        self.assertEqual(self._prefix_requests(), [])

    def test_prefix_result_dropped_when_option_turned_off(self):
        """开关关掉之后，已经在路上的半截译文也要丢掉（别把译文行改回半截的版本）"""
        self.mw.audio_manager.prefix = (1, "Roger")
        self.mw.update_subtitles()
        seq = self._prefix_requests()[0][0]

        config.settings["translation_word_by_word"] = False
        self.mw.translation_worker.results = [(seq, "Roger", "罗杰", KIND_PREFIX)]
        self.mw.subtitle_window.calls.clear()
        self.mw.update_subtitles()
        self.assertEqual(self.mw.subtitle_window.calls, [])

    # -------------------------------------------- 整句后端：半句从逐词通路来

    BATCH_SEGMENT = WordSegment(utterance_id=1,
                                words=[TimedWord("Roger", 0, 5),
                                       TimedWord("over", 6, 10)],
                                start_chunk=0, end_chunk=10,
                                is_final=False, text="Roger over")

    def test_batch_backend_uses_the_revealed_half_sentence(self):
        """整句后端没有"已确认前缀"可取，前缀就是逐词通路已经念出来的那半句"""
        config.settings["asr_backend"] = "whisper_batch"
        self.mw.audio_manager.segments = [self.BATCH_SEGMENT]
        self.mw.update_subtitles()
        self.assertEqual([r[1] for r in self._prefix_requests()], ["Roger over"])
        self.assertEqual(self.mw._prefix_source_utterance, 1)

    def test_batch_backend_without_word_by_word_sends_nothing(self):
        """整句后端 + 不勾「原文逐词显示」：根本没有半截原文可翻"""
        config.settings["asr_backend"] = "whisper_batch"
        config.settings["word_by_word_enabled"] = False
        self.mw.audio_manager.segments = [self.BATCH_SEGMENT]
        self.mw.update_subtitles()
        self.assertEqual(self._prefix_requests(), [])
        self.assertEqual(self.mw.subtitle_window.calls, [])

    def test_final_segment_closes_the_sentence(self):
        """词表里的 is_final 一到，这一句的前缀请求就到此为止

        整句定稿是"词表 + 整句文本"同一次回调发出来的。第一条路（`_prefix_requests`
        被清空）挡住已经在路上的；这条（`_finalized_utterance`）挡住**之后**还要再送的
        ——逐词通路那一刻还在显示这句话的半句，不挡住就会再翻一遍半截的版本，回来
        正好盖掉正式译文。
        """
        config.settings["asr_backend"] = "whisper_batch"
        self.mw.audio_manager.segments = [self.BATCH_SEGMENT]
        self.mw.update_subtitles()
        self.assertEqual(len(self._prefix_requests()), 1)

        self.mw.audio_manager.segments = [self.BATCH_SEGMENT._replace(is_final=True)]
        self.mw.audio_manager.latest_text = self.BATCH_SEGMENT.text
        self.mw._prefix_request_time = 0.0        # 假装节流间隔已经过去
        self.mw.update_subtitles()
        self.assertEqual(self.mw._finalized_utterance, 1)
        self.assertEqual(len(self._prefix_requests()), 1, "定稿之后不许再送半截的")

        # 下一句照常可以送（换句了）
        self.mw.audio_manager.segments = [
            WordSegment(utterance_id=2,
                        words=[TimedWord("Alpha", 20, 25), TimedWord("bravo", 26, 30)],
                        start_chunk=20, end_chunk=30, is_final=False,
                        text="Alpha bravo")]
        self.mw._prefix_request_time = 0.0
        self.mw.update_subtitles()
        self.assertEqual([r[1] for r in self._prefix_requests()],
                         ["Roger over", "Alpha bravo"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
