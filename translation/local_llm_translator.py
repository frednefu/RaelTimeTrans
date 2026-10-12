"""本地翻译后端：调用本机常驻的大模型服务（Ollama，或 llama.cpp 的 llama-server）。

为什么要有它：googletrans 走 Google 的免费接口，实测单句 2.1~2.7 秒（数字见
translation/translation_worker.py 的文件头），会被限流，断网直接不能用。换成本机上的
EuroLLM-1.7B-Instruct-Q8（约 1.8GB 显存）之后单句实测 150~200 毫秒（GPU，约 95 tok/s 生成），
且不依赖网络。

三条实测出来的实现要点，别随手改：

1. **提示词必须按 EuroLLM 官方格式写**：指令放在 user 回合里，形如
   "Translate the following English source text to Chinese:\nEnglish: …\nChinese:"。
   本机实测：把指令写成 system 里的一段自由描述，1.7B 会答非所问（把 "five nine" 的信号
   报告当成摩尔斯电码问题来回答）；而官方格式下，system 里再补一句要求（只输出译文、
   别丢标记）不影响结果 —— 三种写法实测给出同一句正确译文。所以这里 user 回合用官方
   格式，system 只放"只输出译文"这条纪律。

2. **术语标记绝对不能放进提示词**（`_translate_segments`）。原先想着"让模型把
   __TERM_0__ 原样带过去"，1.7B 做不到，实测三种丢法都出现过：
   - 一句话里同一个 __TERM_0__ 出现两次，被**合并成一个**（"CQ CQ this is BG7YYK calling CQ CQ"
     预处理出四个标记，只回来一个，"CQ" 就丢了）；
   - 标记后面跟着括号注释（术语表里的中文，如 "73（最好的祝福）"）时，模型把整个括号当
     正文改写，连标记一起吃掉；
   - 即便保住数量，**位置也不对**："__TERM_0__ __TERM_1__ this is BG7YYK calling" 翻成了
     "BG7YYK 呼叫此处，__TERM_0__ __TERM_1__"，标记全被挪到句尾。
   改成"把标记当分隔符、只把中间的**纯文本片段**交给模型翻，标记由我们自己拼回去"之后，
   位置和数量都是确定的，术语一个不丢 —— 术语的译文照样由 SubtitleManager 第 6 步的
   restore_ham_radio_terms 贴回来，管线的语义没变，只是第 5 步的传输换了做法。
   代价：一句带 N 个术语的话要发 N+1 个请求（都是短句，实测每条 100~200ms，仍远快于谷歌一整句）。

3. **标记后面那份重复的括号注释要摘掉**（`_strip_glosses`）：它和还原时贴回去的文本是同一份
   （"73（最好的祝福）" 里的 "（最好的祝福）"），留着只会被当成正文再翻一遍，译文里出现
   两个"（最好的祝福）"。

4. **冷加载不能算进"单句超时"**（`_LOAD_READ_TIMEOUT_S` / `_warm_model` / `preload`）：
   requests 的读超时管的是"等到第一个字节"，而模型从磁盘进显存全发生在第一个字节之前。
   实测冷加载 1.7B-Q8 1.4 秒、9B-Q4（5.6GB）**10.8 秒**、Spark-1.7B 4.4 秒；而
   `local_llm_timeout_ms` 默认 3000 —— 换个模型之后第一句必然以 ReadTimeout 告终
   （用户实测报的"alibayram/erurollm-9b-instruct 测试失败"就是这个，热起来只要 0.43 秒）。
   所以记一个"哪个模型热过"（`_warm_model`）：没热过的第一次请求用 120 秒兜底，成功
   之后回到配置里的单句超时；`preload()` 则单独把加载那一步做完，给"测试连接"用，好把
   加载和翻译两段耗时分开报。**preload 用的必须是"真跑一步最小生成"（`num_predict=1`），
   而且 options 要和真翻译逐字一致（都走 `_ollama_options`）** —— 用 Ollama 那个"不带
   prompt 只加载"的写法、或者 `num_ctx` 两边给得不一样，都会让下一次翻译请求撞上一次
   重载（实测 5.06 秒），"测试连接"照样失败（详见 preload 的注释）。

5. **思考型模型要显式关掉思考**（`"think": False`）：Spark-X2.5、DeepSeek-R1 这类默认先把
   推理写进 `message.thinking`，实测 Spark-1.7B 把 256 个 token（num_predict 上限）全烧在
   思考上，`content` 是空串、`done_reason='length'` —— 字幕上什么都拿不到。加上
   `think: false` 之后 0.43 秒就给译文。实测 EuroLLM-1.7B/9B 与 Spark 都接受这个字段
   （不支持的模型会忽略它），所以这里无脑加。

6. **"用完就还"是这一侧自己的责任**（`unload` / `unload_others`）：每条请求都带
   `keep_alive: "30m"`，而一句带术语的话要发 N+1 条 —— 等于每 200ms 就把模型续期半小时，
   所以「停止翻译」之后它照样在显存里挂着。这台机器只有 8 GB，实测切过一次模型就有
   EuroLLM(1.73GB) + Spark(3.52GB) 同时驻留；再叠上识别模型，Ollama 就会为了腾地方把
   正在用的那个挤掉重载（日志 `aborting load`），界面上看着是"某些句子突然回落成原文"。
   所以这里备好"点名卸载"（`unload`）和"清场"（`unload_others`），由 `model_residency`
   在闲置超时/点「释放显存」/切模型时调用。**卸掉当前模型时必须清 `_warm_model`**，
   否则下一次请求还按热模型的 3 秒超时发，而它得冷加载，必然超时回落（见要点 4）。

这个类的所有方法**一律不抛异常**（连不上、超时、模型不在都只记进 last_error 并返回
None/False）：仓库的约定是工作线程里任何一句异常都会毁掉整次识别结果（见 CLAUDE.md），
所以这里全部吞掉，由调用方决定怎么回落。
"""

