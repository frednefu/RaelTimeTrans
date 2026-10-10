"""量一量本地翻译到底比谷歌快多少、术语有没有翻丢

背景：原来的翻译走 googletrans 的公网免费接口，实测单句 2.1~2.7 秒（见
translation/translation_worker.py 的文件头），还会被限流、断网即废。现在默认换成
本机的 EuroLLM（translation/local_llm_translator.py 调 Ollama / llama-server）。
这个脚本回答三个问题：

1. **快了多少**：逐句计时，并拿生成的 tok/s 判断模型到底跑在 GPU 上还是内存里
   （本机实测：GPU 约 95 tok/s、单句 150~200ms；退化到 CPU 只有约 13 tok/s、单句 3.7 秒，
   比谷歌还慢 —— 那种时候先去看 Ollama 是不是没吃上显卡）。
2. **术语有没有丢**：信号报告（five by nine → 59）、术语表（CQ / 73 / Roger）这些
   必须原样出现在译文里。本地小模型对 `__TERM_0__` 这类占位符很不老实（会合并、
   会吞掉、会挪到句尾），所以第 5 步的传输是"把标记当分隔符、只翻中间片段"，
   这里就按真实句子验证这条通路。顺带拒收"提示词残渣"（`ECHO_MARKERS`）：术语都在、
   但译文后面跟着 "来源：…" 这种脚手架，同样算不过（实测 Spark-X2.5-1.7B 就是这样）。
3. **连不上时会不会炸**：把服务地址指到一个死端口，确认翻译**不抛异常**、老老实实
   回落到已处理的原文（工作线程里抛异常会毁掉整次识别结果，见 CLAUDE.md）。
4. **冷加载算不算进单句超时**：把模型从显存里卸掉，再把「单句超时」压到 300ms 翻一句。
   修好之前这里必然 ReadTimeout —— 实测 9B-Q4（5.6GB）冷加载 **10.8 秒**、Spark-1.7B 4.4 秒、
   1.7B-Q8 1.4 秒，而 requests 的读超时管的是"等到第一个字节"，加载全发生在第一个字节之前，
   于是"换个模型第一次翻译必定失败"。修好之后第一次请求走 _LOAD_READ_TIMEOUT_S，照样出译文。

用法：

    python check_local_translate.py              # 按 settings.json 里的配置跑
    python check_local_translate.py small        # 换一个模型名（本地服务里的名字）
    python check_local_translate.py --no-google  # 跳过与谷歌的耗时对比
    python check_local_translate.py --no-cold    # 跳过第 4 项（会真的装卸模型，慢）

注意：跑"死端口回落"那一段时会**临时改写 settings.json 里的 local_llm_url**，
跑第 4 项时会临时改写单句超时；跑完（含出错退出）都会恢复原值。
"""
import sys
import time

import requests

from config import config
from translation.local_llm_translator import LocalLLMTranslator
from translation.subtitle_manager import SubtitleManager

# 真实用语 + 译文里**必须**出现的字样（术语翻丢了就是这里挂）
CASES = [
    ("Roger, copy that.", ["收到", "明白"]),
    ("CQ CQ this is BG7YYK calling CQ CQ", ["CQ"]),
    ("Your signal is five by nine", ["59"]),
    ("say 73 and I just may be listening.", ["73"]),
    ("CQ CQ this is BG7YYK calling. Roger, your signal is five by nine",
     ["CQ", "59", "收到", "明白"]),
    ("This is Alpha Bravo Charlie Delta Echo", ["ABCDE"]),
]

DEAD_URL = "http://127.0.0.1:9"   # 9 号端口（discard）不会有人监听

# 译文里**不该**出现的东西：提示词自己的残渣。思考型模型（实测 Spark-X2.5-1.7B）就算
# 用 "think": false 关掉了思考，也会把 "Source: …\nChinese:" 这套脚手架接在译文后面
# 一起吐出来（"收到，来源：罗杰，收到，。" / "您的信号是59\n。中文"）。术语倒是都在，
# 只看术语会判它"通过"——所以这类残渣单独算不过。
ECHO_MARKERS = ["来源：", "来源:", "Source:", "中文:", "中文：", "English:"]


