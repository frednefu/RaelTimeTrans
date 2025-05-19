from googletrans import Translator
import time
import threading

class SubtitleManager:
    def __init__(self):
        self.translator = Translator()
        self.translation_cache = {}  # 缓存已翻译的文本，减少API调用
        self.lock = threading.Lock()  # 线程锁，防止多线程同时访问缓存
        
        # 翻译延迟计时
        self.translation_delay = 0  # 翻译延迟（毫秒）
        
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
    
    def translate(self, text, target_language):
        """
        将文本翻译成目标语言
        
        参数:
            text (str): 要翻译的文本
            target_language (str): 目标语言名称（如中文、英语等）
            
        返回:
            str: 翻译后的文本
        """
        if not text:
            return ""
            
        # 如果目标语言是"不翻译"，直接返回原文
        if target_language == "不翻译":
            # 设置延迟为0，因为没有实际翻译
            self.translation_delay = 0
            return text
        
        # 开始计时
        start_time = time.time()
        
        # 获取目标语言代码
        target_code = self.language_map.get(target_language, "zh-cn")
        
        # 创建缓存键
        cache_key = f"{text}_{target_code}"
        
        # 检查缓存中是否有此翻译
        with self.lock:
            if cache_key in self.translation_cache:
                # 使用缓存时，翻译延迟很小
                self.translation_delay = 1
                return self.translation_cache[cache_key]
        
        try:
            # 调用Google翻译API
            translation = self.translator.translate(text, dest=target_code)
            
            # 获取翻译后的文本
            translated_text = translation.text
            
            # 计算翻译延迟
            end_time = time.time()
            self.translation_delay = int((end_time - start_time) * 1000)
            
            # 缓存翻译结果
            with self.lock:
                self.translation_cache[cache_key] = translated_text
            
            return translated_text
        
        except Exception as e:
            print(f"翻译错误: {e}")
            # 出错时返回原文
            self.translation_delay = 0
            return text
    
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