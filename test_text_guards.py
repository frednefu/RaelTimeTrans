"""「这段不是人话」判据的单元测试

不需要音频/Whisper/网络：`text_guards.py` 是纯逻辑。验的是三件事：

1. 静音/音乐段的幻觉（`youtube youtube youtube`、`[MUSIC PLAYING]`、复读乱码）
   要被拦下——流式接上这道闸门之前，它们会一路进字幕和 SRT；
2. **业余无线电的真实通联用语不许误伤**（`CQ CQ CQ`、`very very good`、
   `Roger roger`、`59 59`）——宁可漏，不能把正常话砍掉；
3. 译文侧的复读截断只砍尾巴、不动前半句。
"""
import unittest

from text_guards import (clean_transcribed_text, is_phrase_repetition,
                         is_redundant_segment, is_repetition_loop, normalize_text,
                         truncate_repetition)
from translation.echo_guard import is_echo, strip_echo


class TestRepetitionLoop(unittest.TestCase):
    def test_character_loops_are_caught(self):
        """字符级复读乱码（噪声段让 Whisper 陷入复读）"""
        self.assertTrue(is_repetition_loop("ʰʰʰʰʰʰʰʰʰʰʰʰ"))
        self.assertTrue(is_repetition_loop("විවිවිවිවිවිවි"))
        self.assertTrue(is_repetition_loop("aaaaaaaaaaaa"))

    def test_normal_sentences_pass(self):
        self.assertFalse(is_repetition_loop("Roger, your signal is five by nine"))
        self.assertFalse(is_repetition_loop("CQ CQ this is BG7YYK calling"))
        self.assertFalse(is_repetition_loop("短句不判"))

    def test_real_words_with_few_distinct_letters_survive(self):
        """字符种类少不等于复读：`detected`（d/e/t/c 四种）原来被 ≤4 的规则误杀过，
        识别结果是整句的，一杀就是整条没了（本机 SRT 里就有两条 `detected`）"""
        self.assertFalse(is_repetition_loop("detected"))
        self.assertFalse(is_repetition_loop("assesses"))
        self.assertFalse(is_repetition_loop("no no no"))


class TestPhraseRepetition(unittest.TestCase):
    def test_repeated_word_is_caught(self):
        """流式语言锁死时吐出来的就是这种（屏幕上一直长同一个词）"""
        self.assertTrue(is_phrase_repetition("youtube youtube youtube"))
        self.assertTrue(is_phrase_repetition("youtube youtube youtube youtube"))
        self.assertTrue(is_phrase_repetition("笨拙的 笨拙的 笨拙的"))

    def test_repeated_phrase_is_caught(self):
        self.assertTrue(is_phrase_repetition("thank you for watching " * 3))
        self.assertTrue(is_phrase_repetition("hello world hello world hello world"))

    def test_ham_radio_phrases_are_not_touched(self):
        """**这是最关键的一条**：通联里的重复是正常的，不能拦"""
        for text in ["CQ CQ CQ", "very very good", "Roger roger",
                     "59 59", "no no no", "yes yes yes", "九 九 九"]:
            self.assertFalse(is_phrase_repetition(text), "%r 被误判成复读" % text)

    def test_short_repeats_pass(self):
        """重复两遍不算（门槛是 3）"""
        self.assertFalse(is_phrase_repetition("youtube youtube"))
        self.assertFalse(is_phrase_repetition("hello world hello world"))


class TestCleanTranscribedText(unittest.TestCase):
    def test_music_and_noise_hallucinations(self):
        """音乐/静音段的括号标注（本机 SRT 实测 8 条）整条删掉，别的一段不动"""
        self.assertEqual(clean_transcribed_text("[MUSIC PLAYING] [MUSIC PLAYING]"), "")
        self.assertEqual(clean_transcribed_text("(欢快的音乐)"), "")
        self.assertEqual(clean_transcribed_text("♪ ♪ ♪"), "")
        self.assertEqual(clean_transcribed_text("youtube youtube youtube"), "")
        self.assertEqual(clean_transcribed_text("谢谢观看"), "")
        self.assertEqual(clean_transcribed_text("..."), "")
        self.assertEqual(clean_transcribed_text(""), "")

    def test_bracket_noise_is_removed_but_speech_stays(self):
        self.assertEqual(
            clean_transcribed_text("[ MUSIC PLAYING] Hi, welcome to the weekend."),
            "Hi, welcome to the weekend.")
        self.assertEqual(clean_transcribed_text("[BLANK _AUDIO] Interesting."),
                         "Interesting.")
        self.assertEqual(clean_transcribed_text("(crying) How many radios is too many?"),
                         "How many radios is too many?")
        self.assertEqual(clean_transcribed_text("on generative. [Music] The Acom 71"),
                         "on generative. The Acom 71")

    def test_short_real_words_survive(self):
        """`detected` 这类"字符种类少"的真实结果不许被当成复读删掉"""
        self.assertEqual(clean_transcribed_text("detected"), "detected")
        self.assertEqual(clean_transcribed_text("assesses"), "assesses")

    def test_hallucination_phrase_inside_a_sentence(self):
        """短语出现在句子里就去掉那一段，剩下的照留"""
        self.assertEqual(clean_transcribed_text("please subscribe to my channel"),
                         "to my channel")
        self.assertEqual(clean_transcribed_text("Thank you for watching, over"),
                         ", over")

    def test_real_speech_survives(self):
        self.assertEqual(clean_transcribed_text("Roger, your signal is five by nine"),
                         "Roger, your signal is five by nine")
        self.assertEqual(clean_transcribed_text("CQ CQ CQ this is BG7YYK"),
                         "CQ CQ CQ this is BG7YYK")
        self.assertEqual(clean_transcribed_text("收到，你的信号是 59"),
                         "收到，你的信号是 59")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(clean_transcribed_text("  hello   world  "), "hello world")