def _fmt_ms(seconds):
    return "%.0f ms" % (seconds * 1000)


def run_cases(manager, target="中文", verbose=True):
    """跑一遍真实句子，返回 (通过数, 总数, 每句耗时列表)"""
    passed = 0
    times = []
    for text, expected in CASES:
        started = time.time()
        try:
            result = manager.translate(text, target)
        except Exception as e:                      # 这里不该发生：翻译失败也只回落
            print("  [失败] %-58s 抛异常：%s" % (text, e))
            continue
        elapsed = time.time() - started
        times.append(elapsed)
        missing = [word for word in expected if word not in result]
        echo = [mark for mark in ECHO_MARKERS if mark in result]
        if missing or echo:
            problem = []
            if missing:
                problem.append("少了 %s" % missing)
            if echo:
                problem.append("混着提示词残渣 %s" % echo)
            print("  [失败] %-58s %s → %s" % (text, "、".join(problem), result))
        else:
            passed += 1
            if verbose:
                print("  [通过] %-58s → %s（%s）" % (text, result, _fmt_ms(elapsed)))
    return passed, len(CASES), times


def unload_model(model):
    """把模型从显存里卸掉，**并确认真的卸掉了**（返回 True/False）

    `/api/generate` 不带 prompt、keep_alive=0 就是"卸"。卸不掉就别往下验：模型还在显存里
    的话，"冷加载"那一炮会变成"热着翻一句"，300ms 也可能够快，这条检查就成了空跑。
    """
    try:
        resp = requests.post("http://127.0.0.1:11434/api/generate",
                             json={"model": model, "keep_alive": 0}, timeout=(2, 60))
        if resp.status_code != 200:
            return False
        for _ in range(10):          # 卸载是异步的，给它几秒
            running = requests.get("http://127.0.0.1:11434/api/ps", timeout=5).json()
            names = [m.get("name") for m in running.get("models", [])]
            if model not in names:
                return True
            time.sleep(0.5)
    except Exception:
        return False
    return False


