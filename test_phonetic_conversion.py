import unittest
from translation.term_manager import TermManager

class TestPhoneticConversion(unittest.TestCase):
    """测试字母解释法转换功能"""
    
    def setUp(self):
        """初始化测试环境"""
        self.term_manager = TermManager()
    
    def test_single_phonetic_words(self):
        """测试单个字母解释法单词不转换"""
        test_cases = [
            "I play Golf every weekend",
            "The Alpha version is not stable",
            "He is a Bravo soldier",
            "This is a Delta class ship",
            "We need more Uniform personnel"
        ]
        
        for text in test_cases:
            result = self.term_manager.extract_and_convert_phonetic_callsign(text)
            # 单个字母解释法词不应被转换
            self.assertEqual(text, result)
            
    def test_consecutive_phonetic_words(self):
        """测试连续的字母解释法单词转换为呼号"""
        test_cases = [
            # 测试文本, 期望结果
            ("This is Bravo Golf Two Alpha Yankee Kilo", "This is BG2AYK"),
            ("My callsign is Alpha Bravo Charlie", "My callsign is ABC"),
            ("Contact Victor Echo Three Foxtrot Oscar", "Contact VE3FO"),
            ("The ship Sierra Tango Echo Papa", "The ship STEP"),
            ("Call sign Bravo Golf Seven X-ray Yankee Kilo", "Call sign BG7XYK")
        ]
        
        for text, expected in test_cases:
            result = self.term_manager.extract_and_convert_phonetic_callsign(text)
            self.assertEqual(result, expected)
    
    def test_mixed_phonetic_words(self):
        """测试混合场景：包含单个和连续的字母解释法单词"""
        test_cases = [
            # 测试文本, 期望结果
            ("Alpha is the first letter, Bravo Charlie is a call sign", 
             "Alpha is the first letter, BC is a call sign"),
            ("I play Golf but my callsign is Uniform Sierra Alpha", 
             "I play Golf but my callsign is USA"),
            ("Sierra is for rescue, Lima Oscar Victor Echo is our team", 
             "Sierra is for rescue, LOVE is our team"),
            ("We use Foxtrot for clarity, but Alpha Bravo is our code", 
             "We use Foxtrot for clarity, but AB is our code"),
            ("Golf sport is different from Golf Uniform call sign", 
             "Golf sport is different from GU call sign")
        ]
        
        for text, expected in test_cases:
            result = self.term_manager.extract_and_convert_phonetic_callsign(text)
            self.assertEqual(result, expected)
    
    def test_convert_phonetic_callsign_method(self):
        """测试convert_phonetic_callsign方法"""
        test_cases = [
            # 测试文本, 期望结果
            ("bravo golf two alpha yankee kilo", "BG2AYK"),
            ("alpha is first letter", "alpha is first letter"),
            ("alpha bravo charlie delta", "ABCD"),
            ("golf is a sport but golf uniform is GU", "golf is a sport but GU is gu")
        ]
        
        for text, expected in test_cases:
            result = self.term_manager.convert_phonetic_callsign(text)
            self.assertEqual(result, expected)
    
    def test_edge_cases(self):
        """测试边缘情况"""
        # 空字符串
        self.assertEqual(self.term_manager.extract_and_convert_phonetic_callsign(""), "")
        self.assertEqual(self.term_manager.convert_phonetic_callsign(""), "")
        
        # 无字母解释法单词
        text = "This is a regular sentence without phonetic alphabet."
        self.assertEqual(self.term_manager.extract_and_convert_phonetic_callsign(text), text)
        
        # 只有一个字母解释法单词在句子开头
        text = "Bravo for your performance!"
        self.assertEqual(self.term_manager.extract_and_convert_phonetic_callsign(text), text)
        
        # 只有一个字母解释法单词在句子结尾
        text = "He deserves a Bravo"
        self.assertEqual(self.term_manager.extract_and_convert_phonetic_callsign(text), text)
        
        # 多个单独的字母解释法单词
        text = "Alpha team and Bravo team will work with Delta force"
        self.assertEqual(self.term_manager.extract_and_convert_phonetic_callsign(text), text)

if __name__ == "__main__":
    unittest.main() 