import re
import time

import requests

from config import config


# 语言名映射：界面上存的是中文显示名（"中文"），Google 那边用的是语言代码（"zh-cn"），
# EuroLLM 的提示词里要写英文语言名（"Chinese"）。这里把三种写法收口到一张表。
_LANGUAGE_CODES = {
    "自动检测": "auto", "不翻译": "none",
    "中文": "zh", "英语": "en", "日语": "ja", "韩语": "ko", "法语": "fr",
    "德语": "de", "俄语": "ru", "西班牙语": "es", "意大利语": "it",
    "葡萄牙语": "pt", "荷兰语": "nl", "波兰语": "pl", "阿拉伯语": "ar",
    "土耳其语": "tr", "泰语": "th", "越南语": "vi", "印尼语": "id",
    "印地语": "hi", "波斯语": "fa", "保加利亚语": "bg", "捷克语": "cs",
    "希腊语": "el", "芬兰语": "fi", "匈牙利语": "hu", "挪威语": "no",
    "罗马尼亚语": "ro", "瑞典语": "sv", "乌克兰语": "uk",
    "加泰罗尼亚语": "ca", "克罗地亚语": "hr", "丹麦语": "da",
    "希伯来语": "he", "乌尔都语": "ur",
}

_LANGUAGE_NAMES = {
    "zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean",
    "fr": "French", "de": "German", "ru": "Russian", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
    "ar": "Arabic", "tr": "Turkish", "th": "Thai", "vi": "Vietnamese",
    "id": "Indonesian", "hi": "Hindi", "fa": "Persian", "uk": "Ukrainian",
    "sv": "Swedish", "ro": "Romanian", "el": "Greek", "cs": "Czech",
    "fi": "Finnish", "hu": "Hungarian", "no": "Norwegian", "da": "Danish",
    "he": "Hebrew", "ca": "Catalan", "hr": "Croatian", "bg": "Bulgarian",
    "ur": "Urdu",
}

# system 回合那句纪律。措辞是按本机实测过的那份抄的（见模块开头的要点 1），
# 改动前先在 check_local_translate.py 上跑一遍。
_SYSTEM_PROMPT = ("You are a simultaneous interpretation engine. "
                  "Output the translation only. Keep tokens that look like "
                  "__TERM_0__ exactly as they are, in place.")

# 冷加载那一次请求的读超时（见模块开头的要点 4）。只在"这个模型还没热过"时生效，
# 之后一律按 config 里的 local_llm_timeout_ms 走 —— 那是"一句译文等多久算失败"，
# 和"把 5 GB 模型读进显存"不是一回事。实测 9B-Q4 冷加载 10.8 秒，留足余量。
_LOAD_READ_TIMEOUT_S = 120.0

