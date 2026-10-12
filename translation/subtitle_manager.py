from googletrans import Translator
import time
import threading
from collections import OrderedDict

from config import config
from model_residency import model_residency
from translation.local_llm_translator import (LocalLLMTranslator,
                                              normalize_placeholders,
                                              strip_leftover_placeholders)
from translation.term_manager import TermManager
import re
import uuid
import traceback

class SubtitleManager:
    def __init__(self):
        self.translator = Translator()
        # 整段翻译结果的 LRU 缓存：键是 (后端签名, 目标语言, 原文)，值就是最后要显示的文本。
        # 业余无线电里 "Roger"、"QSL"、"five nine" 这类重复率极高，命中一次就省掉一整轮
        # 术语处理 + 翻译 + 还原。后端签名参与键，所以换了引擎/模型自然就不会命中旧译文。
        self.translation_cache = OrderedDict()
        self.translation_cache_size = 256
        # 本地翻译客户端，用时才建（translation_backend == "local" 才用得上）
        self.local_translator = None
        self.local_last_error = None
        self.lock = threading.Lock()  # 线程锁，防止多线程同时访问缓存

        # 把本地大模型登记进全局显存账本（闲置自动卸载、「释放显存」都读它）。
        # release_fn 必须是"查当前状态"的薄方法，不能闭包捕获某个 translator 对象。
        model_residency.register("llm", "本地翻译", self._release_local_model,
                                 kind="ollama")
        
        # 初始化术语管理器
        self.term_manager = TermManager()
        
        # 翻译延迟计时
        self.translation_delay = 0  # 翻译延迟（毫秒）
        
        # 调试模式
        self.debug = False
        
        # 语言代码映射
        self.language_map = {
            "中文": "zh-cn",
            "英语": "en",
            "日语": "ja",
            "韩语": "ko",
            "法语": "fr",
            "德语": "de",
            "俄语": "ru",
            "西班牙语": "es"
        }
        
        # 语言代码到显示名称的映射
        self.language_code_to_name = {
            "zh": "中文",
            "en": "英语",
            "ja": "日语",
            "ko": "韩语",
            "fr": "法语",
            "de": "德语",
            "ru": "俄语",
            "es": "西班牙语",
            "it": "意大利语",
            "pt": "葡萄牙语",
            "nl": "荷兰语",
            "pl": "波兰语",
            "ar": "阿拉伯语",
            "tr": "土耳其语",
            "th": "泰语",
            "vi": "越南语",
            "id": "印尼语",
            "hi": "印地语",
            "fa": "波斯语",
            "bg": "保加利亚语",
            "cs": "捷克语",
            "el": "希腊语",
            "fi": "芬兰语",
            "hu": "匈牙利语",
            "no": "挪威语",
            "ro": "罗马尼亚语",
            "sv": "瑞典语",
            "uk": "乌克兰语",
            "ca": "加泰罗尼亚语",
            "hr": "克罗地亚语",
            "da": "丹麦语",
            "he": "希伯来语",
            "ur": "乌尔都语",
            "vi": "越南语",
            "id": "印尼语",
            "hi": "印地语",
            "fa": "波斯语",
            "bg": "保加利亚语",
            "cs": "捷克语"
        }
    
    def translate(self, text, target_language, debug=False):
        """
        翻译文本，处理业余无线电术语
        
        参数:
            text (str): 要翻译的文本
            target_language (str): 目标语言
            debug (bool): 是否输出调试信息
            
        返回:
            str: 翻译后的文本
        """
        if not text:
            return ""

        # 获取目标语言代码
        target_code = self.get_language_code(target_language)
        if not target_code:
            return text

        # 翻译现在由后台线程驱动。加锁一是保护 googletrans 客户端的内部状态
        # （它不见得线程安全），二是保证术语表处理不会和其他调用交叉。
        with self.lock:
            return self._translate_locked(text, target_code, debug)

    def _translate_locked(self, text, target_code, debug=False):
        """实际执行翻译，调用前必须持有 self.lock"""
        # 记录开始时间
        start_time = time.time()

        # 同一句话 + 同一个引擎/模型翻过就直接用（重复的短句在业余无线电里很常见）
        cache_key = (self._backend_signature(), target_code, text)
        cached = self.translation_cache.get(cache_key)
        if cached is not None:
            self.translation_cache.move_to_end(cache_key)
            self.translation_delay = int((time.time() - start_time) * 1000)
            if debug:
                print(f"命中翻译缓存: {cached}")
            return cached

        try:
            # 步骤1: 处理信号报告
            processed_text = self.term_manager.extract_and_convert_signal_report(text)
            if debug:
                print(f"步骤1 - 信号报告处理: {processed_text}")
            
            # 步骤2: 处理特殊术语
            special_terms_processed = self.term_manager.direct_translate(processed_text, target_code)
            if debug:
                print(f"步骤2 - 特殊术语处理: {special_terms_processed}")
            
            # 步骤3: 处理字母解释法呼号
            processed_text = self.term_manager.extract_and_convert_phonetic_callsign(special_terms_processed)
            if debug:
                print(f"步骤3 - 呼号处理: {processed_text}")
            
            # 步骤4: 预处理术语
            preprocessed_text, replacements = self.term_manager.preprocess_ham_radio_terms(processed_text, target_code)
            if debug:
                print(f"步骤4 - 术语预处理: {preprocessed_text}")
                print(f"术语替换表: {replacements}")
            
            # 步骤5: 翻译非术语部分（传输层按 translation_backend 分派：本地模型 / 谷歌）
            try:
                translated_text = self._transport_translate(preprocessed_text, target_code, debug)
                if debug:
                    print(f"步骤5 - 基础翻译: {translated_text}")
            except Exception as e:
                if debug:
                    print(f"翻译环节出错: {str(e)}")
                # 如果翻译失败，返回处理后的文本
                return processed_text

            # 步骤6: 还原术语占位符
            try:
                # 本地模型偶尔会把占位符写花（多加空格、下划线个数不对），先规整回 __TERM_0__；
                # 只有这一步的输入确实带占位符时才做，免得误伤正常译文里的 "term 3" 之类。
                if replacements:
                    translated_text = normalize_placeholders(translated_text)
                final_text = self.term_manager.restore_ham_radio_terms(translated_text, replacements)

                # 检查是否还有未替换的占位符
                if '__TERM_' in final_text or '__term_' in final_text:
                    # 如果还有未替换的占位符，尝试再次执行替换
                    final_text = self.term_manager.restore_ham_radio_terms(final_text, replacements)

                # 两轮还原之后还留着，说明模型把占位符写得太花、匹配不上了：把残骸抠掉。
                # 字幕上绝不能出现 __TERM_0__ 这种机器码（代价是这个术语的译文丢了）。
                if replacements and 'TERM' in final_text.upper():
                    final_text = strip_leftover_placeholders(final_text)

                if debug:
                    print(f"步骤6 - 术语还原: {final_text}")
            except Exception as e:
                if debug:
                    print(f"术语还原出错: {str(e)}")
                    traceback.print_exc()
                # 如果还原失败，返回翻译后的文本
                final_text = translated_text

            # 计算翻译延迟
            end_time = time.time()
            self.translation_delay = int((end_time - start_time) * 1000)
            # 只缓存走完整条管线的结果（上面任何一步失败都已经提前 return 了）
            self._cache_put(cache_key, final_text)

            return final_text
            
        except Exception as e:
            if debug:
                print(f"翻译过程出错: {str(e)}")
                traceback.print_exc()
            # 发生错误时返回原文或经过处理的文本
            # 优先返回经过呼号处理的文本，这样至少保留了基本处理
            try:
                if 'processed_text' in locals():
                    return processed_text
                else:
                    return text
            except:
                return text
    
    def _backend_signature(self):
        """缓存键的一部分：换了引擎/模型/地址，旧译文就不该再命中"""
        backend = str(config.get("translation_backend", "local") or "local").lower()
        if backend == "google":
            return "google"
        return "local|%s|%s" % (config.get("local_llm_url", ""), config.get("local_llm_model", ""))

    def _cache_put(self, key, value):
        """放进 LRU 缓存（调用前必须持有 self.lock）"""
        self.translation_cache[key] = value
        self.translation_cache.move_to_end(key)
        while len(self.translation_cache) > self.translation_cache_size:
            self.translation_cache.popitem(last=False)

    def clear_cache(self):
        """清空翻译缓存（不调也不会串味：缓存键里带着后端签名）"""
        with self.lock:
            self.translation_cache.clear()

    def _get_local_translator(self):
        if self.local_translator is None:
            self.local_translator = LocalLLMTranslator()
        return self.local_translator

    def local_health(self):
        """给界面的"测试连接"用：探活 + 真翻一句（顺带把模型加载进显存）"""
        return self._get_local_translator().self_test()

    def local_models(self):
        """给界面的下拉框用：本地服务里都有哪些模型（连不上返回空列表）"""
        return self._get_local_translator().list_models() or []

    def local_resident_models(self):
        """现在显存里驻留着哪些模型（`[(名, MiB, 到期时刻), …]`，连不上返回 []）"""
        return self._get_local_translator().resident_models() or []

    def local_unload(self, model=None):
        """把本机大模型从显存里卸掉（闲置回收 / 「释放显存」/ 切翻译引擎走这里）"""
        return self._get_local_translator().unload(model)

    def local_unload_others(self, keep=None):
        """卸掉除 `keep` 之外所有驻留的模型（换模型时先清场），返回卸掉的数量"""
        return self._get_local_translator().unload_others(keep)

    def _release_local_model(self):
        """显存账本的回调：卸掉本机的翻译模型（没建过客户端就什么都不用做）"""
        if self.local_translator is None:
            return
        self.local_translator.unload()

    def close_local(self):
        """放掉本地翻译客户端（关窗口时调）"""
        if self.local_translator is not None:
            self.local_translator.close()

    def local_forget_warm(self):
        """换了服务地址/接口类型之后，别再以为旧服务上的模型还是热的"""
        if self.local_translator is not None:
            self.local_translator.forget_warm()

    def _transport_translate(self, preprocessed_text, target_code, debug=False):
        """第 5 步那一次真正的传输：按 translation_backend 分派到本地模型或谷歌

        和原来一样，失败时**抛异常**，由调用处（步骤 5 的 except）决定回落 —— 那边会返回
        已处理的文本，字幕不至于崩掉。
        """
        backend = str(config.get("translation_backend", "local") or "local").lower()
        if backend == "google":
            if debug:
                print("翻译后端: Google（公网）")
            return self.translator.translate(preprocessed_text, dest=target_code).text

        translator = self._get_local_translator()
        if debug:
            print("翻译后端: 本地 %s" % config.get("local_llm_model", ""))
        result = translator.translate(preprocessed_text, target_code)
        self.local_last_error = translator.last_error
        if result is not None:
            # 刚用过：重置闲置计时（这一句之后模型确确实实留在显存里了）
            model_residency.touch("llm")
            return result
        if config.get("local_llm_fallback_to_google", False):
            if debug:
                print("本地翻译失败（%s），按设置回落到谷歌" % translator.last_error)
            return self.translator.translate(preprocessed_text, dest=target_code).text
        raise RuntimeError("本地翻译失败：%s" % (translator.last_error or "未知原因"))

    def _restore_case(self, translated_text, original_patterns):
        """
        恢复译文中的英文单词大小写为原文中的大小写形式
        
        参数:
            translated_text (str): 翻译后的文本
            original_patterns (dict): 原文中的英文单词及其大小写形式，格式为 {小写单词: 原始单词}
            
        返回:
            str: 恢复大小写后的文本
        """
        if not original_patterns:
            return translated_text
        
        import re
        
        # 处理常见的技术术语和缩写（按长度排序，优先匹配较长的词）
        # 这里添加了一些常见的技术术语，可以根据需要扩展
        technical_terms = sorted(["WIFI", "GPS", "CPU", "GPU", "RAM", "ROM", "USB", "SSD", 
                        "HDD", "LCD", "LED", "HD", "UHD", "SD", "HDMI", "VGA", "DVI", 
                        "LAN", "WAN", "IP", "TCP", "UDP", "HTTP", "HTTPS", "FTP", "SSH",
                        "MHz", "GHz", "KB", "MB", "GB", "TB", "PDF", "HTML", "XML", "CSS",
                        "RGB", "CMYK", "FAQ", "NASA", "IBM", "AMD", "PIN", "AI"],
                        key=len, reverse=True)
        
        result = translated_text
        
        # 首先处理常见的技术术语和缩写，强制它们保持大写
        for term in technical_terms:
            # 精确匹配术语，考虑单词边界
            term_pattern = re.compile(r'\b' + term.lower() + r'\b', re.IGNORECASE)
            result = term_pattern.sub(term, result)
        
        # 然后处理原文中提取的自定义单词模式
        # 使用更通用的正则表达式匹配英文字符序列
        eng_pattern = re.compile(r'[a-zA-Z]+')
        
        # 函数：保留原文中的大小写
        def replace_case(match):
            word = match.group(0)
            word_lower = word.lower()
            if word_lower in original_patterns:
                return original_patterns[word_lower]
            return word
        
        # 应用替换
        result = eng_pattern.sub(replace_case, result)
        
        return result
    
    def get_translation_delay(self):
        """获取翻译延迟（毫秒）"""
        return self.translation_delay
    
    def get_subtitle_style(self, position="底部", font_size=24, color="white"):
        """
        获取字幕的CSS样式
        
        参数:
            position (str): 字幕位置（顶部、中间、底部）
            font_size (int): 字体大小
            color (str): 字体颜色
            
        返回:
            str: CSS样式字符串
        """
        # 根据位置设置样式
        position_styles = {
            "顶部": "top: 10%; left: 50%; transform: translateX(-50%);",
            "中间": "top: 50%; left: 50%; transform: translate(-50%, -50%);",
            "底部": "bottom: 10%; left: 50%; transform: translateX(-50%);"
        }
        
        position_style = position_styles.get(position, position_styles["底部"])
        
        # 构建完整的CSS样式
        style = f"""
            position: fixed;
            {position_style}
            color: {color};
            font-size: {font_size}px;
            font-family: Arial, sans-serif;
            background-color: rgba(0, 0, 0, 0.5);
            padding: 5px 10px;
            border-radius: 5px;
            text-align: center;
            max-width: 80%;
            z-index: 9999;
        """
        
        return style
    
    def get_language_name(self, language_code):
        """根据语言代码获取语言名称"""
        return self.language_code_to_name.get(language_code, f"未知({language_code})")
        
    def get_term_manager(self):
        """获取术语管理器实例"""
        return self.term_manager
        
    def edit_terms(self):
        """打开术语文件进行编辑"""
        return self.term_manager.open_term_file()
        
    def reload_terms(self):
        """重新加载术语定义"""
        return self.term_manager.reload_terms()
        
    def get_term_file_path(self):
        """获取术语文件路径"""
        return self.term_manager.term_file
    
    def get_language_code(self, language_name):
        """
        将语言名称转换为语言代码
        
        参数:
            language_name (str): 语言名称（如"中文"、"英语"等）
            
        返回:
            str: 语言代码（如"zh-cn"、"en"等）
        """
        # 语言名称到代码的映射
        language_map = {
            "中文": "zh-cn",
            "英语": "en",
            "日语": "ja",
            "韩语": "ko",
            "法语": "fr",
            "德语": "de",
            "俄语": "ru",
            "西班牙语": "es",
            "不翻译": None
        }
        
        # 返回对应的语言代码，如果没有找到则返回None
        return language_map.get(language_name) 