from googletrans import Translator
import time
import threading
from translation.term_manager import TermManager
import re
import uuid
import traceback

class SubtitleManager:
    def __init__(self):
        self.translator = Translator()
        self.translation_cache = {}  # 缓存已翻译的文本，减少API调用
        self.lock = threading.Lock()  # 线程锁，防止多线程同时访问缓存
        
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
            
        # 记录开始时间
        start_time = time.time()
        
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
            
            # 步骤5: 翻译非术语部分
            # 先翻译整个文本
            translated_text = self.translator.translate(preprocessed_text, dest=target_code).text
            if debug:
                print(f"步骤5 - 基础翻译: {translated_text}")
            
            # 步骤6: 还原术语占位符
            final_text = self.term_manager.restore_ham_radio_terms(translated_text, replacements)
            if debug:
                print(f"步骤6 - 术语还原: {final_text}")
            
            # 步骤7: 再次翻译，确保所有内容都被翻译
            if target_code == "zh-cn":
                # 提取所有英文单词
                english_words = re.findall(r'\b[a-zA-Z]+\b', final_text)
                if english_words:
                    # 翻译剩余的英文内容
                    remaining_text = " ".join(english_words)
                    translated_remaining = self.translator.translate(remaining_text, dest=target_code).text
                    
                    # 替换英文单词为翻译后的内容
                    for word in english_words:
                        if word.lower() in translated_remaining.lower():
                            final_text = final_text.replace(word, translated_remaining)
            
            # 计算翻译延迟
            end_time = time.time()
            self.translation_delay = int((end_time - start_time) * 1000)
            
            return final_text
            
        except Exception as e:
            if debug:
                print(f"翻译过程出错: {str(e)}")
                import traceback
                traceback.print_exc()
            # 发生错误时返回原文
            return text
    
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