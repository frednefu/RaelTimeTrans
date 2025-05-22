import os
import json
import re
import uuid

class TermManager:
    """业余无线电术语管理器，用于处理自定义术语翻译"""
    
    def __init__(self):
        # 术语词典，格式为 {术语: {翻译目标语言代码: 翻译文本}}
        self.terms = {}
        # 正则表达式模式，用于匹配术语
        self.patterns = {}
        # 按照术语长度排序的术语列表，优先匹配较长的术语
        self.sorted_terms = []
        # 资源文件路径
        self.resource_dir = "translation/resources"
        self.term_file = os.path.join(self.resource_dir, "ham_radio_terms.json")
        
        # 确保资源目录存在
        self._ensure_resource_dir()
        # 加载术语资源
        self.load_terms()
    
    def _ensure_resource_dir(self):
        """确保资源目录存在"""
        if not os.path.exists(self.resource_dir):
            os.makedirs(self.resource_dir)
            print(f"创建术语资源目录: {self.resource_dir}")
    
    def load_terms(self, verbose=False):
        """从JSON文件加载术语定义"""
        if not os.path.exists(self.term_file):
            if verbose:
                print(f"术语定义文件 {self.term_file} 不存在，将创建默认术语")
            self._create_default_terms()
            return
        
        try:
            # 读取术语文件
            with open(self.term_file, 'r', encoding='utf-8') as f:
                self.terms = json.load(f)
            
            # 验证和处理术语
            valid_terms = {}
            invalid_terms = []
            
            for term, translations in self.terms.items():
                # 确保术语不为空且包含至少一种语言的翻译
                if term and isinstance(translations, dict) and any(lang in translations for lang in ['zh-cn', 'en']):
                    valid_terms[term] = translations
                else:
                    invalid_terms.append(term)
            
            # 如果有无效术语，更新术语词典并保存
            if invalid_terms and verbose:
                print(f"警告: 忽略了 {len(invalid_terms)} 个无效术语: {', '.join(invalid_terms)}")
                self.terms = valid_terms
                self.save_terms()
            
            # 按照术语长度从长到短排序，确保首先匹配最长的术语
            self.sorted_terms = sorted(self.terms.keys(), key=len, reverse=True)
            
            # 为每个术语创建正则表达式模式
            for term in self.sorted_terms:
                # 创建匹配完整词的正则表达式
                pattern = r'\b' + re.escape(term) + r'\b'
                self.patterns[term] = re.compile(pattern, re.IGNORECASE)
            
            if verbose:
                term_count = len(self.terms)    
                print(f"从 {self.term_file} 加载了 {term_count} 个业余无线电术语")
            
            # 检查是否包含关键术语
            key_terms = ['CQ', 'Roger', 'QRZ', '73']
            missing_terms = [term for term in key_terms if term not in self.terms]
            if missing_terms and verbose:
                print(f"警告: 术语文件缺少以下关键术语: {', '.join(missing_terms)}")
                print(f"建议编辑 {self.term_file} 添加这些术语")
                
        except json.JSONDecodeError as e:
            if verbose:
                print(f"术语文件 {self.term_file} 格式无效: {str(e)}")
                print(f"将创建新的默认术语文件")
            self._create_default_terms()
        except Exception as e:
            if verbose:
                print(f"加载术语文件时出错: {str(e)}")
                print(f"将使用默认术语")
            self._create_default_terms()
    
    def _create_default_terms(self, verbose=False):
        """创建默认的术语定义文件"""
        # 仅包含几个基本术语的最小集合，仅在JSON文件不存在时使用
        default_terms = {
            "CQ": {
                "zh-cn": "CQ（通用呼叫）",
                "en": "CQ (general call)",
                "description": "用于呼叫任何电台"
            },
            "QRZ": {
                "zh-cn": "QRZ（谁在呼叫我）",
                "en": "QRZ (who is calling me)",
                "description": "询问谁在呼叫"
            },
            "73": {
                "zh-cn": "73（最好的祝福）",
                "en": "73 (best regards)",
                "description": "表示最好的祝福，通常用于通信结束时"
            },
            "Roger": {
                "zh-cn": "收到，明白",
                "en": "Roger, understood",
                "description": "表示已经收到并理解信息"
            }
        }
        
        try:
            with open(self.term_file, 'w', encoding='utf-8') as f:
                json.dump(default_terms, f, ensure_ascii=False, indent=4)
            
            self.terms = default_terms
            self.sorted_terms = sorted(self.terms.keys(), key=len, reverse=True)
            
            # 为每个术语创建正则表达式模式
            for term in self.sorted_terms:
                pattern = r'\b' + re.escape(term) + r'\b'
                self.patterns[term] = re.compile(pattern, re.IGNORECASE)
                
            if verbose:
                print(f"创建了默认术语定义文件: {self.term_file}")
                print(f"注意: 这只是基本术语。请根据需要编辑 {self.term_file} 添加更多术语。")
        except Exception as e:
            if verbose:
                print(f"创建默认术语文件时出错: {str(e)}")
    
    def extract_and_convert_signal_report(self, text):
        """
        识别并将信号报告（如five nine、five nine nine、599、59、54等）统一转换为阿拉伯数字。
        例如：'five nine nine' -> '599', 'five nine' -> '59', 'five four' -> '54'
        以及 'five by nine' -> '59'
        """
        if not text:
            return text
            
        # 支持的数字单词
        num_map = {
            'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
            'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'
        }
        
        # 预处理：将 "five by nine" 这样的格式替换为 "five nine"
        pattern = r'\b(zero|one|two|three|four|five|six|seven|eight|nine)\s+by\s+(zero|one|two|three|four|five|six|seven|eight|nine)\b'
        text = re.sub(pattern, r'\1 \2', text, flags=re.IGNORECASE)
        
        # 将文本分割成单词
        words = text.lower().split()
        result = []
        i = 0
        
        while i < len(words):
            # 检查是否为信号报告的数字单词序列
            if words[i] in num_map:
                digits = []
                j = i
                # 收集连续的数字单词
                while j < len(words) and words[j] in num_map and len(digits) < 3:
                    digits.append(num_map[words[j]])
                    j += 1
                
                # 如果收集到至少两个数字，则视为信号报告
                if len(digits) >= 2:
                    result.append(''.join(digits))
                    i = j
                    continue
            
            # 如果不是信号报告的一部分，保持原样
            result.append(words[i])
            i += 1
        
        return ' '.join(result)

    def preprocess_phonetic_callsign(self, text):
        """
        预处理字母解释法呼号，特别处理带有逗号和额外空格的情况
        
        参数:
            text (str): 原始文本
            
        返回:
            str: 预处理后的文本
        """
        if not text:
            return text
            
        # 定义字母解释法映射，仅用于检测
        phonetic_words = [
            'alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel',
            'india', 'juliet', 'kilo', 'lima', 'mike', 'november', 'oscar', 'papa',
            'quebec', 'romeo', 'sierra', 'tango', 'uniform', 'victor', 'whiskey', 
            'x-ray', 'xray', 'yankee', 'zulu'
        ]
        
        result = text
        
        # 正则表达式：匹配连续的字母解释法单词（可能有逗号分隔）
        # 例如: "Victor, Echo, 5, Alpha, Echo" 或 "Alpha Bravo"
        phonetic_pattern = r'(?:' + '|'.join(phonetic_words) + r')(?:,?\s+(?:' + '|'.join(phonetic_words) + r'|\d+))+' 
        
        # 查找所有可能的呼号段
        matches = re.finditer(phonetic_pattern, text, re.IGNORECASE)
        
        for match in matches:
            callsign_segment = match.group(0)
            # 去掉逗号，保持空格
            cleaned_segment = re.sub(r',\s*', ' ', callsign_segment)
            result = result.replace(callsign_segment, cleaned_segment)
        
        # 检测并清理类似于 "Alpha, Bravo" 的模式（只有一个逗号）
        comma_pattern = r'(?:' + '|'.join(phonetic_words) + r'),\s+(?:' + '|'.join(phonetic_words) + r')'
        comma_matches = re.finditer(comma_pattern, result, re.IGNORECASE)
        
        for match in comma_matches:
            comma_segment = match.group(0)
            # 去掉逗号，保持空格
            cleaned_segment = re.sub(r',\s*', ' ', comma_segment)
            result = result.replace(comma_segment, cleaned_segment)
        
        return result

    def extract_and_convert_phonetic_callsign(self, text):
        """
        提取并转换字母解释法呼号，仅在连续出现两个或以上的字母解释法单词时才进行转换
        
        参数:
            text (str): 输入文本
            
        返回:
            str: 处理后的文本
        """
        if not text:
            return text
            
        # 定义字母解释法映射
        phonetic_map = {
            'alpha': 'A', 'bravo': 'B', 'charlie': 'C', 'delta': 'D',
            'echo': 'E', 'foxtrot': 'F', 'golf': 'G', 'hotel': 'H',
            'india': 'I', 'juliet': 'J', 'kilo': 'K', 'lima': 'L',
            'mike': 'M', 'november': 'N', 'oscar': 'O', 'papa': 'P',
            'quebec': 'Q', 'romeo': 'R', 'sierra': 'S', 'tango': 'T',
            'uniform': 'U', 'victor': 'V', 'whiskey': 'W', 'x-ray': 'X',
            'yankee': 'Y', 'zulu': 'Z',
            # 添加数字词映射
            'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
            'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'
        }
        
        # 预处理：处理带有逗号和额外空格的字母解释法词
        processed_text = self.preprocess_phonetic_callsign(text)
        
        # 将文本分割成单词
        words = processed_text.split()
        result = []
        i = 0
        
        # 简化版本：只处理连续的字母解释法单词
        while i < len(words):
            word = words[i].lower()
            
            # 检查是否是字母解释法单词
            if word in phonetic_map:
                # 查找连续的字母解释法单词
                j = i + 1
                consecutive_count = 1
                callsign_parts = [phonetic_map[word]]
                
                while j < len(words) and words[j].lower() in phonetic_map:
                    callsign_parts.append(phonetic_map[words[j].lower()])
                    consecutive_count += 1
                    j += 1
                
                # 仅当连续出现两个或以上的字母解释法单词时才转换
                if consecutive_count >= 2:
                    # 组合成呼号并添加到结果中
                    callsign = ''.join(callsign_parts).upper()  # 确保呼号为大写
                    result.append(callsign)
                    i = j  # 跳过已处理的单词
                else:
                    # 单独的字母解释法单词保持原样
                    result.append(words[i])
                    i += 1
                continue
            
            # 检查是否是标准呼号格式(使其大写)
            if re.match(r'^[A-Z0-9]{2,}[0-9][A-Z]{1,3}$', words[i], re.IGNORECASE):
                result.append(words[i].upper())
                i += 1
                continue
            
            # 如果不是呼号相关，保持原样
            result.append(words[i])
            i += 1
        
        return ' '.join(result)

    def translate_terms(self, text, target_lang_code=None):
        """
        将文本中的术语替换为目标语言的翻译
        
        参数:
            text (str): 原始文本
            target_lang_code (str): 目标语言代码 (如 'zh-cn', 'en')
            
        返回:
            str: 替换术语后的文本
        """
        if not text:
            return text
        
        # 如果没有指定目标语言，使用默认语言
        if not target_lang_code:
            target_lang_code = "zh-cn"
        
        # 规范化目标语言代码
        if target_lang_code.lower() == "zh-cn":
            target_lang_code = "zh-cn"
        else:
            # 只保留主要部分，如"en-US" -> "en"
            target_lang_code = target_lang_code.split('-')[0].lower()
        
        # 如果没有术语，则返回原文
        if not self.terms:
            return text
        
        # 处理业余无线电术语
        words = text.split()
        translated_words = []
        
        for word in words:
            # 检查是否是呼号（全大写字母和数字组成）
            if re.match(r'^[A-Z0-9]+$', word):
                translated_words.append(word)  # 呼号直接保留
            else:
                # 非呼号部分，检查是否是特定术语
                translated = False
                for term in self.sorted_terms:
                    if term.lower() == word.lower():
                        translation = self.terms[term].get(target_lang_code, term)
                        translated_words.append(translation)
                        translated = True
                        break
                
                # 如果不是特定术语，直接添加
                if not translated:
                    translated_words.append(word)
        
        result = ' '.join(translated_words)
        
        # 处理特殊术语组合，比如 "please. roger" -> "请。收到，明白"
        for term in self.sorted_terms:
            # 对于大写或首字母大写的术语，使用大小写不敏感的正则表达式
            pattern = r'\b' + re.escape(term) + r'\b'
            if term in self.terms and target_lang_code in self.terms[term]:
                translation = self.terms[term][target_lang_code]
                result = re.sub(pattern, translation, result, flags=re.IGNORECASE)
            
        return result

    def translate_text(self, text, target_lang_code):
        """
        翻译文本，包括普通文本和术语
        
        参数:
            text (str): 原始文本
            target_lang_code (str): 目标语言代码 (如 'zh-cn', 'en')
            
        返回:
            str: 翻译后的文本
        """
        # 先进行术语和呼号的处理
        processed_text = self.translate_terms(text, target_lang_code)
        
        # 这里应该调用翻译API进行普通文本翻译
        # 暂时返回处理后的文本
        return processed_text
    
    def add_term(self, term, translations):
        """
        添加或更新术语及其翻译
        
        参数:
            term (str): 术语 (如 "CQ")
            translations (dict): 翻译字典 {语言代码: 翻译文本}
        """
        # 确保术语是大写的
        term = term.upper()
        
        # 更新术语词典
        if term in self.terms:
            # 更新现有术语的翻译
            self.terms[term].update(translations)
        else:
            # 添加新术语
            self.terms[term] = translations
            # 更新排序的术语列表
            self.sorted_terms = sorted(self.terms.keys(), key=len, reverse=True)
            # 创建正则表达式模式
            pattern = r'\b' + re.escape(term) + r'\b'
            self.patterns[term] = re.compile(pattern, re.IGNORECASE)
        
        # 保存到文件
        self.save_terms()
    
    def remove_term(self, term):
        """
        删除术语
        
        参数:
            term (str): 要删除的术语
        """
        term = term.upper()
        if term in self.terms:
            del self.terms[term]
            if term in self.patterns:
                del self.patterns[term]
            self.sorted_terms = sorted(self.terms.keys(), key=len, reverse=True)
            self.save_terms()
    
    def save_terms(self, verbose=False):
        """保存术语到JSON文件"""
        try:
            with open(self.term_file, 'w', encoding='utf-8') as f:
                json.dump(self.terms, f, ensure_ascii=False, indent=4)
            if verbose:
                print(f"保存术语定义到: {self.term_file}")
        except Exception as e:
            if verbose:
                print(f"保存术语文件时出错: {str(e)}")

    def convert_phonetic_callsign(self, text):
        """
        将字母解释法呼号转换为标准呼号，仅在连续出现两个或以上的字母解释法单词时才进行转换。
        例如：'Bravo Golf two alpha yankee kilo' -> 'BG2AYK'，但单独的'Golf'或'Alpha'保持不变
        """
        if not text:
            return text
            
        phonetic_map = {
            'alpha': 'A', 'bravo': 'B', 'charlie': 'C', 'delta': 'D', 'echo': 'E',
            'foxtrot': 'F', 'golf': 'G', 'hotel': 'H', 'india': 'I', 'juliet': 'J',
            'kilo': 'K', 'lima': 'L', 'mike': 'M', 'november': 'N', 'oscar': 'O',
            'papa': 'P', 'quebec': 'Q', 'romeo': 'R', 'sierra': 'S', 'tango': 'T',
            'uniform': 'U', 'victor': 'V', 'whiskey': 'W', 'xray': 'X', 'yankee': 'Y',
            'zulu': 'Z', 'zero': '0', 'one': '1', 'two': '2', 'three': '3',
            'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'
        }
        
        # 将文本分割成单词
        words = text.lower().split()
        result = []
        i = 0
        
        # 简化版本：只处理连续的字母解释法单词，避免可能的无限循环
        while i < len(words):
            word = words[i]
            
            # 检查当前单词是否是字母解释法
            if word in phonetic_map:
                # 寻找连续的字母解释法单词
                j = i + 1
                consecutive_count = 1
                phonetic_sequence = [phonetic_map[word]]
                
                while j < len(words) and words[j] in phonetic_map:
                    phonetic_sequence.append(phonetic_map[words[j]])
                    consecutive_count += 1
                    j += 1
                
                # 仅当连续出现两个或以上的字母解释法单词时才转换
                if consecutive_count >= 2:
                    callsign = ''.join(phonetic_sequence).upper()
                    result.append(callsign)
                    i = j  # 跳过已处理的单词
                else:
                    # 单独的字母解释法单词保持原样
                    result.append(word)
                    i += 1
            else:
                # 其他单词直接添加
                result.append(word)
                i += 1
        
        return ' '.join(result)

    def direct_translate(self, text, target_language):
        """直接翻译特殊术语"""
        if not text:
            return text
        terms = self.terms
        if not terms:
            return text
        # 获取目标语言的术语映射
        # 兼容zh-cn/en等
        lang_code = target_language.lower()
        if lang_code.startswith('zh'):
            lang_code = 'zh-cn'
        elif lang_code.startswith('en'):
            lang_code = 'en'
        # 将文本分割成单词
        words = text.split()
        result = []
        for word in words:
            key = word.upper()
            if key in terms and lang_code in terms[key]:
                result.append(terms[key][lang_code])
            else:
                result.append(word)
        return ' '.join(result)

    def preprocess_ham_radio_terms(self, text, target_language):
        """预处理业余无线电术语"""
        if not text:
            return text, {}
        terms = self.terms
        if not terms:
            return text, {}
        lang_code = target_language.lower()
        if lang_code.startswith('zh'):
            lang_code = 'zh-cn'
        elif lang_code.startswith('en'):
            lang_code = 'en'
        replacements = {}
        processed_text = text
        for term, translations in terms.items():
            if lang_code in translations:
                translation = translations[lang_code]
                pattern = r'\b' + re.escape(term) + r'\b'
                if re.search(pattern, processed_text, re.IGNORECASE):
                    placeholder = f"__TERM_{len(replacements)}__"
                    replacements[placeholder] = translation
                    processed_text = re.sub(pattern, placeholder, processed_text, flags=re.IGNORECASE)
        return processed_text, replacements

    def restore_ham_radio_terms(self, text, replacements):
        """还原业余无线电术语"""
        if not text or not replacements:
            return text
            
        result = text
        
        # 按占位符长度降序排序，避免部分替换问题
        sorted_placeholders = sorted(replacements.keys(), key=len, reverse=True)
        
        # 设置最大迭代次数，避免可能的无限循环
        max_iterations = 3
        iterations = 0
        
        # 迭代处理，直到所有占位符都被替换完毕或达到最大迭代次数
        while iterations < max_iterations:
            iterations += 1
            replaced = False
            
            # 先处理精确匹配的占位符
            for placeholder in sorted_placeholders:
                replacement = replacements[placeholder]
                original_result = result
                
                # 使用正则表达式进行精确匹配替换，确保只替换完整的占位符
                pattern = re.compile(re.escape(placeholder), re.IGNORECASE)
                result = pattern.sub(replacement, result)
                
                if result != original_result:
                    replaced = True
            
            # 处理带变形的占位符
            for placeholder in sorted_placeholders:
                replacement = replacements[placeholder]
                placeholder_id = placeholder.replace("__TERM_", "").replace("__", "")
                
                # 处理各种变形格式
                patterns = [
                    # 处理带空格的占位符形式 (__TERM_0__)
                    r'__\s*TERM_' + re.escape(placeholder_id) + r'\s*__',
                    # 处理小写的变形 (__term_0__)
                    r'__\s*term_' + re.escape(placeholder_id) + r'\s*__',
                    # 处理带下划线的变形格式 (__TERM_0_)
                    r'__\s*TERM_' + re.escape(placeholder_id) + r'_',
                ]
                
                for pattern_str in patterns:
                    original_result = result
                    pattern = re.compile(pattern_str, re.IGNORECASE)
                    
                    # 如果是带下划线的格式，需要特殊处理
                    if pattern_str.endswith('_'):
                        matches = pattern.finditer(result)
                        for match in matches:
                            # 替换并保留下划线
                            result = result[:match.start()] + replacement + '_' + result[match.end():]
                    else:
                        result = pattern.sub(replacement, result)
                    
                    if result != original_result:
                        replaced = True
            
            # 如果本次迭代没有进行任何替换，说明所有占位符已经替换完毕，退出循环
            if not replaced:
                break
        
        return result

    def open_term_file(self):
        """
        打开术语定义文件进行编辑
        
        返回:
            bool: 是否成功打开文件
        """
        if not os.path.exists(self.term_file):
            print(f"术语文件不存在: {self.term_file}")
            self._create_default_terms()
        
        try:
            # 根据不同操作系统使用不同的命令打开文件
            import subprocess
            import platform
            
            system = platform.system()
            if system == "Windows":
                os.startfile(self.term_file)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", self.term_file])
            else:  # Linux
                subprocess.run(["xdg-open", self.term_file])
                
            print(f"已打开术语文件进行编辑: {self.term_file}")
            print("编辑完成后请保存，程序将在下次启动时加载更新后的术语。")
            return True
        except Exception as e:
            print(f"打开术语文件失败: {str(e)}")
            print(f"请手动打开并编辑文件: {os.path.abspath(self.term_file)}")
            return False
    
    def reload_terms(self):
        """
        重新加载术语定义
        
        返回:
            bool: 是否成功重新加载
        """
        try:
            # 备份当前术语以防加载失败
            old_terms = self.terms.copy()
            old_sorted_terms = self.sorted_terms.copy()
            old_patterns = self.patterns.copy()
            
            # 重新加载术语
            self.terms = {}
            self.sorted_terms = []
            self.patterns = {}
            self.load_terms()
            
            if not self.terms:
                # 加载失败，还原备份
                self.terms = old_terms
                self.sorted_terms = old_sorted_terms
                self.patterns = old_patterns
                print("重新加载术语失败，已还原为之前的术语定义。")
                return False
                
            print(f"已重新加载 {len(self.terms)} 个术语。")
            return True
        except Exception as e:
            print(f"重新加载术语时出错: {str(e)}")
            return False 