# 卸载请求的读超时。卸载本身很快（实测 EuroLLM-1.7B-Q8 约 0.3 秒就从 /api/ps 里消失），
# 但它可能排在一条正在生成的请求后面，所以别给 2 秒那么紧；也不给 120 秒——这条路会在
# 界面线程上被调用（定时 sweep / 「释放显存」），卡住界面比卸不掉更糟。
_UNLOAD_TIMEOUT_S = 20.0


def language_code(value, default=""):
    """把 "中文" / "zh-cn" / "zh" / "en" 都归一成两位语言代码"""
    if not value:
        return default
    text = str(value).strip()
    if text in _LANGUAGE_CODES:
        return _LANGUAGE_CODES[text]
    return text.lower().replace("_", "-").split("-")[0] or default


def language_name(value, default=None):
    """同上，但要的是提示词里的英文语言名；认不出来就返回 default（None = 未知）"""
    return _LANGUAGE_NAMES.get(language_code(value), default)


# 术语标记的形态。TermManager 生成的一定是 __TERM_0__，这里放宽一点是为了认得出
# （并切掉）别的写法，别让它们溜进提示词。
_TERM_SHAPED = re.compile(r"(?i)_{1,3}\s*T\s*E\s*R\s*M\s*_{0,3}\s*(\d+)\s*_{0,3}")
# 标记后面紧跟的括号注释（术语表里的中文，如 "73（最好的祝福）" 里的那一截）
_GLOSS_AFTER_MARKER = re.compile(
    r"(?i)(_{1,3}\s*T\s*E\s*R\s*M\s*_{0,3}\s*\d+\s*_{0,3})\s*[（(][^（）()]*[）)]")


def _strip_glosses(text):
    """摘掉跟在标记后面的括号注释（还原时整段会一起贴回来，留着只会被重复翻译）"""
    return _GLOSS_AFTER_MARKER.sub(lambda m: m.group(1), text)


def split_markers(text):
    """按术语标记切开，返回 [(是否标记, 片段), …]，标记原样保留在片段里"""
    segments = []
    pos = 0
    for match in _TERM_SHAPED.finditer(text):
        if match.start() > pos:
            segments.append((False, text[pos:match.start()]))
        segments.append((True, match.group(0)))
        pos = match.end()
    if pos < len(text):
        segments.append((False, text[pos:]))
    return segments


def normalize_placeholders(text):
    """把写花了的术语标记规整回 __TERM_N__ 的标准形式

    SubtitleManager 第 6 步还原前会用它兜一道（正常情况下标记是我们自己拼进去的、
    不会花；只有模型自己"编"出一个 TERM 样子的东西才用得上）。
    """
    if not text or "term" not in text.lower():
        return text
    return _TERM_SHAPED.sub(lambda m: "__TERM_%s__" % m.group(1), text)


def strip_leftover_placeholders(text):
    """清掉最后还没被还原的标记残骸（拿不到术语原文，但绝不能让字幕上出现机器码）"""
    if not text or "term" not in text.lower():
        return text
    text = _TERM_SHAPED.sub("", text)
    # 标记被抠掉后常留下多余空格和贴着标点的空档，顺手收拾一下
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\s+([，。！？、；：,.!?;:])", r"\1", text).strip()


