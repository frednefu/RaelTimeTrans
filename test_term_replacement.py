import unittest
from translation.term_manager import TermManager

class TestTermReplacement(unittest.TestCase):
    """测试术语替换功能"""
    
    def setUp(self):
        """初始化测试环境"""
        self.term_manager = TermManager()
    
    def test_multiple_term_replacement(self):
        """测试多次术语替换"""
        # 创建测试用的替换字典
        replacements = {
            "__TERM_0__": "QRZ（谁在呼叫我）",
            "__TERM_1__": "呼叫"
        }
        
        # 测试用例：多个占位符，包括标准和变形格式
        test_cases = [
            # 输入文本, 期望输出
            ("__TERM_0__? 谁在__TERM_1__?", "QRZ（谁在呼叫我）? 谁在呼叫?"),
            ("__term_0__？谁是__term_1__？", "QRZ（谁在呼叫我）？谁是呼叫？"),
            ("__TERM_0____TERM_1__", "QRZ（谁在呼叫我）呼叫"),
            ("请问__term_0__？谁在__term_1__？", "请问QRZ（谁在呼叫我）？谁在呼叫？")
        ]
        
        for text, expected in test_cases:
            result = self.term_manager.restore_ham_radio_terms(text, replacements)
            self.assertEqual(result, expected, f"Failed for input: '{text}'")
        
        # 特殊格式的测试用例：带有下划线结尾的占位符
        special_cases = [
            # 输入文本, 期望结果的部分内容
            ("__ term_0__？谁是__TERM_1_？", ["QRZ（谁在呼叫我）", "呼叫"])
        ]
        
        for text, expected_parts in special_cases:
            result = self.term_manager.restore_ham_radio_terms(text, replacements)
            for part in expected_parts:
                self.assertIn(part, result, f"Failed for input: '{text}', missing '{part}'")
    
    def test_nested_term_replacement(self):
        """测试嵌套术语替换"""
        # 创建一个可能导致嵌套占位符的替换字典
        replacements = {
            "__TERM_0__": "CQ（呼叫__TERM_1__）",
            "__TERM_1__": "所有电台"
        }
        
        test_cases = [
            # 输入文本, 期望输出
            ("这是__TERM_0__测试", "这是CQ（呼叫所有电台）测试"),
            ("__TERM_0____TERM_1__", "CQ（呼叫所有电台）所有电台"),
        ]
        
        for text, expected in test_cases:
            result = self.term_manager.restore_ham_radio_terms(text, replacements)
            self.assertEqual(result, expected, f"Failed for input: '{text}'")
    
    def test_term_replacement_edge_cases(self):
        """测试术语替换的边缘情况"""
        # 测试空字典
        text = "__TERM_0__"
        self.assertEqual(self.term_manager.restore_ham_radio_terms(text, {}), text)
        
        # 测试空文本
        self.assertEqual(self.term_manager.restore_ham_radio_terms("", {"__TERM_0__": "测试"}), "")
        
        # 测试没有占位符的文本
        text = "这是一个普通文本，没有占位符"
        self.assertEqual(
            self.term_manager.restore_ham_radio_terms(text, {"__TERM_0__": "测试"}), 
            text
        )

if __name__ == "__main__":
    unittest.main() 