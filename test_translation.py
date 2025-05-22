import os
import sys
import re
from translation.subtitle_manager import SubtitleManager

def is_callsign(text):
    """检查文本是否包含呼号"""
    # 检查标准呼号格式（大小写不敏感）
    if re.search(r'\b[A-Za-z0-9]{2,}[0-9][A-Za-z]{1,3}\b', text, re.IGNORECASE):
        return True
    # 检查简化呼号格式（2-3个字母）
    if re.search(r'\b[A-Za-z]{2,3}\b', text):
        return True
    # 检查字母解释法单词
    phonetic_words = ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf', 
                      'Hotel', 'India', 'Juliet', 'Kilo', 'Lima', 'Mike', 'November', 
                      'Oscar', 'Papa', 'Quebec', 'Romeo', 'Sierra', 'Tango', 'Uniform', 
                      'Victor', 'Whiskey', 'X-ray', 'Yankee', 'Zulu']
    pattern = '|'.join(phonetic_words)
    if re.search(r'\b(' + pattern + r')\b', text, re.IGNORECASE):
        return True
    return False

def test_translation():
    """测试翻译功能"""
    # 创建字幕管理器实例
    subtitle_manager = SubtitleManager()
    
    # 测试用例分类
    test_cases = {
        "基本术语测试": [
            "CQ CQ this is BG7YYK calling",
            "Roger, copy that",
            "QRZ? Who is calling?",
            "73, best regards",
        ],
        "信号报告测试": [
            "Your signal is five by nine",
            "Signal report five nine nine",
            "five nine and good signal",
            "Signal report five nine nine nine",
            "Your signal is five by nine plus",
        ],
        "呼号测试": [
            "This is Bravo Golf seven yankee yankee kilo",
            "Victor, Echo 5, Alpha, Alpha Echo",
            "This is Alpha Bravo Charlie Delta Echo",
            "This is X-ray Yankee Zulu",
        ],
        "字母解释法单词翻译测试": [
            "I play Golf every weekend",  # 单个字母解释法单词不应被转换为字母
            "Alpha is the first letter in Greek alphabet",  # 单个字母解释法单词不应被转换为字母
            "Bravo for your outstanding performance",  # 单个字母解释法单词不应被转换为字母
            "This is Bravo Golf seven yankee yankee kilo calling",  # 连续的字母解释法单词应被转换为呼号
            "Contact Alpha Bravo Control immediately",  # 连续的字母解释法单词应被转换为呼号
            "The Golf course is beautiful, and Bravo Charlie Delta is my call sign"  # 混合情况
        ],
        "组合测试": [
            "CQ CQ this is BG7YYK calling. Roger, your signal is five by nine",
            "QRZ? This is Victor Echo 5 Alpha Alpha Echo. Signal report five nine nine",
            "say 73 and I just may be listening.",
            "Roger, your signal is five by nine. Over.",
            "CQ CQ this is BG7YYK calling CQ CQ",
        ],
        "错误处理测试": [
            "",  # 空字符串
            "   ",  # 只有空格
            None,  # None值
            "!@#$%^&*()",  # 特殊字符
            "1234567890",  # 纯数字
        ]
    }
    
    # 目标语言
    target_languages = ["中文"]
    
    # 运行测试
    for language in target_languages:
        print(f"\n{language}翻译测试:\n")
        
        for category, cases in test_cases.items():
            print(f"\n{category}:")
            print("-" * 50)
            
            for text in cases:
                print(f"原文: {text}")
                try:
                    # 使用SubtitleManager的translate方法进行翻译
                    translation = subtitle_manager.translate(text, language, debug=True)
                    print(f"译文: {translation}")
                    
                    # 基本验证
                    if text and isinstance(text, str):
                        # 检查呼号处理
                        has_callsign = is_callsign(text)
                        # 如果是字母解释法单词测试或呼号测试，不进行严格验证
                        if category in ["字母解释法单词翻译测试", "呼号测试"]:
                            # 对于连续的字母解释法单词，检查是否有大写字母组合
                            if has_callsign and len(re.findall(r'\b[A-Z]{2,}\b', text)) > 0:
                                # 应该在翻译中找到大写字母组合
                                assert re.search(r'\b[A-Z0-9]{2,}\b', translation) is not None, "连续字母解释法未被正确转换为呼号"
                        
                        # 验证信号报告是否被正确转换
                        if "five by nine" in text.lower():
                            assert "59" in translation, "信号报告未被正确转换"
                        
                        # 验证特殊术语是否被正确翻译
                        if "CQ" in text:
                            if language == "中文":
                                assert "CQ" in translation, "CQ术语未被正确保留"
                            else:
                                assert "CQ" in translation, "CQ术语未被正确保留"
                        
                        # 验证73是否被正确翻译
                        if "73" in text:
                            if language == "中文":
                                assert "73" in translation, "73术语未被正确保留"
                            else:
                                assert "73" in translation, "73术语未被正确保留"
                        
                        # 验证Roger是否被正确翻译
                        if "Roger" in text:
                            if language == "中文":
                                assert "收到" in translation or "明白" in translation, "Roger术语未被正确翻译"
                            else:
                                assert "Roger" in translation, "Roger术语未被正确保留"
                    
                except Exception as e:
                    print(f"测试失败: {str(e)}")
                    import traceback
                    traceback.print_exc()
                
                print("-" * 50)
    
    print("\n测试完成!")

if __name__ == "__main__":
    test_translation() 