class LocalLLMTranslator:
    """本机大模型的翻译客户端

    配置全部现读现用（config.get），界面上改完立刻生效，不用重建对象。
    """

    def __init__(self):
        self.last_error = None   # 最近一次失败原因（界面和诊断脚本要显示）
        self.last_stats = {}     # 最近一次成功的耗时明细（毫秒）
        # 哪个模型已经热过（成功翻译过一次，或 preload 过）。不是它的时候，下一次
        # 请求里含"加载模型"，读超时得放宽 —— 见模块开头的要点 4。
        self._warm_model = None
        self.last_load_ms = None  # 最近一次 preload 花了多久（界面"测试连接"要分开报）
        # 复用的连接池（见 _request）。**名字不能叫 `_session`**：那会和下面的
        # `_session()` 方法撞名，实例属性一覆盖，`self._session()` 就变成
        # `None(...)` → "NoneType object is not callable"（本机实测踩过一次）。
        self._http_session = None

    # ---------------------------------------------------------------- HTTP

    def _session(self):
        """复用一个 `requests.Session`：省掉连接 churn

        前缀翻译每 `simul_prefix_interval_ms`（默认 800ms）一条，一句带 N 个术语要发
        N+1 条，每条都新建 TCP 连接纯属白花时间。惰性创建：不翻译的会话根本不建。
        """
        if self._http_session is None:
            self._http_session = requests.Session()
        return self._http_session

    def _drop_session(self):
        session, self._http_session = self._http_session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def _request(self, method, url, **kwargs):
        """走连接池发一次请求

        **超时不重试**：一次读超时本身就是结论（冷加载慢 / 模型又被卸了），
        `_translate_one` 靠它决定要不要清 `_warm_model`；重试等于把 120 秒翻倍。
        只对"连接层面的错"重连一次 —— 连接池里那条空闲连接被服务端关了（Ollama
        空闲一会儿就会关）属于常态，丢掉换一条就行。
        """
        try:
            return self._session().request(method, url, **kwargs)
        except requests.exceptions.Timeout:
            raise
        except requests.exceptions.RequestException:
            self._drop_session()
            return self._session().request(method, url, **kwargs)

    def close(self):
        """放掉这个客户端（当前只有连接池）。幂等。"""
        self._drop_session()

    def forget_warm(self):
        """忘掉"哪个模型已经热过"（换了服务地址 / 接口类型时调）

        `_warm_model` 记的是"这个模型在显存里"，换服务之后新服务上什么都没有，而它还
        记着旧的 —— 下一次请求会按热模型的 `local_llm_timeout_ms`（3 秒）发出去，实际
        却要冷加载，必然超时回落成原文。换个服务地址还要"等它自己撞一次超时"太蠢了。
        """
        self._warm_model = None

    # ---------------------------------------------------------------- 探活

    def list_models(self):
        """列出服务里已有的模型名；**连不上返回 None**（好和"列表为空"区分开）"""
        url = self._url()
        path = "/v1/models" if self._api_style() == "openai" else "/api/tags"
        try:
            resp = self._request("GET", url + path, timeout=2)
        except Exception as e:
            self.last_error = "连不上 %s：%s" % (url, e)
            return None
        if resp.status_code != 200:
            self.last_error = "%s 返回 HTTP %s" % (url + path, resp.status_code)
            return None
        try:
            data = resp.json()
        except Exception as e:
            self.last_error = "返回内容不是 JSON：%s" % e
            return None
        items = []
        if isinstance(data, dict):
            # Ollama 的 /api/tags 是 {"models": [{"name": ...}]}，
            # OpenAI 风格的 /v1/models 是 {"data": [{"id": ...}]}
            items = data.get("models") or data.get("data") or []
        names = []
        for item in items:
            if isinstance(item, dict):
                name = item.get("name") or item.get("id") or item.get("model")
                if name:
                    names.append(name)
        self.last_error = None
        return names

    def health(self):
        """探活：只看服务在不在、配置里的模型在不在

        **不真正加载模型**（那要几秒，见 self_test）。返回 (是否可用, 一句话)。
        """
        models = self.list_models()
        if models is None:
            return False, self.last_error or "服务不可用"
        model = self._model()
        if model and model not in models:
            self.last_error = "服务里没有模型 %s" % model
            return False, "没有模型 %s（现有 %d 个）" % (model, len(models))
        return True, "服务正常，可用模型 %d 个" % len(models)

    def preload(self):
        """把模型加载进显存（跑一步最小生成）。返回 (是否成功, 一句话)。

        为什么要单独有这一步：加载那几秒（9B 冷启动 10.8 秒）和"翻一句要多久"是两件事，
        混在一次请求里报，用户会以为翻译本身要 10 秒；"测试连接"先把加载做完，还能顺带
        报出加载耗时。

        **必须是"真跑一步生成"，且 options 要和真翻译逐字一致**（都走 `_ollama_options`）：
        - `/api/generate` 不带 prompt（"只加载、不生成"）那条路不要用：它同样要把模型整个
          读进显存，却不一定让模型留在显存里；
        - `num_ctx` 这类**加载期**参数两边不一样的话，Ollama 会在下一次翻译请求到来时把
          刚加载好的 runner 卸掉重载（实测 5.06 秒），刚好把"preload 报已就绪、紧接着按
          热模型的单句超时发请求"这一步打回原形 —— 客户端一超时断开，Ollama 连这次重载
          都取消掉，最后显存里什么都不剩（日志：`aborting load` / `context canceled`）。
        `num_predict=1` 的一步生成实测必定留下常驻模型（EuroLLM 冷加载 1358ms 之后下一次
        请求 load=34ms），代价只有多生成一个 token（约 0.1 秒）；顺带替第一次真解码编译了
        CUDA 内核（和 SimulStreaming 的 warmup 是同一个道理）。
        """
        model = self._model()
        if not model:
            self.last_error = "没有配置本地模型名"
            return False, self.last_error
        # 要加载的新模型进来之前先清个场：免得刚加载好又被 Ollama 挤掉（见模块开头要点 6）。
        # 放在这里是因为界面上所有"主动加载"的路都经过本方法（`local_health()` → `self_test()`
        # → here），也就是"测试连接"和"切完模型点测试"这两条 —— 正是多模型同驻的源头。
        if config.get("unload_previous_llm_on_switch", True):
            self.unload_others(keep=[model])
        if self._api_style() == "openai":
            body = {"model": model, "stream": False, "temperature": 0.0,
                    "max_tokens": 1, "messages": [{"role": "user", "content": "."}]}
        else:
            body = {"model": model, "stream": False, "think": False,
                    "keep_alive": config.get("local_llm_keep_alive", "30m"),
                    "options": self._ollama_options(1),
                    "messages": [{"role": "user", "content": "."}]}
        started = time.time()
        try:
            resp = self._request("POST", self._url() + self._chat_path(), json=body,
                                 timeout=(2, _LOAD_READ_TIMEOUT_S))
        except Exception as e:
            self.last_error = "加载模型失败（预热请求没回来）：%s" % e
            return False, self.last_error
        if resp.status_code != 200:
            self.last_error = "加载模型返回 HTTP %s：%s" % (resp.status_code, resp.text[:200])
            return False, self.last_error
        self.last_load_ms = int((time.time() - started) * 1000)
        self._warm_model = model   # 加载过了：后面的翻译用正常的单句超时
        self.last_error = None
        return True, "模型已就绪（加载 %d ms）" % self.last_load_ms

    def self_test(self, target_language="中文"):
        """真的翻一句再回答（顺带把模型加载进显存）

        界面上的"测试连接"用这个：先 `preload()` 把加载那一段单独做完、单独计时，
        再按正常的单句超时翻一句 —— 不然 9B 光加载就 10.8 秒，报出来的"耗时"根本
        分不清是加载还是翻译（原来的写法还把加载算进了单句超时，直接超时告败）。
        返回 (是否可用, 一句话)。
        """
        ok, message = self.health()
        if not ok:
            return False, message
        loaded, load_message = self.preload()
        if not loaded:
            return False, load_message
        started = time.time()
        result = self.translate("Testing, this is Alpha Bravo.", target_language)
        elapsed_ms = int((time.time() - started) * 1000)
        if result is None:
            return False, self.last_error or "翻译失败"
        parts = []
        if self.last_load_ms is not None:
            parts.append("加载 %d ms" % self.last_load_ms)
        parts.append("翻译 %d ms" % elapsed_ms)
        if self.last_stats.get("tok_per_s"):
            parts.append("%.1f tok/s" % self.last_stats["tok_per_s"])
        return True, "正常：%s" % "，".join(parts)

    # ---------------------------------------------------------------- 卸载/驻留

    def unload(self, model=None):
        """让服务把某个模型从显存里卸掉（不给就卸配置里那一个）。返回是否成功。

        做法照抄 `check_local_translate.py` 里已经实测过的那条路：给 `/api/generate`
        发一个 `keep_alive: 0` 的空请求，Ollama 收到就立刻放掉这个模型。

        和诊断脚本刻意不同的两点：
        - **不在生产代码里轮询 `/api/ps` 确认**：那是给检查脚本用的，界面线程上跑要白等
          好几秒；"到底卸掉没有"交给 `check_gpu_reclaim.py` 去验。
        - **卸掉当前模型时必须清 `_warm_model`**（模块开头要点 6）：否则下一次翻译仍按
          "热模型"用 `local_llm_timeout_ms`（3 秒）发请求，而它其实要冷加载（1.7B-Q8 实测
          1.4 秒、9B 10.8 秒）→ 必然 ReadTimeout → 第 5 步回落成原文上屏。

        OpenAI 兼容接口（llama-server）没有通用的卸载通路，返回 False 并说明。
        """
        if self._api_style() == "openai":
            self.last_error = "OpenAI 兼容接口（llama-server）没有卸载通路，要回收请重启服务"
            return False
        model = str(model or self._model() or "").strip()
        if not model:
            self.last_error = "没有配置本地模型名"
            return False
        url = self._url()
        try:
            # model 必须点名，不能省；空 prompt 的那条路上游会当成"只加载/只卸载"
            resp = self._request("POST", url + "/api/generate",
                                 json={"model": model, "keep_alive": 0},
                                 timeout=(2, _UNLOAD_TIMEOUT_S))
        except Exception as e:
            self.last_error = "卸载模型失败（连不上 %s）：%s" % (url, e)
            return False
        if resp.status_code != 200:
            self.last_error = "卸载模型返回 HTTP %s：%s" % (resp.status_code, resp.text[:200])
            return False
        if self._warm_model == model:
            self._warm_model = None
        self.last_error = None
        return True

    def resident_models(self):
        """现在显存里有哪些模型：`[(名字, 显存 MiB, 到期时刻), …]`；**连不上返回 None**

        Ollama 的 `/api/ps` 实测（0.40.2）返回 `name/size/size_vram/expires_at/
        context_length/runner`，这里只取界面要用的三样。OpenAI 兼容接口没有这个
        通路，返回空列表（表示"问不出来"，不是"一个都没有"）。
        """
        if self._api_style() == "openai":
            return []
        url = self._url()
        try:
            resp = self._request("GET", url + "/api/ps", timeout=2)
        except Exception as e:
            self.last_error = "连不上 %s：%s" % (url, e)
            return None
        if resp.status_code != 200:
            self.last_error = "/api/ps 返回 HTTP %s" % resp.status_code
            return None
        try:
            data = resp.json()
        except Exception as e:
            self.last_error = "返回内容不是 JSON：%s" % e
            return None
        items = data.get("models") if isinstance(data, dict) else data
        result = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            if not name:
                continue
            size = item.get("size_vram") or item.get("size") or 0
            try:
                size_mib = int(size) // (1024 * 1024)
            except (TypeError, ValueError):
                size_mib = 0
            result.append((name, size_mib, item.get("expires_at")))
        self.last_error = None
        return result

    def unload_others(self, keep=None):
        """卸掉除 `keep` 之外所有驻留的模型，返回卸掉的数量

        8 GB 卡上"EuroLLM(1.73GB) + Spark(3.52GB) 同时驻留"就是这么来的（本机实测）。
        白占显存只是其一：Ollama 会为了给新模型腾地方把**正在用的**那个挤掉重载，
        界面上看着就是"某些句子突然回落成原文"。所以切模型前先清场。

        `keep` 是模型名（字符串或列表）；配置里当前在用的那个永远保留。连不上服务
        或压根没有多余模型时返回 0，不抛异常。
        """
        keep = set([keep] if isinstance(keep, str) else (keep or []))
        keep.discard("")
        keep.add(self._model())
        resident = self.resident_models()
        if not resident:
            return 0
        count = 0
        for name, _size_mib, _expires in resident:
            if name in keep:
                continue
            if self.unload(name):
                count += 1
        return count

    # ---------------------------------------------------------------- 翻译

    def translate(self, text, target_language, source_language=None):
        """翻一段文本

        成功返回译文，失败返回 None（原因写在 last_error 里，不抛异常）。
        source_language 不给就从配置里读（配置存的是 "auto"/"en" 这类代码）。
        """
        text = _strip_glosses((text or "").strip())
        if not text:
            return ""
        segments = split_markers(text)
        if len(segments) <= 1:
            # 没有术语标记（大多数句子）：一次请求搞定
            return self._translate_one(text, target_language, source_language)
        return self._translate_segments(segments, target_language, source_language)

    def _translate_segments(self, segments, target_language, source_language):
        """逐片段翻译，标记由我们自己拼回去（理由见模块开头的要点 2）"""
        pieces = []
        for is_marker, chunk in segments:
            if is_marker:
                # 标记原样穿过：模型根本看不到它，也就无从丢它、挪它
                pieces.append(chunk)
                continue
            core = chunk.strip()
            if not core or not any(ch.isalpha() for ch in core):
                # 纯空白/标点/数字，不值得为它单独跑一次推理
                pieces.append(chunk)
                continue
            translated = self._translate_one(core, target_language, source_language)
            if translated is None:
                # 有一段没翻成，整体算失败：宁可回落一整句，也不要拼出半句
                return None
            lead = chunk[:len(chunk) - len(chunk.lstrip())]
            trail = chunk[len(chunk.rstrip()):]
            pieces.append(lead + translated.strip() + trail)
        return "".join(pieces)

    def _translate_one(self, source_text, target_language, source_language=None):
        """一次请求翻一段（不含术语标记的纯文本）"""
        payload = self._payload(source_text, target_language, source_language)
        timeout_ms = int(config.get("local_llm_timeout_ms", 3000) or 3000)
        url = self._url() + self._chat_path()
        # 这个模型还没热过：这一次请求里含"读进显存"，读超时按 _LOAD_READ_TIMEOUT_S 放（要点 4）
        cold = self._warm_model != self._model()
        read_timeout = _LOAD_READ_TIMEOUT_S if cold else max(0.5, timeout_ms / 1000.0)
        started = time.time()
        try:
            # (连接超时, 读取超时)：本机服务连接是瞬时的，超时基本都发生在生成上
            resp = self._request("POST", url, json=payload, timeout=(2, read_timeout))
        except Exception as e:
            self.last_error = self._request_error(e, cold, timeout_ms)
            if not cold and isinstance(e, requests.exceptions.Timeout):
                # 热过的模型也可能早被卸掉（keep_alive 到期、换过服务地址）：这一句认栽，
                # 但下一次请求按"没热过"走长超时，自己爬起来，不会一直卡在 3 秒上
                self._warm_model = None
            return None
        if resp.status_code != 200:
            self.last_error = "本地服务返回 HTTP %s：%s" % (resp.status_code, resp.text[:200])
            return None
        try:
            data = resp.json()
        except Exception as e:
            self.last_error = "返回内容不是 JSON：%s" % e
            return None
        content = self._extract_content(data).strip()
        if not content:
            self.last_error = self._empty_error(data)
            return None
        self.last_error = None
        self._warm_model = self._model()   # 这个模型已经在显存里了
        self._record_stats(data, started)
        return content

    def _request_error(self, error, cold, timeout_ms):
        """超时要说清是"加载慢"还是"模型又被卸了"，别让人对着 ReadTimeout 猜"""
        if not isinstance(error, requests.exceptions.Timeout):
            return "本地翻译请求失败：%s" % error
        if cold:
            return ("本地翻译请求失败：模型加载超过 %.0f 秒（第一次请求要把模型读进显存；"
                    "实测 9B-Q4 冷加载 10.8 秒、1.7B-Q8 1.4 秒）：%s"
                    % (_LOAD_READ_TIMEOUT_S, error))
        return ("本地翻译请求失败：等模型回话超过 %d ms（模型可能又被 Ollama 卸掉了——"
                "换过模型/服务地址/上下文长度，或闲置超过 keep_alive；下一次请求会自动按"
                "加载放宽，想立刻恢复就点一次「测试连接」）：%s"
                % (timeout_ms, error))

    @staticmethod
    def _empty_error(data):
        """拿到空译文：分清楚是"思考型模型没关思考"还是"模型真没话说"（要点 5）"""
        thinking = LocalLLMTranslator._extract_thinking(data)
        if thinking:
            return ("模型把 %d 个字的输出全花在思考过程里，没给译文"
                    "（done_reason=%s；这个模型当翻译用不合适，换个非思考型的）"
                    % (len(thinking), (data or {}).get("done_reason")))
        return "模型返回了空译文"

    # ---------------------------------------------------------------- 内部

    def _url(self):
        return str(config.get("local_llm_url", "http://127.0.0.1:11434") or "").strip().rstrip("/")

    def _model(self):
        return str(config.get("local_llm_model", "") or "").strip()

    def _api_style(self):
        """ollama = Ollama 原生接口（能设 keep_alive、能拿到耗时明细）；openai = 兼容接口"""
        style = str(config.get("local_llm_api", "ollama") or "ollama").strip().lower()
        return "openai" if style in ("openai", "llama-server", "llamaserver") else "ollama"

    def _chat_path(self):
        return "/v1/chat/completions" if self._api_style() == "openai" else "/api/chat"

    def _ollama_options(self, num_predict):
        """Ollama 的 options 块。**preload 和真翻译必须逐字一致**：`num_ctx` 是加载期参数
        （Ollama 按它启动 llama-server，日志里的 `-c 2048`），两边给的值不一样，Ollama 会
        把已经在显存里的 runner 卸掉、按新参数重载一次 —— 那一次重载正好发生在"preload 说
        已就绪、紧接着按热模型发翻译"之间，于是超时告败（实测一次 5.06 秒，而且客户端一
        断开，Ollama 就把这次重载也取消了，最后显存里什么都不剩）。
        """
        return {
            "temperature": float(config.get("local_llm_temperature", 0.0) or 0.0),
            "num_predict": num_predict,
            "num_ctx": int(config.get("local_llm_num_ctx", 2048) or 2048),
        }

    def _payload(self, text, target_language, source_language=None):
        if source_language is None:
            source_language = config.get("source_language", "auto")
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(text, target_language, source_language)},
        ]
        temperature = float(config.get("local_llm_temperature", 0.0) or 0.0)
        num_predict = int(config.get("local_llm_num_predict", 256) or 256)
        if self._api_style() == "openai":
            return {
                "model": self._model(),
                "messages": messages,
                "stream": False,
                "temperature": temperature,
                "max_tokens": num_predict,
            }
        return {
            "model": self._model(),
            "messages": messages,
            "stream": False,
            # 思考型模型（Spark-X2.5、DeepSeek-R1 这类）不关思考的话，会把 num_predict
            # 全烧在 message.thinking 上、content 留空（实测 Spark-1.7B：done_reason=length、
            # content=''、thinking 977 字）。实测 EuroLLM-1.7B/9B 与 Spark 都接受这个字段，
            # 不支持的模型会忽略它，所以无脑加上。OpenAI 兼容那条路不加：那边开关思考
            # 是 chat template 的事，多塞字段反而可能被严格的实现拒掉。
            "think": False,
            "keep_alive": config.get("local_llm_keep_alive", "30m"),
            "options": self._ollama_options(num_predict),
        }

    @staticmethod
    def _extract_content(data):
        if not isinstance(data, dict):
            return ""
        message = data.get("message")            # Ollama 原生
        if isinstance(message, dict):
            return message.get("content") or ""
        choices = data.get("choices") or []      # OpenAI 兼容（llama-server）
        if choices and isinstance(choices[0], dict):
            return ((choices[0].get("message") or {}).get("content")) or ""
        return ""

    @staticmethod
    def _extract_thinking(data):
        """思考型模型的推理正文（只用来诊断"为什么 content 是空的"）"""
        if not isinstance(data, dict):
            return ""
        message = data.get("message") or {}
        if isinstance(message, dict) and (message.get("thinking") or message.get("reasoning")):
            return message.get("thinking") or message.get("reasoning")
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            return ((choices[0].get("message") or {}).get("reasoning_content")) or ""
        return ""

    def _record_stats(self, data, started):
        """记下耗时明细：只看总时间分不清"慢在加载模型"还是"慢在生成"

        Ollama 会在响应里自报 load/eval 这几段（纳秒），有就换算成毫秒；顺便用
        eval_count/eval_duration 算出生成速度 tok/s —— 判断"比谷歌快了多少"就靠它。
        """
        stats = {"total_ms": int((time.time() - started) * 1000)}
        if isinstance(data, dict):
            for key in ("load_duration", "prompt_eval_duration", "eval_duration"):
                value = data.get(key)
                if isinstance(value, (int, float)):
                    stats[key.replace("_duration", "_ms")] = int(value / 1e6)
            count = data.get("eval_count")
            if count and stats.get("eval_ms"):
                stats["eval_count"] = count
                stats["tok_per_s"] = round(count / (stats["eval_ms"] / 1000.0), 1)
        self.last_stats = stats


def _user_prompt(text, target_language, source_language):
    """按 EuroLLM 官方格式拼 user 回合（语言名认不出来时退回不点名的 "text" 写法）

    两种写法都在本机实测过，译文一致；点名源语言只是锦上添花。
    源语言是 "auto"（自动检测）时我们并不知道它是什么，就不点名。
    """
    target = language_name(target_language) or "Chinese"
    source = language_name(source_language)
    if source and source.lower() != "auto":
        instruction = ("Translate the following %s source text to %s, "
                       "keeping tokens like __TERM_0__ unchanged:" % (source, target))
        body = "%s: %s\n%s:" % (source, text, target)
    else:
        instruction = ("Translate the following text to %s, "
                       "keeping tokens like __TERM_0__ unchanged:" % target)
        body = "Source: %s\n%s:" % (text, target)
    return "%s\n%s" % (instruction, body)