class TestRedundantSegment(unittest.TestCase):
    def test_same_segment_again_is_redundant(self):
        """换了起点的同一段照样要拦（`_absorb` 只按起点去重，拦不住这个）"""
        self.assertTrue(is_redundant_segment("youtube", ["youtube", "hello"]))
        self.assertTrue(is_redundant_segment("YOUTUBE!", ["youtube"]))
        self.assertTrue(is_redundant_segment("youtube youtube youtube", ["hello"]))

    def test_new_content_is_not_redundant(self):
        self.assertFalse(is_redundant_segment("roger that", ["hello", "youtube"]))
        self.assertFalse(is_redundant_segment("CQ CQ CQ", ["hello world"]))

    def test_empty_is_redundant(self):
        """空段等于没有进展（看门狗据此判停滞）"""
        self.assertTrue(is_redundant_segment("", ["hello"]))
        self.assertTrue(is_redundant_segment("   ", ["hello"]))

    def test_very_short_text_is_kept(self):
        """一两个字符的段不去和前面比（"59"、"73" 这类短术语要能过）"""
        self.assertFalse(is_redundant_segment("59", ["59"]))

    def test_only_the_tail_is_compared(self):
        """只和尾部几段比：很早以前说过的词再说一遍是正常的"""
        parts = ["youtube"] + ["别的"] * 10
        self.assertFalse(is_redundant_segment("youtube", parts))


class TestTruncateRepetition(unittest.TestCase):
    def test_degenerate_output_keeps_the_first_copy(self):
        """用户实测的退化译文：留第一遍就够"""
        self.assertEqual(truncate_repetition("笨拙的" * 3), "笨拙的")
        self.assertEqual(truncate_repetition("笨拙的" * 60), "笨拙的")
        self.assertEqual(truncate_repetition("hello world " * 10), "hello world")

    def test_normal_text_is_untouched(self):
        for text in ["收到，你的信号是 59", "CQ CQ CQ", "very very good",
                     "Roger, copy that.", ""]:
            self.assertEqual(truncate_repetition(text), text)

    def test_repeat_not_at_the_start_is_left_alone(self):
        """重复段不在开头就原样返回：宁可漏，不可误砍半句正常译文"""
        text = "今天天气不错 笨拙的 笨拙的 笨拙的"
        self.assertEqual(truncate_repetition(text), text)


class TestNormalizeText(unittest.TestCase):
    def test_keeps_letters_digits_and_han(self):
        self.assertEqual(normalize_text("CQ CQ!"), "cq cq")
        self.assertEqual(normalize_text("你的信号 59。"), "你的信号 59")
        self.assertEqual(normalize_text("Hello, World"), "hello world")


class TestEchoGuard(unittest.TestCase):
    """译文侧的判据（`translation/echo_guard.py`）——和识别侧共用同一套归一化

    这些字符串全部取自本机 SRT 里真实出现的"提示词残渣"（12 个字幕文件里 11 条），
    以及模型的两种退化：把脚手架念回来、把原文原样回显。
    """

    def test_prompt_scaffolding_is_stripped(self):
        self.assertEqual(strip_echo("收到，来源：罗杰，收到，。"), "收到")
        self.assertEqual(strip_echo("您的信号是59\n。中文"), "您的信号是59")
        self.assertEqual(strip_echo("中文：你好"), "你好")
        self.assertEqual(strip_echo("Source: Hello\nChinese: 你好"), "Hello")

    def test_leading_marker_keeps_the_rest(self):
        """开头的标记只抠掉标记，后面的正文还在（抠多了等于整句没翻，更糟）"""
        self.assertEqual(strip_echo("来源：200，这就像一个平背，可能还有 __TERM_0__。"),
                         "200，这就像一个平背，可能还有 __TERM_0__。")

    def test_real_translations_are_untouched(self):
        self.assertEqual(strip_echo("收到，你的信号是 59"), "收到，你的信号是 59")
        self.assertEqual(strip_echo("信号的来源：基站。"), "信号的来源：基站。")

    def test_is_echo_needs_exact_match_and_long_enough_source(self):
        self.assertTrue(is_echo("This is Alpha Bravo Charlie Delta Echo",
                                "This is Alpha Bravo Charlie Delta Echo."))
        # 短句一律放过（"Roger"、"CQ CQ CQ" 这类回显和正常译文分不开）
        self.assertFalse(is_echo("Roger copy that", "Roger, copy that."))
        self.assertFalse(is_echo("收到", "CQ CQ CQ"))
        self.assertFalse(is_echo("收到，你的信号是 59", "Your signal is five nine"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