def check_cold_start(translator, model):
    """冷加载那一炮：卸掉模型 + 把单句超时压到 300ms，看能不能照样翻出来

    这条通路修好之前的表现是：`local_llm_timeout_ms`（默认 3000）比冷加载（9B 实测
    10.8 秒）还短，换个模型之后第一句必定 ReadTimeout、回落成原文。
    """
    if str(config.get("local_llm_api", "ollama")).lower().startswith("openai"):
        print("  接口是 OpenAI 兼容，没有「只加载/卸载」这一说，跳过")
        return True
    if not unload_model(model):
        print("  没卸成（服务可能不是 Ollama、端点不通，或模型还挂在显存里），跳过")
        return True
    original_timeout = config.get("local_llm_timeout_ms", 3000)
    try:
        config.set("local_llm_timeout_ms", 300)
        started = time.time()
        # 新开一个 translator，免得它记得"这个模型热过"
        fresh = LocalLLMTranslator()
        result = fresh.translate("Cold start check, this is Alpha Bravo.", "中文")
        elapsed = time.time() - started
        if result:
            print("  通过：单句超时压到 300ms、模型已被卸掉，第一次请求仍翻出来了"
                  "（%.2fs，含加载）→ %s" % (elapsed, result))
            print("        这一炮修好之前必然失败，原因会是：%s" % (fresh.last_error or "（无）"))
            return True
        print("  不通过：模型被卸掉后第一次请求还是没翻出来（%.2fs）：%s"
              % (elapsed, fresh.last_error))
        return False
    finally:
        config.set("local_llm_timeout_ms", original_timeout)
        translator.preload()   # 把模型放回去，后面的用例不用再冷一遍


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    with_google = "--no-google" not in flags
    with_cold = "--no-cold" not in flags

    model = args[0] if args else config.get("local_llm_model", "")
    original_url = config.get("local_llm_url", "")
    original_backend = config.get("translation_backend", "local")
    original_model = config.get("local_llm_model", "")

    print("=" * 70)
    print("本地翻译自检")
    print("  服务地址: %s（接口 %s）" % (original_url, config.get("local_llm_api", "ollama")))
    print("  模型: %s" % model)
    if model and model != original_model:
        config.set("local_llm_model", model)
    config.set("translation_backend", "local")

    failures = []
    try:
        translator = LocalLLMTranslator()
        models = translator.list_models()
        if models is None:
            print("\n[失败] 连不上本地服务：%s" % translator.last_error)
            print("       先确认服务在跑（Ollama：任务栏图标 / `ollama ps`）；")
            print("       装了但没跑的话：ollama serve，或直接 `ollama run %s`" % model)
            return 1
        print("  服务里的模型: %d 个%s" % (len(models),
                                        "" if model in models else "（注意：没有 %s）" % model))
        ok, message = translator.self_test()
        print("\n测试连接: %s —— %s" % ("正常" if ok else "失败", message))
        if not ok:
            failures.append("测试连接失败")

        # 逐句计时 + 术语检查（走 SubtitleManager 的完整管线，不是只调模型）
        print("\n逐句翻译（含术语管线）:")
        print("-" * 70)
        manager = SubtitleManager()
        passed, total, times = run_cases(manager)
        if times:
            print("-" * 70)
            print("单句耗时：平均 %s，最长 %s，最短 %s（%d 句）"
                  % (_fmt_ms(sum(times) / len(times)), _fmt_ms(max(times)),
                     _fmt_ms(min(times)), len(times)))
        if passed < total:
            failures.append("术语检查 %d/%d" % (passed, total))
        else:
            print("术语检查：%d/%d 全部通过" % (passed, total))

        # 冷加载不能算进单句超时（换个模型之后第一句必挂的那个坑）
        if with_cold:
            print("\n冷加载（模型卸掉 + 单句超时压到 300ms）:")
            print("-" * 70)
            if not check_cold_start(translator, model):
                failures.append("冷加载后第一次翻译失败")

        # 连不上时必须回落，绝不能抛异常
        print("\n连不上本地服务时（地址指向死端口 %s）:" % DEAD_URL)
        print("-" * 70)
        config.set("local_llm_url", DEAD_URL)
        try:
            weird = "This sentence only exists to test the offline fallback %d." % int(time.time())
            result = manager.translate(weird, "中文")
            if result:
                print("  [通过] 没有抛异常，返回了回落文本: %s" % result[:60])
            else:
                print("  [失败] 返回了空文本")
                failures.append("死端口回落返回空")
        except Exception as e:
            print("  [失败] 抛异常了：%s" % e)
            failures.append("死端口回落抛异常")
        finally:
            config.set("local_llm_url", original_url)

        # 同一句的谷歌耗时对比（只为给个参照，谷歌失败不算错）
        if with_google:
            print("\n谷歌后端对比（同一句）:")
            print("-" * 70)
            config.set("translation_backend", "google")
            sample = "Roger, your signal is five by nine and I am running one hundred watts."
            started = time.time()
            try:
                google_text = manager.translate(sample, "中文")
                google_ms = time.time() - started
                print("  %s" % google_text)
                print("  谷歌 %s" % _fmt_ms(google_ms))
            except Exception as e:
                print("  谷歌这条路现在不通（%s）—— 本地后端正是为这种情况准备的" % e)
            finally:
                config.set("translation_backend", "local")

        print("\n" + "=" * 70)
        if failures:
            print("有 %d 项没过：%s" % (len(failures), "；".join(failures)))
            return 1
        print("全部通过。")
        print("提示：单句耗时里如果混着「第一次请求」，那是模型被卸掉后重新加载"
              "（实测 9B 冷加载 10.8 秒）；这一步不算进单句超时，之后一直留在显存里。")
        return 0
    finally:
        # 不管怎么退出，都别把用户的服务地址/后端留在临时值上
        config.set("local_llm_url", original_url)
        config.set("local_llm_model", original_model)
        config.set("translation_backend", original_backend)


if __name__ == "__main__":
    sys.exit(main())
