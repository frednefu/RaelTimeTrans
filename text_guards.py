""""这段不是人话"的判据（识别结果与译文共用一份）

这套判据原来只活在 `audio/audio_processor.py` 里，而只有**整句**那条路用得到它；
2026-10 切流式（SimulStreaming）之后一个都没接上，于是静音/音乐段的幻觉
（`youtube youtube youtube`、`[MUSIC PLAYING]`）、复读乱码、纯标点能一路进
`text_queue`、进字幕文件、进翻译——用户报的"语言检测不准、原文一直重复显示
youtube"里，一半是引擎那边的语言锁死，另一半就是这里没有闸门。

所以把判据提到**仓库根目录**（和 `model_residency.py` 一个待遇），`audio/` 与
`translation/` 两条路共用一份。**纯逻辑，无 torch/whisper 依赖**，单测
（`test_text_guards.py`）直接 import。

判据分三类，别混：

- `clean_transcribed_text()`：给**一整条识别结果**用的（整句识别的段文本、流式终稿）；
- `is_redundant_segment()`：给**流式的前缀**用的——流式是一段一段攒的，不能像
  整条那样"不行就整条丢掉"，只能丢掉那一段、保住前面已经确认的内容；
- `truncate_repetition()`：给**译文**用的——本地小模型偶尔会退化成
  "笨拙的笨拙的笨拙的…"×60（`repeat_penalty` 之外的兜底，见
  `translation/echo_guard.py`）。这里只砍尾巴，不整条丢掉：译文前半段可能是好的。
"""

import re

# Whisper 对静音和噪声的典型幻觉输出。这些词一旦混进字幕，看起来就是"识别不
# 准确"，实际上模型在那段音频里根本没听到人说话。
HALLUCINATION_PHRASES = [
    "thank you", "thanks", "thank you for watching", "thanks for watching",
    "please subscribe", "subscribe", "like and subscribe",
    "谢谢观看", "谢谢收看", "感谢观看", "感谢收看",
    "请订阅", "请点赞", "请评论", "字幕由", "字幕志愿者",
]

# 整条结果正好等于这些词时判定为幻觉（识别到纯静音时 Whisper 常吐这几个词）。
# 用整条相等而不是包含来判断，避免误杀 "roger"、"over" 这类真实通联用语。
WHOLE_RESULT_HALLUCINATIONS = {
    "you", "thank you", "thanks", "thank you.", "bye", "bye.", "okay", "okay.",
    "please", "please.", "yeah", "yeah.", "so", "so.", "oh", "oh.",
    "thank you very much", "thank you very much.", "you're welcome",
    "♪", ".", ",", "...", "!", "?",
}


def is_repetition_loop(text):
    """判断识别结果是不是重复循环的乱码

    噪声段会让 Whisper 陷入复读，输出 "ʰʰʰʰʰʰ…"、"විවිවිවි…" 这种整条几乎只有
    一两个字符的内容。正常语句不可能长这样（字符种类必然很丰富）。

    **"字符种类少"这条只在整条没有空白、且种类少到 2 种时才作数**：
    `"CQ CQ CQ"`（8 个字符、只有 3 种）和 `"no no no"` 都落在原来的门槛里，但它们
    是真话；`"detected"`（d/e/t/c 四种，8 个字符）更是被原来的 ≤4 直接误杀过。
    噪声复读是**没有词间空格**的连续同字符（"ʰʰʰʰ…"、"විවිවිවි…"、"不不不不…"），
    所以限定在"无空白 + ≤2 种"这一格；多字符的复读交给 `is_phrase_repetition`。
    """
    if len(text) < 8:
        return False
    if not any(ch.isspace() for ch in text) and len(set(text)) <= 2:
        return True
    # 单个字符连续重复太多次
    run = 1
    for prev, cur in zip(text, text[1:]):
        run = run + 1 if cur == prev else 1
        if run >= 8:
            return True
    return False


