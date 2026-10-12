"""提示词残渣的清理（"模型把脚手架也吐出来了"）

本地小模型偶尔会把提示词自己的脚手架接在译文后面/前面一起吐出来（实测
Spark-X2.5-1.7B，就算用 `"think": false` 关掉思考也一样）：

    "收到，来源：罗杰，收到，。"
    "您的信号是59\\n。中文"
    "来源：200，这就像一个平背，可能还有 __TERM_0__。"

于是字幕上就出现了"来源："和机器码。这套判据原来只活在诊断脚本
（`check_local_translate.py` 的 `ECHO_MARKERS`）里，生产代码一个字都没用 ——
本机 12 个最新字幕文件里 11 条带这种残渣，就是这么来的。

做法是**剥掉**而不是整句丢弃：残渣前面那半句译文通常是好的，扔掉可惜。

- `strip_echo()`：切掉脚手架（标记 + 它后面那一截重复），并清掉孤零零的语言名尾巴；
- `is_echo()`：整条译文和原文一字不差 —— 那是回显，不是翻译（用户报的"直接显示
  原文"里有一条就是这个：模型把原句原样抄了回来，还当成译文进了字幕和 SRT）。

`check_local_translate.py` 复用这里的 `ECHO_MARKERS`，不再各写一份。
"""
import re

from text_guards import normalize_text   # 和识别那边共用同一套归一化（纯逻辑，无重依赖）

# 译文里**不该**出现的东西：提示词自己的脚手架。检查脚本和这里共用一份
# （原来是 `check_local_translate.py` 里的 `ECHO_MARKERS`，一字未改，只多了个
#  "Chinese:" —— 实测脚手架也会写成英文语言名那一套）。
ECHO_MARKERS = ["来源：", "来源:", "Source:", "中文:", "中文：", "Chinese:",
                "English:"]

# 标记必须出现在**分句边界**上才算残渣：中文译文里"信号的来源：基站"是正常句子
# （"的"紧挨着标记），而模型的脚手架一定跟在逗号/句号/换行/开头后面
# （"收到，来源：…"）。少了这条，正常译文会被从中间截断。
_BOUNDARY = "，,。.、;；:：!！?？ \t\n\"'“”（()【】"

# 尾巴上孤零零的语言名（"您的信号是59\n。中文"）：只有它自己占一行/一段时才清
_TRAILING_LANGUAGE = re.compile(
    r"(?i)[\s，,。.、;；:：!！?？]*(中文|英文|汉语|英语|chinese|english)[\s。.!！]*$")

_MARKER_PATTERN = re.compile("|".join(re.escape(m) for m in ECHO_MARKERS), re.IGNORECASE)


def _first_marker_at_boundary(text):
    """第一个"落在分句边界上"的脚手架标记的位置；没有返回 -1"""
    for match in _MARKER_PATTERN.finditer(text):
        start = match.start()
        if start == 0 or text[start - 1] in _BOUNDARY:
            return start
    return -1


def strip_echo(text):
    """剥掉提示词残渣，返回干净的译文（没残渣时原样返回）

    三种残渣一次处理完：**开头**的标记（只去标记本身 —— 它后面就是译文，
    "来源：200，这就像一个平背" → "200，这就像一个平背"）、**中间**起头的标记及其
    后面那截重复脚手架（整段切掉）、孤零零的语言名尾巴，最后收拾切口上的空白与标点。
    """
    if not text:
        return text
    result = text.strip()

    # 1) 开头的标记：只抠掉标记，后面的内容还在
    while True:
        match = _MARKER_PATTERN.match(result)
        if not match:
            break
        result = result[match.end():].lstrip()

    # 2) 中间（分句边界上）起头的标记：后面那截是模型把脚手架重念了一遍，整段切掉
    cut = _first_marker_at_boundary(result)
    if cut != -1:
        result = result[:cut].rstrip()

    # 3) 尾巴上只剩一个语言名（"…59\n。中文"）
    result = _TRAILING_LANGUAGE.sub("", result)

    # 4) 收拾切口：多余空白、贴着标点的空档、孤零零的句读
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\s+([，。！？、；：,.!?;:])", r"\1", result)
    return result.strip().strip("，,").strip()


def is_echo(translated, source, min_words=4):
    """译文是不是"原文原样抄了一遍"

    只有**归一化之后一字不差**、且原文至少有 `min_words` 个词时才算：业余无线电里
    "CQ CQ CQ"、"Roger" 这类短句本来就该原样过去（术语通路也管着它们），短句一律
    放过；长句一字不差地"翻"回来，那就是模型在回显原文（用户报的"直接显示原文"）。
    """
    translated_key = normalize_text(translated)
    source_key = normalize_text(source)
    if not translated_key or translated_key != source_key:
        return False
    return len(source_key.split()) >= int(min_words)