def normalize_text(text):
    """归一化：小写、只留字母数字与汉字、空白收起（比较重复用）"""
    kept = []
    for ch in (text or "").lower():
        if ch.isalnum() or "一" <= ch <= "鿿":
            kept.append(ch)
        else:
            kept.append(" ")
    return " ".join("".join(kept).split())


def _unit_weight(text):
    """一个重复单元的"分量"：一个汉字算 2，其余字符算 1

    门槛（`MIN_UNIT_WEIGHT`）是按**半角字符**定的 4，所以必须这么折算：一个汉字
    顶得上两个字母，`"笨拙的"`（3 个汉字）是 6，不能按字面 3 个字符被门槛挡在外面，
    而 `"cq"`（2）、`"no"`（2）、`"yes"`（3）照样拦不住——它们本来就不该被拦。
    """
    return sum(2 if "一" <= ch <= "鿿" else 1 for ch in text)


# 重复单元的最小分量与最少重复遍数：**刻意保守**，宁可漏，不要误伤
# （业余无线电通联里 "CQ CQ CQ"、"no no no"、"very very good" 全是正常话）
MIN_UNIT_WEIGHT = 4
MIN_REPEATS = 3


def find_repeating_unit(text, min_repeats=MIN_REPEATS):
    """整条是不是同一个单元重复了至少 min_repeats 遍？是就返回那个单元，否则 None

    两种切法都试，**先词后字**：

    - 词一级：`"hello world hello world hello world"` → `"hello world"`（保留空格）；
    - 字符一级：中文没有词间空格，`"笨拙的笨拙的笨拙的…"` 在词一级看只有一个词，
      只能按字符找 → `"笨拙的"`。

    调用方是两个互为镜像的接口：`is_phrase_repetition`（判）与 `truncate_repetition`
    （砍），共用这一个"单元在哪"的实现，免得两边门槛各说各话。
    """
    text = (text or "").strip()
    if not text:
        return None

    # 1) 词一级
    words = text.split()
    if len(words) >= min_repeats:
        for size in range(1, len(words) // min_repeats + 1):
            if len(words) % size:
                continue
            unit = words[:size]
            if _unit_weight("".join(unit)) < MIN_UNIT_WEIGHT:
                continue
            if all(words[i:i + size] == unit for i in range(0, len(words), size)):
                return " ".join(unit)

    # 2) 字符一级（去掉空白之后再找，要求整条正好是单元重复若干遍）
    compact = "".join(text.split())
    for size in range(1, len(compact) // min_repeats + 1):
        if len(compact) % size:
            continue
        unit = compact[:size]
        if _unit_weight(unit) < MIN_UNIT_WEIGHT:
            continue
        if compact == unit * (len(compact) // size):
            return unit
    return None


def is_phrase_repetition(text, min_repeats=MIN_REPEATS):
    """整条是不是"同一个词/短语连着重复了好几遍"（"youtube youtube youtube"）

    与 `is_repetition_loop` 分工不同：那个抓的是**字符**复读（"ʰʰʰʰ"），
    这个抓的是**词/短语**复读——流式的语言锁死时吐出来的正是这种。

    要求整条都是重复（不是"含着重复"）：`"very very good"` 因为最后一个词不一样
    而放过，`"CQ CQ CQ"` 因为单元太短（分量 2 < 4）而放过。
    """
    return find_repeating_unit(text, min_repeats=min_repeats) is not None


# 方括号/圆括号里的"非语音标注"：`[MUSIC PLAYING]`、`[Applause]`、`（笑声）`、
# `[static]`。Whisper 对音乐/静音段会吐这些（流式引擎 `finish()` 遇到尾部静音也吐
# `[static]`），它们不是人说的话，不该进字幕。
# 只在这些括号**整体**是标注时才删——括号里是正文的极少见（Whisper 不产出那种）。
_BRACKET_NOISE = re.compile(r"[\[\(（【][^\]\)）】]*[\]\)）】]")


def clean_transcribed_text(text):
    """清掉识别结果里的幻觉短语、复读乱码、括号标注和纯标点（整条用）

    整句识别和流式识别**共用这一份**。以前只有整句那条路接了这道闸门，流式那边
    `youtube youtube youtube`、`[MUSIC PLAYING]` 一路进字幕和 SRT（见模块开头）。
    """
    if not text:
        return ""

    cleaned = " ".join(text.split())

    # 整条就是常见的静音幻觉词
    if cleaned.lower().strip(" .,!?") in {w.strip(" .,!?") for w in
                                          WHOLE_RESULT_HALLUCINATIONS}:
        return ""

    # 括号里的非语音标注（[MUSIC PLAYING]、[Applause]、[static]…）整段删掉
    cleaned = " ".join(_BRACKET_NOISE.sub(" ", cleaned).split())
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    # 先长后短：否则 "thank you" 会先把 "thank you for watching" 咬掉一半，
    # 剩下 "for watching"
    for phrase in sorted(HALLUCINATION_PHRASES, key=len, reverse=True):
        if phrase in lowered:
            # 用大小写不敏感的方式整段去掉
            idx = lowered.find(phrase)
            while idx != -1:
                cleaned = cleaned[:idx] + cleaned[idx + len(phrase):]
                lowered = cleaned.lower()
                idx = lowered.find(phrase)
            cleaned = " ".join(cleaned.split())

    if is_repetition_loop(cleaned):
        return ""

    # 整条就是同一个词/短语的复读（"youtube youtube youtube"）：噪声段让引擎卡在
    # 一个词上时吐的就是这个，整条丢掉（`clean_transcribed_text` 是"整条"接口，
    # 没有"保住前半段"一说；流式那段要保前缀，走 `is_redundant_segment`）
    if is_phrase_repetition(cleaned):
        return ""

    if not any(ch.isalnum() for ch in cleaned):
        return ""
    return cleaned.strip()


def is_redundant_segment(new_text, previous_parts, tail=4):
    """流式专用：新攒下的这一段是不是"已经说过的内容又吐了一遍"

    流式引擎**每句话只检测一次语言**（AligAtt 上游，`refresh_segment` 之前一直锁着），
    中英交替时后半段解不出东西、反复吐同一个词；而 `_absorb` 原来只按"起点完全相同"
    去重，换了个起点的同一段照样收下，于是前缀长成 "youtube youtube youtube…"
    一直长到单句上限。这条判据把那种段拦下来，**并且告诉调用方"这次没有进展"**，
    好让停滞看门狗（`audio_manager._stream_recognize`）决定要不要强制切句。

    previous_parts 是已经确认的段列表（`SimulStreamingEngine._parts`）。
    """
    if not new_text or not new_text.strip():
        return True
    if is_repetition_loop(new_text):
        return True
    if is_phrase_repetition(new_text):
        return True
    key = normalize_text(new_text)
    if len(key) < 3:
        return False
    return any(key == normalize_text(part) for part in list(previous_parts)[-tail:])


def truncate_repetition(text, min_repeats=MIN_REPEATS):
    """译文退化复读时只留第一遍（"笨拙的笨拙的笨拙的…"×60 → "笨拙的"）

    本地小模型（实测 1.7B）偶尔会在贪心解码下退化成复读同一段短语，一直复读到
    `num_predict` 用完。提示词侧的 `repeat_penalty`（见 `local_llm_translator._ollama_options`）
    是主防线，这一条是兜底：**只在整条就是同一段重复时才动手**，而且只砍尾巴不动前面
    （前面那半句译文可能还是好的）。

    门槛与 `is_phrase_repetition` 同一套（共用 `find_repeating_unit`），所以
    "very very good"、"CQ CQ CQ" 不会被砍。重复段不在开头时（"今天天气不错 笨拙的
    笨拙的…"）这里认不出来、原样返回 —— 有意的：宁可漏，不要误砍半句正常译文。
    """
    text = (text or "").strip()
    if not text:
        return text
    unit = find_repeating_unit(text, min_repeats=min_repeats)
    return unit if unit else text
